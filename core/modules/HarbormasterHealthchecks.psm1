function Send-Heartbeat {
    <#
    .SYNOPSIS
        Sends a Healthchecks.io ping for a Harbormaster-managed game.
    .DESCRIPTION
        Builds the env var name from the per-game config:
            "${EnvVarPrefix}_HC_${Key}"
        With -DayBucket, appends "_WEEKDAY" (Mon-Thu) or "_WEEKEND" (Fri-Sun)
        so different schedules can use separate Healthchecks endpoints.
    .PARAMETER Config
        Per-game config hashtable. Must contain EnvVarPrefix.
    .PARAMETER Key
        Healthchecks key suffix, e.g. 'BACKUP', 'HEALTH', 'UPDATE_CHECK'.
    .PARAMETER Status
        Start | Success | Fail.
    .PARAMETER DayBucket
        Append _WEEKDAY / _WEEKEND to the env var name.
    .EXAMPLE
        Send-Heartbeat -Config $Config -Key BACKUP -Status Start
    .EXAMPLE
        Send-Heartbeat -Config $Config -Key HEALTH -Status Success -DayBucket
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [hashtable]$Config,

        [Parameter(Mandatory)]
        [string]$Key,

        [ValidateSet('Start', 'Success', 'Fail')]
        [string]$Status = 'Success',

        [switch]$DayBucket,

        [int]$TimeoutSec = 10
    )

    if ([string]::IsNullOrWhiteSpace($Config.EnvVarPrefix)) {
        Write-Warning "Config is missing EnvVarPrefix; cannot send heartbeat."
        return
    }

    $envVarName = "$($Config.EnvVarPrefix)_HC_$($Key.ToUpper())"
    if ($DayBucket) {
        $dow = [int](Get-Date).DayOfWeek   # Sun=0, Mon=1, ..., Sat=6
        $bucket = if ($dow -ge 1 -and $dow -le 4) { 'WEEKDAY' } else { 'WEEKEND' }
        $envVarName = "${envVarName}_$bucket"
    }

    $url = [Environment]::GetEnvironmentVariable($envVarName, 'Process')
    if ([string]::IsNullOrWhiteSpace($url)) {
        $url = [Environment]::GetEnvironmentVariable($envVarName, 'Machine')
    }

    if ([string]::IsNullOrWhiteSpace($url)) {
        Write-Warning "No Healthchecks URL configured for env var '$envVarName'"
        return
    }

    $url = ($url -replace '[^\x21-\x7E]', '').Trim()
    if (-not ($url -match '^https://hc-ping\.com/[\w-]+$')) {
        Write-Warning "Healthchecks URL for '$envVarName' looks malformed (length $($url.Length))."
        return
    }

    $finalUrl = switch ($Status) {
        'Start'   { "$url/start" }
        'Success' { $url }
        'Fail'    { "$url/fail" }
    }

    try {
        Invoke-RestMethod -Uri $finalUrl -Method Get -TimeoutSec $TimeoutSec | Out-Null
    }
    catch {
        Write-Warning "Heartbeat ping ($Status) to $envVarName failed: $_"
    }
}

Export-ModuleMember -Function Send-Heartbeat
