#!/usr/bin/env python3
"""Scaffold a new Harbormaster game directory.

Usage:
    scripts/new-game.py --name Windrose

Creates `games/<slug>/` populated from `games/_template/`, then writes
the standard set of two-line wrapper scripts that delegate to the
`core/scripts/*` entry points. Refuses to overwrite an existing dir.

The `--name` value is the canonical PascalCase display name; it is
also used (lowercased) as the slug and (uppercased) as the env-var
prefix. Use `--slug`/`--env-prefix` to override either.
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

# Map of <wrapper_filename_template> -> <core_script_filename>.
# `{name}` is substituted with the PascalCase display name.
WRAPPERS: dict[str, str] = {
    "Backup-{name}.ps1":              "Backup-GameServer.ps1",
    "Check-{name}Health.ps1":         "Check-ServerHealth.ps1",
    "Check-{name}Update.ps1":         "Check-SteamUpdate.ps1",
    "Snapshot-{name}.ps1":            "Manage-Milestones.ps1",
    "Announce-{name}Online.ps1":      "Announce-ServerOnline.ps1",
    "Announce-{name}Shutdown.ps1":    "Announce-ServerShutdown.ps1",
    "Restore-{name}.ps1":             "Restore-GameServer.ps1",
    "List-{name}Backups.ps1":         "List-GameBackups.ps1",
    "Get-{name}Players.ps1":          "Get-PlayerCount.ps1",
}

WRAPPER_BODY = (
    "$config = & \"$PSScriptRoot\\config.ps1\"\n"
    "& \"$PSScriptRoot\\..\\..\\core\\scripts\\{core}\" -Config $config @args\n"
)

NAME_RE = re.compile(r"^[A-Z][A-Za-z0-9]{1,39}$")
SLUG_RE = re.compile(r"^[a-z][a-z0-9]{1,39}$")


def render_config(template: str, name: str, slug: str, env_prefix: str) -> str:
    """Replace template placeholders in `_template/config.ps1`."""
    return (
        template.replace("<DisplayName>", name)
                .replace("<ENV_PREFIX>", env_prefix)
                .replace("<SteamAppId>", "<fill-in>")
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--name", required=True,
                   help="PascalCase display name, e.g. Windrose")
    p.add_argument("--slug",
                   help="Lowercase slug for the directory; defaults to name.lower()")
    p.add_argument("--env-prefix",
                   help="UPPERCASE env-var prefix; defaults to name.upper()")
    p.add_argument("--repo-root",
                   help="Override repo root (default: parent of this script's dir)")
    args = p.parse_args(argv)

    name = args.name
    if not NAME_RE.match(name):
        print(f"error: --name {name!r} must match {NAME_RE.pattern}", file=sys.stderr)
        return 2

    slug = args.slug or name.lower()
    if not SLUG_RE.match(slug):
        print(f"error: --slug {slug!r} must match {SLUG_RE.pattern}", file=sys.stderr)
        return 2

    env_prefix = args.env_prefix or name.upper()
    if not re.match(r"^[A-Z][A-Z0-9_]{1,39}$", env_prefix):
        print(f"error: invalid --env-prefix {env_prefix!r}", file=sys.stderr)
        return 2

    repo_root = (
        Path(args.repo_root).resolve() if args.repo_root
        else Path(__file__).resolve().parent.parent
    )
    template_dir = repo_root / "games" / "_template"
    target_dir = repo_root / "games" / slug

    if not template_dir.is_dir():
        print(f"error: template not found at {template_dir}", file=sys.stderr)
        return 1
    if target_dir.exists():
        print(f"error: {target_dir} already exists; refusing to overwrite",
              file=sys.stderr)
        return 1

    # Copy template (config.ps1 + README.md) -----------------------------
    target_dir.mkdir(parents=True)
    cfg_text = (template_dir / "config.ps1").read_text(encoding="utf-8")
    (target_dir / "config.ps1").write_text(
        render_config(cfg_text, name=name, slug=slug, env_prefix=env_prefix),
        encoding="utf-8",
    )
    readme = template_dir / "README.md"
    if readme.is_file():
        shutil.copy2(readme, target_dir / "README.md")

    # Generate wrappers --------------------------------------------------
    for tmpl, core in WRAPPERS.items():
        wrapper_path = target_dir / tmpl.format(name=name)
        wrapper_path.write_text(
            WRAPPER_BODY.format(core=core),
            encoding="utf-8",
        )

    print(f"Created {target_dir.relative_to(repo_root)} with "
          f"{len(WRAPPERS)} wrapper scripts.")
    print("")
    print("Next steps:")
    print(f"  1. Edit games/{slug}/config.ps1 (SteamAppId, StorageAccount, "
          "BlobContainer, etc.).")
    print(f"  2. Copy games/{slug}/ to C:\\Scripts\\harbormaster\\games\\{slug}\\ "
          "on the VM.")
    print("  3. Set the runtime env vars (Discord webhooks, Healthchecks "
          f"ping URLs) using the {env_prefix}_* prefix.")
    print(f"  4. Configure the bot's game.* block to point at this slug.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
