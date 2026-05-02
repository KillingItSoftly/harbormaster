function Send-Heartbeat {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$EnvVarName,

        [ValidateSet('Start', 'Success', 'Fail')]
        [string]$Status = 'Success',

        [int]$TimeoutSec = 10
    )

    # Read fresh from env on each call (same pattern as the notify module)
    $url = [Environment]::GetEnvironmentVariable($EnvVarName, 'Process')
    if ([string]::IsNullOrWhiteSpace($url)) {
        $url = [Environment]::GetEnvironmentVariable($EnvVarName, 'Machine')
    }

    if ([string]::IsNullOrWhiteSpace($url)) {
        Write-Warning "No Healthchecks URL configured for env var '$EnvVarName'"
        return
    }

    # Sanitize and validate
    $url = ($url -replace '[^\x21-\x7E]', '').Trim()
    if (-not ($url -match '^https://hc-ping\.com/[\w-]+$')) {
        Write-Warning "Healthchecks URL for '$EnvVarName' looks malformed (length $($url.Length))."
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
        Write-Warning "Heartbeat ping ($Status) to $EnvVarName failed: $_"
    }
}

function Get-DayBucketEnvVar {
    <#
    .SYNOPSIS
        Returns 'Weekday' or 'Weekend' based on today's date, used as a suffix
        when picking a Healthchecks URL.
    .EXAMPLE
        Get-DayBucketEnvVar -BaseName 'WINDROSE_HC_HEALTH'
        # Returns 'WINDROSE_HC_HEALTH_WEEKDAY' on Mon-Thu, 'WINDROSE_HC_HEALTH_WEEKEND' on Fri-Sun
    #>
    param([Parameter(Mandatory)][string]$BaseName)

    $dow = [int](Get-Date).DayOfWeek   # Sunday=0, Monday=1, ..., Saturday=6
    $bucket = if ($dow -ge 1 -and $dow -le 4) { 'WEEKDAY' } else { 'WEEKEND' }
    return "${BaseName}_$bucket"
}

Export-ModuleMember -Function Send-Heartbeat, Get-DayBucketEnvVar