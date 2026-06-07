BeforeAll {
    $script:WriteLifecycleSignal = Join-Path (Resolve-Path "$PSScriptRoot/../../channel").Path 'Write-LifecycleSignal.ps1'
    $script:PriorEventWsDisabled = $env:OSTWIN_EVENT_WS_DISABLED
    $env:OSTWIN_EVENT_WS_DISABLED = '1'
}

AfterAll {
    $env:OSTWIN_EVENT_WS_DISABLED = $script:PriorEventWsDisabled
}

Describe 'Write-LifecycleSignal' {
    It 'stamps plan room and event ids without requiring events.jsonl' {
        $warRoomsDir = Join-Path $TestDrive 'warrooms'
        $roomDir = Join-Path $warRoomsDir 'room-001'
        New-Item -ItemType Directory -Path $roomDir -Force | Out-Null

        [ordered]@{
            room_id = 'room-001'
            task_ref = 'EPIC-001'
            plan_id = 'pt-test'
            run_id = 'run-test'
            status = [ordered]@{ current = 'review' }
        } | ConvertTo-Json -Depth 5 | Out-File -FilePath (Join-Path $roomDir 'config.json') -Encoding utf8

        $message = & $script:WriteLifecycleSignal -RoomDir $roomDir -From 'qa' -To 'manager' -Type 'pass' -Ref 'EPIC-001' -Body 'ok' -LifecycleSignal

        $message.plan_id | Should -Be 'pt-test'
        $message.run_id | Should -Be 'run-test'
        $message.room_id | Should -Be 'room-001'
        $message.event_id | Should -Match '^evt_'
        Test-Path (Join-Path $warRoomsDir 'events.jsonl') | Should -BeFalse

        $channel = Get-Content (Join-Path $roomDir 'channel.jsonl') -Raw | ConvertFrom-Json
        $channel.plan_id | Should -Be 'pt-test'
        $channel.run_id | Should -Be 'run-test'
        $channel.room_id | Should -Be 'room-001'
        $channel.event_id | Should -Be $message.event_id
    }
}
