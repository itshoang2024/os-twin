<#
.SYNOPSIS
    Resolves a role name (or capability list) to a runner script path and metadata.
 
.PARAMETER RoleName
    The role to resolve. Can include instance suffix (e.g., "engineer:fe").
.PARAMETER RequiredCapabilities
    Optional. Array of capabilities needed. Used for capability-based matching
    when RoleName is empty or not found.
.PARAMETER AgentsDir
    Path to the .agents directory.
.PARAMETER WarRoomsDir
    Path to the war-rooms directory (for project-level role discovery).
 
.OUTPUTS
    PSCustomObject with: Name, BaseRole, Runner, Model, Timeout, Capabilities, Source
    Source is one of: "registry", "discovered", "capability-match", "ephemeral"
#>
[CmdletBinding()]
param(
    [string]$RoleName = '',
    [string[]]$RequiredCapabilities = @(),
    [Parameter(Mandatory)]
    [string]$AgentsDir,
    [string]$WarRoomsDir = '',
    [string]$RolePath = '',
    [array]$AvailableRoles = $null
)
 
# Strip leading @ (markdown role notation) before any processing
$RoleName = $RoleName -replace '^@', ''

$baseRole = $RoleName -replace ':.*$', ''
$instanceSuffix = if ($RoleName -match ':(.+)$') { $Matches[1] } else { '' }
 
$result = [PSCustomObject]@{
    Name         = $RoleName
    BaseRole     = $baseRole
    Runner       = $null
    Model        = 'google-vertex/gemini-3-flash-preview'
    Timeout      = 600
    Capabilities = @()
    Source       = 'ephemeral'
}
 
# --- Tier 0: Explicit RolePath override (EPIC-006) ---
if ($RolePath -and (Test-Path $RolePath)) {
    if (Test-Path (Join-Path $RolePath "role.json")) {
        $roleJson = Get-Content (Join-Path $RolePath "role.json") -Raw | ConvertFrom-Json
        $result.Capabilities = if ($roleJson.capabilities) { @($roleJson.capabilities) } else { @() }
        if ($roleJson.model) { $result.Model = $roleJson.model }
        $t = if ($roleJson.timeout) { $roleJson.timeout } elseif ($roleJson.timeout_seconds) { $roleJson.timeout_seconds } else { $null }
        if ($t) { $result.Timeout = $t }
    }
    
    $customRunner = Join-Path $RolePath "Start-$baseRole.ps1"
    if (Test-Path $customRunner) {
        $result.Runner = $customRunner
    }
    else {
        $result.Runner = Join-Path $AgentsDir "roles" "_base" "Start-DynamicRole.ps1"
    }
    $result.Source = 'override'
    return $result
}
 
# --- Tier 1 & 2 Fast Path: Use AvailableRoles cache if provided ---
if ($AvailableRoles) {
    $matched = $AvailableRoles | Where-Object { $_.Name -eq $baseRole } | Select-Object -First 1
    if ($matched -and $matched.Runner) {
        $result.Runner = $matched.Runner
        $result.Source = $matched.Source
        if ($matched.Capabilities) { $result.Capabilities = @($matched.Capabilities) }
        if ($matched.Model) { $result.Model = $matched.Model }
        if ($matched.Timeout) { $result.Timeout = $matched.Timeout }
    }
}

if (-not $result.Runner) {
    # --- Tier 1: Static registry match ---
    $registryPath = Join-Path $AgentsDir "roles" "registry.json"
    if ($baseRole -and (Test-Path $registryPath)) {
        $registry = Get-Content $registryPath -Raw | ConvertFrom-Json
        $matchedRole = $registry.roles | Where-Object { $_.name -eq $baseRole }
        if ($matchedRole -and $matchedRole.runner) {
            $runnerRel = $matchedRole.runner -replace '/', [System.IO.Path]::DirectorySeparatorChar
            $runnerPath = Join-Path $AgentsDir $runnerRel
            if (Test-Path $runnerPath) {
                $result.Runner = $runnerPath
                $result.Source = 'registry'
                $result.Capabilities = if ($matchedRole.capabilities) { @($matchedRole.capabilities) } else { @() }
                if ($matchedRole.default_model) { $result.Model = $matchedRole.default_model }
                $registryTimeout = if ($matchedRole.timeout) { $matchedRole.timeout } elseif ($matchedRole.timeout_seconds) { $matchedRole.timeout_seconds } else { $null }
                if ($registryTimeout) { $result.Timeout = $registryTimeout }
            }
        }
    }
     
    # --- Tier 2: Dynamic directory discovery ---
    if (-not $result.Runner -and $baseRole) {
        $searchDirs = @()
        if ($WarRoomsDir) {
            $searchDirs += Join-Path $WarRoomsDir ".." "roles" $baseRole
        }
        # contributes/roles/ — community/dynamic roles directory
        $projectRoot = (Resolve-Path (Join-Path $AgentsDir "..") -ErrorAction SilentlyContinue).Path
        if ($projectRoot) {
            $contributesDir = Join-Path $projectRoot "contributes" "roles" $baseRole
            if (Test-Path $contributesDir) { $searchDirs += $contributesDir }
        }
        $searchDirs += Join-Path $AgentsDir "roles" $baseRole
        # ~/.ostwin/.agents/roles/ — auto-scaffolded and globally installed roles
        $OstwinHome = if ($env:OSTWIN_HOME) { $env:OSTWIN_HOME } else { Join-Path ([Environment]::GetFolderPath('UserProfile')) ".ostwin" }
        $ostwinRoleDir = Join-Path $OstwinHome ".agents" "roles" $baseRole
        if (Test-Path $ostwinRoleDir) { $searchDirs += $ostwinRoleDir }
     
        foreach ($dir in $searchDirs) {
            if (Test-Path (Join-Path $dir "role.json")) {
                $roleJson = Get-Content (Join-Path $dir "role.json") -Raw | ConvertFrom-Json
                $result.Capabilities = if ($roleJson.capabilities) { @($roleJson.capabilities) } else { @() }
                if ($roleJson.model) { $result.Model = $roleJson.model }
                $t = if ($roleJson.timeout) { $roleJson.timeout } elseif ($roleJson.timeout_seconds) { $roleJson.timeout_seconds } else { $null }
        if ($t) { $result.Timeout = $t }
     
                # Check for custom runner script
                $customRunner = Join-Path $dir "Start-$baseRole.ps1"
                if (Test-Path $customRunner) {
                    $result.Runner = $customRunner
                }
                else {
                    # Use universal dynamic runner as fallback for discovered roles
                    $result.Runner = Join-Path $AgentsDir "roles" "_base" "Start-DynamicRole.ps1"
                }
                $result.Source = 'discovered'
                break
            }
        }
    }
}
 
# --- Tier 3: Capability-based matching ---
if (-not $result.Runner -and $RequiredCapabilities.Count -gt 0) {
    $allRoles = if ($AvailableRoles) {
        $AvailableRoles
    }
    else {
        $getAvailable = Join-Path $AgentsDir "roles" "_base" "Get-AvailableRoles.ps1"
        if (Test-Path $getAvailable) {
            & $getAvailable -AgentsDir $AgentsDir -WarRoomsDir $WarRoomsDir
        }
        else { @() }
    }
    
    if ($allRoles) {
        $bestScore = 0
        $bestMatch = $null
        foreach ($candidate in $allRoles) {
            if (-not $candidate.Capabilities) { continue }
            $overlap = ($RequiredCapabilities | Where-Object { $candidate.Capabilities -contains $_ }).Count
            if ($overlap -gt $bestScore) {
                $bestScore = $overlap
                $bestMatch = $candidate
            }
        }
        if ($bestMatch -and $bestScore -gt 0) {
            $result.Runner = $bestMatch.Runner
            if ($bestMatch.Capabilities) { $result.Capabilities = @($bestMatch.Capabilities) }
            if ($bestMatch.Model) { $result.Model = $bestMatch.Model }
            if ($bestMatch.Timeout) { $result.Timeout = $bestMatch.Timeout }
            $result.BaseRole = $bestMatch.Name
            $result.Source = 'capability-match'
        }
    }
}
 
# --- Tier 4: Ephemeral agent fallback ---
if (-not $result.Runner) {
    $result.Runner = Join-Path $AgentsDir "roles" "_base" "Start-EphemeralAgent.ps1"
    $result.Source = 'ephemeral'
}
 
Write-Output $result
