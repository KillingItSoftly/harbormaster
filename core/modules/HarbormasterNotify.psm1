function Send-HarbormasterNotification {
    <#
    .SYNOPSIS
        Posts a Discord embed to a per-game webhook.
    .DESCRIPTION
        Resolves the webhook URL from the env var "${EnvVarPrefix}_WEBHOOK_${Channel}",
        where EnvVarPrefix and the embed footer come from the per-game config.
    .PARAMETER Config
        Per-game config hashtable. Must contain EnvVarPrefix and GameName.
    .EXAMPLE
        Send-HarbormasterNotification -Config $Config `
            -Title 'Backup OK' -Message 'Daily backup completed' -Severity Success
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][hashtable]$Config,
        [Parameter(Mandatory)][string]$Title,
        [Parameter(Mandatory)][string]$Message,

        [ValidateSet("Critical", "Warning", "Info", "Success")]
        [string]$Severity = "Info",
        [ValidateSet("Alerts", "Status")]
        [string]$Channel = "Status",
        [hashtable]$Fields = @{}
    )

    if ([string]::IsNullOrWhiteSpace($Config.EnvVarPrefix)) {
        Write-Warning "Config is missing EnvVarPrefix; cannot send notification."
        return
    }
    if ([string]::IsNullOrWhiteSpace($Config.GameName)) {
        Write-Warning "Config is missing GameName; cannot send notification."
        return
    }

    $envVarName = "$($Config.EnvVarPrefix)_WEBHOOK_$($Channel.ToUpper())"
    $url = [Environment]::GetEnvironmentVariable($envVarName, 'Process')
    if ([string]::IsNullOrWhiteSpace($url)) {
        $url = [Environment]::GetEnvironmentVariable($envVarName, 'Machine')
    }
    if ([string]::IsNullOrWhiteSpace($url)) {
        Write-Warning "No webhook URL configured for channel '$Channel'. Set the $envVarName env var."
        return
    }

    # Strip any non-printable or non-ASCII characters
    $url = ($url -replace '[^\x21-\x7E]', '').Trim()

    if (-not ($url -match '^https://discord\.com/api/webhooks/\d+/[\w-]+$')) {
        Write-Warning "Webhook URL for '$Channel' is malformed (length $($url.Length))."
        return
    }

    $color = switch ($Severity) {
        "Critical" { 16711680 }
        "Warning"  { 16776960 }
        "Success"  { 65280 }
        "Info"     { 5814783 }
    }

    $prefix = switch ($Severity) {
        "Critical" { "[CRITICAL]" }
        "Warning"  { "[WARN]" }
        "Success"  { "[OK]" }
        "Info"     { "[INFO]" }
    }

    $embed = [ordered]@{
        title       = "$prefix $Title"
        description = $Message
        color       = $color
        timestamp   = (Get-Date).ToUniversalTime().ToString("o")
        footer      = @{ text = "$($Config.GameName) Server" }
    }

    if ($Fields.Count -gt 0) {
        $embedFields = @()
        foreach ($key in $Fields.Keys) {
            $embedFields += [ordered]@{
                name   = "$key"
                value  = "$($Fields[$key])"
                inline = $true
            }
        }
        $embed.fields = $embedFields
    }

    $payload = @{ embeds = @($embed) } | ConvertTo-Json -Depth 10 -Compress

    try {
        Invoke-RestMethod `
            -Uri $url `
            -Method Post `
            -Body $payload `
            -ContentType "application/json; charset=utf-8" | Out-Null
    }
    catch {
        Write-Warning "Discord notification failed: $_"
        Write-Warning "Payload was: $payload"
    }
}

Export-ModuleMember -Function Send-HarbormasterNotification
