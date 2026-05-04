"""Tests for harbormaster_bot.views — confirm_prompt and ConfirmView."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from harbormaster_bot.views import ConfirmView, confirm_prompt


# ---------------------------------------------------------------------------
# confirm_prompt — pure string builder
# ---------------------------------------------------------------------------


def test_confirm_prompt_basic():
    text = confirm_prompt("Delete everything")
    assert "Delete everything" in text
    assert "cannot be undone" in text


def test_confirm_prompt_includes_warning_prefix():
    text = confirm_prompt("Do something dangerous")
    assert ":warning:" in text


def test_confirm_prompt_includes_details():
    text = confirm_prompt("Stop server", [("VM", "vm-palworld"), ("Service", "svc")])
    assert "VM" in text
    assert "vm-palworld" in text
    assert "Service" in text
    assert "svc" in text


def test_confirm_prompt_no_details():
    text = confirm_prompt("Simple action")
    # Should still include the standard footer.
    assert "cannot be undone" in text


def test_confirm_prompt_multiple_detail_lines():
    details = [("A", "1"), ("B", "2"), ("C", "3")]
    text = confirm_prompt("Action", details)
    for label, value in details:
        assert label in text
        assert value in text


# ---------------------------------------------------------------------------
# ConfirmView — initialisation
# ---------------------------------------------------------------------------


def test_confirm_view_initial_state():
    view = ConfirmView(user_id=42)
    assert view.confirmed is False
    assert view.user_id == 42


def test_confirm_view_custom_timeout():
    view = ConfirmView(user_id=1, timeout=60)
    assert view.timeout == 60


# ---------------------------------------------------------------------------
# ConfirmView._guard — ownership and already-decided checks
# ---------------------------------------------------------------------------


def _make_interaction(user_id: int) -> MagicMock:
    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = MagicMock()
    interaction.user.id = user_id
    # Plain MagicMock so is_done() returns a real bool, not an awaitable.
    interaction.response = MagicMock()
    interaction.response.is_done.return_value = False
    interaction.response.send_message = AsyncMock()
    return interaction


async def test_guard_allows_owner():
    view = ConfirmView(user_id=123)
    interaction = _make_interaction(user_id=123)

    result = await view._guard(interaction)

    assert result is True
    interaction.response.send_message.assert_not_awaited()


async def test_guard_rejects_other_user():
    view = ConfirmView(user_id=123)
    interaction = _make_interaction(user_id=456)

    result = await view._guard(interaction)

    assert result is False
    interaction.response.send_message.assert_awaited_once()


async def test_guard_rejects_already_decided():
    view = ConfirmView(user_id=123)
    view._decided = True
    interaction = _make_interaction(user_id=123)

    result = await view._guard(interaction)

    assert result is False
    interaction.response.send_message.assert_awaited_once()


# ---------------------------------------------------------------------------
# ConfirmView._confirm
# ---------------------------------------------------------------------------


async def test_confirm_button_sets_confirmed():
    view = ConfirmView(user_id=7)
    interaction = _make_interaction(user_id=7)
    # edit_message is called to visually disable buttons.
    interaction.response.edit_message = AsyncMock()

    await view._confirm.callback(interaction)

    assert view.confirmed is True
    assert view._decided is True


async def test_confirm_button_disables_all_buttons():
    view = ConfirmView(user_id=7)
    interaction = _make_interaction(user_id=7)
    interaction.response.edit_message = AsyncMock()

    await view._confirm.callback(interaction)

    for child in view.children:
        if isinstance(child, discord.ui.Button):
            assert child.disabled is True


async def test_confirm_button_wrong_user_does_not_confirm():
    view = ConfirmView(user_id=7)
    interaction = _make_interaction(user_id=99)

    await view._confirm.callback(interaction)

    assert view.confirmed is False


# ---------------------------------------------------------------------------
# ConfirmView._cancel
# ---------------------------------------------------------------------------


async def test_cancel_button_does_not_set_confirmed():
    view = ConfirmView(user_id=7)
    interaction = _make_interaction(user_id=7)
    interaction.response.edit_message = AsyncMock()

    await view._cancel.callback(interaction)

    assert view.confirmed is False
    assert view._decided is True


async def test_cancel_button_wrong_user_ignored():
    view = ConfirmView(user_id=7)
    interaction = _make_interaction(user_id=99)

    await view._cancel.callback(interaction)

    assert view._decided is False


# ---------------------------------------------------------------------------
# ConfirmView — second-click prevention
# ---------------------------------------------------------------------------


async def test_double_confirm_is_blocked():
    view = ConfirmView(user_id=7)
    interaction = _make_interaction(user_id=7)
    interaction.response.edit_message = AsyncMock()

    await view._confirm.callback(interaction)  # first click

    # Reset the response mock so we can verify what the second click does.
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    interaction.user.id = 7  # preserve ownership

    await view._confirm.callback(interaction)  # second click — must be blocked

    # Guard should have sent a "already answered" message.
    interaction.response.send_message.assert_awaited_once()


async def test_edit_message_http_exception_falls_back_to_defer():
    """If edit_message raises HTTPException, _confirm falls back to defer()."""
    view = ConfirmView(user_id=7)
    interaction = _make_interaction(user_id=7)
    interaction.response.edit_message = AsyncMock(
        side_effect=discord.HTTPException(MagicMock(), "error")
    )
    interaction.response.defer = AsyncMock()

    await view._confirm.callback(interaction)

    assert view.confirmed is True
    interaction.response.defer.assert_awaited_once()
