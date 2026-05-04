<#
.SYNOPSIS
    Posts a "server is going offline soon" warning to Discord and stops the
    service. Optionally runs a final backup first so no progress is lost.

.DESCRIPTION
    Game-agnostic. Designed to run shortly before scheduled VM shutdown
    (e.g. as a scheduled task at 12:50 AM if shutdown is 1:00 AM). Posts a
    Discord embed to the Status channel announcing imminent shutdown.

    With -StopService:
      1. Posts the warning embed.
      2. Sleeps -ShutdownGraceSeconds.
      3. By default, runs Backup-GameServer.ps1 -SkipAnnounce -NoRestart
         so the final state is captured to blob storage. Pass -SkipBackup
         to opt out (e.g. for emergency stops).
      4. Stops the NSSM-managed service.
      5. Drops a sentinel file so the next Announce-ServerOnline.ps1 run
         stays quiet until a real boot.

.PARAMETER Config
    Per-game config hashtable.

.PARAMETER MinutesUntilShutdown
    Number of minutes until the VM goes down. Used in the message text.

.PARAMETER StopService
    If set, stops the NSSM-managed service after warning so the server
    has time to flush save data before the VM is deallocated.

.PARAMETER ShutdownGraceSeconds
    Seconds to wait between sending the warning and starting the
    backup/stop sequence. Default 60. Ignored unless -StopService is set.

.PARAMETER SkipBackup
    Skip the final pre-shutdown backup. Default behavior (no switch) is
    to run a backup so save data is captured to blob storage before the
    service goes down.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [hashtable]$Config,

    [int]$MinutesUntilShutdown = 10,

    [switch]$StopService,

    [int]$ShutdownGraceSeconds = 60,

    [switch]$SkipBackup
)

$ErrorActionPreference = 'Stop'

$moduleRoot = Join-Path $PSScriptRoot '..\modules'
Import-Module (Join-Path $moduleRoot 'HarbormasterNotify.psm1') -Force

$message = "Server going offline in ~$MinutesUntilShutdown minute(s) for nightly maintenance. Save your progress now."
if ($StopService) {
    $message += " Service will stop in $ShutdownGraceSeconds seconds."
    if (-not $SkipBackup) {
        $message += " A final backup will run before shutdown."
    }
}

Send-HarbormasterNotification `
    -Config $Config `
    -Title "$($Config.GameName) shutting down soon" `
    -Message $message `
    -Severity Warning `
    -Channel Status `
    -Fields @{
        'Time remaining' = "$MinutesUntilShutdown min"
        Service          = $Config.ServiceName
        'Final backup'   = if ($StopService -and -not $SkipBackup) { 'yes' } else { 'no' }
    }

if ($StopService) {
    Start-Sleep -Seconds $ShutdownGraceSeconds

    # Drop a sentinel file so Announce-ServerOnline.ps1 (which runs at the
    # next boot, or via any other trigger) knows this was an admin-initiated
    # shutdown and suppresses its "online" message until the next real boot.
    $stateDir     = Join-Path $env:ProgramData 'Harbormaster'
    $sentinelPath = Join-Path $stateDir ("shutdown-{0}.flag" -f $Config.GameName)
    try {
        if (-not (Test-Path $stateDir)) {
            New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
        }
        Set-Content -Path $sentinelPath -Value (Get-Date -Format o) -Force
    }
    catch {
        Write-Warning "Failed to write shutdown sentinel '$sentinelPath': $_"
    }

    # --- Final backup (default on; pass -SkipBackup to disable) -------------
    # Backup-GameServer.ps1 stops the service itself, zips, uploads, and with
    # -NoRestart leaves the service stopped — exactly what we want before
    # deallocating the VM. -SkipAnnounce avoids a duplicate "going offline"
    # message since we already posted one above.
    if (-not $SkipBackup) {
        $backupScript = Join-Path $PSScriptRoot 'Backup-GameServer.ps1'
        try {
            Write-Host "Running pre-shutdown backup..."
            & $backupScript -Config $Config -SkipAnnounce -NoRestart
        }
        catch {
            Send-HarbormasterNotification `
                -Config $Config `
                -Title 'Pre-shutdown backup FAILED' `
                -Message ("Backup error before shutdown: $_`n" +
                          "Continuing with service stop and VM deallocation.") `
                -Severity Critical `
                -Channel Alerts
            # Fall through — we still want to stop the service and let the VM
            # deallocate. Failing the whole shutdown because the backup blew
            # up would leave the VM running forever.
        }
    }

    # --- Stop the service ---------------------------------------------------
    $svc = Get-Service $Config.ServiceName -ErrorAction SilentlyContinue
    if ($svc -and $svc.Status -eq 'Running') {
        try {
            Write-Host "Stopping service '$($Config.ServiceName)' for clean shutdown..."
            Stop-Service $Config.ServiceName -Force
            Send-HarbormasterNotification `
                -Config $Config `
                -Title "$($Config.GameName) is offline" `
                -Message 'Service stopped cleanly. VM shutdown is next.' `
                -Severity Info `
                -Channel Status
        }
        catch {
            Send-HarbormasterNotification `
                -Config $Config `
                -Title 'Service failed to stop cleanly' `
                -Message "Could not stop '$($Config.ServiceName)' before VM shutdown: $_" `
                -Severity Critical `
                -Channel Alerts
            throw
        }
    }
    else {
        # Backup with -NoRestart will have left the service stopped already,
        # which is the expected case here.
        Write-Host "Service '$($Config.ServiceName)' is not running; nothing to stop."
        Send-HarbormasterNotification `
            -Config $Config `
            -Title "$($Config.GameName) is offline" `
            -Message 'Service is stopped. VM shutdown is next.' `
            -Severity Info `
            -Channel Status
    }
}
