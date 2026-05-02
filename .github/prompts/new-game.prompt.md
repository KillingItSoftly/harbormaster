---
mode: agent
description: Scaffold a new game folder under games/ with config.ps1 and wrapper scripts that delegate to core/scripts/.
---

# New Harbormaster Game

Scaffold a new game under `games/<slug>/` so the game-agnostic scripts in
`core/scripts/` can be reused with a game-specific config and thin wrappers.

## Inputs to collect

If any of these are missing or unclear from the user's request, ask **once** in a
single consolidated question. Otherwise, infer reasonable defaults and proceed.

Required:

- **Game slug** — lowercase, no spaces (e.g. `windrose`, `valheim`). Used as the
  folder name and as the lowercased token in wrapper script filenames.
- **Game display name** — PascalCase (e.g. `Windrose`, `Valheim`). Used in
  `GameName`, in wrapper script function names, and as the suffix on wrappers
  (e.g. `Backup-Valheim.ps1`).
- **Steam App ID** — numeric.
- **Service name** — Windows service name registered via NSSM
  (e.g. `WindroseServer`).
- **Server exe path** — full path on the VM
  (e.g. `C:\GameServers\Windrose\WindroseServer.exe`). The `InstallDir` is the
  directory containing it.
- **Saved data path** — directory holding the save data to back up
  (e.g. `C:\GameServers\Windrose\R5\Saved`).

Optional (use defaults if not provided):

- **Env var prefix** — defaults to the game slug uppercased (e.g. `WINDROSE`).
- **Steam install dir** — defaults to the parent of the server exe.
- **SteamCMD path** — defaults to `C:\SteamCMD\steamcmd.exe`.
- **Log path** — defaults to `<InstallDir>\logs\server-stdout.log`.
- **Local backup root** — defaults to `C:\Backups\<DisplayName>`.
- **Storage account / blob container** — leave as `<fill-in>` placeholders if
  not provided; warn the user they must edit before first run.
- **Local retention days** — default `14`.
- **Blob retention days** — default `30`.
- **Crash log pattern** — default `'Crash Stack Trace'`.
- **Log timestamp regex** — default
  `'\[(\d{4})\.(\d{2})\.(\d{2})-(\d{2})\.(\d{2})\.(\d{2}):\d+\]'` (UE-style).

## Pre-flight checks

1. Refuse if `games/<slug>/` already exists and is non-empty. Offer to abort or
   to overwrite explicitly.
2. Refuse if the slug is `_template`.
3. Confirm the slug is lowercase, alphanumeric (with `-` allowed). Reject
   anything else.

## Files to create

All paths are relative to the workspace root. Do not modify anything outside
`games/<slug>/`.

### 1. `games/<slug>/config.ps1`

A single PowerShell hashtable returned at file scope (matches the windrose
pattern — callers do `$config = & "$PSScriptRoot\config.ps1"`):

```powershell
@{
    GameName        = '<DisplayName>'
    EnvVarPrefix    = '<ENV_PREFIX>'

    # Steam
    SteamAppId      = '<SteamAppId>'
    InstallDir      = '<InstallDir>'
    SteamCmdPath    = '<SteamCmdPath>'

    # Service
    ServiceName     = '<ServiceName>'
    ServerExePath   = '<ServerExePath>'

    # Save paths
    SavedDataPath   = '<SavedDataPath>'
    LogPath         = '<LogPath>'

    # Backups
    LocalBackupRoot = '<LocalBackupRoot>'
    StorageAccount  = '<StorageAccount>'
    BlobContainer   = '<BlobContainer>'
    LocalRetention  = <LocalRetention>
    BlobRetention   = <BlobRetention>

    # Game-specific patterns
    CrashLogPattern   = '<CrashLogPattern>'
    LogTimestampRegex = '<LogTimestampRegex>'
}
```

Substitute every `<...>` with the collected value. Strings stay quoted; numbers
must be unquoted.

### 2. Wrapper scripts

Each wrapper is a two-line file that loads the config and delegates to the
matching core script with `-Config $config`. Use the **DisplayName** suffix
for the file name (matches `games/windrose/Backup-Windrose.ps1`).

Create all four:

| Wrapper file                                  | Delegates to                                  |
| --------------------------------------------- | --------------------------------------------- |
| `games/<slug>/Backup-<DisplayName>.ps1`       | `core/scripts/Backup-GameServer.ps1`          |
| `games/<slug>/Check-<DisplayName>Health.ps1`  | `core/scripts/Check-ServerHealth.ps1`         |
| `games/<slug>/Check-<DisplayName>Update.ps1`  | `core/scripts/Check-SteamUpdate.ps1`          |
| `games/<slug>/Manage-<DisplayName>Milestones.ps1` | `core/scripts/Manage-Milestones.ps1`      |

Each one is exactly:

```powershell
$config = & "$PSScriptRoot\config.ps1"
& "$PSScriptRoot\..\..\core\scripts\<CoreScript>.ps1" -Config $config @args
```

The trailing `@args` forwards parameters like `-ApplyUpdate`, `-Action Snapshot`,
`-Label '...'`, etc. through to the core script.

### 3. `games/<slug>/README.md`

Short, factual. Avoid filler. Use this skeleton:

```markdown
# <DisplayName>

Harbormaster configuration for the <DisplayName> dedicated server.

## Files

- `config.ps1` — paths, Steam app id, service name, retention, env var prefix
- `Backup-<DisplayName>.ps1` — wrapper for daily backup
- `Check-<DisplayName>Health.ps1` — wrapper for periodic health check
- `Check-<DisplayName>Update.ps1` — wrapper for Steam update check
- `Manage-<DisplayName>Milestones.ps1` — wrapper for milestone snapshots

## Required environment variables

- `<ENV_PREFIX>_WEBHOOK_ALERTS` — Discord webhook for critical alerts
- `<ENV_PREFIX>_WEBHOOK_STATUS` — Discord webhook for routine status
- `<ENV_PREFIX>_HC_BACKUP` — Healthchecks.io ping URL for backup
- `<ENV_PREFIX>_HC_HEALTH_WEEKDAY` / `<ENV_PREFIX>_HC_HEALTH_WEEKEND`
- `<ENV_PREFIX>_HC_UPDATE_CHECK_WEEKDAY` / `<ENV_PREFIX>_HC_UPDATE_CHECK_WEEKEND`

## First run

1. Verify the values in `config.ps1` against the actual VM layout.
2. Fill in `StorageAccount` and `BlobContainer` if they were left as
   placeholders.
3. Register scheduled tasks pointing at the wrappers (see
   `examples/scheduled-tasks.ps1`).
```

Substitute `<DisplayName>` and `<ENV_PREFIX>` literally.

## After scaffolding

Report back to the user:

1. The list of files created (workspace-relative paths).
2. Any fields that were left as `<fill-in>` placeholders that they must edit
   before first run (storage account, blob container, anything else they
   skipped).

Do **not** modify the core scripts as part of this task — they already accept
`-Config` and read everything from the hashtable.
