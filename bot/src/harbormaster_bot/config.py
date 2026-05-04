from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

# Allowlist for values that get interpolated into PowerShell strings.
# A single quote or backtick in any of these would let an operator with
# config-write access pivot to arbitrary script execution on the VM.
_SAFE_SERVICE_NAME = re.compile(r"^[A-Za-z0-9_.\-]{1,80}$")
# Windows path: drive letter, then any of the usual filesystem chars,
# but explicitly NO single quotes, double quotes, or backticks.
_SAFE_WIN_PATH = re.compile(r"^[A-Za-z]:[\\/][^'\"`\n\r]{1,260}$")
_SAFE_GAME_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9]{0,40}$")


@dataclass(frozen=True)
class DiscordConfig:
    guild_id: int
    player_role_id: int
    admin_role_id: int
    status_channel_id: int | None
    audit_channel_id: int | None = None


@dataclass(frozen=True)
class AzureConfig:
    subscription_id: str
    resource_group: str
    vm_name: str


@dataclass(frozen=True)
class GameConfig:
    name: str
    service_name: str
    script_dir: str
    log_path: str


@dataclass(frozen=True)
class BotConfig:
    discord: DiscordConfig
    azure: AzureConfig
    game: GameConfig
    rate_limit_seconds: int = 30
    # Per-command cooldown overrides keyed by qualified command name
    # (e.g. "server stop", "update apply"). Falls back to rate_limit_seconds.
    rate_limit_overrides: dict[str, int] | None = None


def load_config(path: str | Path | None = None) -> BotConfig:
    """Load config from HARBORMASTER_CONFIG_YAML (inline) or a YAML file.

    Container-Apps deployments inject the entire YAML as a single secret env
    var (HARBORMASTER_CONFIG_YAML). Local dev uses the file at
    HARBORMASTER_CONFIG (defaults to ./config.yaml).
    """
    inline = os.environ.get("HARBORMASTER_CONFIG_YAML")
    if inline:
        raw: dict[str, Any] = yaml.safe_load(inline)
    else:
        resolved = path or os.environ.get("HARBORMASTER_CONFIG", "config.yaml")
        with open(resolved, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)

    d = raw["discord"]
    a = raw["azure"]
    g = raw["game"]

    # --- Validate values that get interpolated into PowerShell ----------
    # If any of these fail, the bot refuses to start. Bad config caught
    # at boot is much better than a Discord-driven RCE later.
    game_name = str(g["name"])
    if not _SAFE_GAME_NAME.match(game_name):
        raise ValueError(
            f"game.name {game_name!r} must match {_SAFE_GAME_NAME.pattern}"
        )
    service_name = str(g["service_name"])
    if not _SAFE_SERVICE_NAME.match(service_name):
        raise ValueError(
            f"game.service_name {service_name!r} must match {_SAFE_SERVICE_NAME.pattern}"
        )
    script_dir = str(g["script_dir"])
    if not _SAFE_WIN_PATH.match(script_dir):
        raise ValueError(
            f"game.script_dir {script_dir!r} must be a Windows path with no quotes/backticks"
        )
    log_path = str(g["log_path"])
    if not _SAFE_WIN_PATH.match(log_path):
        raise ValueError(
            f"game.log_path {log_path!r} must be a Windows path with no quotes/backticks"
        )

    status_channel = d.get("status_channel_id")
    audit_channel = d.get("audit_channel_id")
    overrides_raw = raw.get("rate_limit_overrides") or {}
    overrides = {str(k): int(v) for k, v in overrides_raw.items()}
    return BotConfig(
        discord=DiscordConfig(
            guild_id=int(d["guild_id"]),
            player_role_id=int(d["player_role_id"]),
            admin_role_id=int(d["admin_role_id"]),
            status_channel_id=int(status_channel) if status_channel else None,
            audit_channel_id=int(audit_channel) if audit_channel else None,
        ),
        azure=AzureConfig(
            subscription_id=a["subscription_id"],
            resource_group=a["resource_group"],
            vm_name=a["vm_name"],
        ),
        game=GameConfig(
            name=game_name,
            service_name=service_name,
            script_dir=script_dir,
            log_path=log_path,
        ),
        rate_limit_seconds=int(raw.get("rate_limit_seconds", 30)),
        rate_limit_overrides=overrides or None,
    )
