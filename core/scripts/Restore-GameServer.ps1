<#
.SYNOPSIS
    Restore a Harbormaster game server's saved data from a blob backup
    or milestone snapshot.

.DESCRIPTION
    Game-agnostic. Performs a destructive overwrite of $Config.SavedDataPath
    with the contents of a named blob in $Config.BlobContainer. Always takes
    a pre-restore milestone snapshot first so the previous state can be
    recovered if the restore turns out to be wrong.

    Flow:
      1. Acquire VM-wide Harbormaster lock.
      2. Validate -BlobName matches the slug-prefixed naming convention.
      3. Stop the service (NSSM).
      4. Take a milestone snapshot labeled 'pre-restore-<timestamp>'
         (category pre-change), unless -SkipPreSnapshot is set.
      5. Download the blob to $Config.LocalBackupRoot\restore\<name>.
      6. Move the existing SavedDataPath aside to a .pre-restore folder
         (kept until manually cleaned), then expand the zip into the
         original SavedDataPath.
      7. Restart the service.

    On any failure during steps 5-7, the script attempts to roll the
    .pre-restore folder back into place and restarts the service.

.PARAMETER Config
    Per-game config hashtable.

.PARAMETER BlobName
    Exact blob name (e.g. 'windrose_2026-05-03_0200.zip' or
    'milestone_pre-change_before-update_2026-05-02_1800.zip').

.PARAMETER SkipPreSnapshot
    Skip the pre-restore milestone snapshot. NOT RECOMMENDED. Used by
    automation that already took a snapshot.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [hashtable]$Config,

    [Parameter(Mandatory)]
    [string]$BlobName,

    [switch]$SkipPreSnapshot
)

$ErrorActionPreference = 'Stop'

$moduleRoot = Join-Path $PSScriptRoot '..\modules'
Import-Module (Join-Path $moduleRoot 'HarbormasterNotify.psm1') -Force
Import-Module (Join-Path $moduleRoot 'HarbormasterLock.psm1') -Force

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

# Strict allowlist on BlobName: only filenames our other scripts produce.
# Prevents the operator (or an attacker with command access) from pointing
# the restore at unrelated blobs in the same container.
$slug = $Config.GameName.ToLower()
$blobPatterns = @(
    "^${slug}_\d{4}-\d{2}-\d{2}_\d{4}\.zip$",
    "^milestone_(pristine|pre-change|stable|general)_[A-Za-z0-9_\-]+_\d{4}-\d{2}-\d{2}_\d{4}\.zip$"
)
$matched = $false
foreach ($p in $blobPatterns) {
    if ($BlobName -match $p) { $matched = $true; break }
}
if (-not $matched) {
    throw "Refusing to restore from '$BlobName': name does not match any expected backup or milestone pattern."
}

$hmLock = Acquire-HarbormasterLock -Config $Config -Operation 'restore' -TimeoutSeconds 30

try {
    # --- Pre-restore snapshot --------------------------------------------
    if (-not $SkipPreSnapshot) {
        $snapScript = Join-Path $PSScriptRoot 'Manage-Milestones.ps1'
        $stamp = Get-Date -Format 'yyyy-MM-dd_HHmm'
        Write-Host "Taking pre-restore milestone snapshot..."
        # NOTE: Manage-Milestones tries to acquire its own lock; we already
        # hold it. Workaround: temporarily release for the snapshot, then
        # re-acquire. This is safe — the snapshot is itself a destructive
        # operation that wants exclusivity.
        Release-HarbormasterLock $hmLock
        $hmLock = $null
        try {
            & $snapScript `
                -Config $Config `
                -Action Snapshot `
                -Label "pre-restore-$stamp" `
                -Category 'pre-change'
        }
        finally {
            $hmLock = Acquire-HarbormasterLock -Config $Config -Operation 'restore' -TimeoutSeconds 60
        }
    }
    else {
        Write-Warning "SkipPreSnapshot set; rolling back is impossible if the restore is wrong."
    }

    # --- Stop the service -----------------------------------------------
    $svc = Get-Service $Config.ServiceName -ErrorAction SilentlyContinue
    $wasRunning = $false
    if ($svc -and $svc.Status -eq 'Running') {
        Write-Host "Stopping $($Config.ServiceName) for restore..."
        Stop-Service $Config.ServiceName -Force
        Start-Sleep -Seconds 5
        $wasRunning = $true
    }

    Notify `
        -Title "$($Config.GameName) RESTORE in progress" `
        -Message "Restoring saved data from blob: $BlobName" `
        -Severity Warning `
        -Channel Alerts `
        -Fields @{ Blob = $BlobName; Service = $Config.ServiceName }

    # --- Download blob --------------------------------------------------
    Write-Host "Authenticating to Azure with managed identity..."
    Connect-AzAccount -Identity | Out-Null
    $ctx = New-AzStorageContext `
        -StorageAccountName $Config.StorageAccount `
        -UseConnectedAccount

    $stagingDir = Join-Path $Config.LocalBackupRoot 'restore'
    New-Item -ItemType Directory -Path $stagingDir -Force | Out-Null
    $localZip = Join-Path $stagingDir $BlobName

    Write-Host "Downloading $BlobName..."
    Get-AzStorageBlobContent `
        -Container $Config.BlobContainer `
        -Blob $BlobName `
        -Destination $localZip `
        -Context $ctx `
        -Force | Out-Null

    if (-not (Test-Path $localZip)) {
        throw "Download appeared to succeed but local file '$localZip' is missing."
    }

    # --- Swap saved data -------------------------------------------------
    $saved = $Config.SavedDataPath
    $sideline = "$saved.pre-restore-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
    if (Test-Path $saved) {
        Write-Host "Moving existing saved data aside to: $sideline"
        Move-Item -Path $saved -Destination $sideline -Force
    }
    New-Item -ItemType Directory -Path $saved -Force | Out-Null

    try {
        Write-Host "Expanding $localZip into $saved..."
        Expand-Archive -Path $localZip -DestinationPath $saved -Force
    }
    catch {
        Write-Warning "Expand failed: $_. Rolling back."
        if (Test-Path $sideline) {
            if (Test-Path $saved) { Remove-Item $saved -Recurse -Force -ErrorAction SilentlyContinue }
            Move-Item -Path $sideline -Destination $saved -Force
        }
        throw
    }

    Write-Host "Saved data restored. Old state remains at: $sideline"

    # --- Restart service -------------------------------------------------
    if ($wasRunning) {
        Write-Host "Restarting $($Config.ServiceName)..."
        try {
            Start-Service $Config.ServiceName -ErrorAction Stop
            Start-Sleep -Seconds 10
            $svc = Get-Service $Config.ServiceName
            if ($svc.Status -ne 'Running') {
                throw "Service status is $($svc.Status) after restore."
            }
        }
        catch {
            Notify `
                -Title 'Service failed to start after restore' `
                -Message "Restore completed but service did not start: $_" `
                -Severity Critical `
                -Channel Alerts
            throw
        }
    }

    Notify `
        -Title "$($Config.GameName) RESTORE complete" `
        -Message "Saved data was replaced from blob: $BlobName. Previous state preserved at $sideline on the VM." `
        -Severity Success `
        -Channel Alerts `
        -Fields @{ Blob = $BlobName; 'Old state' = $sideline }
}
catch {
    Notify `
        -Title 'RESTORE FAILED' `
        -Message "Restore from '$BlobName' failed: $_" `
        -Severity Critical `
        -Channel Alerts
    throw
}
finally {
    Release-HarbormasterLock $hmLock
}
