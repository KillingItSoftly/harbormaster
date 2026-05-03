# Healthchecks.io with Cron Schedules

Harbormaster uses [Healthchecks.io](https://healthchecks.io) to detect when scheduled tasks stop running — the failure case Discord notifications can't catch (a script that's not running can't send a Discord message).

The pattern is simple: each scheduled task pings a unique URL when it runs. Healthchecks expects pings on a schedule, and alerts you when one is missing.

## Why cron-style schedules

For tasks that run on a fixed simple interval (every 24 hours, every 30 minutes), the "Simple" schedule type works fine — set the period and a grace window.

For tasks that only run during specific hours (e.g., when the VM is up), simple intervals produce false alarms. The VM is off from 2 AM to 2 PM weekdays; nothing's pinging during that window because nothing's running, but the monitor still expects pings.

Cron schedules let you express "expect a ping at 2:05 PM Mon-Thu" precisely. Outside those windows, missing pings don't trigger alerts.

## Schedule type setup

In Healthchecks.io: edit a check → Schedule → **Cron** → enter expression, timezone, and grace period.

A few things worth understanding:

- **The cron expression isn't telling Healthchecks to *do* anything.** Your script still runs from Windows Task Scheduler. The cron expression tells Healthchecks *when to expect a ping*. The two need to match.
- **The timezone matters.** Set Healthchecks's timezone to whatever your VM uses. Mismatch causes constant false alarms.
- **One expression per check.** If a task runs on different schedules different days (e.g., 2 PM weekdays, 9 AM weekends), you need two separate checks because cron syntax can't represent that in a single expression cleanly.

## Cron syntax cheat sheet

minute  hour  day-of-month  month  day-of-week
*/15    14-23 *             *      1-4

Day-of-week: 0=Sunday, 1=Monday, …, 6=Saturday. Some implementations also accept 7=Sunday.

Common patterns:

- `30 0 * * *` — at 00:30 every day
- `5 14 * * 1-4` — at 14:05 Monday through Thursday
- `*/15 9-23 * * 5,6,0` — every 15 minutes from 09:00 to 23:59 on Friday, Saturday, Sunday
- `0 */6 * * *` — at minute 0 of every 6th hour (00:00, 06:00, 12:00, 18:00)

## Day-bucket pattern for split schedules

When the same task runs at different times on weekdays vs weekends, create two checks:

| Task | Schedule | Cron | Env var |
|---|---|---|---|
| Update Check (Weekday) | 14:05 Mon-Thu | `5 14 * * 1-4` | `<PREFIX>_HC_UPDATE_CHECK_WEEKDAY` |
| Update Check (Weekend) | 09:05 Fri-Sun | `5 9 * * 5,6,0` | `<PREFIX>_HC_UPDATE_CHECK_WEEKEND` |

In the script, pass the per-game `$Config` and use `-DayBucket` to pick the right env var automatically:

```powershell
Import-Module HarbormasterHealthchecks

$Config = & "$PSScriptRoot\..\..\games\windrose\config.ps1"

# With -DayBucket, this resolves to either
#   WINDROSE_HC_UPDATE_CHECK_WEEKDAY (Mon-Thu) or
#   WINDROSE_HC_UPDATE_CHECK_WEEKEND (Fri-Sun)
Send-Heartbeat -Config $Config -Key UPDATE_CHECK -Status Success -DayBucket
```

## Three signal types

Healthchecks supports three variants of the same ping URL, and the script tells the monitor what happened by which one it pings.

For ping URL `https://hc-ping.com/abc-123`:

| URL | Meaning | Fire when |
|---|---|---|
| `…/abc-123` (base) | Success | Job ran and finished its work |
| `…/abc-123/start` | Started | Job has begun (optional, for duration tracking) |
| `…/abc-123/fail` | Failure | Job ran but didn't do its job |

`Send-Heartbeat` from `HarbormasterHealthchecks.psm1` handles all three:

```powershell
Send-Heartbeat -Config $Config -Key BACKUP -Status Start
# ... do work ...
Send-Heartbeat -Config $Config -Key BACKUP -Status Success
# or on failure
Send-Heartbeat -Config $Config -Key BACKUP -Status Fail
```

## When to use Start

The `/start` ping is optional but useful for catching "started but never finished" cases — scripts that hang, get killed mid-run, or otherwise don't reach their success-or-fail decision point.

If you don't ping start, Healthchecks only knows about scripts that completed (one way or the other) or didn't run at all. Adding start pings gives you a third state: "ran but never reported back."

For backups, snapshots, and updates — anything that takes more than a few seconds and could realistically hang — ping start. For the lightweight health check that runs in seconds, skip it.

## Recommended check setup for Harbormaster

For a single-game setup with the standard scripts:

| Check | Schedule | Cron | Grace |
|---|---|---|---|
| Backup | 00:30 daily | `30 0 * * *` | 1 hour |
| Update Check (Weekday) | 14:05 Mon-Thu | `5 14 * * 1-4` | 30 min |
| Update Check (Weekend) | 09:05 Fri-Sun | `5 9 * * 5,6,0` | 30 min |
| Health Check (Weekday) | every 15 min, 14:00-23:59 Mon-Thu | `*/15 14-23 * * 1-4` | 30 min |
| Health Check (Weekend) | every 15 min, 09:00-23:59 Fri-Sun | `*/15 9-23 * * 5,6,0` | 30 min |

Five checks, well within the free tier's 20-check limit. Adjust hours to match your VM's actual uptime schedule.

The 0:00–1:59 window isn't covered by the health-check cron (the wraparound is hard to express). Pings during that window arrive and are recorded, but absent pings during 0:00–1:59 don't trigger alerts. The VM goes down at 2 AM regardless, so this is fine.

## Configuring alerts

Each check has an **Integrations** tab. Add the channels you want to be alerted on:

- **Email** — for everything; works as a backup if Discord goes down
- **Discord webhook** — point at the same `#alerts` channel your scripts use
- **Slack / SMS / Pushover / etc.** — Healthchecks supports many

For game servers, email + Discord is a solid pair. SMS is overkill unless you're running something mission-critical.

## Setting the env vars

Whatever URLs Healthchecks gives you, set as env vars on the VM:

```powershell
[Environment]::SetEnvironmentVariable('WINDROSE_HC_BACKUP', 'https://hc-ping.com/...', 'Machine')
[Environment]::SetEnvironmentVariable('WINDROSE_HC_UPDATE_CHECK_WEEKDAY', '...', 'Machine')
# etc.
```

Set them in `Machine` scope so scheduled tasks running as SYSTEM can see them. The `HarbormasterHealthchecks` module reads from both `Process` and `Machine` scopes automatically.

## Common pitfalls

- **Timezone mismatch** between the check and the VM. Get-TimeZone on the VM, set Healthchecks to match.
- **Forgetting to update the cron** when you change scheduled-task times. Both need to stay in sync; otherwise the monitor alerts on every run that's at a different time than expected.
- **Not testing failures.** Verify alerts actually arrive by manually pinging `/fail` once after setting up integrations:
```powershell
  Invoke-RestMethod 'https://hc-ping.com/your-uuid/fail'
```
  You should get an email/Discord notification within seconds. If not, fix the integration before relying on it.
- **Free tier limits.** 20 checks total per account, which is plenty for one or two games. Multiple games will eat into that quickly if every game has 5+ checks. Paid plans are reasonable if you outgrow it.