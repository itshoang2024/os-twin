<#
.SYNOPSIS
    Parses a plan file and spawns war-rooms for each epic/task.

.DESCRIPTION
    Reads a plan markdown file, extracts epics and tasks with their goals
    and dependencies, creates war-rooms for each, builds the dependency
    graph (DAG), and starts the manager loop.

    Supports -Resume to restart from existing war-rooms without recreating them.

    Replaces: run.sh

.PARAMETER PlanFile
    Path to the plan markdown file.
.PARAMETER ProjectDir
    Project root. Default: current directory.
.PARAMETER DryRun
    Parse and show what would be created, but don't actually create rooms or start the loop.
.PARAMETER Resume
    Skip room creation, rebuild DAG from existing rooms, and restart the manager loop.
    Rooms in 'blocked' state will be reset to 'pending' if their upstream deps are no longer failed.
.PARAMETER Expand
    Automatically run plan expansion before creating rooms.
.PARAMETER Review
    Wait for human review and approval after plan expansion.

.EXAMPLE
    ./Start-Plan.ps1 -PlanFile "./plans/plan-001.md" -ProjectDir "/project"
    ./Start-Plan.ps1 -PlanFile "./plans/plan-001.md" -DryRun
    ./Start-Plan.ps1 -PlanFile "./plans/plan-001.md" -Resume
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$PlanFile,

    [string]$ProjectDir = (Get-Location).Path,

    [switch]$IgnorePlanWorkingDir,

    [switch]$DryRun,

    [switch]$Resume,

    [switch]$Expand,

    [switch]$Review,

    [switch]$SkipLoop,

    [switch]$Unified,

    [switch]$NonInteractive,

    [switch]$EnablePlanning,

    [ValidateSet('room-worktree','shared')]
    [string]$WorkspaceIsolation = 'shared'
)

# --- Resolve paths ---
# The agentsDir must point to the Ostwin *installation* (where scripts like
# New-WarRoom.ps1 and Start-ManagerLoop.ps1 live), NOT the target project's
# .agents folder which might only contain .war-rooms or project-local config.
#
# Resolution order:
#   1. $ProjectDir/.agents — but ONLY if it contains the required scripts
#   2. Script's own installation tree (keeps Start-Plan and helper scripts in sync)
#   3. $OSTWIN_HOME env var (installed global fallback)
$installDir = $PSScriptRoot | Split-Path   # e.g. /Users/paulaan/.ostwin

function Test-OstwinScriptTree {
    param([AllowEmptyString()][string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) { return $false }
    return (Test-Path (Join-Path $Path "war-rooms" "New-WarRoom.ps1")) -and
           (Test-Path (Join-Path $Path "plan" "Build-DependencyGraph.ps1"))
}

$agentsDir = $null
$projectAgentsDir = Join-Path $ProjectDir ".agents"
if (Test-OstwinScriptTree -Path $projectAgentsDir) {
    $agentsDir = $projectAgentsDir
} elseif (Test-OstwinScriptTree -Path $installDir) {
    $agentsDir = $installDir
} elseif ($env:OSTWIN_HOME -and (Test-Path $env:OSTWIN_HOME)) {
    $candidate = Join-Path $env:OSTWIN_HOME ".agents"
    if (Test-OstwinScriptTree -Path $candidate) {
        $agentsDir = $candidate
    } elseif (Test-OstwinScriptTree -Path $env:OSTWIN_HOME) {
        $agentsDir = $env:OSTWIN_HOME
    }
}

if (-not $agentsDir) {
    $agentsDir = $installDir
}

$newWarRoom = Join-Path $agentsDir "war-rooms" "New-WarRoom.ps1"
$managerLoop = Join-Path $agentsDir "roles" "manager" "Start-ManagerLoop.ps1"
$buildDag = Join-Path $agentsDir "plan" "Build-DependencyGraph.ps1"
$buildPlanningDag = Join-Path $agentsDir "plan" "Build-PlanningDAG.ps1"
$invokeAgent = Join-Path $agentsDir "roles" "_base" "Invoke-Agent.ps1"
$waitForMessage = Join-Path $agentsDir "channel" "Wait-ForMessage.ps1"

# --- Import modules ---
$logModule = Join-Path $agentsDir "lib" "Log.psm1"
if (Test-Path $logModule) { 
    $logModule = (Resolve-Path $logModule).Path
    Import-Module $logModule -Force 
}
$utilsModule = Join-Path $agentsDir "lib" "Utils.psm1"
if (Test-Path $utilsModule) { 
    $utilsModule = (Resolve-Path $utilsModule).Path
    Import-Module $utilsModule -Force 
}
$configModule = Join-Path $agentsDir "lib" "Config.psm1"
if (Test-Path $configModule) { 
    $configModule = (Resolve-Path $configModule).Path
    Import-Module $configModule -Force 
}
$planParserModule = Join-Path $agentsDir "lib" "PlanParser.psm1"
if (Test-Path $planParserModule) {
    $planParserModule = (Resolve-Path $planParserModule).Path
    Import-Module $planParserModule -Force
}
$eventsModule = Join-Path $agentsDir "events" "OrchestrationEvents.psm1"
if (Test-Path $eventsModule) {
    $eventsModule = (Resolve-Path $eventsModule).Path
    Import-Module $eventsModule -Force
}
$workspaceModule = Join-Path $agentsDir "workspace" "GitWorkspace.psm1"
if (Test-Path $workspaceModule) {
    $workspaceModule = (Resolve-Path $workspaceModule).Path
    Import-Module $workspaceModule -Force -DisableNameChecking
}

# --- Helper Functions ---
# (Test-Underspecified now in Utils.psm1)

# --- Validate plan file ---
if (-not (Test-Path $PlanFile -PathType Leaf)) {
    Write-Error "Plan file not found or is not a file: $PlanFile"
    exit 1
}

# --- Validate project dir ---
if (-not (Test-Path $ProjectDir -PathType Container)) {
    Write-Error "-ProjectDir must be a directory. It is currently set to: $ProjectDir. If you passed multiple files to 'ostwin run', the second file was interpreted as the ProjectDir."
    exit 1
}

# --- Resolve config ---
$configPath = if (Get-Command Resolve-OstwinConfigPath -ErrorAction SilentlyContinue) {
    Resolve-OstwinConfigPath
} elseif ($env:AGENT_OS_CONFIG) {
    $env:AGENT_OS_CONFIG
} else {
    Join-Path $agentsDir "config.json"
}
$config = Get-OstwinConfig -ConfigPath $configPath

$managerRuntime = if (Get-Command Get-OstwinManagerRuntimeSettings -ErrorAction SilentlyContinue) {
    Get-OstwinManagerRuntimeSettings -Config $config
} else {
    [PSCustomObject]@{
        max_concurrent_rooms  = if ($config.manager.max_concurrent_rooms) { $config.manager.max_concurrent_rooms } else { 10 }
        poll_interval_seconds = if ($config.manager.poll_interval_seconds) { $config.manager.poll_interval_seconds } else { 5 }
        max_engineer_retries  = if ($null -ne $config.manager.max_engineer_retries) { $config.manager.max_engineer_retries } else { 3 }
        state_timeout_seconds = if ($config.manager.state_timeout_seconds) { $config.manager.state_timeout_seconds } else { 900 }
        auto_approve_tools    = if ($null -ne $config.manager.auto_approve_tools) { [bool]$config.manager.auto_approve_tools } else { $false }
        dynamic_pipelines     = if ($null -ne $config.manager.dynamic_pipelines) { [bool]$config.manager.dynamic_pipelines } else { $true }
    }
}
$defaultRoomMaxRetries = [int]$managerRuntime.max_engineer_retries
$defaultRoomTimeoutSeconds = [int]$managerRuntime.state_timeout_seconds

if ($config.manager -and $config.manager.unified_plan_negotiation -eq $true) {
    $Unified = $true
}

# --- Resolve timeout ---
# $planReviewTimeout = ... (deprecated in favor of channel timeouts)
if ($env:PLAN_REVIEW_TIMEOUT_SECONDS) {
    $planReviewTimeout = [int]$env:PLAN_REVIEW_TIMEOUT_SECONDS
} elseif ($config.manager.plan_review_timeout_seconds) {
    $planReviewTimeout = [int]$config.manager.plan_review_timeout_seconds
}

# --- Resolve war-rooms directory (provisional — finalized after plan parsing) ---
$warRoomsDir = if ($env:WARROOMS_DIR) { $env:WARROOMS_DIR }
               else { Join-Path $ProjectDir ".war-rooms" }
$env:WARROOMS_DIR = $warRoomsDir
$warRoomsDirFromEnv = [bool]$env:WARROOMS_DIR -and -not ($env:WARROOMS_DIR -eq (Join-Path $ProjectDir ".war-rooms"))
$skipPlanReview = $env:OSTWIN_SKIP_PLAN_REVIEW -and ($env:OSTWIN_SKIP_PLAN_REVIEW -match '^(1|true|yes)$')

# --- Bootstrap room-000 for plan negotiation ---
$room000Dir = Join-Path $warRoomsDir "room-000"
$negotiationTask = @"
Unified Plan Negotiation

The project plan at '$PlanFile' requires review and potential refinement. 

### Your Instructions:
1. Read the current plan from the filesystem.
2. Verify if epics/tasks are well-specified (detailed Description, DoD, and AC).
3. If underspecified or if you see improvements, refine the plan in-place using your tools.
4. Once the plan is ready for implementation, post a 'plan-approve' message to the channel.
5. If you cannot proceed without more context, post 'plan-reject' with your feedback.
"@
if ($skipPlanReview) {
    Write-Host "[PLAN] Skipping synthetic PLAN-REVIEW room (OSTWIN_SKIP_PLAN_REVIEW=true)." -ForegroundColor Yellow
    if (-not $DryRun -and (Test-Path $room000Dir)) {
        Remove-Item -Path $room000Dir -Recurse -Force
    }
} elseif (-not $DryRun -and -not (Test-Path $room000Dir)) {
    & $newWarRoom -RoomId "room-000" -TaskRef "PLAN-REVIEW" -TaskDescription $negotiationTask -WarRoomsDir $warRoomsDir -WorkingDir $ProjectDir -AssignedRole "architect" -CandidateRoles @("architect","manager") -MaxRetries $defaultRoomMaxRetries -TimeoutSeconds $defaultRoomTimeoutSeconds | Out-Null
} elseif (-not $DryRun -and (Test-Path $room000Dir)) {
    # --- Update room-000 if the plan file has changed ---
    $room000Config = Join-Path $room000Dir "config.json"
    if (Test-Path $room000Config) {
        $r0cfg = Get-Content $room000Config -Raw | ConvertFrom-Json
        $oldDesc = if ($r0cfg.assignment -and $r0cfg.assignment.description) { $r0cfg.assignment.description } else { "" }
        if ($oldDesc -and $oldDesc -notmatch [regex]::Escape($PlanFile)) {
            Write-Warning "room-000 references a different plan file. Updating to current plan: $PlanFile"
            $r0cfg.assignment.description = $negotiationTask
            $r0cfg.assignment.title = "Unified Plan Negotiation"
            $r0cfg | ConvertTo-Json -Depth 10 | Out-File -FilePath $room000Config -Encoding utf8
            # Update brief.md
            $briefFile = Join-Path $room000Dir "brief.md"
            if (Test-Path $briefFile) {
                "# PLAN-REVIEW`n`n$negotiationTask" | Out-File -FilePath $briefFile -Encoding utf8
            }
            # Reset status if stuck on old plan
            $r0Status = if (Test-Path (Join-Path $room000Dir "status")) { (Get-Content (Join-Path $room000Dir "status") -Raw).Trim() } else { "pending" }
            if ($r0Status -in @('developing', 'optimize', 'review', 'triage', 'failed', 'failed-final')) {
                Write-Host "  → Resetting room-000 to pending (was: $r0Status)" -ForegroundColor Yellow
                "pending" | Out-File -FilePath (Join-Path $room000Dir "status") -Encoding utf8 -NoNewline
                # Do not mutate channel.jsonl here. Channel content is owned by
                # agents posting through the ostwin-channel MCP post_message tool.
                # Clear old PID files
                $pidDir = Join-Path $room000Dir "pids"
                if (Test-Path $pidDir) { Get-ChildItem $pidDir -Filter "*.pid" | Remove-Item -Force -ErrorAction SilentlyContinue }
            }
        }
    }
}

# --- Check for refined plan ---
$refinedFile = $PlanFile -replace '\.md$', '.refined.md'
if ((-not $Expand) -and (Test-Path $refinedFile) -and ($PlanFile -notmatch '\.refined\.md$')) {
    Write-Host "Using Existing Refined Plan: $refinedFile" -ForegroundColor Cyan
    $PlanFile = $refinedFile
}

# --- Plan Expansion Logic (Requirement 6) ---
$planContent = Get-Content $PlanFile -Raw
$isUnderspecified = Test-Underspecified -Content $planContent

if ($isUnderspecified) {
    Write-Host "Detected underspecified epics" -ForegroundColor Cyan
}

$expandPlanScript = Join-Path $agentsDir "plan" "Expand-Plan.ps1"
$shouldExpand = $Expand -or ($isUnderspecified -and $config.manager.auto_expand_plan -eq $true)
if ($shouldExpand -and (Test-Path $expandPlanScript)) {
    Write-OstwinLog -Message "Detected underspecified epics or forced expansion. Running Expand-Plan..." -Level "INFO" -Caller "manager"
    $expandOutFile = $PlanFile -replace '\.md$', '.refined.md'
    if ($DryRun) {
        Write-Host "  [DRY RUN] Would expand epics (e.g. EPIC-001) in $PlanFile → $expandOutFile" -ForegroundColor Yellow
    } else {
        & $expandPlanScript -PlanFile $PlanFile -OutFile $expandOutFile
        if ($LASTEXITCODE -eq 0) {
            Write-Host "Plan expanded successfully: $expandOutFile" -ForegroundColor Green
            
            # Log for manager review (Requirement for tests)
            if (Get-Command Write-OstwinLog -ErrorAction SilentlyContinue) {
                $diff = "Expansion diff placeholder" 
                if (Get-Command git -ErrorAction SilentlyContinue) { $diff = git diff --no-index $PlanFile $expandOutFile }
                Write-OstwinLog -Message "Plan expansion diff:`n$diff`n" -Level "INFO" -Caller "manager"
            }

            $PlanFile = $expandOutFile
            $planContent = Get-Content $PlanFile -Raw
        }
    }
}

# --- Parse plan: extract ALL epics and tasks (Requirement 1) ---
# Parse global working_dir from PLAN.md
if (-not $IgnorePlanWorkingDir -and $planContent -match '(?m)^working_dir:\s*(.+)$') {
    $globalWorkingDir = $Matches[1].Trim()
    if ($globalWorkingDir -and $globalWorkingDir -ne '...') {
        $workingDirWarningShown = $false
        if (-not (Test-Path $globalWorkingDir)) {
            if ($WorkspaceIsolation -eq 'shared' -and -not $DryRun) {
                try {
                    Write-Host "  Creating working_dir: $globalWorkingDir" -ForegroundColor DarkGray
                    New-Item -ItemType Directory -Path $globalWorkingDir -Force -ErrorAction Stop | Out-Null
                } catch {
                    Write-Host "  working_dir not found: $globalWorkingDir" -ForegroundColor Yellow
                    $workingDirWarningShown = $true
                }
            } else {
                Write-Host "  working_dir not found: $globalWorkingDir" -ForegroundColor Yellow
                $workingDirWarningShown = $true
            }
        }
        if (Test-Path $globalWorkingDir) {
            $ProjectDir = (Resolve-Path $globalWorkingDir).Path
            Write-Host "  Project: $ProjectDir" -ForegroundColor DarkGray
            # Re-resolve war-rooms dir to follow the plan's working_dir (unless explicitly set via env)
            if (-not $warRoomsDirFromEnv) {
                $warRoomsDir = Join-Path $ProjectDir ".war-rooms"
                $env:WARROOMS_DIR = $warRoomsDir
                $room000Dir = Join-Path $warRoomsDir "room-000"
            }
        } elseif (-not $workingDirWarningShown) {
            Write-Host "  working_dir not found: $globalWorkingDir" -ForegroundColor Yellow
        }
    }
}

# --- Parse plan: extract ALL epics and tasks via PlanParser module (Requirement 1) ---
$parsed = ConvertFrom-PlanMarkdown -Content $planContent

# --- Auto-generate EPICs when plan has only a goal ---
if ($parsed.Count -eq 0) {
    # Extract goal from plan title or content
    $goalTitle = ""
    if ($planContent -match '(?m)^#\s+(?:Plan|PLAN):\s*(.+)$') {
        $goalTitle = $Matches[1].Trim()
    }
    $goalBody = $planContent -replace '(?s)^#\s+.*?\n', '' `
                             -replace '(?m)^##\s+Config\b.*?(?=^##|\z)', '' `
                             -replace '(?m)^>\s+.*$', '' `
                             -replace '(?m)^working_dir:\s*.*$', ''
    $goalBody = $goalBody.Trim()

    if (-not $goalTitle -and -not $goalBody) {
        Write-Error "No epics, tasks, or goal found in plan file: $PlanFile"
        exit 1
    }

    Write-Host ""
    Write-Host "[PLAN] No EPICs found — generating from goal: $goalTitle" -ForegroundColor Cyan

    if ($DryRun) {
        Write-Host "  [DRY RUN] Would generate EPICs from goal via AI architect." -ForegroundColor Yellow
        exit 0
    }

    $generatePrompt = @"
You are a Senior Software Architect. Given a project goal, generate a structured set of EPICs that fully implement it.

## Project Goal
$goalTitle

## Context
$goalBody

## Instructions
1. Break this goal into 2-6 concrete EPICs — each independently deliverable.
2. For each EPIC include:
   - A descriptive title
   - 2-3 sentence description
   - Definition of Done (5+ checkboxes)
   - Acceptance Criteria (5+ checkboxes)
   - depends_on: [] (use real dependencies only if one EPIC truly needs another to finish first)
3. Prefer parallel EPICs — only add depends_on when genuinely required.

## Format
Return ONLY the EPIC sections in markdown. Use this exact format:

## EPIC-001 - Title Here

Description paragraph.

#### Definition of Done
- [ ] Item 1
- [ ] Item 2
...

#### Acceptance Criteria
- [ ] Scenario 1
- [ ] Scenario 2
...

depends_on: []

## EPIC-002 - Next Title
...
"@

    $genResult = & $invokeAgent -RoomDir $room000Dir -RoleName "architect" `
                                -Prompt $generatePrompt -TimeoutSeconds 300

    if ($genResult.ExitCode -ne 0) {
        Write-Error "Epic generation failed: $($genResult.Output)"
        exit 1
    }

    $generatedEpics = $genResult.Output.Trim()
    # Strip markdown fences if AI wrapped output
    $generatedEpics = $generatedEpics -replace '(?s)^```(?:markdown|md)?\s*', '' -replace '(?s)\s*```$', ''

    # Verify at least one EPIC was generated
    if ($generatedEpics -notmatch '(?m)^#{2,3}\s+EPIC-\d+') {
        Write-Error "AI did not generate valid EPICs. Output: $($generatedEpics.Substring(0, [Math]::Min(200, $generatedEpics.Length)))"
        exit 1
    }

    # Append generated EPICs to the plan file
    $separator = "`n`n---`n`n"
    $updatedPlan = $planContent.TrimEnd() + $separator + $generatedEpics + "`n"
    $updatedPlan | Out-File -FilePath $PlanFile -Encoding utf8
    Write-Host "[PLAN] Generated EPICs appended to: $PlanFile" -ForegroundColor Green

    # Sync to dashboard
    $resolvedPlanId = [IO.Path]::GetFileNameWithoutExtension($PlanFile) -replace '\.refined$', ''
    $dashboardUrl = if ($env:DASHBOARD_URL) { $env:DASHBOARD_URL } else { 'http://localhost:3366' }
    $apiHeaders = if (Get-Command Get-OstwinApiHeaders -ErrorAction SilentlyContinue) { Get-OstwinApiHeaders } else { @{} }
    try {
        $saveBody = @{ content = $updatedPlan; change_source = 'epic_generation' } | ConvertTo-Json -Depth 5
        Invoke-RestMethod -Uri "$dashboardUrl/api/plans/$resolvedPlanId/save" `
            -Method Post -ContentType 'application/json' -Body $saveBody -Headers $apiHeaders -ErrorAction Stop | Out-Null
        Write-Host "[PLAN] Synced generated EPICs to dashboard." -ForegroundColor Cyan
    } catch {
        Write-Host "[PLAN] Dashboard not reachable — plan updated locally only." -ForegroundColor Yellow
    }

    # Re-parse the plan with generated EPICs via PlanParser module
    $planContent = Get-Content $PlanFile -Raw
    $parsed = ConvertFrom-PlanMarkdown -Content $planContent

    if ($parsed.Count -eq 0) {
        Write-Error "Epic generation produced no parseable EPICs. Check AI output."
        exit 1
    }

    Write-Host "[PLAN] Generated $($parsed.Count) EPICs from goal." -ForegroundColor Green
}

# --- Auto-inject PLAN-REVIEW as a dependency (Requirement 2) ---
if (-not $skipPlanReview) {
    foreach ($item in $parsed) {
        if ($item.DependsOn -notcontains "PLAN-REVIEW") {
            $item.DependsOn = @("PLAN-REVIEW") + $item.DependsOn
        }
    }
}

# --- Generate / load planning-DAG.json for advisory role assignment ---
$planDir = Split-Path $PlanFile
if (-not $planDir) { $planDir = "." }
$planningDagFile = Join-Path $planDir ".planning-DAG.json"
if ($EnablePlanning -and -not $DryRun -and (Test-Path $buildPlanningDag)) {
    if (-not (Test-Path $planningDagFile) -or $Expand) {
        Write-Host "[PLANNING-DAG] Generating advisory DAG from plan content..." -ForegroundColor Cyan
        if ($env:OSTWIN_AGENT_CMD) {
            & $buildPlanningDag -PlanFile $PlanFile -OutFile $planningDagFile -AgentCmd $env:OSTWIN_AGENT_CMD
        } else {
            & $buildPlanningDag -PlanFile $PlanFile -OutFile $planningDagFile
        }
    }
    # Merge planning-DAG roles AND dependencies into parsed entries (advisory)
    if (Test-Path $planningDagFile) {
        try {
            $planningDag = Get-Content $planningDagFile -Raw | ConvertFrom-Json
            foreach ($pdNode in $planningDag.nodes) {
                $matchedEntry = $parsed | Where-Object { $_.TaskRef -eq $pdNode.task_ref }
                if (-not $matchedEntry) { continue }

                # --- Merge advisory roles (only where no explicit Roles: directive in markdown) ---
                if (-not $matchedEntry.HasExplicitRoles -and $pdNode.role) {
                    Write-Host "  [PLANNING-DAG] $($pdNode.task_ref): role $($matchedEntry.Roles[0]) → $($pdNode.role) (advisory)" -ForegroundColor Yellow
                    $matchedEntry.Roles = @($pdNode.candidate_roles)
                }

                # --- Merge advisory depends_on (only where no explicit depends_on in markdown) ---
                # If the entry only has the auto-injected PLAN-REVIEW dependency (no author-specified deps),
                # adopt the AI-suggested inter-epic dependencies.
                $hasExplicitDeps = $matchedEntry.DependsOn | Where-Object { $_ -ne 'PLAN-REVIEW' }
                if (-not $hasExplicitDeps -and $pdNode.depends_on -and @($pdNode.depends_on).Count -gt 0) {
                    $aiDeps = @($pdNode.depends_on) | Where-Object { $_ -and $_ -ne 'PLAN-REVIEW' }
                    if ($aiDeps.Count -gt 0) {
                        $matchedEntry.DependsOn = @("PLAN-REVIEW") + $aiDeps
                        Write-Host "  [PLANNING-DAG] $($pdNode.task_ref): deps → $($matchedEntry.DependsOn -join ', ') (advisory)" -ForegroundColor Yellow
                    }
                }
            }
        } catch {
            Write-Warning "Failed to read planning-DAG.json: $_"
        }
    }
}

# --- Extract plan_id ---
# If the filename is already a hex hash (12+ hex chars, from dashboard), use it directly.
# Otherwise, generate a stable hash from working_dir + filename to avoid collisions
# between plans with the same name in different directories.
$planStem = [System.IO.Path]::GetFileNameWithoutExtension($PlanFile)
$planStem = $planStem -replace '\.refined$', ''

if ($planStem -match '^[0-9a-fA-F]{8,64}$') {
    # Already a hash ID (dashboard-created plan)
    $planId = $planStem
} elseif ($planStem -and $planStem -ne 'PLAN.template') {
    # CLI plan — generate stable hash from working_dir + filename
    $hashInput = "${ProjectDir}:${planStem}"
    $sha = [System.Security.Cryptography.SHA256]::Create()
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($hashInput)
    $hash = $sha.ComputeHash($bytes)
    $planId = [BitConverter]::ToString($hash).Replace('-', '').Substring(0, 12).ToLower()
    Write-Host "  Plan ID: $planId (from $planStem)" -ForegroundColor DarkGray
} else {
    # Fallback: extract from embedded JSON config
    if ($planContent -match '"plan_id"\s*:\s*"([^"]+)"') {
        $planId = $Matches[1]
    } else {
        $planId = "_global"
    }
}

# --- Establish orchestration event execution context ---
$eventsPath = ''
$env:OSTWIN_PLAN_ID = $planId
$runId = "run_$([guid]::NewGuid().ToString('N'))"
$env:OSTWIN_RUN_ID = $runId
Remove-Item Env:OSTWIN_EVENTS_PATH -ErrorAction SilentlyContinue

# EPIC-003 resume rule: v1 refuses to append a contradictory continuation to
# an event history that has already recorded plan.run.failed. A future archival
# run-id flow may permit explicit resume into a fresh log.
if ($Resume -and $eventsPath -and (Test-Path $eventsPath)) {
    try {
        $hasFailedRun = $false
        foreach ($line in (Get-Content $eventsPath -ErrorAction Stop)) {
            if ([string]::IsNullOrWhiteSpace($line)) { continue }
            try {
                $evt = $line | ConvertFrom-Json
                if ($evt.event_type -eq 'plan.run.failed') { $hasFailedRun = $true; break }
            } catch { }
        }
        if ($hasFailedRun) {
            Write-Error "Cannot resume plan '$planId': events.jsonl already contains plan.run.failed. Use an explicit retry/reset that creates a fresh event log."
            exit 1
        }
    } catch {
        Write-Error "Cannot verify resume safety for plan '$planId': $($_.Exception.Message)"
        exit 1
    }
}

$workspaceManifest = $null
if (-not $DryRun) {
    if ($WorkspaceIsolation -eq 'room-worktree' -and -not (Get-Command Initialize-PlanIntegrationWorkspace -ErrorAction SilentlyContinue)) {
        Write-Error "Workspace isolation requires workspace/GitWorkspace.psm1, but Initialize-PlanIntegrationWorkspace is unavailable."
        exit 1
    }

    $workspaceManifestPath = Join-Path $warRoomsDir 'workspace.json'
    if ($Resume -and (Test-Path $workspaceManifestPath) -and (Get-Command Get-PlanWorkspaceManifest -ErrorAction SilentlyContinue)) {
        $workspaceManifest = Get-PlanWorkspaceManifest -WarRoomsDir $warRoomsDir
        if ($workspaceManifest -and ($workspaceManifest.PSObject.Properties.Name -contains 'run_id') -and $workspaceManifest.run_id) {
            $runId = "$($workspaceManifest.run_id)"
            $env:OSTWIN_RUN_ID = $runId
        }
    } elseif (Get-Command Initialize-PlanIntegrationWorkspace -ErrorAction SilentlyContinue) {
        try {
            $workspaceManifest = Initialize-PlanIntegrationWorkspace `
                -WarRoomsDir $warRoomsDir `
                -PlanId $planId `
                -RunId $runId `
                -SourceWorkingDir $ProjectDir `
                -WorkspaceIsolation $WorkspaceIsolation
        } catch {
            Write-Error "Workspace initialization failed: $($_.Exception.Message)"
            exit 1
        }
    } elseif ($WorkspaceIsolation -eq 'shared') {
        $workspaceManifest = $null
    }
}

# room-000 is created before the final plan_id is known. Reconcile its config so
# negotiation, dashboard, and channel layers share the same execution context.
$room000Config = Join-Path $room000Dir 'config.json'
if (-not $DryRun -and (Test-Path $room000Config)) {
    try {
        $r0cfg = Get-Content $room000Config -Raw | ConvertFrom-Json
        $r0cfg.plan_id = $planId
        if ($r0cfg.PSObject.Properties.Name -contains 'events_path') {
            $r0cfg.PSObject.Properties.Remove('events_path')
        }
        if ($r0cfg.PSObject.Properties.Name -contains 'run_id') {
            $r0cfg.run_id = $runId
        } else {
            $r0cfg | Add-Member -NotePropertyName run_id -NotePropertyValue $runId
        }
        if ($r0cfg.PSObject.Properties.Name -contains 'workspace') {
            $r0cfg.PSObject.Properties.Remove('workspace')
        }
        $r0cfg | ConvertTo-Json -Depth 10 | Out-File -FilePath $room000Config -Encoding utf8
    } catch {
        Write-Warning "Failed to stamp room-000 config with orchestration event context: $_"
    }
}

if (-not $DryRun -and (Get-Command Write-OrchestrationEvent -ErrorAction SilentlyContinue)) {
    $startedEvent = [ordered]@{
        event_type = 'plan.run.started'
        plan_id    = $planId
        run_id     = $runId
        summary    = "Plan run started for $planId."
        payload    = [ordered]@{
            plan_file    = $PlanFile
            project_dir  = $ProjectDir
            warrooms_dir = $warRoomsDir
            resume       = [bool]$Resume
            run_id       = $runId
            skip_loop    = [bool]$SkipLoop
        }
    }
    Write-OrchestrationEvent -Event $startedEvent | Out-Null
}

# --- Register plan in the local registry so the dashboard can see it ---
if (-not $DryRun) {
    try {
        $plansDir = Join-Path $agentsDir "plans"
        if (-not (Test-Path $plansDir)) {
            New-Item -ItemType Directory -Path $plansDir -Force | Out-Null
        }

        $registryPlanFile = Join-Path $plansDir "$planId.md"
        $resolvedPlanFile = (Resolve-Path $PlanFile).Path
        $resolvedRegistryFile = $null
        if (Test-Path $registryPlanFile) {
            $resolvedRegistryFile = (Resolve-Path $registryPlanFile).Path
        }

        if (-not $resolvedRegistryFile -or $resolvedRegistryFile -ne $resolvedPlanFile) {
            $shouldCopy = $true
            if (Test-Path $registryPlanFile) {
                $srcTime = (Get-Item $PlanFile).LastWriteTimeUtc
                $dstTime = (Get-Item $registryPlanFile).LastWriteTimeUtc
                $shouldCopy = $srcTime -gt $dstTime
            }
            if ($shouldCopy) {
                Copy-Item -Path $PlanFile -Destination $registryPlanFile -Force
            }
        }

        $metaFile = Join-Path $plansDir "$planId.meta.json"
        $meta = @{}
        if (Test-Path $metaFile) {
            try {
                $existing = Get-Content $metaFile -Raw | ConvertFrom-Json
                if ($existing) {
                    foreach ($prop in $existing.PSObject.Properties) {
                        $meta[$prop.Name] = $prop.Value
                    }
                }
            } catch {
                $meta = @{}
            }
        }

        $title = $planId
        if ($planContent -match '(?m)^#\s*(?:Plan|PLAN):\s*(.+)$') {
            $title = $Matches[1].Trim()
        }

        $meta["plan_id"] = $planId
        $meta["run_id"] = $runId
        if ($title) { $meta["title"] = $title }
        if (-not $meta["created_at"]) { $meta["created_at"] = (Get-Date).ToUniversalTime().ToString("o") }
        if (-not $meta["status"] -or $meta["status"] -in @("draft","stored")) { $meta["status"] = "active" }
        if ($ProjectDir) { $meta["working_dir"] = $ProjectDir }
        if ($ProjectDir) { $meta["warrooms_dir"] = (Join-Path $ProjectDir ".war-rooms") }
        $meta["launched_at"] = (Get-Date).ToUniversalTime().ToString("o")
        $meta["source_plan_file"] = $PlanFile

        $meta | ConvertTo-Json -Depth 10 | Out-File -FilePath $metaFile -Encoding utf8
    } catch {
        Write-Warning "Failed to register plan for dashboard: $_"
    }
}

# --- Manager Pre-flight skill coverage check ---
$testSkillCoverage = Join-Path $agentsDir "plan" "Test-SkillCoverage.ps1"
if (Test-Path $testSkillCoverage) {
    & $testSkillCoverage -PlanParsed $parsed -ProjectDir $ProjectDir -RoomDir $room000Dir | Out-Null
}

# --- Display what will be created ---
Write-Host ""
Write-Host "=== Ostwin Plan Launcher ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Plan: $PlanFile"
Write-Host "  Plan ID: $planId"
Write-Host "  Project: $ProjectDir"
Write-Host "  Workspace isolation: $WorkspaceIsolation"

function Get-ResumeStatusBeforeFailed {
    param([Parameter(Mandatory)][string]$RoomDir)

    $auditFile = Join-Path $RoomDir "audit.log"
    if (-not (Test-Path $auditFile)) { return $null }

    $lines = @(Get-Content $auditFile -ErrorAction SilentlyContinue)
    for ($i = $lines.Count - 1; $i -ge 0; $i--) {
        $line = $lines[$i]
        if ($line -match '^\S+\s+STATUS\s+(?<from>\S+)\s+->\s+(?<to>\S+)') {
            $from = $Matches['from']
            $to = $Matches['to']
            if ($to -in @('failed', 'failed-final') -and $from -notin @('failed', 'failed-final', 'done', 'passed')) {
                return $from
            }
        }
    }

    return $null
}

if ($Resume) {
    Write-Host "  Mode: RESUME (using existing war-rooms)" -ForegroundColor Yellow
    
    # --- RESUME NORMALIZATION: canonicalize legacy statuses and clear restartable blocked rooms ---
    $targetWarRoomsDir = Join-Path $ProjectDir ".war-rooms"
    if (Test-Path $targetWarRoomsDir) {
        $resumeEpoch = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
        $rooms = Get-ChildItem -Path $targetWarRoomsDir -Directory -Filter "room-*" -ErrorAction SilentlyContinue
        foreach ($rd in $rooms) {
            # Resume starts a fresh retry budget; subsequent fail signals/events
            # consume retries from zero during the resumed run.
            "0" | Out-File -FilePath (Join-Path $rd.FullName "retries") -Encoding utf8 -NoNewline
            Remove-Item (Join-Path $rd.FullName "qa_retries") -Force -ErrorAction SilentlyContinue
            Remove-Item (Join-Path $rd.FullName "crash_respawns") -Force -ErrorAction SilentlyContinue

            # Reset process-level runtime markers for all rooms. The manager loop
            # should restart from the restored status, not from stale PIDs/locks.
            $pidDir = Join-Path $rd.FullName "pids"
            if (Test-Path $pidDir) {
                Get-ChildItem $pidDir -Filter "*.pid" -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
                Get-ChildItem $pidDir -Filter "*.spawned_at" -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
            }

            # Discard stale role-wrapper status from the previous process/run.
            # Otherwise a prior qa_*.json status=failed can look fresh relative
            # to the old state_changed_at and fail-fast the resumed run.
            foreach ($roleRunFile in (Get-ChildItem -Path $rd.FullName -Filter "*.json" -File -ErrorAction SilentlyContinue)) {
                if ($roleRunFile.Name -in @('config.json', 'lifecycle.json', 'DAG.json', 'progress.json')) { continue }
                try {
                    $roleRun = Get-Content $roleRunFile.FullName -Raw | ConvertFrom-Json
                    if (-not ($roleRun.PSObject.Properties['role'] -and $roleRun.PSObject.Properties['instance_id'])) { continue }
                    if ($roleRun.PSObject.Properties['status']) { $roleRun.status = 'pending' }
                    foreach ($propName in @('status_updated_epoch', 'status_updated_at', 'status_state')) {
                        if ($roleRun.PSObject.Properties[$propName]) { $roleRun.PSObject.Properties.Remove($propName) }
                    }
                    $roleRun | ConvertTo-Json -Depth 10 | Out-File -FilePath $roleRunFile.FullName -Encoding utf8
                } catch { }
            }

            $statusFile = Join-Path $rd.FullName "status"
            if (Test-Path $statusFile) {
                $status = (Get-Content $statusFile -Raw).Trim()
                if ($status -eq "passed") {
                    Write-Host "  → Normalizing $($rd.Name) from passed to done" -ForegroundColor Yellow
                    "done" | Out-File -FilePath $statusFile -Encoding utf8 -NoNewline
                } elseif ($status -in @("failed", "failed-final")) {
                    $resumeStatus = Get-ResumeStatusBeforeFailed -RoomDir $rd.FullName
                    if (-not $resumeStatus) { $resumeStatus = "developing" }
                    Write-Host "  → Restoring $($rd.Name) from $status to $resumeStatus (pre-failed audit state)" -ForegroundColor Yellow
                    $resumeStatus | Out-File -FilePath $statusFile -Encoding utf8 -NoNewline
                } elseif ($status -eq "fixing") {
                    Write-Host "  → Normalizing $($rd.Name) from fixing to optimize" -ForegroundColor Yellow
                    "optimize" | Out-File -FilePath $statusFile -Encoding utf8 -NoNewline
                } elseif ($status -eq "blocked") {
                    Write-Host "  → Resetting $($rd.Name) to pending (was: $status)" -ForegroundColor Yellow
                    "pending" | Out-File -FilePath $statusFile -Encoding utf8 -NoNewline
                }

                $normalizedStatus = (Get-Content $statusFile -Raw).Trim()
                if ($normalizedStatus -notin @('done', 'failed')) {
                    $resumeEpoch.ToString() | Out-File -FilePath (Join-Path $rd.FullName "state_changed_at") -Encoding utf8 -NoNewline
                }
            }
        }
    }
    
    # Rebuild progress.json and PROGRESS.md to reflect the resets
    $updateProgressScript = Join-Path $agentsDir "plan" "Update-Progress.ps1"
    if (Test-Path $updateProgressScript) {
        & $updateProgressScript -WarRoomsDir $warRoomsDir
    }
} else {
    $syntheticRoomCount = if ($skipPlanReview) { 0 } else { 1 }
    Write-Host "  War-rooms to create: $($parsed.Count + $syntheticRoomCount)"
}
Write-Host ""
if (-not $skipPlanReview) {
    Write-Host "  room-000 → PLAN-REVIEW — Unified Plan Negotiation (Roles: architect)" -ForegroundColor White
}

    foreach ($entry in $parsed) {
        $dodCount = if ($entry.DoD) { $entry.DoD.Count } else { 0 }
        $acCount = if ($entry.AC) { $entry.AC.Count } else { 0 }
        $rolesStr = if ($entry.Roles) { ($entry.Roles -join ', ') } else { 'engineer' }
        $depStr = ""
        if ($entry.DependsOn -and $entry.DependsOn.Count -gt 0) {
            $depStr = " [depends_on: $($entry.DependsOn -join ', ')]"
        }
        Write-Host "  $($entry.RoomId) → $($entry.TaskRef) — $($entry.Description) (Roles: $rolesStr, DoD: $dodCount, AC: $acCount)$depStr" -ForegroundColor White
    }
Write-Host ""

if ($DryRun) {
    # --- Show DAG structure in DryRun ---
    $nodes = @()
    if (-not $skipPlanReview) {
        $nodes += @{ Id = "PLAN-REVIEW"; DependsOn = @() }
    }
    foreach ($entry in $parsed) {
        $nodes += @{ Id = $entry.TaskRef; DependsOn = $entry.DependsOn }
    }
    
    try {
        $topo = & $buildDag -Nodes $nodes -Validate
        if ($topo) {
            Write-Host "  Dependency Graph (Topological Order):" -ForegroundColor Cyan
            Write-Host "  $($topo.Id -join ' -> ')" -ForegroundColor Gray
        }
    } catch {
        Write-Warning "Could not build dependency graph: $($_.Exception.Message)"
    }

    Write-Host ""
    Write-Host "[DRY RUN] No rooms created." -ForegroundColor Yellow
    exit 0
}

# --- Room Creation Logic ---
function New-PlanWarRooms {
    param($PlanFile, $ProjectDir, $warRoomsDir, $agentsDir, $parsed, $planId, $runId, $eventsPath, $maxRetries, $timeoutSeconds)
    
    # --- Re-parse plan in case it changed during negotiation (uses PlanParser module) ---
    $planContent = Get-Content $PlanFile -Raw
    $parsed = ConvertFrom-PlanMarkdown -Content $planContent

    # --- Enrich parsed entries with asset bindings from plan metadata ---
    $planMetaFile = Join-Path (Split-Path $PlanFile) "$planId.meta.json"
    $planMeta = $null
    if (Test-Path $planMetaFile) {
        try {
            $planMeta = Get-Content $planMetaFile -Raw | ConvertFrom-Json
        } catch {
            Write-Warning "Failed to read plan metadata for assets: $planMetaFile"
        }
    }
    if ($planMeta -and $planMeta.assets) {
        $allPlanAssets = @($planMeta.assets)
        $epicAssetsMap = $planMeta.epic_assets
        $plansDir = Split-Path $PlanFile

        foreach ($entry in $parsed) {
            $boundFilenames = if ($epicAssetsMap -and $epicAssetsMap.($entry.TaskRef)) {
                @($epicAssetsMap.($entry.TaskRef))
            } else { @() }

            $entryAssets = @()
            foreach ($asset in $allPlanAssets) {
                $isBound = $boundFilenames -contains $asset.filename
                $isPlanLevel = -not $asset.bound_epics -or @($asset.bound_epics).Count -eq 0

                if ($isBound -or $isPlanLevel) {
                    $sourcePath = Join-Path (Join-Path $plansDir "assets") $planId $asset.filename
                    $entryAssets += [PSCustomObject]@{
                        Path        = $sourcePath
                        Filename    = $asset.filename
                        Description = $asset.description
                        AssetType   = $asset.asset_type
                    }
                }
            }
            $entry | Add-Member -NotePropertyName Assets -NotePropertyValue $entryAssets -Force
        }
    }

    # Auto-inject PLAN-REVIEW dependency (orchestration logic, not parsing)
    if (-not $skipPlanReview) {
        foreach ($item in $parsed) {
            if ($item.DependsOn -notcontains "PLAN-REVIEW") {
                $item.DependsOn = @("PLAN-REVIEW") + $item.DependsOn
            }
        }
    }

    # --- Merge advisory deps from planning-DAG.json (mirrors first-parse logic) ---
    $planDir2 = Split-Path $PlanFile
    if (-not $planDir2) { $planDir2 = "." }
    $planningDagFile = Join-Path $planDir2 ".planning-DAG.json"
    if (Test-Path $planningDagFile) {
        try {
            $planningDag = Get-Content $planningDagFile -Raw | ConvertFrom-Json
            foreach ($pdNode in $planningDag.nodes) {
                $matchedEntry = $parsed | Where-Object { $_.TaskRef -eq $pdNode.task_ref }
                if (-not $matchedEntry) { continue }
                $hasExplicitDeps = $matchedEntry.DependsOn | Where-Object { $_ -ne 'PLAN-REVIEW' }
                if (-not $hasExplicitDeps -and $pdNode.depends_on -and @($pdNode.depends_on).Count -gt 0) {
                    $aiDeps = @($pdNode.depends_on) | Where-Object { $_ -and $_ -ne 'PLAN-REVIEW' }
                    if ($aiDeps.Count -gt 0) {
                        $matchedEntry.DependsOn = @("PLAN-REVIEW") + $aiDeps
                        Write-Host "  [PLANNING-DAG] $($pdNode.task_ref): deps → $($matchedEntry.DependsOn -join ', ') (advisory)" -ForegroundColor Yellow
                    }
                }
            }
        } catch {
            Write-Warning "Failed to read planning-DAG.json for dep merge: $_"
        }
    }

    # --- Create missing war-rooms or reconcile existing ones ---
    $newWarRoom = Join-Path $agentsDir "war-rooms" "New-WarRoom.ps1"
    foreach ($entry in $parsed) {
        $roomPath = Join-Path $warRoomsDir $entry.RoomId
        if (Test-Path $roomPath) {
            $existingConfigPath = Join-Path $roomPath "config.json"
            if (-not (Test-Path $existingConfigPath)) {
                # Stale room directory without config.json — remove and recreate
                Write-Warning "Stale room $($entry.RoomId) found (no config.json). Removing and recreating."
                Remove-Item -Path $roomPath -Recurse -Force
            } else {
                # --- RECONCILE: update existing room's role assignment from plan ---
                $primaryRole = if ($entry.Roles -and $entry.Roles.Count -gt 0) { $entry.Roles[0] } else { "engineer" }
                $candidateRoles = @(if ($entry.Roles -and $entry.Roles.Count -gt 0) { $entry.Roles } else { @("engineer", "qa") })
                try {
                    $existingConfig = Get-Content $existingConfigPath -Raw | ConvertFrom-Json
                    $currentRole = if ($existingConfig.assignment.assigned_role) { $existingConfig.assignment.assigned_role } else { "engineer" }
                    if ($currentRole -ne $primaryRole) {
                        Write-Host "    [RECONCILE] $($entry.RoomId): role $currentRole → $primaryRole (from plan Roles: directive)" -ForegroundColor Yellow
                        $existingConfig.assignment.assigned_role = $primaryRole
                        $existingConfig.assignment.candidate_roles = $candidateRoles
                    }
                    if ($existingConfig.PSObject.Properties.Name -contains 'workspace') {
                        $existingConfig.PSObject.Properties.Remove('workspace')
                    }
                    $existingConfig | ConvertTo-Json -Depth 10 | Out-File -FilePath $existingConfigPath -Encoding utf8
                } catch {
                    Write-Host "    [WARN] Failed to reconcile $($entry.RoomId): $($_.Exception.Message)" -ForegroundColor Yellow
                }
                continue
            }
        }

        $resolvedWorkingDir = $ProjectDir
        if ($entry.EpicWorkingDir -and $entry.EpicWorkingDir -ne '') {
            $wd = $entry.EpicWorkingDir
            if ($wd -eq '.') {
                $resolvedWorkingDir = $ProjectDir
            } elseif ([System.IO.Path]::IsPathRooted($wd)) {
                $resolvedWorkingDir = $wd
            } else {
                $resolvedWorkingDir = (Join-Path $ProjectDir $wd)
            }
        }
        if (-not (Test-Path $resolvedWorkingDir)) {
            Write-Host "    Creating working_dir: $resolvedWorkingDir" -ForegroundColor DarkGray
            New-Item -ItemType Directory -Path $resolvedWorkingDir -Force | Out-Null
        }

        $primaryRole = if ($entry.Roles -and $entry.Roles.Count -gt 0) { $entry.Roles[0] } else { "engineer" }
        $fullDesc = $entry.Description
        if ($entry.Objective) {
            $fullDesc = "Objective: $($entry.Objective)`n`n$fullDesc"
        }
        if ($entry.DescBody) {
            $fullDesc = "$fullDesc`n`n$($entry.DescBody)"
        }
        # Append all parsed Sections so the full EPIC body is passed to New-WarRoom.
        # This handles plans where content lives under sub-headings (####/###) that
        # $descPattern stops at — e.g. "#### Mục tiêu", "### Tasks", "### Definition of Done".
        # Skip section[0] if it is the EPIC/TASK header itself (parser re-ingests it as a section).
        if ($entry.Sections -and $entry.Sections.Count -gt 0) {
            foreach ($sec in $entry.Sections) {
                # Skip the EPIC/TASK title section re-captured by the parser
                if ($sec.Heading -match "^(EPIC|TASK)-\d+") { continue }
                $escapedHeading = [regex]::Escape($sec.Heading)
                if ([regex]::IsMatch($fullDesc, "(?im)^#{3,4}\s+$escapedHeading\s*$")) { continue }
                $hashes = '#' * $sec.HeadingLevel
                $fullDesc = "$fullDesc`n`n$hashes $($sec.Heading)`n`n$($sec.Content)"
            }
        }


        $candidateRoles = @(if ($entry.Roles -and $entry.Roles.Count -gt 0) { $entry.Roles } else { @("engineer", "qa") })
        $roomArgs = @{
            RoomId           = $entry.RoomId
            TaskRef          = $entry.TaskRef
            TaskDescription  = $fullDesc
            WorkingDir       = $resolvedWorkingDir
            WarRoomsDir      = $warRoomsDir
            PlanId           = $planId
            RunId            = $runId
            AssignedRole     = $primaryRole
            CandidateRoles   = $candidateRoles
            MaxRetries       = $maxRetries
            TimeoutSeconds   = $timeoutSeconds
        }

        if ($entry.DoD -and $entry.DoD.Count -gt 0) {
            $roomArgs['DefinitionOfDone'] = $entry.DoD
        }
        if ($entry.AC -and $entry.AC.Count -gt 0) {
            $roomArgs['AcceptanceCriteria'] = $entry.AC
        }
        if ($entry.DependsOn -and $entry.DependsOn.Count -gt 0) {
            $roomArgs['DependsOn'] = $entry.DependsOn
        }
        if ($entry.Pipeline) {
            $roomArgs['Pipeline'] = $entry.Pipeline
        }
        # PlanParser exposes parsed directives as .Capabilities; forward them to
        # New-WarRoom as RequiredCapabilities so Resolve-Pipeline can drive the
        # correct lifecycle (e.g. security → security-engineer worker +
        # security-specialist evaluator).
        if ($entry.Capabilities -and $entry.Capabilities.Count -gt 0) {
            $roomArgs['RequiredCapabilities'] = $entry.Capabilities
        }
        if ($entry.Lifecycle) {
            $roomArgs['Lifecycle'] = $entry.Lifecycle
        }
        if ($entry.Assets) {
            $roomArgs['Assets'] = $entry.Assets
        }
        # New-WarRoom appends the room.created source event before writing room,
        # status, or role config projections. Keep Start-Plan from duplicating it.
        & $newWarRoom @roomArgs
    }

    # --- Build dependency graph ---
    Write-Host "[DAG] Building dependency graph..." -ForegroundColor Cyan
    $buildDag = Join-Path $agentsDir "plan" "Build-DependencyGraph.ps1"
    $null = & $buildDag -WarRoomsDir $warRoomsDir
    if (Get-Command Write-OrchestrationEvent -ErrorAction SilentlyContinue) {
        $dagEvent = [ordered]@{
            event_type = 'plan.dag.built'
            plan_id    = $planId
            run_id     = $runId
            summary    = "Dependency graph built for $planId."
            payload    = [ordered]@{
                warrooms_dir = $warRoomsDir
                dag_path     = (Join-Path $warRoomsDir 'DAG.json')
            }
        }
        Write-OrchestrationEvent -Event $dagEvent | Out-Null
    }
}

# ===========================================================================
# Phase A: Create/reconcile war-rooms and rebuild DAG
# ===========================================================================
# Always called — even in Resume mode. New-PlanWarRooms skips existing rooms
# internally (reconcile only) but MUST rebuild DAG.json so the manager loop
# sees all rooms, not just room-000.
New-PlanWarRooms -PlanFile $PlanFile -ProjectDir $ProjectDir -warRoomsDir $warRoomsDir -agentsDir $agentsDir -parsed $parsed -planId $planId -runId $runId -eventsPath $eventsPath -maxRetries $defaultRoomMaxRetries -timeoutSeconds $defaultRoomTimeoutSeconds

# ===========================================================================
# Phase B: Dependency review (reads actual brief.md from each war-room)
# ===========================================================================
$reviewDeps = Join-Path $agentsDir "plan" "Review-Dependencies.ps1"
if (-not $Resume -and -not $DryRun -and (Test-Path $reviewDeps)) {
    $depReviewArgs = @{
        WarRoomsDir = $warRoomsDir
        PlanFile    = $PlanFile
    }
    if ($NonInteractive -or ($config.manager -and $config.manager.auto_approve_deps -eq $true)) {
        $depReviewArgs['AutoApprove'] = $true
    }
    & $reviewDeps @depReviewArgs
    # Non-fatal: if user rejects or analysis fails, original deps are preserved
}

# ===========================================================================
# Phase C: Unified or Legacy plan negotiation (content review, not deps)
# ===========================================================================

# --- Unified Negotiation Handoff ---
if ($Unified -and ($Review -or $Expand) -and -not $Resume) {
    Write-Host "[UNIFIED] Handing off plan negotiation to Manager Loop." -ForegroundColor Cyan
    $env:PLAN_FILE = $PlanFile
    & $managerLoop -ConfigPath $configPath -WarRoomsDir $warRoomsDir -Review -PlanFile $PlanFile
    exit 0
}

# --- Auto-Pass room-000 if no review/expand needed ---
if ($Unified -and -not ($Review -or $Expand) -and -not $Resume -and -not $skipPlanReview) {
    "done" | Out-File -FilePath (Join-Path $room000Dir "status") -Encoding utf8 -NoNewline
}

# --- Legacy Negotiation Loop (blocking) ---
$shouldNegotiate = -not $Resume -and -not $Unified

while ($shouldNegotiate) {
    if (-not $Review) { break }

    Write-Host "Waiting for plan approval/update via MCP-authored channel message (timeout: ${planReviewTimeout}s)..." -ForegroundColor Cyan

    $waitResultRaw = & $waitForMessage -RoomDir $room000Dir -WaitType "plan-approve", "plan-reject", "plan-update" -TimeoutSeconds $planReviewTimeout
    
    if ($LASTEXITCODE -ne 0 -or -not $waitResultRaw) {
        Write-Error "Plan negotiation timed out or failed."
        exit 1
    }

    $waitResult = $waitResultRaw | ConvertFrom-Json
    if (-not $waitResult -or -not $waitResult.type) {
        Write-Error "Invalid response from channel."
        exit 1
    }

    if ($waitResult.type -eq "plan-approve") {
        Write-Host "Plan approved via channel!" -ForegroundColor Green
        break
    } elseif ($waitResult.type -eq "plan-update") {
        Write-Host "Manual plan update detected. Reloading..." -ForegroundColor Yellow
        if ($waitResult.body.Trim()) {
            $waitResult.body.Trim() | Out-File -FilePath $PlanFile -Encoding utf8
        }
        continue
    } else {
        # plan-reject — apply feedback via expander, then re-review
        $feedback = $waitResult.body
        Write-Host "Plan rejected with feedback: $feedback" -ForegroundColor Yellow
        
        Write-Host "Applying feedback via AI architect..." -ForegroundColor Cyan
        $expandScript = Join-Path $agentsDir "plan" "Expand-Plan.ps1"
        & $expandScript -PlanFile $PlanFile -OutFile $PlanFile -Feedback $feedback -RoomDir $room000Dir -DryRun:$DryRun
        
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "Failed to apply feedback via AI. Please update the plan manually."
        } else {
            Write-Host "Plan updated with feedback." -ForegroundColor Green
        }
        
        $Review = $true
    }
}

# ===========================================================================
# Phase D: Start the manager loop
# ===========================================================================
if (-not $SkipLoop) {
    Write-Host ""
    Write-Host "[STARTING] Manager loop..." -ForegroundColor Green
    & $managerLoop -ConfigPath $configPath -WarRoomsDir $warRoomsDir
} else {
    Write-Host "[SKIPPED] Manager loop (SkipLoop requested)." -ForegroundColor Yellow
}
