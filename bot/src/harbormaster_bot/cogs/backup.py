from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from ..auth import requires
from ..azure_client import AzureClient


class Backup(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.azure: AzureClient = bot.azure  # type: ignore[attr-defined]

    backup = app_commands.Group(name="backup", description="Backup operations")

    @backup.command(name="now", description="Trigger an on-demand backup (admin).")
    @requires("admin")
    async def now(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        wrapper = f"Backup-{self.bot.config.game.name}.ps1"  # type: ignore[attr-defined]
        result = await self.azure.invoke_wrapper(wrapper)
        if result.succeeded:
            tail = "\n".join(result.stdout.strip().splitlines()[-10:]) or "(done)"
            await interaction.followup.send(
                f":floppy_disk: Backup complete.\n```\n{tail}\n```"
            )
        else:
            err = result.best_text[-1500:] or "(no output)"
            await interaction.followup.send(f":x: Backup failed.\n```\n{err}\n```")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Backup(bot))
