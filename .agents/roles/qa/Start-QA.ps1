<#
.SYNOPSIS
    QA role runner — reviews engineer output and posts done/fail verdict.

.DESCRIPTION
    Reads the engineer's "done" message from the channel, builds a QA review
    prompt, runs the agent via Invoke-Agent.ps1, parses VERDICT from output,
    and posts lifecycle verdicts back to the channel.

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
    $qaRoleConfigFile = $qaConfigs[0].FullName
    if (Get-Command Set-LifecycleRoleStatus -ErrorAction SilentlyContinue) {
        Set-LifecycleRoleStatus -RoomDir $RoomDir -RoleName "qa" -Status "active" -ConfigFile $qaRoleConfigFile | Out-Null
    } else {
        $qaRoleConfig = Get-Content $qaRoleConfigFile -Raw | ConvertFrom-Json
        $qaRoleConfig.status = "active"
        $qaRoleConfig | ConvertTo-Json -Depth 5 | Out-File -FilePath $qaRoleConfigFile -Encoding utf8
    }
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
    if (Get-Command Set-LifecycleRoleStatus -ErrorAction SilentlyContinue) {
        Set-LifecycleRoleStatus -RoomDir $RoomDir -RoleName "qa" -Status "active" -ConfigFile $qaRoleConfigFile | Out-Null
    }
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
  VERDICT: DONE
  VERDICT: FAIL

Use ESCALATE when the failure is NOT an implementation bug — e.g., the requirements
are wrong, the architecture is fundamentally flawed, or the acceptance criteria are
incomplete. Include a classification: DESIGN | SCOPE | REQUIREMENTS.

Follow with detailed reasoning.
"@
if ($predecessorSection) {
    $extraContext += $predecessorSection
}
if ($triageContext) {
    $extraContext += "`n`n## Triage Context`n`n$triageContext"
}

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
$outputArtifact = if ($result.PSObject.Properties.Name -contains "OutputFile" -and $result.OutputFile) {
    "artifacts/$(Split-Path $result.OutputFile -Leaf)"
} else {
    "agent output"
}

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

$verdict = if (Get-Command Get-AgentVerdict -ErrorAction SilentlyContinue) {
    Get-AgentVerdict -Output $output
} else {
    ""
}

# Fallback for older installs without LifecycleSignal.psm1 loaded.
if (-not $verdict) {
    $outputLines = $output -split "`n"

    # Strategy 1: Last line starting with VERDICT: (scan from end)
    for ($i = $outputLines.Count - 1; $i -ge 0; $i--) {
        if ($outputLines[$i] -match '^\s*\*{0,2}VERDICT:?\s*(DONE|PASS|FAIL|ESCALATE)') {
            $verdict = $Matches[1].ToUpper()
            break
        }
    }

    # Strategy 2: Last VERDICT: in final 80 lines
    if (-not $verdict) {
        $last80 = ($outputLines | Select-Object -Last 80) -join "`n"
        $allMatches = [regex]::Matches($last80, 'VERDICT:\s*(DONE|PASS|FAIL|ESCALATE)', 'IgnoreCase')
        if ($allMatches.Count -gt 0) {
            $verdict = $allMatches[$allMatches.Count - 1].Groups[1].Value.ToUpper()
        }
    }

    # Strategy 3: standalone DONE/FAIL/ESCALATE in last 20 lines. PASS is accepted only as legacy compatibility.
    if (-not $verdict) {
        $last20 = ($outputLines | Select-Object -Last 20) -join "`n"
        $allBare = [regex]::Matches($last20, '\b(DONE|PASS|FAIL|ESCALATE)\b', 'IgnoreCase')
        if ($allBare.Count -gt 0) {
            $verdict = $allBare[$allBare.Count - 1].Groups[1].Value.ToUpper()
        }
    }
}

$displayVerdict = if ($verdict -eq "PASS") { "DONE" } else { $verdict }
$successSignal = if (Get-Command Get-PreferredLifecycleSuccessSignal -ErrorAction SilentlyContinue) {
    Get-PreferredLifecycleSuccessSignal -RoomDir $RoomDir -DefaultSignal "done"
} else { "done" }
$signalType = if (Get-Command Convert-VerdictToLifecycleSignal -ErrorAction SilentlyContinue) {
    Convert-VerdictToLifecycleSignal -Verdict $verdict -DefaultSuccessSignal $successSignal
} else {
    switch ($verdict) {
        "DONE" { $successSignal }
        "PASS" { $successSignal }
        "FAIL" { "fail" }
        "ESCALATE" { "escalate" }
        default { "" }
    }
}

# --- Handle agent result ---
if ($result.TimedOut) {
    $signalType = ""
    $displayVerdict = "ERROR"
    if (Get-Command Write-OstwinLog -ErrorAction SilentlyContinue) {
        Write-OstwinLog -Level ERROR -Message "Timed out on $taskRef after ${TimeoutSeconds}s."
    }
}
elseif ($result.ExitCode -ne 0) {
    $signalType = ""
    $displayVerdict = "ERROR"
    if (Get-Command Write-OstwinLog -ErrorAction SilentlyContinue) {
        Write-OstwinLog -Level ERROR -Message "QA agent failed on $taskRef with exit code $($result.ExitCode)."
    }
}
elseif ($signalType -in @("done", "pass")) {
    if (Get-Command Write-OstwinLog -ErrorAction SilentlyContinue) {
        Write-OstwinLog -Level INFO -Message "DONE $taskRef."
    }
}
elseif ($signalType -eq "fail") {
    if (Get-Command Write-OstwinLog -ErrorAction SilentlyContinue) {
        Write-OstwinLog -Level INFO -Message "FAILED $taskRef."
    }
}
elseif ($signalType -eq "escalate") {
    if (Get-Command Write-OstwinLog -ErrorAction SilentlyContinue) {
        Write-OstwinLog -Level WARN -Message "ESCALATED $taskRef — design/scope issue."
    }
}
else {
    if (Get-Command Write-OstwinLog -ErrorAction SilentlyContinue) {
        Write-OstwinLog -Level WARN -Message "Could not parse verdict for $taskRef — leaving lifecycle signal empty."
    }
}

if ($signalType -and (Get-Command Write-LifecycleSignal -ErrorAction SilentlyContinue)) {
    $body = "VERDICT: $displayVerdict`n`nqa completed $taskRef with lifecycle signal '$signalType'. Full output: $outputArtifact"
    Write-LifecycleSignal -RoomDir $RoomDir -FromRole "qa" -Type $signalType -Ref $taskRef -Body $body -SkipIfFresh | Out-Null
}

# --- Update per-role config status ---
if (Test-Path $qaRoleConfigFile) {
    $finalStatus = if ($signalType -in @("done", "pass")) { "completed" } else { "failed" }
    if (Get-Command Set-LifecycleRoleStatus -ErrorAction SilentlyContinue) {
        Set-LifecycleRoleStatus -RoomDir $RoomDir -RoleName "qa" -Status $finalStatus -ConfigFile $qaRoleConfigFile | Out-Null
    } else {
        $qaFinalConfig = Get-Content $qaRoleConfigFile -Raw | ConvertFrom-Json
        $qaFinalConfig.status = $finalStatus
        $qaFinalConfig | ConvertTo-Json -Depth 5 | Out-File -FilePath $qaRoleConfigFile -Encoding utf8
    }
}

# --- PID file is NOT removed here (manager-owned lifecycle) ---
# The manager cleans up PID files when it processes the signal and transitions
# the room state. Removing PID here causes a race: manager polls, finds no PID,
# and re-spawns before processing the channel signal.

Write-Host "[QA] Finished $taskRef in $roomName — verdict: $(if ($displayVerdict) { $displayVerdict } else { 'UNPARSED' }), signal: $(if ($signalType) { $signalType } else { 'none' }), exitCode: $($result.ExitCode)"

$runnerExitCode = if ($result.ExitCode -ne 0) {
    $result.ExitCode
} elseif (-not $signalType) {
    1
} else {
    0
}
exit $runnerExitCode
