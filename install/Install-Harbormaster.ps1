<#
.SYNOPSIS
    Bootstrap a Windows VM with everything Harbormaster needs to run.

.DESCRIPTION
    Idempotent setup script. Run this on a fresh game-server VM after RDP'ing
    in for the first time. Each step skips work that's already done, so it's
    safe to re-run after partial failures or to upgrade an existing install.

    What it does (in order, each step optional via switches):

      1. Sets PowerShell execution policy to RemoteSigned (LocalMachine).
      2. Installs the Visual C++ 2015-2022 x64 redistributable (most game
         servers need it).
      3. Installs the Az.Accounts and Az.Storage PowerShell modules from the
         PSGallery, AllUsers scope.
      4. Installs NSSM to C:\Tools\nssm and copies nssm.exe to System32.
      5. Installs SteamCMD to C:\SteamCMD and runs it once to self-update.
      6. Clones (or pulls) the Harbormaster repo to the install path.
      7. Creates the standard log/backup directories under C:\.

    The script does NOT:
      - Wrap a game server as an NSSM service (game-specific; see
        core/docs/nssm-service-pattern.md).
      - Set webhook or Healthchecks env vars (you fill those in by hand or via
        a deployment-time secrets bundle; see core/docs/discord-channels.md
        and core/docs/healthchecks-cron.md).
      - Enable the VM's system-assigned managed identity (that has to be
        toggled from the Azure portal/CLI on the VM resource itself).

.PARAMETER InstallDir
    Where to clone the repo. Defaults to C:\Scripts\harbormaster.

.PARAMETER RepoUrl
    Git repo to clone. Defaults to the public Harbormaster repo. Override
    with a private fork URL if needed.

.PARAMETER Branch
    Branch to check out. Defaults to main.

.PARAMETER SkipVCRedist
.PARAMETER SkipAzModules
.PARAMETER SkipNssm
.PARAMETER SkipSteamCmd
.PARAMETER SkipRepo
    Skip individual steps. Useful for re-running a single piece.

.EXAMPLE
    # Full first-time install
    PS C:\> .\Install-Harbormaster.ps1

.EXAMPLE
    # Just refresh the cloned repo
    PS C:\> .\Install-Harbormaster.ps1 -SkipVCRedist -SkipAzModules -SkipNssm -SkipSteamCmd

.NOTES
    Must be run as Administrator.
    Tested on Windows Server 2022 and Windows 11 23H2.
#>

[CmdletBinding()]
param(
    [string]$InstallDir = 'C:\Scripts\harbormaster',
    [string]$RepoUrl    = 'https://github.com/KillingItSoftly/harbormaster.git',
    [string]$Branch     = 'main',

    [switch]$SkipVCRedist,
    [switch]$SkipAzModules,
    [switch]$SkipNssm,
    [switch]$SkipSteamCmd,
    [switch]$SkipRepo
)

$ErrorActionPreference = 'Stop'

# ============================================================================
# Helpers
# ============================================================================

function Write-Step {
    param([string]$Title)
    Write-Host ""
    Write-Host "=== $Title ===" -ForegroundColor Cyan
}

function Write-Skip {
    param([string]$Reason)
    Write-Host "  SKIP: $Reason" -ForegroundColor DarkGray
}

function Write-Ok {
    param([string]$Message)
    Write-Host "  OK:   $Message" -ForegroundColor Green
}

function Test-Admin {
    $currentUser = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($currentUser)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Test-CommandExists {
    param([string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

# ============================================================================
# Pre-flight
# ============================================================================

if (-not (Test-Admin)) {
    throw "This script must be run from an elevated PowerShell session (Run as Administrator)."
}

if ($PSVersionTable.PSVersion.Major -lt 5) {
    throw "PowerShell 5.1 or later is required. Current: $($PSVersionTable.PSVersion)"
}

Write-Host "Harbormaster bootstrap starting..." -ForegroundColor White
Write-Host "  InstallDir: $InstallDir"
Write-Host "  RepoUrl:    $RepoUrl"
Write-Host "  Branch:     $Branch"

# ============================================================================
# Step 1: Execution policy
# ============================================================================
Write-Step "Step 1: Execution policy"

$current = Get-ExecutionPolicy -Scope LocalMachine
if ($current -in 'RemoteSigned', 'Unrestricted', 'Bypass') {
    Write-Skip "LocalMachine policy is already '$current'"
} else {
    Set-ExecutionPolicy -Scope LocalMachine -ExecutionPolicy RemoteSigned -Force
    Write-Ok "Set LocalMachine execution policy to RemoteSigned"
}

# ============================================================================
# Step 2: VC++ redistributable
# ============================================================================
Write-Step "Step 2: VC++ 2015-2022 redistributable (x64)"

if ($SkipVCRedist) {
    Write-Skip "Skipped via -SkipVCRedist"
} else {
    $vcKey = 'HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64'
    $installed = $false
    if (Test-Path $vcKey) {
        $v = (Get-ItemProperty $vcKey -ErrorAction SilentlyContinue).Version
        if ($v) {
            Write-Skip "Already installed (version $v)"
            $installed = $true
        }
    }

    if (-not $installed) {
        $tmp = Join-Path $env:TEMP 'vc_redist.x64.exe'
        Write-Host "  Downloading vc_redist.x64.exe..."
        Invoke-WebRequest -Uri 'https://aka.ms/vs/17/release/vc_redist.x64.exe' `
            -OutFile $tmp -UseBasicParsing
        Write-Host "  Installing..."
        $p = Start-Process -FilePath $tmp `
            -ArgumentList '/install','/quiet','/norestart' `
            -Wait -PassThru
        if ($p.ExitCode -ne 0 -and $p.ExitCode -ne 3010) {
            throw "vc_redist installer exited with code $($p.ExitCode)"
        }
        Remove-Item $tmp -Force
        Write-Ok "VC++ redistributable installed"
    }
}

# ============================================================================
# Step 3: Az PowerShell modules
# ============================================================================
Write-Step "Step 3: Az PowerShell modules (Accounts, Storage)"

if ($SkipAzModules) {
    Write-Skip "Skipped via -SkipAzModules"
} else {
    # Trust the PSGallery so Install-Module doesn't prompt
    if ((Get-PSRepository PSGallery).InstallationPolicy -ne 'Trusted') {
        Set-PSRepository -Name PSGallery -InstallationPolicy Trusted
        Write-Ok "Set PSGallery to Trusted"
    }

    foreach ($module in 'Az.Accounts', 'Az.Storage') {
        $existing = Get-Module -ListAvailable -Name $module |
            Sort-Object Version -Descending | Select-Object -First 1
        if ($existing) {
            Write-Skip "$module $($existing.Version) already installed"
        } else {
            Write-Host "  Installing $module..."
            Install-Module -Name $module -Force -AllowClobber -Scope AllUsers
            Write-Ok "$module installed"
        }
    }
}

# ============================================================================
# Step 4: NSSM
# ============================================================================
Write-Step "Step 4: NSSM (Non-Sucking Service Manager)"

if ($SkipNssm) {
    Write-Skip "Skipped via -SkipNssm"
} elseif (Test-CommandExists 'nssm') {
    $ver = & nssm version 2>&1 | Select-Object -First 1
    Write-Skip "Already on PATH ($ver)"
} else {
    $nssmZip = Join-Path $env:TEMP 'nssm.zip'
    $nssmDir = 'C:\Tools'
    Write-Host "  Downloading nssm 2.24..."
    Invoke-WebRequest -Uri 'https://nssm.cc/release/nssm-2.24.zip' `
        -OutFile $nssmZip -UseBasicParsing

    if (-not (Test-Path $nssmDir)) {
        New-Item -ItemType Directory -Path $nssmDir -Force | Out-Null
    }
    Expand-Archive -Path $nssmZip -DestinationPath $nssmDir -Force
    Copy-Item -Path "$nssmDir\nssm-2.24\win64\nssm.exe" `
        -Destination "$env:WINDIR\System32\nssm.exe" -Force
    Remove-Item $nssmZip -Force
    Write-Ok "NSSM installed to System32"
}

# ============================================================================
# Step 5: SteamCMD
# ============================================================================
Write-Step "Step 5: SteamCMD"

if ($SkipSteamCmd) {
    Write-Skip "Skipped via -SkipSteamCmd"
} else {
    $steamDir = 'C:\SteamCMD'
    $steamExe = Join-Path $steamDir 'steamcmd.exe'

    if (Test-Path $steamExe) {
        Write-Skip "Already installed at $steamExe"
    } else {
        if (-not (Test-Path $steamDir)) {
            New-Item -ItemType Directory -Path $steamDir -Force | Out-Null
        }
        $steamZip = Join-Path $env:TEMP 'steamcmd.zip'
        Write-Host "  Downloading steamcmd.zip..."
        Invoke-WebRequest -Uri 'https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip' `
            -OutFile $steamZip -UseBasicParsing
        Expand-Archive -Path $steamZip -DestinationPath $steamDir -Force
        Remove-Item $steamZip -Force

        Write-Host "  Running steamcmd once for first-run self-update..."
        # +quit ensures it exits after updating itself.
        & $steamExe '+quit' | Out-Null
        Write-Ok "SteamCMD installed and self-updated"
    }
}

# ============================================================================
# Step 6: Clone or update the repo
# ============================================================================
Write-Step "Step 6: Harbormaster repo"

if ($SkipRepo) {
    Write-Skip "Skipped via -SkipRepo"
} else {
    if (-not (Test-CommandExists 'git')) {
        Write-Host "  git not found; installing via winget..."
        if (-not (Test-CommandExists 'winget')) {
            throw "Neither git nor winget is available. Install Git for Windows manually and re-run."
        }
        winget install --id Git.Git -e --silent --accept-source-agreements --accept-package-agreements
        # winget doesn't refresh the current shell's PATH; pull it in.
        $env:PATH = [Environment]::GetEnvironmentVariable('PATH', 'Machine') + ';' +
                    [Environment]::GetEnvironmentVariable('PATH', 'User')
    }

    $parent = Split-Path $InstallDir -Parent
    if (-not (Test-Path $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }

    if (Test-Path (Join-Path $InstallDir '.git')) {
        Write-Host "  Repo already cloned at $InstallDir; pulling latest..."
        Push-Location $InstallDir
        try {
            git fetch --all --prune
            git checkout $Branch
            git pull --ff-only origin $Branch
        } finally {
            Pop-Location
        }
        Write-Ok "Repo updated to latest $Branch"
    } else {
        if (Test-Path $InstallDir) {
            $children = Get-ChildItem $InstallDir -Force -ErrorAction SilentlyContinue
            if ($children) {
                throw "Install dir exists and is not empty but isn't a git repo: $InstallDir"
            }
        }
        Write-Host "  Cloning $RepoUrl ($Branch) into $InstallDir..."
        git clone --branch $Branch $RepoUrl $InstallDir
        Write-Ok "Repo cloned to $InstallDir"
    }
}

# ============================================================================
# Step 7: Standard directories
# ============================================================================
Write-Step "Step 7: Standard directories"

foreach ($dir in 'C:\Logs', 'C:\Backups', 'C:\GameServers') {
    if (Test-Path $dir) {
        Write-Skip "$dir already exists"
    } else {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
        Write-Ok "Created $dir"
    }
}

# ============================================================================
# Done
# ============================================================================
Write-Host ""
Write-Host "Bootstrap complete." -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor White
Write-Host "  1. Enable the system-assigned managed identity on this VM (Azure portal -> VM -> Identity)."
Write-Host "  2. Grant that identity 'Storage Blob Data Contributor' on your backup storage account."
Write-Host "  3. Create or copy a per-game folder under $InstallDir\games\<slug>\ and fill in config.ps1."
Write-Host "  4. Set webhook and Healthchecks env vars in Machine scope. See:"
Write-Host "       $InstallDir\core\docs\discord-channels.md"
Write-Host "       $InstallDir\core\docs\healthchecks-cron.md"
Write-Host "  5. Wrap your game server as an NSSM service. See:"
Write-Host "       $InstallDir\core\docs\nssm-service-pattern.md"
Write-Host "  6. Register scheduled tasks against the per-game wrapper scripts."
Write-Host ""
