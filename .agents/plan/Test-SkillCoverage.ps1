#Requires -Version 7.0

<#
.SYNOPSIS
    Performs pre-flight skill coverage check for a project plan.
    Auto-scaffolds missing dynamic roles so they can run via Start-DynamicRole.ps1.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    $PlanParsed,

    [string]$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path,

    [string]$RoomDir = ""
)

$agentsDir = Join-Path $ProjectDir ".agents"
$config = Get-OstwinConfig
$mode = "warn"
if ($config.manager.preflight_skill_check) {
    $mode = $config.manager.preflight_skill_check
}

if ($mode -eq "off") { return $true }

Write-Host "[PRE-FLIGHT] Checking skill coverage..." -ForegroundColor Cyan

$missingSkills = [System.Collections.Generic.List[string]]::new()
$scaffoldedRoles = [System.Collections.Generic.List[string]]::new()
$rolesDir = Join-Path $agentsDir "roles"
$homeDir = [Environment]::GetFolderPath('UserProfile')
$ostwinRolesDir = Join-Path $homeDir ".ostwin" ".agents" "roles"
$openCodeAgentsDir = Join-Path $homeDir ".config" "opencode" "agents"

# Resolve the Ostwin installation directory (where _base scripts live)
$installDir = $null
if ($env:OSTWIN_HOME -and (Test-Path $env:OSTWIN_HOME)) {
    $installDir = $env:OSTWIN_HOME
}
elseif (Test-Path (Join-Path $agentsDir "roles" "_base" "Start-DynamicRole.ps1")) {
    $installDir = $agentsDir
}
else {
    # Fall back to ~/.ostwin
    $fallback = Join-Path ([Environment]::GetFolderPath('UserProfile')) ".ostwin"
    if (Test-Path $fallback) { $installDir = $fallback }
}

foreach ($entry in $PlanParsed) {
    $entryRoles = @($entry.Roles)
    if ($entryRoles.Count -eq 0) { $entryRoles = @("engineer") }

    foreach ($currentRole in $entryRoles) {
        # Check if role exists in any known location:
        #   1. .agents/roles/<role>/
        #   2. ~/.ostwin/.agents/roles/<role>/
        #   3. ~/.config/opencode/agents/<role>.md
        $rolePath = Join-Path $rolesDir $currentRole
        $roleFound = (Test-Path $rolePath)
        if (-not $roleFound) {
            $ostwinPath = Join-Path $ostwinRolesDir $currentRole
            if (Test-Path $ostwinPath) {
                $rolePath = $ostwinPath
                $roleFound = $true
            }
        }
        if (-not $roleFound) {
            $openCodePath = Join-Path $openCodeAgentsDir "$currentRole.md"
            if (Test-Path $openCodePath) {
                $rolePath = $openCodePath
                $roleFound = $true
            }
        }
        # 4. Check contributes/roles/<role>/ inside the project directory.
        #    Contributed roles are fully defined — do NOT auto-scaffold them.
        if (-not $roleFound) {
            $contributePath = Join-Path $ProjectDir "contributes" "roles" $currentRole
            if (Test-Path $contributePath) {
                $rolePath = $contributePath
                $roleFound = $true
            }
        }
        if (-not $roleFound) {
            # --- Auto-scaffold dynamic role ---
            # Create role at ~/.ostwin/.agents/roles/<role>/ and
            # ~/.config/opencode/agents/<role>.md so it is globally available.
            $scaffolded = $false

            # Extract description from the plan entry
            $roleDesc = if ($entry.Objective) { $entry.Objective }
            elseif ($entry.Description) { $entry.Description }
            else { "$currentRole specialist agent" }

            # 1. Scaffold to ~/.ostwin/.agents/roles/<role>/
            $scaffoldPath = Join-Path $ostwinRolesDir $currentRole
            New-Item -ItemType Directory -Path $scaffoldPath -Force | Out-Null

            # Create role.json
            $roleData = @{
                name          = $currentRole
                description   = $roleDesc
                capabilities  = @()
                prompt_file   = "ROLE.md"
                quality_gates = @()
                skills        = @("global", "roles")
                cli           = "agent"
                model         = "google-vertex/gemini-3-flash-preview"
                timeout       = 600
            }
            $roleData | ConvertTo-Json -Depth 5 | Out-File -FilePath (Join-Path $scaffoldPath "role.json") -Encoding utf8

            # Create ROLE.md
            @"
# $currentRole

You are a **$currentRole** specialist agent.

## Description

$roleDesc

## Guidelines

1. Follow the task brief carefully
2. Write clean, tested code
3. Document your work
4. Report progress and blockers
"@ | Out-File -FilePath (Join-Path $scaffoldPath "ROLE.md") -Encoding utf8

            # 2. Scaffold to ~/.config/opencode/agents/<role>.md
            New-Item -ItemType Directory -Path $openCodeAgentsDir -Force | Out-Null
            $openCodeAgentFile = Join-Path $openCodeAgentsDir "$currentRole.md"
            @"
---
name: $currentRole
description: $roleDesc
model: google-vertex/gemini-3-flash-preview
---

# $currentRole

You are a **$currentRole** specialist agent.

## Description

$roleDesc

## Guidelines

1. Follow the task brief carefully
2. Write clean, tested code
3. Document your work
4. Report progress and blockers
"@ | Out-File -FilePath $openCodeAgentFile -Encoding utf8

            # Register in registry.json if not already there
            $registryPath = Join-Path $rolesDir "registry.json"
            if (Test-Path $registryPath) {
                $registry = Get-Content $registryPath -Raw | ConvertFrom-Json
                $alreadyRegistered = $registry.roles | Where-Object { $_.name -eq $currentRole }
                if (-not $alreadyRegistered) {
                    $newEntry = [PSCustomObject]@{
                        name               = $currentRole
                        description        = $roleDesc
                        runner             = "roles/_base/Start-DynamicRole.ps1"
                        definition         = "roles/$currentRole/role.json"
                        prompt             = "roles/$currentRole/ROLE.md"
                        default_assignment = $false
                        capabilities       = @()
                    }
                    $registry.roles += $newEntry
                    $registry | ConvertTo-Json -Depth 10 | Out-File -FilePath $registryPath -Encoding utf8
                }
            }

            if ($scaffoldedRoles -notcontains $currentRole) {
                $scaffoldedRoles.Add($currentRole)
            }
            $scaffolded = $true
            Write-Host "[PRE-FLIGHT] Auto-scaffolded dynamic role '$currentRole' to ~/.ostwin and ~/.config/opencode for $($entry.TaskRef)" -ForegroundColor Yellow

            if (-not $scaffolded) {
                # Don't spam duplicates if multiple epics miss the same role
                $msg = "Role '$currentRole' not found for $($entry.TaskRef)"
                if ($missingSkills -notcontains $msg) {
                    $missingSkills.Add($msg)
                }
            }
            continue
        }

        # Check if role has required skills (simplified check for now)
        $roleJson = Join-Path $rolePath "role.json"
        if (Test-Path $roleJson) {
            $roleData = Get-Content $roleJson -Raw | ConvertFrom-Json
            if ($roleData.skill_refs) {
                foreach ($skill in $roleData.skill_refs) {
                    # Search hierarchically: skills/<name>, skills/global/<name>, skills/roles/*/<name>
                    $found = $false
                    $searchPaths = @(
                        (Join-Path $agentsDir "skills" $skill),
                        (Join-Path $agentsDir "skills" "global" $skill)
                    )
                    # Search all project-local role skill directories
                    $rolesSkillDir = Join-Path $agentsDir "skills" "roles"
                    if (Test-Path $rolesSkillDir) {
                        Get-ChildItem -Path $rolesSkillDir -Directory -ErrorAction SilentlyContinue | ForEach-Object {
                            $searchPaths += Join-Path $_.FullName $skill
                        }
                    }
                    # Also search the user-global ~/.ostwin/.agents/skills tree so
                    # skills installed once for all projects (for example via the
                    # clawhub installer) are recognised by the pre-flight check.
                    # This must mirror Resolve-RoleSkills.ps1 — keeping the two
                    # search ladders in sync prevents false-positive warnings.
                    $ostwinSkillsDir = Join-Path $homeDir ".ostwin" ".agents" "skills"
                    if (Test-Path $ostwinSkillsDir) {
                        $searchPaths += (Join-Path $ostwinSkillsDir $skill)
                        $searchPaths += (Join-Path $ostwinSkillsDir "global" $skill)
                        $homeRolesSkillDir = Join-Path $ostwinSkillsDir "roles"
                        if (Test-Path $homeRolesSkillDir) {
                            Get-ChildItem -Path $homeRolesSkillDir -Directory -ErrorAction SilentlyContinue | ForEach-Object {
                                $searchPaths += Join-Path $_.FullName $skill
                            }
                        }
                    }
                    foreach ($sp in $searchPaths) {
                        if (Test-Path $sp) { $found = $true; break }
                    }
                    if (-not $found) {
                        $msg = "Skill '$skill' required by role '$currentRole' not found (used in $($entry.TaskRef))"
                        if ($missingSkills -notcontains $msg) {
                            $missingSkills.Add($msg)
                        }
                    }
                }
            }
        }
    }
}

if ($scaffoldedRoles.Count -gt 0) {
    Write-Host "[PRE-FLIGHT] Scaffolded $($scaffoldedRoles.Count) dynamic role(s): $($scaffoldedRoles -join ', ')" -ForegroundColor Green
}

if ($missingSkills.Count -gt 0) {
    $report = "### Skill Coverage Gap Report`n`n"
    foreach ($ms in $missingSkills) {
        Write-Warning "[PRE-FLIGHT] $ms"
        $report += "- [ ] $ms`n"
    }

    # Channel messages are agent-authored via MCP only; wrapper pre-flight does
    # not synthesize channel entries. The report is emitted as warnings/errors.

    if ($mode -eq "halt") {
        Write-Error "Pre-flight skill check failed. Halting execution."
        exit 1
    }
}
else {
    Write-Host "[PRE-FLIGHT] All required skills and roles verified." -ForegroundColor Green
}

return $true
