<#
.SYNOPSIS
    Manager orchestration loop — the brain of Agent OS.

.DESCRIPTION
    Monitors all war-rooms, routes work between engineers and QA,
    handles retries, deadlock detection, state timeouts, and release cycles.
    Runs continuously until all rooms pass or the process is terminated.

    Replaces: roles/manager/loop.sh

	    V2 signal-based state-machine per room (lifecycle.json):
	        pending -> developing -> review -> done
	                                ↓ fail
	                       optimize -> review
	        failed is terminal; legacy passed/failed-final/fixing are normalized

.PARAMETER ConfigPath
    Path to config.json. Defaults through Resolve-OstwinConfigPath:
    AGENT_OS_CONFIG, OSTWIN_CONFIG_PATH, OSTWIN_PROJECT_DIR, AGENTS_DIR,
    then ~/.ostwin/.agents/config.json before project-local .agents/config.json.
.PARAMETER WarRoomsDir
    Directory containing war-room directories. Default: WARROOMS_DIR env var.

.EXAMPLE
    ./Start-ManagerLoop.ps1
    ./Start-ManagerLoop.ps1 -ConfigPath ./config.json -WarRoomsDir ./war-rooms
#>
[CmdletBinding()]
param(
    [string]$ConfigPath = '',
    [string]$WarRoomsDir = '',
    [switch]$Review,
    [string]$PlanFile = $env:PLAN_FILE
)

# --- Resolve paths ---
$scriptDir = $PSScriptRoot
$agentsDir = (Resolve-Path (Join-Path $scriptDir ".." "..")).Path
$channelDir = Join-Path $agentsDir "channel"
$releaseDir = Join-Path $agentsDir "release"
$managerPidFile = Join-Path $agentsDir "manager.pid"

$readMessages = Join-Path $channelDir "Read-Messages.ps1"

# --- Import modules ---
$logModule = Join-Path $agentsDir "lib" "Log.psm1"
$configModule = Join-Path $agentsDir "lib" "Config.psm1"
$utilsModule = Join-Path $agentsDir "lib" "Utils.psm1"
$helpersModule = Join-Path $scriptDir "ManagerLoop-Helpers.psm1"
$eventsModule = Join-Path $agentsDir "events" "OrchestrationEvents.psm1"
$workspaceModule = Join-Path $agentsDir "workspace" "GitWorkspace.psm1"
$mergeQueueModule = Join-Path $agentsDir "workspace" "MergeQueue.psm1"
if (Test-Path $logModule) { Import-Module $logModule -Force }
if (Test-Path $configModule) { Import-Module $configModule -Force }
if (Test-Path $utilsModule) { Import-Module $utilsModule -Force }
if (Test-Path $eventsModule) { Import-Module $eventsModule -Force }
if (Test-Path $workspaceModule) { Import-Module $workspaceModule -Force -Global -DisableNameChecking }
if (Test-Path $mergeQueueModule) { Import-Module $mergeQueueModule -Force -Global }
if (Test-Path $helpersModule) { Import-Module $helpersModule -Force }

# --- Helper functions ---

# --- Resolve config ---
if (-not $ConfigPath) {
    $ConfigPath = if (Get-Command Resolve-OstwinConfigPath -ErrorAction SilentlyContinue) {
        Resolve-OstwinConfigPath
    }
    else {
        $homeDir = if ($env:USERPROFILE) { $env:USERPROFILE }
                   elseif ($env:HOME) { $env:HOME }
                   else { $HOME }
        $ostwinHome = if ($env:OSTWIN_HOME) { $env:OSTWIN_HOME } else { Join-Path $homeDir ".ostwin" }
        $globalConfig = Join-Path (Join-Path $ostwinHome ".agents") "config.json"

        if ($env:AGENT_OS_CONFIG) { $env:AGENT_OS_CONFIG }
        elseif ($env:OSTWIN_CONFIG_PATH) { $env:OSTWIN_CONFIG_PATH }
        elseif ($env:OSTWIN_PROJECT_DIR) { Join-Path (Join-Path $env:OSTWIN_PROJECT_DIR ".agents") "config.json" }
        elseif ($env:AGENTS_DIR) { Join-Path $env:AGENTS_DIR "config.json" }
        elseif (Test-Path $globalConfig) { $globalConfig }
        else { Join-Path $agentsDir "config.json" }
    }
}
$config = Get-Content $ConfigPath -Raw | ConvertFrom-Json

$managerRuntime = if (Get-Command Get-OstwinManagerRuntimeSettings -ErrorAction SilentlyContinue) {
    Get-OstwinManagerRuntimeSettings -Config $config
} else {
    [PSCustomObject]@{
        max_concurrent_rooms  = $config.manager.max_concurrent_rooms
        poll_interval_seconds = $config.manager.poll_interval_seconds
        max_engineer_retries  = $config.manager.max_engineer_retries
        state_timeout_seconds = if ($config.manager.state_timeout_seconds) { $config.manager.state_timeout_seconds } else { 900 }
        auto_approve_tools    = $config.manager.auto_approve_tools
        dynamic_pipelines     = $config.manager.dynamic_pipelines
    }
}

$maxConcurrent = $managerRuntime.max_concurrent_rooms
$pollInterval = $managerRuntime.poll_interval_seconds
$maxRetries = $managerRuntime.max_engineer_retries
$stateTimeout = $managerRuntime.state_timeout_seconds

# --- Resolve war-rooms dir ---
if (-not $WarRoomsDir) {
    $WarRoomsDir = if ($env:WARROOMS_DIR) { $env:WARROOMS_DIR }
                   else { Join-Path $agentsDir "war-rooms" }
}

# --- Load DAG if present ---
$dagFile = Join-Path $WarRoomsDir "DAG.json"
$hasDag = Test-Path $dagFile
$testDepsReady = Join-Path $agentsDir "plan" "Test-DependenciesReady.ps1"
$updateProgress = Join-Path $agentsDir "plan" "Update-Progress.ps1"
$script:lastProgressUpdate = 0
$script:dagCache = $null
$script:dagMtime = $null
$script:rolesCache = $null
$script:rolesCacheMtime = 0

# --- Write PID ---
$PID | Out-File -FilePath $managerPidFile -Encoding utf8 -NoNewline

# --- Graceful shutdown handler ---
$script:shuttingDown = $false
Register-EngineEvent -SourceIdentifier PowerShell.Exiting -Action {
    $script:shuttingDown = $true
} | Out-Null

# --- Log startup ---
$logFn = Get-Command Write-OstwinLog -ErrorAction SilentlyContinue
if ($logFn) {
    Write-OstwinLog -Level INFO -Message "Starting Ostwin Manager Loop"
}
else {
    Write-Host "[MANAGER] Starting Ostwin Manager Loop"
}
Write-Host "  Max concurrent rooms: $maxConcurrent"
Write-Host "  Poll interval: ${pollInterval}s"
Write-Host "  Max retries per task: $maxRetries"
Write-Host "  State timeout: ${stateTimeout}s"
Write-Host ""

# --- Pre-flight checks ---
$dashboardBaseUrl = if ($env:OSTWIN_DASHBOARD_URL) { $env:OSTWIN_DASHBOARD_URL } else { "http://localhost:3366" }

# --- Inject runtime context into ManagerLoop-Helpers module ---
# All helper functions are defined in ManagerLoop-Helpers.psm1 (imported above).
# Set-ManagerLoopContext binds runtime paths and config so they remain testable.
if (Get-Command Set-ManagerLoopContext -ErrorAction SilentlyContinue) {
    Set-ManagerLoopContext -Context @{
        agentsDir        = $agentsDir
        WarRoomsDir      = $WarRoomsDir
        dagFile          = $dagFile
        hasDag           = $hasDag
        dagCache         = $script:dagCache
        dagMtime         = $script:dagMtime
        config           = $config
        stateTimeout     = $stateTimeout
        maxRetries       = $maxRetries
        readMessages     = $readMessages
        dashboardBaseUrl = $dashboardBaseUrl
    }
}


# === MAIN LOOP ===
$iteration = 0
$stallCycles = 0
$script:planFailed = $false

function Add-CanonicalLifecycleAliases {
    param(
        $Lifecycle,
        [string]$LifecyclePath = ''
    )

    if (-not $Lifecycle -or -not $Lifecycle.states) { return $Lifecycle }
    $changed = $false
    if (($Lifecycle.states.PSObject.Properties.Name -contains 'passed') -and -not ($Lifecycle.states.PSObject.Properties.Name -contains 'done')) {
        $Lifecycle.states | Add-Member -NotePropertyName done -NotePropertyValue $Lifecycle.states.passed -Force
        $changed = $true
    }
    if ($Lifecycle.states.PSObject.Properties.Name -contains 'failed-final') {
        $Lifecycle.states | Add-Member -NotePropertyName failed -NotePropertyValue ([pscustomobject]@{ type = 'terminal' }) -Force
        $changed = $true
    }
    if (($Lifecycle.states.PSObject.Properties.Name -contains 'fixing') -and -not ($Lifecycle.states.PSObject.Properties.Name -contains 'optimize')) {
        $Lifecycle.states | Add-Member -NotePropertyName optimize -NotePropertyValue $Lifecycle.states.fixing -Force
        $changed = $true
    }

    # Triage is an active manager state. Ensure every permitted manager channel
    # decision has a lifecycle transition so the loop can always make progress
    # once manager writes to the channel. Preserve custom targets/actions when
    # they already exist; only backfill missing canonical signals.
    if ($Lifecycle.states.PSObject.Properties.Name -contains 'triage') {
        if (-not $Lifecycle.states.triage.signals) {
            $Lifecycle.states.triage | Add-Member -NotePropertyName signals -NotePropertyValue ([pscustomobject]@{}) -Force
            $changed = $true
        }
        $triageSignals = $Lifecycle.states.triage.signals
        $stateNames = @($Lifecycle.states.PSObject.Properties.Name)

        $doneTarget = if ($stateNames -contains 'review') { 'review' } elseif ($stateNames -contains 'done') { 'done' } else { $Lifecycle.initial_state }
        $fixTarget = if ($stateNames -contains 'optimize') { 'optimize' } elseif ($stateNames -contains 'developing') { 'developing' } else { $Lifecycle.initial_state }
        $redesignTarget = if ($stateNames -contains 'developing') { 'developing' } else { $Lifecycle.initial_state }
        $rejectTarget = if ($stateNames -contains 'failed') { 'failed' } elseif ($stateNames -contains 'failed-final') { 'failed-final' } elseif ($stateNames -contains 'done') { 'done' } else { $Lifecycle.initial_state }

        if ($doneTarget -and -not ($triageSignals.PSObject.Properties.Name -contains 'done')) {
            $triageSignals | Add-Member -NotePropertyName done -NotePropertyValue ([pscustomobject]@{ target = $doneTarget }) -Force
            $changed = $true
        }
        if ($fixTarget -and -not ($triageSignals.PSObject.Properties.Name -contains 'fix')) {
            $triageSignals | Add-Member -NotePropertyName fix -NotePropertyValue ([pscustomobject]@{ target = $fixTarget; actions = @('increment_retries') }) -Force
            $changed = $true
        }
        if ($redesignTarget -and -not ($triageSignals.PSObject.Properties.Name -contains 'redesign')) {
            $triageSignals | Add-Member -NotePropertyName redesign -NotePropertyValue ([pscustomobject]@{ target = $redesignTarget; actions = @('increment_retries', 'revise_brief') }) -Force
            $changed = $true
        }
        if ($rejectTarget -and -not ($triageSignals.PSObject.Properties.Name -contains 'reject')) {
            $triageSignals | Add-Member -NotePropertyName reject -NotePropertyValue ([pscustomobject]@{ target = $rejectTarget }) -Force
            $changed = $true
        }
    }

    if ($changed -and $LifecyclePath) {
        try {
            $Lifecycle | ConvertTo-Json -Depth 20 | Out-File -FilePath $LifecyclePath -Encoding utf8
        } catch {
            Write-Log "WARN" "Failed to persist canonical lifecycle aliases to '$LifecyclePath': $($_.Exception.Message)"
        }
    }
    return $Lifecycle
}

try {
while (-not $script:shuttingDown) {
    $iteration++

    # --- Hot-reload: check for new roles every 30s ---
    $nowEpochHR = Get-UnixEpoch
    if (($nowEpochHR - $script:rolesCacheMtime) -ge 30) {
        $getAvailableRoles = Join-Path $agentsDir "roles" "_base" "Get-AvailableRoles.ps1"
        if (Test-Path $getAvailableRoles) {
            try {
                $newRoles = & $getAvailableRoles -AgentsDir $agentsDir -WarRoomsDir $WarRoomsDir
                if ($script:rolesCache -and $newRoles.Count -ne $script:rolesCache.Count) {
                    $newNames = ($newRoles | ForEach-Object { $_.Name }) -join ', '
                    Write-Log "INFO" "Roles hot-reload: $($newRoles.Count) roles available ($newNames)"
                }
                $script:rolesCache = $newRoles
            } catch { }
        }
        $script:rolesCacheMtime = $nowEpochHR
    }

    $roomCount = 0
    $allPassed = $true
    $allTerminal = $true
    $failedCount = 0
    $activeWithNoPid = 0
    $totalActive = 0

    $roomDirs = Get-ChildItem -Path $WarRoomsDir -Directory -Filter "room-*" -ErrorAction SilentlyContinue

    foreach ($roomDirInfo in $roomDirs) {
        if ($script:shuttingDown) { break }

        $roomDir = $roomDirInfo.FullName
        $roomCount++
        $roomId = $roomDirInfo.Name

        $rawStatus = if (Test-Path (Join-Path $roomDir "status")) {
            (Get-Content (Join-Path $roomDir "status") -Raw).Trim()
        } else { "pending" }
        $status = if (Get-Command ConvertTo-CanonicalRoomStatus -ErrorAction SilentlyContinue) {
            ConvertTo-CanonicalRoomStatus -Status $rawStatus
        } else {
            switch ($rawStatus) {
                'passed'       { 'done' }
                'failed-final' { 'failed' }
                'fixing'       { 'optimize' }
                default        { $rawStatus }
            }
        }

        $taskRef = if (Test-Path (Join-Path $roomDir "task-ref")) {
            (Get-Content (Join-Path $roomDir "task-ref") -Raw).Trim()
        } elseif (Test-Path (Join-Path $roomDir "config.json")) {
            $rc = Get-Content (Join-Path $roomDir "config.json") -Raw | ConvertFrom-Json
            if ($rc.task_ref) { $rc.task_ref } else { "UNKNOWN" }
        } else { "UNKNOWN" }

        $retries = if (Test-Path (Join-Path $roomDir "retries")) {
            [int](Get-Content (Join-Path $roomDir "retries") -Raw).Trim()
        } else { 0 }

        # --- Resolve Worker Script via centralized Resolve-Role ---
        $roomConfigFile = Join-Path $roomDir "config.json"
        $roomLifecycleFile = Join-Path $roomDir "lifecycle.json"
        $lifecycle = if (Test-Path $roomLifecycleFile) { Add-CanonicalLifecycleAliases -Lifecycle (Get-Content $roomLifecycleFile -Raw | ConvertFrom-Json) -LifecyclePath $roomLifecycleFile } else { $null }
        if ($rawStatus -ne $status -and $status) {
            Write-Log "INFO" "[$taskRef] Normalizing legacy room status '$rawStatus' -> '$status'."
            Write-RoomStatus $roomDir $status
        }
        $stateDef = if ($lifecycle -and $lifecycle.states -and $lifecycle.states.$status) { $lifecycle.states.$status } else { $null }
        if (-not (Test-Path $roomConfigFile)) {
            # Skip non-war-room directories like room-expansion, room-test
            continue
        }
        $assignedRole = "engineer"

        # If the state has a role, prefer that. Else fall back to config assignment.
        if ($stateDef -and $stateDef.role) {
            $assignedRole = $stateDef.role
        } elseif (Test-Path $roomConfigFile) {
            $rc = Get-Content $roomConfigFile -Raw | ConvertFrom-Json
            if ($rc.assignment -and $rc.assignment.assigned_role) {
                $assignedRole = $rc.assignment.assigned_role
            }
        }
        $baseRole = $assignedRole -replace ':.*$', ''

        # --- Override detection (EPIC-006) ---
        $overrideDir = Join-Path $roomDir (Join-Path "overrides" $baseRole)
        $effectiveRoleDir = if (Test-Path $overrideDir) {
            if ((Test-Path (Join-Path $overrideDir "subcommands.json")) -or (Test-Path (Join-Path $overrideDir "role.json"))) { $overrideDir } else { $null }
        } else { $null }

        $resolveRoleScript = Join-Path $agentsDir "roles" "_base" "Resolve-Role.ps1"
        if (Test-Path $resolveRoleScript) {
            $resolveArgs = @{
                RoleName    = $assignedRole
                AgentsDir   = $agentsDir
                WarRoomsDir = $WarRoomsDir
            }
            if ($effectiveRoleDir) {
                $resolveArgs['RolePath'] = $effectiveRoleDir
            }
            if ($script:rolesCache) {
                $resolveArgs['AvailableRoles'] = $script:rolesCache
            }
            $resolved = & $resolveRoleScript @resolveArgs
            $workerScript = $resolved.Runner
        } else {
            # Inline fallback if Resolve-Role.ps1 doesn't exist yet
            $workerScript = $null
            $registryPath = Join-Path $agentsDir "roles" "registry.json"
            if (Test-Path $registryPath) {
                $registry = Get-Content $registryPath -Raw | ConvertFrom-Json
                $matchedRole = $registry.roles | Where-Object { $_.name -eq $baseRole }
                if ($matchedRole -and $matchedRole.runner) {
                    $runnerRel = $matchedRole.runner -replace '/', [System.IO.Path]::DirectorySeparatorChar
                    $runnerPath = Join-Path $agentsDir $runnerRel
                    if (Test-Path $runnerPath) { $workerScript = $runnerPath }
                }
            }
            if (-not $workerScript) {
                $workerScript = Join-Path $agentsDir "roles" "_base" "Start-EphemeralAgent.ps1"
            }
        }

        switch ($status) {
            'pending' {
                $allPassed = $false
                $allTerminal = $false

                # --- DEPENDENCY GATE ---
                if ($hasDag) {
                    $depResult = & $testDepsReady -RoomDir $roomDir -WarRoomsDir $WarRoomsDir
                    if (-not $depResult.Ready) {
                        if ($depResult.Reason -eq 'blocked') {
                            Write-Log "WARN" "[$taskRef] Blocked by $($depResult.BlockedBy)"
                            Write-RoomStatus $roomDir "blocked"
                        }
                        # still waiting or now blocked — skip this room
                        continue
                    }
                }

                if (Get-Command Get-WorkspaceDependencyState -ErrorAction SilentlyContinue) {
                    $workspaceDeps = Get-WorkspaceDependencyState -RoomDir $roomDir -WarRoomsDir $WarRoomsDir
                    if (-not $workspaceDeps.Ready) {
                        Write-Log "INFO" "[$taskRef] Waiting for workspace integration: $($workspaceDeps.BlockedBy -join ', ')"
                        continue
                    }
                }

                # --- ON-THE-FLY PIPELINE GENERATION ---
                $roomLifecycleCheck = Join-Path $roomDir "lifecycle.json"
                $smartAssignment = $false
                if ($config.manager.smart_assignment) { $smartAssignment = $config.manager.smart_assignment }
                $dynamicPipelines = $managerRuntime.dynamic_pipelines

                if ($dynamicPipelines -and -not (Test-Path $roomLifecycleCheck)) {
                    $analyzeScript = Join-Path $agentsDir "roles" "_base" "Analyze-TaskRequirements.ps1"
                    $resolvePipeline = Join-Path $agentsDir "lifecycle" "Resolve-Pipeline.ps1"
                    if ((Test-Path $analyzeScript) -and (Test-Path $resolvePipeline)) {
                        $briefFile = Join-Path $roomDir "brief.md"
                        $taskDesc = if (Test-Path $briefFile) { Get-Content $briefFile -Raw } else { "" }
                        if ($taskDesc) {
                            try {
                                $analysis = & $analyzeScript -TaskDescription $taskDesc -AgentsDir $agentsDir
                                if ($analysis -and $analysis.Confidence -ge 0.6) {
                                    Write-Log "INFO" "[$taskRef] On-the-fly analysis: role=$($analysis.SuggestedRole), caps=$($analysis.RequiredCapabilities -join ','), confidence=$($analysis.Confidence)"
                                    $pipelineArgs = @{
                                        AssignedRole         = $analysis.SuggestedRole
                                        RequiredCapabilities = $analysis.RequiredCapabilities
                                        OutputPath           = $roomLifecycleCheck
                                        AgentsDir            = $agentsDir
                                    }
                                    & $resolvePipeline @pipelineArgs
                                    # Reload lifecycle for this iteration
                                    $lifecycle = Add-CanonicalLifecycleAliases -Lifecycle (Get-Content $roomLifecycleCheck -Raw | ConvertFrom-Json) -LifecyclePath $roomLifecycleCheck
                                }
                            } catch {
                                Write-Log "WARN" "[$taskRef] Task analysis failed: $_. Using default lifecycle."
                            }
                        }
                    }
                }

                if ((Get-ActiveCount) -lt $maxConcurrent) {
                    # Skills are resolved per-agent at spawn time by Invoke-Agent.ps1
                    # via Resolve-RoleSkills.ps1 using config-driven skill_refs.
                    $nextState = if ($lifecycle -and $lifecycle.initial_state) { $lifecycle.initial_state } else { "developing" }
                    Write-Log "INFO" "[$taskRef] Dependencies met. Transitioning to $nextState in $roomId..."
                    if (Get-Command Ensure-RoomWorktree -ErrorAction SilentlyContinue) {
                        try {
                            $workspaceReady = Ensure-RoomWorktree -RoomDir $roomDir -WarRoomsDir $WarRoomsDir -AgentsDir $agentsDir
                            if (-not $workspaceReady.Ready) {
                                Write-Log "WARN" "[$taskRef] Workspace is not ready; keeping room pending."
                                continue
                            }
                        } catch {
                            Write-Log "ERROR" "[$taskRef] Workspace creation failed: $($_.Exception.Message)"
                            $script:planFailed = Invoke-PlanFailFast -RoomDir $roomDir -Reason 'workspace_create_failed' -Role $baseRole -State $status -Summary "$taskRef workspace creation failed."
                            $script:shuttingDown = $true
                            continue
                        }
                    }
                    Write-RoomStatus $roomDir $nextState
                    # Sync config.json assigned_role with the initial state's role
                    $initDef = if ($lifecycle -and $lifecycle.states -and $lifecycle.states.$nextState) { $lifecycle.states.$nextState } else { $null }
                    if ($initDef -and $initDef.role) {
                        $initBaseRole = $initDef.role -replace ':.*$', ''
                        $rcFile = Join-Path $roomDir "config.json"
                        if (Test-Path $rcFile) {
                            $rc = Get-Content $rcFile -Raw | ConvertFrom-Json
                            if ($rc.assignment) {
                                $rc.assignment.assigned_role = $initBaseRole
                                if ($rc.PSObject.Properties['jit_role_id']) { $rc.PSObject.Properties.Remove('jit_role_id') }
                                $rc | ConvertTo-Json -Depth 10 | Out-File -FilePath $rcFile -Encoding utf8
                            }
                        }
                    }
                    $roleTimeout = Resolve-RoleTimeout -RoleName $baseRole -RoomDir $roomDir
                    Start-WorkerJob -RoomDir $roomDir -Role $baseRole -Script $workerScript -TaskRef $taskRef -TimeoutSeconds $roleTimeout -SkipLockCheck
                }
            }

            # === V2 SIGNAL-BASED STATE HANDLER ===
            # All non-pending states are handled via lifecycle.json signals
            default {
                $v2StateDef = if ($lifecycle -and $lifecycle.states -and $lifecycle.states.$status) { $lifecycle.states.$status } else { $null }

                $_homeDir = if ($env:HOME) { $env:HOME } else { $env:USERPROFILE }
                $OstwinHome = if ($env:OSTWIN_HOME) { $env:OSTWIN_HOME } else { Join-Path $_homeDir ".ostwin" }

                $roleMaxRetries = $maxRetries
                $planRoleMaxRetries = $null

                $rcFile = Join-Path $roomDir "config.json"
                if (Test-Path $rcFile) {
                    try {
                        $rcData = Get-Content $rcFile -Raw | ConvertFrom-Json
                        if ($rcData.plan_id) {
                            $planRolesFile = Join-Path $OstwinHome ".agents" "plans" "$($rcData.plan_id).roles.json"
                            if (Test-Path $planRolesFile) {
                                $planRolesConfig = Get-Content $planRolesFile -Raw | ConvertFrom-Json
                                if ($planRolesConfig.$baseRole -and $planRolesConfig.$baseRole.max_retries) {
                                    $planRoleMaxRetries = [int]$planRolesConfig.$baseRole.max_retries
                                }
                            }
                        }
                    } catch {}
                }

                if ($planRoleMaxRetries) {
                    $roleMaxRetries = $planRoleMaxRetries
                } elseif ($config.$baseRole -and $config.$baseRole.max_retries) {
                    $roleMaxRetries = [int]$config.$baseRole.max_retries
                } else {
                    $roleJsonPath = Join-Path $agentsDir "roles" $baseRole "role.json"
                    if (Test-Path $roleJsonPath) {
                        try {
                            $roleJson = Get-Content $roleJsonPath -Raw | ConvertFrom-Json
                            if ($roleJson.max_retries) { $roleMaxRetries = [int]$roleJson.max_retries }
                        } catch {}
                    }
                }
                $v2MaxRetries = if ($lifecycle -and $lifecycle.max_retries) { $lifecycle.max_retries } else { $roleMaxRetries }

                if (-not $v2StateDef -and $status -in @('done', 'failed', 'blocked')) {
                    $v2StateDef = [pscustomobject]@{ type = 'terminal' }
                }

                if (-not $v2StateDef) {
                    # Unknown state with no lifecycle definition
                    Write-Log "WARN" "[$taskRef] Unknown state '$status' in $roomId (no lifecycle definition)"
                    $allPassed = $false; $allTerminal = $false
                    continue
                }

                switch ($v2StateDef.type) {
                    'terminal' {
                        if ($status -eq 'done') {
                            # Guard: only fire Complete-PlanApproval once per plan
                            $planApprovedFlag = Join-Path $WarRoomsDir ".plan_approved_$($taskRef -replace '[^a-zA-Z0-9-]','')"
                            if ($taskRef -eq 'PLAN-REVIEW' -and -not (Test-Path $planApprovedFlag)) {
                                Complete-PlanApproval -TaskRef $taskRef
                                "1" | Out-File -FilePath $planApprovedFlag -Encoding utf8 -NoNewline
                            }
                            # Commit room work, then merge all currently committed
                            # rooms into the source branch. That advances the plan
                            # integration head before dependent rooms leave pending.
                            if (Get-Command Complete-RoomWorkspaceCommit -ErrorAction SilentlyContinue) {
                                try {
                                    $commitResult = Complete-RoomWorkspaceCommit -RoomDir $roomDir -WarRoomsDir $WarRoomsDir
                                    if (-not $commitResult.Committed) {
                                        Write-Log "ERROR" "[$taskRef] Workspace commit failed: $($commitResult.Status)"
                                        $allPassed = $false
                                        $failedCount++
                                        Write-RoomStatus $roomDir 'failed'
                                        Set-BlockedDescendants $taskRef
                                        $script:planFailed = Invoke-PlanFailFast -RoomDir $roomDir -Reason "workspace_commit_$($commitResult.Status)" -Role $baseRole -State $status -Summary "$taskRef workspace commit failed: $($commitResult.Status)."
                                        $script:shuttingDown = $true
                                    } elseif ((Get-Command Complete-PlanWorkspaceMerge -ErrorAction SilentlyContinue) -and $commitResult.Status -eq 'committed') {
                                        $roundMergeResult = Complete-PlanWorkspaceMerge -WarRoomsDir $WarRoomsDir -Force
                                        $roundMergeOk = $roundMergeResult.Integrated -or "$($roundMergeResult.Status)" -eq 'partial'
                                        if (-not $roundMergeOk) {
                                            $mergeDetail = "status=$($roundMergeResult.Status)"
                                            if ($roundMergeResult.Conflicted) { $mergeDetail += " conflicted=$($roundMergeResult.Conflicted)" }
                                            if (@($roundMergeResult.Pending).Count -gt 0) { $mergeDetail += " pending=$(@($roundMergeResult.Pending) -join ',')" }
                                            Write-Log "ERROR" "[$taskRef] Workspace round merge failed: $mergeDetail"
                                            $allPassed = $false
                                            $failedCount++
                                            Write-RoomStatus $roomDir 'failed'
                                            Set-BlockedDescendants $taskRef
                                            $mergeFailRoomDir = if ($roundMergeResult.Conflicted) { Join-Path $WarRoomsDir "$($roundMergeResult.Conflicted)" } else { $roomDir }
                                            $script:planFailed = Invoke-PlanFailFast -RoomDir $mergeFailRoomDir -Reason "workspace_merge_$($roundMergeResult.Status)" -Role $baseRole -State $status -Summary "$taskRef workspace round merge failed: $mergeDetail."
                                            $script:shuttingDown = $true
                                        } elseif (@($roundMergeResult.Merged).Count -gt 0) {
                                            Write-Log "INFO" "[$taskRef] Workspace round merge integrated: $(@($roundMergeResult.Merged) -join ', ')"
                                        }
                                    }
                                } catch {
                                    Write-Log "ERROR" "[$taskRef] Workspace commit/merge failed: $($_.Exception.Message)"
                                    $allPassed = $false
                                    $failedCount++
                                    Write-RoomStatus $roomDir 'failed'
                                    Set-BlockedDescendants $taskRef
                                    $script:planFailed = Invoke-PlanFailFast -RoomDir $roomDir -Reason 'workspace_commit_failed' -Role $baseRole -State $status -Summary "$taskRef workspace commit/merge failed."
                                    $script:shuttingDown = $true
                                }
                            }
                        } elseif ($status -eq 'failed') {
                            $allPassed = $false; $failedCount++
                            Write-Log "ERROR" "[$taskRef] Terminal failed is unrecoverable. Failing plan run."
                            $script:planFailed = Invoke-PlanFailFast -RoomDir $roomDir -Reason 'room_failed' -Role $baseRole -State $status -Summary "$taskRef reached failed."
                            $script:shuttingDown = $true
                            Set-BlockedDescendants $taskRef
                        } else {
                            # blocked or other terminal
                            $allPassed = $false; $failedCount++
                        }
                    }
                    'decision' {
                        $allPassed = $false; $allTerminal = $false; $totalActive++
                        if ($retries -lt $v2MaxRetries) {
                            # Increment retries so the retry/exhaust guard makes progress.
                            # Without this, crash-respawn cycles that never produce a
                            # lifecycle signal (done/pass/fail) would loop indefinitely
                            # between failed→developing because retries stays at 0.
                            $newRetries = $retries + 1
                            $newRetries.ToString() | Out-File -FilePath (Join-Path $roomDir "retries") -Encoding utf8 -NoNewline
                            $retryTarget = $v2StateDef.signals.retry.target
                            Write-Log "INFO" "[$taskRef] Decision: retries ($newRetries/$v2MaxRetries). Retrying → $retryTarget."
                            Write-RoomStatus $roomDir $retryTarget

                            # Spawn the target state's worker immediately so the next
                            # poll iteration doesn't miscount it as a crash-respawn.
                            $retryStateDef = if ($lifecycle.states.$retryTarget) { $lifecycle.states.$retryTarget } else { $null }
                            if ($retryStateDef -and $retryStateDef.role -and $retryStateDef.type -in @('work', 'review')) {
                                $retryRole = $retryStateDef.role -replace ':.*$', ''
                                $retryTimeout = Resolve-RoleTimeout -RoleName $retryRole -RoomDir $roomDir
                                if (Test-Path $resolveRoleScript) {
                                    $retryResolved = & $resolveRoleScript -RoleName $retryStateDef.role -AgentsDir $agentsDir -WarRoomsDir $WarRoomsDir
                                    Start-WorkerJob -RoomDir $roomDir -Role $retryRole -Script $retryResolved.Runner -TaskRef $taskRef -TimeoutSeconds $retryTimeout -SkipLockCheck
                                } else {
                                    Start-WorkerJob -RoomDir $roomDir -Role $retryRole -Script $workerScript -TaskRef $taskRef -TimeoutSeconds $retryTimeout -SkipLockCheck
                                }
                            }
                        } else {
                            Write-Log "ERROR" "[$taskRef] Decision: retries exhausted ($retries/$v2MaxRetries). Failing."
                            Write-ManagerOrchestrationEvent -RoomDir $roomDir -EventType 'lifecycle.retry.exhausted' -Summary "$taskRef exhausted lifecycle retries." -Payload @{ retries = $retries; max_retries = $v2MaxRetries; reason = 'decision_retries_exhausted' } -Role $baseRole -State $status -Severity 'error' | Out-Null
                            Write-RoomStatus $roomDir $v2StateDef.signals.exhaust.target
                            Set-BlockedDescendants $taskRef
                            $script:planFailed = Invoke-PlanFailFast -RoomDir $roomDir -Reason 'retry_exhausted' -Role $baseRole -State $status -Summary "$taskRef exhausted retries ($retries/$v2MaxRetries)."
                            $script:shuttingDown = $true
                        }
                    }
                    { $_ -in @('work', 'review', 'triage') } {
                        $allPassed = $false; $allTerminal = $false; $totalActive++

                        # PID tracking for deadlock detection
                        $anyPidAlive = $false; $anySpawnLock = $false
                        $pidDir = Join-Path $roomDir "pids"
                        if (Test-Path $pidDir) {
                            Get-ChildItem $pidDir -Filter "*.pid" -ErrorAction SilentlyContinue | ForEach-Object {
                                if (Test-PidAlive $_.FullName) { $anyPidAlive = $true }
                            }
                            Get-ChildItem $pidDir -Filter "*.spawned_at" -ErrorAction SilentlyContinue | ForEach-Object {
                                if (Test-SpawnLock -RoomDir $roomDir -Role $_.BaseName) { $anySpawnLock = $true }
                            }
                        }
                        if ($v2StateDef.type -ne 'triage' -and -not $anyPidAlive -and -not $anySpawnLock) { $activeWithNoPid++ }

                        # State timeout
                        if (Test-StateTimedOut $roomDir) {
                            Write-Log "ERROR" "[$taskRef] V2 state '$status' timed out after ${stateTimeout}s."
                            Stop-RoomProcesses $roomDir
                            if ($retries -lt $v2MaxRetries) {
                                ($retries + 1).ToString() | Out-File -FilePath (Join-Path $roomDir "retries") -Encoding utf8 -NoNewline
                                $restartState = if ($lifecycle.initial_state) { $lifecycle.initial_state } else { 'developing' }
                                Write-RoomStatus $roomDir $restartState
                                # LEAK-6 fix: re-resolve role from the restart state, not the timed-out state
                                $restartStateDef = $lifecycle.states.$restartState
                                $restartRole = if ($restartStateDef -and $restartStateDef.role) { $restartStateDef.role } else { $baseRole }
                                $restartBaseRole = $restartRole -replace ':.*$', ''
                                $restartTimeout = Resolve-RoleTimeout -RoleName $restartBaseRole -RoomDir $roomDir
                                if (Test-Path $resolveRoleScript) {
                                    $restartResolved = & $resolveRoleScript -RoleName $restartRole -AgentsDir $agentsDir -WarRoomsDir $WarRoomsDir
                                    Start-WorkerJob -RoomDir $roomDir -Role $restartBaseRole -Script $restartResolved.Runner -TaskRef $taskRef -TimeoutSeconds $restartTimeout -SkipLockCheck
                                } else {
                                    Start-WorkerJob -RoomDir $roomDir -Role $restartBaseRole -Script $workerScript -TaskRef $taskRef -TimeoutSeconds $restartTimeout -SkipLockCheck
                                }
                            } else {
                                Write-ManagerOrchestrationEvent -RoomDir $roomDir -EventType 'agent.run.timed_out' -Summary "$baseRole timed out in $status after manager state timeout." -Payload @{ reason = 'state_timeout_exhausted'; timeout_seconds = $stateTimeout; retries = $retries; max_retries = $v2MaxRetries } -Role $baseRole -State $status -Severity 'error' | Out-Null
                                Write-RoomStatus $roomDir 'failed'
                                Set-BlockedDescendants $taskRef
                                $script:planFailed = Invoke-PlanFailFast -RoomDir $roomDir -Reason 'state_timeout_exhausted' -Role $baseRole -State $status -Summary "$taskRef exhausted timeout retries in $status."
                                $script:shuttingDown = $true
                            }
                            continue
                        }

                        # PLAN-REVIEW shortcut — check all signal types the architect may post
                        if ($taskRef -eq 'PLAN-REVIEW') {
                            $passCount    = Get-MsgCount $roomDir "pass"
                            $approveCount = Get-MsgCount $roomDir "plan-approve"
                            $doneCount    = Get-MsgCount $roomDir "done"
                            $failCount    = Get-MsgCount $roomDir "fail"

                            Write-Log "DEBUG" "[$taskRef] PLAN-REVIEW shortcut: pass=$passCount approve=$approveCount done=$doneCount fail=$failCount"

                            # Log latest message bodies for debugging
                            if ($passCount -gt 0) {
                                $passBody = Get-LatestBody $roomDir "pass"
                                $passPreview = if ($passBody.Length -gt 200) { $passBody.Substring(0, 200) + '...' } else { $passBody }
                                Write-Log "DEBUG" "[$taskRef] Latest pass body: $passPreview"
                            }
                            if ($failCount -gt 0) {
                                $failBody = Get-LatestBody $roomDir "fail"
                                $failPreview = if ($failBody.Length -gt 200) { $failBody.Substring(0, 200) + '...' } else { $failBody }
                                Write-Log "DEBUG" "[$taskRef] Latest fail body: $failPreview"
                            }
                            if ($doneCount -gt 0) {
                                $doneBody = Get-LatestBody $roomDir "done"
                                $donePreview = if ($doneBody.Length -gt 200) { $doneBody.Substring(0, 200) + '...' } else { $doneBody }
                                Write-Log "DEBUG" "[$taskRef] Latest done body: $donePreview"
                            }
                            # Check for approval: pass signal, plan-approve signal, or done with approval keyword
                            $approved = $false
                            if ($passCount -gt 0 -or $approveCount -gt 0) {
                                $approved = $true
                                Write-Log "DEBUG" "[$taskRef] Approved via pass/plan-approve signal"
                            } elseif ($doneCount -gt 0) {
                                $doneBody = Get-LatestBody $roomDir "done"
                                if ($doneBody -match 'plan-approve|signoff|APPROVED|VERDICT:\s*(DONE|PASS)') {
                                    $approved = $true
                                    Write-Log "DEBUG" "[$taskRef] Approved via done body keyword match"
                                } else {
                                    Write-Log "DEBUG" "[$taskRef] done body did NOT match approval keywords"
                                }
                            } else {
                                Write-Log "DEBUG" "[$taskRef] No pass/approve/done signals — shortcut cannot decide"
                            }

                            if ($approved) {
                                $planApprovedFlag = Join-Path $WarRoomsDir ".plan_approved_$($taskRef -replace '[^a-zA-Z0-9-]','')"
                                Write-Log "INFO" "[$taskRef] Plan APPROVED. Transitioning to done."
                                Write-RoomStatus $roomDir 'done'
                                if (-not (Test-Path $planApprovedFlag)) {
                                    Complete-PlanApproval -TaskRef $taskRef
                                    "1" | Out-File -FilePath $planApprovedFlag -Encoding utf8 -NoNewline
                                }
                                continue
                            }

                            # Handle architect VERDICT: REJECT via fail signal or done body
                            if ($failCount -gt 0) {
                                $rejectBody = Get-LatestBody $roomDir "fail"
                                Write-Log "WARN" "[$taskRef] Plan REJECTED by architect."
                            } elseif ($doneCount -gt 0) {
                                $rejectBody = Get-LatestBody $roomDir "done"
                                if ($rejectBody -match 'VERDICT:\s*REJECT') {
                                    Write-Log "WARN" "[$taskRef] Plan REJECTED by architect."
                                }
                            }
                        }

                        # Triage mediation — ESCALATE means the epic roles need
                        # a short manager-mediated clarification loop. Convert
                        # the latest reviewer escalation into a manager 'fix'
                        # signal so the counterpart role can respond, then the
                        # normal lifecycle routes optimize.done back to review.
                        if ($v2StateDef.type -eq 'triage') {
                            $mediation = Invoke-TriageMediation -RoomDir $roomDir -Lifecycle $lifecycle -TaskRef $taskRef
                            if ($mediation -and -not $mediation.AlreadyPresent) {
                                if ($mediation.Started) {
                                    Write-Log "INFO" "[$taskRef] Triage mediation started manager for escalation from '$($mediation.RaisedBy)'."
                                } elseif ($mediation.Reason -in @('spawn-lock', 'pid-alive')) {
                                    Write-Log "DEBUG" "[$taskRef] Triage mediation already in progress for escalation from '$($mediation.RaisedBy)' (reason=$($mediation.Reason))."
                                } else {
                                    Write-Log "DEBUG" "[$taskRef] Triage mediation did not start manager (reason=$($mediation.Reason))."
                                }
                            }
                        }

                        # Signal detection — lifecycle-driven (derives signals + sender from lifecycle.json)
                        $matchedSignal = Find-LatestSignal -RoomDir $roomDir -Lifecycle $lifecycle -StateName $status

                        if ($matchedSignal) {
                            $transitionDef = $v2StateDef.signals.$matchedSignal
                            $targetState = $transitionDef.target
                            if ($v2StateDef.type -eq 'triage' -and (Get-Command Get-ManagerTriageDecisionNextState -ErrorAction SilentlyContinue)) {
                                $targetState = Get-ManagerTriageDecisionNextState -RoomDir $roomDir -Lifecycle $lifecycle -MatchedSignal $matchedSignal -DefaultTargetState $targetState
                            }
                            $actions = @()
                            if ($transitionDef.actions) { $actions = @($transitionDef.actions) }

                            # --- Retry exhaustion guard ---
                            # Signals with increment_retries (e.g. review.fail → optimize) must
                            # check against max_retries. Without this, the review→optimize loop
                            # runs indefinitely because the 'failed' decision state is never reached.
                            if ($actions -contains 'increment_retries' -and $retries -ge ($v2MaxRetries - 1)) {
                                Write-Log "WARN" "[$taskRef] Signal '$matchedSignal' would exceed max retries ($($retries+1)/$v2MaxRetries). Redirecting to failed."
                                Invoke-SignalActions -RoomDir $roomDir -Actions $actions -TaskRef $taskRef -BaseRole $baseRole
                                Write-ManagerOrchestrationEvent -RoomDir $roomDir -EventType 'lifecycle.retry.exhausted' -Summary "$taskRef exhausted lifecycle retries after '$matchedSignal'." -Payload @{ signal = $matchedSignal; retries = ($retries + 1); max_retries = $v2MaxRetries; reason = 'semantic_retry_exhausted' } -Role $baseRole -State $status -Severity 'error' | Out-Null
                                Write-RoomStatus $roomDir "failed"
                                Set-BlockedDescendants $taskRef
                                $script:planFailed = Invoke-PlanFailFast -RoomDir $roomDir -Reason 'retry_exhausted' -Role $baseRole -State $status -Summary "$taskRef exhausted retries after '$matchedSignal'."
                                $script:shuttingDown = $true
                                continue
                            }

                            Write-Log "INFO" "[$taskRef] V2 signal '$matchedSignal' in '$status' -> '$targetState'."
                            # Resolve the TARGET state's role so post_fix delivers to the fixer,
                            # not the current state's reviewer/worker.
                            $targetDef = $lifecycle.states.$targetState
                            $targetRoleForActions = if ($targetDef -and $targetDef.role) {
                                $targetDef.role -replace ':.*$', ''
                            } else { $baseRole }
                            Invoke-SignalActions -RoomDir $roomDir -Actions $actions -TaskRef $taskRef -BaseRole $targetRoleForActions
                            Write-RoomStatus $roomDir $targetState

                            if ($matchedSignal -eq 'fail' -and $actions -contains 'increment_retries') {
                                Write-ManagerOrchestrationEvent -RoomDir $roomDir -EventType 'epic.retrying' -Summary "$taskRef semantic QA fail routed to retry/optimize." -Payload @{ signal = $matchedSignal; retries = ($retries + 1); max_retries = $v2MaxRetries; target_state = $targetState } -Role $baseRole -State $status -Severity 'warn' -LastMessage (Get-LatestFailureMessage -RoomDir $roomDir -Role $baseRole) | Out-Null
                            }

                            # Reset crash-respawn counter on successful transition
                            $crashFile = Join-Path $roomDir "crash_respawns"
                            Remove-Item $crashFile -Force -ErrorAction SilentlyContinue

                            # Sync config.json assigned_role with the target state's role
                            $trDef = $lifecycle.states.$targetState
                            if ($trDef -and $trDef.role) {
                                $trBaseRole = $trDef.role -replace ':.*$', ''
                                $rcFile = Join-Path $roomDir "config.json"
                                if (Test-Path $rcFile) {
                                    $rc = Get-Content $rcFile -Raw | ConvertFrom-Json
                                    if ($rc.assignment) {
                                        $rc.assignment.assigned_role = $trBaseRole
                                        if ($rc.PSObject.Properties['jit_role_id']) { $rc.PSObject.Properties.Remove('jit_role_id') }
                                        $rc | ConvertTo-Json -Depth 10 | Out-File -FilePath $rcFile -Encoding utf8
                                    }
                                }
                            }

                            # Spawn target state's role agent
                            $targetDef = $lifecycle.states.$targetState
                            if ($targetDef -and $targetDef.role -and $targetDef.type -in @('work', 'review')) {
                                $targetRole = $targetDef.role
                                $targetBaseRole = $targetRole -replace ':.*$', ''
                                $targetTimeout = Resolve-RoleTimeout -RoleName $targetBaseRole -RoomDir $roomDir
                                if (Test-Path $resolveRoleScript) {
                                    $targetResolved = & $resolveRoleScript -RoleName $targetRole -AgentsDir $agentsDir -WarRoomsDir $WarRoomsDir
                                    Start-WorkerJob -RoomDir $roomDir -Role $targetBaseRole -Script $targetResolved.Runner -TaskRef $taskRef -TimeoutSeconds $targetTimeout -SkipLockCheck
                                } else {
                                    Start-WorkerJob -RoomDir $roomDir -Role $targetBaseRole -Script $workerScript -TaskRef $taskRef -TimeoutSeconds $targetTimeout -SkipLockCheck
                                }
                            }
                        }
                        else {
                            # No signal — ensure worker/reviewer is alive
                            $stateRole = $v2StateDef.role
                            if ($stateRole -and $v2StateDef.type -notin @('triage', 'decision')) {
                                $stateBaseRole = $stateRole -replace ':.*$', ''
                                $statePidFile = Join-Path $roomDir "pids" "$stateBaseRole.pid"
                                $pidAlive = Test-PidAlive $statePidFile
                                $spawnLocked = Test-SpawnLock -RoomDir $roomDir -Role $stateBaseRole
                                Write-Log "INFO" "[$taskRef] No signal matched. role='$stateBaseRole' pidAlive=$pidAlive spawnLocked=$spawnLocked status='$status'"

                                $failedRoleRun = Get-FreshFailedRoleRun -RoomDir $roomDir -Role $stateBaseRole
                                if ($failedRoleRun) {
                                    Write-Log "ERROR" "[$taskRef] Role '$stateBaseRole' reported failed in '$status'. Marking room as failed for manager decision handling."
                                    Remove-Item (Join-Path $roomDir "crash_respawns") -Force -ErrorAction SilentlyContinue
                                    $script:planFailed = Invoke-PlanFailFast -RoomDir $roomDir -Reason 'role_run_failed' -Role $stateBaseRole -State $status -Summary "$taskRef role '$stateBaseRole' failed in '$status'."
                                    $script:shuttingDown = $true
                                    continue
                                }

                                if (-not $pidAlive -and -not $spawnLocked) {
                                    # Guard: check if a signal is pending but hasn't been processed yet.
                                    $pendingSignalCheck = Find-LatestSignal -RoomDir $roomDir -Lifecycle $lifecycle -StateName $status
                                    if ($pendingSignalCheck) {
                                        Write-Log "DEBUG" "[$taskRef] Signal '$pendingSignalCheck' pending in '$status' — skipping re-spawn."
                                    } else {
                                        # --- Crash-respawn guard ---
                                        # If the agent keeps dying without posting any signal,
                                        # cap consecutive crash-respawns to prevent infinite loops.
                                        $crashFile = Join-Path $roomDir "crash_respawns"
                                        $crashCount = if (Test-Path $crashFile) { [int](Get-Content $crashFile -Raw).Trim() } else { 0 }
                                        $crashCount++
                                        $maxCrashRespawns = 3
                                        if ($crashCount -gt $maxCrashRespawns) {
                                            Write-Log "ERROR" "[$taskRef] Agent '$stateRole' crashed $crashCount times in '$status' without producing a signal. Marking as failed."
                                            Write-ManagerOrchestrationEvent -RoomDir $roomDir -EventType 'agent.run.failed' -Summary "$stateBaseRole exhausted crash respawns in $status." -Payload @{ reason = 'crash_respawn_exhausted'; crash_count = $crashCount; max_crash_respawns = $maxCrashRespawns } -Role $stateBaseRole -State $status -Severity 'error' | Out-Null
                                            $script:planFailed = Invoke-PlanFailFast -RoomDir $roomDir -Reason 'crash_respawn_exhausted' -Role $stateBaseRole -State $status -Summary "$taskRef exhausted crash respawns in '$status'."
                                            $script:shuttingDown = $true
                                            # Reset the crash counter for the next lifecycle attempt
                                            Remove-Item $crashFile -Force -ErrorAction SilentlyContinue
                                        } else {
                                            $crashCount.ToString() | Out-File -FilePath $crashFile -Encoding utf8 -NoNewline
                                            # Kill any lingering processes from the crashed agent before respawning
                                            # (prevents orphan process pile-up that can exhaust system RAM)
                                            Stop-RoomProcesses $roomDir
                                            Write-Log "DEBUG" "[$taskRef] No pending signal, no PID, no lock — will re-spawn '$stateRole' (crash $crashCount/$maxCrashRespawns)."
                                            $respawnTimeout = Resolve-RoleTimeout -RoleName $stateBaseRole -RoomDir $roomDir
                                            if (Test-Path $resolveRoleScript) {
                                                $stateResolved = & $resolveRoleScript -RoleName $stateRole -AgentsDir $agentsDir -WarRoomsDir $WarRoomsDir
                                                Write-Log "INFO" "[$taskRef] Spawning '$stateRole' for '$status'."
                                                Start-WorkerJob -RoomDir $roomDir -Role $stateBaseRole -Script $stateResolved.Runner -TaskRef $taskRef -TimeoutSeconds $respawnTimeout
                                            } else {
                                                Start-WorkerJob -RoomDir $roomDir -Role $stateBaseRole -Script $workerScript -TaskRef $taskRef -TimeoutSeconds $respawnTimeout
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                    default {
                        Write-Log "WARN" "[$taskRef] Unknown lifecycle type '$($v2StateDef.type)' for state '$status'"
                        $allPassed = $false; $allTerminal = $false
                    }
                }
            }
        }
    }

    # === Deadlock detection ===
    if ($totalActive -gt 0 -and $activeWithNoPid -eq $totalActive) {
        $stallCycles++
        if ($stallCycles -ge 12) {  # 12 cycles × 5s poll = 60s — enough for LLM API calls to complete
            Write-Log "WARN" "Deadlock detected: $totalActive rooms active but no PIDs alive for 2 cycles. Attempting recovery..."
            Get-ChildItem -Path $WarRoomsDir -Directory -Filter "room-*" -ErrorAction SilentlyContinue | ForEach-Object {
                $rd = $_.FullName
                $ls = if (Test-Path (Join-Path $rd "status")) { (Get-Content (Join-Path $rd "status") -Raw).Trim() } else { "" }
                $lr = if (Test-Path (Join-Path $rd "retries")) { [int](Get-Content (Join-Path $rd "retries") -Raw).Trim() } else { 0 }
                $lt = if (Test-Path (Join-Path $rd "task-ref")) { (Get-Content (Join-Path $rd "task-ref") -Raw).Trim() } else { "UNKNOWN" }

                # --- Skip rooms in terminal states (already completed or failed) ---
                $lsc = if (Get-Command ConvertTo-CanonicalRoomStatus -ErrorAction SilentlyContinue) { ConvertTo-CanonicalRoomStatus -Status $ls } else { $ls }
                if ($lsc -in @('done', 'failed', 'blocked', '')) {
                    return  # ForEach-Object: skip this room
                }

                # --- Safety net: cap total deadlock recoveries per room ---
                $dlFile = Join-Path $rd "deadlock_recoveries"
                $dlCount = if (Test-Path $dlFile) { [int](Get-Content $dlFile -Raw).Trim() } else { 0 }
                if ($dlCount -ge 3) {
                    Write-Log "ERROR" "[$lt] Max deadlock recoveries (3) exceeded. Marking as failed."
                    Write-RoomStatus $rd "failed"
                    Set-BlockedDescendants $lt
                    return  # ForEach-Object uses 'return' to skip to next item
                }
                ($dlCount + 1).ToString() | Out-File -FilePath $dlFile -Encoding utf8 -NoNewline

                # Risk 6 fix: Resolve role from lifecycle state, not config.json.
                # Multi-role lifecycles (e.g. reporting.role=reporter) need the state's role.
                $dlLifecycleFile = Join-Path $rd "lifecycle.json"
                $dlLifecycle = if (Test-Path $dlLifecycleFile) { Get-Content $dlLifecycleFile -Raw | ConvertFrom-Json } else { $null }
                $dlStateDef = if ($dlLifecycle -and $dlLifecycle.states -and $dlLifecycle.states.$ls) { $dlLifecycle.states.$ls } else { $null }

                $dlRole = "engineer"
                if ($dlStateDef -and $dlStateDef.role) {
                    $dlRole = ($dlStateDef.role -replace ':.*$', '')
                } else {
                    $dlRoomConfig = Join-Path $rd "config.json"
                    if (Test-Path $dlRoomConfig) {
                        $dlRc = Get-Content $dlRoomConfig -Raw | ConvertFrom-Json
                        if ($dlRc.assignment -and $dlRc.assignment.assigned_role) {
                            $dlRole = $dlRc.assignment.assigned_role -replace ':.*$', ''
                        }
                    }
                }

                if ($dlStateDef -and $dlStateDef.type -in @('work', 'review')) {
                    $restartState = if ($dlLifecycle.initial_state) { $dlLifecycle.initial_state } else { 'developing' }

                    # LEAK-7 fix: check for pending signals before deadlock reset
                    $dlPendingSignal = $null
                    if ($dlLifecycle) {
                        $dlPendingSignal = Find-LatestSignal -RoomDir $rd -Lifecycle $dlLifecycle -StateName $ls
                    }
                    if ($dlPendingSignal) {
                        Write-Log "INFO" "[$lt] Deadlock recovery: signal '$dlPendingSignal' pending — skipping reset."
                        return  # Let normal signal detection handle it next iteration
                    }

                    # Risk 2 fix: Clean stale PIDs before transition (prevents double retry increment)
                    Stop-RoomProcesses $rd

                    # Risk 3+4 fix: DO NOT increment retries here.
                    # Retries should only be incremented by lifecycle signal actions (e.g. increment_retries on QA fail).
                    # Incrementing retries during deadlock recovery corrupts the done-count gate (Risk 3)
                    # and compounds into QA cascade deadlocks (Risk 4).
                    # Exhaustion is handled by the deadlock_recoveries cap (line 1113), not by lifecycle retries.

                    # Risk 6 fix: Resolve restart state's role from lifecycle for correct runner
                    $restartStateDef = if ($dlLifecycle.states.$restartState) { $dlLifecycle.states.$restartState } else { $null }
                    $dlRestartRole = if ($restartStateDef -and $restartStateDef.role) { ($restartStateDef.role -replace ':.*$', '') } else { $dlRole }

                    Write-Log "WARN" "[$lt] Deadlock recovery ($($dlCount+1)/3): restarting $dlRestartRole via $restartState."
                    Write-RoomStatus $rd $restartState

                    # Risk 2 fix: Spawn worker immediately (don't rely on next iteration's respawn branch)
                    $dlTimeout = Resolve-RoleTimeout -RoleName $dlRestartRole -RoomDir $rd
                    $dlResolveRole = Join-Path $agentsDir "roles" "_base" "Resolve-Role.ps1"
                    if (Test-Path $dlResolveRole) {
                        $dlResolved = & $dlResolveRole -RoleName ($restartStateDef.role) -AgentsDir $agentsDir -WarRoomsDir $WarRoomsDir
                        Start-WorkerJob -RoomDir $rd -Role $dlRestartRole -Script $dlResolved.Runner -TaskRef $lt -TimeoutSeconds $dlTimeout -SkipLockCheck
                    }
                } else {
                    Write-Log "WARN" "[$lt] Deadlock recovery: state '$ls' not recoverable. Skipping."
                }
            }
            $stallCycles = 0
        }
    }
    else {
        $stallCycles = 0
    }

    # === Release check ===
    if ($roomCount -gt 0 -and $allPassed) {
        Write-Host ""

        # Safety net: normal operation merges each completed round immediately,
        # so by release time this should usually have nothing left to do.
        if (Get-Command Complete-PlanWorkspaceMerge -ErrorAction SilentlyContinue) {
            try {
                $planMergeResult = Complete-PlanWorkspaceMerge -WarRoomsDir $WarRoomsDir
                if (-not $planMergeResult.Integrated) {
                    $mergeDetail = "status=$($planMergeResult.Status)"
                    if ($planMergeResult.Conflicted) { $mergeDetail += " conflicted=$($planMergeResult.Conflicted)" }
                    if (@($planMergeResult.Pending).Count -gt 0) { $mergeDetail += " pending=$(@($planMergeResult.Pending) -join ',')" }
                    Write-Log "ERROR" "Plan workspace merge failed: $mergeDetail"
                    $mergeFailRoomDir = if ($planMergeResult.Conflicted) { Join-Path $WarRoomsDir "$($planMergeResult.Conflicted)" } else { $WarRoomsDir }
                    $script:planFailed = Invoke-PlanFailFast -RoomDir $mergeFailRoomDir -Reason "workspace_merge_$($planMergeResult.Status)" -Role 'manager' -State 'done' -Summary "Plan workspace merge failed: $mergeDetail. Resolve, then run workspace/Merge-Plan.ps1 manually."
                    Remove-Item $managerPidFile -Force -ErrorAction SilentlyContinue
                    break
                }
                if (@($planMergeResult.Merged).Count -gt 0) {
                    Write-Log "INFO" "Plan workspace merge integrated: $(@($planMergeResult.Merged) -join ', ')"
                }
            } catch {
                Write-Log "ERROR" "Plan workspace merge failed: $($_.Exception.Message)"
                $script:planFailed = Invoke-PlanFailFast -RoomDir $WarRoomsDir -Reason 'workspace_merge_failed' -Role 'manager' -State 'done' -Summary "Plan workspace merge failed: $($_.Exception.Message)"
                Remove-Item $managerPidFile -Force -ErrorAction SilentlyContinue
                break
            }
        }

        Write-Log "INFO" "All $roomCount rooms done. Drafting release..."

        $draftScript = Join-Path $releaseDir "draft.sh"
        $draftOk = $true
        if (Test-Path $draftScript) {
            $draftOut = bash $draftScript $agentsDir 2>&1
            $draftOk = ($LASTEXITCODE -eq 0)
            if (-not $draftOk) { Write-Log "ERROR" "draft.sh failed: $draftOut" }
        }

        Write-Log "INFO" "Collecting signoffs..."
        $signoffScript = Join-Path $releaseDir "signoff.sh"
        $signoffOk = $false
        if ($draftOk -and (Test-Path $signoffScript)) {
            $signoffOut = bash $signoffScript $agentsDir 2>&1
            $signoffOk = ($LASTEXITCODE -eq 0)
            if (-not $signoffOk) { Write-Log "ERROR" "signoff.sh failed: $signoffOut" }
        }
        elseif (-not (Test-Path $signoffScript)) {
            $signoffOk = $true  # No signoff script means auto-approve
        }

        if ($signoffOk) {
            Write-Host ""
            Write-Host "============================================"
            Write-Log "INFO" "RELEASE COMPLETE! Release notes: $agentsDir/RELEASE.md"
            Write-Host "  Release notes: $agentsDir/RELEASE.md"
            Write-Host "============================================"
            $firstRoomDir = (Get-ChildItem -Path $WarRoomsDir -Directory -Filter "room-*" -ErrorAction SilentlyContinue | Sort-Object Name | Select-Object -First 1).FullName
            $completionRoomDir = Join-Path $WarRoomsDir ("room-{0:D3}" -f [int]$roomCount)
            if (-not (Test-Path $completionRoomDir)) { $completionRoomDir = $firstRoomDir }
            $completionLastMessage = if ($completionRoomDir) { Get-LatestChannelMessage -RoomDir $completionRoomDir -Role 'manager' } else { $null }
            if ($completionRoomDir) {
                Write-ManagerOrchestrationEvent -RoomDir $completionRoomDir -EventType 'plan.run.completed' -Summary "Plan run completed successfully." -Payload @{ room_count = $roomCount; role = 'manager'; agent_name = 'manager' } -Role 'manager' -Severity 'info' -LastMessage $completionLastMessage | Out-Null
            }
            Remove-Item $managerPidFile -Force -ErrorAction SilentlyContinue
            break
        }
        else {
            if (-not (Test-Path variable:script:signoffAttempts)) {
                $script:signoffAttempts = 0
            }
            $script:signoffAttempts++
            $maxSignoffAttempts = 3
            if ($script:signoffAttempts -ge $maxSignoffAttempts) {
                Write-Log "WARN" "Signoff rejected $maxSignoffAttempts times. Exiting with release pending manual review."
                Write-Host ""
                Write-Host "============================================"
                Write-Log "INFO" "RELEASE PENDING REVIEW: $agentsDir/RELEASE.md"
                Write-Host "  All rooms are done but signoff was not approved after $maxSignoffAttempts attempts."
                Write-Host "  Review RELEASE.md manually and re-run signoff."
                Write-Host "============================================"
                Remove-Item $managerPidFile -Force -ErrorAction SilentlyContinue
                break
            }
            Write-Log "ERROR" "Signoff failed (attempt $($script:signoffAttempts)/$maxSignoffAttempts). Continuing loop..."
        }
    }

    # === Exit on all-terminal (some failed/blocked) ===
    if ($roomCount -gt 0 -and -not $allPassed -and $allTerminal) {
        Write-Host ""
        $doneRooms = $roomCount - $failedCount
        Write-Log "ERROR" "All rooms terminal: $doneRooms done, $failedCount failed/blocked. Exiting."
        Write-Log "INFO" "To resume: Start-Plan.ps1 -PlanFile <plan> -Resume"
        Remove-Item $managerPidFile -Force -ErrorAction SilentlyContinue
        break
    }

    # OPT-002: Time-based progress throttle (10s minimum interval)
    $nowEpoch = Get-UnixEpoch
    if ($roomCount -gt 0 -and ($nowEpoch - $script:lastProgressUpdate) -ge 10) {
        $doneCount = 0
        $failedSummary = 0
        $blockedCount = 0
        Get-ChildItem -Path $WarRoomsDir -Directory -Filter "room-*" -ErrorAction SilentlyContinue | ForEach-Object {
            $s2 = if (Test-Path (Join-Path $_.FullName "status")) { (Get-Content (Join-Path $_.FullName "status") -Raw).Trim() } else { "" }
            $s2c = if (Get-Command ConvertTo-CanonicalRoomStatus -ErrorAction SilentlyContinue) { ConvertTo-CanonicalRoomStatus -Status $s2 } else { $s2 }
            if ($s2c -eq 'done') { $doneCount++ }
            if ($s2c -eq 'failed') { $failedSummary++ }
            if ($s2 -eq 'blocked') { $blockedCount++ }
        }
        Write-Log "INFO" "Progress: $doneCount/$roomCount done, $failedSummary failed, $blockedCount blocked (iteration $iteration)"

        # Update progress file if available
        if (Test-Path $updateProgress) {
            try { & $updateProgress -WarRoomsDir $WarRoomsDir } catch { }
        }
        $script:lastProgressUpdate = $nowEpoch
    }

    # Capture completed manager triage jobs before pruning. This records the
    # Invoke-Agent result (log/output file) and falls back to the latest manager
    # channel message from the canonical room so triage protocol can be audited
    # even when the agent posts to the wrong path or fails to post.
    Get-Job -Name "ostwin-triage-*-manager" -ErrorAction SilentlyContinue | Where-Object State -eq 'Completed' | ForEach-Object {
        $triageJob = $_
        $triageResult = $null
        try { $triageResult = Receive-Job $triageJob -ErrorAction SilentlyContinue 2>&1 } catch { }
        $exitCode = $null
        $outputFile = ''
        $outputPreview = ''
        $resultObj = @($triageResult | Where-Object { $_ -and $_.PSObject.Properties['ExitCode'] } | Select-Object -Last 1)
        if ($resultObj) {
            $exitCode = $resultObj.ExitCode
            if ($resultObj.PSObject.Properties['OutputFile']) { $outputFile = [string]$resultObj.OutputFile }
            if ($resultObj.PSObject.Properties['Output'] -and $resultObj.Output) {
                $outText = [string]$resultObj.Output
                $outputPreview = if ($outText.Length -gt 300) { $outText.Substring(0, 300) + '...' } else { $outText }
            }
        }

        $roomNameFromJob = ''
        if ($triageJob.Name -match '^ostwin-triage-(?<room>.+)-manager$') { $roomNameFromJob = $Matches['room'] }
        $triageRoomDir = if ($roomNameFromJob) { Join-Path $WarRoomsDir $roomNameFromJob } else { '' }
        $latestManagerSummary = ''
        if ($triageRoomDir -and (Test-Path $triageRoomDir) -and (Test-Path $readMessages)) {
            try {
                $latestManager = & $readMessages -RoomDir $triageRoomDir -FilterFrom 'manager' -Last 1 -AsObject
                if ($latestManager -and $latestManager.Count -gt 0) {
                    $m = @($latestManager)[-1]
                    $body = if ($m.body) { [string]$m.body } else { '' }
                    $bodyPreview = if ($body.Length -gt 220) { $body.Substring(0, 220) + '...' } else { $body }
                    $latestManagerSummary = "latest_manager_message id=$($m.id) type=$($m.type) to=$($m.to) body=[$bodyPreview]"
                }
            } catch {
                $latestManagerSummary = "latest_manager_message_error=$($_.Exception.Message)"
            }
        }

        Write-Log "INFO" "Manager triage job '$($triageJob.Name)' completed exit=$exitCode outputFile='$outputFile' $latestManagerSummary outputPreview=[$outputPreview]"
        Remove-Job $triageJob -Force -ErrorAction SilentlyContinue
    }

    Get-Job -Name "ostwin-triage-*-manager" -ErrorAction SilentlyContinue | Where-Object State -eq 'Failed' | ForEach-Object {
        $failedOutput = $null
        try { $failedOutput = Receive-Job $_ -ErrorAction SilentlyContinue 2>&1 } catch { }
        Write-Log "ERROR" "Manager triage job '$($_.Name)' failed: $failedOutput"
        Remove-Job $_ -Force -ErrorAction SilentlyContinue
    }

    # Prune completed PowerShell background jobs to prevent memory accumulation.
    # Start-WorkerJob uses Start-Job which creates job objects that persist until
    # removed. Without cleanup, long-running plans accumulate hundreds of stale jobs.
    Get-Job -Name "ostwin-worker-*" -ErrorAction SilentlyContinue | Where-Object State -eq 'Completed' | Remove-Job -Force -ErrorAction SilentlyContinue
    Get-Job -Name "ostwin-worker-*" -ErrorAction SilentlyContinue | Where-Object State -eq 'Failed' | ForEach-Object {
        $failedOutput = $null
        try { $failedOutput = Receive-Job $_ -ErrorAction SilentlyContinue 2>&1 } catch { }
        Write-Log "ERROR" "Worker job '$($_.Name)' failed: $failedOutput"
        Remove-Job $_ -Force -ErrorAction SilentlyContinue
    }
    # Detect and kill zombie jobs: Running state but child process is dead.
    # These leak ~50MB per runspace and accumulate during long plans with retries.
    $maxJobAge = $stateTimeout * 2
    Get-Job -Name "ostwin-worker-*" -ErrorAction SilentlyContinue | Where-Object {
        $_.State -eq 'Running' -and $_.PSBeginTime -and
        ((Get-Date) - $_.PSBeginTime).TotalSeconds -gt $maxJobAge
    } | ForEach-Object {
        Write-Log "WARN" "Killing zombie job: $($_.Name) (running for $([int]((Get-Date) - $_.PSBeginTime).TotalSeconds)s, exceeds ${maxJobAge}s limit)"
        Stop-Job $_ -PassThru -ErrorAction SilentlyContinue | Remove-Job -Force -ErrorAction SilentlyContinue
    }

    Start-Sleep -Seconds $pollInterval
}
} # end try
finally {
    # --- Cleanup on exit (runs on graceful exit, Ctrl+C, and unhandled errors) ---
    Write-Log "INFO" "Shutting down all war-rooms..."
    # Kill all agent processes in every room
    Get-ChildItem -Path $WarRoomsDir -Directory -Filter "room-*" -ErrorAction SilentlyContinue | ForEach-Object {
        Stop-RoomProcesses $_.FullName
    }
    # Stop all PowerShell background jobs (Start-WorkerJob creates these)
    Get-Job -ErrorAction SilentlyContinue | Stop-Job -PassThru -ErrorAction SilentlyContinue | Remove-Job -Force -ErrorAction SilentlyContinue
    # Clean up manager PID file
    Remove-Item $managerPidFile -Force -ErrorAction SilentlyContinue
    Write-Log "INFO" "Shutdown complete."
}

if ($script:planFailed) {
    exit 1
}
