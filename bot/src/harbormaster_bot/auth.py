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

# Commands that admins are allowed to run even while maintenance mode is on.
_MAINTENANCE_BYPASS = {
    "maintenance on",
    "maintenance off",
    "maintenance status",
    "server status",
    "server logs",
    "health",
    "help",
}


def _has_role(member: discord.Member, role_id: int) -> bool:
    return any(r.id == role_id for r in member.roles)


def member_tier(member: discord.Member, config: BotConfig) -> Tier | None:
    if _has_role(member, config.discord.admin_role_id):
        return "admin"
    if _has_role(member, config.discord.player_role_id):
        return "player"
    return None


def _cooldown_for(config: BotConfig, command_name: str) -> int:
    overrides = config.rate_limit_overrides or {}
    return int(overrides.get(command_name, config.rate_limit_seconds))


def requires(tier: Tier):
    """Slash-command check: enforces guild scope, permission tier, rate limit,
    and maintenance mode."""

    async def predicate(interaction: discord.Interaction) -> bool:
        config: BotConfig = interaction.client.config  # type: ignore[attr-defined]
        state = getattr(interaction.client, "state", None)

        # Reject DMs and any guild that is not the configured one.
        if interaction.guild_id is None:
            await interaction.response.send_message(
                "This bot only works inside its configured server.",
                ephemeral=True,
            )
            return False
        if interaction.guild_id != config.discord.guild_id:
            await interaction.response.send_message(
                "This bot is not authorized for this server.",
                ephemeral=True,
            )
            return False

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

        cmd_name = interaction.command.qualified_name

        # Maintenance-mode gate.
        if (
            state is not None
            and state.maintenance
            and cmd_name not in _MAINTENANCE_BYPASS
            and actual != "admin"
        ):
            await interaction.response.send_message(
                ":construction: The bot is in **maintenance mode**. "
                "Try again later.",
                ephemeral=True,
            )
            return False

        # Per-(user, command) cooldown with per-command override.
        cooldown = _cooldown_for(config, cmd_name)
        now = time.monotonic()
        last = _last_invoked[interaction.user.id].get(cmd_name, 0.0)
        wait = cooldown - (now - last)
        if wait > 0:
            await interaction.response.send_message(
                f"Slow down — try `/{cmd_name}` again in {int(wait) + 1}s.",
                ephemeral=True,
            )
            return False
        _last_invoked[interaction.user.id][cmd_name] = now
        return True

    return app_commands.check(predicate)
