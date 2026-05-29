<#
.SYNOPSIS
    Universal dynamic role runner — executes any role in a war-room.

.DESCRIPTION
    A role-agnostic version of Start-Engineer.ps1 that derives its identity
    from the war-room config or an explicit $RoleName parameter. Handles PID
    tracking, channel posting, triage context injection, predecessor output
    injection, epic/task handling — all parameterized by role name.

    Used as the default runner for dynamically created roles that don't have
    a custom Start-*.ps1 script.

.PARAMETER RoomDir
    Path to the war-room directory.
.PARAMETER RoleName
    Optional override for the role name. If not provided, reads from
    the war-room config.json assigned_role field.
.PARAMETER TimeoutSeconds
    Override timeout. Default: from config or role.json.

.EXAMPLE
    ./Start-DynamicRole.ps1 -RoomDir "./war-rooms/room-001"
    ./Start-DynamicRole.ps1 -RoomDir "./war-rooms/room-001" -RoleName "security-auditor"
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$RoomDir,

    [string]$RoleName = '',

    [int]$TimeoutSeconds = 0,

    [string]$AgentsDir = '',
    [string]$OverrideInvokeAgent = '',
    [string]$OverridePostMessage = '',
    [string]$OverrideReadMessages = '',
    [string]$OverrideGetRoleDef = '',
    [string]$OverrideBuildSystemPrompt = ''
)

# --- Resolve paths ---
$scriptDir = $PSScriptRoot
if (-not $AgentsDir) {
    $AgentsDir = (Resolve-Path (Join-Path $scriptDir ".." "..")).Path
}
$channelDir = Join-Path $AgentsDir "channel"
$invokeAgent = if ($OverrideInvokeAgent) { $OverrideInvokeAgent } else { Join-Path $AgentsDir "roles" "_base" "Invoke-Agent.ps1" }
$buildSystemPrompt = if ($OverrideBuildSystemPrompt) { $OverrideBuildSystemPrompt } else { Join-Path $AgentsDir "roles" "_base" "Build-SystemPrompt.ps1" }
$getRoleDef = if ($OverrideGetRoleDef) { $OverrideGetRoleDef } else { Join-Path $AgentsDir "roles" "_base" "Get-RoleDefinition.ps1" }
$postMessage = if ($OverridePostMessage) { $OverridePostMessage } else { Join-Path $channelDir "Post-Message.ps1" }
$readMessages = if ($OverrideReadMessages) { $OverrideReadMessages } else { Join-Path $channelDir "Read-Messages.ps1" }

# --- Import logging ---
$logModule = Join-Path $AgentsDir "lib" "Log.psm1"
if (Test-Path $logModule) { Import-Module $logModule -Force }

function Write-Log {
    param([string]$Level, [string]$Message)
    if (Get-Command Write-OstwinLog -ErrorAction SilentlyContinue) {
        Write-OstwinLog -Level $Level -Message $Message
    } else {
        Write-Host "[$Level] $Message"
    }
}

# --- Load room config ---
$roomConfigFile = Join-Path $RoomDir "config.json"
if (-not (Test-Path $roomConfigFile)) {
    Write-Log "ERROR" "config.json not found in war room: $RoomDir"
    exit 1
}
$roomConfig = Get-Content $roomConfigFile -Raw | ConvertFrom-Json

# --- Resolve role identity ---
$assignedRole = if ($RoleName) {
    # Lifecycle-resolved role passed explicitly by manager — takes precedence over stale config.json
    $RoleName
} elseif ($roomConfig.assignment -and $roomConfig.assignment.assigned_role) {
    $roomConfig.assignment.assigned_role
} else { "engineer" }

$baseRole = $assignedRole -replace ':.*$', ''
$instanceSuffix = if ($assignedRole -match ':(.+)$') { $Matches[1] } else { '' }

# --- Override detection (EPIC-006) ---
$overrideDir = Join-Path $RoomDir (Join-Path "overrides" $baseRole)

# Resolve role directory across all search paths
$projectRoot = (Resolve-Path (Join-Path $AgentsDir "..") -ErrorAction SilentlyContinue).Path
$_homeDir = if ($env:HOME) { $env:HOME } else { $env:USERPROFILE }
$_ostwinHome = if ($env:OSTWIN_HOME) { $env:OSTWIN_HOME } else { Join-Path $_homeDir ".ostwin" }

$foundRoleDir = $null
foreach ($candidate in @(
    (Join-Path $AgentsDir "roles" $baseRole),
    (Join-Path $_ostwinHome ".agents" "roles" $baseRole)
)) {
    if (Test-Path $candidate) { $foundRoleDir = $candidate; break }
}
if (-not $foundRoleDir -and $projectRoot) {
    $contributesDir = Join-Path $projectRoot "contributes" "roles" $baseRole
    if (Test-Path $contributesDir) { $foundRoleDir = $contributesDir }
}
if (-not $foundRoleDir) {
    $foundRoleDir = Join-Path $AgentsDir (Join-Path "roles" $baseRole)
}

$roleWorkingDir = if (Test-Path $overrideDir) {
    if ((Test-Path (Join-Path $overrideDir "subcommands.json")) -or (Test-Path (Join-Path $overrideDir "role.json"))) { $overrideDir }
    else { $foundRoleDir }
} else { $foundRoleDir }

$taskRef = if (Test-Path (Join-Path $RoomDir "task-ref")) {
    (Get-Content (Join-Path $RoomDir "task-ref") -Raw).Trim()
} else { "UNKNOWN" }

$roomName = Split-Path $RoomDir -Leaf

Write-Log "INFO" "[$baseRole] Starting dynamic role '$baseRole' on $taskRef in $roomName"

# --- Process Tracking (PID) ---
$pidDir = Join-Path $RoomDir "pids"
if (-not (Test-Path $pidDir)) { New-Item -ItemType Directory -Path $pidDir -Force | Out-Null }
$pidFile = Join-Path $pidDir "$baseRole.pid"
$PID | Out-File -FilePath $pidFile -Encoding utf8 -NoNewline

function Cleanup-And-Exit {
    param([int]$ExitCode, [string]$ErrorMsg = "")
    if ($ErrorMsg) {
        Write-Log "ERROR" "[$baseRole] Error: $ErrorMsg"
        & $postMessage -RoomDir $RoomDir -From $baseRole -To "manager" -Type "error" -Ref $taskRef -Body $ErrorMsg
    }
    # PID file is NOT removed here — manager-owned lifecycle
    exit $ExitCode
}

# --- Load global config ---
$configPath = if ($env:AGENT_OS_CONFIG) { $env:AGENT_OS_CONFIG }
              else { Join-Path $AgentsDir "config.json" }

$config = $null
$maxPromptBytes = 102400
if (Test-Path $configPath) {
    $config = Get-Content $configPath -Raw | ConvertFrom-Json

    # Try role-specific config, then fallback to engineer config, then defaults
    $roleConfig = $null
    if ($config.$baseRole) { $roleConfig = $config.$baseRole }
    elseif ($config.engineer) { $roleConfig = $config.engineer }

    if ($roleConfig) {
        if ($TimeoutSeconds -eq 0 -and $roleConfig.timeout_seconds) {
            $TimeoutSeconds = $roleConfig.timeout_seconds
        }
        if ($roleConfig.max_prompt_bytes) {
            $maxPromptBytes = $roleConfig.max_prompt_bytes
        }
    }
}

# --- Load role definition for model/timeout defaults ---
$roleDef = $null
$rolePath = $roleWorkingDir
if (Test-Path $getRoleDef) {
    if (Test-Path $rolePath) {
        $roleDef = & $getRoleDef -RolePath $rolePath
    } else {
        $roleDef = & $getRoleDef -RoleName $baseRole 2>$null
    }
}

if ($TimeoutSeconds -eq 0) {
    $TimeoutSeconds = if ($roleDef -and $roleDef.Timeout) { $roleDef.Timeout } else { 600 }
}

$agentModel = if ($roleDef -and $roleDef.Model) { $roleDef.Model } else { "google-vertex/gemini-3-flash-preview" }
$agentInstanceType = if ($roleDef -and $roleDef.InstanceType) { $roleDef.InstanceType } else { "worker" }

# --- Resolve instance-specific config ---
$instanceWorkingDir = ''
if ($instanceSuffix -and $config -and $config.$baseRole -and $config.$baseRole.instances.$instanceSuffix) {
    $instanceConfig = $config.$baseRole.instances.$instanceSuffix
    if ($instanceConfig.working_dir) { $instanceWorkingDir = $instanceConfig.working_dir }
    if ($instanceConfig.timeout_seconds -and $TimeoutSeconds -eq $config.$baseRole.timeout_seconds) {
        $TimeoutSeconds = $instanceConfig.timeout_seconds
    }
    if ($instanceConfig.default_model) { $agentModel = $instanceConfig.default_model }
}
# Fallback: read working_dir from room config.json if not resolved from instance config
if (-not $instanceWorkingDir -and $roomConfig -and $roomConfig.working_dir) {
    $instanceWorkingDir = $roomConfig.working_dir
}

# --- Read per-role config file ({role}_{id}.json) ---
$roleInstanceModel = ""
$roleConfigs = Get-ChildItem -Path $RoomDir -Filter "${baseRole}_*.json" -ErrorAction SilentlyContinue | Sort-Object Name -Descending
if ($roleConfigs) {
    $latestRoleConfig = Get-Content $roleConfigs[0].FullName -Raw | ConvertFrom-Json
    if ($latestRoleConfig.model) { $roleInstanceModel = $latestRoleConfig.model }
    # Update status to active
    $latestRoleConfig.status = "active"
    $latestRoleConfig | ConvertTo-Json -Depth 5 | Out-File -FilePath $roleConfigs[0].FullName -Encoding utf8
}

# --- Write per-role context.md ---
$contextsDir = Join-Path $RoomDir "contexts"
if (-not (Test-Path $contextsDir)) {
    New-Item -ItemType Directory -Path $contextsDir -Force | Out-Null
}
$contextFileName = if ($instanceSuffix) { "$baseRole-$instanceSuffix.md" } else { "$baseRole.md" }
$contextFile = Join-Path $contextsDir $contextFileName
$displayName = if ($instanceSuffix -and $config.$baseRole.instances.$instanceSuffix.display_name) {
    $config.$baseRole.instances.$instanceSuffix.display_name
} else { $baseRole }
@"
# $displayName Context

## Assignment
- Task: $taskRef
- Role: $baseRole$(if ($instanceSuffix) { ":$instanceSuffix" } else { "" })
- Working Directory: $(if ($instanceWorkingDir) { $instanceWorkingDir } else { 'project root' })
- Started: $((Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ'))
"@ | Out-File -FilePath $contextFile -Encoding utf8 -Force

# --- Detect Epic vs Task ---
$isEpic = $taskRef -match '^EPIC-'

# --- Read latest task or fix message ---
$latestBody = ""
try {
    $msgs = & $readMessages -RoomDir $RoomDir -Last 1 -AsObject
    if ($msgs) {
        foreach ($m in ($msgs | Sort-Object { $_.ts } -Descending)) {
            if ($m.type -in @('task', 'fix')) {
                $latestBody = $m.body
                break
            }
        }
    }
} catch { }

# --- Read full task description ---
$taskDesc = if (Test-Path (Join-Path $RoomDir "brief.md")) {
    Get-Content (Join-Path $RoomDir "brief.md") -Raw
} else { "No task description found." }

# --- Parse working directories from brief.md ---
$workingDirs = @()
$briefContent = $taskDesc
if ($briefContent -match '(?s)## Working Directories\s*\n(.*?)(?=\n## |\z)') {
    $workingDirs = @(($Matches[1].Trim() -split '\n') |
        ForEach-Object { ($_ -replace '^-\s*', '').Trim() } | Where-Object { $_ })
}
elseif ($briefContent -match 'working_dir:\s*(.+)') {
    $workingDirs = @($Matches[1].Trim())
} elseif ($briefContent -match '## Working Directory\s*\n(.+)') {
    $workingDirs = @($Matches[1].Trim())
}

# --- Build system prompt via Build-SystemPrompt.ps1 ---
$rolePrompt = ""
if (Test-Path $buildSystemPrompt) {
    $promptArgs = @{ RoomDir = $RoomDir }
    if (Test-Path $rolePath) {
        $promptArgs['RolePath'] = $rolePath
    } else {
        $promptArgs['RoleName'] = $baseRole
    }
    $rolePrompt = & $buildSystemPrompt @promptArgs
} else {
    # Fallback: load ROLE.md or SKILL.md directly
    foreach ($promptFile in @("ROLE.md", "SKILL.md")) {
        $promptPath = Join-Path $rolePath $promptFile
        if (Test-Path $promptPath) {
            $rolePrompt = Get-Content $promptPath -Raw
            break
        }
    }
    if (-not $rolePrompt) {
        $rolePrompt = "# $baseRole`n`nYou are a $displayName specialist agent."
    }
}

# --- Build instructions based on Epic vs Task ---
if ($isEpic) {
    $existingTasksFile = Join-Path $RoomDir "TASKS.md"
    $existingTasksMd = if (Test-Path $existingTasksFile) { Get-Content $existingTasksFile -Raw } else { "" }

    if ($existingTasksMd) {
        $instructions = @"
You are continuing work on an EPIC — a previous attempt was made and TASKS.md already exists.

## Existing TASKS.md (from previous attempt)

$existingTasksMd

### Instructions
1. Review the existing TASKS.md above — checked tasks ([x]) were completed previously
2. Focus on unchecked tasks ([ ]) and any issues raised in the QA feedback / fix message
3. Update TASKS.md if fixes require new sub-tasks
4. After completing each sub-task, check it off: - [x] TASK-001 — Description
5. Write tests as you go — each sub-task should be verified before moving on
6. When all tasks are complete, summarize your changes with:
   - Epic overview: what was delivered
   - Sub-tasks completed (include the final TASKS.md checklist)
   - Files modified/created
   - How to test the full epic
"@
    } else {
        $instructions = @"
You are working on an EPIC — a high-level feature that you must plan and implement yourself.

### Phase 1 — Planning
1. Analyze the brief above and break it into concrete sub-tasks
2. Create a file called TASKS.md at: $RoomDir/TASKS.md
   - Use markdown checkboxes: - [ ] TASK-001 — Description
   - Each sub-task should be independently testable
   - Include acceptance criteria for each sub-task
3. Save TASKS.md before proceeding to implementation

### Phase 2 — Implementation
1. Work through each sub-task in TASKS.md sequentially
2. After completing each sub-task, check it off: - [x] TASK-001 — Description
3. Write tests as you go — each sub-task should be verified before moving on

### Phase 3 — Reporting
1. Ensure all checkboxes in TASKS.md are checked
2. Summarize your changes with:
   - Epic overview: what was delivered
   - Sub-tasks completed (include the final TASKS.md checklist)
   - Files modified/created
   - How to test the full epic
"@
    }
} else {
    $instructions = @"
1. Implement the task described above
2. When done, summarize your changes clearly
3. Format your summary with: Changes Made, Files Modified, How to Test
"@
}

# --- Inject predecessor context from DAG ---
$predecessorSection = ""
$dagFile = Join-Path (Split-Path $RoomDir) "DAG.json"
if (Test-Path $dagFile) {
    $dag = Get-Content $dagFile -Raw | ConvertFrom-Json
    $myNode = $dag.nodes.$taskRef
    if ($myNode -and $myNode.depends_on -and $myNode.depends_on.Count -gt 0) {
        $sections = @()
        foreach ($depRef in $myNode.depends_on) {
            $depNode = $dag.nodes.$depRef
            if (-not $depNode) { continue }
            $depRoomDir = Join-Path (Split-Path $RoomDir) $depNode.room_id
            try {
                $doneMsgs = & $readMessages -RoomDir $depRoomDir -FilterType "done" -Last 1 -AsObject
                if ($doneMsgs -and $doneMsgs.Count -gt 0) {
                    $body = $doneMsgs[-1].body
                    if ($body.Length -gt 10240) { $body = $body.Substring(0, 10240) + "`n[TRUNCATED]" }
                    $sections += "### $depRef`n$body"
                }
            } catch { }
        }
        if ($sections.Count -gt 0) {
            $predecessorSection = "`n`n## Predecessor Outputs`n`n$($sections -join "`n`n")"
        }
    }
}

# --- Read triage context if available ---
$triageSection = ""
$triageFile = Join-Path $RoomDir "artifacts" "triage-context.md"
if (Test-Path $triageFile) {
    $triageContent = Get-Content $triageFile -Raw
    $triageSection = @"

## Triage Context (Manager Analysis)

$triageContent
"@
}

# --- Assemble final prompt ---
$evaluatorInstruction = if ($agentInstanceType -eq 'evaluator') {
@"

## Evaluator Output Requirement

IMPORTANT: Your response MUST include exactly one of these lines to indicate your final decision:
  VERDICT: DONE (approves and entirely finishes the workflow)
  VERDICT: FAIL
  VERDICT: ESCALATE
"@
} else { "" }

$prompt = @"
$rolePrompt

---

## Latest Instruction

$latestBody
$triageSection
## War-Room

Room: $roomName
Task Ref: $taskRef
Role: $baseRole
Working Directory: $(if ($workingDirs.Count -gt 0) { $workingDirs -join ', ' } else { Get-Location })
$predecessorSection
## Instructions

$instructions
$evaluatorInstruction
"@

# --- Prompt size guard ---
if ($prompt.Length -gt $maxPromptBytes) {
    $originalSize = $prompt.Length
    $prompt = $prompt.Substring(0, $maxPromptBytes) + @"

[TRUNCATED: prompt was $originalSize bytes, max is $maxPromptBytes. Full task description in: $RoomDir/brief.md]
"@
    Write-Log "WARN" "[$baseRole] Prompt truncated from $originalSize to $maxPromptBytes bytes for $taskRef"
}

# --- Run the agent ---
$invokeArgs = @{
    RoomDir        = $RoomDir
    RoleName       = $baseRole
    Prompt         = $prompt
    TimeoutSeconds = $TimeoutSeconds
}

if ($instanceSuffix) { $invokeArgs['InstanceId'] = $instanceSuffix }
if ($instanceWorkingDir) { $invokeArgs['WorkingDir'] = $instanceWorkingDir }
# Model resolution: only pass explicit per-room instance model overrides.
# Do NOT pass the fallback $agentModel (from role.json / config.json) — let
# Invoke-Agent.ps1 resolve from plan.roles.json → config.json → role.json → default.
# This ensures the user's plan-level model configuration is respected.
if ($roleInstanceModel) { $invokeArgs['Model'] = $roleInstanceModel }

$result = & $invokeAgent @invokeArgs

# --- Post result to channel ---
if ($result.ExitCode -eq 0) {
    if ($agentInstanceType -eq 'evaluator') {
        # Parse verdict
        $verdict = "FAIL" # Default if not found
        if ($result.Output -match '(?m)^VERDICT:\s*(PASS|FAIL|ESCALATE|DONE)') {
            $verdict = $Matches[1].ToUpper()
        } elseif ($result.Output -match 'VERDICT:\s*(PASS|FAIL|ESCALATE|DONE)') {
            $verdict = $Matches[1].ToUpper()
        }
        $finalVerdict = $verdict
        $postType = $verdict.ToLower()
        
        # Strip noise
        $cleanLines = ($result.Output -split "`n") | Where-Object {
            $line = $_.Trim()
            if (-not $line -or $line.Length -lt 4) { return $false }
            -not ($line -match '^🔧' -or $line -match '[Cc]alling tool:' -or $line -match '^Loading MCP' -or $line -match '^Running task non-interactively' -or $line -match '^Agent active' -or $line -match '^Usage Stats' -or $line -match '^\s*Reqs\s+InputTok' -or $line -match '^✓ Task completed' -or $line -match '^System\.Management\.Automation')
        }
        $cleanOutput = ($cleanLines -join "`n").Trim()
        if (-not $cleanOutput) { $cleanOutput = $result.Output }
        
        & $postMessage -RoomDir $RoomDir -From $baseRole -To "manager" `
                       -Type $postType -Ref $taskRef -Body $cleanOutput
        Write-Log "INFO" "[$baseRole] Evaluator finished $taskRef with verdict $verdict."
    } else {
        & $postMessage -RoomDir $RoomDir -From $baseRole -To "manager" `
                       -Type "done" -Ref $taskRef -Body $result.Output
        Write-Log "INFO" "[$baseRole] Completed $taskRef successfully."
    }
}
elseif ($result.TimedOut) {
    & $postMessage -RoomDir $RoomDir -From $baseRole -To "manager" `
                   -Type "error" -Ref $taskRef -Body "$baseRole timed out after ${TimeoutSeconds}s"
    Write-Log "ERROR" "[$baseRole] Timed out on $taskRef after ${TimeoutSeconds}s."
}
else {
    & $postMessage -RoomDir $RoomDir -From $baseRole -To "manager" `
                   -Type "error" -Ref $taskRef `
                   -Body "$baseRole exited with code $($result.ExitCode): $($result.Output)"
    Write-Log "ERROR" "[$baseRole] Failed on $taskRef with exit code $($result.ExitCode)."
}

# --- Update per-role config status ---
if ($roleConfigs) {
    $latestRoleConfig = Get-Content $roleConfigs[0].FullName -Raw | ConvertFrom-Json
    $latestRoleConfig.status = if ($result.ExitCode -eq 0) { "completed" } else { "failed" }
    $latestRoleConfig | ConvertTo-Json -Depth 5 | Out-File -FilePath $roleConfigs[0].FullName -Encoding utf8
}

# --- PID file is NOT removed here (manager-owned lifecycle) ---
# The manager cleans up PID files when it processes the signal and transitions
# the room state. Removing PID here causes a race: manager polls, finds no PID,
# and re-spawns before processing the channel signal.

exit $result.ExitCode
