<#
.SYNOPSIS
    Redesign-Subcommand.ps1 — Automate clone → patch → re-execute for subcommands.
.DESCRIPTION
    Self-heals broken subcommands within a war-room scope.
#>
param(
    [Parameter(Mandatory)]
    [string]$RoomDir,
    [Parameter(Mandatory)]
    [string]$RoleName,
    [Parameter(Mandatory)]
    [string]$SubcommandName,
    [Parameter(Mandatory)]
    [string]$ErrorContext,
    [string]$TaskRef = ''
)

$agentsDir = $env:AGENTS_DIR
if (-not $agentsDir) {
    $scriptDir = $PSScriptRoot
    $agentsDir = (Resolve-Path (Join-Path $scriptDir ".." "..")).Path
}

# Resolve task-ref if not provided
if (-not $TaskRef) {
    $refFile = Join-Path $RoomDir "task-ref"
    if (Test-Path $refFile) { $TaskRef = (Get-Content $refFile -Raw).Trim() }
}

$cloneScript = Join-Path $agentsDir "roles" "manager" "Clone-RoleToProject.ps1"
$validateScript = Join-Path $agentsDir "bin" "validate-subcommands.sh"

Write-Host "[REDESIGN] Starting redesign for $RoleName/$SubcommandName in $RoomDir"

# 1. Clone role into overrides
$overrideProjectDir = Join-Path $RoomDir "overrides"
if (-not (Test-Path $overrideProjectDir)) {
    New-Item -ItemType Directory -Path $overrideProjectDir -Force | Out-Null
}

Write-Host "[REDESIGN] Cloning role $RoleName..."
& pwsh -NoProfile -File $cloneScript -RoleName $RoleName -ProjectDir $overrideProjectDir
$overrideRoleDir = Join-Path $overrideProjectDir ".ostwin" "roles" $RoleName

if (-not (Test-Path $overrideRoleDir)) {
    Write-Error "Failed to clone role to $overrideRoleDir"
    exit 1
}

# 2. Spawn engineer agent to fix the subcommand
$subcommandsJsonPath = Join-Path $overrideRoleDir "subcommands.json"
$subcommandsJson = Get-Content $subcommandsJsonPath | ConvertFrom-Json
$subcmd = $subcommandsJson.subcommands | Where-Object { $_.name -eq $SubcommandName }

if (-not $subcmd) {
    Write-Error "Subcommand '$SubcommandName' not found in $subcommandsJsonPath"
    exit 1
}

$entrypoint = $subcmd.entrypoint
$entrypointPath = Join-Path $overrideRoleDir $entrypoint
$sourceCode = if (Test-Path $entrypointPath) { Get-Content $entrypointPath -Raw } else { "# Entrypoint file not found: $entrypoint" }

$prompt = @"
You are fixing a broken subcommand in a role.
Role: $RoleName
Subcommand: $SubcommandName
Error Context: $ErrorContext

Current Entrypoint ($entrypoint):
$sourceCode

Subcommand Manifest Entry:
$($subcmd | ConvertTo-Json)

Please fix the issue in $entrypoint or subcommands.json. Ensure the code is syntactically valid and handles the error.
Target directory: $overrideRoleDir
"@

Write-Host "[REDESIGN] Spawning engineer agent..."
$engineerCmd = "ostwin agent engineer --working-dir ""$overrideRoleDir"" --goal ""$($prompt -replace '"', '\"')"""
# Execute engineer agent
& bash -c "$engineerCmd"

# 3. Validate the fix
Write-Host "[REDESIGN] Validating fix..."
if ($entrypoint -like "*.py") {
    python3 -m py_compile $entrypointPath
    if ($LASTEXITCODE -ne 0) { throw "Python syntax error in $entrypoint" }
} elseif ($entrypoint -like "*.ps1") {
    pwsh -NoProfile -Command "Get-Command -Syntax -File '$entrypointPath'" > $null
    if ($LASTEXITCODE -ne 0) { throw "PowerShell syntax error in $entrypoint" }
}

if (Test-Path $subcommandsJsonPath) {
    & bash $validateScript $subcommandsJsonPath
    if ($LASTEXITCODE -ne 0) { throw "Invalid subcommands.json schema" }
}

# 4. Re-execute the original war-room task
Write-Host "[REDESIGN] Re-executing task with override..."
# Direct channel writes from wrappers are disabled. If this redesign needs to be
# visible in the channel, the responsible agent must post via the ostwin-channel
# MCP post_message tool from inside its session.
Write-Host "[REDESIGN] Done. Channel event suppressed; use MCP post_message from the agent if a channel record is required."

