<#
.SYNOPSIS
    Azure Automation runbook to deallocate a game server VM on a schedule.

.DESCRIPTION
    Authenticates with the Automation Account's system-assigned managed
    identity and deallocates (Stop -Force) the named VM. Deallocation is
    required to actually stop billing for compute — a graceful guest-OS
    shutdown alone leaves the VM in the 'stopped' state, which still
    incurs cost.

    If the VM is already deallocated, exits with a no-op message instead
    of erroring.

    Optional pre-stop hold-off: if -BackupTaskWindowMinutes is specified,
    the runbook checks whether the most recent activity log entry on the
    VM looks like an in-progress backup operation and aborts the stop if
    so, leaving the next scheduled run to try again. This is a coarse
    safeguard, not a guarantee.

.PARAMETER ResourceGroupName
    The resource group containing the VM.

.PARAMETER VmName
    The name of the VM to stop.

.PARAMETER SubscriptionId
    Optional. Subscription to operate against. If omitted, uses the
    default subscription of the managed identity.

.PARAMETER SkipShutdownIfBackupRunning
    If set, queries the VM's activity log for recent write operations and
    skips the deallocate if one is in progress. Useful when a daily backup
    schedule overlaps with the auto-shutdown window.

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

    [string]$SubscriptionId,

    [switch]$SkipShutdownIfBackupRunning
)

$ErrorActionPreference = 'Stop'

Write-Output "[$(Get-Date -Format o)] stop-vm runbook: $ResourceGroupName/$VmName"

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

if ($powerState -eq 'PowerState/deallocated') {
    Write-Output "VM is already deallocated. Nothing to do."
    return
}

# --- Optional safeguard: skip if a backup-shaped operation is in flight ---
if ($SkipShutdownIfBackupRunning) {
    $since = (Get-Date).AddMinutes(-30).ToUniversalTime()
    $log = Get-AzLog `
        -ResourceGroupName $ResourceGroupName `
        -StartTime $since `
        -ErrorAction SilentlyContinue |
        Where-Object {
            $_.ResourceId -like "*/virtualMachines/$VmName" -and
            $_.Status.Value -eq 'Started' -and
            ($_.OperationName.Value -like '*backup*' -or
             $_.OperationName.Value -like '*snapshot*')
        }

    if ($log) {
        Write-Output "Backup/snapshot operation appears in flight; skipping shutdown."
        Write-Output ($log | Select-Object -First 1 |
            Format-List EventTimestamp, OperationName, Caller | Out-String)
        return
    }
}

# --- Deallocate ---
Write-Output "Deallocating VM..."
$result = Stop-AzVM `
    -ResourceGroupName $ResourceGroupName `
    -Name $VmName `
    -Force `
    -ErrorAction Stop

if ($result.Status -eq 'Succeeded') {
    Write-Output "VM deallocated successfully."
}
else {
    throw "Stop-AzVM completed with status: $($result.Status)"
}
