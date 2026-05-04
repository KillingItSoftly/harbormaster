"""Tests for harbormaster_bot.checks — ensure_vm_running, ensure_service_running, run_slot."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from harbormaster_bot.checks import ensure_service_running, ensure_vm_running, run_slot
from harbormaster_bot.state import BusyError, RuntimeState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_interaction() -> MagicMock:
    interaction = MagicMock(spec=discord.Interaction)
    # Use a plain MagicMock for response so is_done() returns a real bool
    # (AsyncMock children are also AsyncMock whose call result is a truthy
    # coroutine object even before being awaited).
    interaction.response = MagicMock()
    interaction.response.is_done.return_value = False
    interaction.response.send_message = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
    return interaction


def _make_azure(*, power_state: str = "running", service_status: str = "Running"):
    azure = MagicMock()
    azure.power_state = AsyncMock(return_value=power_state)
    azure.get_service_status = AsyncMock(return_value=service_status)
    return azure


# ---------------------------------------------------------------------------
# ensure_vm_running
# ---------------------------------------------------------------------------


async def test_ensure_vm_running_returns_true_when_running():
    interaction = _make_interaction()
    azure = _make_azure(power_state="running")

    result = await ensure_vm_running(interaction, azure)

    assert result is True
    interaction.response.send_message.assert_not_awaited()
    interaction.followup.send.assert_not_awaited()


@pytest.mark.parametrize("state", ["starting", "stopping", "deallocating"])
async def test_ensure_vm_running_returns_false_for_transitional_states(state):
    interaction = _make_interaction()
    azure = _make_azure(power_state=state)

    result = await ensure_vm_running(interaction, azure)

    assert result is False
    # Should have replied with a message mentioning the state.
    interaction.response.send_message.assert_awaited_once()
    call_args = interaction.response.send_message.call_args
    assert state in call_args[0][0]


@pytest.mark.parametrize("state", ["deallocated", "stopped", "unknown"])
async def test_ensure_vm_running_returns_false_for_non_running_states(state):
    interaction = _make_interaction()
    azure = _make_azure(power_state=state)

    result = await ensure_vm_running(interaction, azure)

    assert result is False
    interaction.response.send_message.assert_awaited_once()


async def test_ensure_vm_running_when_response_already_done():
    """If interaction.response is done, must use followup instead."""
    interaction = _make_interaction()
    interaction.response.is_done.return_value = True
    azure = _make_azure(power_state="deallocated")

    result = await ensure_vm_running(interaction, azure)

    assert result is False
    # send_message must NOT be called on an already-done response.
    interaction.response.send_message.assert_not_awaited()
    interaction.followup.send.assert_awaited_once()


# ---------------------------------------------------------------------------
# ensure_service_running
# ---------------------------------------------------------------------------


async def test_ensure_service_running_returns_true():
    interaction = _make_interaction()
    azure = _make_azure(service_status="Running")

    result = await ensure_service_running(interaction, azure, "my-svc")

    assert result is True


@pytest.mark.parametrize("status", ["Stopped", "Paused", "StartPending", "Unknown"])
async def test_ensure_service_running_returns_false_for_non_running(status):
    interaction = _make_interaction()
    azure = _make_azure(service_status=status)

    result = await ensure_service_running(interaction, azure, "my-svc")

    assert result is False
    interaction.response.send_message.assert_awaited_once()


async def test_ensure_service_running_message_includes_service_name():
    interaction = _make_interaction()
    azure = _make_azure(service_status="Stopped")

    await ensure_service_running(interaction, azure, "palworld-nssm")

    call_text = interaction.response.send_message.call_args[0][0]
    assert "palworld-nssm" in call_text


# ---------------------------------------------------------------------------
# run_slot
# ---------------------------------------------------------------------------


def _make_bot(*, maintenance: bool = False) -> MagicMock:
    bot = MagicMock()
    bot.state = RuntimeState()
    bot.state.maintenance = maintenance
    return bot


async def test_run_slot_yields_true_when_free():
    bot = _make_bot()
    interaction = _make_interaction()

    yielded = []
    async with run_slot(bot, interaction, "test-op") as ok:
        yielded.append(ok)
        assert bot.state.lock_held is True

    assert yielded == [True]
    assert bot.state.lock_held is False


async def test_run_slot_yields_false_and_replies_when_busy():
    bot = _make_bot()
    interaction = _make_interaction()

    yielded = []
    async with bot.state.acquire_run("already-running"):
        async with run_slot(bot, interaction, "new-op") as ok:
            yielded.append(ok)

    assert yielded == [False]
    # Should have replied with a "busy" message.
    interaction.response.send_message.assert_awaited_once()


async def test_run_slot_busy_message_includes_holder():
    bot = _make_bot()
    interaction = _make_interaction()

    async with bot.state.acquire_run("the-holder-op"):
        async with run_slot(bot, interaction, "new-op") as ok:
            pass

    call_text = interaction.response.send_message.call_args[0][0]
    assert "the-holder-op" in call_text


async def test_run_slot_releases_lock_after_body():
    bot = _make_bot()
    interaction = _make_interaction()

    async with run_slot(bot, interaction, "op-a") as ok:
        assert ok is True

    # After exiting, the lock must be free for another operation.
    async with run_slot(bot, interaction, "op-b") as ok2:
        assert ok2 is True


async def test_run_slot_releases_lock_on_exception():
    bot = _make_bot()
    interaction = _make_interaction()

    with pytest.raises(RuntimeError):
        async with run_slot(bot, interaction, "failing-op") as ok:
            assert ok is True
            raise RuntimeError("boom")

    assert bot.state.lock_held is False


async def test_run_slot_uses_followup_when_response_done():
    """When interaction.response.is_done() is True, reply via followup."""
    bot = _make_bot()
    interaction = _make_interaction()
    interaction.response.is_done.return_value = True

    async with bot.state.acquire_run("blocker"):
        async with run_slot(bot, interaction, "blocked") as ok:
            assert ok is False

    interaction.response.send_message.assert_not_awaited()
    interaction.followup.send.assert_awaited_once()
