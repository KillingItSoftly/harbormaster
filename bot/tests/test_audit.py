"""Tests for harbormaster_bot.audit — audit() function."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from harbormaster_bot.audit import audit
from harbormaster_bot.config import (
    AzureConfig,
    BotConfig,
    DiscordConfig,
    GameConfig,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

AUDIT_CHANNEL_ID = 123456789


def _config(*, audit_channel_id: int | None = AUDIT_CHANNEL_ID) -> BotConfig:
    return BotConfig(
        discord=DiscordConfig(
            guild_id=1,
            player_role_id=2,
            admin_role_id=3,
            status_channel_id=None,
            audit_channel_id=audit_channel_id,
        ),
        azure=AzureConfig(subscription_id="sub", resource_group="rg", vm_name="vm"),
        game=GameConfig(
            name="TestGame",
            service_name="svc",
            script_dir=r"C:\Scripts",
            log_path=r"C:\Logs\game.log",
        ),
    )


def _make_bot(channel=None, *, audit_channel_id: int | None = AUDIT_CHANNEL_ID):
    bot = MagicMock()
    bot.config = _config(audit_channel_id=audit_channel_id)
    bot.get_channel.return_value = channel
    return bot


def _make_interaction(*, guild_id: int | None = 999):
    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild_id = guild_id
    interaction.user = MagicMock()
    interaction.user.__str__ = lambda self: "TestUser#0001"
    interaction.user.id = 777
    return interaction


def _make_channel():
    chan = AsyncMock(spec=discord.TextChannel)
    chan.send = AsyncMock()
    return chan


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_audit_no_op_when_no_channel_id_configured():
    """audit() should silently return when audit_channel_id is None."""
    bot = _make_bot(audit_channel_id=None)
    interaction = _make_interaction()

    # Should not raise and should not call get_channel.
    await audit(bot, interaction, "some action")
    bot.get_channel.assert_not_called()


async def test_audit_no_op_when_channel_not_found():
    """audit() is a no-op if get_channel returns None (channel not cached)."""
    bot = _make_bot(channel=None)
    interaction = _make_interaction()

    await audit(bot, interaction, "some action")
    # No exception and no send call.


async def test_audit_sends_embed_to_channel():
    chan = _make_channel()
    bot = _make_bot(channel=chan)
    interaction = _make_interaction()

    await audit(bot, interaction, "vm start", success=True)

    chan.send.assert_awaited_once()
    embed_arg = chan.send.call_args[1]["embed"]
    assert isinstance(embed_arg, discord.Embed)


async def test_audit_embed_title_is_action():
    chan = _make_channel()
    bot = _make_bot(channel=chan)
    interaction = _make_interaction()

    await audit(bot, interaction, "backup", success=True)

    embed = chan.send.call_args[1]["embed"]
    assert embed.title == "backup"


async def test_audit_success_color_is_green():
    chan = _make_channel()
    bot = _make_bot(channel=chan)
    interaction = _make_interaction()

    await audit(bot, interaction, "op", success=True)

    embed = chan.send.call_args[1]["embed"]
    assert embed.color.value == 0x2ECC71


async def test_audit_failure_color_is_red():
    chan = _make_channel()
    bot = _make_bot(channel=chan)
    interaction = _make_interaction()

    await audit(bot, interaction, "op", success=False)

    embed = chan.send.call_args[1]["embed"]
    assert embed.color.value == 0xE74C3C


async def test_audit_includes_guild_id_field():
    chan = _make_channel()
    bot = _make_bot(channel=chan)
    interaction = _make_interaction(guild_id=42)

    await audit(bot, interaction, "op")

    embed = chan.send.call_args[1]["embed"]
    field_names = [f.name for f in embed.fields]
    assert "Guild" in field_names


async def test_audit_omits_guild_field_when_no_guild():
    chan = _make_channel()
    bot = _make_bot(channel=chan)
    interaction = _make_interaction(guild_id=None)

    await audit(bot, interaction, "op")

    embed = chan.send.call_args[1]["embed"]
    field_names = [f.name for f in embed.fields]
    assert "Guild" not in field_names


async def test_audit_includes_detail_field():
    chan = _make_channel()
    bot = _make_bot(channel=chan)
    interaction = _make_interaction()

    await audit(bot, interaction, "op", detail="Something went wrong here")

    embed = chan.send.call_args[1]["embed"]
    field_names = [f.name for f in embed.fields]
    field_values = [f.value for f in embed.fields]
    assert "Detail" in field_names
    assert "Something went wrong here" in field_values


async def test_audit_omits_detail_field_when_empty():
    chan = _make_channel()
    bot = _make_bot(channel=chan)
    interaction = _make_interaction()

    await audit(bot, interaction, "op", detail="")

    embed = chan.send.call_args[1]["embed"]
    field_names = [f.name for f in embed.fields]
    assert "Detail" not in field_names


async def test_audit_detail_truncated_to_1024_chars():
    chan = _make_channel()
    bot = _make_bot(channel=chan)
    interaction = _make_interaction()
    long_detail = "x" * 2000

    await audit(bot, interaction, "op", detail=long_detail)

    embed = chan.send.call_args[1]["embed"]
    for f in embed.fields:
        if f.name == "Detail":
            assert len(f.value) <= 1024
            break


async def test_audit_does_not_raise_on_send_failure():
    """A broken audit channel must never propagate exceptions."""
    chan = _make_channel()
    chan.send = AsyncMock(side_effect=discord.HTTPException(MagicMock(), "network error"))
    bot = _make_bot(channel=chan)
    interaction = _make_interaction()

    # Should not raise.
    await audit(bot, interaction, "op")
