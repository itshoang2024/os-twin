# Agent OS — Manager fail-fast orchestration semantics (EPIC-003)

BeforeAll {
    $script:agentsDir = (Resolve-Path (Join-Path $PSScriptRoot "../../..")).Path
    . (Join-Path $script:agentsDir "tests" "TestChannelHelpers.ps1")
    $script:PostMessage = New-TestChannelWriter

    Import-Module (Join-Path $script:agentsDir "events" "OrchestrationEvents.psm1") -Force
    Import-Module (Join-Path $script:agentsDir "roles" "manager" "ManagerLoop-Helpers.psm1") -Force
    $script:PriorEventWsDisabled = $env:OSTWIN_EVENT_WS_DISABLED
    $script:PriorEventFileEnabled = $env:OSTWIN_EVENT_FILE_ENABLED
    $env:OSTWIN_EVENT_WS_DISABLED = '1'
    $env:OSTWIN_EVENT_FILE_ENABLED = '1'

    function New-FailFastTestRoom {
        param(
            [string]$RoomId = 'room-001',
            [string]$TaskRef = 'EPIC-003',
            [string]$Status = 'review'
        )
        $warRoomsDir = Join-Path $TestDrive "warrooms-$(Get-Random)"
        $roomDir = Join-Path $warRoomsDir $RoomId
        $artifactsDir = Join-Path $roomDir 'artifacts'
        New-Item -ItemType Directory -Path $artifactsDir -Force | Out-Null
        $eventsPath = Join-Path $warRoomsDir 'events.jsonl'
        $TaskRef | Out-File -FilePath (Join-Path $roomDir 'task-ref') -Encoding utf8 -NoNewline
        $Status | Out-File -FilePath (Join-Path $roomDir 'status') -Encoding utf8 -NoNewline
        '0' | Out-File -FilePath (Join-Path $roomDir 'retries') -Encoding utf8 -NoNewline
        @{
            plan_id = 'plan-failfast'
            run_id = 'run-failfast'
            events_path = $eventsPath
            room_id = $RoomId
            task_ref = $TaskRef
            status = @{ current = $Status }
            assignment = @{ assigned_role = 'qa' }
        } | ConvertTo-Json -Depth 10 | Out-File -FilePath (Join-Path $roomDir 'config.json') -Encoding utf8
        Set-ManagerLoopContext -Context @{
            WarRoomsDir = $warRoomsDir
            readMessages = (Join-Path $script:agentsDir 'channel' 'Read-Messages.ps1')
            stateTimeout = 1
            maxRetries = 3
        }
        return [pscustomobject]@{ WarRoomsDir = $warRoomsDir; RoomDir = $roomDir; EventsPath = $eventsPath }
    }
}

AfterAll {
    $env:OSTWIN_EVENT_WS_DISABLED = $script:PriorEventWsDisabled
    $env:OSTWIN_EVENT_FILE_ENABLED = $script:PriorEventFileEnabled
    Remove-Module OrchestrationEvents -ErrorAction SilentlyContinue
    Remove-Module ManagerLoop-Helpers -ErrorAction SilentlyContinue
}

Describe 'Manager fail-fast event semantics' {
    It 'emits epic.failed then plan.run.failed with latest failed channel message' {
        $ctx = New-FailFastTestRoom -RoomId 'room-ff-001' -TaskRef 'EPIC-003' -Status 'review'
        & $script:PostMessage -RoomDir $ctx.RoomDir -From 'qa' -To 'manager' -Type 'fail' -Ref 'EPIC-003' -Body ('QA failure ' + ('x' * 700)) | Out-Null

        Invoke-PlanFailFast -RoomDir $ctx.RoomDir -Reason 'retry_exhausted' -Role 'qa' -State 'review' -Summary 'EPIC-003 exhausted retries.' | Should -BeTrue

        $events = Read-OrchestrationEvents -EventsPath $ctx.EventsPath
        $failFastEvents = @($events | Where-Object { $_.event_type -in @('epic.failed', 'plan.run.failed') })
        $failFastEvents.Count | Should -Be 2
        $failFastEvents[0].event_type | Should -Be 'epic.failed'
        $failFastEvents[1].event_type | Should -Be 'plan.run.failed'
        $failFastEvents[0].plan_id | Should -Be 'plan-failfast'
        $failFastEvents[0].run_id | Should -Be 'run-failfast'
        $failFastEvents[0].room_id | Should -Be 'room-ff-001'
        $failFastEvents[0].epic_ref | Should -Be 'EPIC-003'
        $failFastEvents[0].last_message.type | Should -Be 'fail'
        $failFastEvents[0].last_message.from | Should -Be 'qa'
        $failFastEvents[0].last_message.body_preview.Length | Should -BeLessOrEqual 500
        $failFastEvents[1].payload.failed_epic.epic_ref | Should -Be 'EPIC-003'
        $failFastEvents[1].payload.failed_epic.run_id | Should -Be 'run-failfast'
    }

    It 'routes semantic QA fail to manager triage without spending retry budget or plan fail-fast' {
        $ctx = New-FailFastTestRoom -RoomId 'room-ff-002' -TaskRef 'EPIC-004' -Status 'review'
        & $script:PostMessage -RoomDir $ctx.RoomDir -From 'qa' -To 'manager' -Type 'fail' -Ref 'EPIC-004' -Body 'Implementation defect; retry is allowed.' | Out-Null

        Write-ManagerOrchestrationEvent -RoomDir $ctx.RoomDir -EventType 'lifecycle.escalated' -Summary 'EPIC-004 semantic QA fail routed to manager triage.' -Payload @{ signal = 'fail'; retries = 0; max_retries = 3; target_state = 'triage' } -Role 'qa' -State 'review' -Severity 'warn' -LastMessage (Get-LatestFailureMessage -RoomDir $ctx.RoomDir -Role 'qa') | Out-Null

        $events = Read-OrchestrationEvents -EventsPath $ctx.EventsPath
        $events.Count | Should -Be 1
        $events[0].event_type | Should -Be 'lifecycle.escalated'
        $events[0].payload.retries | Should -Be 0
        $events[0].payload.target_state | Should -Be 'triage'
        $events[0].run_id | Should -Be 'run-failfast'
        @($events | Where-Object event_type -eq 'epic.retrying').Count | Should -Be 0
        @($events | Where-Object event_type -eq 'plan.run.failed').Count | Should -Be 0
    }

    It 'attaches latest manager channel message to plan completion context' {
        $ctx = New-FailFastTestRoom -RoomId 'room-003' -TaskRef 'EPIC-006' -Status 'passed'
        & $script:PostMessage -RoomDir $ctx.RoomDir -From 'qa' -To 'manager' -Type 'pass' -Ref 'EPIC-006' -Body 'QA signed off.' | Out-Null
        & $script:PostMessage -RoomDir $ctx.RoomDir -From 'manager' -To 'all' -Type 'done' -Ref 'EPIC-006' -Body ('Release summary ' + ('x' * 700)) | Out-Null

        $lastMessage = Get-LatestChannelMessage -RoomDir $ctx.RoomDir -Role 'manager'
        Write-ManagerOrchestrationEvent -RoomDir $ctx.RoomDir -EventType 'plan.run.completed' -Summary 'Plan run completed successfully.' -Payload @{ room_count = 3; role = 'manager'; agent_name = 'manager' } -Role 'manager' -State 'passed' -Severity 'info' -LastMessage $lastMessage | Out-Null

        $events = Read-OrchestrationEvents -EventsPath $ctx.EventsPath
        $completion = @($events | Where-Object event_type -eq 'plan.run.completed')[-1]
        $completion.payload.room_count | Should -Be 3
        $completion.payload.agent_name | Should -Be 'manager'
        $completion.last_message.from | Should -Be 'manager'
        $completion.last_message.type | Should -Be 'done'
        $completion.last_message.body_preview | Should -Match '^Release summary'
        $completion.last_message.body_preview.Length | Should -BeLessOrEqual 500
    }

    It 'attaches latest manager channel message to room status changes' {
        $ctx = New-FailFastTestRoom -RoomId 'room-002' -TaskRef 'EPIC-002' -Status 'pending'
        & $script:PostMessage -RoomDir $ctx.RoomDir -From 'manager' -To 'engineer' -Type 'assign' -Ref 'EPIC-002' -Body 'Manager context for transition.' | Out-Null

        Write-RoomStatus -RoomDir $ctx.RoomDir -NewStatus 'developing'

        $events = Read-OrchestrationEvents -EventsPath $ctx.EventsPath
        $statusEvent = @($events | Where-Object event_type -eq 'room.status.changed')[-1]
        $statusEvent.payload.previous_status | Should -Be 'pending'
        $statusEvent.payload.status | Should -Be 'developing'
        $statusEvent.payload.agent_name | Should -Be 'manager'
        $statusEvent.last_message.from | Should -Be 'manager'
        $statusEvent.last_message.body_preview | Should -Be 'Manager context for transition.'
    }

    It 'keeps non-manager crash exhaustion observable without immediate fail-fast' {
        $ctx = New-FailFastTestRoom -RoomId 'room-ff-003' -TaskRef 'EPIC-005' -Status 'developing'

        Write-ManagerOrchestrationEvent -RoomDir $ctx.RoomDir -EventType 'agent.run.failed' -Summary 'engineer exhausted crash respawns in developing.' -Payload @{ reason = 'crash_respawn_exhausted'; crash_count = 4; max_crash_respawns = 3 } -Role 'engineer' -State 'developing' -Severity 'error' | Out-Null

        $events = Read-OrchestrationEvents -EventsPath $ctx.EventsPath
        $failureEvents = @($events | Where-Object { $_.event_type -in @('agent.run.failed', 'epic.failed', 'plan.run.failed') })
        ($failureEvents | Select-Object -ExpandProperty event_type) | Should -Be @('agent.run.failed')
        $failureEvents[0].payload.reason | Should -Be 'crash_respawn_exhausted'
        @($events | Where-Object event_type -eq 'epic.failed').Count | Should -Be 0
        @($events | Where-Object event_type -eq 'plan.run.failed').Count | Should -Be 0
    }

}
