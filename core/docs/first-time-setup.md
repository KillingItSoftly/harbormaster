# First-Time Setup

End-to-end walkthrough for setting up Harbormaster on a fresh Azure VM. Plan for 2-3 hours the first time you do this. After that, adding a second game on the same VM is closer to 30 minutes.

> **Heads up:** This guide uses Windrose as the running example because that's what Harbormaster was originally built for. The pattern works for any Steam-distributed Windows game server. Substitute your game's specifics where indicated.

## What you'll have at the end

- A Windows VM running on Azure with auto-shutdown/start scheduling
- A game server wrapped as a Windows service (auto-starts at boot, auto-restarts on crash)
- Daily backups of save data to Azure Blob Storage
- Discord notifications when things break
- Healthchecks.io heartbeats so you find out fast if the automation itself stops running
- A milestone snapshot system for rolling back risky changes

## Prerequisites

- An Azure subscription (free trial works for getting started)
- A Discord server you control, for notifications
- A free [Healthchecks.io](https://healthchecks.io) account
- The game you're hosting, on Steam (the dedicated server tool needs to be available via SteamCMD)

You don't need any particular dev tools on your local machine — everything in this guide runs on the VM itself via RDP.

## Quick reference: the five phases

1. **Create the Azure VM and storage account** (~30 min)
2. **Prep the VM and install dependencies** (~20 min)
3. **Install the game server and wrap it with NSSM** (~30 min)
4. **Clone Harbormaster and configure for your game** (~20 min)
5. **Wire up monitoring (Healthchecks + Discord) and scheduled tasks** (~30 min)

Each phase has a verification step at the end. Don't move on until that step works — debugging gets harder when there are multiple unverified pieces stacked up.

---

## Phase 1: Azure infrastructure

See [azure-vm-setup.md](azure-vm-setup.md) for the full reasoning behind these choices. The condensed setup:

### Create the VM

In the Azure portal, create a new VM with:

- **Image**: Windows Server 2022 Datacenter (Azure Edition)
- **Size**: `Standard_D4s_v5` (4 vCPU, 16 GB RAM)
- **Authentication**: Password
- **Inbound ports**: RDP (3389) only
- **OS disk**: Premium SSD, 128 GB
- **Public IP**: Standard, **static** (this matters)
- **Resource group**: a new one named after your project (e.g., `harbormaster-rg`)

Restrict the RDP NSG rule to your home IP rather than `*`. You can find your IP by visiting [whatismyip.com](https://whatismyip.com) and using that with `/32`.

### Enable system-assigned managed identity

Once the VM is created: VM → **Identity** (under Security) → **System assigned** → **Status: On** → Save. This is how the VM authenticates to Azure Storage without needing keys stored on disk.

### Create the storage account

Storage Accounts → Create:

- **Same resource group** as the VM
- **Name**: globally unique, lowercase alphanumeric (e.g., `harbormasterbackups<random>`)
- **Region**: same as the VM (cross-region transfers cost money)
- **Performance**: Standard
- **Redundancy**: LRS (cheapest, fine for game saves)

Configuration tab:
- **Allow storage account key access**: Disabled

Networking tab:
- **Public network access**: Enabled from selected virtual networks
- Add the VM's VNet, enable the `Microsoft.Storage` service endpoint when prompted

Data protection tab:
- Enable **Soft delete for blobs** (14 days)
- Enable **Soft delete for containers** (14 days)
- Enable **Versioning** (optional but recommended)

### Create the blob container

Once the storage account is provisioned, open it → **Containers** → **+ Container**:
- **Name**: `<game>-backups` (e.g., `windrose-backups`)
- **Anonymous access**: Private

### Grant the VM access to the storage account

Storage account → **Access Control (IAM)** → **+ Add** → **Add role assignment**:
- **Role**: `Storage Blob Data Contributor`
- **Members**: Managed identity → your VM
- Review + Assign

Wait 1-2 minutes for the role assignment to propagate.

### Set up auto-shutdown

VM → Operations → **Auto-shutdown**:
- **Enabled**: On
- **Time**: a time when nobody plays (e.g., 1 or 2 AM)
- **Timezone**: yours
- **Notification**: optional, can wire to Discord later

### Set up auto-start (Azure Automation)

This is more involved. See `azure/runbooks/` in the repo for the runbook scripts and `core/docs/azure-vm-setup.md` for the step-by-step. The summary:

1. Create an Automation Account in the same region as the VM
2. Enable system-assigned managed identity on the Automation Account
3. Grant it `Virtual Machine Contributor` on the VM
4. Import the runbooks from `azure/runbooks/`
5. Create schedules for the times you want the VM up
6. Link the schedules to the runbooks

Day-of-week schedules: create one runbook (`Start-VM`) and attach two schedules to it — one for weekdays, one for weekends, with different times.

### ✅ Phase 1 verification

Before moving on:

- [ ] You can RDP to the VM
- [ ] The storage account exists and you can see it in the portal
- [ ] The blob container exists
- [ ] Auto-shutdown fires at the configured time (test by leaving the VM up overnight)
- [ ] Auto-start fires when expected (test by manually stopping the VM and waiting for the next scheduled start)

---

## Phase 2: VM preparation

RDP into the VM. From here on, everything runs on the VM unless noted.

### Disable IE Enhanced Security

Server Manager → Local Server → IE Enhanced Security Configuration → Off for both Administrators and Users. Without this, every download is a battle.

### Install VC++ redistributables

Most modern games need these. In an admin PowerShell:

```powershell
Invoke-WebRequest 'https://aka.ms/vs/17/release/vc_redist.x64.exe' -OutFile "$env:TEMP\vc.exe"
Start-Process "$env:TEMP\vc.exe" -ArgumentList '/install','/quiet','/norestart' -Wait
```

### Set execution policy

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope LocalMachine
```

### Install Az PowerShell modules

For blob backups and Azure auth:

```powershell
Install-Module -Name Az.Accounts -Force -AllowClobber -Scope AllUsers
Install-Module -Name Az.Storage -Force -AllowClobber -Scope AllUsers
```

This takes a few minutes. Both modules together pull ~100 MB.

### Install SteamCMD

```powershell
New-Item -ItemType Directory -Path 'C:\SteamCMD' -Force | Out-Null
Invoke-WebRequest -Uri 'https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip' -OutFile 'C:\SteamCMD\steamcmd.zip'
Expand-Archive -Path 'C:\SteamCMD\steamcmd.zip' -DestinationPath 'C:\SteamCMD'
& 'C:\SteamCMD\steamcmd.exe' +quit  # let it self-update on first run
```

### Install NSSM

```powershell
Invoke-WebRequest -Uri 'https://nssm.cc/release/nssm-2.24.zip' -OutFile "$env:TEMP\nssm.zip"
Expand-Archive -Path "$env:TEMP\nssm.zip" -DestinationPath 'C:\Tools' -Force
Copy-Item 'C:\Tools\nssm-2.24\win64\nssm.exe' 'C:\Windows\System32\nssm.exe'
nssm version  # should print 'NSSM 2.24'
```

### Install Git

```powershell
Invoke-WebRequest -Uri 'https://github.com/git-for-windows/git/releases/download/v2.43.0.windows.1/Git-2.43.0-64-bit.exe' -OutFile "$env:TEMP\git.exe"
Start-Process "$env:TEMP\git.exe" -ArgumentList '/VERYSILENT','/NORESTART' -Wait
```

(Adjust the URL to whatever the current Git for Windows release is.) You'll need this for cloning the Harbormaster repo.

### Test that the VM can reach Azure storage

```powershell
Connect-AzAccount -Identity
Get-AzStorageAccount  # should list your storage account
```

If `Connect-AzAccount` fails with auth errors, the managed identity probably hasn't propagated yet — wait 5 minutes and try again.

### ✅ Phase 2 verification

```powershell
# All these should succeed without errors
Get-Command nssm
Get-Command git
Get-Module -ListAvailable Az.Accounts
Get-Module -ListAvailable Az.Storage
Test-Path 'C:\SteamCMD\steamcmd.exe'
[Environment]::GetEnvironmentVariable('PSExecutionPolicyPreference', 'LocalMachine')
```

---

## Phase 3: Install the game server with NSSM

This phase is the most game-specific. The example below is Windrose; adjust paths and Steam app ID for your game.

See [nssm-service-pattern.md](nssm-service-pattern.md) for the reasoning behind the NSSM config choices.

### Install via SteamCMD

```powershell
New-Item -ItemType Directory -Path 'C:\GameServers\Windrose' -Force | Out-Null

# Create an update batch file you can re-run on every game patch
@'
@echo off
"C:\SteamCMD\steamcmd.exe" ^
  +force_install_dir "C:\GameServers\Windrose" ^
  +login anonymous ^
  +app_update 4129620 validate ^
  +quit
'@ | Out-File -FilePath 'C:\SteamCMD\windrose-update.bat' -Encoding ASCII

# Run it for the initial install
& 'C:\SteamCMD\windrose-update.bat'
```

For other games, change `C:\GameServers\Windrose` and the Steam app ID (`4129620` for Windrose). Look up the app ID via SteamDB or your hosting provider's docs.

The install can take 10-30 minutes depending on the game's size.

### Find the actual server executable

After install, locate the real exe. For Windrose, it's typically in a nested path:

```powershell
Get-ChildItem 'C:\GameServers\Windrose' -Recurse -Filter '*Server.exe' |
    Select-Object FullName, Length
```

You'll get one (or several) matches. The one with `Server.exe` in the name and a meaningful size is your target. Note the path.

### First boot: generate default configs

Run the server interactively once to let it generate its config files:

```powershell
& 'C:\GameServers\Windrose\R5\Builds\WindroseServer\StartServerForeground.bat'
```

(Or whatever your game's launcher is.) Wait for the log output to settle. Note the **invite code** if one is printed — you may need it later. Then close the console window cleanly to shut down.

### Wrap as a Windows service with NSSM

```powershell
$serviceName = 'WindroseServer'
$serverDir   = 'C:\GameServers\Windrose\R5\Builds\WindroseServer'
$serverExe   = "$serverDir\WindroseServer.exe"

nssm install $serviceName $serverExe
nssm set $serviceName AppDirectory $serverDir
nssm set $serviceName DisplayName "Windrose Dedicated Server"
nssm set $serviceName Description "Windrose game server managed by Harbormaster"

nssm set $serviceName Start SERVICE_AUTO_START

nssm set $serviceName AppExit Default Restart
nssm set $serviceName AppRestartDelay 5000
nssm set $serviceName AppThrottle 60000

$logDir = "$serverDir\logs"
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
nssm set $serviceName AppStdout "$logDir\server-stdout.log"
nssm set $serviceName AppStderr "$logDir\server-stderr.log"
nssm set $serviceName AppRotateFiles 1
nssm set $serviceName AppRotateOnline 1
nssm set $serviceName AppRotateBytes 10485760

nssm start $serviceName
```

### Open Windows Firewall for the server

```powershell
New-NetFirewallRule -DisplayName "Windrose Server In" -Direction Inbound -Program $serverExe -Action Allow
New-NetFirewallRule -DisplayName "Windrose Server Out" -Direction Outbound -Program $serverExe -Action Allow
```

### ✅ Phase 3 verification

```powershell
Get-Service WindroseServer  # Status: Running
Get-Content "$logDir\server-stdout.log" -Tail 50  # should show startup logs, not errors
```

Have a friend connect to the server using the invite code. If they can join and play, the game install is solid.

If the service won't start, the most common causes are:

1. Wrong path to the exe → double-check `nssm get WindroseServer Application`
2. Missing DLLs → run the exe manually and read the error dialog
3. The server's "WindroseServer" folder inside the main game install is being launched instead of a copy → see Windrose-specific docs in `games/windrose/`

---

## Phase 4: Clone Harbormaster and configure

### Clone the repo

```powershell
New-Item -ItemType Directory -Path 'C:\Scripts' -Force | Out-Null
git clone https://github.com/<your-username>/harbormaster.git C:\Scripts\harbormaster
```

(If your repo is private, you'll need to authenticate to GitHub. For an unattended VM, a personal access token is easier than SSH keys.)

### Create the game-specific config

```powershell
Copy-Item 'C:\Scripts\harbormaster\games\_template\config.ps1' 'C:\Scripts\harbormaster\games\windrose\config.ps1'
```

Open the new `config.ps1` and fill in:

- `GameName` — the friendly name (`Windrose`)
- `EnvVarPrefix` — env var prefix in caps (`WINDROSE`)
- `SteamAppId` — your game's app ID
- `InstallDir` — where SteamCMD installed the server
- `ServiceName` — the NSSM service name
- `SavedDataPath` — the folder containing save data (the thing you want backed up)
- `LogPath` — full path to the stdout log file
- `LocalBackupRoot` — where local backups land
- `StorageAccount` — your Azure storage account name
- `BlobContainer` — your blob container name
- `LocalRetention` — days to keep local backups (default 14)
- `BlobRetention` — days to keep blob backups (default 30)
- `CrashLogPattern` — regex pattern for crash detection (game-specific; for Windrose: `Crash Stack Trace`)
- `LogTimestampRegex` — pattern for parsing timestamps from log lines

For Windrose specifically, see `games/windrose/README.md` for the values.

### Test the config loads cleanly

```powershell
$config = & 'C:\Scripts\harbormaster\games\windrose\config.ps1'
$config | Format-List
```

You should see all the expected keys with your values. If anything's missing or null, fix the config before moving on.

### ✅ Phase 4 verification

```powershell
Test-Path 'C:\Scripts\harbormaster\core\modules\HarbormasterNotify.psm1'
Test-Path 'C:\Scripts\harbormaster\games\windrose\config.ps1'

# Modules load without error
Import-Module 'C:\Scripts\harbormaster\core\modules\HarbormasterNotify.psm1' -Force
Import-Module 'C:\Scripts\harbormaster\core\modules\HarbormasterHealthchecks.psm1' -Force
Get-Command Send-WindroseNotification, Send-Heartbeat
```

---

## Phase 5: Wire up monitoring

### Set up Discord webhooks

For each notification channel (see [discord-channels.md](discord-channels.md)):

1. Discord → Server Settings → Integrations → Webhooks → New Webhook
2. Name it descriptively
3. Copy the URL

Set them as machine env vars:

```powershell
[Environment]::SetEnvironmentVariable('WINDROSE_WEBHOOK_ALERTS',  '<url>', 'Machine')
[Environment]::SetEnvironmentVariable('WINDROSE_WEBHOOK_STATUS',  '<url>', 'Machine')

# Refresh current session
$env:WINDROSE_WEBHOOK_ALERTS = [Environment]::GetEnvironmentVariable('WINDROSE_WEBHOOK_ALERTS', 'Machine')
$env:WINDROSE_WEBHOOK_STATUS = [Environment]::GetEnvironmentVariable('WINDROSE_WEBHOOK_STATUS', 'Machine')
```

Test:

```powershell
Send-WindroseNotification `
    -Title 'Setup test' `
    -Message 'If you see this, Discord webhooks are working.' `
    -Severity Info `
    -Channel Status
```

You should see the message appear in your Discord channel within a second or two. If not, check [discord-channels.md](discord-channels.md) for troubleshooting.

### Set up Healthchecks.io

See [healthchecks-cron.md](healthchecks-cron.md) for the full setup. Quick version:

1. Sign up at [healthchecks.io](https://healthchecks.io)
2. Create five checks (or whatever subset you need):

   | Check name | Cron | Grace |
   |---|---|---|
   | Windrose Backup | `30 0 * * *` | 1 hour |
   | Windrose Update Check (Weekday) | `5 14 * * 1-4` | 30 min |
   | Windrose Update Check (Weekend) | `5 9 * * 5,6,0` | 30 min |
   | Windrose Health (Weekday) | `*/15 14-23 * * 1-4` | 30 min |
   | Windrose Health (Weekend) | `*/15 9-23 * * 5,6,0` | 30 min |

   Adjust the cron expressions to match your VM's actual uptime schedule.

3. For each check, **Integrations** tab → add Email and/or a Discord webhook integration

4. Set the env vars on the VM:
```powershell
   [Environment]::SetEnvironmentVariable('WINDROSE_HC_BACKUP', '<url>', 'Machine')
   [Environment]::SetEnvironmentVariable('WINDROSE_HC_UPDATE_CHECK_WEEKDAY', '<url>', 'Machine')
   [Environment]::SetEnvironmentVariable('WINDROSE_HC_UPDATE_CHECK_WEEKEND', '<url>', 'Machine')
   [Environment]::SetEnvironmentVariable('WINDROSE_HC_HEALTH_WEEKDAY', '<url>', 'Machine')
   [Environment]::SetEnvironmentVariable('WINDROSE_HC_HEALTH_WEEKEND', '<url>', 'Machine')

   # Refresh current session
   foreach ($name in 'WINDROSE_HC_BACKUP','WINDROSE_HC_UPDATE_CHECK_WEEKDAY','WINDROSE_HC_UPDATE_CHECK_WEEKEND','WINDROSE_HC_HEALTH_WEEKDAY','WINDROSE_HC_HEALTH_WEEKEND') {
       Set-Item "env:$name" ([Environment]::GetEnvironmentVariable($name, 'Machine'))
   }
```

5. Test heartbeats:
```powershell
   Import-Module 'C:\Scripts\harbormaster\core\modules\HarbormasterHealthchecks.psm1' -Force
   Send-Heartbeat -EnvVarName 'WINDROSE_HC_BACKUP' -Status Success
```
   Check the Healthchecks dashboard — the corresponding check should show "Up" with a recent ping.

### Run each script manually once

Before scheduling them, verify each one works end-to-end:

```powershell
# Take an initial milestone snapshot (your "vanilla baseline")
& 'C:\Scripts\harbormaster\games\windrose\Snapshot-Windrose.ps1' -Label 'first-time-setup-baseline' -Category pristine

# Run a manual backup
& 'C:\Scripts\harbormaster\games\windrose\Backup-Windrose.ps1'

# Run an update check (no -ApplyUpdate, just check)
& 'C:\Scripts\harbormaster\games\windrose\Check-WindroseUpdate.ps1'

# Run the health check
& 'C:\Scripts\harbormaster\games\windrose\Check-WindroseHealth.ps1'
```

Each should complete without errors. Discord and Healthchecks should reflect what each script reported.

### Register scheduled tasks

See `examples/scheduled-tasks.ps1` in the repo for the full block. The summary:

| Task | Trigger |
|---|---|
| `WindroseBackup` | Daily at 12:30 AM |
| `WindroseUpdateCheck` | 14:05 Mon-Thu, 9:05 Fri-Sun |
| `WindroseHealthCheck` | Every 15 minutes (continuous repetition) |
| `WindroseAnnounceStart` | At system startup, 60-second delay |
| `WindroseShutdownWarning` | Daily at 12:50 AM |

All run as SYSTEM with `RunLevel Highest`.

### ✅ Phase 5 verification

After scheduling everything, give it a day to run on its own and check:

- [ ] Healthchecks dashboard shows all checks as "Up" with recent pings
- [ ] No unexpected Discord alerts (alerts should be quiet during normal operation)
- [ ] Backup ran at 12:30 AM (check the blob container for a new zip)
- [ ] Update check ran at the scheduled time (check `C:\Logs\Windrose-UpdateCheck.log`)
- [ ] Health check is firing every 15 minutes (check `C:\Logs\windrose-health-state.json` is being updated)

---

## You're done

The setup is now self-monitoring. You'll find out about:

- Crashes and restarts (Discord alerts)
- Backup or update failures (Discord alerts + Healthchecks)
- Disk filling up (Discord alerts)
- Any of the automation tasks not running (Healthchecks)

You should be able to walk away and not think about the server unless Discord or Healthchecks pings you.

## What's next

A few things worth doing in the first week or two:

- **Test a restore.** Pick a milestone snapshot and walk through restoring it to a test directory (don't replace the live world). The first time you actually need to restore is the worst time to find out the process doesn't work.
- **Update something.** When the next game patch hits, run `Check-WindroseUpdate.ps1 -ApplyUpdate` manually first time so you can watch the snapshot/update/restart flow happen.
- **Take a `pristine` snapshot.** Mark your current setup as a permanent rollback point so you always have a known-good state to fall back to.
- **Test alert delivery.** Manually ping `/fail` on one of your Healthchecks URLs to confirm the alert path works end-to-end. Better to discover broken integrations now than during a real failure.

## Adding a second game

Once Harbormaster is set up for one game, adding another is faster:

1. Install via SteamCMD (different `force_install_dir`)
2. Create a second NSSM service
3. Copy `games/<existing>/` to `games/<new-game>/`, update `config.ps1`
4. Set new env vars with the `<NEWGAME>_*` prefix
5. Create new Healthchecks checks
6. Register scheduled tasks pointing at the new wrappers

Most of the heavy lifting is done — you're just creating a new tenant inside the existing infrastructure.

## Getting help

- **Game-specific issues**: check `games/<gamename>/README.md` for that game's quirks
- **Azure issues**: [azure-vm-setup.md](azure-vm-setup.md)
- **NSSM issues**: [nssm-service-pattern.md](nssm-service-pattern.md)
- **Discord issues**: [discord-channels.md](discord-channels.md)
- **Healthchecks issues**: [healthchecks-cron.md](healthchecks-cron.md)

If something genuinely doesn't work, that's a candidate for a documentation gap — file an issue in the repo so future-you (or anyone else following this guide) gets a better experience.