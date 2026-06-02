<#
.SYNOPSIS
    JIT Agent Factory runner — synthesizes an ephemeral persona and executes the task.

.DESCRIPTION
    Reads the task from the war-room, asks the Manager LLM to synthesize an
    ideal specific agent persona with necessary skills, then launches that agent.
    Bypasses static role definitions.

.PARAMETER RoomDir
    Path to the war-room directory.
.PARAMETER TimeoutSeconds
    Override timeout.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$RoomDir,

    [int]$TimeoutSeconds = 0
)

# --- Resolve paths ---
$scriptDir = $PSScriptRoot
$agentsDir = (Resolve-Path (Join-Path $scriptDir ".." "..")).Path
$channelDir = Join-Path $agentsDir "channel"
$invokeAgent = Join-Path $agentsDir "roles" "_base" "Invoke-Agent.ps1"
$postMessage = Join-Path $channelDir "Post-Message.ps1"
$readMessages = Join-Path $channelDir "Read-Messages.ps1"

# --- Import logging ---
$logModule = Join-Path $agentsDir "lib" "Log.psm1"
if (Test-Path $logModule) { Import-Module $logModule -Force }

if ($TimeoutSeconds -eq 0) { $TimeoutSeconds = 600 }

function Write-Log {
    param([string]$Level, [string]$Message)
    if (Get-Command Write-OstwinLog -ErrorAction SilentlyContinue) {
        Write-OstwinLog -Level $Level -Message $Message
    }
    else {
        Write-Host "[$Level] $Message"
    }
}

# --- Load Config (must happen before PID tracking to resolve role name) ---
$roomConfigFile = Join-Path $RoomDir "config.json"
if (-not (Test-Path $roomConfigFile)) {
    Write-Log "ERROR" "config.json not found in war room."
    exit 1
}
$roomConfig = Get-Content $roomConfigFile -Raw | ConvertFrom-Json

# --- Process Tracking (PID) ---
# NOTE: Writing $PID (PowerShell's PID) here is CORRECT because this script
# runs inline — it does not exec into another process. This differs from
# Invoke-Agent.ps1, which delegates PID writing to bin/agent via the
# AGENT_OS_PID_FILE env var (since exec replaces the process image).
#
# DESIGN NOTE: Start-EphemeralAgent reads config.json's assigned_role for PID
# tracking because it acts as the JIT SYNTHESIS COORDINATOR — it runs as the
# manager during Phase 1 (spec generation), then delegates to Start-DynamicRole.ps1
# for Phase 2 (actual role execution). Start-DynamicRole.ps1 receives the correct
# lifecycle-resolved role via -RoleName (passed by the manager loop), overriding
# the stale config.json assigned_role.  This is NOT the same bug as the main
# role-resolution fix in Start-DynamicRole.ps1.
$pidDir = Join-Path $RoomDir "pids"
if (-not (Test-Path $pidDir)) { New-Item -ItemType Directory -Path $pidDir -Force | Out-Null }
$assignedRole = if ($roomConfig.assignment -and $roomConfig.assignment.assigned_role) {
    ($roomConfig.assignment.assigned_role -replace ':.*$', '')
} else { "engineer" }
$pidFile = Join-Path $pidDir "$assignedRole.pid"
$PID | Out-File -FilePath $pidFile -Encoding utf8 -NoNewline

function Cleanup-And-Exit {
    param([int]$ExitCode, [string]$ErrorMsg = "")
    if ($ErrorMsg) {
        Write-Log "ERROR" "Agent Error: $ErrorMsg"
        & $postMessage -RoomDir $RoomDir -From $assignedRole -To "manager" -Type "error" -Ref $TaskRef -Body $ErrorMsg
    }
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
    $lockFile = Join-Path $pidDir "$assignedRole.spawned_at"
    Remove-Item $lockFile -Force -ErrorAction SilentlyContinue
    exit $ExitCode
}
$TaskRef = $roomConfig.task_ref
$TaskTitle = $roomConfig.assignment.title
$TaskDesc = $roomConfig.assignment.description
$WorkingDir = ''
if ($roomConfig.PSObject.Properties['working_dir'] -and $roomConfig.working_dir) {
    $WorkingDir = $roomConfig.working_dir
}

# Get the latest instruction from channel
$latestFix = ""
$fixMsgs = & $readMessages -RoomDir $RoomDir -FilterType "fix" -AsObject
if ($fixMsgs -and $fixMsgs.Count -gt 0) {
    $latestFix = $fixMsgs[-1].body
}

# --- PHASE 1: JIT Agent Synthesis (The Manager's Brain) ---
$AgentSpecFile = Join-Path $RoomDir "artifacts" "agent-spec.json"
$AgentSpec = $null

if (-not (Test-Path $AgentSpecFile) -or $latestFix) {
    # If no spec exists OR there is new feedback from Manager/QA, regenerate the spec
    Write-Log "INFO" "Synthesizing dynamic ephemeral agent for $TaskRef..."
    
    $SynthesisPrompt = @"
You are an expert.
Your task is to analyze the following work objective and synthesize an ephemeral AI agent perfectly suited to complete it.

Objective Title: $TaskTitle
Objective Description: $TaskDesc
$($latestFix ? "`nLatest Feedback/Fix Instruction:`n$latestFix" : "")

Respond ONLY with a JSON object matching this schema. NO markdown backticks, NO extra text.
{
  "role_id": "short-descriptive-role-name",
  "purpose": "A clear, specific sentence describing the agent's exact purpose.",
  "instance_type": "The role type - MUST be exactly 'worker' or 'evaluator'. Use 'evaluator' ONLY if the objective requires reviewing, auditing, validating, or approving other work. Otherwise use 'worker'.",
  "required_capabilities": ["list", "of", "capabilities"],
  "required_skills": ["list", "of", "skill-folder-names"]
}

Available Skills in skills/:
$(Get-ChildItem -Path (Join-Path $agentsDir "skills") -Directory | Select-Object -ExpandProperty Name | Join-String -Separator ', ')
"@
    
    # Run a quick synthesis LLM call
    $SyncResult = & $invokeAgent -RoomDir $RoomDir -RoleName "manager" -Prompt $SynthesisPrompt -Model "google-vertex/gemini-3.1-pro-preview" -TimeoutSeconds 120 -InstanceId "synth"
    
    if ($SyncResult.ExitCode -ne 0) {
        Cleanup-And-Exit 1 "Agent synthesis failed. See output: $($SyncResult.Output)"
    }
    
    $RawOutput = $SyncResult.Output
    # Extract JSON robustly, ignoring any CLI prefixes/logs
    if ($RawOutput -match '(?s)(\{.*?\})') {
        $RawOutput = $Matches[1]
    }
    
    try {
        $AgentSpec = $RawOutput | ConvertFrom-Json
        if (-not $AgentSpec.instance_type) { $AgentSpec | Add-Member -MemberType NoteProperty -Name "instance_type" -Value "worker" }
        $AgentSpec | ConvertTo-Json -Depth 5 | Out-File -FilePath $AgentSpecFile -Encoding utf8
        Write-Log "INFO" "Synthesized Role: $($AgentSpec.role_id) [type: $($AgentSpec.instance_type)] equipped with: $($AgentSpec.required_skills -join ', ')"
    } catch {
        Cleanup-And-Exit 1 "Failed to parse synthesized agent JSON: $RawOutput"
    }
} else {
    $AgentSpec = Get-Content $AgentSpecFile -Raw | ConvertFrom-Json
    Write-Log "INFO" "Loaded cached agent role: $($AgentSpec.role_id)"
}

# --- PHASE 1.5: Persist the role on disk (fast scaffolding, no LLM) ---
$newDynamicRole = Join-Path $agentsDir "roles" "_base" "New-DynamicRole.ps1"
$roleDir = Join-Path $agentsDir "roles" $AgentSpec.role_id

if ((Test-Path $newDynamicRole) -and -not (Test-Path (Join-Path $roleDir "role.json"))) {
    Write-Log "INFO" "Scaffolding persistent role: $($AgentSpec.role_id)..."

    # Build a ROLE.md prompt from the synthesized spec + skills
    $rolePromptContent = @"
# $($AgentSpec.role_id)

$($AgentSpec.purpose)

You are a highly specialized AI agent. Complete your objective thoroughly using your tools.
If tests exist, run them. If tests fail, fix your code.
When the objective is complete, output a brief, concise summary of exactly what you accomplished.
"@

    # Inject skills into the ROLE.md
    $SkillsDir = Join-Path $agentsDir "skills"
    if ($AgentSpec.required_skills) {
        $rolePromptContent += "`n`n## Equipped Skills`n"
        foreach ($skill in $AgentSpec.required_skills) {
            $SkillPath = Join-Path $SkillsDir $skill "SKILL.md"
            if (Test-Path $SkillPath) {
                $SkillContent = Get-Content $SkillPath -Raw
                $rolePromptContent += "`n### Skill: $skill`n$SkillContent`n"
            }
        }
    }

    $scaffoldArgs = @{
        RoleName      = $AgentSpec.role_id
        AgentsDir     = $agentsDir
        Description   = $AgentSpec.purpose
        InstanceType  = $AgentSpec.instance_type
        PromptContent = $rolePromptContent
    }
    if ($AgentSpec.required_capabilities) {
        $scaffoldArgs['Capabilities'] = @($AgentSpec.required_capabilities)
    }
    if ($AgentSpec.required_skills) {
        $scaffoldArgs['Skills'] = @($AgentSpec.required_skills)
    }

    & $newDynamicRole @scaffoldArgs
}

# --- Store synthesized role in config WITHOUT overwriting assigned_role ---
# The lifecycle.json expects the original assigned_role (e.g. "researcher").
# Overwriting it with the JIT name (e.g. "research-scriptwriter") causes
# sender validation in Find-LatestSignal to reject signals → infinite loop.
$roomConfig | Add-Member -NotePropertyName "jit_role_id" -NotePropertyValue $AgentSpec.role_id -Force
$roomConfig | ConvertTo-Json -Depth 10 | Out-File -FilePath $roomConfigFile -Encoding utf8

# --- PHASE 2: Delegate to Start-DynamicRole.ps1 ---
Write-Log "INFO" "Delegating to Start-DynamicRole.ps1 for '$($AgentSpec.role_id)'..."

$dynamicRunner = Join-Path $agentsDir "roles" "_base" "Start-DynamicRole.ps1"
Remove-Item $pidFile -Force -ErrorAction SilentlyContinue  # Let the dynamic runner manage its own PID
# Use the lifecycle's assigned_role so PID/signal "from" matches lifecycle.json
& $dynamicRunner -RoomDir $RoomDir -RoleName $assignedRole -TimeoutSeconds $TimeoutSeconds
exit $LASTEXITCODE
