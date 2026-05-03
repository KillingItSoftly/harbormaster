# Healthchecks.io Setup Walkthrough

Step-by-step setup of the five Healthchecks.io checks Harbormaster uses by default. Pairs with [healthchecks-cron.md](../core/docs/healthchecks-cron.md), which covers the conceptual side.

## Before you start

- A Healthchecks.io account ([sign up free](https://healthchecks.io/accounts/signup/))
- Your VM's timezone confirmed (`Get-TimeZone` on the VM)
- A clear picture of when your VM is actually up (e.g., 2 PM-2 AM Mon-Thu, 9 AM-2 AM Fri-Sun)

## Create a project

Healthchecks groups checks into projects. Create one called something like "Harbormaster - Windrose" so checks for different games stay grouped if you ever expand.

Projects → New Project → name it.

## Create the five checks

For each check below, click **Add Check**, fill in the values, and save. The ping URL is generated automatically — copy it for the env var setup at the end.

### 1. Backup

| Field | Value |
|---|---|
| Name | `<Game> Backup` |
| Tags | `backup`, `<game>` |
| Schedule | Cron |
| Cron expression | `30 0 * * *` |
| Timezone | (your VM's timezone) |
| Grace period | 1 hour |

### 2. Update Check (Weekday)

| Field | Value |
|---|---|
| Name | `<Game> Update Check (Weekday)` |
| Tags | `update`, `<game>`, `weekday` |
| Schedule | Cron |
| Cron expression | `5 14 * * 1-4` |
| Timezone | (your VM's timezone) |
| Grace period | 30 minutes |

Adjust the hour `14` to match your VM's weekday start time +5 minutes.

### 3. Update Check (Weekend)

| Field | Value |
|---|---|
| Name | `<Game> Update Check (Weekend)` |
| Tags | `update`, `<game>`, `weekend` |
| Schedule | Cron |
| Cron expression | `5 9 * * 5,6,0` |
| Timezone | (your VM's timezone) |
| Grace period | 30 minutes |

Adjust the hour `9` to match your VM's weekend start time +5 minutes.

### 4. Health Check (Weekday)

| Field | Value |
|---|---|
| Name | `<Game> Health (Weekday)` |
| Tags | `health`, `<game>`, `weekday` |
| Schedule | Cron |
| Cron expression | `*/15 14-23 * * 1-4` |
| Timezone | (your VM's timezone) |
| Grace period | 30 minutes |

### 5. Health Check (Weekend)

| Field | Value |
|---|---|
| Name | `<Game> Health (Weekend)` |
| Tags | `health`, `<game>`, `weekend` |
| Schedule | Cron |
| Cron expression | `*/15 9-23 * * 5,6,0` |
| Timezone | (your VM's timezone) |
| Grace period | 30 minutes |

## Configure alert delivery

For each check, click into it, then the **Integrations** tab.

Recommended baseline integrations:

- **Email** — works as a backup if Discord goes down. Free, reliable.
- **Discord** — point at the same alerts webhook your scripts use. The difference: scripts ping Discord while running; Healthchecks pings when scripts *stop* running.

Email integration is enabled by default for all checks. For Discord, you may need to add the webhook integration once at the project level (Integrations → Add → Discord), then enable it per-check.

## Capture the ping URLs

Each check has a unique ping URL, visible on its detail page. Format: https://hc-ping.com/<uuid>

Copy each URL. You'll set them as env vars on the VM.

## Set env vars on the VM

```powershell
[Environment]::SetEnvironmentVariable('WINDROSE_HC_BACKUP', 'https://hc-ping.com/...', 'Machine')
[Environment]::SetEnvironmentVariable('WINDROSE_HC_UPDATE_CHECK_WEEKDAY', 'https://hc-ping.com/...', 'Machine')
[Environment]::SetEnvironmentVariable('WINDROSE_HC_UPDATE_CHECK_WEEKEND', 'https://hc-ping.com/...', 'Machine')
[Environment]::SetEnvironmentVariable('WINDROSE_HC_HEALTH_WEEKDAY',     'https://hc-ping.com/...', 'Machine')
[Environment]::SetEnvironmentVariable('WINDROSE_HC_HEALTH_WEEKEND',     'https://hc-ping.com/...', 'Machine')

# Refresh current session
foreach ($v in 'WINDROSE_HC_BACKUP','WINDROSE_HC_UPDATE_CHECK_WEEKDAY','WINDROSE_HC_UPDATE_CHECK_WEEKEND','WINDROSE_HC_HEALTH_WEEKDAY','WINDROSE_HC_HEALTH_WEEKEND') {
    Set-Item "env:$v" ([Environment]::GetEnvironmentVariable($v, 'Machine'))
}
```

## Test it works

```powershell
Import-Module C:\Scripts\harbormaster\core\modules\HarbormasterHealthchecks.psm1 -Force
$Config = & 'C:\Scripts\harbormaster\games\windrose\config.ps1'

# Should ping success on each check
Send-Heartbeat -Config $Config -Key BACKUP -Status Success
Send-Heartbeat -Config $Config -Key HEALTH -Status Success -DayBucket
```

Refresh the Healthchecks dashboard. Each check you pinged should show "Up" with a recent timestamp.

## Test failure alerts

Before relying on this in production, verify alerts actually arrive:

```powershell
Send-Heartbeat -Config $Config -Key BACKUP -Status Fail
```

You should receive an email and/or Discord notification within seconds. If not, the integration setup needs fixing — the time to find out is now, not when something real breaks.

After confirming the alert works, ping success again to clear the failed state:

```powershell
Send-Heartbeat -Config $Config -Key BACKUP -Status Success
```

## Multiple games on the same Healthchecks account

The free tier gives you 20 checks. With 5 checks per game, that's 4 games before you run out. If you exceed it, the Hobbyist tier ($5/mo) gets you 50 checks.

Tags are how you keep different games' checks separated visually. The pattern:

- All Windrose checks tagged `windrose`
- All Minecraft checks tagged `minecraft`
- Filter the dashboard by tag to see one game's status at a time

## Common gotchas

- **Timezone mismatch.** The cron expression is interpreted in the timezone you set on the check. Get-TimeZone on the VM and match.
- **Grace period too tight.** A backup that occasionally takes 10 minutes will false-alarm with a 5-minute grace period. Err on the side of generous grace periods, especially for backups.
- **Forgetting to set env vars in Machine scope.** Process or User scope means scheduled tasks running as SYSTEM can't see them. Use Machine.
- **Editing cron without updating Task Scheduler.** Both have to stay in sync. If you change the VM's auto-start time, update both the scheduled tasks and the corresponding Healthchecks crons.