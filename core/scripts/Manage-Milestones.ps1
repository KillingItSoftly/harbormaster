<#
.SYNOPSIS
    Manage milestone snapshots and pruning for a Harbormaster-managed game
    server.

.DESCRIPTION
    Three modes:
      Snapshot - creates a labeled milestone backup (local + blob).
      Prune    - removes old milestones based on category retention rules.
      List     - shows current milestones in blob storage.

    Game-agnostic. All paths, names and storage targets come from the
    -Config hashtable.

.PARAMETER Config
    Hashtable with at least:
      GameName, ServiceName, SavedDataPath,
      LocalBackupRoot, StorageAccount, BlobContainer

.EXAMPLE
    .\Manage-Milestones.ps1 -Config $cfg -Action Snapshot `
        -Label 'before-mod-reinstall' -Category pre-change

.EXAMPLE
    .\Manage-Milestones.ps1 -Config $cfg -Action Prune -DryRun
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [hashtable]$Config,

    [ValidateSet('Snapshot', 'Prune', 'List')]
    [string]$Action = 'Snapshot',

    [string]$Label,

    [ValidateSet('pristine', 'pre-change', 'stable', 'general')]
    [string]$Category = 'general',

    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

# Retention by category in days. Use $null for "keep forever".
$retention = @{
    'pristine'   = $null
    'pre-change' = 90
    'stable'     = 180
    'general'    = 60
}

function Connect-Storage {
    Write-Host "Authenticating to Azure with managed identity..." -ForegroundColor Cyan
    Connect-AzAccount -Identity | Out-Null
    return New-AzStorageContext -StorageAccountName $Config.StorageAccount -UseConnectedAccount
}

function Get-MilestoneCategory {
    param([string]$BlobName)
    if ($BlobName -match 'milestone_([^_]+)_') {
        return $Matches[1]
    }
    return 'general'
}

function Stop-ServiceIfRunning {
    $svc = Get-Service $Config.ServiceName -ErrorAction SilentlyContinue
    if ($svc -and $svc.Status -eq 'Running') {
        Write-Host "Stopping $($Config.ServiceName) for clean snapshot..." -ForegroundColor Yellow
        Stop-Service $Config.ServiceName -Force
        Start-Sleep -Seconds 5
        return $true
    }
    return $false
}

function Start-ServiceIfWasRunning {
    param([bool]$WasRunning)
    if ($WasRunning) {
        Write-Host "Restarting $($Config.ServiceName)..." -ForegroundColor Yellow
        try {
            Start-Service $Config.ServiceName -ErrorAction Stop
            Start-Sleep -Seconds 10
            $svc = Get-Service $Config.ServiceName
            if ($svc.Status -ne 'Running') {
                Write-Warning "Service status is $($svc.Status) after start attempt"
            } else {
                Write-Host "Service restarted successfully." -ForegroundColor Green
            }
        }
        catch {
            Write-Error "CRITICAL: Failed to restart $($Config.ServiceName): $_"
        }
    }
}

function Invoke-Snapshot {
    if (-not $Label) {
        throw "The -Label parameter is required for Snapshot action."
    }

    $sourcePath = $Config.SavedDataPath
    if (-not (Test-Path $sourcePath)) {
        throw "Source path not found: $sourcePath. Check SavedDataPath in config."
    }

    $safeLabel   = $Label -replace '[^a-zA-Z0-9_-]', '_'
    $timestamp   = Get-Date -Format 'yyyy-MM-dd_HHmm'
    $archiveName = "milestone_${Category}_${safeLabel}_${timestamp}.zip"

    New-Item -ItemType Directory -Path $Config.LocalBackupRoot -Force | Out-Null
    $localArchive = Join-Path $Config.LocalBackupRoot $archiveName

    Write-Host ""
    Write-Host "=== Creating Milestone ===" -ForegroundColor Cyan
    Write-Host "  Category: $Category"
    Write-Host "  Label:    $safeLabel"
    Write-Host "  Archive:  $archiveName"
    Write-Host ""

    $wasRunning = Stop-ServiceIfRunning

    try {
        Write-Host "Compressing $sourcePath..." -ForegroundColor Cyan
        Compress-Archive -Path $sourcePath -DestinationPath $localArchive -CompressionLevel Optimal

        $sizeMB = [math]::Round((Get-Item $localArchive).Length / 1MB, 2)
        Write-Host "Local archive created: $sizeMB MB" -ForegroundColor Green
    }
    finally {
        Start-ServiceIfWasRunning -WasRunning $wasRunning
    }

    Write-Host "Uploading to blob storage..." -ForegroundColor Cyan
    $ctx = Connect-Storage

    Set-AzStorageBlobContent `
        -File $localArchive `
        -Container $Config.BlobContainer `
        -Blob $archiveName `
        -Context $ctx `
        -StandardBlobTier Cool `
        -Force | Out-Null

    Write-Host "Milestone uploaded: $archiveName" -ForegroundColor Green
    Write-Host ""
}

function Invoke-Prune {
    Write-Host ""
    Write-Host "=== Pruning Milestones ===" -ForegroundColor Cyan
    if ($DryRun) {
        Write-Host "DRY RUN - no deletions will occur" -ForegroundColor Yellow
    }
    Write-Host ""
    Write-Host "Retention rules:"
    foreach ($cat in $retention.Keys | Sort-Object) {
        $days = $retention[$cat]
        if ($null -eq $days) {
            Write-Host "  $cat -> kept forever"
        } else {
            Write-Host "  $cat -> $days days"
        }
    }
    Write-Host ""

    $ctx   = Connect-Storage
    $blobs = Get-AzStorageBlob -Container $Config.BlobContainer -Context $ctx
    $now   = Get-Date

    $toDelete = @()
    $toKeep   = @()

    foreach ($blob in $blobs) {
        if ($blob.Name -notlike "milestone_*.zip") {
            continue
        }

        $category      = Get-MilestoneCategory -BlobName $blob.Name
        $retentionDays = $retention[$category]
        $age           = ($now - $blob.LastModified.LocalDateTime).TotalDays

        if ($null -eq $retentionDays) {
            $toKeep += [PSCustomObject]@{
                Name = $blob.Name; Category = $category
                AgeDays = [math]::Round($age, 1); Reason = 'kept forever'
            }
        }
        elseif ($age -gt $retentionDays) {
            $toDelete += [PSCustomObject]@{
                Name = $blob.Name; Category = $category
                AgeDays = [math]::Round($age, 1); Reason = "older than $retentionDays days"
            }
        }
        else {
            $toKeep += [PSCustomObject]@{
                Name = $blob.Name; Category = $category
                AgeDays = [math]::Round($age, 1); Reason = "within $retentionDays-day window"
            }
        }
    }

    if ($toKeep.Count -gt 0) {
        Write-Host "Keeping $($toKeep.Count) milestone(s):" -ForegroundColor Green
        $toKeep | Format-Table -AutoSize Name, Category, AgeDays, Reason
    }

    if ($toDelete.Count -eq 0) {
        Write-Host "No milestones eligible for pruning." -ForegroundColor Green
        return
    }

    Write-Host "Deleting $($toDelete.Count) milestone(s):" -ForegroundColor Yellow
    $toDelete | Format-Table -AutoSize Name, Category, AgeDays, Reason

    if ($DryRun) {
        Write-Host "DRY RUN complete. Re-run without -DryRun to actually delete." -ForegroundColor Yellow
        return
    }

    foreach ($item in $toDelete) {
        Remove-AzStorageBlob -Container $Config.BlobContainer -Blob $item.Name -Context $ctx -Force
        Write-Host "  Deleted: $($item.Name)" -ForegroundColor DarkGray
    }

    Write-Host "Prune complete." -ForegroundColor Green
}

function Invoke-List {
    Write-Host ""
    Write-Host "=== Current Milestones in Blob Storage ===" -ForegroundColor Cyan
    Write-Host ""

    $ctx   = Connect-Storage
    $blobs = Get-AzStorageBlob -Container $Config.BlobContainer -Context $ctx
    $now   = Get-Date

    $milestones = $blobs |
        Where-Object { $_.Name -like "milestone_*.zip" } |
        ForEach-Object {
            [PSCustomObject]@{
                Name      = $_.Name
                Category  = Get-MilestoneCategory -BlobName $_.Name
                SizeMB    = [math]::Round($_.Length / 1MB, 2)
                AgeDays   = [math]::Round(($now - $_.LastModified.LocalDateTime).TotalDays, 1)
                Modified  = $_.LastModified.LocalDateTime.ToString('yyyy-MM-dd HH:mm')
            }
        } |
        Sort-Object Modified -Descending

    if ($milestones.Count -eq 0) {
        Write-Host "No milestones found." -ForegroundColor Yellow
        return
    }

    $milestones | Format-Table -AutoSize

    $totalSize = ($milestones | Measure-Object -Property SizeMB -Sum).Sum
    Write-Host "Total: $($milestones.Count) milestones, $([math]::Round($totalSize, 2)) MB" -ForegroundColor Cyan
    Write-Host ""
}

switch ($Action) {
    'Snapshot' { Invoke-Snapshot }
    'Prune'    { Invoke-Prune }
    'List'     { Invoke-List }
}
