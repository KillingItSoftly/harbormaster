# Environment Variables

Harbormaster uses environment variables for everything that's secret, machine-specific, or rotates without a code change — webhook URLs, Healthchecks ping URLs, and similar. This doc covers how to set them correctly, the gotchas to avoid, and how the modules use them.

## Why env vars instead of config files

A few specific reasons:

- **Secrets stay out of the repo.** A leaked webhook URL in a committed file is a worse problem than a leaked URL in an env var. The `.gitignore` blocks `.env`, but a typo in a script literal slips through.
- **Different VMs can share the same script.** When you eventually clone Harbormaster to a second VM for a different game, the scripts work identically — only the env vars differ.
- **Rotation doesn't require a deploy.** Webhook compromised? Rotate the URL, update one env var, done. No git pull, no script edits.
- **Multiple games coexist.** With a per-game prefix (`WINDROSE_*`, `MINECRAFT_*`), one VM can run multiple games using the same modules.

## Naming convention

All Harbormaster env vars follow this shape:

```
<PREFIX>_<CATEGORY>[_<SUFFIX>]
```

Where:

- `<PREFIX>` matches the `EnvVarPrefix` in your game's `config.ps1` (e.g., `WINDROSE`, `MINECRAFT`)
- `<CATEGORY>` is what kind of integration: `WEBHOOK` or `HC` (Healthchecks)
- `<SUFFIX>` identifies the specific channel or task

Examples:

| Variable | Purpose |
|---|---|
| `WINDROSE_WEBHOOK_ALERTS` | Discord webhook for the alerts channel |
| `WINDROSE_WEBHOOK_STATUS` | Discord webhook for the status channel |
| `WINDROSE_HC_BACKUP` | Healthchecks ping URL for the daily backup |
| `WINDROSE_HC_UPDATE_CHECK_WEEKDAY` | Healthchecks ping for weekday update check |
| `WINDROSE_HC_HEALTH_WEEKEND` | Healthchecks ping for weekend health check |

The day-bucket suffix (`_WEEKDAY`, `_WEEKEND`) is only used for tasks that run on different schedules different days. See [healthchecks-cron.md](healthchecks-cron.md) for why.

## Setting env vars on Windows

There are three "scopes" for environment variables on Windows, and **only one of them works for scheduled tasks running as SYSTEM**.

### Scope: Machine (recommended)

Visible to all users and all processes, including services and SYSTEM-context scheduled tasks.

```powershell
[Environment]::SetEnvironmentVariable('WINDROSE_WEBHOOK_ALERTS', 'https://discord.com/api/webhooks/...', 'Machine')
```

This requires running PowerShell as Administrator. Without admin rights, the call silently fails.

### Scope: User

Visible only to the current user's processes. Won't work for SYSTEM-run scheduled tasks.

```powershell
[Environment]::SetEnvironmentVariable('WINDROSE_WEBHOOK_ALERTS', 'https://discord.com/api/webhooks/...', 'User')
```

### Scope: Process

Visible only to the current PowerShell session. Goes away when you close the window.

```powershell
$env:WINDROSE_WEBHOOK_ALERTS = 'https://discord.com/api/webhooks/...'
```

This is the syntax most people are familiar with. It's perfect for testing, but useless for unattended automation.

### The "I just set it but PowerShell can't see it" gotcha

Setting a Machine-scope env var **does not propagate to your current PowerShell session**. New processes started after the set will see it; the current session won't.

```powershell
# Set it Machine-wide
[Environment]::SetEnvironmentVariable('WINDROSE_WEBHOOK_ALERTS', 'https://...', 'Machine')

# Current session: doesn't see it
$env:WINDROSE_WEBHOOK_ALERTS
# (returns nothing)

# Open a new PowerShell window
$env:WINDROSE_WEBHOOK_ALERTS
# (now visible)
```

Two ways to handle this:

**Option A: also set it in the current session**

```powershell
$webhookUrl = 'https://discord.com/api/webhooks/...'
[Environment]::SetEnvironmentVariable('WINDROSE_WEBHOOK_ALERTS', $webhookUrl, 'Machine')
$env:WINDROSE_WEBHOOK_ALERTS = $webhookUrl
```

**Option B: open a new PowerShell session after setting**

Less convenient for testing but cleaner if you're doing a one-time setup.

## The standard setup pattern

Here's the canonical block for setting all the env vars Harbormaster needs for a single game. Run as Administrator on the VM:

```powershell
# ------------------------------------------------------------------------
# Harbormaster env var setup for Windrose
# ------------------------------------------------------------------------

# Define the values up front
$envVars = @{
    # Discord webhooks
    'WINDROSE_WEBHOOK_ALERTS' = 'https://discord.com/api/webhooks/PASTE_URL_HERE'
    'WINDROSE_WEBHOOK_STATUS' = 'https://discord.com/api/webhooks/PASTE_URL_HERE'

    # Healthchecks.io ping URLs
    'WINDROSE_HC_BACKUP'                  = 'https://hc-ping.com/PASTE_UUID_HERE'
    'WINDROSE_HC_UPDATE_CHECK_WEEKDAY'    = 'https://hc-ping.com/PASTE_UUID_HERE'
    'WINDROSE_HC_UPDATE_CHECK_WEEKEND'    = 'https://hc-ping.com/PASTE_UUID_HERE'
    'WINDROSE_HC_HEALTH_WEEKDAY'          = 'https://hc-ping.com/PASTE_UUID_HERE'
    'WINDROSE_HC_HEALTH_WEEKEND'          = 'https://hc-ping.com/PASTE_UUID_HERE'
}

# Set them in Machine scope (so SYSTEM-run scheduled tasks can read them)
foreach ($name in $envVars.Keys) {
    $value = $envVars[$name]
    [Environment]::SetEnvironmentVariable($name, $value, 'Machine')
    # Also set in current session so we can test immediately
    Set-Item "env:$name" $value
    Write-Host "Set: $name"
}

Write-Host "Done. New PowerShell sessions will pick these up automatically." -ForegroundColor Green
```

Save this as `setup-env.local.ps1` (the `.local.` suffix keeps it out of the repo per `.gitignore`). Edit with your actual URLs, run once on the VM, done.

## Verifying env vars are set correctly

After setting, confirm each one is readable:

```powershell
# Listed values
@(
    'WINDROSE_WEBHOOK_ALERTS'
    'WINDROSE_WEBHOOK_STATUS'
    'WINDROSE_HC_BACKUP'
    'WINDROSE_HC_UPDATE_CHECK_WEEKDAY'
    'WINDROSE_HC_UPDATE_CHECK_WEEKEND'
    'WINDROSE_HC_HEALTH_WEEKDAY'
    'WINDROSE_HC_HEALTH_WEEKEND'
) | ForEach-Object {
    $machine = [Environment]::GetEnvironmentVariable($_, 'Machine')
    $process = [Environment]::GetEnvironmentVariable($_, 'Process')
    [PSCustomObject]@{
        Name    = $_
        Machine = if ($machine) { 'set ({0} chars)' -f $machine.Length } else { 'NOT SET' }
        Process = if ($process) { 'set' } else { 'not in current session' }
    }
} | Format-Table -AutoSize
```

What you want to see: every var with `Machine: set (...)` and `Process: set`. If any show `NOT SET` for Machine, scheduled tasks won't see them.

## Verifying scheduled tasks can read them

A subtle bug: env vars set in Machine scope while a scheduled task is "running" don't propagate to that running task. The next time the task fires, it picks them up. To verify your tasks see them, trigger one manually after setting:

```powershell
Start-ScheduledTask -TaskName 'WindroseHealthCheck'
Start-Sleep -Seconds 30
Get-ScheduledTaskInfo -TaskName 'WindroseHealthCheck' | Select LastTaskResult
```

`LastTaskResult: 0` means the task ran successfully. Anything else and the task likely couldn't read the env vars — check the task's log file.

## How the modules read env vars

The modules `HarbormasterNotify` and `HarbormasterHealthchecks` read env vars **on every call**, not at module import time. This means:

- You can rotate webhooks without restarting anything
- Setting a new env var is visible on the next function call (within the same session)
- A stale module import doesn't pin you to old values

The reading order tries Process scope first (current session), then falls back to Machine scope:

```powershell
$url = [Environment]::GetEnvironmentVariable($name, 'Process')
if ([string]::IsNullOrWhiteSpace($url)) {
    $url = [Environment]::GetEnvironmentVariable($name, 'Machine')
}
```

This means scheduled tasks running as SYSTEM only need Machine-scope vars (they don't have a meaningful Process scope from a previous interactive session). Interactive testing in your RDP session benefits from Process scope being faster to update.

## Common gotchas

### "Invalid URI: The hostname could not be parsed"

The env var contains an invisible character, usually from copy-paste. Check the actual bytes:

```powershell
$url = $env:WINDROSE_WEBHOOK_ALERTS
$url.ToCharArray() | ForEach-Object {
    $code = [int]$_
    "  [{0,3}] '{1}'" -f $code, $(if ($code -ge 32 -and $code -le 126) { $_ } else { '?' })
} | Select-Object -First 30
```

Anything below 32 or above 126 (printable ASCII range) is invisible junk that breaks URL parsing. The `HarbormasterNotify` module strips this automatically, but the standalone `Invoke-RestMethod` does not.

To clean a stuck env var:

```powershell
$raw = [Environment]::GetEnvironmentVariable('WINDROSE_WEBHOOK_ALERTS', 'Machine')
$clean = $raw -replace '[^\x21-\x7E]', ''
[Environment]::SetEnvironmentVariable('WINDROSE_WEBHOOK_ALERTS', $clean, 'Machine')
$env:WINDROSE_WEBHOOK_ALERTS = $clean
```

### Quotes in the env var value

If you set the var via the GUI (System Properties → Environment Variables) and pasted a URL with surrounding quotes, those quotes are now part of the value:

```
$env:WINDROSE_WEBHOOK_ALERTS  -->  '"https://discord.com/..."'
```

Strip them:

```powershell
$clean = $env:WINDROSE_WEBHOOK_ALERTS.Trim('"').Trim("'")
[Environment]::SetEnvironmentVariable('WINDROSE_WEBHOOK_ALERTS', $clean, 'Machine')
$env:WINDROSE_WEBHOOK_ALERTS = $clean
```

### "I set the User-scope var, why doesn't the scheduled task see it?"

Because scheduled tasks run as SYSTEM, not as your user. SYSTEM has its own User-scope env (effectively empty). Always use Machine scope for anything that needs to be visible to scheduled tasks.

### "I want a different webhook for testing vs production"

The `Process` scope wins over `Machine` in the modules' lookup order. To override for a single test session:

```powershell
$env:WINDROSE_WEBHOOK_ALERTS = 'https://discord.com/api/webhooks/test-channel/...'
# Now this session uses the test URL
# Other sessions (and the scheduled tasks) still use the Machine value
```

Close that PowerShell window when done; the override goes away.

### Setting env vars from a non-admin session

`[Environment]::SetEnvironmentVariable(..., 'Machine')` requires admin. Without it, the call appears to succeed but the value isn't actually persisted. Always check after setting:

```powershell
[Environment]::GetEnvironmentVariable($name, 'Machine')
```

If it returns nothing right after you "set" it, your session lacked the privilege.

## Rotating credentials

When a webhook URL or Healthchecks ping URL needs rotating (compromised, regenerated, moved to a different account):

1. Get the new URL from Discord/Healthchecks
2. Update the Machine-scope env var:
```powershell
   [Environment]::SetEnvironmentVariable('WINDROSE_WEBHOOK_ALERTS', $newUrl, 'Machine')
   $env:WINDROSE_WEBHOOK_ALERTS = $newUrl   # current session
```
3. Test with a manual ping:
```powershell
   Send-WindroseNotification -Title 'Test rotation' -Message 'New URL active' -Severity Info -Channel Alerts
```
4. The old URL is now unused. If you compromised it (leaked in a log, shared in a screenshot), delete it on the Discord/Healthchecks side too.

No script changes required for rotation — that's the whole point of using env vars.

## Auditing what's set

Periodically worth checking what's actually configured:

```powershell
# All Harbormaster-shaped env vars in Machine scope
[Environment]::GetEnvironmentVariables('Machine').GetEnumerator() |
    Where-Object { $_.Name -match '^[A-Z]+_(WEBHOOK|HC)_' } |
    Sort-Object Name |
    Select-Object Name, @{N='Length'; E={$_.Value.Length}}
```

That gives you a table of variable names and their string lengths (without exposing the values themselves to logs/screenshots). If a length is suspiciously different from your other webhooks/pings, something's likely truncated or has hidden characters.

## What about `.env` files?

The repo includes a `.env.example` showing all the variables that need to be set. You can use a `.env` file for local development if you find that easier, but it requires a tool to load it into the environment — PowerShell doesn't natively read `.env` files.

For production VMs, set Machine env vars directly. The `.env` file pattern is more useful for ephemeral dev environments where you'd source the file into a session.

If you do want `.env` support on the VM, this snippet loads one into Process scope:

```powershell
function Import-DotEnv {
    param([string]$Path = '.env')
    Get-Content $Path | ForEach-Object {
        if ($_ -match '^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.+?)\s*$') {
            Set-Item "env:$($Matches[1])" $Matches[2].Trim('"').Trim("'")
        }
    }
}
```

Run `Import-DotEnv 'C:\path\to\.env'` to load. Useful for one-off testing, not what I'd build production around.