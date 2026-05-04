<#
.SYNOPSIS List blobs in the configured backup container, newest first.
.DESCRIPTION
    Used by the bot's /restore list command. Game-agnostic. Outputs
    one blob per line in: <name>\t<size_mb>\t<lastmodified_iso>
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][hashtable]$Config,
    [int]$Limit = 30
)
$ErrorActionPreference = 'Stop'

Connect-AzAccount -Identity | Out-Null
$ctx = New-AzStorageContext `
    -StorageAccountName $Config.StorageAccount `
    -UseConnectedAccount

$slug = $Config.GameName.ToLower()
$blobs = Get-AzStorageBlob -Container $Config.BlobContainer -Context $ctx |
    Where-Object {
        $_.Name -match "^${slug}_\d{4}-\d{2}-\d{2}_\d{4}\.zip$" -or
        $_.Name -match '^milestone_(pristine|pre-change|stable|general)_'
    } |
    Sort-Object -Property LastModified -Descending |
    Select-Object -First $Limit

foreach ($b in $blobs) {
    $sizeMb = [math]::Round($b.Length / 1MB, 1)
    $when = $b.LastModified.UtcDateTime.ToString('s') + 'Z'
    "$($b.Name)`t${sizeMb}`t$when"
}
