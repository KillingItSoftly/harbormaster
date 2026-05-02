$ErrorActionPreference = "Stop"

# ============================================================================
# Imports
# ============================================================================
Import-Module C:\Scripts\HarbormasterHealthchecks.psm1 -Force
Import-Module C:\Scripts\HarbormasterNotify.psm1 -Force

# ============================================================================
# Configuration
# ============================================================================
# Local
$serverPath     = ""
$backupRoot     = ""
$retentionDays  = 14

# Azure
$storageAccount = "<your_storage_account>"
$container      = "<your_container>"
$blobRetention  = 30

# ============================================================================
# Setup
# ============================================================================
$timestamp   = Get-Date -Format "yyyy-MM-dd_HHmm"
$archiveName = "windrose_$timestamp.zip"
$archive     = Join-Path $backupRoot $archiveName

New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null

# Heartbeat: starting
Send-Heartbeat -EnvVarName 'WINDROSE_HC_BACKUP' -Status Start

# ============================================================================
# Main backup flow
# ============================================================================
try {
    # --- Stop the service for a clean snapshot ---
    Write-Host "Stopping Windrose service..."
    Stop-Service WindroseServer -Force
    Start-Sleep -Seconds 5

    $serviceRestarted = $false
    try {
        # --- Create local zip ---
        Write-Host "Creating local backup: $archive"
        Compress-Archive `
            -Path "$serverPath\R5\Saved" `
            -DestinationPath $archive `
            -CompressionLevel Optimal

        $sizeMB = [math]::Round((Get-Item $archive).Length / 1MB, 2)
        Write-Host "Local backup complete: $sizeMB MB"
    }
    finally {
        # --- Restart the service ---
        # This runs whether the zip succeeded or failed, so the server
        # comes back up either way.
        Write-Host "Restarting Windrose service..."
        try {
            Start-Service WindroseServer -ErrorAction Stop
            Start-Sleep -Seconds 10
            $svc = Get-Service WindroseServer
            if ($svc.Status -ne "Running") {
                throw "Service status is $($svc.Status) after start attempt"
            }
            Write-Host "Service restarted successfully"
            $serviceRestarted = $true
        }
        catch {
            $errMsg = "CRITICAL: Failed to restart Windrose service after backup: $_"
            Write-Error $errMsg
            Send-WindroseNotification `
                -Title 'Service failed to restart' `
                -Message $errMsg `
                -Severity Critical `
                -Channel Alerts
            # Don't rethrow here — we still want to upload the local backup
            # we just made, since the local zip is the more important artifact.
        }
    }

    # --- Upload to blob storage ---
    Write-Host "Authenticating to Azure with managed identity..."
    Connect-AzAccount -Identity | Out-Null
    $ctx = New-AzStorageContext `
        -StorageAccountName $storageAccount `
        -UseConnectedAccount

    Write-Host "Uploading $archiveName to blob storage..."
    Set-AzStorageBlobContent `
        -File $archive `
        -Container $container `
        -Blob $archiveName `
        -Context $ctx `
        -StandardBlobTier Cool `
        -Force | Out-Null
    Write-Host "Upload complete."

    # --- Prune old local backups ---
    Write-Host "Pruning local backups older than $retentionDays days..."
    Get-ChildItem $backupRoot -Filter "windrose_*.zip" |
        Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-$retentionDays) } |
        Remove-Item -Force

    # --- Prune old blob backups ---
    Write-Host "Pruning blob backups older than $blobRetention days..."
    Get-AzStorageBlob -Container $container -Context $ctx |
        Where-Object {
            $_.Name -like "windrose_*.zip" -and
            $_.LastModified.LocalDateTime -lt (Get-Date).AddDays(-$blobRetention)
        } |
        Remove-AzStorageBlob -Force

    Write-Host "Done."

    # --- Heartbeat: success ---
    # Service restart failures are surfaced via Discord above but don't
    # invalidate the backup itself, so we still ping success here.
    Send-Heartbeat -EnvVarName 'WINDROSE_HC_BACKUP' -Status Success
}
catch {
    Write-Error "Backup failed: $_"
    Send-Heartbeat -EnvVarName 'WINDROSE_HC_BACKUP' -Status Fail
    Send-WindroseNotification `
        -Title 'Backup FAILED' `
        -Message "Backup script encountered an error: $_" `
        -Severity Critical `
        -Channel Alerts
    throw
}