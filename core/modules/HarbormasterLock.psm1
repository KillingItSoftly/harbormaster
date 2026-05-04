function Acquire-HarbormasterLock {
    <#
    .SYNOPSIS
        Acquire an exclusive file-based lock on the VM.
    .DESCRIPTION
        Used by Backup-GameServer.ps1, Manage-Milestones.ps1, and
        Check-SteamUpdate.ps1 to prevent two destructive scripts from
        running simultaneously on the VM (e.g. the cron-driven nightly
        backup colliding with a bot-triggered /update apply).

        Uses a FileStream opened with FileShare::None so a second process
        attempting the same lock will fail immediately. The returned
        object MUST be passed to Release-HarbormasterLock in a finally
        block — if the script throws and the FileStream isn't disposed,
        the lock will only release when the PowerShell process exits.
    .PARAMETER Config
        Per-game config hashtable. Used for the per-game lock file name.
    .PARAMETER Operation
        Short name of the operation requesting the lock (used in
        diagnostics and the lock file's contents). E.g. 'backup', 'update'.
    .PARAMETER TimeoutSeconds
        How long to wait for the lock before giving up. Default 0
        (fail immediately if held). Set to a positive value for cron
        scripts that should wait briefly rather than fail.
    .PARAMETER PollIntervalMs
        How often to retry while waiting. Default 500 ms.
    .EXAMPLE
        $lock = Acquire-HarbormasterLock -Config $cfg -Operation 'backup'
        try {
            # ... do work ...
        }
        finally {
            Release-HarbormasterLock $lock
        }
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][hashtable]$Config,
        [Parameter(Mandatory)][string]$Operation,
        [int]$TimeoutSeconds = 0,
        [int]$PollIntervalMs = 500
    )

    $stateDir = Join-Path $env:ProgramData 'Harbormaster'
    if (-not (Test-Path $stateDir)) {
        New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
    }
    $lockPath = Join-Path $stateDir ("{0}.lock" -f $Config.GameName.ToLower())

    $deadline = (Get-Date).AddSeconds([math]::Max(0, $TimeoutSeconds))
    $stream = $null

    while ($true) {
        try {
            # FileShare::None means any other process opening this file with
            # the same flag will get an IOException immediately.
            $stream = [System.IO.FileStream]::new(
                $lockPath,
                [System.IO.FileMode]::OpenOrCreate,
                [System.IO.FileAccess]::ReadWrite,
                [System.IO.FileShare]::None
            )
            break
        }
        catch [System.IO.IOException] {
            if ((Get-Date) -ge $deadline) {
                $holder = ''
                try { $holder = (Get-Content $lockPath -ErrorAction SilentlyContinue) -join ' ' } catch {}
                throw "Could not acquire Harbormaster lock at '$lockPath' (held by: $holder)."
            }
            Start-Sleep -Milliseconds $PollIntervalMs
        }
    }

    # Write diagnostic contents so a stuck lock can be investigated.
    $info = @{
        Operation = $Operation
        Pid       = $PID
        Started   = (Get-Date).ToString('o')
        Host      = $env:COMPUTERNAME
    } | ConvertTo-Json -Compress
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($info)
    $stream.SetLength(0) | Out-Null
    $stream.Write($bytes, 0, $bytes.Length)
    $stream.Flush()

    return [pscustomobject]@{
        Path      = $lockPath
        Stream    = $stream
        Operation = $Operation
        Acquired  = Get-Date
    }
}

function Release-HarbormasterLock {
    <#
    .SYNOPSIS
        Release a lock acquired by Acquire-HarbormasterLock.
    .DESCRIPTION
        Disposes the underlying FileStream and removes the lock file.
        Safe to call with $null or a half-initialized object — failures
        are warnings, never errors, so this is safe in finally blocks.
    #>
    [CmdletBinding()]
    param([Parameter(ValueFromPipeline)] $Lock)

    if (-not $Lock) { return }
    try {
        if ($Lock.Stream) { $Lock.Stream.Dispose() }
    }
    catch {
        Write-Warning "Failed to dispose lock stream: $_"
    }
    try {
        if ($Lock.Path -and (Test-Path $Lock.Path)) {
            Remove-Item $Lock.Path -Force -ErrorAction SilentlyContinue
        }
    }
    catch {
        Write-Warning "Failed to remove lock file '$($Lock.Path)': $_"
    }
}

Export-ModuleMember -Function Acquire-HarbormasterLock, Release-HarbormasterLock
