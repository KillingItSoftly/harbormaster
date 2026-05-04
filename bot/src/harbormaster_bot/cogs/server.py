from __future__ import annotations

import time

import discord
from discord import app_commands
from discord.ext import commands

from ..audit import audit
from ..auth import requires
from ..azure_client import AzureClient
from ..checks import ensure_vm_running, progress_heartbeat, run_slot
from ..views import ConfirmView, confirm_prompt


class Server(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.azure: AzureClient = bot.azure  # type: ignore[attr-defined]

    server = app_commands.Group(name="server", description="Game server controls")

    @server.command(name="status", description="Show VM and service state.")
    @requires("player")
    async def status(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        cfg = self.bot.config  # type: ignore[attr-defined]
        vm = await self.azure.vm_status()
        embed = discord.Embed(
            title=f"{cfg.game.name} status",
            color=0x5865F2 if vm.power_state == "running" else 0x95A5A6,
        )
        embed.add_field(name="VM", value=cfg.azure.vm_name, inline=True)
        embed.add_field(name="Power", value=f"`{vm.power_state}`", inline=True)
        embed.add_field(name="Provisioning", value=f"`{vm.provisioning_state}`", inline=True)
        embed.add_field(name="VM Agent", value=f"`{vm.agent_status}`", inline=True)
        # Maintenance flag is local to the bot, not the VM.
        embed.add_field(
            name="Maintenance mode",
            value="**ON**" if self.bot.state.maintenance else "off",  # type: ignore[attr-defined]
            inline=True,
        )
        if vm.power_state == "running":
            svc = await self.azure.get_service_status(cfg.game.service_name)
            embed.add_field(name="Service", value=f"`{svc}`", inline=True)
        else:
            embed.add_field(name="Service", value="(VM off)", inline=True)
        await interaction.followup.send(embed=embed)

    @server.command(name="start", description="Start the VM.")
    @requires("player")
    async def start(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        state = await self.azure.power_state()
        if state == "running":
            await interaction.followup.send(":information_source: VM is already running.")
            return
        if state in {"starting"}:
            await interaction.followup.send(
                ":hourglass: VM is already starting — give it ~30s."
            )
            return
        if state in {"stopping", "deallocating"}:
            await interaction.followup.send(
                f":hourglass: VM is `{state}`. Wait for that to finish, then retry."
            )
            return
        await interaction.followup.send("Starting VM… (this can take a minute)")
        try:
            await self.azure.start_vm()
        except Exception as exc:  # noqa: BLE001
            await audit(
                self.bot, interaction, "vm start", success=False, detail=repr(exc)
            )
            raise
        await interaction.followup.send(
            f":white_check_mark: VM started by {interaction.user.mention}."
        )
        await audit(self.bot, interaction, "vm start", success=True)

    @server.command(name="stop", description="Deallocate the VM (admin).")
    @app_commands.describe(
        delay_minutes="Minutes to warn players in Discord before deallocating (0-30, default 5).",
        force="Stop even if players are reported online.",
    )
    @requires("admin")
    async def stop(
        self,
        interaction: discord.Interaction,
        delay_minutes: app_commands.Range[int, 0, 30] = 5,
        force: bool = False,
    ) -> None:
        cfg = self.bot.config  # type: ignore[attr-defined]

        # Refuse-with-active-players gate. Best-effort: if the player
        # probe isn't configured, or returns `unknown`, we DO NOT block —
        # silence is consent here, otherwise we'd permanently block stop
        # on games without a probe.
        if not force:
            try:
                wrapper = f"Get-{cfg.game.name}Players.ps1"
                probe = await self.azure.invoke_wrapper(wrapper, timeout_sec=60)
            except Exception:  # noqa: BLE001
                probe = None
            if probe is not None:
                from .players import parse_player_count
                count = parse_player_count(probe.stdout)
                if count is not None and count > 0:
                    await interaction.response.send_message(
                        f":no_entry: **{count}** player(s) currently online. "
                        "Re-invoke with `force:true` to stop anyway.",
                        ephemeral=True,
                    )
                    return

        warn_text = (
            f"Warn players for {delay_minutes} min, stop the service, then deallocate."
            if delay_minutes > 0
            else "Immediately deallocate (no warning)."
        )
        view = ConfirmView(interaction.user.id)
        await interaction.response.send_message(
            confirm_prompt(
                "Stop the game server",
                [
                    ("VM", cfg.azure.vm_name),
                    ("Service", cfg.game.service_name),
                    ("Plan", warn_text),
                    ("Force", str(force)),
                ],
            ),
            view=view,
            ephemeral=True,
        )
        await view.wait()
        if not view.confirmed:
            await interaction.followup.send("Aborted.", ephemeral=True)
            return

        async with run_slot(self.bot, interaction, "server stop") as ok:
            if not ok:
                return
            if delay_minutes > 0:
                state = await self.azure.power_state()
                if state != "running":
                    await interaction.followup.send(
                        f":information_source: VM is `{state}`; skipping shutdown warning and deallocating directly.",
                        ephemeral=True,
                    )
                else:
                    grace_seconds = delay_minutes * 60
                    wrapper = f"Announce-{cfg.game.name}Shutdown.ps1"
                    await interaction.followup.send(
                        f":hourglass: Posting warning, deallocating in **{delay_minutes} min**…",
                        ephemeral=True,
                    )
                    async with progress_heartbeat(
                        interaction, f"Warning players ({delay_minutes} min grace) + final backup"
                    ):
                        announce = await self.azure.invoke_wrapper(
                            wrapper,
                            f"-MinutesUntilShutdown {delay_minutes} -StopService "
                            f"-ShutdownGraceSeconds {grace_seconds}",
                            # Wrapper sleeps `grace_seconds`, then runs the
                            # final backup (zip + blob upload), then stops
                            # the service. Allow a generous backup window
                            # on top of the grace period.
                            timeout_sec=grace_seconds + 1800,
                        )
                    if not announce.succeeded:
                        await interaction.followup.send(
                            f":x: Shutdown warning failed, aborting deallocation.\n```\n{announce.best_text[-1500:]}\n```",
                            ephemeral=True,
                        )
                        await audit(
                            self.bot,
                            interaction,
                            "vm stop",
                            success=False,
                            detail="announce wrapper failed",
                        )
                        return
            else:
                await interaction.followup.send("Deallocating VM…", ephemeral=True)

            try:
                await self.azure.deallocate_vm()
            except Exception as exc:  # noqa: BLE001
                await audit(
                    self.bot, interaction, "vm stop", success=False, detail=repr(exc)
                )
                raise

        await interaction.followup.send(
            f":white_check_mark: VM deallocated by {interaction.user.mention}."
        )
        await audit(
            self.bot,
            interaction,
            "vm stop",
            success=True,
            detail=f"delay_minutes={delay_minutes}",
        )

    @server.command(
        name="restart-service",
        description="Restart the NSSM-wrapped server service (admin).",
    )
    @requires("admin")
    async def restart_service(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        if not await ensure_vm_running(interaction, self.azure):
            return
        cfg = self.bot.config  # type: ignore[attr-defined]
        async with run_slot(self.bot, interaction, "server restart-service") as ok:
            if not ok:
                return
            svc = cfg.game.service_name
            result = await self.azure.run_powershell(
                [
                    f"Restart-Service '{svc}' -Force",
                    "Start-Sleep -Seconds 5",
                    f"(Get-Service '{svc}').Status",
                ]
            )
        body = result.best_text or "(no output)"
        emoji = ":arrows_counterclockwise:" if result.succeeded else ":x:"
        await interaction.followup.send(f"{emoji} `{cfg.game.service_name}`\n```\n{body[-1500:]}\n```")
        await audit(
            self.bot,
            interaction,
            "service restart",
            success=result.succeeded,
            detail=cfg.game.service_name,
        )

    @server.command(name="logs", description="Tail the server log.")
    @app_commands.describe(lines="How many lines to return (1-50).")
    @requires("player")
    async def logs(
        self,
        interaction: discord.Interaction,
        lines: app_commands.Range[int, 1, 50] = 20,
    ) -> None:
        await interaction.response.defer(thinking=True)
        if not await ensure_vm_running(interaction, self.azure):
            return
        cfg = self.bot.config  # type: ignore[attr-defined]
        log_path = cfg.game.log_path
        result = await self.azure.run_powershell(
            [
                f"if (Test-Path '{log_path}') {{ Get-Content -Path '{log_path}' -Tail {int(lines)} }} "
                f"else {{ 'Log not found at {log_path}' }}",
            ]
        )
        text = result.best_text or "(empty)"
        await interaction.followup.send(f"```\n{text[-1800:]}\n```")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Server(bot))
