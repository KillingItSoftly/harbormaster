from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from ..auth import member_tier


class Help(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="help",
        description="Show available commands and your permission tier.",
    )
    async def help_(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Use this in the configured server.", ephemeral=True
            )
            return
        config = self.bot.config  # type: ignore[attr-defined]
        tier = member_tier(interaction.user, config) or "none"

        player = (
            "`/server status` — show VM power state\n"
            "`/server start` — boot the VM\n"
            "`/server logs lines:<n>` — tail the server log\n"
            "`/snapshot list` — list milestones\n"
            "`/update check` — check for Steam updates\n"
            "`/health` — run the VM health check\n"
        )
        admin = (
            "`/server stop` — deallocate the VM\n"
            "`/server restart-service` — restart the NSSM service\n"
            "`/backup now` — on-demand backup\n"
            "`/snapshot create label:<text> category:<choice>` — milestone snapshot\n"
            "`/update apply` — snapshot then apply Steam update\n"
        )

        embed = discord.Embed(
            title=f"{config.game.name} bot — commands",
            description=f"Your role: **{tier}**",
            color=0x5865F2,
        )
        embed.add_field(name="Player", value=player, inline=False)
        embed.add_field(name="Admin", value=admin, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Help(bot))
