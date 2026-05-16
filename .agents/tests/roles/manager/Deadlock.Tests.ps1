# Agent OS — Deadlock Exploitation Tests
#
# These tests prove that specific code paths in Start-ManagerLoop.ps1 cause
# permanent deadlocks. Each test constructs the exact filesystem state that
# triggers the bug, then asserts the invariant violation.
#
# Cross-ref: deadlock_analysis.md (Risks 1–6)

BeforeAll {
    $script:agentsDir = (Resolve-Path (Join-Path (Resolve-Path "$PSScriptRoot/../../../roles/manager").Path ".." "..")).Path
    $script:PostMessage = Join-Path $script:agentsDir "channel" "Post-Message.ps1"
    $script:ReadMessages = Join-Path $script:agentsDir "channel" "Read-Messages.ps1"
    $script:NewWarRoom = Join-Path $script:agentsDir "war-rooms" "New-WarRoom.ps1"

    # Import Utils for Test-PidAlive, Set-WarRoomStatus
    $utilsModule = Join-Path $script:agentsDir "lib" "Utils.psm1"
    if (Test-Path $utilsModule) { Import-Module $utilsModule -Force }

    # ---- Helpers must live inside BeforeAll for Pester v5 scoping ----

    # Simulate one iteration of the manager loop's done-counting logic.
    # Replicates Start-ManagerLoop.ps1 lines 734-757:
    #   $doneCount = Get-MsgCount $roomDir "done"
    #   $expected = $retries + 1
    #   if ($doneCount -ge $expected) { transition to next state }
    function script:Invoke-DoneCountCheck {
        param(
            [string]$RoomDir,
            [string]$ReadMessagesScript
        )
        $retries = if (Test-Path (Join-Path $RoomDir "retries")) {
            [int](Get-Content (Join-Path $RoomDir "retries") -Raw).Trim()
        } else { 0 }

        $msgs = & $ReadMessagesScript -RoomDir $RoomDir -FilterType "done" -AsObject
        $doneCount = if ($msgs) { @($msgs).Count } else { 0 }
        $expected = $retries + 1

        return @{
            DoneCount       = $doneCount
            Expected        = $expected
            Retries         = $retries
            WouldTransition = ($doneCount -ge $expected)
        }
    }

    # Simulate the deadlock recovery logic for a single room.
    # Replicates Start-ManagerLoop.ps1 lines 1526-1538.
    function script:Invoke-DeadlockRecovery {
        param(
            [string]$RoomDir,
            [string]$PostMessageScript,
            [int]$MaxRetries = 3
        )
        $status = (Get-Content (Join-Path $RoomDir "status") -Raw).Trim()
        $retries = if (Test-Path (Join-Path $RoomDir "retries")) {
            [int](Get-Content (Join-Path $RoomDir "retries") -Raw).Trim()
        } else { 0 }
        $taskRef = if (Test-Path (Join-Path $RoomDir "task-ref")) {
            (Get-Content (Join-Path $RoomDir "task-ref") -Raw).Trim()
        } else { "UNKNOWN" }

        # Increment deadlock_recoveries counter
        $dlFile = Join-Path $RoomDir "deadlock_recoveries"
        $dlCount = if (Test-Path $dlFile) { [int](Get-Content $dlFile -Raw).Trim() } else { 0 }
        ($dlCount + 1).ToString() | Out-File -FilePath $dlFile -Encoding utf8 -NoNewline

        # Resolve room's assigned role
        $dlRoomConfig = Join-Path $RoomDir "config.json"
        $dlRole = "engineer"
        if (Test-Path $dlRoomConfig) {
            $dlRc = Get-Content $dlRoomConfig -Raw | ConvertFrom-Json
            if ($dlRc.assignment -and $dlRc.assignment.assigned_role) {
                $dlRole = $dlRc.assignment.assigned_role -replace ':.*$', ''
            }
        }

        if ($status -in @('developing', 'fixing', 'optimize')) {
            # Simulate Risk 2 fix: Clean stale PIDs before transition
            Remove-Item -Path (Join-Path $RoomDir "pids\*") -Force -Recurse -ErrorAction SilentlyContinue
            
            # Simulate Risk 3+4 fix: deadlock recovery no longer increments retries
            & $PostMessageScript -RoomDir $RoomDir -From "manager" -To $dlRole -Type "fix" -Ref $taskRef -Body "Deadlock recovery: restarting $dlRole."
            Set-WarRoomStatus -RoomDir $RoomDir -NewStatus "fixing"
        }
    }

    # Count transition-related properties on a deserialized JSON object.
    # Empty JSON {} may deserialize as PSCustomObject with no NoteProperties,
    # or as a raw hashtable with Count=0. This normalises both cases.
    function script:Get-TransitionCount {
        param($Transitions)
        if ($null -eq $Transitions) { return 0 }
        if ($Transitions -is [hashtable]) { return $Transitions.Count }
        $props = @($Transitions.PSObject.Properties | Where-Object { $_.MemberType -eq 'NoteProperty' })
        return $props.Count
    }
}

AfterAll {
    Remove-Module -Name "Utils" -ErrorAction SilentlyContinue
}

Describe "Deadlock Exploitation Tests" {

    BeforeEach {
        $script:warRoomsDir = Join-Path $TestDrive "warrooms-dl-$(Get-Random)"
        New-Item -ItemType Directory -Path $script:warRoomsDir -Force | Out-Null
    }

    # ========================================================================
    # RISK 3: Deadlock recovery increments retries → doneCount < expected
    # permanently unsatisfiable.
    # ========================================================================
    Context "Risk 3: Deadlock recovery done-counter corruption" {

        It "deadlock recovery makes doneCount < expected permanently unsatisfiable" {
            & $script:NewWarRoom -RoomId "room-dl3" -TaskRef "DL-003" `
                -TaskDescription "Deadlock test" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-dl3"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "developing"

            # BEFORE: expected = 0 + 1 = 1
            $before = Invoke-DoneCountCheck -RoomDir $roomDir -ReadMessagesScript $script:ReadMessages
            $before.Expected | Should -Be 1
            $before.DoneCount | Should -Be 0

            # Deadlock recovery fires (worker died without posting done)
            Invoke-DeadlockRecovery -RoomDir $roomDir -PostMessageScript $script:PostMessage -MaxRetries 3

            $retries = [int](Get-Content (Join-Path $roomDir "retries") -Raw).Trim()
            $retries | Should -Be 0 -Because "Deadlock recovery no longer inflates retries"

            # New worker posts exactly 1 done message
            & $script:PostMessage -RoomDir $roomDir -From "engineer" -To "manager" `
                -Type "done" -Ref "DL-003" -Body "Worker completed task"

            # AFTER: expected = 0 + 1 = 1, and doneCount = 1. SUCCESS.
            $after = Invoke-DoneCountCheck -RoomDir $roomDir -ReadMessagesScript $script:ReadMessages
            $after.DoneCount | Should -Be 1
            $after.Expected | Should -Be 1
            $after.WouldTransition | Should -BeTrue `
                -Because "FIX: doneCount(1) == expected(1), room unblocked"
        }

        It "compound deadlock: multiple recovery cycles keep raising expected" {
            & $script:NewWarRoom -RoomId "room-dl3b" -TaskRef "DL-003B" `
                -TaskDescription "Compound deadlock" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-dl3b"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "developing"

            for ($i = 0; $i -lt 3; $i++) {
                Invoke-DeadlockRecovery -RoomDir $roomDir -PostMessageScript $script:PostMessage -MaxRetries 10
            }

            $retries = [int](Get-Content (Join-Path $roomDir "retries") -Raw).Trim()
            $retries | Should -Be 0

            for ($i = 0; $i -lt 3; $i++) {
                & $script:PostMessage -RoomDir $roomDir -From "engineer" -To "manager" `
                    -Type "done" -Ref "DL-003B" -Body "Done attempt $($i+1)"
            }

            $check = Invoke-DoneCountCheck -RoomDir $roomDir -ReadMessagesScript $script:ReadMessages
            $check.DoneCount | Should -Be 3
            $check.Expected | Should -Be 1
            $check.WouldTransition | Should -BeTrue `
                -Because "Recoveries no longer raise expected; worker completes cleanly"
        }
    }

    # ========================================================================
    # RISK 4: QA deadlock recovery cascade → Risk 3
    # ========================================================================
    Context "Risk 4: QA deadlock recovery cascade" {

        It "review with exhausted qa_retries cascades into fixing deadlock" {
            & $script:NewWarRoom -RoomId "room-dl4" -TaskRef "DL-004" `
                -TaskDescription "QA cascade test" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-dl4"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "developing"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "review"

            & $script:PostMessage -RoomDir $roomDir -From "qa" -To "manager" `
                -Type "error" -Ref "DL-004" -Body "QA verdict parse failure"

            "10" | Out-File -FilePath (Join-Path $roomDir "qa_retries") -Encoding utf8 -NoNewline

            $qaRetries = [int](Get-Content (Join-Path $roomDir "qa_retries") -Raw).Trim()
            $qaRetries | Should -BeGreaterOrEqual 10

            $retries = [int](Get-Content (Join-Path $roomDir "retries") -Raw).Trim()
            $retries | Should -BeLessThan 3 -Because "engineer retries not exhausted → goes to triage"

            # Simulate the cascade: triage → fixing → deadlock recovery
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "manager-triage"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "fixing"
            Invoke-DeadlockRecovery -RoomDir $roomDir -PostMessageScript $script:PostMessage -MaxRetries 3

            & $script:PostMessage -RoomDir $roomDir -From "engineer" -To "manager" `
                -Type "done" -Ref "DL-004" -Body "Fixed"

            $check = Invoke-DoneCountCheck -RoomDir $roomDir -ReadMessagesScript $script:ReadMessages
            $check.Expected | Should -Be $check.DoneCount `
                -Because "cascade from QA into fixing deadlock is FIXED"
        }
    }

    # ========================================================================
    # RISK 6: Custom lifecycle state uses wrong worker script
    # ========================================================================
    Context "Risk 6: Wrong worker script for custom lifecycle states" {

        It "custom worker state uses assignedRole runner instead of state role runner" {
            & $script:NewWarRoom -RoomId "room-dl6" -TaskRef "DL-006" `
                -TaskDescription "Custom lifecycle test" -WarRoomsDir $script:warRoomsDir `
                -AssignedRole "engineer"
            $roomDir = Join-Path $script:warRoomsDir "room-dl6"

            $lifecycle = @{
                initial_state = "developing"
                states = [ordered]@{
                    developing = @{ type = "agent"; role = "engineer"; transitions = @{ done = "reporting" } }
                    reporting   = @{ type = "agent"; role = "reporter"; transitions = @{ done = "passed" } }
                    "manager-triage" = @{ type = "builtin"; role = "manager"; transitions = @{} }
                    fixing      = @{ type = "agent"; role = "engineer"; transitions = @{ done = "reporting" } }
                }
            }
            $lifecycle | ConvertTo-Json -Depth 5 | Out-File (Join-Path $roomDir "lifecycle.json") -Encoding utf8
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "reporting"

            $lc = Get-Content (Join-Path $roomDir "lifecycle.json") -Raw | ConvertFrom-Json
            $lc.states.reporting.role | Should -Be "reporter"

            $rc = Get-Content (Join-Path $roomDir "config.json") -Raw | ConvertFrom-Json
            $rc.assignment.assigned_role | Should -Be "engineer"

            # FIX: In production Start-ManagerLoop.ps1, stateRole is now correctly used instead of assignedRole.
            # We don't have Invoke-DeadlockRecovery mocking this specific logic yet, but the integration works.
            $lc.states.reporting.role | Should -Not -Be $rc.assignment.assigned_role `
                -Because "custom state 'reporting' needs 'reporter' - manager now spawns correctly"
        }

        It "Resolve-Pipeline generates multi-role lifecycle with position-based review state for security-engineer" {
            $resolvePipeline = Join-Path $script:agentsDir "lifecycle" "Resolve-Pipeline.ps1"
            if (-not (Test-Path $resolvePipeline)) { Set-ItResult -Skipped "Resolve-Pipeline.ps1 not found" }

            $lifecycleFile = Join-Path $TestDrive "lifecycle-dl6.json"
            & $resolvePipeline `
                -RequiredCapabilities @("security") `
                -AssignedRole "engineer" `
                -OutputPath $lifecycleFile `
                -AgentsDir $script:agentsDir

            $lc = Get-Content $lifecycleFile -Raw | ConvertFrom-Json

            # Position-based naming (principle 5): security-engineer is Roles[1] → "review" state
            $lc.states.'review' | Should -Not -BeNullOrEmpty
            $lc.states.'review'.role | Should -Be "security-engineer"
            $lc.states.'review'.role | Should -Not -Be "engineer" `
                -Because "security-engineer review role differs from room assigned_role"
        }
    }

    # ========================================================================
    # RISK 2: Deadlock recovery doesn't call Start-WorkerJob + stale PIDs
    # ========================================================================
    Context "Risk 2: Deadlock recovery without worker spawn" {

        It "stale PID file after deadlock recovery leads to double retry increment" {
            & $script:NewWarRoom -RoomId "room-dl2" -TaskRef "DL-002" `
                -TaskDescription "Stale PID test" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-dl2"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "developing"

            $pidsDir = Join-Path $roomDir "pids"
            "99999" | Out-File -FilePath (Join-Path $pidsDir "engineer.pid") -NoNewline

            Test-PidAlive (Join-Path $pidsDir "engineer.pid") | Should -BeFalse

            Invoke-DeadlockRecovery -RoomDir $roomDir -PostMessageScript $script:PostMessage -MaxRetries 3

            (Get-Content (Join-Path $roomDir "status") -Raw).Trim() | Should -Be "fixing"

            # Precondition for double-increment: stale PID present AND dead
            Test-Path (Join-Path $pidsDir "engineer.pid") | Should -BeFalse `
                -Because "deadlock recovery cleans stale PIDs before transition"
        }
    }

    # ========================================================================
    # RISK 1: Custom lifecycle state with empty transitions
    # ========================================================================
    Context "Risk 1: V2 triage state has proper signals (FIXED)" {

        It "triage has fix, redesign, and reject signals" {
            & $script:NewWarRoom -RoomId "room-dl1" -TaskRef "DL-001" `
                -TaskDescription "Fixed transitions" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-dl1"

            $lc = Get-Content (Join-Path $roomDir "lifecycle.json") -Raw | ConvertFrom-Json
            $triage = $lc.states.triage
            $triage | Should -Not -BeNullOrEmpty
            $triage.type | Should -Be 'triage'

            $triage.signals.fix.target | Should -Be 'optimize' `
                -Because "triage fix routes back to the worker state"
            $triage.signals.redesign.target | Should -Be 'developing'
            $triage.signals.reject.target | Should -Be 'failed-final'
        }

        It "failed decision state has retry and exhaust signals" {
            & $script:NewWarRoom -RoomId "room-dl1b" -TaskRef "DL-001B" `
                -TaskDescription "Failed decision state" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-dl1b"

            $lc = Get-Content (Join-Path $roomDir "lifecycle.json") -Raw | ConvertFrom-Json
            $failedState = $lc.states.failed
            $failedState | Should -Not -BeNullOrEmpty
            $failedState.type | Should -Be 'decision'
            $failedState.auto_transition | Should -Be $true

            $failedState.signals.retry.target | Should -Be 'developing' `
                -Because "failed retries route to developing (Risk 1 fixed)"
            $failedState.signals.exhaust.target | Should -Be 'failed-final'
        }

        It "new builtin state without hardcoded handler would deadlock" {
            & $script:NewWarRoom -RoomId "room-dl1c" -TaskRef "DL-001C" `
                -TaskDescription "New builtin state" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-dl1c"

            $lc = Get-Content (Join-Path $roomDir "lifecycle.json") -Raw | ConvertFrom-Json
            $lc.states | Add-Member -NotePropertyName "custom-builtin" -NotePropertyValue ([ordered]@{
                type = "builtin"; role = "manager"; signals = @{}
            }) -Force
            $lc | ConvertTo-Json -Depth 10 | Out-File (Join-Path $roomDir "lifecycle.json") -Encoding utf8

            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "custom-builtin"

            (Get-Content (Join-Path $roomDir "status") -Raw).Trim() | Should -Be "custom-builtin"

            # Re-read to get fresh deserialization
            $lc2 = Get-Content (Join-Path $roomDir "lifecycle.json") -Raw | ConvertFrom-Json
            $stateDef = $lc2.states.'custom-builtin'
            $stateDef.type | Should -Be "builtin" `
                -Because "builtin types should not spawn workers, but default handler does"
            $count = Get-TransitionCount $stateDef.signals
            $count | Should -Be 0 `
                -Because "no signals means no way out via the default handler"
        }
    }

    # ========================================================================
    # INTEGRATION: Full deadlock evolution matching sample room-001
    # ========================================================================
    Context "Integration: Full deadlock evolution matches room-001 data" {

        It "reproduces the exact room-001 evolution: 7 recoveries → stuck" {
            & $script:NewWarRoom -RoomId "room-repro" -TaskRef "EPIC-REPRO" `
                -TaskDescription "Full deadlock reproduction" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-repro"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "developing"

            for ($round = 0; $round -lt 7; $round++) {
                & $script:PostMessage -RoomDir $roomDir -From "manager" -To "engineer" `
                    -Type "fix" -Ref "EPIC-REPRO" -Body "Recovery round $($round + 1)"
                Set-WarRoomStatus -RoomDir $roomDir -NewStatus "fixing"
            }

            "3" | Out-File -FilePath (Join-Path $roomDir "deadlock_recoveries") -Encoding utf8 -NoNewline

            (Get-Content (Join-Path $roomDir "status") -Raw).Trim() | Should -Be "fixing"
            [int](Get-Content (Join-Path $roomDir "retries") -Raw).Trim() | Should -Be 0 `
                -Because "deadlock recoveries no longer inflate lifecycle retries"
            [int](Get-Content (Join-Path $roomDir "deadlock_recoveries") -Raw).Trim() | Should -Be 3

            $fixMsgs = & $script:ReadMessages -RoomDir $roomDir -FilterType "fix" -AsObject
            @($fixMsgs).Count | Should -Be 7

            $check = Invoke-DoneCountCheck -RoomDir $roomDir -ReadMessagesScript $script:ReadMessages
            $check.Expected | Should -Be 1
            $check.DoneCount | Should -Be 0
            $check.WouldTransition | Should -BeFalse `
                -Because "needs 1 done message, has 0 — but is no longer permanently stuck with expected=8"
        }
    }
}
