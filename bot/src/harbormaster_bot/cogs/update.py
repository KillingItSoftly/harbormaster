from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from ..auth import requires
from ..azure_client import AzureClient
from ..views import ConfirmView


class Update(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.azure: AzureClient = bot.azure  # type: ignore[attr-defined]

    update = app_commands.Group(name="update", description="Steam update operations")

    @update.command(name="check", description="Check Steam for available updates.")
    @requires("player")
    async def check(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        wrapper = f"Check-{self.bot.config.game.name}Update.ps1"  # type: ignore[attr-defined]
        result = await self.azure.invoke_wrapper(wrapper)
        text = result.best_text[-1800:] or "(no output)"
        await interaction.followup.send(f"```\n{text}\n```")

    @update.command(
        name="apply",
        description="Snapshot then apply available update (admin).",
    )
    @requires("admin")
    async def apply(self, interaction: discord.Interaction) -> None:
        view = ConfirmView(interaction.user.id)
        await interaction.response.send_message(
            ":warning: Apply Steam update now? Server will be briefly stopped.",
            view=view,
            ephemeral=True,
        )
        await view.wait()
        if not view.confirmed:
            await interaction.followup.send("Aborted.", ephemeral=True)
            return
        await interaction.followup.send("Applying update… this may take several minutes.")
        wrapper = f"Check-{self.bot.config.game.name}Update.ps1"  # type: ignore[attr-defined]
        result = await self.azure.invoke_wrapper(wrapper, "-ApplyUpdate")
        if result.succeeded:
            tail = "\n".join(result.stdout.strip().splitlines()[-15:]) or "(done)"
            await interaction.followup.send(
                f":white_check_mark: Update finished.\n```\n{tail}\n```"
            )
        else:
            err = result.best_text[-1500:] or "(no output)"
            await interaction.followup.send(f":x: Update failed.\n```\n{err}\n```")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Update(bot))
