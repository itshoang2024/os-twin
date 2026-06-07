Set-StrictMode -Version Latest

$script:EventTaxonomy = @(
    'plan.created', 'plan.updated', 'plan.review.requested', 'plan.review.approved', 'plan.review.rejected', 'plan.dag.built',
    'plan.run.started', 'plan.run.completed', 'plan.run.failed', 'plan.run.cancelled', 'plan.run.paused', 'plan.run.resumed',
    'room.created', 'room.status.changed', 'epic.started', 'epic.passed', 'epic.failed', 'epic.retrying', 'epic.blocked', 'epic.unblocked',
    'dependency.created', 'dependency.satisfied', 'dependency.blocked', 'dependency.unblocked',
    'role.assigned', 'role.reassigned', 'role.resolved', 'role.spawn.requested',
    'agent.run.started', 'agent.run.completed', 'agent.run.failed', 'agent.run.timed_out', 'agent.run.respawned',
    'lifecycle.signal.posted', 'lifecycle.transition.applied', 'lifecycle.retry.exhausted', 'lifecycle.escalated',
    'workspace.git.preflight.passed', 'workspace.git.preflight.failed', 'workspace.integration.ready',
    'workspace.worktree.requested', 'workspace.worktree.ready', 'workspace.worktree.failed', 'workspace.room.committed',
    'workspace.merge.requested', 'workspace.merge.started', 'workspace.merge.completed', 'workspace.merge.conflicted',
    'channel.message.posted', 'bot.notification.queued', 'bot.notification.sent', 'bot.notification.failed',
    'conversation.bound', 'conversation.unbound', 'conversation.subscription.updated',
    'user.feedback.requested', 'user.feedback.posted', 'user.plan.cancel_requested', 'user.plan.pause_requested', 'user.plan.resume_requested'
)

$script:RoomScopedEventTypes = @(
    'room.created', 'room.status.changed',
    'epic.started', 'epic.passed', 'epic.failed', 'epic.retrying', 'epic.blocked', 'epic.unblocked',
    'dependency.created', 'dependency.satisfied', 'dependency.blocked', 'dependency.unblocked',
    'role.assigned', 'role.reassigned', 'role.resolved', 'role.spawn.requested',
    'agent.run.started', 'agent.run.completed', 'agent.run.failed', 'agent.run.timed_out', 'agent.run.respawned',
    'lifecycle.signal.posted', 'lifecycle.transition.applied', 'lifecycle.retry.exhausted', 'lifecycle.escalated',
    'workspace.worktree.requested', 'workspace.worktree.ready', 'workspace.worktree.failed', 'workspace.room.committed',
    'workspace.merge.requested', 'workspace.merge.started', 'workspace.merge.completed', 'workspace.merge.conflicted',
    'channel.message.posted',
    'conversation.bound', 'conversation.unbound', 'conversation.subscription.updated'
)

$script:RoleScopedEventTypes = @(
    'role.assigned', 'role.reassigned', 'role.resolved', 'role.spawn.requested',
    'agent.run.started', 'agent.run.completed', 'agent.run.failed', 'agent.run.timed_out', 'agent.run.respawned'
)

$script:AllowedSeverities = @('debug', 'info', 'warn', 'error', 'fatal')

function ConvertTo-OrchestrationHashtable {
    param([Parameter(Mandatory)]$InputObject)

    if ($InputObject -is [hashtable]) { return $InputObject.Clone() }
    if ($InputObject -is [System.Collections.Specialized.OrderedDictionary]) {
        $result = [ordered]@{}
        foreach ($key in $InputObject.Keys) { $result[$key] = $InputObject[$key] }
        return $result
    }

    $result = [ordered]@{}
    foreach ($prop in $InputObject.PSObject.Properties) {
        $result[$prop.Name] = $prop.Value
    }
    return $result
}

function New-OrchestrationEventId {
    [CmdletBinding()]
    param()

    $guid = [guid]::NewGuid().ToString('N')
    return "evt_$guid"
}

function Resolve-OrchestrationEventLogPath {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$PlanId,
        [Parameter(Mandatory)][string]$WarRoomsDir
    )

    if ([string]::IsNullOrWhiteSpace($PlanId)) { throw 'PlanId is required to resolve orchestration event log path.' }
    if ([string]::IsNullOrWhiteSpace($WarRoomsDir)) { throw 'WarRoomsDir is required to resolve orchestration event log path.' }

    return ''
}

function Get-OrchestrationStableJson {
    param([Parameter(Mandatory)][hashtable]$Event)

    $copy = [ordered]@{}
    foreach ($key in ($Event.Keys | Sort-Object)) {
        if ($key -eq 'payload_hash') { continue }
        if ($key -eq 'ts') { continue }
        $value = $Event[$key]
        $copy[$key] = $value
    }
    return ($copy | ConvertTo-Json -Compress -Depth 20)
}

function Get-OrchestrationPayloadHash {
    param([Parameter(Mandatory)][hashtable]$Event)

    $json = Get-OrchestrationStableJson -Event $Event
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
        return [BitConverter]::ToString($sha.ComputeHash($bytes)).Replace('-', '').ToLowerInvariant()
    } finally {
        $sha.Dispose()
    }
}

function Resolve-OrchestrationDashboardWebSocketUrl {
    [CmdletBinding()]
    param()

    if ($env:OSTWIN_DASHBOARD_WS_URL) { return $env:OSTWIN_DASHBOARD_WS_URL }
    if ($env:DASHBOARD_URL) {
        $base = $env:DASHBOARD_URL.TrimEnd('/')
        if ($base.StartsWith('https://')) { return ($base -replace '^https://', 'wss://') + '/api/ws' }
        if ($base.StartsWith('http://')) { return ($base -replace '^http://', 'ws://') + '/api/ws' }
    }
    $port = if ($env:DASHBOARD_PORT) { $env:DASHBOARD_PORT } else { '3366' }
    return "ws://127.0.0.1:$port/api/ws"
}

function Send-OrchestrationEventToDashboard {
    [CmdletBinding()]
    param([Parameter(Mandatory)][object]$Event)

    if ($env:OSTWIN_EVENT_WS_DISABLED -in @('1', 'true', 'TRUE', 'yes', 'YES')) { return $false }

    $wsUrl = Resolve-OrchestrationDashboardWebSocketUrl
    $client = [System.Net.WebSockets.ClientWebSocket]::new()
    $cts = [System.Threading.CancellationTokenSource]::new()
    $cts.CancelAfter(750)
    try {
        $uri = [Uri]$wsUrl
        $client.ConnectAsync($uri, $cts.Token).GetAwaiter().GetResult()
        $envelope = [ordered]@{
            type = 'orchestration.event.ingest'
            data = $Event
        }
        $json = $envelope | ConvertTo-Json -Compress -Depth 30
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
        $segment = [ArraySegment[byte]]::new($bytes)
        $client.SendAsync($segment, [System.Net.WebSockets.WebSocketMessageType]::Text, $true, $cts.Token).GetAwaiter().GetResult()
        $client.CloseAsync([System.Net.WebSockets.WebSocketCloseStatus]::NormalClosure, 'event sent', $cts.Token).GetAwaiter().GetResult()
        return $true
    } catch {
        return $false
    } finally {
        $cts.Dispose()
        $client.Dispose()
    }
}

function Test-OrchestrationEvent {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][object]$Event
    )

    $e = ConvertTo-OrchestrationHashtable -InputObject $Event
    $errors = @()

    foreach ($field in @('v', 'event_id', 'event_type', 'ts', 'plan_id', 'run_id', 'severity', 'summary', 'payload')) {
        if (-not $e.Contains($field) -or $null -eq $e[$field] -or ($e[$field] -is [string] -and [string]::IsNullOrWhiteSpace($e[$field]))) {
            $errors += "Missing required field: $field"
        }
    }

    if ($e.Contains('v') -and [int]$e['v'] -ne 1) { $errors += 'Unsupported event envelope version. Expected v=1.' }
    if ($e.Contains('event_type') -and $script:EventTaxonomy -notcontains [string]$e['event_type']) { $errors += "Unknown event_type: $($e['event_type'])" }
    if ($e.Contains('severity') -and $script:AllowedSeverities -notcontains [string]$e['severity']) { $errors += "Invalid severity: $($e['severity'])" }

    $eventType = if ($e.Contains('event_type')) { [string]$e['event_type'] } else { '' }
    if ($script:RoomScopedEventTypes -contains $eventType) {
        foreach ($field in @('room_id', 'epic_ref')) {
            if (-not $e.Contains($field) -or [string]::IsNullOrWhiteSpace([string]$e[$field])) {
                $errors += "Room-scoped event '$eventType' missing required field: $field"
            }
        }
    }
    if ($script:RoleScopedEventTypes -contains $eventType) {
        foreach ($field in @('role', 'state')) {
            if (-not $e.Contains($field) -or [string]::IsNullOrWhiteSpace([string]$e[$field])) {
                $errors += "Role-scoped event '$eventType' missing required field: $field"
            }
        }
    }

    return [PSCustomObject]@{
        IsValid = ($errors.Count -eq 0)
        Errors  = $errors
    }
}

function Read-OrchestrationEvents {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$EventsPath,
        [int]$Tail = 0
    )

    if (-not (Test-Path $EventsPath)) { return @() }
    $lines = Get-Content -Path $EventsPath -ErrorAction Stop
    if ($Tail -gt 0 -and $lines.Count -gt $Tail) {
        $lines = $lines | Select-Object -Last $Tail
    }

    $events = @()
    foreach ($line in $lines) {
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        $events += ($line | ConvertFrom-Json)
    }
    return $events
}

function Write-OrchestrationEvent {
    [CmdletBinding()]
    param(
        [string]$EventsPath = '',
        [Parameter(Mandatory)][object]$Event
    )

    $e = ConvertTo-OrchestrationHashtable -InputObject $Event
    if (-not $e.Contains('v') -or $null -eq $e['v']) { $e['v'] = 1 }
    if (-not $e.Contains('event_id') -or [string]::IsNullOrWhiteSpace([string]$e['event_id'])) { $e['event_id'] = New-OrchestrationEventId }
    if (-not $e.Contains('ts') -or [string]::IsNullOrWhiteSpace([string]$e['ts'])) { $e['ts'] = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ') }
    if (-not $e.Contains('run_id') -or [string]::IsNullOrWhiteSpace([string]$e['run_id'])) {
        if ($env:OSTWIN_RUN_ID) { $e['run_id'] = $env:OSTWIN_RUN_ID }
    }
    if (-not $e.Contains('severity') -or [string]::IsNullOrWhiteSpace([string]$e['severity'])) { $e['severity'] = 'info' }
    if (-not $e.Contains('payload') -or $null -eq $e['payload']) { $e['payload'] = [ordered]@{} }

    $validation = Test-OrchestrationEvent -Event $e
    if (-not $validation.IsValid) {
        throw "Invalid orchestration event: $($validation.Errors -join '; ')"
    }

    $e['payload_hash'] = Get-OrchestrationPayloadHash -Event $e

    $written = ($e | ConvertTo-Json -Compress -Depth 20) | ConvertFrom-Json
    Send-OrchestrationEventToDashboard -Event $written | Out-Null

    $fileEnabled = $env:OSTWIN_EVENT_FILE_ENABLED -in @('1', 'true', 'TRUE', 'yes', 'YES')
    if (-not $fileEnabled -or [string]::IsNullOrWhiteSpace($EventsPath)) {
        return $written
    }

    $parent = Split-Path $EventsPath -Parent
    if ($parent -and -not (Test-Path $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    $lockPath = "$EventsPath.lock"

    $lockStream = [System.IO.File]::Open($lockPath, [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
    try {
        $existing = @()
        if (Test-Path $EventsPath) { $existing = Read-OrchestrationEvents -EventsPath $EventsPath }
        foreach ($prior in $existing) {
            if ($prior.event_id -eq $e['event_id']) {
                if ($prior.payload_hash -eq $e['payload_hash']) { return $prior }
                throw "Event idempotency conflict for event_id '$($e['event_id'])': existing payload hash differs."
            }
        }

        $json = ($e | ConvertTo-Json -Compress -Depth 20)
        [System.IO.File]::AppendAllText($EventsPath, $json + [Environment]::NewLine, [System.Text.Encoding]::UTF8)
        $written = ($json | ConvertFrom-Json)
        Send-OrchestrationEventToDashboard -Event $written | Out-Null
        return $written
    } finally {
        $lockStream.Dispose()
    }
}

Export-ModuleMember -Function New-OrchestrationEventId, Resolve-OrchestrationEventLogPath, Resolve-OrchestrationDashboardWebSocketUrl, Send-OrchestrationEventToDashboard, Write-OrchestrationEvent, Read-OrchestrationEvents, Test-OrchestrationEvent
