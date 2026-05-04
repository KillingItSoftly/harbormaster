"""Tests for harbormaster_bot.state — RuntimeState, BusyError, acquire_run."""
from __future__ import annotations

import asyncio

import pytest

from harbormaster_bot.state import BusyError, RuntimeState


# ---------------------------------------------------------------------------
# BusyError
# ---------------------------------------------------------------------------


def test_busy_error_stores_holder():
    err = BusyError("backup")
    assert err.holder == "backup"


def test_busy_error_is_runtime_error():
    assert isinstance(BusyError("x"), RuntimeError)


def test_busy_error_message_contains_holder():
    err = BusyError("update apply")
    assert "update apply" in str(err)


# ---------------------------------------------------------------------------
# RuntimeState — construction and defaults
# ---------------------------------------------------------------------------


def test_runtime_state_defaults():
    state = RuntimeState()
    assert state.maintenance is False
    assert state.last_health_ts == 0.0
    assert state.last_health_ok is False
    assert state.lock_holder is None
    assert state.lock_held is False


# ---------------------------------------------------------------------------
# RuntimeState — acquire_run happy path
# ---------------------------------------------------------------------------


async def test_acquire_run_yields_and_releases():
    state = RuntimeState()

    async with state.acquire_run("test-op"):
        assert state.lock_held is True
        assert state.lock_holder == "test-op"

    assert state.lock_held is False
    assert state.lock_holder is None


async def test_acquire_run_can_be_reacquired_after_release():
    state = RuntimeState()

    async with state.acquire_run("op-1"):
        pass

    # Should succeed a second time because the lock was released.
    async with state.acquire_run("op-2"):
        assert state.lock_holder == "op-2"


# ---------------------------------------------------------------------------
# RuntimeState — acquire_run conflict (BusyError)
# ---------------------------------------------------------------------------


async def test_acquire_run_raises_busy_when_locked():
    state = RuntimeState()

    async with state.acquire_run("outer"):
        with pytest.raises(BusyError) as exc_info:
            async with state.acquire_run("inner"):
                pass  # never reached

    assert exc_info.value.holder == "outer"


async def test_acquire_run_busy_error_holder_is_first_holder():
    state = RuntimeState()

    async with state.acquire_run("first-holder"):
        with pytest.raises(BusyError) as exc_info:
            # Attempt two nested conflicting acquisitions — only the first
            # holder matters.
            async with state.acquire_run("second-attempt"):
                pass

    assert exc_info.value.holder == "first-holder"


# ---------------------------------------------------------------------------
# RuntimeState — lock released on exception inside context
# ---------------------------------------------------------------------------


async def test_acquire_run_releases_on_exception():
    state = RuntimeState()

    with pytest.raises(ValueError):
        async with state.acquire_run("failing-op"):
            raise ValueError("boom")

    # Lock MUST be released even though the body raised.
    assert state.lock_held is False
    assert state.lock_holder is None


# ---------------------------------------------------------------------------
# RuntimeState — maintenance flag
# ---------------------------------------------------------------------------


def test_maintenance_flag_can_be_toggled():
    state = RuntimeState()
    assert state.maintenance is False

    state.maintenance = True
    assert state.maintenance is True

    state.maintenance = False
    assert state.maintenance is False


# ---------------------------------------------------------------------------
# RuntimeState — health-check fields
# ---------------------------------------------------------------------------


def test_health_fields_can_be_updated():
    state = RuntimeState()
    state.last_health_ts = 12345.0
    state.last_health_ok = True

    assert state.last_health_ts == 12345.0
    assert state.last_health_ok is True
