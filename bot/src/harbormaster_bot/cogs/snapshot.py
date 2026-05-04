from __future__ import annotations

import re

import discord
from discord import app_commands
from discord.ext import commands

from ..audit import audit
from ..auth import requires
from ..azure_client import AzureClient
from ..checks import ensure_vm_running, run_slot

CATEGORIES = ["pristine", "pre-change", "stable", "general"]
# Tightened from the previous 1-50 to forbid spaces/quotes/dots, since the
# label is interpolated into a PowerShell single-quoted string.
LABEL_RE = re.compile(r"^[A-Za-z0-9_-]{1,50}$")


class Snapshot(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.azure: AzureClient = bot.azure  # type: ignore[attr-defined]

    snapshot = app_commands.Group(name="snapshot", description="Milestone snapshots")

    @snapshot.command(name="create", description="Create a labeled milestone snapshot (admin).")
    @app_commands.describe(
        label="Short label (1-50 chars, letters/digits/_/-).",
        category="Retention bucket.",
    )
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
        if not await ensure_vm_running(interaction, self.azure):
            return
        cfg = self.bot.config  # type: ignore[attr-defined]
        async with run_slot(self.bot, interaction, "snapshot create") as ok:
            if not ok:
                return
            wrapper = f"Manage-{cfg.game.name}Milestones.ps1"
            result = await self.azure.invoke_wrapper(
                wrapper, f"-Action Snapshot -Label '{label}' -Category {cat}"
            )
        if result.succeeded:
            await interaction.followup.send(
                f":camera: Snapshot `{label}` ({cat}) created."
            )
            await audit(
                self.bot, interaction, "snapshot create",
                success=True, detail=f"{label} / {cat}",
            )
        else:
            err = result.best_text[-1500:] or "(no output)"
            await interaction.followup.send(f":x: Snapshot failed.\n```\n{err}\n```")
            await audit(
                self.bot, interaction, "snapshot create",
                success=False, detail=err[-512:],
            )

    @snapshot.command(name="list", description="List milestones currently in blob storage.")
    @requires("player")
    async def list_(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        if not await ensure_vm_running(interaction, self.azure):
            return
        cfg = self.bot.config  # type: ignore[attr-defined]
        async with run_slot(self.bot, interaction, "snapshot list") as ok:
            if not ok:
                return
            wrapper = f"Manage-{cfg.game.name}Milestones.ps1"
            result = await self.azure.invoke_wrapper(wrapper, "-Action List")
        text = result.best_text[-1800:] or "(none)"
        await interaction.followup.send(f"```\n{text}\n```")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Snapshot(bot))
