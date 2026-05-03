<#
.SYNOPSIS
    Example scheduled task registration for Harbormaster on a single-game VM.

.DESCRIPTION
    Run this script once on the VM (as Administrator) to register all the
    scheduled tasks Harbormaster relies on. Edit paths and times to match
    your setup before running.

    Each task runs as SYSTEM with RunLevel Highest. Tasks reference the
    per-game wrapper scripts under games/<gamename>/.

    Re-running this script will fail with "task already exists" — to update
    a task, either Unregister-ScheduledTask first or use Set-ScheduledTask.
#>

# ============================================================================
# Edit these to match your setup
# ============================================================================
$gameName = 'Windrose'
$gameDir  = 'C:\Scripts\harbormaster\games\windrose'

# Times for VM uptime — must match your auto-start/auto-shutdown schedule
$vmWeekdayStartHour = 14   # 2 PM Mon-Thu
$vmWeekendStartHour = 9    # 9 AM Fri-Sun
$updateCheckOffsetMinutes = 5   # how long after VM starts before checking
$dailyBackupTime = '12:30AM'
$shutdownWarningTime = '12:50AM'

# Common settings reused across tasks
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -RunLevel Highest
$baseSettings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1)

function Register-HarbormasterTask {
    param(
        [string]$TaskName,
        [string]$ScriptPath,
        [scriptblock]$Trigger,
        [string]$Description,
        [int]$ExecutionMinutes = 60
    )

    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Write-Warning "Task '$TaskName' already exists. Unregister it first to recreate."
        return
    }

    $action = New-ScheduledTaskAction `
        -Execute 'powershell.exe' `
        -Argument "-ExecutionPolicy Bypass -NoProfile -File `"$ScriptPath`""

    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -ExecutionTimeLimit (New-TimeSpan -Minutes $ExecutionMinutes)

    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $action `
        -Trigger (& $Trigger) `
        -Principal $principal `
        -Settings $settings `
        -Description $Description | Out-Null

    Write-Host "Registered: $TaskName" -ForegroundColor Green
}

# ============================================================================
# 1. Daily backup at 12:30 AM
# ============================================================================
Register-HarbormasterTask `
    -TaskName "${gameName}Backup" `
    -ScriptPath "$gameDir\Backup-$gameName.ps1" `
    -Trigger { New-ScheduledTaskTrigger -Daily -At $dailyBackupTime } `
    -Description "Daily backup of $gameName saves to local + blob storage" `
    -ExecutionMinutes 60

# ============================================================================
# 2. Update check (split across weekday/weekend)
# ============================================================================
$updateCheckTriggers = {
    $weekdayTime = "$($vmWeekdayStartHour):$('{0:D2}' -f $updateCheckOffsetMinutes)"
    $weekendTime = "$($vmWeekendStartHour):$('{0:D2}' -f $updateCheckOffsetMinutes)"

    @(
        New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday -At $weekdayTime
        New-ScheduledTaskTrigger -Weekly -DaysOfWeek Friday,Saturday,Sunday -At $weekendTime
    )
}

Register-HarbormasterTask `
    -TaskName "${gameName}UpdateCheck" `
    -ScriptPath "$gameDir\Check-${gameName}Update.ps1" `
    -Trigger $updateCheckTriggers `
    -Description "Daily check for $gameName updates from Steam" `
    -ExecutionMinutes 30

# ============================================================================
# 3. Health check every 15 minutes
# ============================================================================
Register-HarbormasterTask `
    -TaskName "${gameName}HealthCheck" `
    -ScriptPath "$gameDir\Check-${gameName}Health.ps1" `
    -Trigger {
        $t = New-ScheduledTaskTrigger -Once -At (Get-Date) `
            -RepetitionInterval (New-TimeSpan -Minutes 15) `
            -RepetitionDuration (New-TimeSpan -Days 3650)
        $t
    } `
    -Description "Periodic health checks for $gameName service, disk, crashes" `
    -ExecutionMinutes 5

# ============================================================================
# 4. Server-online announcement at boot
# ============================================================================
Register-HarbormasterTask `
    -TaskName "${gameName}AnnounceStart" `
    -ScriptPath "$gameDir\Announce-${gameName}Start.ps1" `
    -Trigger {
        $t = New-ScheduledTaskTrigger -AtStartup
        $t.Delay = 'PT60S'   # 60 second delay so service can come up first
        $t
    } `
    -Description "Posts to Discord when $gameName server is online after VM boot" `
    -ExecutionMinutes 5

# ============================================================================
# 5. Pre-shutdown warning at 12:50 AM
# ============================================================================
Register-HarbormasterTask `
    -TaskName "${gameName}ShutdownWarning" `
    -ScriptPath "$gameDir\Announce-${gameName}Shutdown.ps1" `
    -Trigger { New-ScheduledTaskTrigger -Daily -At $shutdownWarningTime } `
    -Description "Posts to Discord 10 minutes before VM auto-shutdown" `
    -ExecutionMinutes 5

# ============================================================================
# Verify all tasks registered
# ============================================================================
Write-Host ""
Write-Host "Registered Harbormaster tasks:" -ForegroundColor Cyan
Get-ScheduledTask -TaskName "${gameName}*" |
    Select-Object TaskName, State, @{N='LastRun'; E={(Get-ScheduledTaskInfo $_.TaskName).LastRunTime}} |
    Format-Table -AutoSize

Write-Host "Done." -ForegroundColor Green
Write-Host ""
Write-Host "To trigger any task manually for testing:" -ForegroundColor Yellow
Write-Host "  Start-ScheduledTask -TaskName '${gameName}Backup'" -ForegroundColor DarkGray