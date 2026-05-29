# ──────────────────────────────────────────────────────────────────────────────
# Sync-ContributedAgents.ps1 — Sync project role definitions to OpenCode agents
#
# Copies ROLE.md from each role directory in the project into the OpenCode
# agents folder so `opencode run --agent <role>` can discover them.
#
# Sources (in priority order — later overwrites earlier):
#   1. <ProjectDir>/.agents/roles/<role>/ROLE.md   — built-in/global roles
#   2. <ProjectDir>/contributes/roles/<role>/ROLE.md — project-local contributed
#
# Contributed roles (contributes/roles/) take precedence over built-in roles of
# the same name because they're written last, matching installer sync behavior.
#
# RULES:
#   - Skip _base directories (infrastructure, not a role)
#   - Requires role.json in the role directory (marks it as a valid role)
#   - Safe to call multiple times (idempotent)
#   - Does NOT auto-scaffold generic ROLE.md content — copies what exists only
#
# Parameters:
#   ProjectDir    Root of the project (contains .agents/ and contributes/)
#   AgentsDir     Override for destination directory (default: ~/.config/opencode/agents)
# ──────────────────────────────────────────────────────────────────────────────

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectDir,

    [string]$AgentsDir = ""
)

# ─── Resolve destination directory ───────────────────────────────────────────

if (-not $AgentsDir) {
    $opencodeHome = if ($env:XDG_CONFIG_HOME) {
        Join-Path $env:XDG_CONFIG_HOME "opencode"
    } elseif ($env:USERPROFILE) {
        Join-Path $env:USERPROFILE ".config" "opencode"
    } else {
        Join-Path $HOME ".config" "opencode"
    }
    $AgentsDir = Join-Path $opencodeHome "agents"
}

if (-not (Test-Path $AgentsDir)) {
    New-Item -ItemType Directory -Path $AgentsDir -Force | Out-Null
}

# ─── Role source directories ──────────────────────────────────────────────────
# Process built-in roles first, then contributed roles (contributed wins on conflict).

$rolesDirs = @(
    (Join-Path $ProjectDir ".agents"     "roles"),
    (Join-Path $ProjectDir "contributes" "roles")
)

$synced  = 0
$skipped = 0

foreach ($rolesDir in $rolesDirs) {
    if (-not (Test-Path $rolesDir)) { continue }

    Get-ChildItem -Path $rolesDir -Directory -ErrorAction SilentlyContinue | ForEach-Object {
        $roleName = $_.Name

        # Skip _base (infrastructure scripts, not a role)
        if ($roleName -eq "_base") { $skipped++; return }

        # Must have role.json to be a valid role entry
        $roleJson = Join-Path $_.FullName "role.json"
        if (-not (Test-Path $roleJson)) { $skipped++; return }

        # Copy ROLE.md as <role-name>.md into the agents directory
        $roleMd = Join-Path $_.FullName "ROLE.md"
        if (Test-Path $roleMd) {
            Copy-Item -Path $roleMd -Destination (Join-Path $AgentsDir "${roleName}.md") -Force
            $synced++
        } else {
            $skipped++
        }
    }
}

Write-Host "  -> Synced $synced agent definition(s) to $AgentsDir ($skipped skipped)"
