<#
.SYNOPSIS
    Check for and optionally apply dedicated server updates from Steam.

.DESCRIPTION
    Compares the installed dedicated server build against the current public
    build on Steam. Can run in check-only mode (default) or apply mode.

    When -ApplyUpdate is set, takes a milestone snapshot via the sibling
    Manage-Milestones.ps1 (using the same -Config) before applying the
    update. If the snapshot fails, the update is aborted to preserve a
    rollback point.

    Designed to be run from Task Scheduler. Returns:
      Exit 0 - no update available, or update applied successfully
      Exit 1 - update is available (when -ApplyUpdate is not set)
      Exit 2 - error checking, snapshotting, or applying update

.PARAMETER Config
    Hashtable with at least:
      GameName, EnvVarPrefix
      SteamAppId, InstallDir, SteamCmdPath
      ServiceName

.PARAMETER ApplyUpdate
    If set, takes a snapshot then downloads and installs the update via
    SteamCMD. The service will be stopped before the update and restarted
    after.

.PARAMETER NotifyOnly
    If set, only checks and reports. Does not apply updates even if available.

.PARAMETER LogPath
    Where to write the log file. Defaults to
    C:\Logs\<GameName>-UpdateCheck.log.

.PARAMETER SkipSnapshot
    If set with -ApplyUpdate, skips the pre-update snapshot. Use with caution.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [hashtable]$Config,

    [switch]$ApplyUpdate,
    [switch]$NotifyOnly,
    [string]$LogPath,
    [switch]$SkipSnapshot
)

$ErrorActionPreference = 'Stop'

$moduleRoot = Join-Path $PSScriptRoot '..\modules'
Import-Module (Join-Path $moduleRoot 'HarbormasterNotify.psm1') -Force
Import-Module (Join-Path $moduleRoot 'HarbormasterHealthchecks.psm1') -Force
Import-Module (Join-Path $moduleRoot 'HarbormasterLock.psm1') -Force

if (-not $LogPath) {
    $LogPath = "C:\Logs\$($Config.GameName)-UpdateCheck.log"
}

# Sibling milestone script — used for the pre-update snapshot.
$snapshotScriptPath = Join-Path $PSScriptRoot 'Manage-Milestones.ps1'

Send-Heartbeat -Config $Config -Key UPDATE_CHECK -Status Start -DayBucket

# ============================================================================
# Notification helper
# ============================================================================
function Notify {
    param(
        [Parameter(Mandatory)][string]$Title,
        [Parameter(Mandatory)][string]$Message,
        [string]$Severity = 'Info',
        [string]$Channel = 'Status',
        [hashtable]$Fields = @{}
    )
    Send-HarbormasterNotification `
        -Config $Config `
        -Title $Title `
        -Message $Message `
        -Severity $Severity `
        -Channel $Channel `
        -Fields $Fields
}

# ============================================================================
# Logging
# ============================================================================
function Write-Log {
    param(
        [string]$Message,
        [ValidateSet('INFO', 'WARN', 'ERROR', 'OK')]
        [string]$Level = 'INFO'
    )
    $timestamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    $line = "[$timestamp] [$Level] $Message"

    $logDir = Split-Path $LogPath -Parent
    if (-not (Test-Path $logDir)) {
        New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    }

    Add-Content -Path $LogPath -Value $line

    $color = switch ($Level) {
        'OK'    { 'Green' }
        'WARN'  { 'Yellow' }
        'ERROR' { 'Red' }
        default { 'White' }
    }
    Write-Host $line -ForegroundColor $color
}

# ============================================================================
# Get installed build ID
# ============================================================================
function Get-InstalledBuildId {
    $manifestPath = Join-Path $Config.InstallDir "steamapps\appmanifest_$($Config.SteamAppId).acf"

    if (-not (Test-Path $manifestPath)) {
        Write-Log "Manifest file not found at $manifestPath" -Level WARN
        return $null
    }

    $content = Get-Content $manifestPath -Raw

    if ($content -match '"buildid"\s+"(\d+)"') {
        return $Matches[1]
    }

    Write-Log "Could not parse buildid from manifest." -Level WARN
    return $null
}

# ============================================================================
# Get current public build ID from Steam
# ============================================================================
function Get-PublicBuildId {
    $url = "https://api.steamcmd.net/v1/info/$($Config.SteamAppId)"

    try {
        Write-Log "Querying Steam API at $url"
        $response = Invoke-RestMethod -Uri $url -Method Get -TimeoutSec 30

        if ($response.status -ne 'success') {
            Write-Log "Steam API returned status: $($response.status)" -Level WARN
            return $null
        }

        $publicBranch = $response.data.($Config.SteamAppId).depots.branches.public

        if (-not $publicBranch) {
            Write-Log "No 'public' branch found in API response." -Level WARN
            return $null
        }

        return @{
            BuildId  = $publicBranch.buildid
            TimeUpdated = if ($publicBranch.timeupdated) {
                [DateTimeOffset]::FromUnixTimeSeconds([long]$publicBranch.timeupdated).LocalDateTime
            } else { $null }
        }
    }
    catch {
        Write-Log "Failed to query Steam API: $_" -Level ERROR
        return $null
    }
}

# ============================================================================
# Take a pre-update snapshot
# ============================================================================
function Invoke-PreUpdateSnapshot {
    param(
        [string]$InstalledBuild,
        [string]$PublicBuild
    )

    if (-not (Test-Path $snapshotScriptPath)) {
        Write-Log "Snapshot script not found at $snapshotScriptPath" -Level ERROR
        return $false
    }

    $label = "before-update-from-${InstalledBuild}-to-${PublicBuild}"
    Write-Log "Taking pre-update snapshot with label: $label" -Level INFO

    try {
        & $snapshotScriptPath `
            -Config $Config `
            -Action Snapshot `
            -Label $label `
            -Category 'pre-change'

        if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) {
            Write-Log "Snapshot script exited with code $LASTEXITCODE" -Level ERROR
            return $false
        }

        Write-Log "Pre-update snapshot completed." -Level OK
        return $true
    }
    catch {
        Write-Log "Snapshot failed: $_" -Level ERROR
        return $false
    }
}

# ============================================================================
# Apply the update
# ============================================================================
function Invoke-Update {
    Write-Log "Starting update process..." -Level INFO

    $svc = Get-Service $Config.ServiceName -ErrorAction SilentlyContinue
    $wasRunning = $false
    if ($svc -and $svc.Status -eq 'Running') {
        Write-Log "Stopping $($Config.ServiceName)..." -Level INFO
        Stop-Service $Config.ServiceName -Force
        Start-Sleep -Seconds 10
        $wasRunning = $true
    }

    try {
        if (-not (Test-Path $Config.SteamCmdPath)) {
            throw "SteamCMD not found at $($Config.SteamCmdPath)"
        }

        Write-Log "Running SteamCMD update..." -Level INFO
        $steamCmdArgs = @(
            '+force_install_dir', "`"$($Config.InstallDir)`"",
            '+login', 'anonymous',
            '+app_update', $Config.SteamAppId, 'validate',
            '+quit'
        )

        $process = Start-Process `
            -FilePath $Config.SteamCmdPath `
            -ArgumentList $steamCmdArgs `
            -NoNewWindow `
            -Wait `
            -PassThru

        if ($process.ExitCode -ne 0) {
            throw "SteamCMD exited with code $($process.ExitCode)"
        }

        Write-Log "SteamCMD update completed successfully." -Level OK
    }
    finally {
        if ($wasRunning) {
            Write-Log "Restarting $($Config.ServiceName)..." -Level INFO
            try {
                Start-Service $Config.ServiceName
                Start-Sleep -Seconds 15
                $svc = Get-Service $Config.ServiceName
                if ($svc.Status -ne 'Running') {
                    Write-Log "Service did not start cleanly. Status: $($svc.Status)" -Level ERROR
                    Notify `
                        -Title 'Server failed to start' `
                        -Message "Update completed but service status is '$($svc.Status)'. Manual intervention needed." `
                        -Severity Critical `
                        -Channel Alerts
                } else {
                    Write-Log "Service restarted successfully." -Level OK
                }
            }
            catch {
                Write-Log "Failed to restart service: $_" -Level ERROR
                Notify `
                    -Title 'Server failed to start' `
                    -Message "Update completed but service start threw an error: $_" `
                    -Severity Critical `
                    -Channel Alerts
            }
        }
    }
}

# ============================================================================
# Main
# ============================================================================
Write-Log "=== $($Config.GameName) Update Check ==="

$installed = Get-InstalledBuildId
if (-not $installed) {
    Write-Log "Could not determine installed build. Aborting." -Level ERROR
    Send-Heartbeat -Config $Config -Key UPDATE_CHECK -Status Fail -DayBucket
    exit 2
}
Write-Log "Installed build: $installed"

$publicInfo = Get-PublicBuildId
if (-not $publicInfo) {
    Write-Log "Could not determine current public build. Aborting." -Level ERROR
    Send-Heartbeat -Config $Config -Key UPDATE_CHECK -Status Fail -DayBucket
    exit 2
}
Write-Log "Public build:    $($publicInfo.BuildId)"
if ($publicInfo.TimeUpdated) {
    Write-Log "Public updated:  $($publicInfo.TimeUpdated)"
}

if ($installed -eq $publicInfo.BuildId) {
    Write-Log "Server is up to date." -Level OK
    Send-Heartbeat -Config $Config -Key UPDATE_CHECK -Status Success -DayBucket
    exit 0
}

# Update available
Write-Log "UPDATE AVAILABLE: installed=$installed, public=$($publicInfo.BuildId)" -Level WARN

if ($ApplyUpdate -and -not $NotifyOnly) {
    # Acquire the VM-wide lock for the snapshot+update window. /backup now
    # and /update apply collide otherwise.
    $hmLock = Acquire-HarbormasterLock -Config $Config -Operation 'update' -TimeoutSeconds 60
    try {
        Notify `
            -Title 'Update available - applying' `
            -Message "$($Config.GameName) update detected. Will snapshot then apply." `
            -Severity Warning `
            -Channel Alerts `
            -Fields @{ Installed = $installed; Public = $publicInfo.BuildId }

        if (-not $SkipSnapshot) {
            Write-Log "Taking pre-update snapshot..." -Level INFO
            $snapshotOk = Invoke-PreUpdateSnapshot `
                -InstalledBuild $installed `
                -PublicBuild $publicInfo.BuildId

            if (-not $snapshotOk) {
                Write-Log "Pre-update snapshot FAILED. Aborting update." -Level ERROR
                Notify `
                    -Title 'Update aborted - snapshot failed' `
                    -Message 'Pre-update snapshot failed. Update was not applied to preserve a rollback point. Investigate manually.' `
                    -Severity Critical `
                    -Channel Alerts
                Send-Heartbeat -Config $Config -Key UPDATE_CHECK -Status Fail -DayBucket
                exit 2
            }
        }
        else {
            Write-Log "SkipSnapshot flag set; bypassing snapshot. No rollback point." -Level WARN
            Notify `
                -Title 'Update without snapshot' `
                -Message 'SkipSnapshot flag was set. Update is being applied without a rollback point.' `
                -Severity Warning `
                -Channel Alerts
        }

        try {
            Invoke-Update
            Notify `
                -Title 'Update applied' `
                -Message "$($Config.GameName) updated successfully and service is running." `
                -Severity Success `
                -Channel Status `
                -Fields @{ From = $installed; To = $publicInfo.BuildId }
            Write-Log "Update applied successfully." -Level OK
            Send-Heartbeat -Config $Config -Key UPDATE_CHECK -Status Success -DayBucket
            exit 0
        }
        catch {
            Write-Log "Update failed: $_" -Level ERROR
            Notify `
                -Title 'Update FAILED' `
                -Message "SteamCMD update failed: $_`n`nA pre-update snapshot was taken; you can roll back if needed." `
                -Severity Critical `
                -Channel Alerts `
                -Fields @{ Installed = $installed; Target = $publicInfo.BuildId }
            Send-Heartbeat -Config $Config -Key UPDATE_CHECK -Status Fail -DayBucket
            exit 2
        }
    }
    finally {
        Release-HarbormasterLock $hmLock
    }
}
else {
    # Check-only mode: notify that an update is available but don't apply it
    Notify `
        -Title 'Update available' `
        -Message "A $($Config.GameName) update is available. Run with -ApplyUpdate to install." `
        -Severity Warning `
        -Channel Alerts `
        -Fields @{ Installed = $installed; Public = $publicInfo.BuildId }
    Write-Log "Run with -ApplyUpdate to install. Exiting with code 1." -Level INFO
    Send-Heartbeat -Config $Config -Key UPDATE_CHECK -Status Success -DayBucket
    exit 1
}
