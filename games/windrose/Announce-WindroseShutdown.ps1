$config = & "$PSScriptRoot\config.ps1"
& "$PSScriptRoot\..\..\core\scripts\Announce-ServerShutdown.ps1" -Config $config @args
