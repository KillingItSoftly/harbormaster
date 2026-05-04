from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from ..audit import audit
from ..auth import requires


class Maintenance(commands.Cog):
    """Admin-only kill switch. Players are blocked from running commands
    while maintenance mode is on; admins still have access to /server
    status, /server logs, /health, and these toggle commands."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    maintenance = app_commands.Group(
        name="maintenance",
        description="Maintenance mode controls (admin)",
    )

    @maintenance.command(name="status", description="Show whether maintenance mode is on.")
    @requires("admin")
    async def status(self, interaction: discord.Interaction) -> None:
        on = self.bot.state.maintenance  # type: ignore[attr-defined]
        await interaction.response.send_message(
            f"Maintenance mode is **{'ON' if on else 'off'}**.",
            ephemeral=True,
        )

    @maintenance.command(name="on", description="Block player-tier commands.")
    @requires("admin")
    async def on(self, interaction: discord.Interaction) -> None:
        self.bot.state.maintenance = True  # type: ignore[attr-defined]
        await interaction.response.send_message(
            ":construction: Maintenance mode **enabled**. Player commands are blocked.",
            ephemeral=True,
        )
        await audit(self.bot, interaction, "maintenance enabled", success=True)

    @maintenance.command(name="off", description="Resume normal player access.")
    @requires("admin")
    async def off(self, interaction: discord.Interaction) -> None:
        self.bot.state.maintenance = False  # type: ignore[attr-defined]
        await interaction.response.send_message(
            ":white_check_mark: Maintenance mode **disabled**. Players can run commands again.",
            ephemeral=True,
        )
        await audit(self.bot, interaction, "maintenance disabled", success=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Maintenance(bot))
