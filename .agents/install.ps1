<#
.SYNOPSIS
    Agent OS (Ostwin) — Windows Installer

.DESCRIPTION
    Installs all dependencies and the ostwin CLI on Windows 10/11.
    This is the PowerShell equivalent of install.sh for macOS/Linux.

    What gets installed:
      - Python 3.10+       (via winget / choco / direct download)
      - PowerShell 7+      (via winget / choco / MSI)
      - uv                 (Python package/env manager)
      - Node.js            (for dashboard UI)
      - opencode           (Agent execution engine)
      - Obscura            (built-in browser MCP runtime)
      - Pester 5+          (PowerShell test framework)
      - MCP dependencies   (fastapi, uvicorn, etc.)

    Supports: Windows 10 (build 10240+), Windows 11
    No dependency on WSL, Cygwin, or Git Bash.

.PARAMETER Yes
    Non-interactive mode — auto-approve all installs.

.PARAMETER Dir
    Install to custom location (default: $HOME\.ostwin).

.PARAMETER SourceDir
    Path to the agent-os source repository.

.PARAMETER Port
    Dashboard port (default: 3366).

.PARAMETER DashboardOnly
    Install dashboard API + frontend only (implies -Yes).

.PARAMETER Channel
    Also install & start the channel connectors (Telegram + Discord + Slack).

.PARAMETER SkipOptional
    Skip optional components (Pester, etc.)

.PARAMETER Help
    Show this help text.

.EXAMPLE
    .\install.ps1 -Yes
    Non-interactive full install.

.EXAMPLE
    .\install.ps1 -DashboardOnly
    Install dashboard-only subset.

.EXAMPLE
    .\install.ps1 -Dir C:\MyOstwin -Port 8080
    Install to custom directory with custom port.
#>

[CmdletBinding()]
param(
    [Alias("y")]
    [switch]$Yes,

    [string]$Dir,

    [string]$SourceDir,

    [int]$Port = 3366,

    [switch]$DashboardOnly,

    [switch]$Channel,

    [switch]$SkipOptional,

    [switch]$Help
)

# ═══════════════════════════════════════════════════════════════════════════════
# SETUP
# ═══════════════════════════════════════════════════════════════════════════════

$ErrorActionPreference = "Stop"

if ($Help) {
    Get-Help $MyInvocation.MyCommand.Path -Detailed
    exit 0
}

# Script location
$script:ScriptDir = $PSScriptRoot
$script:InstallerDir = Join-Path $script:ScriptDir "installer"

# Globals consumed by modules
$script:InstallDir = if ($Dir) { $Dir } else { Join-Path $HOME ".ostwin" }
$script:SourceDir = if ($SourceDir) { $SourceDir } else { Split-Path $script:ScriptDir -Parent }
$script:AutoYes = $Yes.IsPresent -or $DashboardOnly.IsPresent
$script:SkipOptional = $SkipOptional.IsPresent
$script:DashboardOnly = $DashboardOnly.IsPresent
$script:StartChannel = $Channel.IsPresent -or $true  # default: true (mirrors bash)
$script:DashboardPort = $Port
$script:VenvDir = Join-Path $script:InstallDir ".venv"
$script:FirstInstall = -not (Test-Path $script:VenvDir)
$script:PythonVersion = ""
$script:PwshCurrentVersion = ""
$script:PythonCmd = ""
$script:TunnelUrl = ""
$script:OstwinApiKey = ""

# ═══════════════════════════════════════════════════════════════════════════════
# SOURCE ALL MODULES
# ═══════════════════════════════════════════════════════════════════════════════

$modules = @(
    "Lib.ps1",
    "Versions.ps1",
    "Detect-OS.ps1",
    "Check-Deps.ps1",
    "Install-Deps.ps1",
    "Install-Files.ps1",
    "Setup-Venv.ps1",
    "Setup-Env.ps1",
    "Setup-Models.ps1",
    "Patch-MCP.ps1",
    "Build-Frontend.ps1",
    "Setup-Path.ps1",
    "Setup-OpenCode.ps1",
    "Sync-Agents.ps1",
    "Start-Dashboard.ps1",
    "Start-Channels.ps1",
    "Verify.ps1",
    "Orchestrate-Deps.ps1"
)

foreach ($mod in $modules) {
    $modPath = Join-Path $script:InstallerDir $mod
    if (Test-Path $modPath) {
        . $modPath
    }
    else {
        Write-Warning "Module not found: $modPath"
    }
}

# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

Write-Host ""
Write-Host "  ╔══════════════════════════════════════════════════╗" -ForegroundColor White
Write-Host "  ║     " -ForegroundColor White -NoNewline
Write-Host "Ostwin" -ForegroundColor Cyan -NoNewline
Write-Host " — Agent OS Installer (Windows)        ║" -ForegroundColor White
Write-Host "  ║     Multi-Agent War-Room Orchestrator            ║" -ForegroundColor White
Write-Host "  ╚══════════════════════════════════════════════════╝" -ForegroundColor White
Write-Host ""

# Step 1: Detect platform
Write-Header "1. Detecting platform"
Detect-WindowsOS
Write-Ok "Windows $($script:WinVersion) ($($script:ARCH)) [pkg: $($script:PkgMgr)]"
if ($script:DevModeEnabled) {
    Write-Ok "Developer Mode enabled (symlinks without elevation)"
}
else {
    Write-Info "Developer Mode not enabled — symlinks may fall back to junctions"
}

# Step 2: Dependencies
Invoke-DependencyOrchestration
Write-Host ""

# Step 3: Build frontend
Write-Header "3. Building dashboard frontend (fe)"
Build-Frontend -SubDir "dashboard\fe" -Label "Dashboard FE" -Required

# Step 4: Install files
Write-Header "4. Installing Agent OS"
Install-Files

# Step 5: Python environment + MCP patching
Write-Header "5. Setting up Python environment"
Setup-Venv
Patch-McpConfig
Sync-OpenCodeAgents
Compute-BuildHash

Write-Header "5b. Setting up .env"
Setup-Env
Write-Header "5c. Initializing models catalog"
if ($script:FirstInstall) {
    Setup-Models -Force
} else {
    Setup-Models
}

Write-Header "5d. OpenCode agent permissions"
Setup-OpenCodePermissions

# Step 6: Pester
if ($script:DashboardOnly) {
    Write-Header "6. PowerShell modules (skipped — dashboard-only)"
    Write-Info "Skipping in dashboard-only mode"
}
elseif (-not $script:SkipOptional) {
    Write-Header "6. PowerShell modules"
    Install-PesterModule
}
else {
    Write-Header "6. PowerShell modules (skipped)"
    Write-Info "--SkipOptional set"
}

# Step 7: PATH
if (-not $script:DashboardOnly) {
    Write-Header "7. Configuring PATH"
    Setup-Path
}
else {
    Write-Header "7. PATH (skipped — dashboard-only)"
    Write-Info "Skipping PATH setup in dashboard-only mode"
    $binDir = Join-Path $script:InstallDir ".agents\bin"
    if ($env:PATH -notlike "*$binDir*") {
        $env:PATH = "$binDir;$env:PATH"
    }
}

# Step 8: Verification
Write-Header "8. Verification"
Verify-Components

# Step 9: Dashboard
Write-Header "9. Starting dashboard"
Start-Dashboard
Publish-Skills

# Step 9c: Channels
Write-Header "9c. Installing channel dependencies (Telegram + Discord + Slack)"
Install-Channels

if ($script:StartChannel -and $script:ChanDir) {
    Write-Header "9d. Starting channel connectors"
    try {
        Start-Channels
    }
    catch {
        Write-Warn "Channel connectors failed to start (non-critical): $_"
    }
}

# Final banner
Print-CompletionBanner
