<#
.SYNOPSIS
    Engineer role runner — reads task from war-room and executes via deepagents.

.DESCRIPTION
    Reads the task brief and latest instruction from the war-room channel,
    builds a role-specific prompt, runs the agent via Invoke-Agent.ps1,
    and posts the result (done/error) back to the channel.

    Replaces: roles/engineer/run.sh

.PARAMETER RoomDir
    Path to the war-room directory.
.PARAMETER TimeoutSeconds
    Override timeout. Default: from config.

.EXAMPLE
    ./Start-Engineer.ps1 -RoomDir "./war-rooms/room-001"
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$RoomDir,

    [int]$TimeoutSeconds = 0,

    # Accepted but unused — passed by Start-WorkerJob for generic role dispatch
    [string]$RoleName = ''
)

# --- Resolve paths ---
$scriptDir = $PSScriptRoot
$agentsDir = (Resolve-Path (Join-Path $scriptDir ".." "..")).Path
$channelDir = Join-Path $agentsDir "channel"
$invokeAgent = Join-Path $agentsDir "roles" "_base" "Invoke-Agent.ps1"
$readMessages = Join-Path $channelDir "Read-Messages.ps1"

# --- Import logging ---
$logModule = Join-Path $agentsDir "lib" "Log.psm1"
if (Test-Path $logModule) { Import-Module $logModule -Force }
$lifecycleSignalModule = Join-Path $agentsDir "roles" "_base" "LifecycleSignal.psm1"
if (Test-Path $lifecycleSignalModule) { Import-Module $lifecycleSignalModule -Force }

function Get-LastChannelItemBody {
    param([Parameter(Mandatory)][string]$RoomDir)

    $channelPath = Join-Path $RoomDir "channel.jsonl"
    if (-not (Test-Path $channelPath)) { return $null }

    $lastLine = $null
    try {
        foreach ($line in [System.IO.File]::ReadLines($channelPath)) {
            if (-not [string]::IsNullOrWhiteSpace($line)) {
                $lastLine = $line.TrimEnd()
            }
        }
    }
    catch { return $null }

    if (-not $lastLine) { return $null }

    try {
        $lastItem = $lastLine | ConvertFrom-Json
        if ($lastItem.PSObject.Properties.Name -contains 'body') {
            return [string]$lastItem.body
        }
    }
    catch { }

    return $null
}

# --- Load config ---
$configPath = if ($env:AGENT_OS_CONFIG) { $env:AGENT_OS_CONFIG }
              else { Join-Path $agentsDir "config.json" }

$config = $null
$maxPromptBytes = 102400
$InstanceId = ""
if (Test-Path $configPath) {
    $config = Get-Content $configPath -Raw | ConvertFrom-Json
    if ($TimeoutSeconds -eq 0) {
        $TimeoutSeconds = $config.engineer.timeout_seconds
    }
    if ($config.engineer.max_prompt_bytes) {
        $maxPromptBytes = $config.engineer.max_prompt_bytes
    }
}
if ($TimeoutSeconds -eq 0) { $TimeoutSeconds = 600 }

# --- Parse instance from war-room config ---
$roomConfigFile = Join-Path $RoomDir "config.json"
if (Test-Path $roomConfigFile) {
    $roomConfig = Get-Content $roomConfigFile -Raw | ConvertFrom-Json
    $assignedRole = $roomConfig.assignment.assigned_role
    if ($assignedRole -match '^engineer:(.+)$') {
        $InstanceId = $Matches[1]
    }
}

# --- Mark per-role config (engineer_{id}.json) as active ---
# Model resolution lives in Invoke-Agent.ps1 (reads from plan roles.json).
# This block exists only to flip status → active and to keep $engineerConfigs
# around so the post-run block at the bottom can flip status → completed/failed.
$engineerConfigs = Get-ChildItem -Path $RoomDir -Filter "engineer_*.json" -ErrorAction SilentlyContinue | Sort-Object Name -Descending
if ($engineerConfigs) {
    $latestRoleConfig = Get-Content $engineerConfigs[0].FullName -Raw | ConvertFrom-Json
    $latestRoleConfig.status = "active"
    $latestRoleConfig | ConvertTo-Json -Depth 5 | Out-File -FilePath $engineerConfigs[0].FullName -Encoding utf8
}

# --- Resolve instance-specific working directory ---
$instanceWorkingDir = ''
if ($InstanceId -and $config -and $config.engineer.instances.$InstanceId) {
    $instanceConfig = $config.engineer.instances.$InstanceId
    if ($instanceConfig.working_dir) {
        $instanceWorkingDir = $instanceConfig.working_dir
    }
    if ($instanceConfig.timeout_seconds -and $TimeoutSeconds -eq $config.engineer.timeout_seconds) {
        $TimeoutSeconds = $instanceConfig.timeout_seconds
    }
}
# Fallback: read working_dir from room config.json if not resolved from instance config
if (-not $instanceWorkingDir -and $roomConfig -and $roomConfig.working_dir) {
    $instanceWorkingDir = $roomConfig.working_dir
}

# --- Write per-role context.md ---
$contextsDir = Join-Path $RoomDir "contexts"
if (-not (Test-Path $contextsDir)) {
    New-Item -ItemType Directory -Path $contextsDir -Force | Out-Null
}
$contextFileName = if ($InstanceId) { "engineer-$InstanceId.md" } else { "engineer.md" }
$contextFile = Join-Path $contextsDir $contextFileName
$instanceDisplayName = if ($InstanceId -and $config.engineer.instances.$InstanceId.display_name) {
    $config.engineer.instances.$InstanceId.display_name
} else { "Engineer" }
$contextContent = @"
# $instanceDisplayName Context

## Assignment
- Task: $taskRef (resolving below)
- Instance: $(if ($InstanceId) { $InstanceId } else { 'default' })
- Working Directory: $(if ($instanceWorkingDir) { $instanceWorkingDir } else { 'project root' })
- Started: $((Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ'))
"@

# --- Read task ref ---
$taskRef = if (Test-Path (Join-Path $RoomDir "task-ref")) {
    (Get-Content (Join-Path $RoomDir "task-ref") -Raw).Trim()
} else { "UNKNOWN" }

# --- Finalize context.md with task ref ---
$contextContent = $contextContent -replace '\$taskRef \(resolving below\)', $taskRef
$contextContent | Out-File -FilePath $contextFile -Encoding utf8 -Force

# --- Detect Epic vs Task ---
$isEpic = $taskRef -match '^EPIC-'

# --- Read latest task or fix message ---
$latestBody = ""
try {
    $msgs = & $readMessages -RoomDir $RoomDir -FilterType @('task', 'fix') -Last 1 -AsObject
    if ($msgs -and $msgs.Count -gt 0) {
        $latestBody = $msgs[-1].body
    }
}
catch { }

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
}
elseif ($briefContent -match '## Working Directory\s*\n(.+)') {
    $workingDirs = @($Matches[1].Trim())
}

# Note: ROLE.md is loaded by Build-SystemPrompt.ps1 via Get-RoleDefinition.
# Skills are loaded by Invoke-Agent.ps1 via AGENT_OS_SKILLS_DIR.
# No manual reads needed here.

# --- Build instructions based on Epic vs Task ---
$roomName = Split-Path $RoomDir -Leaf

# --- Build role-specific workflow instructions ---
# Note: brief.md and role context are injected by Build-SystemPrompt.ps1.
# Invoke-Agent.ps1 appends the latest channel effort and TASKS.md after this prompt.
# Here we only provide workflow instructions specific to Epic vs Task.
$existingTasksFile = Join-Path $RoomDir "TASKS.md"
$hasExistingTasks = Test-Path $existingTasksFile

if ($isEpic) {
    if ($hasExistingTasks) {
        # Fix cycle: TASKS.md already exists from a previous attempt
        $instructions = @"
You are continuing work on an EPIC — TASKS.md already exists and is included at the end of this prompt.

1. Review the TASKS.md section at the end of this prompt — checked tasks ([x]) were completed previously
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
    }
    else {
        # First attempt: create TASKS.md from scratch
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
}
else {
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
            if ($depRef -eq 'PLAN-REVIEW') { continue }
            $depNode = $dag.nodes.$depRef
            if (-not $depNode) { continue }
            $depRoomDir = Join-Path (Split-Path $RoomDir) $depNode.room_id
            $lastBody = Get-LastChannelItemBody -RoomDir $depRoomDir
            if ($lastBody) {
                if ($lastBody.Length -gt 10240) { $lastBody = $lastBody.Substring(0, 10240) + "`n[TRUNCATED]" }
                $sections += "### $depRef`n$lastBody"
            }
        }
        if ($sections.Count -gt 0) {
            $predecessorSection = "`n`n## Predecessor Outputs`n`n$($sections -join "`n`n")"
        }
    }
}

# --- Read triage context if available (from manager triage) ---
$triageContext = ""
$triageFile = Join-Path $RoomDir "artifacts" "triage-context.md"
if (Test-Path $triageFile) {
    $triageContext = Get-Content $triageFile -Raw
}

# --- Assemble final prompt using Build-SystemPrompt.ps1 ---
$buildPrompt = Join-Path $agentsDir "roles" "_base" "Build-SystemPrompt.ps1"
$extraContext = $instructions
if ($predecessorSection) {
    $extraContext += $predecessorSection
}
if ($triageContext) {
    $extraContext += "`n`n## Triage Context`n`n$triageContext"
}
$prompt = & $buildPrompt -RoleName "engineer" -RolePath $scriptDir `
                         -RoomDir $RoomDir -TaskRef $taskRef -TaskBody $latestBody `
                         -ExtraContext $extraContext

# --- Log start ---
if (Get-Command Write-OstwinLog -ErrorAction SilentlyContinue) {
    Write-OstwinLog -Level INFO -Message "Starting work on $taskRef in $roomName"
}
else {
    Write-Host "[ENGINEER] Starting work on $taskRef in $roomName"
}

# --- Run the agent ---
$result = & $invokeAgent -RoomDir $RoomDir -RoleName "engineer" `
                         -InstanceId $InstanceId `
                         -WorkingDir $instanceWorkingDir `
                         -Prompt $prompt -TimeoutSeconds $TimeoutSeconds
$outputArtifact = if ($result.PSObject.Properties.Name -contains "OutputFile" -and $result.OutputFile) {
    "artifacts/$(Split-Path $result.OutputFile -Leaf)"
} else {
    "agent output"
}

# --- Handle agent result ---
if ($result.ExitCode -eq 0) {
    if (Get-Command Write-OstwinLog -ErrorAction SilentlyContinue) {
        Write-OstwinLog -Level INFO -Message "Completed $taskRef successfully."
    }
    if (Get-Command Write-LifecycleSignal -ErrorAction SilentlyContinue) {
        $successSignal = if (Get-Command Get-PreferredLifecycleSuccessSignal -ErrorAction SilentlyContinue) {
            Get-PreferredLifecycleSuccessSignal -RoomDir $RoomDir -DefaultSignal "done"
        } else { "done" }
        $body = "VERDICT: DONE`n`nEngineer completed $taskRef successfully with lifecycle signal '$successSignal'. Full output: $outputArtifact"
        Write-LifecycleSignal -RoomDir $RoomDir -FromRole "engineer" -Type $successSignal -Ref $taskRef -Body $body -SkipIfFresh | Out-Null
    }
}
elseif ($result.TimedOut) {
    if (Get-Command Write-OstwinLog -ErrorAction SilentlyContinue) {
        Write-OstwinLog -Level ERROR -Message "Timed out on $taskRef after ${TimeoutSeconds}s."
    }
    if (Get-Command Write-LifecycleSignal -ErrorAction SilentlyContinue) {
        Write-LifecycleSignal -RoomDir $RoomDir -FromRole "engineer" -Type "error" -Ref $taskRef -Body "VERDICT: ERROR`n`nEngineer timed out after ${TimeoutSeconds}s." -SkipIfFresh | Out-Null
    }
}
else {
    if (Get-Command Write-OstwinLog -ErrorAction SilentlyContinue) {
        Write-OstwinLog -Level ERROR -Message "Failed on $taskRef with exit code $($result.ExitCode)."
    }
    if (Get-Command Write-LifecycleSignal -ErrorAction SilentlyContinue) {
        Write-LifecycleSignal -RoomDir $RoomDir -FromRole "engineer" -Type "error" -Ref $taskRef -Body "VERDICT: ERROR`n`nEngineer failed with exit code $($result.ExitCode)." -SkipIfFresh | Out-Null
    }
}

# --- Update per-role config status ---
if ($engineerConfigs) {
    $latestRoleConfig = Get-Content $engineerConfigs[0].FullName -Raw | ConvertFrom-Json
    $latestRoleConfig.status = if ($result.ExitCode -eq 0) { "completed" } else { "failed" }
    $latestRoleConfig | ConvertTo-Json -Depth 5 | Out-File -FilePath $engineerConfigs[0].FullName -Encoding utf8
}

# --- PID file is NOT removed here (manager-owned lifecycle) ---
# The manager cleans up PID files when it processes the signal and transitions
# the room state. Removing PID here causes a race: manager polls, finds no PID,
# and re-spawns before processing the channel signal.

exit $result.ExitCode
