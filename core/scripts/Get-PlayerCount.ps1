<#
.SYNOPSIS Return the current online player count for a Harbormaster game.
.DESCRIPTION
    Game-agnostic harness. Each per-game config may define a
    PlayerCountProbe key whose value is a scriptblock; this script
    invokes it with $Config and prints a single integer to stdout.

    If no probe is defined, prints "unknown" and exits 0 — callers
    should treat that as "cannot determine, do not gate on it".

    The probe contract:
      [scriptblock] -> takes $Config -> returns [int] or $null.
      $null means "service is up but the probe couldn't read a count
      right now" (e.g. log file rotated).
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][hashtable]$Config
)
$ErrorActionPreference = 'Stop'

if (-not $Config.ContainsKey('PlayerCountProbe') -or $null -eq $Config.PlayerCountProbe) {
    Write-Output 'unknown'
    exit 0
}

$probe = $Config.PlayerCountProbe
if ($probe -isnot [scriptblock]) {
    Write-Output 'unknown'
    exit 0
}

try {
    $count = & $probe $Config
    if ($null -eq $count) {
        Write-Output 'unknown'
        exit 0
    }
    Write-Output ([int]$count)
}
catch {
    Write-Warning "PlayerCountProbe failed: $_"
    Write-Output 'unknown'
    exit 0
}
