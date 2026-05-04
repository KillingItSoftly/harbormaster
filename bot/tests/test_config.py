"""Tests for harbormaster_bot.config — load_config() and security validators."""
from __future__ import annotations

import os
import textwrap
from pathlib import Path

import pytest
import yaml

from harbormaster_bot.config import (
    AzureConfig,
    BotConfig,
    DiscordConfig,
    GameConfig,
    load_config,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_YAML = textwrap.dedent(
    """\
    discord:
      guild_id: 111111111111111111
      player_role_id: 222222222222222222
      admin_role_id: 333333333333333333
      status_channel_id: 444444444444444444
      audit_channel_id: 555555555555555555
    azure:
      subscription_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
      resource_group: "rg-gameservers"
      vm_name: "vm-palworld"
    game:
      name: "Palworld"
      service_name: "palworld-nssm"
      script_dir: "C:\\\\Harbormaster\\\\Palworld"
      log_path: "C:\\\\Servers\\\\Palworld\\\\logs\\\\server.log"
    rate_limit_seconds: 45
    rate_limit_overrides:
      "server stop": 120
      "update apply": 300
    """
)


def _make_config(overrides: dict | None = None) -> dict:
    """Return a base config dict, optionally patching in `overrides`."""
    cfg = yaml.safe_load(_VALID_YAML)
    if overrides:
        for key_path, value in overrides.items():
            parts = key_path.split(".")
            node = cfg
            for part in parts[:-1]:
                node = node[part]
            node[parts[-1]] = value
    return cfg


def _load_from_inline(raw: dict) -> BotConfig:
    """Inject a raw dict as HARBORMASTER_CONFIG_YAML and call load_config."""
    os.environ["HARBORMASTER_CONFIG_YAML"] = yaml.dump(raw)
    try:
        return load_config()
    finally:
        del os.environ["HARBORMASTER_CONFIG_YAML"]


# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------


def test_load_config_inline_happy_path():
    cfg = _load_from_inline(_make_config())

    assert isinstance(cfg, BotConfig)
    assert isinstance(cfg.discord, DiscordConfig)
    assert isinstance(cfg.azure, AzureConfig)
    assert isinstance(cfg.game, GameConfig)


def test_discord_fields_parsed():
    cfg = _load_from_inline(_make_config())

    assert cfg.discord.guild_id == 111111111111111111
    assert cfg.discord.player_role_id == 222222222222222222
    assert cfg.discord.admin_role_id == 333333333333333333
    assert cfg.discord.status_channel_id == 444444444444444444
    assert cfg.discord.audit_channel_id == 555555555555555555


def test_azure_fields_parsed():
    cfg = _load_from_inline(_make_config())

    assert cfg.azure.subscription_id == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    assert cfg.azure.resource_group == "rg-gameservers"
    assert cfg.azure.vm_name == "vm-palworld"


def test_game_fields_parsed():
    cfg = _load_from_inline(_make_config())

    assert cfg.game.name == "Palworld"
    assert cfg.game.service_name == "palworld-nssm"
    assert cfg.game.script_dir == "C:\\Harbormaster\\Palworld"
    assert cfg.game.log_path == "C:\\Servers\\Palworld\\logs\\server.log"


def test_rate_limit_and_overrides_parsed():
    cfg = _load_from_inline(_make_config())

    assert cfg.rate_limit_seconds == 45
    assert cfg.rate_limit_overrides == {"server stop": 120, "update apply": 300}


def test_optional_channel_ids_absent():
    raw = _make_config()
    del raw["discord"]["status_channel_id"]
    del raw["discord"]["audit_channel_id"]
    cfg = _load_from_inline(raw)

    assert cfg.discord.status_channel_id is None
    assert cfg.discord.audit_channel_id is None


def test_rate_limit_defaults_to_30():
    raw = _make_config()
    del raw["rate_limit_seconds"]
    cfg = _load_from_inline(raw)

    assert cfg.rate_limit_seconds == 30


def test_rate_limit_overrides_absent_gives_none():
    raw = _make_config()
    del raw["rate_limit_overrides"]
    cfg = _load_from_inline(raw)

    assert cfg.rate_limit_overrides is None


def test_load_config_from_file(tmp_path: Path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(_VALID_YAML, encoding="utf-8")

    # Make sure inline env var is NOT set.
    os.environ.pop("HARBORMASTER_CONFIG_YAML", None)
    cfg = load_config(config_file)

    assert cfg.game.name == "Palworld"


def test_load_config_from_env_path(tmp_path: Path, monkeypatch):
    config_file = tmp_path / "cfg.yaml"
    config_file.write_text(_VALID_YAML, encoding="utf-8")
    monkeypatch.setenv("HARBORMASTER_CONFIG", str(config_file))
    monkeypatch.delenv("HARBORMASTER_CONFIG_YAML", raising=False)

    cfg = load_config()
    assert cfg.game.name == "Palworld"


# ---------------------------------------------------------------------------
# game.name validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "Palworld",
        "MyGame",
        "A1",
        "A" + "b" * 40,  # 41 chars — at max
    ],
)
def test_valid_game_names(name):
    raw = _make_config({"game.name": name})
    cfg = _load_from_inline(raw)
    assert cfg.game.name == name


@pytest.mark.parametrize(
    "name",
    [
        "",             # empty
        "1Invalid",     # starts with digit
        "my game",      # space
        "name'quote",   # single quote (injection risk)
        "name`backtick",# backtick (injection risk)
        "a" * 42,       # too long (>41 chars)
    ],
)
def test_invalid_game_name_raises(name):
    raw = _make_config({"game.name": name})
    with pytest.raises(ValueError, match="game.name"):
        _load_from_inline(raw)


# ---------------------------------------------------------------------------
# game.service_name validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "svc",
    [
        "palworld-nssm",
        "my_service.01",
        "X" * 80,       # exactly 80 chars
    ],
)
def test_valid_service_names(svc):
    raw = _make_config({"game.service_name": svc})
    cfg = _load_from_inline(raw)
    assert cfg.game.service_name == svc


@pytest.mark.parametrize(
    "svc",
    [
        "",             # empty
        "bad service",  # space
        "bad'quote",    # single quote
        "bad`tick",     # backtick
        "X" * 81,       # too long
    ],
)
def test_invalid_service_name_raises(svc):
    raw = _make_config({"game.service_name": svc})
    with pytest.raises(ValueError, match="game.service_name"):
        _load_from_inline(raw)


# ---------------------------------------------------------------------------
# game.script_dir and game.log_path validation (Windows path)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        r"C:\Harbormaster\Palworld",
        r"D:/Servers/Game",
        r"C:\Path With Spaces\OK",
    ],
)
def test_valid_win_paths_script_dir(path):
    raw = _make_config({"game.script_dir": path})
    cfg = _load_from_inline(raw)
    assert cfg.game.script_dir == path


@pytest.mark.parametrize(
    "path",
    [
        r"relative\path",                  # no drive letter
        r"C:\bad'quote\path",              # single quote
        r'C:\bad"quote\path',              # double quote
        "C:\\bad`tick\\path",              # backtick
        "",                                # empty
        r"C:no-backslash",                 # no separator after colon
    ],
)
def test_invalid_win_path_raises(path):
    raw = _make_config({"game.script_dir": path})
    with pytest.raises(ValueError, match="game.script_dir"):
        _load_from_inline(raw)
