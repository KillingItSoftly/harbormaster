# NSSM Service Pattern

NSSM (the [Non-Sucking Service Manager](https://nssm.cc)) wraps any executable as a Windows service. For a self-hosted game server, this means: auto-start at boot, auto-restart on crash, log capture with rotation, all without writing a service in C# or messing with `sc.exe`.

This is the pattern Harbormaster uses for every game server it manages.

## Why NSSM over Task Scheduler

Both can launch a process at boot, but NSSM is genuinely better for long-running processes:

- **Real Windows service** — appears in `services.msc`, status reflects whether the process is alive, can be managed with `Get-Service` / `Stop-Service` / etc.
- **Auto-restart on crash** — if the process exits unexpectedly, NSSM restarts it after a configurable delay
- **Log capture with rotation** — stdout and stderr go to files, with size-based rotation so they don't grow forever
- **Throttle protection** — won't restart a crash-looping process more than once per N seconds

Task Scheduler can fake some of this with retry-on-failure settings, but it's clunky and doesn't model "is this process currently alive?" well.

## Installing NSSM

```powershell
Invoke-WebRequest -Uri 'https://nssm.cc/release/nssm-2.24.zip' -OutFile "$env:TEMP\nssm.zip"
Expand-Archive -Path "$env:TEMP\nssm.zip" -DestinationPath 'C:\Tools' -Force
Copy-Item 'C:\Tools\nssm-2.24\win64\nssm.exe' 'C:\Windows\System32\nssm.exe'
```

Verify: `nssm version` should print `NSSM 2.24`.

NSSM 2.24 (the current stable) doesn't support the `AppEvents` parameter for lifecycle hooks — that was added in pre-release 2.25 builds. For most game server use cases, 2.24 is plenty.

## The standard service config

This is the canonical setup Harbormaster uses for any game server:

```powershell
$serviceName = 'YourGameServer'
$serverDir   = 'C:\GameServers\YourGame'
$serverExe   = "$serverDir\YourGameServer.exe"

nssm install $serviceName $serverExe
nssm set $serviceName AppDirectory $serverDir
nssm set $serviceName DisplayName "Your Game Dedicated Server"
nssm set $serviceName Description "Game server managed by Harbormaster"

# Start at boot
nssm set $serviceName Start SERVICE_AUTO_START

# Auto-restart on crash, with throttling
nssm set $serviceName AppExit Default Restart
nssm set $serviceName AppRestartDelay 5000        # wait 5s before restart
nssm set $serviceName AppThrottle 60000           # don't restart faster than once/60s

# Log capture
$logDir = "$serverDir\logs"
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
nssm set $serviceName AppStdout "$logDir\server-stdout.log"
nssm set $serviceName AppStderr "$logDir\server-stderr.log"

# Log rotation: 10 MB per file, online rotation (no service restart needed)
nssm set $serviceName AppRotateFiles 1
nssm set $serviceName AppRotateOnline 1
nssm set $serviceName AppRotateBytes 10485760
```

## Pointing at the right thing

NSSM monitors whatever process you give it. Two common patterns:

### Direct executable (preferred when possible)

```powershell
nssm set $serviceName Application "$serverDir\GameServer.exe"
```

NSSM watches `GameServer.exe` directly. When it crashes, NSSM sees the exit immediately and triggers restart logic. Simplest and most reliable.

### Batch wrapper (when you need pre-launch steps)

If the game requires something before launch (mod pak rebuilds, environment setup, etc.), point NSSM at a batch file:

```powershell
nssm set $serviceName Application "$serverDir\start-with-prerun.bat"
```

The batch must call the exe directly with no `start` command — using `start` spawns the exe as a separate process and the batch exits, which NSSM interprets as the service dying.

```bat
@echo off
REM Pre-launch step
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0prelaunch.ps1"
if errorlevel 1 exit /b %errorlevel%

REM Run the server (no `start`!)
GameServer.exe
```

The downside: NSSM monitors `cmd.exe` (the batch interpreter) rather than the game exe. Crash detection still works (when `GameServer.exe` exits, the batch exits, NSSM sees `cmd.exe` exit), but it's one indirection layer.

## Throttle settings matter

The default `AppThrottle` of 1500 ms is too aggressive for most game servers. A crash loop where the server starts, fails, and restarts every 1.5 seconds will hammer your save state, potentially corrupt RocksDB databases, and burn through Steam API rate limits if the server tries to phone home on each start.

**Recommended**: 60 seconds (`60000`). Gives the server a fighting chance to either start cleanly or for whatever transient condition to clear, while still being responsive enough that real crashes get attention quickly.

## Useful commands

```powershell
nssm start <name>         # start the service
nssm stop <name>          # stop the service
nssm restart <name>       # restart
nssm status <name>        # current state
nssm edit <name>          # GUI dialog to tweak any setting
nssm remove <name>        # uninstall the service entirely (with confirm)
nssm get <name> AppExit Default   # read a specific setting
```

## Verifying the service config

```powershell
Get-Service $serviceName
nssm get $serviceName Application
nssm get $serviceName AppDirectory
nssm get $serviceName AppExit Default
```

A working service shows `Status: Running` and the application path matches your expectation.

## Common failure modes

### "Unexpected status SERVICE_STOPPED in response to START control"

NSSM reports this when the service starts but the wrapped process dies immediately. Causes, in rough order of frequency:

1. **The Application path doesn't exist.** Double-check spelling; `Get-ChildItem` the directory to confirm.
2. **Missing DLLs** (VC++ redistributables, DirectX, etc.). Run the exe manually from PowerShell to see the dialog.
3. **The Application is a `.bat` that uses `start`** — see "Batch wrapper" above; the batch exits, NSSM thinks the service died.
4. **Wrong working directory** — `AppDirectory` needs to be set to where the exe expects to find its config/data files.

Check `C:\GameServers\YourGame\logs\server-stderr.log` and the NSSM event log:

```powershell
Get-EventLog -LogName Application -Source nssm -Newest 10 | Format-List
```

NSSM logs why each wrapped process exited.

### Service runs but server isn't accessible

Service is up, but players can't connect. Usually:

1. **Windows Firewall blocking** — add a rule for the exe:
```powershell
   New-NetFirewallRule -DisplayName "Game Server" -Direction Inbound `
       -Program "C:\GameServers\YourGame\GameServer.exe" -Action Allow
```
2. **Azure NSG blocking the port** — if the game uses fixed ports rather than NAT punch-through, open them in the NSG.

### Crash loops

If you see lots of restarts in `Get-EventLog`, raise the throttle (`nssm set <name> AppThrottle 60000`) so it doesn't hammer. Then dig into the logs to find the actual crash cause.