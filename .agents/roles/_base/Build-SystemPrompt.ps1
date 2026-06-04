<#
.SYNOPSIS
    Composes a full system prompt from role definition, skills, and war-room context.

.DESCRIPTION
    Reads a role definition (via Get-RoleDefinition), loads the ROLE.md prompt template,
    injects skill context files, war-room goals, and task context to produce
    a complete system prompt ready for the agent.

    Part of Epic 4 — Extensible Role Engine.

.PARAMETER RoleName
    Role name (engineer, qa, architect, etc.).
.PARAMETER RolePath
    Direct path to role directory (overrides RoleName).
.PARAMETER RoomDir
    Optional. War-room directory for context injection.
.PARAMETER TaskRef
    Optional. Task/Epic reference for context.
.PARAMETER TaskBody
    Optional. Latest task/fix body text.
.PARAMETER ExtraContext
    Optional. Additional context to append.

.OUTPUTS
    [string] The fully composed system prompt.

.EXAMPLE
    $prompt = ./Build-SystemPrompt.ps1 -RoleName "engineer" -RoomDir "./war-rooms/room-001"
#>
[CmdletBinding()]
param(
    [string]$RoleName = '',
    [string]$RolePath = '',
    [string]$RoomDir = '',
    [string]$TaskRef = '',
    [string]$TaskBody = '',
    [string]$ExtraContext = ''
)

$getRoleDef = Join-Path $PSScriptRoot "Get-RoleDefinition.ps1"

# --- Load role definition ---
$roleArgs = @{}
if ($RolePath) { $roleArgs['RolePath'] = $RolePath }
elseif ($RoleName) { $roleArgs['RoleName'] = $RoleName }
else {
    Write-Error "Either -RoleName or -RolePath must be specified."
    exit 1
}

$role = & $getRoleDef @roleArgs

# --- Start building the prompt ---
$sections = [System.Collections.Generic.List[string]]::new()

# Section 1: Role prompt template
if ($role.PromptTemplate) {
    $sections.Add($role.PromptTemplate)
}
else {
    $sections.Add("# $($role.Name)`n`nYou are a $($role.Description).")
}

# Section 2: Capabilities
if ($role.Capabilities -and $role.Capabilities.Count -gt 0) {
    $capList = ($role.Capabilities | ForEach-Object { "- $_" }) -join "`n"
    $sections.Add(@"

## Your Capabilities

$capList
"@)
}

# Section 3: Quality gates
if ($role.QualityGates -and $role.QualityGates.Count -gt 0) {
    $gateList = ($role.QualityGates | ForEach-Object { "- $_" }) -join "`n"
    $sections.Add(@"

## Quality Gates

You must satisfy these quality gates before marking work as done:

$gateList
"@)
}

# Section 4: Skills — resolved at runtime by Invoke-Agent.ps1
# Skills are NOT compiled into the prompt. Instead, Invoke-Agent.ps1 calls
# Resolve-RoleSkills.ps1, copies skill directories into $RoomDir/skills/,
# and sets AGENT_OS_SKILLS_DIR for the agent CLI to discover them at runtime.
# This keeps the system prompt lean and avoids duplicating skill content.
$agentsDir = Split-Path (Split-Path $PSScriptRoot)

# Section 4b: Workspace boundary rules
$sections.Add(@"

## Workspace Boundaries (MANDATORY)

You MUST follow these rules when exploring the filesystem:

1. **NEVER list or read files inside `.war-rooms/`** — these are infrastructure
   directories for the orchestration system, not project source code.
   The only exceptions are files explicitly referenced in your prompt
   (e.g. brief.md, TASKS.md, channel.jsonl).
2. **NEVER list or read files inside `.agents/`** — these are system configuration
   files. Use the ``memory`` MCP tools instead to discover what other agents built.
3. **NEVER traverse above your working directory** — do not ``ls ..``, ``ls ../..``,
   or ``find`` in parent directories. Your scope is the project working directory only.
4. **NEVER use ``ls -R`` or ``ls -Ra`` on the project root** — this dumps hundreds
   of infrastructure files and wastes your context window. Instead, list only the
   specific directories you need (e.g. ``ls src/``, ``ls app/``).
5. **Assets**: If the brief references image or data files, their locations are
   specified in the brief. Do not search the entire filesystem for them.
6. **Focus on project source code only**: ``src/``, ``app/``, ``lib/``, ``public/``,
   ``pages/``, ``components/``, ``prisma/``, ``package.json``, ``tsconfig.json``,
   and similar project files.
"@)

# Section 4c: Scoped Working Directories
if ($RoomDir -and (Test-Path $RoomDir)) {
    $roomConfigFile = Join-Path $RoomDir "config.json"
    if (Test-Path $roomConfigFile) {
        try {
            $roomCfg = Get-Content $roomConfigFile -Raw | ConvertFrom-Json
            $scopedDir = ''
            if ($roomCfg.PSObject.Properties['working_dir'] -and $roomCfg.working_dir) {
                $scopedDir = $roomCfg.working_dir
            }
            if ($scopedDir) {
                $sections.Add(@"

## Scoped Working Directory

Your work is scoped to the following directory. Focus all file exploration,
code changes, and testing within this path:

- ``$scopedDir``

Do NOT modify files outside this directory unless explicitly required by
a dependency (e.g. a shared config file referenced from your scoped directory).
"@)
            }
        } catch { }
    }
}

# Section 5: War-room context
if ($RoomDir -and (Test-Path $RoomDir)) {
    # Task brief
    $briefFile = Join-Path $RoomDir "brief.md"
    if (Test-Path $briefFile) {
        $briefContent = Get-Content $briefFile -Raw
        $sections.Add(@"

---

## Task Assignment

$briefContent
"@)
    }

    # TASKS.md for epics
    $tasksFile = Join-Path $RoomDir "TASKS.md"
    if (Test-Path $tasksFile) {
        $tasksContent = Get-Content $tasksFile -Raw
        $sections.Add(@"

## Sub-Tasks (TASKS.md)

$tasksContent
"@)
    }

}

# Section 6: Overrides
if ($TaskRef) {
    $sections.Add("`n## Task Reference: $TaskRef")
}

if ($TaskBody) {
    $sections.Add(@"

## Current Instruction

$TaskBody
"@)
}

if ($ExtraContext) {
    $sections.Add(@"

## Additional Context

$ExtraContext
"@)
}

# --- Compose final prompt ---
$finalPrompt = $sections -join "`n"

# --- Token Size Warning ---
$maxBytes = 102400 # Default fallback
try {
    $configPath = if ($env:AGENT_OS_CONFIG) { $env:AGENT_OS_CONFIG } else { Join-Path (Split-Path (Split-Path $PSScriptRoot)) "config.json" }
    if (Test-Path $configPath) {
        $fullConfig = Get-Content $configPath -Raw | ConvertFrom-Json
        $roleNameLower = $role.Name.ToLower()
        if ($fullConfig.$roleNameLower.max_prompt_bytes) {
            $maxBytes = $fullConfig.$roleNameLower.max_prompt_bytes
        }
    }
} catch {}

$promptSize = [System.Text.Encoding]::UTF8.GetByteCount($finalPrompt)
if ($promptSize -gt $maxBytes) {
    Write-Warning "System prompt size ($promptSize bytes) exceeds threshold ($maxBytes bytes) for role '$($role.Name)'."
}

Write-Output $finalPrompt
