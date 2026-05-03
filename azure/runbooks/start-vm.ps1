<#
.SYNOPSIS
    Azure Automation runbook to start a game server VM on a schedule.

.DESCRIPTION
    Authenticates with the Automation Account's system-assigned managed
    identity and starts the named VM. If the VM is already running, exits
    with a no-op message instead of erroring.

    Designed to run on a schedule (e.g. Friday 16:00 local time) to bring
    a self-hosted game server up before peak play hours, paired with the
    matching stop-vm.ps1 runbook to shut it down off-hours.

.PARAMETER ResourceGroupName
    The resource group containing the VM.

.PARAMETER VmName
    The name of the VM to start.

.PARAMETER SubscriptionId
    Optional. Subscription to operate against. If omitted, uses the
    default subscription of the managed identity.

.NOTES
    Requires:
      - Az.Accounts and Az.Compute modules imported into the Automation Account.
      - System-assigned managed identity on the Automation Account.
      - That identity granted "Virtual Machine Contributor" on the VM (or RG).
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$ResourceGroupName,

    [Parameter(Mandatory)]
    [string]$VmName,

    [string]$SubscriptionId
)

$ErrorActionPreference = 'Stop'

Write-Output "[$(Get-Date -Format o)] start-vm runbook: $ResourceGroupName/$VmName"

# --- Auth ---
try {
    Disable-AzContextAutosave -Scope Process | Out-Null
    $ctx = (Connect-AzAccount -Identity).Context
    if ($SubscriptionId) {
        $ctx = Set-AzContext -SubscriptionId $SubscriptionId -DefaultProfile $ctx
    }
    Write-Output "Authenticated as $($ctx.Account.Id) in subscription $($ctx.Subscription.Name)"
}
catch {
    throw "Failed to authenticate with managed identity: $_"
}

# --- Look up the VM ---
$vm = Get-AzVM -ResourceGroupName $ResourceGroupName -Name $VmName -Status -ErrorAction Stop

$powerState = ($vm.Statuses | Where-Object { $_.Code -like 'PowerState/*' } |
    Select-Object -First 1).Code

Write-Output "Current power state: $powerState"

if ($powerState -eq 'PowerState/running') {
    Write-Output "VM is already running. Nothing to do."
    return
}

# --- Start ---
Write-Output "Starting VM..."
$result = Start-AzVM -ResourceGroupName $ResourceGroupName -Name $VmName -ErrorAction Stop

if ($result.Status -eq 'Succeeded') {
    Write-Output "VM started successfully."
}
else {
    throw "Start-AzVM completed with status: $($result.Status)"
}
