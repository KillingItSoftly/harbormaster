from __future__ import annotations

import re

import discord
from discord import app_commands
from discord.ext import commands

from ..auth import requires
from ..azure_client import AzureClient

CATEGORIES = ["pristine", "pre-change", "stable", "general"]
LABEL_RE = re.compile(r"[A-Za-z0-9_-]{1,50}")


class Snapshot(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.azure: AzureClient = bot.azure  # type: ignore[attr-defined]

    snapshot = app_commands.Group(name="snapshot", description="Milestone snapshots")

    @snapshot.command(name="create", description="Create a labeled milestone snapshot (admin).")
    @app_commands.describe(label="Short label (1-50 chars, letters/digits/_/-).",
                           category="Retention bucket.")
    @app_commands.choices(
        category=[app_commands.Choice(name=c, value=c) for c in CATEGORIES]
    )
    @requires("admin")
    async def create(
        self,
        interaction: discord.Interaction,
        label: str,
        category: app_commands.Choice[str] | None = None,
    ) -> None:
        if not LABEL_RE.fullmatch(label):
            await interaction.response.send_message(
                "Label must be 1-50 chars, letters/digits/`_`/`-` only.",
                ephemeral=True,
            )
            return
        cat = category.value if category else "general"
        await interaction.response.defer(thinking=True)
        wrapper = f"Manage-{self.bot.config.game.name}Milestones.ps1"  # type: ignore[attr-defined]
        result = await self.azure.invoke_wrapper(
            wrapper, f"-Action Snapshot -Label '{label}' -Category {cat}"
        )
        if result.succeeded:
            await interaction.followup.send(
                f":camera: Snapshot `{label}` ({cat}) created."
            )
        else:
            err = result.best_text[-1500:] or "(no output)"
            await interaction.followup.send(f":x: Snapshot failed.\n```\n{err}\n```")

    @snapshot.command(name="list", description="List milestones currently in blob storage.")
    @requires("player")
    async def list_(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        wrapper = f"Manage-{self.bot.config.game.name}Milestones.ps1"  # type: ignore[attr-defined]
        result = await self.azure.invoke_wrapper(wrapper, "-Action List")
        text = result.best_text[-1800:] or "(none)"
        await interaction.followup.send(f"```\n{text}\n```")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Snapshot(bot))
