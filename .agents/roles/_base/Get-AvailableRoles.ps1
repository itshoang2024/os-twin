<#
.SYNOPSIS
    Discovers all available roles from registry + filesystem.
 
.PARAMETER AgentsDir
    Path to the .agents directory.
.PARAMETER WarRoomsDir
    Optional. Path to war-rooms dir for project-level role discovery.
 
.OUTPUTS
    Array of PSCustomObject: Name, Runner, Model, Timeout, Capabilities, Source
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$AgentsDir,
    [string]$WarRoomsDir = ''
)
 
$roles = [System.Collections.Generic.List[PSObject]]::new()
$seen = @{}
 
# --- Source 1: Static registry ---
$registryPath = Join-Path $AgentsDir "roles" "registry.json"
if (Test-Path $registryPath) {
    $registry = Get-Content $registryPath -Raw | ConvertFrom-Json
    foreach ($r in $registry.roles) {
        if ($seen.ContainsKey($r.name)) { continue }
        $seen[$r.name] = $true
        $runnerPath = $null
        if ($r.runner) {
            $runnerRel = $r.runner -replace '/', [System.IO.Path]::DirectorySeparatorChar
            $candidate = Join-Path $AgentsDir $runnerRel
            if (Test-Path $candidate) { $runnerPath = $candidate }
        }
        $roles.Add([PSCustomObject]@{
                Name         = $r.name
                Runner       = $runnerPath
                Model        = if ($r.default_model) { $r.default_model } else { 'google-vertex/gemini-3-flash-preview' }
                Timeout      = if ($r.timeout) { $r.timeout } elseif ($r.timeout_seconds) { $r.timeout_seconds } else { 600 }
                Capabilities = if ($r.capabilities) { @($r.capabilities) } else { @() }
                Source       = 'registry'
            })
    }
}
 
# --- Source 2: Filesystem discovery ---
$searchDirs = @(Join-Path $AgentsDir "roles")
if ($WarRoomsDir) {
    $projectRoles = Join-Path $WarRoomsDir ".." "roles"
    if (Test-Path $projectRoles) { $searchDirs += $projectRoles }
}
# contributes/roles/ — community/dynamic roles
$projectRoot = (Resolve-Path (Join-Path $AgentsDir "..") -ErrorAction SilentlyContinue).Path
if ($projectRoot) {
    $contributesRoles = Join-Path $projectRoot "contributes" "roles"
    if (Test-Path $contributesRoles) { $searchDirs += $contributesRoles }
}

# Also check external_roles_dirs from config
$configPath = Join-Path $AgentsDir "config.json"
if (Test-Path $configPath) {
    $config = Get-Content $configPath -Raw | ConvertFrom-Json
    if ($config.manager.external_roles_dirs) {
        $searchDirs += @($config.manager.external_roles_dirs)
    }
}
 
foreach ($searchDir in $searchDirs) {
    if (-not (Test-Path $searchDir)) { continue }
    Get-ChildItem -Path $searchDir -Directory -ErrorAction SilentlyContinue | ForEach-Object {
        $roleName = $_.Name
        if ($roleName -eq '_base' -or $roleName -eq 'manager') { return }
        if ($seen.ContainsKey($roleName)) { return }
 
        $roleJsonPath = Join-Path $_.FullName "role.json"
        if (-not (Test-Path $roleJsonPath)) { return }
 
        $seen[$roleName] = $true
        $roleJson = Get-Content $roleJsonPath -Raw | ConvertFrom-Json
 
        $runnerPath = Join-Path $_.FullName "Start-$roleName.ps1"
        if (-not (Test-Path $runnerPath)) {
            $runnerPath = Join-Path $AgentsDir "roles" "_base" "Start-DynamicRole.ps1"
        }
 
        $roles.Add([PSCustomObject]@{
                Name         = $roleName
                Runner       = $runnerPath
                Model        = if ($roleJson.model) { $roleJson.model } else { 'google-vertex/gemini-3-flash-preview' }
                Timeout      = if ($roleJson.timeout) { $roleJson.timeout } elseif ($roleJson.timeout_seconds) { $roleJson.timeout_seconds } else { 600 }
                Capabilities = if ($roleJson.capabilities) { @($roleJson.capabilities) } else { @() }
                Source       = 'discovered'
            })
    }
}
 
Write-Output $roles
