<#
.SYNOPSIS
    Daily backup of a Harbormaster-managed game server: stops the service,
    zips the saved data, uploads to Azure blob storage, prunes old backups.

.DESCRIPTION
    Game-agnostic. All paths, names, retention values and env-var prefixes
    come from the -Config hashtable, normally produced by a per-game
    config.ps1 (see games/<slug>/config.ps1).

.PARAMETER Config
    Hashtable with at least:
      GameName, EnvVarPrefix
      ServiceName, SavedDataPath
      LocalBackupRoot, StorageAccount, BlobContainer
      LocalRetention, BlobRetention
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [hashtable]$Config
)

$ErrorActionPreference = "Stop"

# ============================================================================
# Imports
# ============================================================================
$moduleRoot = Join-Path $PSScriptRoot '..\modules'
Import-Module (Join-Path $moduleRoot 'HarbormasterHealthchecks.psm1') -Force
Import-Module (Join-Path $moduleRoot 'HarbormasterNotify.psm1') -Force

# ============================================================================
# Setup
# ============================================================================
$slug         = $Config.GameName.ToLower()
$timestamp    = Get-Date -Format "yyyy-MM-dd_HHmm"
$archiveName  = "${slug}_$timestamp.zip"
$archive      = Join-Path $Config.LocalBackupRoot $archiveName

New-Item -ItemType Directory -Path $Config.LocalBackupRoot -Force | Out-Null

# Heartbeat: starting
Send-Heartbeat -Config $Config -Key BACKUP -Status Start

# ============================================================================
# Main backup flow
# ============================================================================
try {
    # --- Stop the service for a clean snapshot ---
    Write-Host "Stopping $($Config.ServiceName) service..."
    Stop-Service $Config.ServiceName -Force
    Start-Sleep -Seconds 5

    try {
        # --- Create local zip ---
        Write-Host "Creating local backup: $archive"
        Compress-Archive `
            -Path $Config.SavedDataPath `
            -DestinationPath $archive `
            -CompressionLevel Optimal

        $sizeMB = [math]::Round((Get-Item $archive).Length / 1MB, 2)
        Write-Host "Local backup complete: $sizeMB MB"
    }
    finally {
        # --- Restart the service ---
        # Runs whether the zip succeeded or failed, so the server comes back
        # up either way.
        Write-Host "Restarting $($Config.ServiceName) service..."
        try {
            Start-Service $Config.ServiceName -ErrorAction Stop
            Start-Sleep -Seconds 10
            $svc = Get-Service $Config.ServiceName
            if ($svc.Status -ne "Running") {
                throw "Service status is $($svc.Status) after start attempt"
            }
            Write-Host "Service restarted successfully"
        }
        catch {
            $errMsg = "CRITICAL: Failed to restart $($Config.ServiceName) after backup: $_"
            Write-Error $errMsg
            Send-HarbormasterNotification `
                -Config $Config `
                -Title 'Service failed to restart' `
                -Message $errMsg `
                -Severity Critical `
                -Channel Alerts
            # Don't rethrow — we still want to upload the local backup we
            # just made, since the local zip is the more important artifact.
        }
    }

    # --- Upload to blob storage ---
    Write-Host "Authenticating to Azure with managed identity..."
    Connect-AzAccount -Identity | Out-Null
    $ctx = New-AzStorageContext `
        -StorageAccountName $Config.StorageAccount `
        -UseConnectedAccount

    Write-Host "Uploading $archiveName to blob storage..."
    Set-AzStorageBlobContent `
        -File $archive `
        -Container $Config.BlobContainer `
        -Blob $archiveName `
        -Context $ctx `
        -StandardBlobTier Cool `
        -Force | Out-Null
    Write-Host "Upload complete."

    # --- Prune old local backups ---
    Write-Host "Pruning local backups older than $($Config.LocalRetention) days..."
    Get-ChildItem $Config.LocalBackupRoot -Filter "${slug}_*.zip" |
        Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-$Config.LocalRetention) } |
        Remove-Item -Force

    # --- Prune old blob backups ---
    Write-Host "Pruning blob backups older than $($Config.BlobRetention) days..."
    Get-AzStorageBlob -Container $Config.BlobContainer -Context $ctx |
        Where-Object {
            $_.Name -like "${slug}_*.zip" -and
            $_.LastModified.LocalDateTime -lt (Get-Date).AddDays(-$Config.BlobRetention)
        } |
        Remove-AzStorageBlob -Force

    Write-Host "Done."

    # --- Heartbeat: success ---
    Send-Heartbeat -Config $Config -Key BACKUP -Status Success
}
catch {
    Write-Error "Backup failed: $_"
    Send-Heartbeat -Config $Config -Key BACKUP -Status Fail
    Send-HarbormasterNotification `
        -Config $Config `
        -Title 'Backup FAILED' `
        -Message "Backup script encountered an error: $_" `
        -Severity Critical `
        -Channel Alerts
    throw
}
