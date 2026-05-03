# Install

One-shot bootstrap for a fresh Windows VM. Idempotent — safe to re-run.

## Quickest path

RDP into the VM, open an **elevated** PowerShell window, and run:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
$url = 'https://raw.githubusercontent.com/twlorenz/harbormaster/main/install/Install-Harbormaster.ps1'
Invoke-WebRequest $url -OutFile "$env:TEMP\Install-Harbormaster.ps1" -UseBasicParsing
& "$env:TEMP\Install-Harbormaster.ps1"
```

Replace the URL with your fork if you're using one.

## What it does

1. Sets `LocalMachine` execution policy to `RemoteSigned`.
2. Installs the VC++ 2015-2022 x64 redistributable.
3. Installs `Az.Accounts` and `Az.Storage` from the PSGallery (AllUsers).
4. Installs NSSM 2.24 to `C:\Tools\nssm` and copies `nssm.exe` to `System32`.
5. Installs SteamCMD to `C:\SteamCMD` and runs it once to self-update.
6. Clones (or `git pull`s) the Harbormaster repo to `C:\Scripts\harbormaster`.
7. Creates `C:\Logs`, `C:\Backups`, `C:\GameServers`.

Each step skips the work if it's already done.

## Common parameters

```powershell
.\Install-Harbormaster.ps1 `
    -InstallDir 'C:\Scripts\harbormaster' `
    -RepoUrl 'https://github.com/KillingItSoftly/harbormaster.git' `
    -Branch 'develop'
```

To re-run a single piece (e.g. just refresh the repo):

```powershell
.\Install-Harbormaster.ps1 -SkipVCRedist -SkipAzModules -SkipNssm -SkipSteamCmd
```

## What it doesn't do

These have to happen elsewhere:

- **Enable the VM's system-assigned managed identity** — toggle on the VM
  resource in Azure (portal or `az vm identity assign`).
- **Grant Storage Blob Data Contributor** to that identity on your backup
  storage account.
- **Set webhook / Healthchecks env vars** — these are secrets and the script
  doesn't ask for them. Set in `Machine` scope so scheduled tasks running
  as SYSTEM see them.
- **Wrap the game server as an NSSM service** — game-specific. See
  [core/docs/nssm-service-pattern.md](../core/docs/nssm-service-pattern.md).
- **Fill in `games/<slug>/config.ps1`** — paths and IDs are per-game.
