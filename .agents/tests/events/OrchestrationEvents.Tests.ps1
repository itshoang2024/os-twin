BeforeAll {
    $script:EventsModule = Join-Path (Resolve-Path "$PSScriptRoot/../../events").Path 'OrchestrationEvents.psm1'
    Import-Module $script:EventsModule -Force
    $script:PriorEventWsDisabled = $env:OSTWIN_EVENT_WS_DISABLED
    $script:PriorEventFileEnabled = $env:OSTWIN_EVENT_FILE_ENABLED
    $env:OSTWIN_EVENT_WS_DISABLED = '1'
    $env:OSTWIN_EVENT_FILE_ENABLED = '1'
}

AfterAll {
    $env:OSTWIN_EVENT_WS_DISABLED = $script:PriorEventWsDisabled
    $env:OSTWIN_EVENT_FILE_ENABLED = $script:PriorEventFileEnabled
}

Describe 'OrchestrationEvents' {
    BeforeEach {
        $script:eventsPath = Join-Path $TestDrive "events-$(Get-Random).jsonl"
    }

    It 'appends a valid event with defaults and compact JSONL' {
        $event = Write-OrchestrationEvent -EventsPath $script:eventsPath -Event ([ordered]@{
            event_type = 'plan.run.started'
            plan_id    = 'pt-test'
            run_id     = 'run-test'
            summary    = 'Plan started'
            payload    = @{ source = 'test' }
        })

        $event.v | Should -Be 1
        $event.event_id | Should -Match '^evt_'
        $event.run_id | Should -Be 'run-test'
        $event.ts.ToString('o') | Should -Match '^\d{4}-\d{2}-\d{2}T'
        $event.severity | Should -Be 'info'
        $event.payload_hash | Should -Not -BeNullOrEmpty
        (Get-Content $script:eventsPath).Count | Should -Be 1
        (Get-Content $script:eventsPath -Raw) | Should -Match '"event_type":"plan.run.started"'
    }

    It 'does not create an event file by default' {
        $prior = $env:OSTWIN_EVENT_FILE_ENABLED
        Remove-Item Env:OSTWIN_EVENT_FILE_ENABLED -ErrorAction SilentlyContinue
        try {
            $event = Write-OrchestrationEvent -EventsPath $script:eventsPath -Event ([ordered]@{
                event_type = 'plan.run.started'
                plan_id    = 'pt-test'
                run_id     = 'run-test'
                summary    = 'Plan started'
                payload    = @{}
            })

            $event.event_type | Should -Be 'plan.run.started'
            Test-Path $script:eventsPath | Should -BeFalse
        } finally {
            $env:OSTWIN_EVENT_FILE_ENABLED = $prior
        }
    }

    It 'rejects events missing plan_id' {
        { Write-OrchestrationEvent -EventsPath $script:eventsPath -Event ([ordered]@{
            event_type = 'plan.run.started'
            summary    = 'Plan started'
            payload    = @{}
        }) } | Should -Throw '*plan_id*'
    }

    It 'rejects events missing run_id' {
        { Write-OrchestrationEvent -EventsPath $script:eventsPath -Event ([ordered]@{
            event_type = 'plan.run.started'
            plan_id    = 'pt-test'
            summary    = 'Plan started'
            payload    = @{}
        }) } | Should -Throw '*run_id*'
    }

    It 'rejects room-scoped events missing room_id or epic_ref' {
        { Write-OrchestrationEvent -EventsPath $script:eventsPath -Event ([ordered]@{
            event_type = 'room.status.changed'
            plan_id    = 'pt-test'
            run_id     = 'run-test'
            summary    = 'Status changed'
            payload    = @{}
        }) } | Should -Throw '*room_id*epic_ref*'
    }

    It 'returns existing event for idempotent duplicate append' {
        $eventId = New-OrchestrationEventId
        $input = [ordered]@{
            event_id   = $eventId
            event_type = 'plan.run.started'
            plan_id    = 'pt-test'
            run_id     = 'run-test'
            summary    = 'Plan started'
            payload    = @{ source = 'test' }
        }

        $first = Write-OrchestrationEvent -EventsPath $script:eventsPath -Event $input
        Start-Sleep -Milliseconds 20
        $second = Write-OrchestrationEvent -EventsPath $script:eventsPath -Event $input

        $second.event_id | Should -Be $first.event_id
        (Get-Content $script:eventsPath).Count | Should -Be 1
    }

    It 'throws on same event_id with different content' {
        $eventId = New-OrchestrationEventId
        Write-OrchestrationEvent -EventsPath $script:eventsPath -Event ([ordered]@{
            event_id   = $eventId
            event_type = 'plan.run.started'
            plan_id    = 'pt-test'
            run_id     = 'run-test'
            summary    = 'Plan started'
            payload    = @{ source = 'first' }
        }) | Out-Null

        { Write-OrchestrationEvent -EventsPath $script:eventsPath -Event ([ordered]@{
            event_id   = $eventId
            event_type = 'plan.run.started'
            plan_id    = 'pt-test'
            run_id     = 'run-test'
            summary    = 'Plan started differently'
            payload    = @{ source = 'second' }
        }) } | Should -Throw '*idempotency conflict*'
    }

    It 'reads events for replay without duplicating source lines' {
        Write-OrchestrationEvent -EventsPath $script:eventsPath -Event ([ordered]@{
            event_type = 'plan.run.started'
            plan_id    = 'pt-test'
            run_id     = 'run-test'
            summary    = 'Plan started'
            payload    = @{}
        }) | Out-Null

        $events = Read-OrchestrationEvents -EventsPath $script:eventsPath
        $events.Count | Should -Be 1
        $events[0].event_type | Should -Be 'plan.run.started'
        $events[0].run_id | Should -Be 'run-test'
    }
}
