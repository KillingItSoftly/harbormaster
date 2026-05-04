from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from ..auth import requires
from ..azure_client import AzureClient
from ..checks import ensure_service_running, ensure_vm_running, run_slot


def parse_player_count(text: str) -> int | None:
    """Parse a Get-PlayerCount.ps1 wrapper's stdout into a player count.

    Returns None if the probe couldn't determine a count (the script
    prints `unknown`) or if parsing failed for any other reason. Callers
    should treat `None` as "do not gate operations on this value".
    """
    if not text:
        return None
    # Take the last non-empty line — Connect-AzAccount and friends can
    # spam stdout, but the probe always prints the answer last.
    last = ""
    for line in text.strip().splitlines():
        line = line.strip()
        if line:
            last = line
    if not last or last.lower() == "unknown":
        return None
    try:
        return int(last)
    except ValueError:
        return None


class Players(commands.Cog):
    """Read-only player-count visibility."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.azure: AzureClient = bot.azure  # type: ignore[attr-defined]

    @app_commands.command(
        name="players",
        description="Show the current online player count, if known.",
    )
    @requires("player")
    async def players(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        if not await ensure_vm_running(interaction, self.azure):
            return
        if not await ensure_service_running(interaction, self.azure):
            return
        cfg = self.bot.config  # type: ignore[attr-defined]
        async with run_slot(self.bot, interaction, "players") as ok:
            if not ok:
                return
            wrapper = f"Get-{cfg.game.name}Players.ps1"
            result = await self.azure.invoke_wrapper(wrapper, timeout_sec=60)
        count = parse_player_count(result.stdout)
        if count is None:
            await interaction.followup.send(
                "Player count is **unknown** "
                "(probe not configured for this game, or it couldn't read a count)."
            )
            return
        if count == 0:
            await interaction.followup.send(":zzz: No players online.")
        elif count == 1:
            await interaction.followup.send(":bust_in_silhouette: **1** player online.")
        else:
            await interaction.followup.send(
                f":busts_in_silhouette: **{count}** players online."
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Players(bot))
