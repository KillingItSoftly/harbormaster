"""Shared pytest fixtures for the harbormaster_bot test suite."""
from __future__ import annotations

import pytest

import harbormaster_bot.auth as auth_module


@pytest.fixture(autouse=True)
def clear_rate_limit_state():
    """Reset the module-level _last_invoked dict before each test.

    The dict persists for the lifetime of the process, so without this
    fixture, tests that invoke the ``requires()`` predicate with the same
    user_id + command_name can bleed cooldown state into later tests.
    """
    auth_module._last_invoked.clear()
    yield
    auth_module._last_invoked.clear()
