<#
.SYNOPSIS
    Audit role runner — scopes investigations, commissions analysis, validates findings, makes risk decisions.

.DESCRIPTION
    Reads the task brief and triage context from the war-room, builds an
    audit-specific prompt with the investigation workflow, runs the auditor
    agent via Invoke-Agent.ps1, and posts the result (done/escalate/error)
    back to the channel.

    The auditor follows the DEPT framework for scoping, commissions data
    analysis via structured DATA requests, validates output using the
    Five Validation Questions, and produces formal Risk Decision Records.

.PARAMETER RoomDir
    Path to the war-room directory.
.PARAMETER TimeoutSeconds
    Override timeout. Default: from config or role.json (900s).

.EXAMPLE
    ./Start-Audit.ps1 -RoomDir "./war-rooms/room-001"
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
$postMessage = Join-Path $channelDir "Post-Message.ps1"
$readMessages = Join-Path $channelDir "Read-Messages.ps1"

# --- Import logging ---
$logModule = Join-Path $agentsDir "lib" "Log.psm1"
if (Test-Path $logModule) { Import-Module $logModule -Force }

function Write-Log {
    param([string]$Level, [string]$Message)
    if (Get-Command Write-OstwinLog -ErrorAction SilentlyContinue) {
        Write-OstwinLog -Level $Level -Message $Message
    } else {
        Write-Host "[$Level] $Message"
    }
}

# --- Load config ---
$configPath = if ($env:AGENT_OS_CONFIG) { $env:AGENT_OS_CONFIG }
              else { Join-Path $agentsDir "config.json" }

$config = $null
$maxPromptBytes = 102400
if (Test-Path $configPath) {
    $config = Get-Content $configPath -Raw | ConvertFrom-Json
    if ($TimeoutSeconds -eq 0 -and $config.audit -and $config.audit.timeout_seconds) {
        $TimeoutSeconds = $config.audit.timeout_seconds
    }
    if ($config.audit -and $config.audit.max_prompt_bytes) {
        $maxPromptBytes = $config.audit.max_prompt_bytes
    }
}
if ($TimeoutSeconds -eq 0) { $TimeoutSeconds = 900 }

# --- Process Tracking (PID) ---
$pidDir = Join-Path $RoomDir "pids"
if (-not (Test-Path $pidDir)) { New-Item -ItemType Directory -Path $pidDir -Force | Out-Null }
$pidFile = Join-Path $pidDir "audit.pid"
$PID | Out-File -FilePath $pidFile -Encoding utf8 -NoNewline

function Cleanup-And-Exit {
    param([int]$ExitCode, [string]$ErrorMsg = "")
    if ($ErrorMsg) {
        Write-Log "ERROR" "[AUDIT] Error: $ErrorMsg"
        & $postMessage -RoomDir $RoomDir -From "audit" -To "manager" -Type "error" -Ref $taskRef -Body $ErrorMsg
    }
    # PID file is NOT removed here — manager-owned lifecycle
    exit $ExitCode
}

# --- Read/Create per-role config file (audit_{id}.json) ---
$auditConfigs = Get-ChildItem -Path $RoomDir -Filter "audit_*.json" -ErrorAction SilentlyContinue | Sort-Object Name -Descending
$auditRoleConfigFile = $null
if ($auditConfigs) {
    $auditRoleConfig = Get-Content $auditConfigs[0].FullName -Raw | ConvertFrom-Json
    $auditRoleConfig.status = "active"
    $auditRoleConfig | ConvertTo-Json -Depth 5 | Out-File -FilePath $auditConfigs[0].FullName -Encoding utf8
    $auditRoleConfigFile = $auditConfigs[0].FullName
} else {
    $auditModel = "google-vertex/gemini-3.1-pro-preview"
    if ($config -and $config.audit -and $config.audit.default_model) {
        $auditModel = $config.audit.default_model
    }
    $ts = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    $auditRoleConfigObj = [ordered]@{
        role            = "audit"
        instance_id     = "001"
        instance_type   = ""
        display_name    = "auditor #001"
        model           = $auditModel
        assigned_at     = $ts
        status          = "active"
        config_override = [ordered]@{}
    }
    $auditRoleConfigFile = Join-Path $RoomDir "audit_001.json"
    $auditRoleConfigObj | ConvertTo-Json -Depth 5 | Out-File -FilePath $auditRoleConfigFile -Encoding utf8
}

# --- Read task ref ---
$taskRef = if (Test-Path (Join-Path $RoomDir "task-ref")) {
    (Get-Content (Join-Path $RoomDir "task-ref") -Raw).Trim()
} else { "UNKNOWN" }

$roomName = Split-Path $RoomDir -Leaf

# --- Write per-role context.md ---
$contextsDir = Join-Path $RoomDir "contexts"
if (-not (Test-Path $contextsDir)) {
    New-Item -ItemType Directory -Path $contextsDir -Force | Out-Null
}
$contextFile = Join-Path $contextsDir "audit.md"
@"
# Auditor Context

## Assignment
- Task: $taskRef
- Role: audit
- Room: $roomName
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

# --- Parse working directory from brief.md ---
$workingDir = ''
$briefContent = $taskDesc
if ($briefContent -match '## Working Directory\s*\n(.+)') {
    $workingDir = $Matches[1].Trim()
} elseif ($briefContent -match 'working_dir:\s*(.+)') {
    $workingDir = $Matches[1].Trim()
}

# --- Read data analyst responses (from downstream war-rooms) ---
$analystOutputs = ""
try {
    $doneMsgs = & $readMessages -RoomDir $RoomDir -FilterType "done" -AsObject
    if ($doneMsgs -and $doneMsgs.Count -gt 0) {
        $sections = @()
        foreach ($dm in $doneMsgs) {
            if ($dm.from -and $dm.from -ne "audit") {
                $body = $dm.body
                if ($body.Length -gt 10240) { $body = $body.Substring(0, 10240) + "`n[TRUNCATED]" }
                $sections += "### From: $($dm.from)`n$body"
            }
        }
        if ($sections.Count -gt 0) {
            $analystOutputs = "`n`n## Data Analyst Outputs`n`n$($sections -join "`n`n")"
        }
    }
} catch { }

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
                $depDoneMsgs = & $readMessages -RoomDir $depRoomDir -FilterType "done" -Last 1 -AsObject
                if ($depDoneMsgs -and $depDoneMsgs.Count -gt 0) {
                    $body = $depDoneMsgs[-1].body
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

# --- Build audit-specific instructions ---
if ($isEpic) {
    $existingTasksFile = Join-Path $RoomDir "TASKS.md"
    $hasExistingTasks = Test-Path $existingTasksFile

    if ($hasExistingTasks) {
        $instructions = @"
You are continuing an investigation — TASKS.md already exists (see above).

1. Review the TASKS.md — checked tasks ([x]) were completed previously
2. Focus on unchecked investigation steps ([ ]) and any new findings
3. Update TASKS.md if new investigation threads emerge
4. After completing each step, check it off: - [x] INVESTIGATION-001 — Description
5. Validate ALL data analyst outputs using the Five Validation Questions
6. When all investigation tasks are complete, produce a formal Risk Decision Record with:
   - Investigation reference and scope (DEPT framework)
   - Key findings with quantified financial exposure
   - Decision category: Accept / Mitigate / Investigate / Escalate
   - Required actions with owners and deadlines
   - Monitoring triggers for re-evaluation
"@
    } else {
        $instructions = @"
You are starting a new investigation — follow the investigation pipeline.

### Phase 1 — Scoping (DEPT Framework)
1. Define investigation boundaries: Domain, Entity Population, Period, Theme
2. Create TASKS.md at: $RoomDir/TASKS.md
   - Use markdown checkboxes: - [ ] INVESTIGATION-001 — Description
   - Each investigation step should be independently verifiable
3. Save TASKS.md before proceeding

### Phase 2 — Analysis Commission
1. Select analytical lenses (Distribution, Deviation, Relationship, Temporality, Compounding)
2. Formulate precise questions for data analysts
3. Compose structured DATA requests (Define, Articulate, Timeline, Audience)

### Phase 3 — Validation & Decision
1. Validate ALL data analyst outputs using the Five Validation Questions
2. Quantify financial exposure for every finding
3. Produce a formal Risk Decision Record:
   - Decision category: Accept / Mitigate / Investigate / Escalate
   - Required actions with owners and deadlines
   - Monitoring triggers
"@
    }
} else {
    $instructions = @"
1. Scope the investigation using the DEPT framework
2. Commission data analysis via structured DATA requests
3. Validate outputs using the Five Validation Questions
4. Produce a Risk Decision Record with: Decision Category, Financial Exposure, Required Actions, Monitoring Triggers
"@
}

# --- Assemble final prompt using Build-SystemPrompt.ps1 ---
$buildPrompt = Join-Path $agentsDir "roles" "_base" "Build-SystemPrompt.ps1"
$extraContext = @"
## Latest Instruction

$latestBody
$triageSection
$analystOutputs

## War-Room

Room: $roomName
Task Ref: $taskRef
Role: audit
Working Directory: $(if ($workingDir) { $workingDir } else { Get-Location })
$predecessorSection

## Instructions

$instructions
"@

$prompt = & $buildPrompt -RoleName "audit" -RolePath $scriptDir `
                         -RoomDir $RoomDir -TaskRef $taskRef `
                         -ExtraContext $extraContext

# --- Prompt size guard ---
if ($prompt.Length -gt $maxPromptBytes) {
    $originalSize = $prompt.Length
    $prompt = $prompt.Substring(0, $maxPromptBytes) + @"

[TRUNCATED: prompt was $originalSize bytes, max is $maxPromptBytes. Full task description in: $RoomDir/brief.md]
"@
    Write-Log "WARN" "[AUDIT] Prompt truncated from $originalSize to $maxPromptBytes bytes for $taskRef"
}

# --- Log start ---
Write-Log "INFO" "[AUDIT] Starting investigation on $taskRef in $roomName"

# --- Run the agent ---
$agentModel = "google-vertex/gemini-3.1-pro-preview"
if ($auditConfigs) {
    $latestConfig = Get-Content $auditConfigs[0].FullName -Raw | ConvertFrom-Json
    if ($latestConfig.model) { $agentModel = $latestConfig.model }
}

$result = & $invokeAgent -RoomDir $RoomDir -RoleName "audit" `
                         -Prompt $prompt -TimeoutSeconds $TimeoutSeconds `
                         -Model $agentModel

# --- Parse output for escalation signals ---
$output = $result.Output
$isEscalation = $false

# Check for escalation keywords in the output
if ($output -match '(?i)(DECISION:\s*ESCALATE|ESCALATE.*immediately|material financial exposure|potential fraud|regulatory)') {
    $isEscalation = $true
}

# --- Post result to channel ---
if ($result.ExitCode -eq 0) {
    if ($isEscalation) {
        & $postMessage -RoomDir $RoomDir -From "audit" -To "manager" `
                       -Type "escalate" -Ref $taskRef -Body $output
        Write-Log "WARN" "[AUDIT] ESCALATION on $taskRef — material risk detected."
    } else {
        & $postMessage -RoomDir $RoomDir -From "audit" -To "manager" `
                       -Type "done" -Ref $taskRef -Body $output
        Write-Log "INFO" "[AUDIT] Completed investigation on $taskRef."
    }
} elseif ($result.TimedOut) {
    & $postMessage -RoomDir $RoomDir -From "audit" -To "manager" `
                   -Type "error" -Ref $taskRef -Body "Auditor timed out after ${TimeoutSeconds}s"
    Write-Log "ERROR" "[AUDIT] Timed out on $taskRef after ${TimeoutSeconds}s."
} else {
    & $postMessage -RoomDir $RoomDir -From "audit" -To "manager" `
                   -Type "error" -Ref $taskRef `
                   -Body "Auditor exited with code $($result.ExitCode): $($result.Output)"
    Write-Log "ERROR" "[AUDIT] Failed on $taskRef with exit code $($result.ExitCode)."
}

# --- Update per-role config status ---
if ($auditRoleConfigFile -and (Test-Path $auditRoleConfigFile)) {
    $auditFinalConfig = Get-Content $auditRoleConfigFile -Raw | ConvertFrom-Json
    $auditFinalConfig.status = if ($result.ExitCode -eq 0) { "completed" } else { "failed" }
    $auditFinalConfig | ConvertTo-Json -Depth 5 | Out-File -FilePath $auditRoleConfigFile -Encoding utf8
}

# --- PID file is NOT removed here (manager-owned lifecycle) ---
# The manager cleans up PID files when it processes the signal and transitions
# the room state. Removing PID here causes a race: manager polls, finds no PID,
# and re-spawns before processing the channel signal.

exit $result.ExitCode
