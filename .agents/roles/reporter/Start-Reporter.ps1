<#
.SYNOPSIS
    Reporter role runner — composes a report spec via agent, then generates PDF.

.DESCRIPTION
    Two-phase execution:
      Phase 1 — Launches deepagents with the reporter SKILL.md prompt to read
                the brief, gather data, and compose a JSON report spec file.
      Phase 2 — Runs `python -m reporter generate <spec>.json` to produce the
                actual PDF output.

    This custom runner exists because the reporter's PDF generation step is a
    deterministic Python module invocation, not an agent conversation. The
    generic Start-DynamicRole.ps1 would only run Phase 1 and rely on the agent
    to shell out — which requires shell access that may not be available.

.PARAMETER RoomDir
    Path to the war-room directory.
.PARAMETER TimeoutSeconds
    Override timeout. Default: from config or role.json (600s).

.EXAMPLE
    ./Start-Reporter.ps1 -RoomDir "./war-rooms/room-003"
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
$buildSystemPrompt = Join-Path $agentsDir "roles" "_base" "Build-SystemPrompt.ps1"
$getRoleDef = Join-Path $agentsDir "roles" "_base" "Get-RoleDefinition.ps1"
$postMessage = Join-Path $channelDir "Post-Message.ps1"
$readMessages = Join-Path $channelDir "Read-Messages.ps1"

$RoleName = "reporter"
$reporterDir = $scriptDir

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

# --- Load room config ---
$roomConfigFile = Join-Path $RoomDir "config.json"
if (-not (Test-Path $roomConfigFile)) {
    Write-Log "ERROR" "[reporter] config.json not found in war room: $RoomDir"
    exit 1
}
$roomConfig = Get-Content $roomConfigFile -Raw | ConvertFrom-Json

# --- Read task ref ---
$taskRef = if (Test-Path (Join-Path $RoomDir "task-ref")) {
    (Get-Content (Join-Path $RoomDir "task-ref") -Raw).Trim()
} else { "UNKNOWN" }

$roomName = Split-Path $RoomDir -Leaf

Write-Log "INFO" "[reporter] Starting reporter on $taskRef in $roomName"

# --- Process tracking (PID) ---
$pidDir = Join-Path $RoomDir "pids"
if (-not (Test-Path $pidDir)) { New-Item -ItemType Directory -Path $pidDir -Force | Out-Null }
$pidFile = Join-Path $pidDir "reporter.pid"
$PID | Out-File -FilePath $pidFile -Encoding utf8 -NoNewline

function Cleanup-And-Exit {
    param([int]$ExitCode, [string]$ErrorMsg = "")
    if ($ErrorMsg) {
        Write-Log "ERROR" "[reporter] Error: $ErrorMsg"
        & $postMessage -RoomDir $RoomDir -From $RoleName -To "manager" -Type "error" -Ref $taskRef -Body $ErrorMsg
    }
    # PID file is NOT removed here — manager-owned lifecycle
    exit $ExitCode
}

# --- Load global config ---
$configPath = if ($env:AGENT_OS_CONFIG) { $env:AGENT_OS_CONFIG }
              else { Join-Path $agentsDir "config.json" }

$config = $null
$maxPromptBytes = 102400
if (Test-Path $configPath) {
    $config = Get-Content $configPath -Raw | ConvertFrom-Json
    $roleConfig = $null
    if ($config.$RoleName) { $roleConfig = $config.$RoleName }
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
if (Test-Path $getRoleDef) {
    $roleDef = & $getRoleDef -RolePath $reporterDir
}

if ($TimeoutSeconds -eq 0) {
    $TimeoutSeconds = if ($roleDef -and $roleDef.Timeout) { $roleDef.Timeout } else { 600 }
}

$agentModel = if ($roleDef -and $roleDef.Model) { $roleDef.Model } else { "google-vertex/gemini-3-flash-preview" }

# --- Read per-role config file (reporter_{id}.json) ---
$roleInstanceModel = ""
$reporterConfigs = Get-ChildItem -Path $RoomDir -Filter "reporter_*.json" -ErrorAction SilentlyContinue | Sort-Object Name -Descending
if ($reporterConfigs) {
    $latestRoleConfig = Get-Content $reporterConfigs[0].FullName -Raw | ConvertFrom-Json
    if ($latestRoleConfig.model) { $roleInstanceModel = $latestRoleConfig.model }
    $latestRoleConfig.status = "active"
    $latestRoleConfig | ConvertTo-Json -Depth 5 | Out-File -FilePath $reporterConfigs[0].FullName -Encoding utf8
}

# --- Write per-role context.md ---
$contextsDir = Join-Path $RoomDir "contexts"
if (-not (Test-Path $contextsDir)) {
    New-Item -ItemType Directory -Path $contextsDir -Force | Out-Null
}
$contextFile = Join-Path $contextsDir "reporter.md"
@"
# Reporter Context

## Assignment
- Task: $taskRef
- Role: reporter
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

# --- Build the reporter-specific prompt ---
# The key difference: we instruct the agent to ONLY compose the spec JSON,
# NOT to run `python -m reporter`. Phase 2 handles PDF generation.
$rolePrompt = ""
if (Test-Path $buildSystemPrompt) {
    $rolePrompt = & $buildSystemPrompt -RoomDir $RoomDir -RolePath $reporterDir
} else {
    $skillPath = Join-Path $reporterDir "SKILL.md"
    if (Test-Path $skillPath) {
        $rolePrompt = Get-Content $skillPath -Raw
    } else {
        $rolePrompt = "# Reporter`n`nYou are a report generation specialist agent."
    }
}

# Artifacts directory for output
$artifactsDir = Join-Path $RoomDir "artifacts"
if (-not (Test-Path $artifactsDir)) {
    New-Item -ItemType Directory -Path $artifactsDir -Force | Out-Null
}

$specOutputPath = Join-Path $artifactsDir "report-spec.json"
$pdfOutputPath = Join-Path $artifactsDir "report.pdf"

$instructions = @"
You are composing a report. Follow these phases:

### Phase 1 — Gather & Compose
1. Read the task brief to understand what report is needed
2. Gather data from the project sources mentioned in the brief
3. Compose a complete report spec JSON following the spec format in your SKILL guide
4. Write the spec JSON to: $specOutputPath
   - Use the reporter's brand.json for branding (located at: $reporterDir/brand.json)
   - Set "brand_file" in the spec to: $reporterDir/brand.json
   - Set "output" in the spec to: $pdfOutputPath

### Phase 2 — Generate PDF
After writing the spec, generate the PDF by running:
```
PYTHONPATH='$(Split-Path $reporterDir)' python -m reporter generate '$specOutputPath' -o '$pdfOutputPath'
```

### Phase 3 — Report Completion
Summarize what was generated:
- Path to the generated PDF: $pdfOutputPath
- Report title and page count
- Components used
"@

$prompt = @"
$rolePrompt

---

## Your Task

$taskDesc

## Latest Instruction

$latestBody
$triageSection
## War-Room

Room: $roomName
Task Ref: $taskRef
Role: reporter
Working Directory: $(if ($workingDir) { $workingDir } else { Get-Location })
$predecessorSection
## Instructions

$instructions
"@

# --- Prompt size guard ---
if ($prompt.Length -gt $maxPromptBytes) {
    $originalSize = $prompt.Length
    $prompt = $prompt.Substring(0, $maxPromptBytes) + @"

[TRUNCATED: prompt was $originalSize bytes, max is $maxPromptBytes. Full task description in: $RoomDir/brief.md]
"@
    Write-Log "WARN" "[reporter] Prompt truncated from $originalSize to $maxPromptBytes bytes for $taskRef"
}

# ============================================================
# PHASE 1 — Run agent to compose the spec (and attempt PDF gen)
# ============================================================
Write-Log "INFO" "[reporter] Phase 1: Launching agent to compose report spec for $taskRef"

$invokeArgs = @{
    RoomDir        = $RoomDir
    RoleName       = $RoleName
    Prompt         = $prompt
    TimeoutSeconds = $TimeoutSeconds
}

# Model resolution: only pass explicit per-room instance model overrides.
# Do NOT pass the fallback $agentModel (from role.json / config.json) — let
# Invoke-Agent.ps1 resolve from plan.roles.json → config.json → role.json → default.
# This ensures the user's plan-level model configuration is respected.
if ($roleInstanceModel) { $invokeArgs['Model'] = $roleInstanceModel }

# Grant shell access so the agent can run python -m reporter
$invokeArgs['ExtraArgs'] = @("--dangerously-skip-permissions")

$result = & $invokeAgent @invokeArgs

# ============================================================
# PHASE 2 — If agent didn't produce the PDF, generate it now
# ============================================================
if ($result.ExitCode -eq 0 -and (Test-Path $specOutputPath) -and (-not (Test-Path $pdfOutputPath))) {
    Write-Log "INFO" "[reporter] Phase 2: Agent composed spec but didn't generate PDF. Running python -m reporter..."

    try {
        $rolesDir = Join-Path $agentsDir "roles"
        $env:PYTHONPATH = $rolesDir
        $phase2Output = & python -m reporter generate $specOutputPath -o $pdfOutputPath 2>&1
        $phase2Exit = $LASTEXITCODE
        if ($phase2Exit -ne 0) {
            Write-Log "WARN" "[reporter] Phase 2 PDF generation failed (exit $phase2Exit): $phase2Output"
            # Not fatal — report the spec was composed, note PDF failed
            $result = [PSCustomObject]@{
                ExitCode   = 0
                Output     = "$($result.Output)`n`n[PDF Generation Failed]`n$phase2Output`nSpec file is at: $specOutputPath"
                OutputFile = $result.OutputFile
                PidFile    = $result.PidFile
                RoleName   = $RoleName
                TimedOut   = $false
            }
        } else {
            Write-Log "INFO" "[reporter] Phase 2: PDF generated at $pdfOutputPath"
            $result = [PSCustomObject]@{
                ExitCode   = 0
                Output     = "$($result.Output)`n`n[PDF Generated]`nOutput: $pdfOutputPath`n$phase2Output"
                OutputFile = $result.OutputFile
                PidFile    = $result.PidFile
                RoleName   = $RoleName
                TimedOut   = $false
            }
        }
    } catch {
        Write-Log "WARN" "[reporter] Phase 2 exception: $($_.Exception.Message)"
    }
}

# ============================================================
# POST RESULTS
# ============================================================
if ($result.ExitCode -eq 0) {
    $body = $result.Output
    if (Test-Path $pdfOutputPath) {
        $body += "`n`nPDF: $pdfOutputPath"
    }
    & $postMessage -RoomDir $RoomDir -From $RoleName -To "manager" `
                   -Type "done" -Ref $taskRef -Body $body
    Write-Log "INFO" "[reporter] Completed $taskRef successfully."
}
elseif ($result.TimedOut) {
    & $postMessage -RoomDir $RoomDir -From $RoleName -To "manager" `
                   -Type "error" -Ref $taskRef -Body "Reporter timed out after ${TimeoutSeconds}s"
    Write-Log "ERROR" "[reporter] Timed out on $taskRef after ${TimeoutSeconds}s."
}
else {
    & $postMessage -RoomDir $RoomDir -From $RoleName -To "manager" `
                   -Type "error" -Ref $taskRef `
                   -Body "Reporter exited with code $($result.ExitCode): $($result.Output)"
    Write-Log "ERROR" "[reporter] Failed on $taskRef with exit code $($result.ExitCode)."
}

# --- Update per-role config status ---
if ($reporterConfigs) {
    $latestRoleConfig = Get-Content $reporterConfigs[0].FullName -Raw | ConvertFrom-Json
    $latestRoleConfig.status = if ($result.ExitCode -eq 0) { "completed" } else { "failed" }
    $latestRoleConfig | ConvertTo-Json -Depth 5 | Out-File -FilePath $reporterConfigs[0].FullName -Encoding utf8
}

# --- PID file is NOT removed here (manager-owned lifecycle) ---
# The manager cleans up PID files when it processes the signal and transitions
# the room state. Removing PID here causes a race: manager polls, finds no PID,
# and re-spawns before processing the channel signal.

exit $result.ExitCode
