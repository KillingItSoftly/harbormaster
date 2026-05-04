"""Tests for harbormaster_bot.cogs.snapshot — LABEL_RE pattern validation."""
from __future__ import annotations

import pytest

from harbormaster_bot.cogs.snapshot import LABEL_RE


# ---------------------------------------------------------------------------
# Valid snapshot labels
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "label",
    [
        "v1",
        "before-update",
        "post_patch",
        "A" * 50,          # exactly 50 chars — at max length
        "abc123",
        "My-Label_01",
        "a",               # single character minimum
        "UPPERCASE",
        "mix3d-CASE_label",
    ],
)
def test_valid_labels(label):
    assert LABEL_RE.fullmatch(label), f"Expected {label!r} to match LABEL_RE"


# ---------------------------------------------------------------------------
# Invalid labels
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "label",
    [
        "",                 # empty
        "A" * 51,          # too long (> 50 chars)
        "has space",        # space — injection risk in PowerShell
        "has'quote",        # single quote — PowerShell injection
        'has"dquote',       # double quote
        "has`backtick",     # backtick — PowerShell string interpolation
        "has.dot",          # dot not in allowlist
        "has/slash",        # slash
        "has\\backslash",   # backslash
        "has@at",           # @ not in allowlist
        "has!bang",         # ! not in allowlist
    ],
)
def test_invalid_labels(label):
    assert not LABEL_RE.fullmatch(label), f"Expected {label!r} NOT to match LABEL_RE"


# ---------------------------------------------------------------------------
# Security — injection characters explicitly blocked
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "injection",
    [
        "'; Get-Process",     # PS injection via quote break
        "$(whoami)",          # subshell / PS expansion
        "`nStart-Process",    # PS escape char
        "label\ninjection",   # newline in label
        "label\x00null",      # null byte
    ],
)
def test_injection_labels_rejected(injection):
    assert not LABEL_RE.fullmatch(injection)
