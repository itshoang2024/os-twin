<#
.SYNOPSIS
    Appends a lifecycle/channel signal with orchestration event metadata.

.DESCRIPTION
    Publishes the causal orchestration event before appending the conversation row to
    channel.jsonl. This preserves channel.jsonl for agent context while live
    dashboard ingestion handles orchestration facts.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$RoomDir,
    [Parameter(Mandatory)][string]$From,
    [Parameter(Mandatory)][string]$To,
    [Parameter(Mandatory)][string]$Type,
    [Parameter(Mandatory)][string]$Ref,
    [AllowEmptyString()][string]$Body = '',
    [string]$PlanId = '',
    [string]$RoomId = '',
    [string]$RunId = '',
    [string]$EventsPath = '',
    [string]$EventId = '',
    [string]$State = '',
    [switch]$LifecycleSignal
)

$agentsDir = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$eventsModule = Join-Path $agentsDir 'events' 'OrchestrationEvents.psm1'
if (Test-Path $eventsModule) { Import-Module (Resolve-Path $eventsModule).Path -Force }

$configPath = Join-Path $RoomDir 'config.json'
if (Test-Path $configPath) {
    try {
        $cfg = Get-Content $configPath -Raw | ConvertFrom-Json
        if (-not $PlanId -and $cfg.plan_id) { $PlanId = $cfg.plan_id }
        if (-not $RunId -and $cfg.run_id) { $RunId = $cfg.run_id }
        if (-not $RoomId -and $cfg.room_id) { $RoomId = $cfg.room_id }
        if (-not $EventsPath -and $cfg.events_path) { $EventsPath = $cfg.events_path }
        if (-not $State -and $cfg.status -and $cfg.status.current) { $State = $cfg.status.current }
    } catch {
        Write-Verbose "Unable to read room config for lifecycle signal metadata: $_"
    }
}
if (-not $RoomId) { $RoomId = Split-Path $RoomDir -Leaf }
if (-not $PlanId -and $env:OSTWIN_PLAN_ID) { $PlanId = $env:OSTWIN_PLAN_ID }
if (-not $RunId -and $env:OSTWIN_RUN_ID) { $RunId = $env:OSTWIN_RUN_ID }
if (-not $EventsPath -and $env:OSTWIN_EVENTS_PATH) { $EventsPath = $env:OSTWIN_EVENTS_PATH }
if (-not $RunId -and $PlanId) { $RunId = 'run_legacy' }
if (-not $EventId -and (Get-Command New-OrchestrationEventId -ErrorAction SilentlyContinue)) { $EventId = New-OrchestrationEventId }
if (-not $EventId) { $EventId = "evt_$([guid]::NewGuid().ToString('N'))" }

$msgId = "$From-$Type-$([guid]::NewGuid().ToString('N'))"
$ts = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
$bodyPreview = if ($Body.Length -gt 200) { $Body.Substring(0, 200) } else { $Body }

if ($PlanId -and (Get-Command Write-OrchestrationEvent -ErrorAction SilentlyContinue)) {
    $eventType = if ($LifecycleSignal) { 'lifecycle.signal.posted' } else { 'channel.message.posted' }
    $event = [ordered]@{
        event_id   = $EventId
        event_type = $eventType
        ts         = $ts
        plan_id    = $PlanId
        run_id     = $RunId
        room_id    = $RoomId
        epic_ref   = $Ref
        severity   = 'info'
        summary    = "$From posted $Type for $Ref."
        payload    = [ordered]@{
            from = $From
            to   = $To
            type = $Type
            ref  = $Ref
        }
        last_message = [ordered]@{
            message_id   = $msgId
            type         = $Type
            body_preview = $bodyPreview
        }
    }
    if ($LifecycleSignal) {
        $event['role'] = $From
        $event['state'] = if ($State) { $State } else { 'unknown' }
    }
    Write-OrchestrationEvent -EventsPath $EventsPath -Event $event | Out-Null
}

$message = [ordered]@{
    v        = 1
    id       = $msgId
    event_id = $EventId
    ts       = $ts
    plan_id  = $PlanId
    run_id   = $RunId
    room_id  = $RoomId
    from     = $From
    to       = $To
    type     = $Type
    ref      = $Ref
    body     = $Body
}

if (-not (Test-Path $RoomDir)) { New-Item -ItemType Directory -Path $RoomDir -Force | Out-Null }
($message | ConvertTo-Json -Compress -Depth 10) | Out-File -FilePath (Join-Path $RoomDir 'channel.jsonl') -Encoding utf8 -Append
return $message
