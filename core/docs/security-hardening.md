# Security hardening checklist

Operational hygiene to keep the Harbormaster bot from being a path into the
Azure subscription. Treat this as a recurring audit, not a one-time setup.

## 1. Discord token rotation

- The bot token in `bot/main.parameters.example.json` was committed in
  plaintext at one point. **Regenerate it** in the Discord developer portal
  (Bot → Reset Token) and rewrite history (`git filter-repo`) before any
  public push.
- Store the live token only in the Container App secret named
  `discord-bot-token`. Never commit a real token to any file.
- Rotate the token any time:
  - A new admin joins the operations team.
  - You suspect a leak or audit-log anomaly.
  - At least once per year as routine hygiene.

## 2. Managed-identity scope (least privilege)

The Container App's user-assigned managed identity should hold only the
roles it needs, scoped to the **single VM** — not the resource group or
subscription:

```bash
# Inspect what your identity currently has
az role assignment list \
  --assignee <managed-identity-object-id> \
  --all -o table
```

Required roles (assign these scoped to `/subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.Compute/virtualMachines/<vm>`):

| Role                       | Purpose                                  |
| -------------------------- | ---------------------------------------- |
| `Virtual Machine Contributor` | start/deallocate, run-command on the VM |
| `Reader` (RG scope OK)     | resolve resource references             |

If you see `Owner`, `Contributor` at subscription/RG scope, or anything
broader — remove and reassign at VM scope.

## 3. Run Command script ACL on the VM

The bot executes `.ps1` wrappers from `script_dir` (per-game folder). If a
non-admin Windows account can write those files, a compromised player
account on the VM can cause the bot to run arbitrary code as
`NT AUTHORITY\SYSTEM` (which is what Run Command uses).

Lock down the directory:

```powershell
# Run as Administrator on the VM.
$path = 'C:\Scripts\harbormaster'
icacls $path /inheritance:r
icacls $path /grant:r "NT AUTHORITY\SYSTEM:(OI)(CI)F"
icacls $path /grant:r "BUILTIN\Administrators:(OI)(CI)F"
icacls $path /grant:r "BUILTIN\Users:(OI)(CI)RX"
```

Verify with `icacls C:\Scripts\harbormaster` — the `Users` group should
have `RX` only, never `M` or `F`.

## 4. Bot-side defenses already implemented

These are enforced in code; this list is for review/audit:

- **Guild allow-list**: every command rejects `interaction.guild_id !=
  configured guild_id`. (`auth.py`)
- **DM rejection**: every command rejects `interaction.guild_id is None`.
- **Argument allowlists**: snapshot labels are `[A-Za-z0-9_-]{1,50}`,
  log-line counts are `app_commands.Range[int, 1, 50]`, snapshot
  categories are `app_commands.Choice[...]`. (`cogs/snapshot.py`,
  `cogs/server.py`)
- **Wrapper-name allowlist**: `azure_client.invoke_wrapper` rejects any
  wrapper filename not matching `^[A-Za-z0-9_.-]+\.ps1$` to prevent path
  traversal.
- **Service-name allowlist**: `azure_client.get_service_status` applies
  the same regex.
- **Concurrency lock**: a bot-wide async lock prevents two destructive
  Run Commands from running simultaneously. (`state.py`, `checks.py`)
- **Audit log channel**: every privileged action posts a one-line embed
  to `discord.audit_channel_id` if configured. (`audit.py`)
- **Per-command rate limits**: configurable via `rate_limit_overrides`.
- **Maintenance mode**: `/maintenance on` blocks all player-tier
  commands until an admin runs `/maintenance off`. Admins keep access
  to status/logs/health for triage.
- **Idempotent confirm prompts**: ConfirmView rejects the second click
  on the same prompt to prevent button-spam double-fires.

## 5. Things to monitor

- Container App logs for `auth` denials (suspicious traffic).
- Audit channel for anomalous patterns (admin commands at odd hours,
  back-to-back stop/start).
- Azure activity log for the VM — unexpected RunCommand invocations
  outside the bot's identity are a serious flag.
- Steam update applies that changed the major version (the wrapper
  records this; review before next session).
