from __future__ import annotations

import re

import discord
from discord import app_commands
from discord.ext import commands

from ..audit import audit
from ..auth import requires
from ..azure_client import AzureClient
from ..checks import ensure_vm_running, progress_heartbeat, run_slot
from ..views import ConfirmView, confirm_prompt

# Mirrors the allowlist in core/scripts/Restore-GameServer.ps1. The bot
# enforces it client-side so we can fail fast without burning a Run
# Command, and so the confirm prompt can quote a name we know is safe to
# echo back into Discord.
_BLOB_NAME_RE = re.compile(
    r"^("
    r"[a-z][a-z0-9]*_\d{4}-\d{2}-\d{2}_\d{4}\.zip"
    r"|"
    r"milestone_(pristine|pre-change|stable|general)_[A-Za-z0-9_\-]+_\d{4}-\d{2}-\d{2}_\d{4}\.zip"
    r")$"
)


class Restore(commands.Cog):
    """Restore the game's saved data from a backup or milestone blob."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.azure: AzureClient = bot.azure  # type: ignore[attr-defined]

    restore = app_commands.Group(
        name="restore", description="Restore saved data from blob"
    )

    @restore.command(
        name="list",
        description="List recent backup and milestone blobs.",
    )
    @requires("player")
    async def list_(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        if not await ensure_vm_running(interaction, self.azure):
            return
        cfg = self.bot.config  # type: ignore[attr-defined]
        async with run_slot(self.bot, interaction, "restore list") as ok:
            if not ok:
                return
            wrapper = f"List-{cfg.game.name}Backups.ps1"
            result = await self.azure.invoke_wrapper(wrapper, timeout_sec=120)
        text = result.best_text.strip()
        if not text:
            await interaction.followup.send("(no blobs found)")
            return
        # Truncate; Discord caps at 2000 chars per message.
        body = text[-1800:]
        await interaction.followup.send(
            f"**Available blobs (newest first):**\n```\n{body}\n```"
        )

    @restore.command(
        name="apply",
        description="Restore saved data from a named blob (admin, destructive).",
    )
    @app_commands.describe(
        blob_name="Exact blob name. Must match a backup or milestone naming convention.",
        confirm_blob_name="Repeat the blob name exactly. Must match `blob_name`.",
        skip_pre_snapshot="Skip the pre-restore milestone snapshot. NOT RECOMMENDED.",
    )
    @requires("admin")
    async def apply(
        self,
        interaction: discord.Interaction,
        blob_name: str,
        confirm_blob_name: str,
        skip_pre_snapshot: bool = False,
    ) -> None:
        # Defense in depth: server-side check too.
        if blob_name != confirm_blob_name:
            await interaction.response.send_message(
                ":no_entry: `blob_name` and `confirm_blob_name` must match exactly.",
                ephemeral=True,
            )
            return

        if not _BLOB_NAME_RE.match(blob_name):
            await interaction.response.send_message(
                f":no_entry: `{blob_name}` is not a recognized backup or milestone "
                "name. Use `/restore list` to see valid names.",
                ephemeral=True,
            )
            return

        if not await ensure_vm_running(interaction, self.azure):
            return

        cfg = self.bot.config  # type: ignore[attr-defined]

        view = ConfirmView(interaction.user.id)
        await interaction.response.send_message(
            confirm_prompt(
                "Restore saved data from blob",
                [
                    ("Game", cfg.game.name),
                    ("Service", cfg.game.service_name),
                    ("Blob", f"`{blob_name}`"),
                    ("Pre-restore snapshot",
                     "skipped (no rollback!)" if skip_pre_snapshot
                     else "will be taken"),
                    ("Effect",
                     "Service stops, current saved data is replaced."),
                ],
            ),
            view=view,
            ephemeral=True,
        )
        await view.wait()
        if not view.confirmed:
            await interaction.followup.send("Aborted.", ephemeral=True)
            return

        async with run_slot(self.bot, interaction, "restore apply") as ok:
            if not ok:
                return
            await interaction.followup.send(
                f":warning: Restoring from `{blob_name}`… this can take several minutes."
            )
            wrapper = f"Restore-{cfg.game.name}.ps1"
            args = f"-BlobName '{blob_name}'"
            if skip_pre_snapshot:
                args += " -SkipPreSnapshot"
            async with progress_heartbeat(interaction, "Restore in progress"):
                # Restore can take a long time on a large savedata directory.
                result = await self.azure.invoke_wrapper(
                    wrapper, args, timeout_sec=2400
                )

        if result.succeeded:
            tail = "\n".join(result.stdout.strip().splitlines()[-15:]) or "(done)"
            await interaction.followup.send(
                f":white_check_mark: Restore complete.\n```\n{tail}\n```"
            )
            await audit(
                self.bot, interaction, "restore apply", success=True,
                detail=f"blob={blob_name} skip_pre_snapshot={skip_pre_snapshot}",
            )
        else:
            err = result.best_text[-1500:] or "(no output)"
            await interaction.followup.send(f":x: Restore failed.\n```\n{err}\n```")
            await audit(
                self.bot, interaction, "restore apply", success=False,
                detail=f"blob={blob_name}: {err[-300:]}",
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Restore(bot))
