# Azure VM Setup

This is the foundation everything else sits on. A reasonably-sized Windows VM with a static IP, sized for one game server, with cost-saving auto-shutdown.

## VM specs

- **Image**: Windows Server 2022 Datacenter (Azure Edition) is the cleanest choice. Windows 10/11 desktop also works if you prefer a familiar GUI.
- **Size**: `Standard_D4s_v5` (4 vCPU, 16 GB RAM) handles one full-crew game server comfortably with room for monitoring overhead. Scale up to `D8s_v5` if you need to run multiple servers.
- **OS disk**: Premium SSD, 128 GB. Plenty for the OS, game install, logs, and local backup retention.
- **Authentication**: Password is simpler than RDP cert juggling for a one-off box.
- **Public IP**: Standard, **static**. You want the IP to survive reboots so DNS, firewall rules, and any external integrations stay valid.
- **Inbound ports**: RDP (3389) only at first. Lock it down to your home IP via NSG rule, or better, use Azure Bastion or Just-In-Time access.

## Cost optimization

A D4s_v5 left running 24/7 is about $140/month for compute. A part-time gaming server doesn't need to be on 24/7.

### Auto-shutdown

Built into the Azure portal — VM → Operations → Auto-shutdown. Set a daily shutdown time when nobody plays (typical: 1 or 2 AM). The VM gracefully shuts down at that time and stops billing for compute.

Storage and the static IP keep billing while stopped — usually around $20-25/month minimum even when off.

### Auto-start (no built-in option)

Azure has no native auto-start. Three options:

- **Azure Automation runbook** with a managed identity and scheduled trigger (recommended — see [start-vm.ps1](../../azure/runbooks/start-vm.ps1) and [stop-vm.ps1](../../azure/runbooks/stop-vm.ps1) in this repo)
- **Logic App with Recurrence trigger** — clickier but works
- **External cron** (GitHub Actions, Healthchecks.io's webhook, etc.)

For schedules that vary by day-of-week (gaming weekday evenings vs. weekend daytime), create one runbook per action (start, stop) and attach multiple schedules — one weekday, one weekend.

### Cost rough math

For a typical schedule of ~365 hours/month on:

- Compute (D4s_v5 @ $0.192/hr): ~$70/mo
- 128 GB Premium SSD: ~$19/mo
- Static IP: ~$3.65/mo
- **Total**: ~$93/mo

vs. ~$163/mo running 24/7. Roughly half the cost for time-bounded use.

## Storage account for backups

Separate from the VM — a Standard, LRS storage account in the same region. See [healthchecks-cron.md](healthchecks-cron.md) for the timezone-related gotchas; [discord-channels.md](discord-channels.md) doesn't apply here.

Recommended security settings:

- **Allow storage account key access**: Disabled (forces Entra ID auth)
- **Public network access**: Enabled from selected virtual networks
- **Service endpoint**: Enable `Microsoft.Storage` on the VM's subnet so traffic stays on the Azure backbone without paying for a private endpoint

Grant the VM's system-assigned managed identity the **Storage Blob Data Contributor** role on the storage account. The backup script uses `Connect-AzAccount -Identity` to authenticate; no keys are stored anywhere.

Enable on the blob containers:

- **Soft delete for blobs** (14 days)
- **Soft delete for containers** (14 days)
- **Versioning** (optional, useful for accidental overwrite recovery)

## VM prerequisites for the toolkit

After the VM is created, RDP in and:

1. **Disable IE Enhanced Security** (Server Manager → Local Server → IE Enhanced Security Configuration → Off). Without this every download is a battle.
2. **Install the VC++ redistributables**:
```powershell
Invoke-WebRequest 'https://aka.ms/vs/17/release/vc_redist.x64.exe' -OutFile "$env:TEMP\vc.exe"
Start-Process "$env:TEMP\vc.exe" -ArgumentList '/install','/quiet','/norestart' -Wait
```
Many Unreal Engine games (and game servers) need MSVCP140.dll, VCRUNTIME140.dll, etc. Server Core / fresh Server installs don't have these by default.
3. **Install the Az PowerShell modules** (for blob backups and Azure auth):
```powershell
   Install-Module -Name Az.Accounts -Force -AllowClobber -Scope AllUsers
   Install-Module -Name Az.Storage -Force -AllowClobber -Scope AllUsers
```
4. **Enable the system-assigned managed identity** on the VM (VM → Identity → System assigned → On).
5. **Set execution policy** to RemoteSigned so PowerShell scripts can run:
```powershell
   Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope LocalMachine
```

## Common pitfalls

- **Forgetting to size for AVX**: Some game servers (Unreal Engine 5 specifically) require CPU AVX support. D-series and E-series v5 SKUs have it; older A-series and B1 tiers don't. Check before downsizing.
- **Burstable B-series for game servers**: Looks cheaper but credits can deplete during sustained CPU load, causing performance throttling. D-series gives predictable performance for the same money in practice.
- **Region mismatch between VM and storage account**: Cross-region transfers add bandwidth charges. Always pin them to the same region.
- **Running the auto-shutdown without a graceful in-game warning**: Players hate sudden disconnects. Schedule a Discord ping 10-15 minutes before shutdown.

## Resizing later

VM resizes preserve everything — disk, network, services, configs. From the portal: VM → Size → pick new size → Resize. Downtime is 3-5 minutes (the VM stops, swaps to a new host, restarts). Static IPs survive. NSSM-wrapped services come back up automatically on boot.

The OS disk doesn't auto-resize when you upsize the VM — disk size is independent. To grow the disk, that's a separate operation, and disks can only grow, never shrink.