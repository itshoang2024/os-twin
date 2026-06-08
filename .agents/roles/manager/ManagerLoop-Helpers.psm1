<#
.SYNOPSIS
    Helper functions for the Manager Loop — extracted for testability & coverage.

.DESCRIPTION
    This module is dot-sourced by Start-ManagerLoop.ps1 and can be independently
    imported by Pester tests to achieve code-coverage instrumentation of the
    manager's core logic without running the infinite while-loop.

    Functions exported:
      Get-UnixEpoch, Write-AtomicFile, Test-ValidRoomState,
      Get-ActiveCount, Get-MsgCount, Get-LatestBody,
      Test-StateTimedOut, Stop-RoomProcesses, Write-RoomStatus,
      Get-RoomOrchestrationContext, Get-LatestFailureMessage,
      Write-ManagerOrchestrationEvent, Invoke-PlanFailFast,
      Find-LatestSignal, Invoke-SignalActions, Write-Log,
      Write-SpawnLock, Test-SpawnLock, Start-WorkerJob,
      Get-CachedDag, Set-BlockedDescendants, Invoke-ManagerTriage,
      Write-TriageContext, Complete-PlanApproval,
      Resolve-WorkerForState, Invoke-PlanReviewShortcut
#>

#region --- Module-level state (injected by Start-ManagerLoop.ps1 via Set-ManagerLoopContext) ---
$script:_ctx = $null

function Set-ManagerLoopContext {
    <#
    .SYNOPSIS
        Injects runtime context from Start-ManagerLoop.ps1 into this module.
        Called once at startup (or from test BeforeAll) to bind all script-scope
        dependencies (paths, config, cache references).
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [hashtable]$Context
    )
    $script:_ctx = $Context
}

function Get-ManagerLoopContext {
    [CmdletBinding()]
    param()
    return $script:_ctx
}

# Convenience accessors (short names used internally)
function _ctx([string]$Key) { return $script:_ctx[$Key] }
#endregion

# ---------------------------------------------------------------------------
# Get-UnixEpoch — culture-invariant epoch timestamp
# Replaces fragile [int][double]::Parse((Get-Date -UFormat %s)) pattern
# which breaks in non-en-US locales (comma decimal separator).
# ---------------------------------------------------------------------------
function Get-UnixEpoch {
    [CmdletBinding()]
    [OutputType([long])]
    param()
    [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
}

# ---------------------------------------------------------------------------
# Write-AtomicFile — atomic file write via tmp+rename
# Prevents partial reads during concurrent access to state files.
# ---------------------------------------------------------------------------
function Write-AtomicFile {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Content
    )
    $tmp = "$Path.tmp.$PID"
    try {
        [System.IO.File]::WriteAllText($tmp, $Content, [System.Text.Encoding]::UTF8)
        [System.IO.File]::Move($tmp, $Path, $true)
    } catch {
        # Fallback for older .NET runtimes without Move(,,bool) overload
        if (Test-Path $tmp) {
            Copy-Item $tmp $Path -Force
            Remove-Item $tmp -Force -ErrorAction SilentlyContinue
        } else {
            $Content | Out-File -FilePath $Path -Encoding utf8 -NoNewline
        }
    }
}

# ---------------------------------------------------------------------------
# Test-ValidRoomState — validates state name against lifecycle definition
# ---------------------------------------------------------------------------
function Test-ValidRoomState {
    [CmdletBinding()]
    [OutputType([bool])]
    param(
        [Parameter(Mandatory)][string]$State,
        [PSCustomObject]$Lifecycle
    )
    if (-not $Lifecycle -or -not $Lifecycle.states) { return $true }
    return ($null -ne $Lifecycle.states.$State)
}

function ConvertTo-CanonicalRoomStatus {
    [CmdletBinding()]
    param([AllowEmptyString()][string]$Status)

    switch ($Status) {
        'passed'       { return 'done' }
        'failed-final' { return 'failed' }
        'fixing'       { return 'optimize' }
        default        { return $Status }
    }
}

# ---------------------------------------------------------------------------
# Get-ActiveCount
# ---------------------------------------------------------------------------
function Get-ActiveCount {
    [CmdletBinding()]
    param()
    $WarRoomsDir = _ctx 'WarRoomsDir'
    $count = 0
    Get-ChildItem -Path $WarRoomsDir -Directory -Filter "room-*" -ErrorAction SilentlyContinue | ForEach-Object {
        $s = if (Test-Path (Join-Path $_.FullName "status")) {
            (Get-Content (Join-Path $_.FullName "status") -Raw).Trim()
        } else { "pending" }
        $canonical = ConvertTo-CanonicalRoomStatus -Status $s
        if ($canonical -notin @('pending', 'done', 'failed', 'blocked', '')) { $count++ }
    }
    return $count
}

# ---------------------------------------------------------------------------
# Get-MsgCount
# ---------------------------------------------------------------------------
function Get-MsgCount {
    [CmdletBinding()]
    param([string]$RoomDir, [string]$MsgType)
    $readMessages = _ctx 'readMessages'
    try {
        $msgs = & $readMessages -RoomDir $RoomDir -FilterType $MsgType -AsObject
        if ($msgs) { return $msgs.Count }
    }
    catch {
        Write-Log "DEBUG" "[Get-MsgCount] Error reading '$MsgType' from ${RoomDir}: $($_.Exception.Message)"
    }
    return 0
}

# ---------------------------------------------------------------------------
# Get-LatestBody
# ---------------------------------------------------------------------------
function Get-LatestBody {
    [CmdletBinding()]
    param([string]$RoomDir, [string]$MsgType)
    $readMessages = _ctx 'readMessages'
    try {
        $msgs = & $readMessages -RoomDir $RoomDir -FilterType $MsgType -Last 1 -AsObject
        if ($msgs -and $msgs.Count -gt 0) { return $msgs[-1].body }
    }
    catch {
        Write-Log "DEBUG" "[Get-LatestBody] Error reading '$MsgType' from ${RoomDir}: $($_.Exception.Message)"
    }
    return ""
}

# ---------------------------------------------------------------------------
# Get-RoomOrchestrationContext
# Reads the canonical event metadata stamped into room config by Start-Plan.
# Falls back to environment for compatibility with direct test/runtime invokes.
# ---------------------------------------------------------------------------
function Get-RoomOrchestrationContext {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$RoomDir)

    $roomId = Split-Path $RoomDir -Leaf
    $planId = $env:OSTWIN_PLAN_ID
    $runId = $env:OSTWIN_RUN_ID
    $eventsPath = $env:OSTWIN_EVENTS_PATH
    $epicRef = if (Test-Path (Join-Path $RoomDir 'task-ref')) { (Get-Content (Join-Path $RoomDir 'task-ref') -Raw).Trim() } else { '' }
    $state = if (Test-Path (Join-Path $RoomDir 'status')) { (Get-Content (Join-Path $RoomDir 'status') -Raw).Trim() } else { 'unknown' }

    $configFile = Join-Path $RoomDir 'config.json'
    if (Test-Path $configFile) {
        try {
            $cfg = Get-Content $configFile -Raw | ConvertFrom-Json
            if ($cfg.plan_id) { $planId = $cfg.plan_id }
            if ($cfg.run_id) { $runId = $cfg.run_id }
            if ($cfg.events_path) { $eventsPath = $cfg.events_path }
            if ($cfg.room_id) { $roomId = $cfg.room_id }
            if ($cfg.task_ref) { $epicRef = $cfg.task_ref }
            if ($cfg.status -and $cfg.status.current) { $state = $cfg.status.current }
        } catch {
            Write-Log 'DEBUG' "[Get-RoomOrchestrationContext] Error reading ${configFile}: $($_.Exception.Message)"
        }
    }

    if ([string]::IsNullOrWhiteSpace($runId) -and -not [string]::IsNullOrWhiteSpace($planId)) { $runId = 'run_legacy' }

    return [pscustomobject]@{
        PlanId     = $planId
        RunId      = $runId
        EventsPath = $eventsPath
        RoomId     = $roomId
        EpicRef    = $epicRef
        State      = $state
    }
}

# ---------------------------------------------------------------------------
# Get-LatestFailureMessage
# Captures the latest relevant semantic failure message for epic.failed payloads.
# If no channel message exists, falls back to the per-room plan log preview.
# ---------------------------------------------------------------------------
function Get-LatestFailureMessage {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$RoomDir,
        [string]$Role = ''
    )

    $readMessages = _ctx 'readMessages'
    foreach ($msgType in @('fail', 'error', 'fix')) {
        try {
            $msgs = & $readMessages -RoomDir $RoomDir -FilterType $msgType -Last 1 -AsObject
            if ($msgs -and $msgs.Count -gt 0) {
                $latest = $msgs[-1]
                $body = if ($latest.body) { [string]$latest.body } else { '' }
                return [ordered]@{
                    message_id   = if ($latest.id) { $latest.id } elseif ($latest.message_id) { $latest.message_id } else { '' }
                    type         = if ($latest.type) { $latest.type } else { $msgType }
                    from         = if ($latest.from) { $latest.from } else { '' }
                    body_preview = if ($body.Length -gt 500) { $body.Substring(0, 500) } else { $body }
                    artifact     = ''
                }
            }
        } catch {
            Write-Log 'DEBUG' "[Get-LatestFailureMessage] Error reading '$msgType' from ${RoomDir}: $($_.Exception.Message)"
        }
    }

    $artifactRole = if ($Role) { ($Role -replace ':.*$', '') } else { '' }
    $candidateFiles = @()
    $ctx = Get-RoomOrchestrationContext -RoomDir $RoomDir
    if ($ctx -and -not [string]::IsNullOrWhiteSpace($ctx.PlanId) -and -not [string]::IsNullOrWhiteSpace($ctx.RoomId)) {
        $_homeDir = if ($env:HOME) { $env:HOME } else { $env:USERPROFILE }
        $ostwinHome = if ($env:OSTWIN_HOME) { $env:OSTWIN_HOME } else { Join-Path $_homeDir '.ostwin' }
        $planLogsDir = Join-Path (Join-Path $ostwinHome '.agents') 'plans'
        $safePlanId = $ctx.PlanId -replace '[^A-Za-z0-9._-]', '_'
        $safeRoomId = $ctx.RoomId -replace '[^A-Za-z0-9._-]', '_'
        $candidateFiles += (Join-Path $planLogsDir "$safePlanId.$safeRoomId.log")
    }
    if ($artifactRole) { $candidateFiles += (Join-Path $RoomDir (Join-Path 'artifacts' "$artifactRole-output.txt")) }
    $candidateFiles += (Join-Path $RoomDir (Join-Path 'artifacts' 'qa-output.txt'))
    $candidateFiles += (Join-Path $RoomDir (Join-Path 'artifacts' 'engineer-output.txt'))

    foreach ($outputFile in $candidateFiles) {
        if (Test-Path $outputFile) {
            try {
                $text = Get-Content $outputFile -Raw -ErrorAction Stop
                $preview = if ($text.Length -gt 500) { $text.Substring(0, 500) } else { $text }
                return [ordered]@{
                    message_id   = ''
                    type         = 'artifact'
                    from         = $artifactRole
                    body_preview = $preview
                    artifact     = $outputFile
                }
            } catch {
                Write-Log 'DEBUG' "[Get-LatestFailureMessage] Error reading ${outputFile}: $($_.Exception.Message)"
            }
        }
    }

    return $null
}

# ---------------------------------------------------------------------------
# Get-LatestChannelMessage
# Captures the latest channel message for a role so plan-level events can carry
# useful context from the room that produced the final manager signal.
# ---------------------------------------------------------------------------
function Get-LatestChannelMessage {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$RoomDir,
        [string]$Role = ''
    )

    $readMessages = _ctx 'readMessages'
    try {
        $args = @{
            RoomDir  = $RoomDir
            Last     = 1
            AsObject = $true
        }
        if ($Role) { $args['FilterFrom'] = $Role }
        $msgs = & $readMessages @args
        if ($msgs -and $msgs.Count -gt 0) {
            $latest = $msgs[-1]
            $body = if ($latest.body) { [string]$latest.body } else { '' }
            return [ordered]@{
                message_id   = if ($latest.id) { $latest.id } elseif ($latest.message_id) { $latest.message_id } else { '' }
                type         = if ($latest.type) { $latest.type } else { '' }
                from         = if ($latest.from) { $latest.from } else { '' }
                to           = if ($latest.to) { $latest.to } else { '' }
                ref          = if ($latest.ref) { $latest.ref } else { '' }
                ts           = if ($latest.ts) { $latest.ts } else { '' }
                body_preview = if ($body.Length -gt 500) { $body.Substring(0, 500) } else { $body }
            }
        }
    } catch {
        Write-Log 'DEBUG' "[Get-LatestChannelMessage] Error reading latest message from ${RoomDir}: $($_.Exception.Message)"
    }

    return $null
}

# ---------------------------------------------------------------------------
# Write-ManagerOrchestrationEvent
# Manager-owned event append helper. Missing event context is tolerated so local
# unit tests and legacy direct invocations do not break.
# ---------------------------------------------------------------------------
function Write-ManagerOrchestrationEvent {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$RoomDir,
        [Parameter(Mandatory)][string]$EventType,
        [Parameter(Mandatory)][string]$Summary,
        [hashtable]$Payload = @{},
        [string]$Role = '',
        [string]$State = '',
        [string]$Severity = 'info',
        [object]$LastMessage = $null,
        [string]$EpicRef = ''
    )

    if (-not (Get-Command Write-OrchestrationEvent -ErrorAction SilentlyContinue)) { return $null }
    $ctx = Get-RoomOrchestrationContext -RoomDir $RoomDir
    if ([string]::IsNullOrWhiteSpace($ctx.PlanId)) { return $null }
    $roomScopedEventTypes = @('room.created', 'room.status.changed', 'epic.started', 'epic.passed', 'epic.failed', 'epic.retrying', 'epic.blocked', 'epic.unblocked', 'dependency.created', 'dependency.satisfied', 'dependency.blocked', 'dependency.unblocked', 'role.assigned', 'role.reassigned', 'role.resolved', 'role.spawn.requested', 'agent.run.started', 'agent.run.completed', 'agent.run.failed', 'agent.run.timed_out', 'agent.run.respawned', 'lifecycle.signal.posted', 'lifecycle.transition.applied', 'lifecycle.retry.exhausted', 'lifecycle.escalated', 'channel.message.posted', 'conversation.bound', 'conversation.unbound', 'conversation.subscription.updated')
    $isRoomScopedEvent = $roomScopedEventTypes -contains $EventType
    if ($isRoomScopedEvent -and ([string]::IsNullOrWhiteSpace($ctx.RoomId) -or [string]::IsNullOrWhiteSpace($ctx.EpicRef))) {
        Write-Log 'DEBUG' "[Write-ManagerOrchestrationEvent] Skipping '$EventType' because room context is incomplete for '$RoomDir'."
        return $null
    }

    $event = [ordered]@{
        event_type = $EventType
        plan_id    = $ctx.PlanId
        run_id     = $ctx.RunId
        severity   = $Severity
        summary    = $Summary
        payload    = [ordered]@{}
    }
    foreach ($key in $Payload.Keys) { $event.payload[$key] = $Payload[$key] }

    $effectiveRole = if ($Role) { $Role } else { 'manager' }
    $effectiveState = if ($State) { $State } else { $ctx.State }
    $event['role'] = $effectiveRole
    $event['state'] = $effectiveState
    if (-not $event.payload.Contains('role')) { $event.payload['role'] = $effectiveRole }
    if (-not $event.payload.Contains('agent_name')) { $event.payload['agent_name'] = $effectiveRole }

    if ($isRoomScopedEvent) {
        $event['room_id'] = $ctx.RoomId
        $event['epic_ref'] = if ($EpicRef) { $EpicRef } else { $ctx.EpicRef }
    }
    if ($LastMessage) { $event['last_message'] = $LastMessage }

    return (Write-OrchestrationEvent -EventsPath $ctx.EventsPath -Event $event)
}

# ---------------------------------------------------------------------------
# Invoke-PlanFailFast
# Implements fail-fast: one unrecoverable epic failure emits epic.failed and
# plan.run.failed, then stops active room processes before the manager exits.
# ---------------------------------------------------------------------------
function Invoke-PlanFailFast {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$RoomDir,
        [Parameter(Mandatory)][string]$Reason,
        [string]$Role = '',
        [string]$State = '',
        [string]$Summary = '',
        [object]$LastMessage = $null
    )

    $WarRoomsDir = _ctx 'WarRoomsDir'
    $ctx = Get-RoomOrchestrationContext -RoomDir $RoomDir
    $failedSummary = if ($Summary) { $Summary } else { "$($ctx.EpicRef) failed: $Reason" }
    if (-not $LastMessage) { $LastMessage = Get-LatestFailureMessage -RoomDir $RoomDir -Role $Role }

    $epicPayload = @{
        reason       = $Reason
        plan_id      = $ctx.PlanId
        run_id       = $ctx.RunId
        room_id      = $ctx.RoomId
        epic_ref     = $ctx.EpicRef
        role         = $Role
        state        = if ($State) { $State } else { $ctx.State }
        last_message = $LastMessage
    }
    Write-ManagerOrchestrationEvent -RoomDir $RoomDir -EventType 'epic.failed' -Summary $failedSummary -Payload $epicPayload -Role $Role -State $State -Severity 'fatal' -LastMessage $LastMessage | Out-Null

    $planPayload = @{
        reason       = $Reason
        failed_epic  = [ordered]@{
            plan_id      = $ctx.PlanId
            run_id       = $ctx.RunId
            room_id      = $ctx.RoomId
            epic_ref     = $ctx.EpicRef
            role         = $Role
            state        = if ($State) { $State } else { $ctx.State }
            summary      = $failedSummary
            last_message = $LastMessage
        }
    }
    Write-ManagerOrchestrationEvent -RoomDir $RoomDir -EventType 'plan.run.failed' -Summary "Plan $($ctx.PlanId) failed because $($ctx.EpicRef) failed." -Payload $planPayload -Severity 'fatal' | Out-Null

    # Stop all active room processes only after events have been appended.
    if ($WarRoomsDir -and (Test-Path $WarRoomsDir)) {
        Get-ChildItem -Path $WarRoomsDir -Directory -Filter 'room-*' -ErrorAction SilentlyContinue | ForEach-Object {
            $status = if (Test-Path (Join-Path $_.FullName 'status')) { (Get-Content (Join-Path $_.FullName 'status') -Raw).Trim() } else { '' }
            $canonicalStatus = ConvertTo-CanonicalRoomStatus -Status $status
            if ($canonicalStatus -notin @('done', 'failed', 'blocked', '')) {
                Stop-RoomProcesses $_.FullName
            }
        }
    }

    Write-RoomStatus $RoomDir 'failed'
    return $true
}

# ---------------------------------------------------------------------------
# Test-StateTimedOut
# ---------------------------------------------------------------------------
function Test-StateTimedOut {
    [CmdletBinding()]
    param([string]$RoomDir)
    $stateTimeout = _ctx 'stateTimeout'
    $changedFile = Join-Path $RoomDir "state_changed_at"
    if (-not (Test-Path $changedFile)) { return $false }
    $changedAt = [int](Get-Content $changedFile -Raw).Trim()
    $now = Get-UnixEpoch
    return (($now - $changedAt) -gt $stateTimeout)
}

# ---------------------------------------------------------------------------
# Stop-RoomProcesses
# Kills agent processes and their entire process trees (MCP servers, etc.).
# On Unix: uses process-group kill (kill -- -PID) for reliable tree cleanup.
# On Windows: uses taskkill /T /F for tree kill.
# Falls back to Stop-Process if group/tree kill is unavailable.
# ---------------------------------------------------------------------------
function Stop-RoomProcesses {
    [CmdletBinding()]
    param([string]$RoomDir)
    $pidDir = Join-Path $RoomDir "pids"
    if (-not (Test-Path $pidDir)) { return }
    Get-ChildItem $pidDir -Filter "*.pid" -ErrorAction SilentlyContinue | ForEach-Object {
        $pidVal = (Get-Content $_.FullName -Raw).Trim()
        if ($pidVal -match '^\d+$') {
            $p = [int]$pidVal
            # Verify the process is alive before attempting kill
            $alive = $false
            try { $null = Get-Process -Id $p -ErrorAction Stop; $alive = $true } catch {}
            if ($alive) {
                if ($IsWindows) {
                    # Windows: tree kill via taskkill
                    try { & taskkill /T /F /PID $p 2>&1 | Out-Null } catch {}
                } elseif ($IsLinux -or $IsMacOS) {
                    # Unix: attempt process-group kill first (covers child MCP servers).
                    # This works when PID is a group leader (the exec pattern in Invoke-Agent).
                    try { & /bin/kill -- -$p 2>&1 | Out-Null } catch {}
                    Start-Sleep -Milliseconds 500
                    # Check if process is still alive — if group kill didn't work
                    # (PID wasn't a group leader), fall back to single-process kill.
                    $stillAlive = $false
                    try { $null = Get-Process -Id $p -ErrorAction Stop; $stillAlive = $true } catch {}
                    if ($stillAlive) {
                        # Fallback: direct SIGKILL to the process itself
                        try { Stop-Process -Id $p -Force -ErrorAction SilentlyContinue } catch {}
                    }
                } else {
                    # Fallback: single-process kill
                    try { Stop-Process -Id $p -Force -ErrorAction SilentlyContinue } catch {}
                }
            }
        }
        Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue
    }
    Get-ChildItem $pidDir -Filter "*.spawned_at" -ErrorAction SilentlyContinue | ForEach-Object {
        Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue
    }
}

# ---------------------------------------------------------------------------
# Write-RoomStatus
# ---------------------------------------------------------------------------
function Write-RoomStatus {
    [CmdletBinding()]
    param([string]$RoomDir, [string]$NewStatus)
    $NewStatus = ConvertTo-CanonicalRoomStatus -Status $NewStatus
    $oldStatus = if (Test-Path (Join-Path $RoomDir "status")) {
        (Get-Content (Join-Path $RoomDir "status") -Raw).Trim()
    } else { "unknown" }

    if (Get-Command Set-WarRoomStatus -ErrorAction SilentlyContinue) {
        Set-WarRoomStatus -RoomDir $RoomDir -NewStatus $NewStatus
    } else {
        $NewStatus | Out-File -FilePath (Join-Path $RoomDir "status") -Encoding utf8 -NoNewline
        $epoch = Get-UnixEpoch
        $epoch.ToString() | Out-File -FilePath (Join-Path $RoomDir "state_changed_at") -Encoding utf8 -NoNewline
        $ts = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
        "$ts STATUS $oldStatus -> $NewStatus" | Out-File -Append -FilePath (Join-Path $RoomDir "audit.log") -Encoding utf8
    }

    if ($oldStatus -ne $NewStatus) {
        $statusLastMessage = Get-LatestChannelMessage -RoomDir $RoomDir -Role 'manager'
        Write-ManagerOrchestrationEvent -RoomDir $RoomDir -EventType 'room.status.changed' -Summary "War-room status changed from '$oldStatus' to '$NewStatus'." -Payload @{
            previous_status = $oldStatus
            status          = $NewStatus
            role            = 'manager'
            agent_name      = 'manager'
        } -Role 'manager' -State $NewStatus -LastMessage $statusLastMessage | Out-Null
    }

    $pidDir = Join-Path $RoomDir "pids"
    if (Test-Path $pidDir) {
        $terminalStates = @('done', 'failed', 'blocked', 'passed', 'failed-final')
        if ($NewStatus -in $terminalStates) {
            Get-ChildItem $pidDir -Filter "*.pid"        -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
            Get-ChildItem $pidDir -Filter "*.spawned_at" -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
        } else {
            $oldRole = $null
            $lcFile = Join-Path $RoomDir "lifecycle.json"
            if (Test-Path $lcFile) {
                try {
                    $lc = Get-Content $lcFile -Raw | ConvertFrom-Json
                    if ($lc.states -and $lc.states.$oldStatus -and $lc.states.$oldStatus.role) {
                        $oldRole = ($lc.states.$oldStatus.role -replace ':.*$', '')
                    }
                } catch {
                    Write-Log "DEBUG" "[Write-RoomStatus] Error reading lifecycle for PID cleanup: $($_.Exception.Message)"
                }
            }
            if ($oldRole) {
                Remove-Item (Join-Path $pidDir "$oldRole.pid")        -Force -ErrorAction SilentlyContinue
                Remove-Item (Join-Path $pidDir "$oldRole.spawned_at") -Force -ErrorAction SilentlyContinue
            }
        }
    }
}

# ---------------------------------------------------------------------------
# Find-LatestSignal
# ---------------------------------------------------------------------------
function Convert-ManagerSignalTimestampToEpoch {
    [CmdletBinding()]
    param($Timestamp)

    if (-not $Timestamp) { return 0 }
    if ($Timestamp -is [datetime]) {
        return [long]([DateTimeOffset]::new($Timestamp.ToUniversalTime()).ToUnixTimeSeconds())
    }
    if ("$Timestamp" -match '^\d+$') { return [long]"$Timestamp" }

    try {
        return [long]([DateTimeOffset]::new([datetime]::Parse("$Timestamp").ToUniversalTime()).ToUnixTimeSeconds())
    } catch {
        Write-Log "DEBUG" "[Find-LatestSignal] Failed to parse timestamp '$Timestamp': $($_.Exception.Message)"
        return 0
    }
}

function Test-ManagerSignalSenderMatches {
    [CmdletBinding()]
    param(
        [AllowEmptyString()][string]$ExpectedRole,
        [AllowEmptyString()][string]$ActualRole
    )

    if (-not $ExpectedRole) { return $true }
    if (-not $ActualRole) { return $false }

    $expectedBase = ($ExpectedRole -replace ':.*$', '')
    $actualBase = ($ActualRole -replace ':.*$', '')

    if ($actualBase -eq $expectedBase) { return $true }

    # MCP channel_post_message only supports canonical sender roles
    # (manager|engineer|qa|architect). Dynamic QA evaluator roles such as
    # qa-automation-engineer may therefore emit their direct channel signal as
    # from='qa', while the wrapper emits from='qa-automation-engineer'. Treat
    # canonical qa as an alias only for QA-family dynamic evaluator roles.
    if ($actualBase -eq 'qa' -and ($expectedBase -eq 'qa' -or $expectedBase -like 'qa-*')) {
        return $true
    }

    return $false
}

function Find-LatestSignal {
    [CmdletBinding()]
    param(
        [string]$RoomDir,
        [Parameter(Mandatory)]$Lifecycle,
        [Parameter(Mandatory)][string]$StateName
    )
    $readMessages = _ctx 'readMessages'
    $roomId = Split-Path $RoomDir -Leaf

    $stateDef = $Lifecycle.states.$StateName
    if (-not $stateDef -or -not $stateDef.signals) {
        Write-Log "DEBUG" "[Find-LatestSignal][$roomId] state='$StateName' has no signals defined in lifecycle"
        return $null
    }
    $expectedSignals = @($stateDef.signals.PSObject.Properties.Name | Where-Object { $_ -ne 'error' })
    $expectedRole    = if ($stateDef.role) { ($stateDef.role -replace ':.*$', '') } else { '' }

    $changedAt = 0
    $changedFile = Join-Path $RoomDir "state_changed_at"
    if (Test-Path $changedFile) {
        $changedAt = [int](Get-Content $changedFile -Raw).Trim()
    }
    Write-Log "DEBUG" "[Find-LatestSignal][$roomId] state='$StateName' role='$expectedRole' state_changed_at=$changedAt signals=($($expectedSignals -join ', '))"

    $candidateSignals = [System.Collections.Generic.List[object]]::new()

    foreach ($sigType in $expectedSignals) {
        try {
            # Read all messages of this signal type and filter before choosing
            # the latest. Using -Last 1 before role/timestamp filtering lets a
            # newer wrong-role message mask an earlier valid lifecycle signal.
            $msgs = & $readMessages -RoomDir $RoomDir -FilterType $sigType -AsObject
            if ($msgs -and $msgs.Count -gt 0) {
                foreach ($latest in $msgs) {
                    $msgTs = Convert-ManagerSignalTimestampToEpoch -Timestamp $latest.ts
                    $body = if ($latest.body) { [string]$latest.body } else { '' }
                    $bodyPreview = if ($body.Length -gt 120) { $body.Substring(0, 120) + '...' } else { $body }

                    if ($expectedRole -and -not (Test-ManagerSignalSenderMatches -ExpectedRole $expectedRole -ActualRole $latest.from)) {
                        Write-Log "DEBUG" "[Find-LatestSignal][$roomId] signal='$sigType' REJECTED: from='$($latest.from)' != lifecycle role='$expectedRole'"
                        continue
                    }

                    # Accept signals posted at or after the state change.
                    # Using -ge (not -gt) because the worker's MCP tool may update
                    # state_changed_at and post a channel signal in the same epoch
                    # second — -gt would reject that signal as "stale".
                    $accepted = ($msgTs -ge $changedAt)
                    Write-Log "DEBUG" "[Find-LatestSignal][$roomId] signal='$sigType' from='$($latest.from)' msgTs=$msgTs changedAt=$changedAt accepted=$accepted body=[$bodyPreview]"
                    if ($accepted) {
                        $candidateSignals.Add([pscustomobject]@{
                            Type = $sigType
                            Timestamp = $msgTs
                            Id = if ($latest.id) { [string]$latest.id } else { '' }
                            Message = $latest
                        }) | Out-Null
                    }
                }
            } else {
                Write-Log "DEBUG" "[Find-LatestSignal][$roomId] signal='$sigType' — no messages found"
            }
        } catch {
            Write-Log "DEBUG" "[Find-LatestSignal][$roomId] signal='$sigType' — error: $($_.Exception.Message)"
        }
    }

    if ($candidateSignals.Count -gt 0) {
        $selected = $candidateSignals |
            Sort-Object @{ Expression = 'Timestamp'; Descending = $true }, @{ Expression = 'Id'; Descending = $true } |
            Select-Object -First 1

        # --- Output-grep cross-check (defense-in-depth) ---
        # The agent itself may have posted a different signal via the
        # channel_post_message MCP tool than what the worker script parsed and
        # re-posted. Prefer the current invocation's direct channel intent only
        # when it can be found in the latest wrapper segment.
        $outputSignal = Get-OutputSignal -RoomDir $RoomDir -Role $expectedRole
        if ($outputSignal -and $outputSignal -ne 'error' -and $outputSignal -ne $selected.Type -and $outputSignal -in $expectedSignals) {
            Write-Log "WARN" "[Find-LatestSignal][$roomId] OUTPUT OVERRIDE: channel='$($selected.Type)' but agent output shows msg_type='$outputSignal'. Using '$outputSignal'."
            return $outputSignal
        }
        return $selected.Type
    }

    Write-Log "DEBUG" "[Find-LatestSignal][$roomId] no matching signal found"
    return $null
}

# ---------------------------------------------------------------------------
# Get-OutputSignal
# Reads the role's raw output file and extracts the msg_type from the LAST
# channel_post_message MCP tool call. This is the agent's direct intent,
# uncontaminated by the worker script's verdict parsing.
#
# Format in output file:
#   ⚙ channel_post_message {"msg_type":"pass",...}
# ---------------------------------------------------------------------------
function Get-OutputSignal {
    [CmdletBinding()]
    param(
        [string]$RoomDir,
        [string]$Role
    )
    $outputFile = Join-Path $RoomDir "artifacts" "$Role-output.txt"
    if (-not (Test-Path $outputFile)) { return $null }

    $lastMsgType = $null
    try {
        # Read the file and scan only the latest wrapper invocation segment.
        # Agent output files are append-only across --continue retries; scanning
        # the whole file lets stale MCP calls from a previous invocation override
        # the current run's channel signal.
        $lines = Get-Content $outputFile -ErrorAction Stop
        $startIndex = 0
        for ($j = $lines.Count - 1; $j -ge 0; $j--) {
            if ($lines[$j] -match '^\[wrapper\]\s+PID=') {
                $startIndex = $j
                break
            }
        }
        for ($i = $lines.Count - 1; $i -ge $startIndex; $i--) {
            if ($lines[$i] -match 'channel_post_message\s+(\{.+\})') {
                $jsonStr = $Matches[1]
                try {
                    $parsed = $jsonStr | ConvertFrom-Json
                    if ($parsed.msg_type) {
                        $lastMsgType = $parsed.msg_type.ToLower()
                        break
                    }
                } catch {
                    # JSON parse failed — try regex fallback
                    if ($jsonStr -match '"msg_type"\s*:\s*"(pass|fail|done|escalate)"') {
                        $lastMsgType = $Matches[1].ToLower()
                        break
                    }
                }
            }
        }
    } catch {
        Write-Log "DEBUG" "[Get-OutputSignal] Error reading ${outputFile}: $($_.Exception.Message)"
    }
    return $lastMsgType
}

# ---------------------------------------------------------------------------
# Invoke-SignalActions
# ---------------------------------------------------------------------------
function Invoke-SignalActions {
    [CmdletBinding()]
    param([string]$RoomDir, [string[]]$Actions, [string]$TaskRef, [string]$BaseRole)
    $readMessages = _ctx 'readMessages'

    foreach ($action in $Actions) {
        switch ($action) {
            'increment_retries' {
                $retriesFile = Join-Path $RoomDir "retries"
                $r = if (Test-Path $retriesFile) { [int](Get-Content $retriesFile -Raw).Trim() } else { 0 }
                ($r + 1).ToString() | Out-File -FilePath $retriesFile -Encoding utf8 -NoNewline
            }
            'post_fix' {
                # No PowerShell channel synthesis. The worker prompt now receives
                # current channel.jsonl context directly from Invoke-Agent; fixes
                # must be posted by agents through the MCP channel tool.
                Write-Log "DEBUG" "[$TaskRef] post_fix action skipped; channel writes are MCP-only."
            }
            'revise_brief' {
                $briefFile   = Join-Path $RoomDir "brief.md"
                $triageFile  = Join-Path $RoomDir "artifacts" "triage-context.md"
                if ((Test-Path $briefFile) -and (Test-Path $triageFile)) {
                    $originalBrief = Get-Content $briefFile -Raw
                    $triageContent = Get-Content $triageFile -Raw
                    $updatedBrief  = $originalBrief + "`n`n---`n`n## Plan Revision Notes`n`n$triageContent"
                    $updatedBrief | Out-File -FilePath $briefFile -Encoding utf8 -Force
                }
                $qaRetriesFile = Join-Path $RoomDir "qa_retries"
                if (Test-Path $qaRetriesFile) { Remove-Item $qaRetriesFile -Force }
            }
        }
    }
}

# ---------------------------------------------------------------------------
# Write-Log
# ---------------------------------------------------------------------------
function Write-Log {
    [CmdletBinding()]
    param([string]$Level, [string]$Message)
    if (Get-Command Write-OstwinLog -ErrorAction SilentlyContinue) {
        Write-OstwinLog -Level $Level -Message $Message
    } else {
        Write-Host "[MANAGER] $Message"
    }
}

# ---------------------------------------------------------------------------
# Write-SpawnLock
# ---------------------------------------------------------------------------
function Write-SpawnLock {
    [CmdletBinding()]
    param([string]$RoomDir, [string]$Role)
    $pidDir = Join-Path $RoomDir "pids"
    if (-not (Test-Path $pidDir)) { New-Item -ItemType Directory -Path $pidDir -Force | Out-Null }
    $lockFile = Join-Path $pidDir "$Role.spawned_at"
    $epoch = Get-UnixEpoch
    $epoch.ToString() | Out-File -FilePath $lockFile -Encoding utf8 -NoNewline
}

# ---------------------------------------------------------------------------
# Test-SpawnLock
# ---------------------------------------------------------------------------
function Test-SpawnLock {
    [CmdletBinding()]
    param([string]$RoomDir, [string]$Role, [int]$GracePeriodSeconds = 30)
    $lockFile = Join-Path $RoomDir "pids" "$Role.spawned_at"
    if (-not (Test-Path $lockFile)) { return $false }
    try {
        $spawnedAt = [int](Get-Content $lockFile -Raw).Trim()
        $now = Get-UnixEpoch
        return (($now - $spawnedAt) -lt $GracePeriodSeconds)
    } catch {
        Write-Log "DEBUG" "[Test-SpawnLock] Error reading spawn lock for '$Role': $($_.Exception.Message)"
        return $false
    }
}

# ---------------------------------------------------------------------------
# Set-RoleRunStatus / Get-FreshFailedRoleRun
# Role wrappers update their per-role config when a process exits. The manager
# consumes that status as orchestration state, not as a lifecycle signal.
# ---------------------------------------------------------------------------
function Set-RoleRunStatus {
    [CmdletBinding()]
    param(
        [string]$RoomDir,
        [string]$Role,
        [ValidateSet("pending", "active", "completed", "failed")][string]$Status
    )

    $baseRole = $Role -replace ':.*$', ''
    $roleConfigs = Get-ChildItem -Path $RoomDir -Filter "${baseRole}_*.json" -ErrorAction SilentlyContinue |
        Sort-Object Name -Descending
    if (-not $roleConfigs) { return $null }

    $targetFile = $roleConfigs[0].FullName
    $cfg = Get-Content $targetFile -Raw | ConvertFrom-Json
    $epoch = Get-UnixEpoch
    $state = if (Test-Path (Join-Path $RoomDir "status")) {
        (Get-Content (Join-Path $RoomDir "status") -Raw).Trim()
    } else { "" }

    $cfg.status = $Status
    $cfg | Add-Member -NotePropertyName "status_updated_epoch" -NotePropertyValue $epoch -Force
    $cfg | Add-Member -NotePropertyName "status_updated_at" -NotePropertyValue ((Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')) -Force
    $cfg | Add-Member -NotePropertyName "status_state" -NotePropertyValue $state -Force
    $cfg | ConvertTo-Json -Depth 5 | Out-File -FilePath $targetFile -Encoding utf8
    return $targetFile
}

function Get-FreshFailedRoleRun {
    [CmdletBinding()]
    param(
        [string]$RoomDir,
        [string]$Role
    )

    $baseRole = $Role -replace ':.*$', ''
    $roleConfigs = Get-ChildItem -Path $RoomDir -Filter "${baseRole}_*.json" -ErrorAction SilentlyContinue |
        Sort-Object Name -Descending
    if (-not $roleConfigs) { return $null }

    $cfgFile = $roleConfigs[0].FullName
    try {
        $cfg = Get-Content $cfgFile -Raw | ConvertFrom-Json
    } catch {
        Write-Log "DEBUG" "[Get-FreshFailedRoleRun] Error reading ${cfgFile}: $($_.Exception.Message)"
        return $null
    }

    if ($cfg.status -ne 'failed') { return $null }

    $changedAt = 0
    $changedFile = Join-Path $RoomDir "state_changed_at"
    if (Test-Path $changedFile) {
        try { $changedAt = [long](Get-Content $changedFile -Raw).Trim() } catch { $changedAt = 0 }
    }

    $statusEpoch = 0
    if ($cfg.PSObject.Properties['status_updated_epoch'] -and "$($cfg.status_updated_epoch)" -match '^\d+$') {
        $statusEpoch = [long]"$($cfg.status_updated_epoch)"
    } elseif ($cfg.PSObject.Properties['status_updated_at'] -and $cfg.status_updated_at) {
        try {
            $statusEpoch = [long]([DateTimeOffset]::new([datetime]::Parse("$($cfg.status_updated_at)").ToUniversalTime()).ToUnixTimeSeconds())
        } catch { $statusEpoch = 0 }
    }

    if ($statusEpoch -le 0) { return $null }
    if ($statusEpoch -lt $changedAt) { return $null }

    return [pscustomobject]@{
        Role               = $baseRole
        ConfigFile         = $cfgFile
        StatusUpdatedEpoch = $statusEpoch
    }
}

# ---------------------------------------------------------------------------
# Resolve-RoleTimeout
# Resolves timeout_seconds for a role from plan roles config (highest priority)
# then config.json (fallback). Returns 0 if neither has a value, which tells
# the worker script to use its own default.
#
# Priority chain:
#   1. Plan roles config (~/.ostwin/.agents/plans/{plan_id}.roles.json)
#   2. Global config.json (.agents/config.json)
#   3. 0 (worker script decides)
# ---------------------------------------------------------------------------
function Resolve-RoleTimeout {
    [CmdletBinding()]
    param(
        [string]$RoleName,
        [string]$RoomDir
    )
    $config = _ctx 'config'
    $agentsDir = _ctx 'agentsDir'

    # Resolve OSTWIN_HOME for plan roles path
    $_homeDir = if ($env:HOME) { $env:HOME } else { $env:USERPROFILE }
    $OstwinHome = if ($env:OSTWIN_HOME) { $env:OSTWIN_HOME } else { Join-Path $_homeDir ".ostwin" }

    $baseRole = $RoleName -replace ':.*$', ''

    # --- Priority 1: Plan roles config ---
    $roomConfigFile = Join-Path $RoomDir "config.json"
    if (Test-Path $roomConfigFile) {
        try {
            $roomCfg = Get-Content $roomConfigFile -Raw | ConvertFrom-Json
            $planId = $roomCfg.plan_id
            if ($planId) {
                $planRolesFile = Join-Path $OstwinHome ".agents" "plans" "$planId.roles.json"
                if (Test-Path $planRolesFile) {
                    $planRoles = Get-Content $planRolesFile -Raw | ConvertFrom-Json
                    if ($planRoles.$baseRole -and $planRoles.$baseRole.timeout_seconds) {
                        $resolved = [int]$planRoles.$baseRole.timeout_seconds
                        Write-Log "DEBUG" "[Resolve-RoleTimeout] role='$baseRole' resolved=$resolved from plan roles ($planId)"
                        return $resolved
                    }
                }
            }
        } catch {
            Write-Log "DEBUG" "[Resolve-RoleTimeout] Error reading plan roles config for '$RoleName': $($_.Exception.Message)"
        }
    }

    # --- Priority 2: Global config.json ---
    if ($config -and $config.$baseRole -and $config.$baseRole.timeout_seconds) {
        $resolved = [int]$config.$baseRole.timeout_seconds
        Write-Log "DEBUG" "[Resolve-RoleTimeout] role='$baseRole' resolved=$resolved from config.json"
        return $resolved
    }

    # --- Fallback: let worker script decide ---
    Write-Log "DEBUG" "[Resolve-RoleTimeout] role='$baseRole' no timeout configured — returning 0 (worker default)"
    return 0
}

# ---------------------------------------------------------------------------
# Start-WorkerJob
# ---------------------------------------------------------------------------
function Start-WorkerJob {
    [CmdletBinding()]
    param(
        [string]$RoomDir,
        [string]$Role,
        [string]$Script,
        [string]$TaskRef = '',
        [string]$RoleName = '',
        [int]$TimeoutSeconds = 0,
        [switch]$SkipLockCheck
    )
    if (-not $SkipLockCheck) {
        if (Test-SpawnLock -RoomDir $RoomDir -Role $Role) {
            Write-Log "DEBUG" "[$TaskRef] Spawn lock active for '$Role' — skipping duplicate spawn."
            return $false
        }
        $existingPid = Join-Path $RoomDir "pids" "$Role.pid"
        if (Test-PidAlive $existingPid) {
            Write-Log "DEBUG" "[$TaskRef] Process already alive for '$Role' — skipping duplicate spawn."
            return $false
        }
    }
    Write-SpawnLock -RoomDir $RoomDir -Role $Role
    $effectiveRoleName = if ($RoleName) { $RoleName } else { $Role }
    # Detect whether the target script accepts -RoleName / -TimeoutSeconds
    # before passing them. Scripts with [CmdletBinding()] will throw a
    # terminating error on unknown parameters, silently killing the
    # Start-Job runspace with zero output.
    $acceptsRoleName = $false
    $acceptsTimeout = $false
    try {
        $scriptCmd = Get-Command $Script -ErrorAction SilentlyContinue
        if ($scriptCmd) {
            if ($scriptCmd.Parameters.ContainsKey('RoleName')) { $acceptsRoleName = $true }
            if ($scriptCmd.Parameters.ContainsKey('TimeoutSeconds')) { $acceptsTimeout = $true }
        }
    } catch {
        Write-Log "DEBUG" "[$TaskRef] Error inspecting script parameters for '$Script': $($_.Exception.Message)"
    }
    if ($TimeoutSeconds -gt 0) {
        Write-Log "DEBUG" "[$TaskRef] Spawning '$Role' with TimeoutSeconds=$TimeoutSeconds (passTimeout=$acceptsTimeout)"
    }
    Set-RoleRunStatus -RoomDir $RoomDir -Role $Role -Status "active" | Out-Null
    $roomId = Split-Path $RoomDir -Leaf
    Start-Job -Name "ostwin-worker-$roomId-$Role" -ScriptBlock {
        param($s, $r, $rn, $passRn, $ts, $passTs)
        $splatArgs = @{ RoomDir = $r }
        if ($passRn -and $rn) { $splatArgs['RoleName'] = $rn }
        if ($passTs -and $ts -gt 0) { $splatArgs['TimeoutSeconds'] = $ts }
        & $s @splatArgs
    } -ArgumentList $Script, $RoomDir, $effectiveRoleName, $acceptsRoleName, $TimeoutSeconds, $acceptsTimeout | Out-Null
    return $true
}

# ---------------------------------------------------------------------------
# Get-CachedDag
# ---------------------------------------------------------------------------
function Get-CachedDag {
    [CmdletBinding()]
    param()
    $dagFile        = _ctx 'dagFile'
    $script:dagCache = (_ctx 'dagCache')
    $script:dagMtime = (_ctx 'dagMtime')

    if (-not (Test-Path $dagFile)) { return $null }
    $mtime = (Get-Item $dagFile).LastWriteTimeUtc.Ticks
    if ($script:dagCache -and $script:dagMtime -eq $mtime) {
        return $script:dagCache
    }
    $newCache = Get-Content $dagFile -Raw | ConvertFrom-Json
    # Write back via context — callers update the ctx after call
    return $newCache
}

# ---------------------------------------------------------------------------
# Set-BlockedDescendants
# ---------------------------------------------------------------------------
function Set-BlockedDescendants {
    [CmdletBinding()]
    param([string]$FailedTaskRef)
    $hasDag      = _ctx 'hasDag'
    $WarRoomsDir = _ctx 'WarRoomsDir'

    if (-not $hasDag) { return }
    $dag = Get-CachedDag
    if (-not $dag) { return }

    $bfsQueue = [System.Collections.Queue]::new()
    $bfsQueue.Enqueue($FailedTaskRef)
    $visited = @{}

    while ($bfsQueue.Count -gt 0) {
        $current = $bfsQueue.Dequeue()
        if ($visited.ContainsKey($current)) { continue }
        $visited[$current] = $true

        $node = $dag.nodes.$current
        if (-not $node) { continue }
        $dependents = $node.dependents
        if (-not $dependents) { continue }
        foreach ($dep in $dependents) {
            $depNode = $dag.nodes.$dep
            if (-not $depNode) { continue }
            $depRoomDir = Join-Path $WarRoomsDir $depNode.room_id
            if (-not (Test-Path (Join-Path $depRoomDir "status"))) { continue }
            $depStatus = (Get-Content (Join-Path $depRoomDir "status") -Raw).Trim()
            if ($depStatus -eq "pending") {
                Write-Log "WARN" "[$dep] Blocked: upstream $FailedTaskRef failed"
                Write-RoomStatus $depRoomDir "blocked"
            }
            $bfsQueue.Enqueue($dep)
        }
    }
}

# ---------------------------------------------------------------------------
# Invoke-ManagerTriage
# ---------------------------------------------------------------------------
function Invoke-ManagerTriage {
    [CmdletBinding()]
    param([string]$RoomDir, [string]$QaFeedback)
    $agentsDir    = _ctx 'agentsDir'
    $config       = _ctx 'config'
    $readMessages = _ctx 'readMessages'

    if (-not $QaFeedback -or $QaFeedback.Trim() -eq '') { return 'no-feedback' }

    $designKeywords = 'architecture|design|scope|interface|contract|api-design|redesign|structural'
    $planKeywords   = 'specification|acceptance criteria|definition of done|brief|missing requirement|requirements|out of scope'
    if ($QaFeedback -match $designKeywords) { return 'design-issue' }
    if ($QaFeedback -match $planKeywords)   { return 'plan-gap' }

    $capabilityMatching = $true
    if ($null -ne $config.manager.capability_matching) { $capabilityMatching = $config.manager.capability_matching }

    $roomConfigFile = Join-Path $RoomDir "config.json"
    if (Test-Path $roomConfigFile) {
        $rc           = Get-Content $roomConfigFile -Raw | ConvertFrom-Json
        $assignedRole = if ($rc.assignment -and $rc.assignment.assigned_role) { $rc.assignment.assigned_role } else { "engineer" }
        $baseRole     = $assignedRole -replace ':.*$', ''
        $overrideDir  = Join-Path $RoomDir (Join-Path "overrides" $baseRole)
        $roleDir      = if (Test-Path $overrideDir) { $overrideDir } else { Join-Path $agentsDir (Join-Path "roles" $baseRole) }
        $subcommandsFile = Join-Path $roleDir "subcommands.json"

        if (Test-Path $subcommandsFile) {
            $subcommands = Get-Content $subcommandsFile -Raw | ConvertFrom-Json
            $analyzeSubcommandScript = Join-Path $agentsDir "roles" "_base" "Analyze-SubcommandFailure.ps1"
            if (Test-Path $analyzeSubcommandScript) {
                try {
                    $analysis = & $analyzeSubcommandScript -QaFeedback $QaFeedback -Subcommands $subcommands
                    if ($analysis.Confidence -ge 0.7 -and $analysis.SubcommandName) {
                        return "subcommand-failure:$($analysis.SubcommandName)"
                    }
                } catch {
                    Write-Log "DEBUG" "[Invoke-ManagerTriage] Subcommand analysis error: $($_.Exception.Message)"
                }
            } else {
                foreach ($sc in $subcommands.subcommands.PSObject.Properties) {
                    $scName  = $sc.Name
                    $scEntry = $sc.Value.entrypoint
                    if ($QaFeedback -match $scName -or ($scEntry -and $QaFeedback -match (Split-Path $scEntry -Leaf))) {
                        return "subcommand-failure:$scName"
                    }
                }
            }
        }
    }

    if ($capabilityMatching) {
        $analyzeScript = Join-Path $agentsDir "roles" "_base" "Analyze-TaskRequirements.ps1"
        if (Test-Path $analyzeScript) {
            try {
                $analysis = & $analyzeScript -TaskDescription $QaFeedback -AgentsDir $agentsDir
                if ($analysis.Confidence -ge 0.6 -and $analysis.RequiredCapabilities.Count -gt 0) {
                    $specialistCaps = @('security', 'database', 'infrastructure', 'architecture')
                    $matched = $analysis.RequiredCapabilities | Where-Object { $_ -in $specialistCaps }
                    if ($matched -and $matched.Count -gt 0) { return 'design-issue' }
                }
            } catch {
                Write-Log "DEBUG" "[Invoke-ManagerTriage] Capability analysis error: $($_.Exception.Message)"
            }
        }
    }

    $retries = if (Test-Path (Join-Path $RoomDir "retries")) {
        [int](Get-Content (Join-Path $RoomDir "retries") -Raw).Trim()
    } else { 0 }
    if ($retries -ge 2) {
        try {
            $failMsgs = & $readMessages -RoomDir $RoomDir -FilterType "fail" -AsObject
            if ($failMsgs -and $failMsgs.Count -ge 2) {
                $prev      = $failMsgs[-2].body
                $curr      = $failMsgs[-1].body
                $prevWords = ($prev -split '\W+') | Where-Object { $_.Length -gt 3 } | Sort-Object -Unique
                $currWords = ($curr -split '\W+') | Where-Object { $_.Length -gt 3 } | Sort-Object -Unique
                if ($prevWords.Count -gt 0 -and $currWords.Count -gt 0) {
                    $overlap    = ($prevWords | Where-Object { $currWords -contains $_ }).Count
                    $maxSet     = [Math]::Max($prevWords.Count, $currWords.Count)
                    $similarity = $overlap / $maxSet
                    if ($similarity -ge 0.6) { return 'design-issue' }
                }
            }
        } catch {
            Write-Log "DEBUG" "[Invoke-ManagerTriage] Similarity analysis error: $($_.Exception.Message)"
        }
    }
    return 'implementation-bug'
}

# ---------------------------------------------------------------------------
# Write-TriageContext
# ---------------------------------------------------------------------------
function Write-TriageContext {
    [CmdletBinding()]
    param(
        [string]$RoomDir,
        [string]$Classification,
        [string]$QaFeedback,
        [string]$ArchitectGuidance,
        [string]$ManagerNotes
    )
    $artifactsDir = Join-Path $RoomDir "artifacts"
    if (-not (Test-Path $artifactsDir)) {
        New-Item -ItemType Directory -Path $artifactsDir -Force | Out-Null
    }
    $contextFile = Join-Path $artifactsDir "triage-context.md"
    $actionLine  = switch ($Classification) {
        'implementation-bug' { "Engineer: Fix the specific issues listed in QA's report above." }
        'design-issue'       { "Engineer: Follow the architect's guidance above to redesign the approach." }
        'plan-gap'           { "Engineer: The brief has been updated. Re-read brief.md and implement accordingly." }
        'role-mediation'     { "Counterpart role: answer the escalation, resolve missing assumptions, then post DONE so the reviewer can continue." }
        default              { "Engineer: Address the issues identified above." }
    }
    $guidanceSection = if ($ArchitectGuidance) { $ArchitectGuidance } else { "_Not consulted — classified as implementation bug._" }
    $content = @"
# Manager Triage Context

## Classification: $Classification

## QA Failure Report
$QaFeedback

## Architect Guidance
$guidanceSection

## Manager's Direction
$ManagerNotes

## Action Required
$actionLine
"@
    $content | Out-File -FilePath $contextFile -Encoding utf8 -Force
}

# ---------------------------------------------------------------------------
# Invoke-TriageMediation
# Starts a manager-as-leader triage judge when a reviewer escalates. ESCALATE
# means the deterministic loop should compile the current epic member context,
# then invoke --agent manager to judge the last escalator message. The manager
# agent posts the actual lifecycle signal (fix/reject/etc.); Start-ManagerLoop
# remains the authority that applies state transitions after that signal appears.
# ---------------------------------------------------------------------------
function Resolve-ManagerRolePath {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$RoleName)

    $agentsDir = _ctx 'agentsDir'
    $projectRoot = if ($agentsDir) { Split-Path $agentsDir -Parent } else { '' }
    $_homeDir = if ($env:HOME) { $env:HOME } else { $env:USERPROFILE }
    $ostwinHome = if ($env:OSTWIN_HOME) { $env:OSTWIN_HOME } else { Join-Path $_homeDir '.ostwin' }

    $candidates = @()
    if ($agentsDir) { $candidates += (Join-Path $agentsDir (Join-Path 'roles' $RoleName)) }
    $candidates += (Join-Path $ostwinHome (Join-Path '.agents' (Join-Path 'roles' $RoleName)))
    if ($projectRoot) { $candidates += (Join-Path $projectRoot (Join-Path 'contributes' (Join-Path 'roles' $RoleName))) }

    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path $candidate)) { return $candidate }
    }
    return $null
}

function Read-ManagerRoleHeader {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$RoleName)

    $rolePath = Resolve-ManagerRolePath -RoleName $RoleName
    $roleMd = if ($rolePath) { Join-Path $rolePath 'ROLE.md' } else { '' }
    if (-not $roleMd -or -not (Test-Path $roleMd)) {
        return [pscustomobject]@{
            Name = $RoleName
            Description = "$RoleName role"
            Tags = @()
            TrustLevel = ''
            Path = $roleMd
        }
    }

    $content = Get-Content $roleMd -Raw
    $header = ''
    if ($content -match '(?s)^---\s*\r?\n(.*?)\r?\n---') { $header = $Matches[1] }

    $name = $RoleName
    $description = "$RoleName role"
    $tags = @()
    $trustLevel = ''

    if ($header) {
        foreach ($line in ($header -split "\r?\n")) {
            if ($line -match '^name:\s*(.+)$') { $name = $Matches[1].Trim().Trim('"').Trim("'") }
            elseif ($line -match '^description:\s*(.+)$') { $description = $Matches[1].Trim().Trim('"').Trim("'") }
            elseif ($line -match '^trust_level:\s*(.+)$') { $trustLevel = $Matches[1].Trim().Trim('"').Trim("'") }
            elseif ($line -match '^tags:\s*\[(.*)\]\s*$') {
                $tags = @($Matches[1] -split ',' | ForEach-Object { $_.Trim().Trim('"').Trim("'") } | Where-Object { $_ })
            }
        }
    }

    return [pscustomobject]@{
        Name = $name
        Description = $description
        Tags = $tags
        TrustLevel = $trustLevel
        Path = $roleMd
    }
}

function Get-ManagerEpicMemberRoles {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$RoomDir,
        [Parameter(Mandatory)]$Lifecycle
    )

    $roles = [System.Collections.Generic.List[string]]::new()
    if ($Lifecycle -and $Lifecycle.states) {
        foreach ($stateName in $Lifecycle.states.PSObject.Properties.Name) {
            $stateDef = $Lifecycle.states.$stateName
            if ($stateDef -and $stateDef.role) {
                $base = ([string]$stateDef.role) -replace ':.*$', ''
                if ($base -and $base -ne 'manager' -and -not $roles.Contains($base)) { $roles.Add($base) | Out-Null }
            }
        }
    }

    $roomConfigFile = Join-Path $RoomDir 'config.json'
    if (Test-Path $roomConfigFile) {
        try {
            $roomCfg = Get-Content $roomConfigFile -Raw | ConvertFrom-Json
            if ($roomCfg.assignment -and $roomCfg.assignment.assigned_role) {
                $base = ([string]$roomCfg.assignment.assigned_role) -replace ':.*$', ''
                if ($base -and $base -ne 'manager' -and -not $roles.Contains($base)) { $roles.Add($base) | Out-Null }
            }
            if ($roomCfg.assignment -and $roomCfg.assignment.candidate_roles) {
                foreach ($candidate in @($roomCfg.assignment.candidate_roles)) {
                    $base = ([string]$candidate) -replace ':.*$', ''
                    if ($base -and $base -ne 'manager' -and -not $roles.Contains($base)) { $roles.Add($base) | Out-Null }
                }
            }
        } catch { }
    }

    return @($roles)
}

function Build-ManagerTeamDomainContext {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$RoomDir,
        [Parameter(Mandatory)]$Lifecycle
    )

    $memberRoles = Get-ManagerEpicMemberRoles -RoomDir $RoomDir -Lifecycle $Lifecycle
    $lines = [System.Collections.Generic.List[string]]::new()
    $lines.Add('## Team Domain Context') | Out-Null
    $lines.Add('') | Out-Null
    if (-not $memberRoles -or $memberRoles.Count -eq 0) {
        $lines.Add('Current epic members: _No member roles resolved from lifecycle/config._') | Out-Null
    } else {
        $lines.Add('Current epic members:') | Out-Null
        foreach ($roleName in $memberRoles) {
            $header = Read-ManagerRoleHeader -RoleName $roleName
            $tagText = if ($header.Tags -and $header.Tags.Count -gt 0) { $header.Tags -join ', ' } else { 'none' }
            $trustText = if ($header.TrustLevel) { $header.TrustLevel } else { 'unspecified' }
            $lines.Add("- $($header.Name): $($header.Description) (tags: $tagText; trust_level: $trustText)") | Out-Null
        }
    }
    $lines.Add('') | Out-Null
    $lines.Add('Leadership stance: You are the generic team leader for this epic. Inherit the domain language, risk lens, and evaluation expectations from the member descriptions above. Judge the escalation against the current epic context, not against a fixed engineering-manager persona.') | Out-Null
    return ($lines -join "`n")
}

function Build-ManagerTriagePrompt {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$RoomDir,
        [Parameter(Mandatory)]$Lifecycle,
        [Parameter(Mandatory)][string]$TaskRef,
        [Parameter(Mandatory)]$EscalationMessage
    )

    $agentsDir = _ctx 'agentsDir'
    $managerRolePath = if ($agentsDir) { Join-Path $agentsDir (Join-Path 'roles' (Join-Path 'manager' 'ROLE.md')) } else { '' }
    $managerRole = if ($managerRolePath -and (Test-Path $managerRolePath)) { Get-Content $managerRolePath -Raw } else { '# manager' }
    $teamDomain = Build-ManagerTeamDomainContext -RoomDir $RoomDir -Lifecycle $Lifecycle
    $briefPath = Join-Path $RoomDir 'brief.md'
    $brief = if (Test-Path $briefPath) { Get-Content $briefPath -Raw } else { '_No brief.md found._' }
    $tasksPath = Join-Path $RoomDir 'TASKS.md'
    $tasks = if (Test-Path $tasksPath) { Get-Content $tasksPath -Raw } else { '_No TASKS.md found._' }

    $readMessages = _ctx 'readMessages'
    $recent = @()
    try { $recent = & $readMessages -RoomDir $RoomDir -Last 8 -AsObject } catch { $recent = @() }
    $recentText = if ($recent -and $recent.Count -gt 0) {
        (@($recent) | ForEach-Object { "### $($_.from) -> $($_.to) [$($_.type)]`n$($_.body)" }) -join "`n`n"
    } else { '_No recent messages found._' }

    $escalationBody = if ($EscalationMessage.body) { [string]$EscalationMessage.body } else { '' }
    $raiser = if ($EscalationMessage.from) { [string]$EscalationMessage.from } else { 'unknown' }

    return @"
$managerRole

$teamDomain

## Current Epic Context

Task/Epic reference: $TaskRef

### Brief
$brief

### TASKS.md
$tasks

## Recent Member Messages

$recentText

## Last Escalator Message To Review

Escalator: $raiser

$escalationBody

## Your Triage Task

Review the last message from the escalator/member as the team leader for this epic.

Judge:
1. What is the actual blocker?
2. Is the answer already in the brief, TASKS.md, artifacts, or prior messages?
3. Which exact member/domain should answer or act next?
4. Is this classification: CLARIFICATION, MEMBER_WORK_DEFECT, DOMAIN_DESIGN_ISSUE, PLAN_GAP, BLOCKED, or INVALID_ALREADY_ANSWERED?
5. Should lifecycle retry budget be consumed? Default is NO for clarification/debate.
6. What exact next channel message should be posted?

You MUST post exactly one lifecycle decision message to the war-room channel as `manager`. Do not answer only in plain text. Do not say "no new channel post should be made".

End your channel message with exactly one compact machine-readable block:

```markdown
## TRIAGE_DECISION
message: <done | fix | design-review | plan-update | blocked | reject>
next: <review | optimize | developing | triage | blocked | failed>
```

Do not add extra keys to `TRIAGE_DECISION`.

Decision mapping:
- `message: done` / `next: review` when the escalation is resolved, stale, already answered, or the reviewer can continue.
- `message: fix` / `next: optimize` when the responsible member must clarify or change delivered work.
- `message: design-review` / `next: triage` when a specialist/domain decision is required before routing work.
- `message: plan-update` / `next: blocked` when requirements or acceptance criteria must be clarified outside the room.
- `message: blocked` / `next: blocked` when an external dependency prevents progress.
- `message: reject` / `next: failed` when the room cannot safely continue.

Fallback rule: if you cannot confidently determine the next lifecycle state, or if the escalation appears stale/already answered, return control to the escalator with:

```markdown
## TRIAGE_DECISION
message: done
next: review
```

Include concise classification, evidence considered, decision, next role, retry impact, and return path above the `TRIAGE_DECISION` block.
"@
}

function Start-ManagerTriageAgent {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$RoomDir,
        [Parameter(Mandatory)][string]$Prompt,
        [Parameter(Mandatory)][string]$TaskRef
    )

    $agentsDir = _ctx 'agentsDir'
    $invokeAgent = if ($agentsDir) { Join-Path $agentsDir (Join-Path 'roles' (Join-Path '_base' 'Invoke-Agent.ps1')) } else { '' }
    if (-not $invokeAgent -or -not (Test-Path $invokeAgent)) { throw "Invoke-Agent.ps1 not found for manager triage." }

    $artifactsDir = Join-Path $RoomDir 'artifacts'
    if (-not (Test-Path $artifactsDir)) { New-Item -ItemType Directory -Path $artifactsDir -Force | Out-Null }
    $promptPath = Join-Path $artifactsDir 'manager-triage-prompt.md'
    $Prompt | Out-File -FilePath $promptPath -Encoding utf8 -Force

    if ($env:OSTWIN_MANAGER_TRIAGE_NO_AGENT -eq '1') {
        return [pscustomobject]@{ Started = $false; Reason = 'disabled'; PromptPath = $promptPath }
    }

    if (Test-SpawnLock -RoomDir $RoomDir -Role 'manager') {
        return [pscustomobject]@{ Started = $false; Reason = 'spawn-lock'; PromptPath = $promptPath }
    }
    $managerPid = Join-Path $RoomDir (Join-Path 'pids' 'manager.pid')
    if (Test-PidAlive $managerPid) {
        return [pscustomobject]@{ Started = $false; Reason = 'pid-alive'; PromptPath = $promptPath }
    }

    Write-SpawnLock -RoomDir $RoomDir -Role 'manager'
    Set-RoleRunStatus -RoomDir $RoomDir -Role 'manager' -Status 'active' | Out-Null
    $timeout = Resolve-RoleTimeout -RoleName 'manager' -RoomDir $RoomDir
    $roomId = Split-Path $RoomDir -Leaf
    Start-Job -Name "ostwin-triage-$roomId-manager" -ScriptBlock {
        param($invoke, $room, $prompt, $timeoutSeconds)
        & $invoke -RoomDir $room -RoleName 'manager' -Prompt $prompt -TimeoutSeconds $timeoutSeconds -ForkSession
    } -ArgumentList $invokeAgent, $RoomDir, $Prompt, $timeout | Out-Null

    return [pscustomobject]@{ Started = $true; Reason = 'started'; PromptPath = $promptPath }
}

function Invoke-TriageMediation {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$RoomDir,
        [Parameter(Mandatory)]$Lifecycle,
        [Parameter(Mandatory)][string]$TaskRef
    )

    $readMessages = _ctx 'readMessages'
    $triageDef = if ($Lifecycle -and $Lifecycle.states -and $Lifecycle.states.triage) { $Lifecycle.states.triage } else { $null }
    if (-not $triageDef -or -not $triageDef.signals -or -not $triageDef.signals.fix) { return $null }

    # If the manager already emitted a triage decision for this state entry,
    # do not duplicate it. Find-LatestSignal will consume it normally.
    $existing = Find-LatestSignal -RoomDir $RoomDir -Lifecycle $Lifecycle -StateName 'triage'
    if ($existing) { return [pscustomobject]@{ Signal = $existing; AlreadyPresent = $true } }

    $changedAt = 0
    $changedFile = Join-Path $RoomDir 'state_changed_at'
    if (Test-Path $changedFile) {
        try { $changedAt = [long](Get-Content $changedFile -Raw).Trim() } catch { $changedAt = 0 }
    }

    $escalations = @()
    try { $escalations = & $readMessages -RoomDir $RoomDir -FilterType 'escalate' -AsObject } catch { $escalations = @() }
    if (-not $escalations -or $escalations.Count -eq 0) { return $null }

    $latestEscalation = $null
    $latestAnyEscalation = $null
    foreach ($msg in $escalations) {
        $msgTs = Convert-ManagerSignalTimestampToEpoch -Timestamp $msg.ts
        if (-not $latestAnyEscalation -or $msgTs -ge (Convert-ManagerSignalTimestampToEpoch -Timestamp $latestAnyEscalation.ts)) {
            $latestAnyEscalation = $msg
        }
        if ($msgTs -ge $changedAt -and (-not $latestEscalation -or $msgTs -ge (Convert-ManagerSignalTimestampToEpoch -Timestamp $latestEscalation.ts))) {
            $latestEscalation = $msg
        }
    }
    if (-not $latestEscalation -and $latestAnyEscalation) {
        # The escalation that caused review -> triage is usually timestamped just
        # BEFORE triage's state_changed_at. Filtering strictly against the new
        # triage timestamp drops the causal message and leaves triage idle with
        # no manager-output.txt. Fall back to the latest escalation when no
        # post-triage escalation exists; Find-LatestSignal already validated the
        # review escalation before the state transition.
        Write-Log "DEBUG" "[$TaskRef] Triage using latest pre-triage escalation as causal context."
        $latestEscalation = $latestAnyEscalation
    }
    if (-not $latestEscalation) {
        Write-Log "WARN" "[$TaskRef] Triage has no escalation message to compile for manager."
        return $null
    }

    $raiser = if ($latestEscalation.from) { [string]$latestEscalation.from } else { '' }
    $raiserBase = $raiser -replace ':.*$', ''

    $escalationBody = if ($latestEscalation.body) { [string]$latestEscalation.body } else { '' }

    $managerNotes = @"
Manager triage judge requested for ESCALATE: $raiserBase asked for leadership mediation before review can proceed.

The deterministic manager loop compiled the current epic member ROLE.md headers, recent messages, brief, TASKS.md, and the latest escalator message, then invoked --agent manager to judge the next action.
"@

    Write-TriageContext -RoomDir $RoomDir -Classification 'leader-triage' -QaFeedback $escalationBody -ArchitectGuidance '' -ManagerNotes $managerNotes
    $prompt = Build-ManagerTriagePrompt -RoomDir $RoomDir -Lifecycle $Lifecycle -TaskRef $TaskRef -EscalationMessage $latestEscalation
    $start = Start-ManagerTriageAgent -RoomDir $RoomDir -Prompt $prompt -TaskRef $TaskRef

    return [pscustomobject]@{
        Signal = 'manager-triage'
        TargetRole = 'manager'
        RaisedBy = $raiserBase
        PromptPath = $start.PromptPath
        Started = $start.Started
        Reason = $start.Reason
        AlreadyPresent = $false
    }
}

# ---------------------------------------------------------------------------
# Complete-PlanApproval (renamed from Handle-PlanApproval — P2 verb-noun fix)
# ---------------------------------------------------------------------------
function Complete-PlanApproval {
    [CmdletBinding()]
    param([string]$TaskRef)
    $agentsDir   = _ctx 'agentsDir'
    $WarRoomsDir = _ctx 'WarRoomsDir'

    if ($TaskRef -eq 'PLAN-REVIEW') {
        Write-Log "INFO" "[PLAN-REVIEW] Plan approved. Unblocking dependent rooms..."
        $buildDagScript = Join-Path $agentsDir "plan" "Build-DependencyGraph.ps1"
        if (Test-Path $buildDagScript) {
            $null = & $buildDagScript -WarRoomsDir $WarRoomsDir
            # Signal cache invalidation to caller via context
            if ($script:_ctx) { $script:_ctx['dagCache'] = $null }
        }
    }
}

Export-ModuleMember -Function @(
    'Get-UnixEpoch',
    'Write-AtomicFile',
    'Test-ValidRoomState',
    'ConvertTo-CanonicalRoomStatus',
    'Set-ManagerLoopContext',
    'Get-ManagerLoopContext',
    'Get-ActiveCount',
    'Get-MsgCount',
    'Get-LatestBody',
    'Get-RoomOrchestrationContext',
    'Get-LatestFailureMessage',
    'Get-LatestChannelMessage',
    'Write-ManagerOrchestrationEvent',
    'Invoke-PlanFailFast',
    'Test-StateTimedOut',
    'Stop-RoomProcesses',
    'Write-RoomStatus',
    'Find-LatestSignal',
    'Get-OutputSignal',
    'Invoke-SignalActions',
    'Write-Log',
    'Write-SpawnLock',
    'Test-SpawnLock',
    'Set-RoleRunStatus',
    'Get-FreshFailedRoleRun',
    'Resolve-RoleTimeout',
    'Start-WorkerJob',
    'Get-CachedDag',
    'Set-BlockedDescendants',
    'Invoke-ManagerTriage',
    'Write-TriageContext',
    'Resolve-ManagerRolePath',
    'Read-ManagerRoleHeader',
    'Get-ManagerEpicMemberRoles',
    'Build-ManagerTeamDomainContext',
    'Build-ManagerTriagePrompt',
    'Start-ManagerTriageAgent',
    'Invoke-TriageMediation',
    'Complete-PlanApproval'
)
