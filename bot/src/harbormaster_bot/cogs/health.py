from __future__ import annotations

import time

import discord
from discord import app_commands
from discord.ext import commands

from ..audit import audit
from ..auth import requires
from ..azure_client import AzureClient
from ..checks import ensure_vm_running, run_slot


class Health(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.azure: AzureClient = bot.azure  # type: ignore[attr-defined]

    @app_commands.command(name="health", description="Run the on-VM health check and report.")
    @requires("player")
    async def health(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        if not await ensure_vm_running(interaction, self.azure):
            return
        cfg = self.bot.config  # type: ignore[attr-defined]
        state = self.bot.state  # type: ignore[attr-defined]
        async with run_slot(self.bot, interaction, "health") as ok:
            if not ok:
                return
            wrapper = f"Check-{cfg.game.name}Health.ps1"
            result = await self.azure.invoke_wrapper(wrapper)

        # Stamp the bot-wide health-freshness state so /update apply can gate.
        state.last_health_ts = time.time()
        state.last_health_ok = result.succeeded

        text = result.best_text[-1800:] or "(no output — checks passed silently)"
        emoji = ":white_check_mark:" if result.succeeded else ":warning:"
        await interaction.followup.send(f"{emoji} Health check\n```\n{text}\n```")
        await audit(
            self.bot, interaction, "health check",
            success=result.succeeded,
            detail="" if result.succeeded else text[-512:],
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Health(bot))
