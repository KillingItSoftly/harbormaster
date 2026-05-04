"""Tests for harbormaster_bot.cogs.players — parse_player_count."""
from __future__ import annotations

import pytest

from harbormaster_bot.cogs.players import parse_player_count


# ---------------------------------------------------------------------------
# Straightforward numeric outputs
# ---------------------------------------------------------------------------


def test_parse_zero():
    assert parse_player_count("0") == 0


def test_parse_positive_integer():
    assert parse_player_count("7") == 7


def test_parse_large_number():
    assert parse_player_count("100") == 100


# ---------------------------------------------------------------------------
# Whitespace handling
# ---------------------------------------------------------------------------


def test_parse_strips_trailing_newline():
    assert parse_player_count("3\n") == 3


def test_parse_strips_surrounding_whitespace():
    assert parse_player_count("  5  ") == 5


def test_parse_multi_line_takes_last_non_empty():
    """Azure SDK noise before the answer — only last line counts."""
    text = "WARNING: some noise\nConnecting to Azure…\n4"
    assert parse_player_count(text) == 4


def test_parse_trailing_blank_lines_ignored():
    assert parse_player_count("2\n\n\n") == 2


# ---------------------------------------------------------------------------
# Unknown / unparseable outputs
# ---------------------------------------------------------------------------


def test_parse_unknown_keyword_returns_none():
    assert parse_player_count("unknown") is None


def test_parse_unknown_case_insensitive():
    assert parse_player_count("UNKNOWN") is None


def test_parse_empty_string_returns_none():
    assert parse_player_count("") is None


def test_parse_non_numeric_string_returns_none():
    assert parse_player_count("not a number") is None


def test_parse_float_string_returns_none():
    assert parse_player_count("3.5") is None


def test_parse_mixed_noise_then_unknown():
    text = "INFO: server ok\nunknown"
    assert parse_player_count(text) is None


def test_parse_mixed_noise_then_parseable():
    text = "INFO: server ok\n12"
    assert parse_player_count(text) == 12


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_parse_all_blank_lines_returns_none():
    assert parse_player_count("\n\n\n") is None


def test_parse_negative_number():
    # Negative is not a valid player count; int() will parse it but callers
    # gate on count > 0, so we just confirm what the parser does.
    result = parse_player_count("-1")
    assert result == -1


def test_parse_only_whitespace_lines_returns_none():
    assert parse_player_count("   \n   \n   ") is None
