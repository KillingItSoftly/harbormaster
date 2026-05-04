<#
.SYNOPSIS
    Posts a "server is online" announcement to Discord.

.DESCRIPTION
    Game-agnostic. Designed to run at boot (e.g. via a scheduled task with
    "At system startup" trigger and a 60-90 second delay). Waits for the
    NSSM-managed service to reach Running, then posts a Discord embed to the
    Status channel.

    If the service does not come up in time, posts a Critical alert to the
    Alerts channel and exits non-zero.

    Two safety guards prevent spurious announcements when this script gets
    triggered outside of a real boot (e.g. recurring scheduled task,
    service restart, manual run during shutdown grace window):

    1. Boot-recency check: skips announce if the VM has been up longer
       than -MaxBootAgeMinutes (default 15) — a real boot triggers the
       startup task within seconds of LastBootUpTime, so anything older
       isn't a fresh boot.
    2. Shutdown sentinel: Announce-ServerShutdown.ps1 writes a sentinel
       file before stopping the service. If that file exists and is
       newer than LastBootUpTime, an admin-initiated shutdown is in
       progress (or just completed) and we suppress the online message.

.PARAMETER Config
    Per-game config hashtable.

.PARAMETER WaitSeconds
    How long to wait for the service to become Running. Default 180s.

.PARAMETER PollSeconds
    How often to poll the service status. Default 5s.

.PARAMETER MaxBootAgeMinutes
    Skip announcement if the VM has been up longer than this many minutes.
    Default 15. Set to 0 to disable the boot-recency guard.

.PARAMETER Force
    Bypass both safety guards and announce regardless of boot age or
    sentinel. Use only for manual testing.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [hashtable]$Config,

    [int]$WaitSeconds = 180,
    [int]$PollSeconds = 5,
    [int]$MaxBootAgeMinutes = 15,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'

$moduleRoot = Join-Path $PSScriptRoot '..\modules'
Import-Module (Join-Path $moduleRoot 'HarbormasterNotify.psm1') -Force

# --- Safety guards -----------------------------------------------------------

$bootTime  = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime
$bootAgeMin = ((Get-Date) - $bootTime).TotalMinutes

# Sentinel file location is shared across both announce scripts.
$stateDir     = Join-Path $env:ProgramData 'Harbormaster'
$sentinelPath = Join-Path $stateDir ("shutdown-{0}.flag" -f $Config.GameName)

if (-not $Force) {
    if ($MaxBootAgeMinutes -gt 0 -and $bootAgeMin -gt $MaxBootAgeMinutes) {
        Write-Host ("Skipping online announcement: VM has been up for {0:N1} min (> {1} min). " +
                    "Not a fresh boot.") -f $bootAgeMin, $MaxBootAgeMinutes
        return
    }

    if (Test-Path $sentinelPath) {
        $sentinelTime = (Get-Item $sentinelPath).LastWriteTime
        if ($sentinelTime -gt $bootTime) {
            Write-Host ("Skipping online announcement: shutdown sentinel at '$sentinelPath' " +
                        "is newer than LastBootUpTime. An admin-initiated shutdown is in progress.")
            return
        }
        # Sentinel is from a previous boot cycle — stale, remove it.
        Remove-Item $sentinelPath -Force -ErrorAction SilentlyContinue
    }
}

# --- Wait for service --------------------------------------------------------

$service = $Config.ServiceName
$elapsed = 0
$status  = 'Unknown'

while ($elapsed -lt $WaitSeconds) {
    $svc = Get-Service $service -ErrorAction SilentlyContinue
    if ($svc) {
        $status = $svc.Status
        if ($status -eq 'Running') { break }
    }
    Start-Sleep -Seconds $PollSeconds
    $elapsed += $PollSeconds
}

if ($status -ne 'Running') {
    Send-HarbormasterNotification `
        -Config $Config `
        -Title 'Server failed to start' `
        -Message "Service '$service' did not reach Running within $WaitSeconds seconds. Last status: $status." `
        -Severity Critical `
        -Channel Alerts `
        -Fields @{ Service = $service; Status = $status; 'Waited' = "$elapsed s" }
    exit 1
}

# Compose human-friendly time
$uptimeMin = [math]::Round($bootAgeMin, 1)

Send-HarbormasterNotification `
    -Config $Config `
    -Title "$($Config.GameName) is online" `
    -Message "Server is up and accepting connections." `
    -Severity Success `
    -Channel Status `
    -Fields @{
        Service       = $service
        'VM uptime'   = "$uptimeMin min"
        'Ready after' = "$elapsed s"
    }
