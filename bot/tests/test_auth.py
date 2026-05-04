"""Tests for harbormaster_bot.auth — member_tier, _has_role, _cooldown_for, requires()."""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from harbormaster_bot.auth import _cooldown_for, _has_role, member_tier, requires
from harbormaster_bot.config import (
    AzureConfig,
    BotConfig,
    DiscordConfig,
    GameConfig,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

GUILD_ID = 111111111111111111
PLAYER_ROLE_ID = 222222222222222222
ADMIN_ROLE_ID = 333333333333333333


def _config(
    *,
    rate_limit_seconds: int = 30,
    rate_limit_overrides: dict[str, int] | None = None,
) -> BotConfig:
    return BotConfig(
        discord=DiscordConfig(
            guild_id=GUILD_ID,
            player_role_id=PLAYER_ROLE_ID,
            admin_role_id=ADMIN_ROLE_ID,
            status_channel_id=None,
            audit_channel_id=None,
        ),
        azure=AzureConfig(
            subscription_id="sub-id",
            resource_group="rg",
            vm_name="vm",
        ),
        game=GameConfig(
            name="TestGame",
            service_name="testgame-svc",
            script_dir=r"C:\Harbormaster\TestGame",
            log_path=r"C:\Servers\TestGame\logs\server.log",
        ),
        rate_limit_seconds=rate_limit_seconds,
        rate_limit_overrides=rate_limit_overrides,
    )


def _make_role(role_id: int) -> MagicMock:
    r = MagicMock(spec=discord.Role)
    r.id = role_id
    return r


def _make_member(*role_ids: int) -> MagicMock:
    m = MagicMock(spec=discord.Member)
    m.roles = [_make_role(rid) for rid in role_ids]
    m.id = 999999999
    return m


# ---------------------------------------------------------------------------
# _has_role
# ---------------------------------------------------------------------------


def test_has_role_true_when_present():
    member = _make_member(PLAYER_ROLE_ID, 12345)
    assert _has_role(member, PLAYER_ROLE_ID) is True


def test_has_role_false_when_absent():
    member = _make_member(12345, 67890)
    assert _has_role(member, ADMIN_ROLE_ID) is False


def test_has_role_empty_roles():
    member = _make_member()
    assert _has_role(member, PLAYER_ROLE_ID) is False


# ---------------------------------------------------------------------------
# member_tier
# ---------------------------------------------------------------------------


def test_member_tier_admin():
    member = _make_member(ADMIN_ROLE_ID)
    assert member_tier(member, _config()) == "admin"


def test_member_tier_player():
    member = _make_member(PLAYER_ROLE_ID)
    assert member_tier(member, _config()) == "player"


def test_member_tier_admin_wins_over_player():
    """Admin role takes precedence if a member somehow has both."""
    member = _make_member(ADMIN_ROLE_ID, PLAYER_ROLE_ID)
    assert member_tier(member, _config()) == "admin"


def test_member_tier_none_when_no_harbormaster_role():
    member = _make_member(99999)
    assert member_tier(member, _config()) is None


# ---------------------------------------------------------------------------
# _cooldown_for
# ---------------------------------------------------------------------------


def test_cooldown_falls_back_to_rate_limit_seconds():
    cfg = _config(rate_limit_seconds=60)
    assert _cooldown_for(cfg, "server status") == 60


def test_cooldown_uses_override_when_present():
    cfg = _config(rate_limit_seconds=30, rate_limit_overrides={"server stop": 120})
    assert _cooldown_for(cfg, "server stop") == 120


def test_cooldown_falls_back_for_unlisted_command():
    cfg = _config(rate_limit_seconds=30, rate_limit_overrides={"server stop": 120})
    assert _cooldown_for(cfg, "health") == 30


def test_cooldown_no_overrides():
    cfg = _config(rate_limit_seconds=45, rate_limit_overrides=None)
    assert _cooldown_for(cfg, "anything") == 45


# ---------------------------------------------------------------------------
# requires() predicate — via direct predicate invocation
# ---------------------------------------------------------------------------

# The predicate returned by app_commands.check wraps our async function.
# We pull the inner callable out to test it without Discord's decorator machinery.


def _get_predicate(tier: str):
    """Return the raw async predicate function from requires(tier)."""
    # requires() calls app_commands.check(predicate) and returns the result.
    # We capture `predicate` before the wrapping by patching app_commands.check.
    captured = []

    def fake_check(fn):
        captured.append(fn)
        return fn

    with patch("harbormaster_bot.auth.app_commands.check", side_effect=fake_check):
        requires(tier)

    return captured[0]


def _make_interaction(
    *,
    guild_id: int | None = GUILD_ID,
    user_roles: tuple[int, ...] = (PLAYER_ROLE_ID,),
    command_name: str = "server status",
    maintenance: bool = False,
    cooldown: float = 0.0,
) -> MagicMock:
    """Build a minimal mock discord.Interaction for predicate tests."""
    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild_id = guild_id
    # Use a plain MagicMock for response so is_done() returns a real bool,
    # not a coroutine (AsyncMock child attributes are also AsyncMock and their
    # call result is a truthy coroutine object even before being awaited).
    interaction.response = MagicMock()
    interaction.response.is_done.return_value = False
    interaction.response.send_message = AsyncMock()

    user = _make_member(*user_roles)
    user.id = 9876543210
    interaction.user = user

    cmd = MagicMock()
    cmd.qualified_name = command_name
    interaction.command = cmd

    # Attach a fake bot with config + state.
    bot = MagicMock()
    bot.config = _config()

    state = MagicMock()
    state.maintenance = maintenance
    bot.state = state

    interaction.client = bot
    return interaction


async def test_requires_rejects_dm(monkeypatch):
    predicate = _get_predicate("player")
    interaction = _make_interaction(guild_id=None)

    result = await predicate(interaction)

    assert result is False
    interaction.response.send_message.assert_awaited_once()


async def test_requires_rejects_wrong_guild(monkeypatch):
    predicate = _get_predicate("player")
    interaction = _make_interaction(guild_id=999)  # not GUILD_ID

    result = await predicate(interaction)

    assert result is False
    interaction.response.send_message.assert_awaited_once()


async def test_requires_rejects_non_member_user():
    predicate = _get_predicate("player")
    interaction = _make_interaction()
    # Swap user out for a plain User object (not a Member)
    interaction.user = MagicMock(spec=discord.User)
    interaction.user.id = 9876543210

    result = await predicate(interaction)

    assert result is False


async def test_requires_rejects_no_role():
    predicate = _get_predicate("player")
    interaction = _make_interaction(user_roles=(99999,))  # not a HM role

    result = await predicate(interaction)

    assert result is False


async def test_requires_player_allows_player():
    predicate = _get_predicate("player")
    interaction = _make_interaction(user_roles=(PLAYER_ROLE_ID,))

    result = await predicate(interaction)

    assert result is True


async def test_requires_admin_allows_admin():
    predicate = _get_predicate("admin")
    interaction = _make_interaction(user_roles=(ADMIN_ROLE_ID,))

    result = await predicate(interaction)

    assert result is True


async def test_requires_admin_rejects_player():
    predicate = _get_predicate("admin")
    interaction = _make_interaction(user_roles=(PLAYER_ROLE_ID,))

    result = await predicate(interaction)

    assert result is False
    interaction.response.send_message.assert_awaited_once()


async def test_requires_maintenance_blocks_player():
    predicate = _get_predicate("player")
    interaction = _make_interaction(
        user_roles=(PLAYER_ROLE_ID,),
        command_name="server start",  # not in bypass set
        maintenance=True,
    )

    result = await predicate(interaction)

    assert result is False


async def test_requires_maintenance_allows_bypass_command():
    predicate = _get_predicate("player")
    interaction = _make_interaction(
        user_roles=(PLAYER_ROLE_ID,),
        command_name="server status",  # in _MAINTENANCE_BYPASS
        maintenance=True,
    )

    result = await predicate(interaction)

    assert result is True


async def test_requires_maintenance_allows_admin():
    """Admins pass even if maintenance is on and command is not bypassed."""
    predicate = _get_predicate("admin")
    interaction = _make_interaction(
        user_roles=(ADMIN_ROLE_ID,),
        command_name="update apply",
        maintenance=True,
    )

    result = await predicate(interaction)

    assert result is True


async def test_requires_cooldown_blocks_repeat():
    """Second invocation within the cooldown window must be rejected."""
    predicate = _get_predicate("player")
    interaction = _make_interaction(user_roles=(PLAYER_ROLE_ID,), command_name="health")

    # First call — should succeed and record timestamp.
    first = await predicate(interaction)
    assert first is True

    # Second call immediately after — cooldown (30s default) not elapsed.
    second = await predicate(interaction)
    assert second is False


async def test_requires_cooldown_passes_after_wait(monkeypatch):
    """After the cooldown window passes, the command should be allowed again."""
    import harbormaster_bot.auth as auth_module

    predicate = _get_predicate("player")
    user_id = 9876543210
    cmd_name = "players"

    interaction = _make_interaction(
        user_roles=(PLAYER_ROLE_ID,), command_name=cmd_name
    )
    interaction.user.id = user_id

    # Manually plant a very old last-invoked timestamp (far in the past).
    auth_module._last_invoked[user_id][cmd_name] = time.monotonic() - 9999

    result = await predicate(interaction)
    assert result is True
