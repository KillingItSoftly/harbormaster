# Discord Channels for Notifications

Harbormaster splits notifications across channels by severity, so the alerts that need attention don't get lost in a stream of routine status updates.

## Why split channels at all

A noisy channel gets muted, and a muted channel doesn't help when something actually breaks. The split is about preserving the signal-to-noise ratio of the channel that matters.

## The standard three channels

### `#<game>-alerts`

**Purpose**: Things that need you to do something. Server crashes, backup failures, disk space warnings, update available, snapshot failures.

**Notification settings**: All messages, you keep notifications on, you check it when you see a ping.

**Volume**: Should be quiet most days. If alerts is firing daily, either something's actually wrong or your alerting is too aggressive — both are signals to fix.

### `#<game>-status`

**Purpose**: Routine confirmations of expected events. Server came online, update applied successfully, snapshot taken before a known-good state.

**Notification settings**: Mention-only or muted entirely. You glance at it occasionally for a vibe check.

**Volume**: A few per day during normal operation.

### `#<game>-heartbeat`

**Purpose**: Daily "I ran and nothing was wrong" confirmations from automation. Update checks, periodic health checks, etc.

**Notification settings**: Muted. Always.

**Volume**: Daily, sometimes multiple times. If you skip this channel in favor of Healthchecks.io (recommended), you don't need it at all.

## Severity → channel mapping

The `Send-WindroseNotification` function takes a `-Severity` and `-Channel`. The script decides both based on what's happening:

| Severity | When | Channel |
|---|---|---|
| Critical | Service down, backup failed, update FAILED, snapshot couldn't be taken before update | Alerts |
| Warning | Update available (action needed), update without snapshot, disk space getting low | Alerts |
| Success | Update applied successfully, server came online | Status |
| Info | Routine confirmations, nothing actionable | Status or Heartbeat |

## Setting up webhooks

In Discord, for each channel:

1. Channel settings → Integrations → Webhooks → New Webhook
2. Name it descriptively (e.g., "Harbormaster - Alerts")
3. Copy the URL
4. Set it as an env var on the VM:
```powershell
   [Environment]::SetEnvironmentVariable('WINDROSE_WEBHOOK_ALERTS', '<url>', 'Machine')
```
5. Refresh the current PowerShell session if testing immediately:
```powershell
   $env:WINDROSE_WEBHOOK_ALERTS = [Environment]::GetEnvironmentVariable('WINDROSE_WEBHOOK_ALERTS', 'Machine')
```

## Webhook security

Discord webhook URLs are bearer credentials — anyone with the URL can post to the channel as the webhook. A few practices:

- **Never commit them** to a repo. The `.gitignore` blocks `.env`, but a typo in a script literal will leak the URL.
- **Rotate immediately** if a URL ends up somewhere it shouldn't be (chat logs, screenshots, screenshares). Discord lets you regenerate the token without recreating the webhook.
- **Don't share screenshots of debug output** that contain webhook URLs. Redact the second path segment (the token) before sharing.
- **Webhooks can't be scoped.** A leaked URL gives full post access to the channel until you rotate it. The blast radius is "spam in one channel" — annoying, not catastrophic, but worth fixing.

## Channel naming conventions

If you run multiple games eventually, prefix the channel by game:

- `#windrose-alerts`, `#windrose-status`
- `#minecraft-alerts`, `#minecraft-status`
- etc.

Env vars follow the same prefix convention: `WINDROSE_WEBHOOK_ALERTS`, `MINECRAFT_WEBHOOK_ALERTS`. The prefix is configurable in each game's `config.ps1` (`EnvVarPrefix = 'MINECRAFT'`) so the modules pick the right webhook automatically.

## What about pings?

Discord webhooks can include `@here` or `@everyone` mentions, but they need explicit `allowed_mentions` configuration to actually trigger the notification (since around 2020). The `HarbormasterNotify` module doesn't include them by default — channel notification settings handle volume just as well without the noise of forced pings.

If you want a specific role pinged on Critical alerts, you can add it as an embed mention. Useful if multiple people admin the server and you want everyone notified at once. Most single-admin setups don't need it.

## Testing the setup

A quick smoke test for each channel:

```powershell
Import-Module C:\Scripts\harbormaster\core\modules\HarbormasterNotify.psm1 -Force

foreach ($severity in 'Critical','Warning','Success','Info') {
    Send-WindroseNotification `
        -Title "Test: $severity" `
        -Message "Testing notification routing." `
        -Severity $severity `
        -Channel Alerts
}
```

Check that all four messages arrive in `#alerts` with appropriate colors. Then test `Status` and `Heartbeat` channels separately.

If a notification fails, check:

1. The env var is set in the right scope (Machine vs Process)
2. The PowerShell session can see the env var (`$env:VAR_NAME` returns it, not blank)
3. The URL is well-formed (no extra quotes, no whitespace, no smart quotes from a paste)
4. The module isn't caching a stale URL (use `Remove-Module` then `Import-Module -Force`)

The HarbormasterNotify module reads env vars on every call (not at import time), so you can rotate webhooks and the next call uses the new value without any reload dance.

## What goes where: examples

To make the routing concrete, here's how the existing scripts decide:

**Backup script:**
- Service fails to restart after backup → `Critical` to `Alerts` (you need to fix this)
- Backup itself failed → `Critical` to `Alerts`
- Backup succeeded → no Discord notification (the Healthchecks ping is enough)

**Update check:**
- Update available, action needed → `Warning` to `Alerts`
- Update applied successfully → `Success` to `Status`
- Update FAILED → `Critical` to `Alerts`
- No update (script ran fine) → no Discord notification (Healthchecks ping handles this)

**Health check:**
- Server down for >10 min → `Critical` to `Alerts`
- Server recovered → `Success` to `Alerts` (closes the loop on the prior alert)
- Disk space low → `Warning` or `Critical` to `Alerts` based on threshold
- Backup hasn't run in 26+ hours → `Warning` to `Alerts`
- All checks passed → no Discord notification

The pattern: **don't notify Discord for routine successes**. Healthchecks handles "did it run?" — Discord handles "should you care?"