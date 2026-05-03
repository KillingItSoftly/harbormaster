from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class DiscordConfig:
    guild_id: int
    player_role_id: int
    admin_role_id: int
    status_channel_id: int | None


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

    status_channel = d.get("status_channel_id")
    return BotConfig(
        discord=DiscordConfig(
            guild_id=int(d["guild_id"]),
            player_role_id=int(d["player_role_id"]),
            admin_role_id=int(d["admin_role_id"]),
            status_channel_id=int(status_channel) if status_channel else None,
        ),
        azure=AzureConfig(
            subscription_id=a["subscription_id"],
            resource_group=a["resource_group"],
            vm_name=a["vm_name"],
        ),
        game=GameConfig(
            name=g["name"],
            service_name=g["service_name"],
            script_dir=g["script_dir"],
            log_path=g["log_path"],
        ),
        rate_limit_seconds=int(raw.get("rate_limit_seconds", 30)),
    )
