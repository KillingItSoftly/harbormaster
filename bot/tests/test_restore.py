"""Tests for harbormaster_bot.cogs.restore — _BLOB_NAME_RE pattern validation."""
from __future__ import annotations

import pytest

from harbormaster_bot.cogs.restore import _BLOB_NAME_RE


# ---------------------------------------------------------------------------
# Valid backup blob names (regular backup naming convention)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "palworld_2024-01-15_1430.zip",
        "mygame_2023-12-31_0000.zip",
        "ab_2024-06-01_2359.zip",  # minimal game prefix
        "savegamedata_2025-03-22_1200.zip",
    ],
)
def test_valid_regular_backup_names(name):
    assert _BLOB_NAME_RE.match(name), f"Expected {name!r} to match"


# ---------------------------------------------------------------------------
# Valid milestone blob names
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "milestone_pristine_initial-setup_2024-01-01_0000.zip",
        "milestone_pre-change_before-update_2024-06-15_1530.zip",
        "milestone_stable_v1-2-3_2023-11-20_0830.zip",
        "milestone_general_my-label_2024-07-04_1200.zip",
        "milestone_stable_AB_2024-01-01_1200.zip",  # short label
        "milestone_pristine_label123_2024-01-01_0000.zip",  # numeric in label
    ],
)
def test_valid_milestone_names(name):
    assert _BLOB_NAME_RE.match(name), f"Expected {name!r} to match"


# ---------------------------------------------------------------------------
# Invalid names — wrong structure
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "",                                        # empty
        "palworld_2024-01-15_1430.tar.gz",         # wrong extension
        "palworld_2024-01-15_1430",                # no extension
        "2024-01-15_1430.zip",                     # starts with date, no game name
        "palworld_2024-01-15.zip",                 # missing time part
        "palworld_20240115_1430.zip",              # date not in YYYY-MM-DD format
        "PALWORLD_2024-01-15_1430.zip",            # uppercase game prefix (first alternative requires [a-z])
        "Milestone_pristine_label_2024-01-01_0000.zip",  # uppercase M — not milestone prefix
        "milestone_unknown_label_2024-01-01_0000.zip",  # invalid category
        "milestone_stable_bad label_2024-01-01_0000.zip",  # space in label
        "milestone_stable__2024-01-01_0000.zip",   # empty label (double underscore)
        "../../../evil.zip",                       # path traversal
        "palworld_2024-01-15_1430.zip; rm -rf /",  # shell injection
        "palworld_2024-01-15_14:30.zip",           # colon in time (invalid)
    ],
)
def test_invalid_blob_names_rejected(name):
    assert not _BLOB_NAME_RE.match(name), f"Expected {name!r} NOT to match"


# ---------------------------------------------------------------------------
# Security — injection characters must not match
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "dangerous_name",
    [
        "palworld_2024-01-15_1430.zip'; DROP TABLE backups;--",
        "palworld_2024-01-15_1430.zip`whoami`",
        "palworld_2024-01-15_1430.zip$(evil)",
    ],
)
def test_injection_characters_rejected(dangerous_name):
    assert not _BLOB_NAME_RE.match(dangerous_name)
