<#
.SYNOPSIS
    QA role runner — reviews engineer output and posts pass/fail verdict.

.DESCRIPTION
    Reads the engineer's "done" message from the channel, builds a QA review
    prompt, runs the agent via Invoke-Agent.ps1, parses VERDICT from output,
    and posts pass/fail/error back to the channel.

    Replaces: roles/qa/run.sh

.PARAMETER RoomDir
    Path to the war-room directory.
.PARAMETER TimeoutSeconds
    Override timeout. Default: from config.

.EXAMPLE
    ./Start-QA.ps1 -RoomDir "./war-rooms/room-001"
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

# --- Load config ---
$configPath = if ($env:AGENT_OS_CONFIG) { $env:AGENT_OS_CONFIG }
else { Join-Path $agentsDir "config.json" }

if (Test-Path $configPath) {
    $config = Get-Content $configPath -Raw | ConvertFrom-Json
    if ($TimeoutSeconds -eq 0) {
        $TimeoutSeconds = $config.qa.timeout_seconds
    }
}
if ($TimeoutSeconds -eq 0) { $TimeoutSeconds = 300 }

# --- Read/Create per-role config file (qa_{id}.json) ---
$qaConfigs = Get-ChildItem -Path $RoomDir -Filter "qa_*.json" -ErrorAction SilentlyContinue | Sort-Object Name -Descending
if ($qaConfigs) {
    # Existing QA config — update status to active
    $qaRoleConfig = Get-Content $qaConfigs[0].FullName -Raw | ConvertFrom-Json
    $qaRoleConfig.status = "active"
    $qaRoleConfig | ConvertTo-Json -Depth 5 | Out-File -FilePath $qaConfigs[0].FullName -Encoding utf8
    $qaRoleConfigFile = $qaConfigs[0].FullName
}
else {
    # First QA assignment — create qa_001.json
    $qaModel = "google-vertex/gemini-3-flash-preview"
    if ($config -and $config.qa.default_model) {
        $qaModel = $config.qa.default_model
    }
    $ts = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    $qaRoleConfigObj = [ordered]@{
        role            = "qa"
        instance_id     = "001"
        instance_type   = ""
        display_name    = "qa #001"
        model           = $qaModel
        assigned_at     = $ts
        status          = "active"
        config_override = [ordered]@{}
    }
    $qaRoleConfigFile = Join-Path $RoomDir "qa_001.json"
    $qaRoleConfigObj | ConvertTo-Json -Depth 5 | Out-File -FilePath $qaRoleConfigFile -Encoding utf8
}

# --- Read task ref ---
$taskRef = if (Test-Path (Join-Path $RoomDir "task-ref")) {
    (Get-Content (Join-Path $RoomDir "task-ref") -Raw).Trim()
}
else { "UNKNOWN" }

$roomName = Split-Path $RoomDir -Leaf

# --- Resolve working_dir from room config.json ---
$instanceWorkingDir = ''
$roomConfigFile = Join-Path $RoomDir "config.json"
if (Test-Path $roomConfigFile) {
    $roomConfig = Get-Content $roomConfigFile -Raw | ConvertFrom-Json
    if ($roomConfig.working_dir) {
        $instanceWorkingDir = $roomConfig.working_dir
    }
}

# --- Debug: show resolved config ---
$qaModel = if ($qaConfigs) {
    $qaRoleConfig = Get-Content $qaConfigs[0].FullName -Raw | ConvertFrom-Json
    $qaRoleConfig.model
}
else { "google-vertex/gemini-3-flash-preview" }
Write-Host "[QA] === Debug Config ==="
Write-Host "[QA]   Room:      $roomName"
Write-Host "[QA]   TaskRef:   $taskRef"
Write-Host "[QA]   Model:     $qaModel"
Write-Host "[QA]   Timeout:   ${TimeoutSeconds}s"
Write-Host "[QA]   RoomDir:   $RoomDir"
Write-Host "[QA]   Config:    $qaRoleConfigFile"
Write-Host "[QA] ==================="

# --- Write per-role context.md ---
$contextsDir = Join-Path $RoomDir "contexts"
if (-not (Test-Path $contextsDir)) {
    New-Item -ItemType Directory -Path $contextsDir -Force | Out-Null
}
$contextFile = Join-Path $contextsDir "qa.md"
$contextContent = @"
# QA Context

## Assignment
- Task: $taskRef
- Room: $roomName
- Working Directory: $(if ($instanceWorkingDir) { $instanceWorkingDir } else { 'project root' })
- Started: $((Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ'))
"@
$contextContent | Out-File -FilePath $contextFile -Encoding utf8 -Force

# --- Detect Epic vs Task ---
$isEpic = $taskRef -match '^EPIC-'

# --- Read the engineer's "done" message ---
$engineerReport = "."
try {
    $doneMsgs = & $readMessages -RoomDir $RoomDir -FilterType "done" -Last 1 -AsObject
    if ($doneMsgs -and $doneMsgs.Count -gt 0) {
        $engineerReport = $doneMsgs[-1].body
    }
}
catch { }

# --- Read original task ---
$taskDesc = if (Test-Path (Join-Path $RoomDir "brief.md")) {
    Get-Content (Join-Path $RoomDir "brief.md") -Raw
}
else { "No task description found." }

# --- Read TASKS.md for Epic reviews ---
$tasksMd = ""
if ($isEpic) {
    $tasksFile = Join-Path $RoomDir "TASKS.md"
    if (Test-Path $tasksFile) {
        $tasksMd = Get-Content $tasksFile -Raw
    }
}

# --- Read role prompt (supports both ROLE.md and SKILL.md) ---
$rolePrompt = ""
foreach ($promptFile in @("ROLE.md", "SKILL.md")) {
    $promptPath = Join-Path $scriptDir $promptFile
    if (Test-Path $promptPath) {
        $rolePrompt = Get-Content $promptPath -Raw
        break
    }
}

# --- Build Epic-specific sections ---
$tasksSection = ""
if ($isEpic -and $tasksMd) {
    $tasksSection = @"

## Team's Task Breakdown (TASKS.md)

$tasksMd
"@
}

# --- Build review instructions ---
if ($isEpic) {
    $reviewInstructions = @"
You are reviewing an EPIC — a complete feature delivered by the team.

1. Review ALL code changes holistically across the full epic
2. Verify the TASKS.md checklist is complete — all sub-tasks must be checked off
3. Verify each sub-task was actually implemented (not just checked off)
4. Run the project test suite
5. Validate the epic delivers the feature described in the brief
6. Provide your verdict
"@
}
else {
    $reviewInstructions = @"
1. Review the code changes described in the team's report
2. Verify the implementation meets the task requirements
3. Run tests if applicable
4. Provide your verdict
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
            }
            catch { }
        }
        if ($sections.Count -gt 0) {
            $predecessorSection = "`n`n## Predecessor Outputs`n`n$($sections -join "`n`n")"
            Write-Host "[QA] Injected $($sections.Count) predecessor context(s)"
        }
    }
}

# --- Read triage context if available (from manager triage) ---
$triageContext = ""
$triageFile = Join-Path $RoomDir "artifacts" "triage-context.md"
if (Test-Path $triageFile) {
    $triageContext = Get-Content $triageFile -Raw
    Write-Host "[QA] Loaded triage context from artifacts/triage-context.md"
}

# --- Assemble final prompt using Build-SystemPrompt.ps1 ---
$buildPrompt = Join-Path $agentsDir "roles" "_base" "Build-SystemPrompt.ps1"
$extraContext = @"
## Team's Report

$engineerReport

## Instructions

$reviewInstructions

IMPORTANT: Your response MUST include exactly one of these lines:
  VERDICT: PASS
  VERDICT: FAIL

Use ESCALATE when the failure is NOT an implementation bug — e.g., the requirements
are wrong, the architecture is fundamentally flawed, or the acceptance criteria are
incomplete. Include a classification: DESIGN | SCOPE | REQUIREMENTS.

Follow with detailed reasoning.
"@

$prompt = & $buildPrompt -RoleName "qa" -RolePath $scriptDir `
    -RoomDir $RoomDir -TaskRef $taskRef `
    -ExtraContext $extraContext

Write-Host "[QA] Prompt assembled ($($prompt.Length) chars)"

# --- Log start ---
if (Get-Command Write-OstwinLog -ErrorAction SilentlyContinue) {
    Write-OstwinLog -Level INFO -Message "Starting review of $taskRef in $roomName (model: $qaModel, timeout: ${TimeoutSeconds}s)"
}
else {
    Write-Host "[QA] Starting review of $taskRef in $roomName (model: $qaModel, timeout: ${TimeoutSeconds}s)"
}

# --- Run the agent ---
Write-Host "[QA] Invoking agent: qa, room=$roomName, timeout=${TimeoutSeconds}s"
$result = & $invokeAgent -RoomDir $RoomDir -RoleName "qa" `
    -WorkingDir $instanceWorkingDir `
    -Prompt $prompt -TimeoutSeconds $TimeoutSeconds
Write-Host "[QA] Agent returned: exitCode=$($result.ExitCode), timedOut=$($result.TimedOut), outputLen=$($result.Output.Length)"

# --- Parse verdict from output ---
$rawOutput = $result.Output

# --- Strip tool-calling noise from agent output ---
# deepagents --quiet still emits "🔧 Calling tool:" lines and MCP loading messages.
# These are meaningless for channel/release notes and cause signoff rejection.
# Also strip [wrapper] preamble and MCP tool-call lines (⚙) which contain
# channel message dumps with stale verdicts that corrupt verdict parsing.
$cleanLines = ($rawOutput -split "`r?\n") | Where-Object {
    $line = $_.Trim()
    # Preserve empty lines for formatting
    if (-not $line) { return $true }

    # Strip specific noise patterns
    $isNoise = ($line -match '^\[wrapper\]' -or
        $line -match '^🔧' -or
        $line -match '[Cc]alling tool:' -or
        $line -match '^\w{0,5}\s*tool:' -or
        $line -match '^Loading MCP' -or
        $line -match '^Running task non-interactively' -or
        $line -match '^Agent active' -or
        $line -match '^Usage Stats' -or
        $line -match '^\s*Reqs\s+InputTok' -or
        $line -match '^\s*google-vertex/gemini-' -or
        $line -match '^✓ Task completed' -or
        $line -match '^System\.Management\.Automation' -or
        $line -match '^⚙\s' -or
        $line -match '^[✗✓•→✱]\s' -or
        $line -match '^\x1b\[0m[⚙✗✓•→✱]\s' -or
        $line -match '^\x1b\[\d+m' -and $line -match '^\x1b\[0m\s*$')
    
    return (-not $isNoise)
}
$output = ($cleanLines -join "`n").Trim()
if (-not $output) {
    # Fallback: if everything was stripped, keep the raw output
    $output = $rawOutput
}

$verdict = ""
$outputLines = $output -split "`n"

# --- Verdict parsing: scan from the END of output ---
# The agent's output may contain channel_read_messages dumps with stale
# VERDICT: FAIL from prior iterations. Parsing from the start would match
# the stale verdict. Parsing from the end matches the agent's final verdict.

# Strategy 1: Last line starting with VERDICT: (scan from end)
for ($i = $outputLines.Count - 1; $i -ge 0; $i--) {
    if ($outputLines[$i] -match '^\s*\*{0,2}VERDICT:?\s*(PASS|FAIL|ESCALATE)') {
        $verdict = $Matches[1].ToUpper()
        break
    }
}

# Strategy 2: Last VERDICT: in final 80 lines
if (-not $verdict) {
    $last80 = ($outputLines | Select-Object -Last 80) -join "`n"
    $allMatches = [regex]::Matches($last80, 'VERDICT:\s*(PASS|FAIL|ESCALATE)')
    if ($allMatches.Count -gt 0) {
        $verdict = $allMatches[$allMatches.Count - 1].Groups[1].Value.ToUpper()
    }
}

# Strategy 3: standalone PASS/FAIL/ESCALATE in last 20 lines (not first 20)
if (-not $verdict) {
    $last20 = ($outputLines | Select-Object -Last 20) -join "`n"
    $allBare = [regex]::Matches($last20, '\b(PASS|FAIL|ESCALATE)\b')
    if ($allBare.Count -gt 0) {
        $verdict = $allBare[$allBare.Count - 1].Groups[1].Value.ToUpper()
    }
}

# --- Post result to channel ---
if ($result.TimedOut) {
    & $postMessage -RoomDir $RoomDir -From "qa" -To "manager" `
        -Type "error" -Ref $taskRef -Body "QA timed out after ${TimeoutSeconds}s"
    if (Get-Command Write-OstwinLog -ErrorAction SilentlyContinue) {
        Write-OstwinLog -Level ERROR -Message "Timed out on $taskRef after ${TimeoutSeconds}s."
    }
}
elseif ($verdict -eq "PASS") {
    & $postMessage -RoomDir $RoomDir -From "qa" -To "manager" `
        -Type "pass" -Ref $taskRef -Body $output
    if (Get-Command Write-OstwinLog -ErrorAction SilentlyContinue) {
        Write-OstwinLog -Level INFO -Message "PASSED $taskRef."
    }
}
elseif ($verdict -eq "FAIL") {
    & $postMessage -RoomDir $RoomDir -From "qa" -To "manager" `
        -Type "fail" -Ref $taskRef -Body $output
    if (Get-Command Write-OstwinLog -ErrorAction SilentlyContinue) {
        Write-OstwinLog -Level INFO -Message "FAILED $taskRef."
    }
}
elseif ($verdict -eq "ESCALATE") {
    & $postMessage -RoomDir $RoomDir -From "qa" -To "manager" `
        -Type "escalate" -Ref $taskRef -Body $output
    if (Get-Command Write-OstwinLog -ErrorAction SilentlyContinue) {
        Write-OstwinLog -Level WARN -Message "ESCALATED $taskRef — design/scope issue."
    }
}
else {
    & $postMessage -RoomDir $RoomDir -From "qa" -To "manager" `
        -Type "error" -Ref $taskRef `
        -Body "Could not parse QA verdict. Full output: $output"
    if (Get-Command Write-OstwinLog -ErrorAction SilentlyContinue) {
        Write-OstwinLog -Level WARN -Message "Could not parse verdict for $taskRef — posting as error."
    }
}

# --- Update per-role config status ---
if (Test-Path $qaRoleConfigFile) {
    $qaFinalConfig = Get-Content $qaRoleConfigFile -Raw | ConvertFrom-Json
    $qaFinalConfig.status = if ($verdict -eq "PASS") { "completed" } else { "failed" }
    $qaFinalConfig | ConvertTo-Json -Depth 5 | Out-File -FilePath $qaRoleConfigFile -Encoding utf8
}

# --- PID file is NOT removed here (manager-owned lifecycle) ---
# The manager cleans up PID files when it processes the signal and transitions
# the room state. Removing PID here causes a race: manager polls, finds no PID,
# and re-spawns before processing the channel signal.

Write-Host "[QA] Finished $taskRef in $roomName — verdict: $(if ($verdict) { $verdict } else { 'UNPARSED' }), exitCode: $($result.ExitCode)"

exit $result.ExitCode

