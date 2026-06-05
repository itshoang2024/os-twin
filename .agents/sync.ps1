<#
.SYNOPSIS
    Agent OS — Framework Sync (PowerShell port of sync.sh)

.DESCRIPTION
    Re-syncs framework files from the os-twin source to an already-initialized
    target project, preserving project-specific data (plans, .env, config).

.PARAMETER TargetDir
    Directory to sync to. Defaults to current directory.
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$TargetDir = "."
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path $PSCommandPath -Parent
$SourceAgents = $ScriptDir
$TargetAgents = Join-Path $TargetDir ".agents"

if (-not (Test-Path $TargetAgents -PathType Container)) {
    Write-Error "[ERROR] .agents/ not found in $TargetDir"
    Write-Host "  Run 'ostwin init $TargetDir' first to initialize."
    exit 1
}

Write-Host ""
Write-Host "  +======================================+"
Write-Host "  |        Ostwin -- Framework Sync       |"
Write-Host "  +======================================+"
Write-Host ""
Write-Host "  Source: $SourceAgents"
Write-Host "  Target: $TargetAgents"
Write-Host ""

# ─── Helper: Sync directory contents, excluding specific patterns ────────────

function Sync-Directory {
    param(
        [string]$Source,
        [string]$Destination,
        [string[]]$ExcludeNames = @()
    )
    if (-not (Test-Path $Source -PathType Container)) { return }
    if (-not (Test-Path $Destination)) { New-Item -ItemType Directory -Path $Destination -Force | Out-Null }

    foreach ($item in Get-ChildItem -Path $Source -Force -ErrorAction SilentlyContinue) {
        # Skip excluded names
        if ($item.Name -in $ExcludeNames) { continue }

        $destPath = Join-Path $Destination $item.Name
        if ($item.PSIsContainer) {
            Sync-Directory -Source $item.FullName -Destination $destPath -ExcludeNames $ExcludeNames
        }
        else {
            Copy-Item -Path $item.FullName -Destination $destPath -Force
        }
    }
}

# ─── Sync core framework files (excluding project-specific) ─────────────────

Sync-Directory -Source $SourceAgents -Destination $TargetAgents -ExcludeNames @("plans", ".env", "config.json", "dashboard")
Write-Host "  [synced] core framework files"

# ─── Sync channel tools ─────────────────────────────────────────────────────

$channelDir = Join-Path $TargetAgents "channel"
if (-not (Test-Path $channelDir)) { New-Item -ItemType Directory -Path $channelDir -Force | Out-Null }
foreach ($script in @("read.sh", "wait-for.sh", "Read-Messages.ps1", "Wait-ForMessage.ps1")) {
    $src = Join-Path $SourceAgents "channel" $script
    if (Test-Path $src) {
        Copy-Item -Path $src -Destination (Join-Path $channelDir $script) -Force
    }
}
Write-Host "  [synced] channel tools"

# ─── Sync plan tools ────────────────────────────────────────────────────────

$planDir = Join-Path $TargetAgents "plan"
if (-not (Test-Path $planDir)) { New-Item -ItemType Directory -Path $planDir -Force | Out-Null }
foreach ($script in @("New-Plan.ps1", "Start-Plan.ps1", "New-Plan.Tests.ps1", "Start-Plan.Tests.ps1")) {
    $src = Join-Path $SourceAgents "plan" $script
    if (Test-Path $src) {
        Copy-Item -Path $src -Destination (Join-Path $planDir $script) -Force
    }
}
Write-Host "  [synced] plan tools"

# ─── Sync role definitions and runners ───────────────────────────────────────

$baseRoleDir = Join-Path $TargetAgents "roles" "_base"
if (-not (Test-Path $baseRoleDir)) { New-Item -ItemType Directory -Path $baseRoleDir -Force | Out-Null }

foreach ($role in @("manager", "engineer", "qa", "architect")) {
    $roleDir = Join-Path $TargetAgents "roles" $role
    if (-not (Test-Path $roleDir)) { New-Item -ItemType Directory -Path $roleDir -Force | Out-Null }

    foreach ($pattern in @("ROLE.md", "run.sh", "loop.sh", "deepagents-cli.md", "role.json")) {
        $src = Join-Path $SourceAgents "roles" $role $pattern
        if (Test-Path $src) {
            Copy-Item -Path $src -Destination (Join-Path $roleDir (Split-Path $src -Leaf)) -Force
        }
    }
    # Sync Start-*.ps1 files
    foreach ($ps1File in Get-ChildItem -Path (Join-Path $SourceAgents "roles" $role) -Filter "Start-*.ps1" -ErrorAction SilentlyContinue) {
        Copy-Item -Path $ps1File.FullName -Destination (Join-Path $roleDir $ps1File.Name) -Force
    }
}

# Sync _base role engine
foreach ($ps1File in Get-ChildItem -Path (Join-Path $SourceAgents "roles" "_base") -Filter "*.ps1" -ErrorAction SilentlyContinue) {
    Copy-Item -Path $ps1File.FullName -Destination (Join-Path $baseRoleDir $ps1File.Name) -Force
}

# Sync role registry
$registryJson = Join-Path $SourceAgents "roles" "registry.json"
if (Test-Path $registryJson) {
    Copy-Item -Path $registryJson -Destination (Join-Path $TargetAgents "roles" "registry.json") -Force
}
Write-Host "  [synced] roles"

# ─── Sync release tools ─────────────────────────────────────────────────────

$releaseDir = Join-Path $TargetAgents "release"
if (-not (Test-Path $releaseDir)) { New-Item -ItemType Directory -Path $releaseDir -Force | Out-Null }
foreach ($script in @("draft.sh", "signoff.sh")) {
    $src = Join-Path $SourceAgents "release" $script
    if (Test-Path $src) { Copy-Item -Path $src -Destination (Join-Path $releaseDir $script) -Force }
}
$releaseTemplate = Join-Path $SourceAgents "release" "RELEASE.template.md"
if (Test-Path $releaseTemplate) {
    Copy-Item -Path $releaseTemplate -Destination (Join-Path $releaseDir "RELEASE.template.md") -Force
}
Write-Host "  [synced] release tools"

# ─── Sync libraries ─────────────────────────────────────────────────────────

$libDir = Join-Path $TargetAgents "lib"
if (-not (Test-Path $libDir)) { New-Item -ItemType Directory -Path $libDir -Force | Out-Null }
foreach ($lib in @("utils.sh", "log.sh")) {
    $src = Join-Path $SourceAgents "lib" $lib
    if (Test-Path $src) { Copy-Item -Path $src -Destination (Join-Path $libDir $lib) -Force }
}
foreach ($psm1 in Get-ChildItem -Path (Join-Path $SourceAgents "lib") -Filter "*.psm1" -ErrorAction SilentlyContinue) {
    Copy-Item -Path $psm1.FullName -Destination (Join-Path $libDir $psm1.Name) -Force
}
Write-Host "  [synced] libraries"

# ─── Sync CLI entry point ───────────────────────────────────────────────────

$binDir = Join-Path $TargetAgents "bin"
if (-not (Test-Path $binDir)) { New-Item -ItemType Directory -Path $binDir -Force | Out-Null }
$srcOstwin = Join-Path $SourceAgents "bin" "ostwin"
if (Test-Path $srcOstwin) { Copy-Item -Path $srcOstwin -Destination (Join-Path $binDir "ostwin") -Force }
# Also sync PS1 entry points
foreach ($ps1 in @("ostwin.ps1", "ostwin.cmd", "agent.ps1", "memory.ps1")) {
    $src = Join-Path $SourceAgents "bin" $ps1
    if (Test-Path $src) { Copy-Item -Path $src -Destination (Join-Path $binDir $ps1) -Force }
}
Write-Host "  [synced] CLI entry point"

# ─── Sync plan template (but NOT user plans) ────────────────────────────────

$plansDir = Join-Path $TargetAgents "plans"
if (-not (Test-Path $plansDir)) { New-Item -ItemType Directory -Path $plansDir -Force | Out-Null }
$planTemplate = Join-Path $SourceAgents "plans" "PLAN.template.md"
if (Test-Path $planTemplate) {
    Copy-Item -Path $planTemplate -Destination (Join-Path $plansDir "PLAN.template.md") -Force
}
Write-Host "  [synced] plan template"

# ─── Sync dashboard from sibling directory ───────────────────────────────────

$srcDashboard = Join-Path (Split-Path $SourceAgents -Parent) "dashboard"
if (Test-Path $srcDashboard -PathType Container) {
    Write-Host "  [synced] dashboard"
    $destDashboard = Join-Path $TargetAgents "dashboard"
    if (-not (Test-Path $destDashboard)) { New-Item -ItemType Directory -Path $destDashboard -Force | Out-Null }
    # Mirror sync (delete destination items not in source)
    Sync-Directory -Source $srcDashboard -Destination $destDashboard
}

# ─── Check for new config keys ───────────────────────────────────────────────

$srcConfig = Join-Path $SourceAgents "config.json"
$dstConfig = Join-Path $TargetAgents "config.json"
if ((Test-Path $srcConfig) -and (Test-Path $dstConfig)) {
    try {
        $srcData = Get-Content $srcConfig -Raw | ConvertFrom-Json
        $dstData = Get-Content $dstConfig -Raw | ConvertFrom-Json

        $srcKeys = ($srcData | Get-Member -MemberType NoteProperty).Name | Sort-Object -Unique
        $dstKeys = ($dstData | Get-Member -MemberType NoteProperty).Name | Sort-Object -Unique

        $newKeys = $srcKeys | Where-Object { $_ -notin $dstKeys }
        if ($newKeys.Count -gt 0) {
            Write-Host ""
            Write-Host "  [NOTICE] Source config.json has new keys not in your project config:"
            foreach ($key in $newKeys) {
                Write-Host "    `"$key`":"
            }
            Write-Host "  Review $srcConfig and update your config manually."
        }
    }
    catch { }
}

Write-Host ""
Write-Host "  [OK] Framework synced to $TargetAgents/"
Write-Host ""
Write-Host "  Preserved:"
Write-Host "    - .agents/plans/ (your plans)"
Write-Host "    - .agents/.env (your secrets)"
Write-Host "    - .agents/config.json (your config)"
Write-Host ""
