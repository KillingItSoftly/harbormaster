from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from ..auth import requires
from ..azure_client import AzureClient
from ..views import ConfirmView


class Server(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.azure: AzureClient = bot.azure  # type: ignore[attr-defined]

    server = app_commands.Group(name="server", description="Game server controls")

    @server.command(name="status", description="Show VM power state and basic info.")
    @requires("player")
    async def status(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        state = await self.azure.power_state()
        embed = discord.Embed(
            title=f"{self.bot.config.game.name} status",  # type: ignore[attr-defined]
            color=0x5865F2,
        )
        embed.add_field(name="Power", value=f"`{state}`", inline=True)
        embed.add_field(
            name="VM",
            value=self.bot.config.azure.vm_name,  # type: ignore[attr-defined]
            inline=True,
        )
        await interaction.followup.send(embed=embed)

    @server.command(name="start", description="Start the VM.")
    @requires("player")
    async def start(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        state = await self.azure.power_state()
        if state == "running":
            await interaction.followup.send("VM is already running.")
            return
        await interaction.followup.send("Starting VM… (this can take a minute)")
        await self.azure.start_vm()
        await interaction.followup.send(
            f":white_check_mark: VM started by {interaction.user.mention}."
        )

    @server.command(name="stop", description="Deallocate the VM (admin).")
    @requires("admin")
    async def stop(self, interaction: discord.Interaction) -> None:
        view = ConfirmView(interaction.user.id)
        await interaction.response.send_message(
            ":warning: Deallocate the VM and disconnect all players?",
            view=view,
            ephemeral=True,
        )
        await view.wait()
        if not view.confirmed:
            await interaction.followup.send("Aborted.", ephemeral=True)
            return
        await interaction.followup.send("Deallocating VM…", ephemeral=True)
        await self.azure.deallocate_vm()
        await interaction.followup.send(
            f":white_check_mark: VM deallocated by {interaction.user.mention}."
        )

    @server.command(
        name="restart-service",
        description="Restart the NSSM-wrapped server service (admin).",
    )
    @requires("admin")
    async def restart_service(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        svc = self.bot.config.game.service_name  # type: ignore[attr-defined]
        result = await self.azure.run_powershell([
            f"Restart-Service '{svc}' -Force",
            "Start-Sleep -Seconds 5",
            f"(Get-Service '{svc}').Status",
        ])
        body = result.best_text or "(no output)"
        emoji = ":arrows_counterclockwise:" if result.succeeded else ":x:"
        await interaction.followup.send(f"{emoji} `{svc}`\n```\n{body[-1500:]}\n```")

    @server.command(name="logs", description="Tail the server log.")
    @app_commands.describe(lines="How many lines to return (1-50).")
    @requires("player")
    async def logs(self, interaction: discord.Interaction, lines: int = 20) -> None:
        lines = max(1, min(50, lines))
        await interaction.response.defer(thinking=True)
        log_path = self.bot.config.game.log_path  # type: ignore[attr-defined]
        result = await self.azure.run_powershell([
            f"if (Test-Path '{log_path}') {{ Get-Content -Path '{log_path}' -Tail {lines} }} "
            f"else {{ 'Log not found at {log_path}' }}",
        ])
        text = result.best_text or "(empty)"
        await interaction.followup.send(f"```\n{text[-1800:]}\n```")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Server(bot))
