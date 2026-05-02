# &lt;DisplayName&gt;

Harbormaster configuration for the &lt;DisplayName&gt; dedicated server.

> Replace `<DisplayName>` and `<ENV_PREFIX>` throughout this folder before
> first run. The `/new-game` workspace prompt will scaffold a populated
> copy of this template.

## Files

- `config.ps1` — paths, Steam app id, service name, retention, env var prefix
- `Backup-<DisplayName>.ps1` — wrapper for daily backup
- `Check-<DisplayName>Health.ps1` — wrapper for periodic health check
- `Check-<DisplayName>Update.ps1` — wrapper for Steam update check
- `Manage-<DisplayName>Milestones.ps1` — wrapper for milestone snapshots

Each wrapper is a two-liner that loads `config.ps1` and forwards `-Config`
plus any extra args to the matching script in `core/scripts/`.

## Required environment variables

- `<ENV_PREFIX>_WEBHOOK_ALERTS` — Discord webhook for critical alerts
- `<ENV_PREFIX>_WEBHOOK_STATUS` — Discord webhook for routine status
- `<ENV_PREFIX>_HC_BACKUP` — Healthchecks.io ping URL for backup
- `<ENV_PREFIX>_HC_HEALTH_WEEKDAY` / `<ENV_PREFIX>_HC_HEALTH_WEEKEND`
- `<ENV_PREFIX>_HC_UPDATE_CHECK_WEEKDAY` / `<ENV_PREFIX>_HC_UPDATE_CHECK_WEEKEND`
