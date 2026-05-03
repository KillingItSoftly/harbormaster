from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from ..auth import requires
from ..azure_client import AzureClient


class Health(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.azure: AzureClient = bot.azure  # type: ignore[attr-defined]

    @app_commands.command(name="health", description="Run the on-VM health check and report.")
    @requires("player")
    async def health(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        wrapper = f"Check-{self.bot.config.game.name}Health.ps1"  # type: ignore[attr-defined]
        result = await self.azure.invoke_wrapper(wrapper)
        text = result.best_text[-1800:] or "(no output — checks passed silently)"
        await interaction.followup.send(f"```\n{text}\n```")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Health(bot))
