<#
.SYNOPSIS
    Architect role runner — reviews QA failures and provides design guidance.

.DESCRIPTION
    When QA fails a war-room and the manager classifies the failure as a
    design issue or plan gap, this script spawns the architect agent to
    analyze the failure and provide guidance.

    Reads QA feedback, engineer output, and original brief, then invokes
    the architect agent to classify and recommend: FIX, REDESIGN, or REPLAN.

.PARAMETER RoomDir
    Path to the war-room directory.
.PARAMETER TimeoutSeconds
    Override timeout. Default: from config.

.EXAMPLE
    ./Start-Architect.ps1 -RoomDir "./war-rooms/room-001"
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

# --- Load config ---
$configPath = if ($env:AGENT_OS_CONFIG) { $env:AGENT_OS_CONFIG }
              else { Join-Path $agentsDir "config.json" }

if (Test-Path $configPath) {
    $config = Get-Content $configPath -Raw | ConvertFrom-Json
    if ($TimeoutSeconds -eq 0 -and $config.architect -and $config.architect.timeout_seconds) {
        $TimeoutSeconds = $config.architect.timeout_seconds
    }
}
if ($TimeoutSeconds -eq 0) { $TimeoutSeconds = 300 }

# --- Read/Create per-role config file (architect_{id}.json) ---
$archConfigs = Get-ChildItem -Path $RoomDir -Filter "architect_*.json" -ErrorAction SilentlyContinue | Sort-Object Name -Descending
if ($archConfigs) {
    $archRoleConfig = Get-Content $archConfigs[0].FullName -Raw | ConvertFrom-Json
    $archRoleConfig.status = "active"
    $archRoleConfig | ConvertTo-Json -Depth 5 | Out-File -FilePath $archConfigs[0].FullName -Encoding utf8
    $archRoleConfigFile = $archConfigs[0].FullName
}
else {
    $archModel = "google-vertex/gemini-3-flash-preview"
    if ($config -and $config.architect -and $config.architect.default_model) {
        $archModel = $config.architect.default_model
    }
    $ts = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    $archRoleConfigObj = [ordered]@{
        role          = "architect"
        instance_id   = "001"
        instance_type = ""
        display_name  = "architect #001"
        model         = $archModel
        assigned_at   = $ts
        status        = "active"
        config_override = [ordered]@{}
    }
    $archRoleConfigFile = Join-Path $RoomDir "architect_001.json"
    $archRoleConfigObj | ConvertTo-Json -Depth 5 | Out-File -FilePath $archRoleConfigFile -Encoding utf8
}

# --- Read task ref ---
$taskRef = if (Test-Path (Join-Path $RoomDir "task-ref")) {
    (Get-Content (Join-Path $RoomDir "task-ref") -Raw).Trim()
} else { "UNKNOWN" }

# --- Read the original brief ---
$taskDesc = if (Test-Path (Join-Path $RoomDir "brief.md")) {
    Get-Content (Join-Path $RoomDir "brief.md") -Raw
} else { "No task description found." }

# --- Read the engineer's latest done message ---
$engineerReport = "No engineer report found."
try {
    $doneMsgs = & $readMessages -RoomDir $RoomDir -FilterType "done" -Last 1 -AsObject
    if ($doneMsgs -and $doneMsgs.Count -gt 0) {
        $engineerReport = $doneMsgs[-1].body
    }
}
catch { }

# --- Read QA failure or escalation ---
$qaFeedback = "No QA feedback found."
try {
    # Check for escalate first, then fail
    $escalateMsgs = & $readMessages -RoomDir $RoomDir -FilterType "escalate" -Last 1 -AsObject
    if ($escalateMsgs -and $escalateMsgs.Count -gt 0) {
        $qaFeedback = $escalateMsgs[-1].body
    } else {
        $failMsgs = & $readMessages -RoomDir $RoomDir -FilterType "fail" -Last 1 -AsObject
        if ($failMsgs -and $failMsgs.Count -gt 0) {
            $qaFeedback = $failMsgs[-1].body
        }
    }
}
catch { }

# --- Read manager's design-review request ---
$managerRequest = ""
try {
    $designMsgs = & $readMessages -RoomDir $RoomDir -FilterType "review" -Last 1 -AsObject
    if ($designMsgs -and $designMsgs.Count -gt 0) {
        $managerRequest = $designMsgs[-1].body
    }
}
catch { }

# --- Read latest plan review/update body for PLAN-REVIEW rooms ---
$planReviewBody = ""
if ($taskRef -eq 'PLAN-REVIEW') {
    try {
        $planMsgs = & $readMessages -RoomDir $RoomDir -FilterFrom "manager" -FilterType @('review', 'plan-update') -Last 1 -AsObject
        if ($planMsgs -and $planMsgs.Count -gt 0) {
            $planReviewBody = $planMsgs[-1].body
        }
    }
    catch { }
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

# --- Assemble final prompt using Build-SystemPrompt.ps1 ---
$buildPrompt = Join-Path $agentsDir "roles" "_base" "Build-SystemPrompt.ps1"
if ($taskRef -eq 'PLAN-REVIEW') {
    $extraContext = @"
## Context: Plan Review Assignment

You have been called to review the project plan and task breakdowns.

## Instructions

Analyze the provided plan details.
If the plan is well-specified, well-scoped, and ready for engineering implementation, approve it.
If it lacks critical details, provide architectural guidance on what must be improved.

If approving, call `memory_save` with the plan-review decision before posting `plan-approve`.
Do NOT use `signoff` for plan review approval.

IMPORTANT: Your response MUST conclude with exactly one of these lines:
  VERDICT: DONE
  VERDICT: REJECT
"@
    if ($planReviewBody) {
        $extraContext += @"

## Current Plan Review Body

$planReviewBody
"@
    }
}
else {
    $extraContext = @"
## Context: Architectural Review for $taskRef

You have been called to provide architectural oversight.

## Instructions

Provide detailed technical guidance and architectural advice for the current state.

IMPORTANT: Your response MUST conclude with exactly one of these lines:
  VERDICT: DONE
  VERDICT: REJECT
"@
    if ($managerRequest) {
        $extraContext += @"

## Manager Request

$managerRequest
"@
    }
}

$prompt = & $buildPrompt -RoleName "architect" -RolePath $scriptDir `
                         -RoomDir $RoomDir -TaskRef $taskRef `
                         -ExtraContext $extraContext

# --- Log start ---
if (Get-Command Write-OstwinLog -ErrorAction SilentlyContinue) {
    Write-OstwinLog -Level INFO -Message "Starting architect review of $taskRef in $(Split-Path $RoomDir -Leaf)"
}
else {
    Write-Host "[ARCHITECT] Starting review of $taskRef in $(Split-Path $RoomDir -Leaf)"
}

# --- Run the agent ---
$result = & $invokeAgent -RoomDir $RoomDir -RoleName "architect" `
                         -Prompt $prompt -TimeoutSeconds $TimeoutSeconds

$rawOutput = $result.Output
$outputArtifact = if ($result.PSObject.Properties.Name -contains "OutputFile" -and $result.OutputFile) {
    "artifacts/$(Split-Path $result.OutputFile -Leaf)"
} else {
    "agent output"
}

# --- Strip tool-calling noise from agent output ---
$cleanLines = ($rawOutput -split "`r?\n") | Where-Object {
    $line = $_.Trim()
    # Preserve empty lines for formatting
    if (-not $line) { return $true }

    # Strip specific noise patterns
    $isNoise = ($line -match '^🔧' -or
                $line -match '[Cc]alling tool:' -or
                $line -match '^\w{0,5}\s*tool:' -or
                $line -match '^Loading MCP' -or
                $line -match '^Running task non-interactively' -or
                $line -match '^Agent active' -or
                $line -match '^Usage Stats' -or
                $line -match '^\s*Reqs\s+InputTok' -or
                $line -match '^\s*google-vertex/gemini-' -or
                $line -match '^✓ Task completed' -or
                $line -match '^System\.Management\.Automation')
    
    return (-not $isNoise)
}
$output = ($cleanLines -join "`n").Trim()
if (-not $output) {
    $output = $rawOutput
}

$verdict = if (Get-Command Get-AgentVerdict -ErrorAction SilentlyContinue) {
    Get-AgentVerdict -Output $output
} else {
    ""
}

# Fallback for older installs without LifecycleSignal.psm1 loaded.
if (-not $verdict) {
    # Strategy 1: Line starts with VERDICT:
    if ($output -match '(?m)^VERDICT:\s*(DONE|PASS|REJECT)') {
        $verdict = $Matches[1].ToUpper()
    }

    # Strategy 2: VERDICT: anywhere in a line
    if (-not $verdict -and $output -match 'VERDICT:\s*(DONE|PASS|REJECT)') {
        $verdict = $Matches[1].ToUpper()
    }

    # Strategy 3: standalone DONE/REJECT in first 20 lines. PASS is accepted only as legacy compatibility.
    if (-not $verdict) {
        $first20 = ($output -split "`n" | Select-Object -First 20) -join "`n"
        if ($first20 -match '\b(DONE|PASS|REJECT)\b') {
            $verdict = $Matches[1].ToUpper()
        }
    }
}

# --- Default VERDICT injection for Evaluator consistency ---
# If architect gave feedback but forgot the keyword, assume DONE for oversight roles
if (-not $verdict) {
    $verdict = "DONE"
    $output += "`n`nVERDICT: DONE"
}

$displayVerdict = if ($verdict -eq "PASS") { "DONE" } else { $verdict }
$successSignal = if (Get-Command Get-PreferredLifecycleSuccessSignal -ErrorAction SilentlyContinue) {
    Get-PreferredLifecycleSuccessSignal -RoomDir $RoomDir -DefaultSignal "done"
} else { "done" }
$signalType = if (Get-Command Convert-VerdictToLifecycleSignal -ErrorAction SilentlyContinue) {
    Convert-VerdictToLifecycleSignal -Verdict $verdict -DefaultSuccessSignal $successSignal
} else {
    switch ($verdict) {
        "DONE"   { $successSignal }
        "PASS"   { $successSignal }
        "REJECT" { "fail" }
        default  { "" }
    }
}

# --- Handle agent result ---
if ($result.TimedOut) {
    $signalType = "error"
    $displayVerdict = "ERROR"
    if (Get-Command Write-OstwinLog -ErrorAction SilentlyContinue) {
        Write-OstwinLog -Level ERROR -Message "Timed out on $taskRef after ${TimeoutSeconds}s."
    }
}
elseif ($result.ExitCode -ne 0) {
    $signalType = "error"
    $displayVerdict = "ERROR"
    if (Get-Command Write-OstwinLog -ErrorAction SilentlyContinue) {
        Write-OstwinLog -Level ERROR -Message "Architect agent failed on $taskRef with exit code $($result.ExitCode)."
    }
}
elseif ($signalType -in @("done", "pass")) {
    if (Get-Command Write-OstwinLog -ErrorAction SilentlyContinue) {
        Write-OstwinLog -Level INFO -Message "DONE $taskRef."
    }
}
elseif ($signalType -eq "fail") {
    if (Get-Command Write-OstwinLog -ErrorAction SilentlyContinue) {
        Write-OstwinLog -Level INFO -Message "REJECTED $taskRef."
    }
}
else {
    if (Get-Command Write-OstwinLog -ErrorAction SilentlyContinue) {
        Write-OstwinLog -Level WARN -Message "Could not parse verdict for $taskRef — posting as error."
    }
}

if (Get-Command Write-LifecycleSignal -ErrorAction SilentlyContinue) {
    $body = if ($signalType -eq "error") {
        "VERDICT: ERROR`n`narchitect could not complete $taskRef cleanly. Full output: $outputArtifact"
    } else {
        "VERDICT: $displayVerdict`n`narchitect completed $taskRef with lifecycle signal '$signalType'. Full output: $outputArtifact"
    }
    $postType = if ($signalType) { $signalType } else { "error" }
    Write-LifecycleSignal -RoomDir $RoomDir -FromRole "architect" -Type $postType -Ref $taskRef -Body $body -SkipIfFresh | Out-Null
}

# --- PID file is NOT removed here (manager-owned lifecycle) ---
# The manager cleans up PID files when it processes the signal and transitions
# the room state. Removing PID here causes a race: manager polls, finds no PID,
# and re-spawns before processing the channel signal.

# --- Update per-role config status ---
if (Test-Path $archRoleConfigFile) {
    $archFinalConfig = Get-Content $archRoleConfigFile -Raw | ConvertFrom-Json
    $archFinalConfig.status = if ($signalType -in @("done", "pass")) { "completed" } else { "failed" }
    $archFinalConfig | ConvertTo-Json -Depth 5 | Out-File -FilePath $archRoleConfigFile -Encoding utf8
}

exit $result.ExitCode
