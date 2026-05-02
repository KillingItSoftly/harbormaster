<#
.SYNOPSIS
    Periodic health check for the Windrose server. Sends Discord alerts
    only when something is wrong or notable.
#>

[CmdletBinding()]
param(
    [int]$DiskWarnGB = 20,
    [int]$DiskCriticalGB = 5,
    [int]$BackupFailureWindowHours = 26,
    [int]$ServiceDownAlertMinutes = 10,
    [string]$StateFile = 'C:\Logs\windrose-health-state.json'
)

$ErrorActionPreference = 'Continue'

Import-Module C:\Scripts\HarbormasterNotify.psm1 -Force

Import-Module C:\Scripts\HarbormasterHealthchecks.psm1 -Force

$hcVar = Get-DayBucketEnvVar -BaseName 'HARBORMASTER_HC_HEALTH'

Send-Heartbeat -EnvVarName $hcVar -Status Start

# Load previous state to avoid spamming on persistent issues
$state = if (Test-Path $StateFile) {
    Get-Content $StateFile -Raw | ConvertFrom-Json -AsHashtable
} else {
    @{}
}

$now = Get-Date
function Should-Alert {
    param([string]$Key, [int]$CooldownMinutes = 60)
    if (-not $state.ContainsKey($Key)) { return $true }
    $lastAlert = [datetime]$state[$Key]
    return ($now - $lastAlert).TotalMinutes -gt $CooldownMinutes
}
function Mark-Alerted { param([string]$Key); $state[$Key] = $now.ToString('o') }
function Clear-Alert { param([string]$Key); $state.Remove($Key) | Out-Null }

# --- Check 1: Service running ---
$svc = Get-Service WindroseServer -ErrorAction SilentlyContinue
if (-not $svc) {
    if (Should-Alert 'service-missing' 1440) {
        Send-WindroseNotification `
            -Title 'Service not installed' `
            -Message 'WindroseServer service was not found. Has NSSM been removed?' `
            -Severity Critical `
            -Channel Alerts
        Mark-Alerted 'service-missing'
    }
}
elseif ($svc.Status -ne 'Running') {
    # Check how long it's been down
    $stopTime = (Get-EventLog -LogName Application -Source nssm -Newest 50 -ErrorAction SilentlyContinue |
        Where-Object { $_.Message -like "*WindroseServer*" -and $_.Message -like "*stop*" } |
        Select-Object -First 1).TimeGenerated

    $downMinutes = if ($stopTime) {
        [int]($now - $stopTime).TotalMinutes
    } else {
        $ServiceDownAlertMinutes + 1   # Assume it's been down long enough
    }

    if ($downMinutes -ge $ServiceDownAlertMinutes -and (Should-Alert 'service-down' 30)) {
        Send-WindroseNotification `
            -Title 'Server is down' `
            -Message "Service has been in '$($svc.Status)' state for ~$downMinutes minutes." `
            -Severity Critical `
            -Channel Alerts `
            -Fields @{ Status = $svc.Status; 'Down for' = "$downMinutes min" }
        Mark-Alerted 'service-down'
    }
}
else {
    # Service is running; clear any prior down alert
    if ($state.ContainsKey('service-down')) {
        Send-WindroseNotification `
            -Title 'Server recovered' `
            -Message 'Service is running again.' `
            -Severity Success `
            -Channel Alerts
        Clear-Alert 'service-down'
    }
}

# --- Check 2: Recent crashes ---
$logPath = 'C:\GameServers\Windrose\logs\server-stdout.log'
if (Test-Path $logPath) {
    $recentCrashes = Get-Content $logPath -Tail 5000 |
        Select-String -Pattern 'Crash Stack Trace' |
        Where-Object {
            if ($_.Line -match '\[(\d{4})\.(\d{2})\.(\d{2})-(\d{2})\.(\d{2})\.(\d{2}):\d+\]') {
                $crashTime = [datetime]"$($Matches[1])-$($Matches[2])-$($Matches[3]) $($Matches[4]):$($Matches[5]):$($Matches[6])"
                ($now - $crashTime).TotalHours -lt 1
            } else { $false }
        }

    if ($recentCrashes.Count -ge 3 -and (Should-Alert 'crash-loop' 60)) {
        Send-WindroseNotification `
            -Title 'Multiple crashes detected' `
            -Message "$($recentCrashes.Count) crash trace(s) in the last hour. Check the logs." `
            -Severity Critical `
            -Channel Alerts `
            -Fields @{ 'Crashes (1h)' = $recentCrashes.Count }
        Mark-Alerted 'crash-loop'
    }
}

# --- Check 3: Backup ran successfully ---
$backupTask = Get-ScheduledTaskInfo -TaskName 'WindroseBackup' -ErrorAction SilentlyContinue
if ($backupTask) {
    $hoursSinceLastRun = ($now - $backupTask.LastRunTime).TotalHours
    if ($hoursSinceLastRun -gt $BackupFailureWindowHours) {
        if (Should-Alert 'backup-stale' 720) {
            Send-WindroseNotification `
                -Title 'Backup may be stale' `
                -Message "Last backup ran $([math]::Round($hoursSinceLastRun, 1)) hours ago." `
                -Severity Warning `
                -Channel Alerts `
                -Fields @{ 'Last run' = $backupTask.LastRunTime; 'Last result' = $backupTask.LastTaskResult }
            Mark-Alerted 'backup-stale'
        }
    }
    elseif ($backupTask.LastTaskResult -ne 0) {
        if (Should-Alert 'backup-failed' 360) {
            Send-WindroseNotification `
                -Title 'Backup failed' `
                -Message "Last backup completed with non-zero exit code." `
                -Severity Critical `
                -Channel Alerts `
                -Fields @{ 'Last run' = $backupTask.LastRunTime; 'Exit code' = $backupTask.LastTaskResult }
            Mark-Alerted 'backup-failed'
        }
    }
    else {
        Clear-Alert 'backup-stale'
        Clear-Alert 'backup-failed'
    }
}

# --- Check 4: Disk space ---
$cDrive = Get-PSDrive C
$freeGB = [math]::Round($cDrive.Free / 1GB, 1)

if ($freeGB -lt $DiskCriticalGB -and (Should-Alert 'disk-critical' 360)) {
    Send-WindroseNotification `
        -Title 'Disk space critical' `
        -Message "Only $freeGB GB free on C:. Server may fail soon." `
        -Severity Critical `
        -Channel Alerts `
        -Fields @{ 'Free' = "$freeGB GB"; 'Threshold' = "$DiskCriticalGB GB" }
    Mark-Alerted 'disk-critical'
}
elseif ($freeGB -lt $DiskWarnGB -and (Should-Alert 'disk-warn' 1440)) {
    Send-WindroseNotification `
        -Title 'Disk space low' `
        -Message "$freeGB GB free on C:. Consider cleaning up old backups or logs." `
        -Severity Warning `
        -Channel Alerts `
        -Fields @{ 'Free' = "$freeGB GB"; 'Threshold' = "$DiskWarnGB GB" }
    Mark-Alerted 'disk-warn'
}
elseif ($freeGB -ge $DiskWarnGB) {
    Clear-Alert 'disk-warn'
    Clear-Alert 'disk-critical'
}

Send-Heartbeat -EnvVarName $hcVar -Status Success

# --- Save state ---
$state | ConvertTo-Json | Set-Content $StateFile -Encoding UTF8