# Windrose

Harbormaster configuration for the Windrose dedicated server.

## Files

- `config.ps1` — paths, Steam app id, service name, retention, env var prefix
- `Backup-Windrose.ps1` — wrapper for daily backup
- `Check-WindroseHealth.ps1` — wrapper for periodic health check
- `Check-WindroseUpdate.ps1` — wrapper for Steam update check
- `Manage-WindroseMilestones.ps1` — wrapper for milestone snapshots
- `examples/world-easy-mode.json` — reference world config

## Required environment variables

- `WINDROSE_WEBHOOK_ALERTS` — Discord webhook for critical alerts
- `WINDROSE_WEBHOOK_STATUS` — Discord webhook for routine status
- `WINDROSE_HC_BACKUP` — Healthchecks.io ping URL for backup
- `WINDROSE_HC_HEALTH_WEEKDAY` / `WINDROSE_HC_HEALTH_WEEKEND`
- `WINDROSE_HC_UPDATE_CHECK_WEEKDAY` / `WINDROSE_HC_UPDATE_CHECK_WEEKEND`

## First run

1. Verify the values in `config.ps1` against the actual VM layout.
2. Confirm `StorageAccount` and `BlobContainer` match your Azure setup.
3. Register scheduled tasks pointing at the wrappers (see
   `examples/scheduled-tasks.ps1`).

# Windrose setup

Harbormaster wrappers and configuration for [Windrose](https://store.steampowered.com/app/3041230) (Steam app `4129620` for the dedicated server).

## Files in this folder

- `config.ps1` — Windrose-specific paths and identifiers
- `Backup-Windrose.ps1` — daily backup wrapper
- `Snapshot-Windrose.ps1` — milestone snapshot wrapper
- `Check-WindroseUpdate.ps1` — Steam update check wrapper
- `Check-WindroseHealth.ps1` — health check wrapper
- `examples/world-easy-mode.json` — example WorldDescription.json for an easier game

## Quick reference

| Setting | Value |
|---|---|
| Steam app ID (server) | `4129620` |
| Recommended VM size | `D4s_v5` (4 vCPU, 16 GB) |
| Save data format | RocksDB key-value store |
| Player connection | NAT punch-through via invite code |

## Windrose-specific quirks

### The "WindroseServer" folder inside the game install isn't the standalone server

If you install Windrose via Steam, you'll see a `WindroseServer` folder inside the game install directory. This is **not** a standalone dedicated server — it's a complementary part of the client. Launching it directly while running the client causes process conflicts.

For a true standalone server, either:
- Install via SteamCMD with the dedicated server app ID (`4129620`), or
- Copy the `WindroseServer` folder out of the game install to a different location

The `InstallDir` in `config.ps1` should point at the standalone copy, not the in-game one.

### Save data is RocksDB, not flat files

Windrose saves world state to a RocksDB key-value store, not a single save file. The `SavedDataPath` in config points at the parent of the RocksDB folder. You can't just copy "the save file" — you need to back up the entire `R5\Saved` tree.

The path is typically: <InstallDir>\R5\Saved

### Edit configs only when the server is stopped

Both `ServerDescription.json` (server-level settings) and `WorldDescription.json` (per-world settings) get rewritten by the server on shutdown. Edit them only when the service is fully stopped:

```powershell
nssm stop WindroseServer
# edit configs
nssm start WindroseServer
```

### Worlds have a baked-in preset

When a world is created, the `WorldPresetType` (`Easy`, `Medium`, `Hard`, `Custom`) gets baked into individual multiplier fields in `WorldDescription.json`. Changing `WorldPresetType` later doesn't automatically rewrite those multipliers.

To change difficulty on an existing world:
1. Stop the server
2. Set `WorldPresetType` to `"Custom"`
3. Manually edit each multiplier field
4. Start the server

See `examples/world-easy-mode.json` for an example custom-easy config.

### Updates are frequent in early access

Windrose patches often during early access — sometimes weekly. The `Check-WindroseUpdate.ps1` wrapper can be set to auto-apply updates, but be aware that game updates can occasionally break save formats or invalidate mod frameworks. Manual updates with a snapshot first are safer until the game stabilizes.

## Connection methods

Windrose supports two connection modes:

- **Invite code via NAT punch-through** (default) — players paste a code in the client and the connection negotiates through Windrose's matchmaking. Doesn't require port forwarding or NSG rules. Easiest for small private crews.
- **Direct connection on a fixed port** — set `UseDirectConnection: true` in `ServerDescription.json` and open the configured port (default 7777) on both Windows Firewall and the Azure NSG, both TCP and UDP. Useful if NAT punch-through has issues.

Most setups use invite code. If you change to direct connection, update the firewall rules:

```powershell
$port = 7777
New-NetFirewallRule -DisplayName "Windrose Direct TCP" -Direction Inbound -Protocol TCP -LocalPort $port -Action Allow
New-NetFirewallRule -DisplayName "Windrose Direct UDP" -Direction Inbound -Protocol UDP -LocalPort $port -Action Allow
```

And open the same port in your Azure NSG.

## Crash log patterns

Windrose uses Unreal Engine 5 logs. Crashes show as: [2026.04.26-22.43.25:539][277]LogOutputDevice: Error: === Crash Stack Trace: ===

The `Crash Stack Trace` substring is what `CrashLogPattern` in config.ps1 matches against. The timestamp format `[YYYY.MM.DD-HH.MM.SS:fff]` is what `LogTimestampRegex` parses.

## References

- [Windrose dedicated server guide (official)](https://playwindrose.com/dedicated-server-guide/)
- [Steam community guide by WHOLF/Blackbeard](https://steamcommunity.com/sharedfiles/filedetails/?id=3706337486)
- [Windrose Server Manager (community GUI tool)](https://github.com/ManuelStaggl/WindroseServerManager)