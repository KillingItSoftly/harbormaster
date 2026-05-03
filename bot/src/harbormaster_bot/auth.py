from __future__ import annotations

import time
from collections import defaultdict
from typing import Literal

import discord
from discord import app_commands

from .config import BotConfig

Tier = Literal["player", "admin"]

# user_id -> command_name -> last_invoked_monotonic_ts
_last_invoked: dict[int, dict[str, float]] = defaultdict(dict)


def _has_role(member: discord.Member, role_id: int) -> bool:
    return any(r.id == role_id for r in member.roles)


def member_tier(member: discord.Member, config: BotConfig) -> Tier | None:
    if _has_role(member, config.discord.admin_role_id):
        return "admin"
    if _has_role(member, config.discord.player_role_id):
        return "player"
    return None


def requires(tier: Tier):
    """Slash-command check: enforces a permission tier and a per-user rate limit."""

    async def predicate(interaction: discord.Interaction) -> bool:
        config: BotConfig = interaction.client.config  # type: ignore[attr-defined]

        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "This command must be used inside the configured server.",
                ephemeral=True,
            )
            return False

        actual = member_tier(interaction.user, config)
        if actual is None:
            await interaction.response.send_message(
                "You don't have a Harbormaster role on this server.",
                ephemeral=True,
            )
            return False

        if tier == "admin" and actual != "admin":
            cmd = interaction.command.qualified_name if interaction.command else "this command"
            await interaction.response.send_message(
                f"`/{cmd}` requires the Admin role.", ephemeral=True
            )
            return False

        if interaction.command is None:
            return True

        cmd = interaction.command.qualified_name
        now = time.monotonic()
        last = _last_invoked[interaction.user.id].get(cmd, 0.0)
        wait = config.rate_limit_seconds - (now - last)
        if wait > 0:
            await interaction.response.send_message(
                f"Slow down — try `/{cmd}` again in {int(wait) + 1}s.",
                ephemeral=True,
            )
            return False
        _last_invoked[interaction.user.id][cmd] = now
        return True

    return app_commands.check(predicate)
