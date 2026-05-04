from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from ..audit import audit
from ..auth import requires
from ..azure_client import AzureClient
from ..checks import (
    ensure_service_running,
    ensure_vm_running,
    progress_heartbeat,
    run_slot,
)


class Backup(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.azure: AzureClient = bot.azure  # type: ignore[attr-defined]

    backup = app_commands.Group(name="backup", description="Backup operations")

    @backup.command(name="now", description="Trigger an on-demand backup (admin).")
    @requires("admin")
    async def now(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        if not await ensure_vm_running(interaction, self.azure):
            return
        cfg = self.bot.config  # type: ignore[attr-defined]
        if not await ensure_service_running(interaction, self.azure, cfg.game.service_name):
            return

        async with run_slot(self.bot, interaction, "backup now") as ok:
            if not ok:
                return
            wrapper = f"Backup-{cfg.game.name}.ps1"
            async with progress_heartbeat(interaction, "Running backup"):
                result = await self.azure.invoke_wrapper(wrapper)

        if result.succeeded:
            tail = "\n".join(result.stdout.strip().splitlines()[-10:]) or "(done)"
            await interaction.followup.send(
                f":floppy_disk: Backup complete.\n```\n{tail}\n```"
            )
            await audit(self.bot, interaction, "backup", success=True)
        else:
            err = result.best_text[-1500:] or "(no output)"
            await interaction.followup.send(f":x: Backup failed.\n```\n{err}\n```")
            await audit(
                self.bot, interaction, "backup", success=False, detail=err[-512:]
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Backup(bot))
