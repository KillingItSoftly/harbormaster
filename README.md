# Harbormaster ⚓

> Self-hosting toolkit for Windows game servers on Azure: NSSM service wrapping, Steam update checks, blob-backed snapshots, Discord alerts, and Healthchecks heartbeats.

Harbormaster is a collection of PowerShell scripts and modules for managing self-hosted Windows game servers — the kind you run on a cloud VM for a handful of friends. It handles the tedious parts: keeping the server running as a service, snapshotting saves before risky changes, checking for game updates, alerting you on Discord when something breaks, and verifying via [Healthchecks.io](https://healthchecks.io) that the automation itself is still running.

Originally built for a Windrose dedicated server on Azure, but designed so the core can be reused for any Windows game server you'd want to keep online without babysitting it.

---

## What it does

- **Wraps the game server as a Windows service** via [NSSM](https://nssm.cc/), so it auto-starts on boot, auto-restarts on crash, and rotates logs to disk.
- **Snapshots save data on demand** to local disk and Azure Blob Storage, with categorized retention (pristine kept forever, pre-change 90 days, etc.).
- **Backs up daily** with a separate rolling retention (14 days local, 30 days blob).
- **Checks Steam for game updates** using a public Steam API mirror, optionally applying them after taking a snapshot.
- **Alerts on Discord** when something breaks, splitting between an alerts channel (you keep notifications on) and a status channel (low-priority confirmations).
- **Heartbeats to Healthchecks.io** so you find out within minutes when an automation task stops running — not when you eventually need it.
- **Manages cost** with VM auto-shutdown / auto-start schedules via Azure Automation.

## What it isn't

- A multi-tenant hosting panel (use [Pterodactyl](https://pterodactyl.io) if you need that).
- A Linux toolkit. Game servers it's built for are Windows-only binaries.
- A turnkey solution. Expect to read scripts and adjust paths, build IDs, and configs for your specific game.

---

## Architecture

harbormaster/
├── core/                          # Game-agnostic modules and scripts
│   ├── modules/
│   │   ├── HarbormasterNotify.psm1        # Discord webhook notifications
│   │   └── HarbormasterHealthchecks.psm1  # Healthchecks.io heartbeats
│   ├── scripts/
│   │   ├── Manage-Milestones.ps1          # Snapshot save data with retention
│   │   ├── Check-SteamUpdate.ps1          # Compare installed vs current build
│   │   ├── Check-ServerHealth.ps1         # NSSM service + crash + disk checks
│   │   └── Backup-GameServer.ps1          # Daily backup with blob upload
│   └── docs/
│       ├── azure-vm-setup.md
│       ├── nssm-service-pattern.md
│       ├── healthchecks-cron.md
│       └── discord-channels.md
├── games/
│   ├── windrose/                          # Windrose-specific configuration
│   │   ├── README.md
│   │   ├── config.ps1
│   │   └── examples/
│   │       └── world-easy-mode.json
│   └── _template/                         # Boilerplate for new games
│       ├── README.md
│       └── config.ps1
├── azure/
│   └── runbooks/
│       ├── start-vm.ps1
│       └── stop-vm.ps1
└── examples/
├── healthchecks-setup.md
└── scheduled-tasks.ps1

The core/ vs games/ split is the key idea. Each game gets a small folder with its specific config (paths, Steam app id, service name, game-specific quirks). The heavy lifting lives in core/ and gets reused.

---

## Setup

### Prerequisites

- A Windows VM (Windows Server 2019/2022 or Windows 10/11 desktop)
- An Azure subscription if using blob backups, runbooks, or VM scheduling
- A Discord server (for notifications) and a [Healthchecks.io](https://healthchecks.io) account (free tier is plenty)
- PowerShell 5.1 (built into modern Windows) or PowerShell 7+

### First-time installation

See [docs/first-time-setup.md](core/docs/first-time-setup.md) for the full walk-through. The short version:

1. Install [SteamCMD](https://developer.valvesoftware.com/wiki/SteamCMD) and the game's dedicated server binaries
2. Install [NSSM](https://nssm.cc/) and wrap the server as a Windows service
3. Clone this repo to `C:\Scripts\harbormaster\`
4. Copy `.env.example` to `.env` and fill in your webhook and ping URLs (or set them as machine env vars)
5. Edit `games/<your-game>/config.ps1` with your paths, app id, and service name
6. Register the scheduled tasks (see `examples/scheduled-tasks.ps1`)

### Per-game setup

Each game has its own folder under `games/`. To add a new game:

1. Copy `games/_template/` to `games/<your-game>/`
2. Fill in `config.ps1` with the game's paths, Steam app id, service name, etc.
3. Add any game-specific scripts (most setups don't need any — the core scripts handle most cases)

---

## How the pieces fit together

### Notifications (Discord)

Two modules drive all the alerting:

- `HarbormasterNotify` — sends formatted Discord embeds with severity levels (Critical / Warning / Info / Success). Configurable per-channel via env vars.
- `HarbormasterHealthchecks` — pings Healthchecks.io endpoints with start / success / fail signals. Catches missing pings the notification module can't.

Together they cover both "something went wrong while running" (Discord) and "the script that was supposed to alert me stopped running" (Healthchecks).

### Snapshots and backups

Two flavors of save preservation, with distinct purposes:

- **Daily backups** — rolling, ephemeral, kept for ~14 days local and ~30 days blob. Recovery point for routine "yesterday was fine, today is broken."
- **Milestone snapshots** — manual, categorized, longer retention. Anchor points for risky changes (mod installs, version updates, major edits). Can be marked `pristine` for "never auto-prune."

Both end up in the same Azure Blob container under different prefixes, so you have one place to look when restoring.

### Update checks

Steam doesn't expose a free public API for build IDs, but [steamcmd.net](https://steamcmd.net) does. The update check compares the build ID in your local `appmanifest_<appid>.acf` against the current public branch. Optional auto-apply takes a milestone snapshot first, then runs SteamCMD to install.

### Health checks

Runs every 15 minutes via Task Scheduler. Catches:

- Service not running for >10 minutes
- Multiple crash traces in the last hour
- Daily backup hasn't run in >26 hours
- Disk space below configurable thresholds

Uses a state file to avoid spamming the same alert repeatedly — each issue has its own cooldown.

---

## Configuration

All sensitive values live in environment variables. See [.env.example](.env.example) for the full list. The two modules look up env vars at call time, not import time, so you can rotate webhooks or ping URLs without restarting anything.

### Environment variable naming

- `<GAME>_WEBHOOK_<CHANNEL>` — Discord webhook for a given game/channel combo
- `<GAME>_HC_<TASK>[_<DAYBUCKET>]` — Healthchecks.io ping URL for a given task

For example: `WINDROSE_WEBHOOK_ALERTS`, `WINDROSE_HC_BACKUP`, `WINDROSE_HC_HEALTH_WEEKDAY`.

The day-bucket suffix (`_WEEKDAY` / `_WEEKEND`) is used for tasks whose schedule differs by day — Healthchecks's cron expressions can't span both directly, so you create two checks and the scripts pick the right one based on `Get-Date`.

---

## Status

This is a personal toolkit, not a polished product. Scripts are documented and tested in production for one game on one VM. Expect to read code before running it.

## License

MIT. See [LICENSE](LICENSE).

## Why "harbormaster"?

The harbormaster manages ships coming and going from a port — knows when each is due, who's overdue, what state they're in. A fitting metaphor for managing a fleet of game servers, even if your fleet is just one.