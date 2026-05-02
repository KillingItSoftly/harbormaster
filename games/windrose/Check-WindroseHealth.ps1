$config = & "$PSScriptRoot\config.ps1"
& "$PSScriptRoot\..\..\core\scripts\Check-ServerHealth.ps1" -Config $config @args
