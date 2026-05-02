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
