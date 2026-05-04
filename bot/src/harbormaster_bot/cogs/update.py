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

# An admin must have run /health within this many seconds for /update apply
# to proceed without `force`.
HEALTH_FRESHNESS_SEC = 24 * 60 * 60


class Update(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.azure: AzureClient = bot.azure  # type: ignore[attr-defined]

    update = app_commands.Group(name="update", description="Steam update operations")

    @update.command(name="check", description="Check Steam for available updates.")
    @requires("player")
    async def check(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        if not await ensure_vm_running(interaction, self.azure):
            return
        cfg = self.bot.config  # type: ignore[attr-defined]
        async with run_slot(self.bot, interaction, "update check") as ok:
            if not ok:
                return
            wrapper = f"Check-{cfg.game.name}Update.ps1"
            result = await self.azure.invoke_wrapper(wrapper)
        text = result.best_text[-1800:] or "(no output)"
        await interaction.followup.send(f"```\n{text}\n```")

    @update.command(
        name="apply",
        description="Snapshot then apply available update (admin).",
    )
    @app_commands.describe(
        force="Skip the recent-/health check and proceed even if health is stale.",
    )
    @requires("admin")
    async def apply(
        self,
        interaction: discord.Interaction,
        force: bool = False,
    ) -> None:
        if not await ensure_vm_running(interaction, self.azure):
            return

        cfg = self.bot.config  # type: ignore[attr-defined]
        state = self.bot.state  # type: ignore[attr-defined]

        # Health-staleness gate.
        if not force:
            now = time.time()
            age = now - (state.last_health_ts or 0)
            if state.last_health_ts == 0 or age > HEALTH_FRESHNESS_SEC:
                await interaction.response.send_message(
                    ":no_entry: No recent `/health` run on record. "
                    "Run `/health` first, or re-invoke with `force:true`.",
                    ephemeral=True,
                )
                return
            if not state.last_health_ok:
                await interaction.response.send_message(
                    ":no_entry: Last `/health` run reported failures. "
                    "Investigate first, or re-invoke with `force:true`.",
                    ephemeral=True,
                )
                return

        view = ConfirmView(interaction.user.id)
        await interaction.response.send_message(
            confirm_prompt(
                "Apply Steam update",
                [
                    ("Game", cfg.game.name),
                    ("Service", cfg.game.service_name),
                    ("Effect", "Service stops briefly during update"),
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

        async with run_slot(self.bot, interaction, "update apply") as ok:
            if not ok:
                return
            await interaction.followup.send(
                "Applying update… this may take several minutes."
            )
            wrapper = f"Check-{cfg.game.name}Update.ps1"
            args = "-ApplyUpdate"
            if force:
                args += " -Force"
            async with progress_heartbeat(interaction, "Applying Steam update"):
                result = await self.azure.invoke_wrapper(wrapper, args)

        if result.succeeded:
            tail = "\n".join(result.stdout.strip().splitlines()[-15:]) or "(done)"
            await interaction.followup.send(
                f":white_check_mark: Update finished.\n```\n{tail}\n```"
            )
            await audit(
                self.bot, interaction, "update apply", success=True,
                detail=f"force={force}",
            )
        else:
            err = result.best_text[-1500:] or "(no output)"
            await interaction.followup.send(f":x: Update failed.\n```\n{err}\n```")
            await audit(
                self.bot, interaction, "update apply", success=False,
                detail=err[-512:],
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Update(bot))
