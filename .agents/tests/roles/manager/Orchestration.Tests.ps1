# Agent OS — Orchestration Integration Tests
#
# Tests the full communication flow between Manager ↔ Engineer ↔ QA
# through the JSONL channel, verifying state transitions, message protocols,
# and retry/deadlock handling.
#
# These tests do NOT call deepagents — they simulate the message flow
# by directly writing to channels and status files, then verify the manager's
# routing decisions.

BeforeAll {
    $script:agentsDir = (Resolve-Path (Join-Path (Resolve-Path "$PSScriptRoot/../..").Path "..")).Path
    . (Join-Path $script:agentsDir "tests" "TestChannelHelpers.ps1")
    $script:PostMessage = New-TestChannelWriter
    $script:ReadMessages = Join-Path $script:agentsDir "channel" "Read-Messages.ps1"
    $script:NewWarRoom = Join-Path $script:agentsDir "war-rooms" "New-WarRoom.ps1"

    # Import Utils for Set-WarRoomStatus, Test-PidAlive
    $utilsModule = Join-Path $script:agentsDir "lib" "Utils.psm1"
    if (Test-Path $utilsModule) { Import-Module $utilsModule -Force }

    # --- Shared helpers ---

    # Create a room with status and messages pre-populated
    function New-OrcTestRoom {
        param(
            [string]$RoomId,
            [string]$TaskRef = "TASK-001",
            [string]$Description = "Test task",
            [hashtable]$Extra = @{}
        )
        $wd = Join-Path $TestDrive "wr-orch-$(Get-Random)"
        if (-not (Test-Path $wd)) {
            New-Item -ItemType Directory -Path $wd -Force | Out-Null
        }

        $dodParam = if ($Extra.DoD) { $Extra.DoD } else { @("Goal reached") }
        $acParam = if ($Extra.AC) { $Extra.AC } else { @("Criterion met") }

        & $script:NewWarRoom -RoomId $RoomId -TaskRef $TaskRef `
                             -TaskDescription $Description `
                             -WarRoomsDir $wd `
                             -DefinitionOfDone $dodParam `
                             -AcceptanceCriteria $acParam | Out-Null

        $path = Join-Path $wd $RoomId
        return [string]$path
    }
}

AfterAll {
    Remove-Module -Name "Utils" -ErrorAction SilentlyContinue
}

# ═══════════════════════════════════════════════════════════════════════════════
# 1. MESSAGE PROTOCOL — Verify the correct sender/receiver/type for every step
# ═══════════════════════════════════════════════════════════════════════════════

Describe "Message Protocol" {

    Context "Room creation" {
        It "New-WarRoom does not synthesize PowerShell channel messages" {
            $roomDir = New-OrcTestRoom -RoomId "room-proto-01" -TaskRef "TASK-101" `
                                       -Description "Implement login"

            $msgs = @(& $script:ReadMessages -RoomDir $roomDir -AsObject)
            $msgs.Count | Should -Be 0
        }
    }

    Context "Engineer → Manager done message" {
        It "done message has correct from/to/type/ref" {
            $roomDir = New-OrcTestRoom -RoomId "room-proto-02" -TaskRef "TASK-102"

            & $script:PostMessage -RoomDir $roomDir -From "engineer" -To "manager" `
                                  -Type "done" -Ref "TASK-102" -Body "Feature implemented"

            $doneMsgs = @(& $script:ReadMessages -RoomDir $roomDir -FilterType "done" -AsObject)
            $doneMsgs.Count | Should -Be 1
            $doneMsgs[0].from | Should -Be "engineer"
            $doneMsgs[0].to | Should -Be "manager"
            $doneMsgs[0].ref | Should -Be "TASK-102"
        }
    }

    Context "QA → Manager done message" {
        It "done message has correct from/to/type" {
            $roomDir = New-OrcTestRoom -RoomId "room-proto-03" -TaskRef "TASK-103"

            & $script:PostMessage -RoomDir $roomDir -From "qa" -To "manager" `
                                  -Type "done" -Ref "TASK-103" -Body "VERDICT: DONE"

            $doneMsgs = @(& $script:ReadMessages -RoomDir $roomDir -FilterType "done" -AsObject)
            $doneMsgs.Count | Should -Be 1
            $doneMsgs[0].from | Should -Be "qa"
            $doneMsgs[0].to | Should -Be "manager"
        }
    }

    Context "QA → Manager fail message" {
        It "fail message has correct protocol" {
            $roomDir = New-OrcTestRoom -RoomId "room-proto-04" -TaskRef "TASK-104"

            & $script:PostMessage -RoomDir $roomDir -From "qa" -To "manager" `
                                  -Type "fail" -Ref "TASK-104" -Body "VERDICT: FAIL - Missing tests"

            $failMsgs = @(& $script:ReadMessages -RoomDir $roomDir -FilterType "fail" -AsObject)
            $failMsgs.Count | Should -Be 1
            $failMsgs[0].from | Should -Be "qa"
            $failMsgs[0].body | Should -Match "Missing tests"
        }
    }

    Context "Manager → Engineer fix message" {
        It "fix message routes QA feedback to engineer" {
            $roomDir = New-OrcTestRoom -RoomId "room-proto-05" -TaskRef "TASK-105"

            & $script:PostMessage -RoomDir $roomDir -From "manager" -To "engineer" `
                                  -Type "fix" -Ref "TASK-105" -Body "QA says: add validation"

            $fixMsgs = @(& $script:ReadMessages -RoomDir $roomDir -FilterType "fix" -AsObject)
            $fixMsgs.Count | Should -Be 1
            $fixMsgs[0].from | Should -Be "manager"
            $fixMsgs[0].to | Should -Be "engineer"
            $fixMsgs[0].body | Should -Match "add validation"
        }
    }

    Context "Error messages" {
        It "engineer→manager error has correct protocol" {
            $roomDir = New-OrcTestRoom -RoomId "room-proto-06" -TaskRef "TASK-106"

            & $script:PostMessage -RoomDir $roomDir -From "engineer" -To "manager" `
                                  -Type "error" -Ref "TASK-106" -Body "Timeout after 600s"

            $errMsgs = @(& $script:ReadMessages -RoomDir $roomDir -FilterType "error" -AsObject)
            $errMsgs.Count | Should -Be 1
            $errMsgs[0].from | Should -Be "engineer"
        }

        It "qa→manager error has correct protocol" {
            $roomDir = New-OrcTestRoom -RoomId "room-proto-07" -TaskRef "TASK-107"

            & $script:PostMessage -RoomDir $roomDir -From "qa" -To "manager" `
                                  -Type "error" -Ref "TASK-107" -Body "Could not parse verdict"

            $errMsgs = @(& $script:ReadMessages -RoomDir $roomDir -FilterType "error" -AsObject)
            $errMsgs.Count | Should -Be 1
            $errMsgs[0].from | Should -Be "qa"
        }
    }
}

# ═══════════════════════════════════════════════════════════════════════════════
# 2. STATE MACHINE — Manager routing decisions based on channel state
# ═══════════════════════════════════════════════════════════════════════════════

Describe "Manager State Machine — Routing Decisions" {

    Context "pending → developing (team allocation)" {
        It "pending room with active count below max should be picked up" {
            $roomDir = New-OrcTestRoom -RoomId "room-sm-01" -TaskRef "TASK-201"

            $status = (Get-Content (Join-Path $roomDir "status") -Raw).Trim()
            $status | Should -Be "pending"

            # Simulate manager decision: set to developing
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "developing"
            $status = (Get-Content (Join-Path $roomDir "status") -Raw).Trim()
            $status | Should -Be "developing"
        }
    }

    Context "developing → review (done message triggers QA recruitment)" {
        It "done message count ≥ expected triggers QA transition" {
            $roomDir = New-OrcTestRoom -RoomId "room-sm-02" -TaskRef "TASK-202"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "developing"

            # Simulate engineer posting done
            & $script:PostMessage -RoomDir $roomDir -From "engineer" -To "manager" `
                                  -Type "done" -Ref "TASK-202" -Body "Work complete"

            # Manager logic: count done ≥ retries + 1
            $retries = [int](Get-Content (Join-Path $roomDir "retries") -Raw).Trim()
            $expected = $retries + 1
            $doneMsgs = @(& $script:ReadMessages -RoomDir $roomDir -FilterType "done" -AsObject)

            $doneMsgs.Count | Should -BeGreaterOrEqual $expected

            # Transition
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "review"
            $status = (Get-Content (Join-Path $roomDir "status") -Raw).Trim()
            $status | Should -Be "review"
        }

        It "done count less than expected does NOT trigger QA" {
            $roomDir = New-OrcTestRoom -RoomId "room-sm-03" -TaskRef "TASK-203"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "fixing"

            # Increment retries to 1 → needs 2 done messages
            "1" | Out-File -FilePath (Join-Path $roomDir "retries") -NoNewline
            $retries = [int](Get-Content (Join-Path $roomDir "retries") -Raw).Trim()

            # Only 1 done message (from initial task)
            $doneMsgs = @(& $script:ReadMessages -RoomDir $roomDir -FilterType "done" -AsObject)
            $expected = $retries + 1  # 2

            $doneMsgs.Count | Should -BeLessThan $expected
        }
    }

    Context "review → passed (QA DONE verdict)" {
        It "done message triggers passed status" {
            $roomDir = New-OrcTestRoom -RoomId "room-sm-04" -TaskRef "TASK-204"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "review"

            & $script:PostMessage -RoomDir $roomDir -From "qa" -To "manager" `
                                  -Type "done" -Ref "TASK-204" -Body "VERDICT: DONE"

            $doneMsgs = @(& $script:ReadMessages -RoomDir $roomDir -FilterType "done" -AsObject)
            $doneMsgs.Count | Should -BeGreaterThan 0

            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "passed"
            $status = (Get-Content (Join-Path $roomDir "status") -Raw).Trim()
            $status | Should -Be "passed"
        }
    }

    Context "review → fixing (QA FAIL with retries)" {
        It "fail message + retries < max triggers fix cycle" {
            $roomDir = New-OrcTestRoom -RoomId "room-sm-05" -TaskRef "TASK-205"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "review"

            & $script:PostMessage -RoomDir $roomDir -From "qa" -To "manager" `
                                  -Type "fail" -Ref "TASK-205" -Body "Missing input validation"

            $failMsgs = @(& $script:ReadMessages -RoomDir $roomDir -FilterType "fail" -AsObject)
            $failMsgs.Count | Should -BeGreaterThan 0

            $retries = [int](Get-Content (Join-Path $roomDir "retries") -Raw).Trim()
            $maxRetries = 3
            $retries | Should -BeLessThan $maxRetries

            # Manager route: increment retries, post fix, set fixing
            ($retries + 1).ToString() | Out-File -FilePath (Join-Path $roomDir "retries") -NoNewline
            & $script:PostMessage -RoomDir $roomDir -From "manager" -To "engineer" `
                                  -Type "fix" -Ref "TASK-205" -Body $failMsgs[-1].body

            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "fixing"
            $status = (Get-Content (Join-Path $roomDir "status") -Raw).Trim()
            $status | Should -Be "fixing"

            $fixMsgs = @(& $script:ReadMessages -RoomDir $roomDir -FilterType "fix" -AsObject)
            $fixMsgs.Count | Should -BeGreaterOrEqual 1
            $fixMsgs[-1].body | Should -Match "Missing input validation"
        }
    }

    Context "review → failed-final (retries exhausted)" {
        It "fail message + retries ≥ max triggers failed-final" {
            $roomDir = New-OrcTestRoom -RoomId "room-sm-06" -TaskRef "TASK-206"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "review"
            "3" | Out-File -FilePath (Join-Path $roomDir "retries") -NoNewline

            & $script:PostMessage -RoomDir $roomDir -From "qa" -To "manager" `
                                  -Type "fail" -Ref "TASK-206" -Body "Still broken"

            $retries = [int](Get-Content (Join-Path $roomDir "retries") -Raw).Trim()
            $maxRetries = 3
            $retries | Should -BeGreaterOrEqual $maxRetries

            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "failed-final"
            $status = (Get-Content (Join-Path $roomDir "status") -Raw).Trim()
            $status | Should -Be "failed-final"
        }
    }
}

# ═══════════════════════════════════════════════════════════════════════════════
# 3. FULL LIFECYCLE — Happy path + failure scenarios
# ═══════════════════════════════════════════════════════════════════════════════

Describe "Full Room Lifecycle" {

    Context "Happy path: task → done → pass → passed" {
        It "walks through complete lifecycle" {
            $roomDir = New-OrcTestRoom -RoomId "room-life-01" -TaskRef "TASK-301" `
                                       -Description "Build auth system"

            # Step 1: Manager picks up → developing
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "developing"

            # Step 2: Engineer completes → posts done
            & $script:PostMessage -RoomDir $roomDir -From "engineer" -To "manager" `
                                  -Type "done" -Ref "TASK-301" -Body "Auth system implemented with JWT"

            # Step 3: Manager routes to QA → review
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "review"

            # Step 4: QA reviews → posts done
            & $script:PostMessage -RoomDir $roomDir -From "qa" -To "manager" `
                                  -Type "done" -Ref "TASK-301" -Body "VERDICT: DONE - all tests green"

            # Step 5: Manager reads done → status passed
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "passed"

            # VERIFICATION: Full message history
            $allMsgs = @(& $script:ReadMessages -RoomDir $roomDir -AsObject)
            $allMsgs.Count | Should -Be 2  # engineer done + QA done
            ($allMsgs | Where-Object { $_.type -eq "done" }).Count | Should -Be 2
            ($allMsgs | Where-Object { $_.type -eq "pass" }).Count | Should -Be 0

            # VERIFICATION: Status trail
            $audit = Get-Content (Join-Path $roomDir "audit.log")
            $audit.Count | Should -Be 3  # pending→eng, eng→qa, qa→passed
            $audit[-1] | Should -Match "review -> passed"
        }
    }

    Context "Retry path: task → done → fail → fix → done → done" {
        It "walks through fail-retry-done lifecycle" {
            $roomDir = New-OrcTestRoom -RoomId "room-life-02" -TaskRef "TASK-302" `
                                       -Description "Implement API endpoint"

            # Phase 1: First attempt
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "developing"
            & $script:PostMessage -RoomDir $roomDir -From "engineer" -To "manager" `
                                  -Type "done" -Ref "TASK-302" -Body "API endpoint created"

            # Phase 2: QA fails
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "review"
            & $script:PostMessage -RoomDir $roomDir -From "qa" -To "manager" `
                                  -Type "fail" -Ref "TASK-302" -Body "VERDICT: FAIL - No input validation"

            # Phase 3: Manager routes fix
            "1" | Out-File -FilePath (Join-Path $roomDir "retries") -NoNewline
            & $script:PostMessage -RoomDir $roomDir -From "manager" -To "engineer" `
                                  -Type "fix" -Ref "TASK-302" -Body "No input validation"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "fixing"

            # Phase 4: Engineer fixes
            & $script:PostMessage -RoomDir $roomDir -From "engineer" -To "manager" `
                                  -Type "done" -Ref "TASK-302" -Body "Added validation, all tests pass"

            # Phase 5: QA marks done on retry
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "review"
            & $script:PostMessage -RoomDir $roomDir -From "qa" -To "manager" `
                                  -Type "done" -Ref "TASK-302" -Body "VERDICT: DONE"

            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "passed"

            # VERIFICATION
            $allMsgs = @(& $script:ReadMessages -RoomDir $roomDir -AsObject)
            $allMsgs.Count | Should -Be 5  # done + fail + fix + done + done

            ($allMsgs | Where-Object { $_.type -eq "done" }).Count | Should -Be 3
            ($allMsgs | Where-Object { $_.type -eq "fail" }).Count | Should -Be 1
            ($allMsgs | Where-Object { $_.type -eq "fix" }).Count | Should -Be 1
            ($allMsgs | Where-Object { $_.type -eq "pass" }).Count | Should -Be 0

            $retries = [int](Get-Content (Join-Path $roomDir "retries") -Raw).Trim()
            $retries | Should -Be 1

            $audit = Get-Content (Join-Path $roomDir "audit.log")
            ($audit -join "`n") | Should -Match "fixing"
        }
    }

    Context "Max retries exhausted → failed-final" {
        It "fails after max retries" {
            $roomDir = New-OrcTestRoom -RoomId "room-life-03" -TaskRef "TASK-303" `
                                       -Description "Complex feature"
            $maxRetries = 3

            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "developing"

            # Simulate 3 fail cycles
            for ($i = 1; $i -le $maxRetries; $i++) {
                & $script:PostMessage -RoomDir $roomDir -From "engineer" -To "manager" `
                    -Type "done" -Ref "TASK-303" -Body "Attempt $i done"

                Set-WarRoomStatus -RoomDir $roomDir -NewStatus "review"

                & $script:PostMessage -RoomDir $roomDir -From "qa" -To "manager" `
                    -Type "fail" -Ref "TASK-303" -Body "VERDICT: FAIL - Attempt $i still failing"

                $i.ToString() | Out-File -FilePath (Join-Path $roomDir "retries") -NoNewline

                if ($i -lt $maxRetries) {
                    & $script:PostMessage -RoomDir $roomDir -From "manager" -To "engineer" `
                        -Type "fix" -Ref "TASK-303" -Body "Fix attempt $i"
                    Set-WarRoomStatus -RoomDir $roomDir -NewStatus "fixing"
                    Set-WarRoomStatus -RoomDir $roomDir -NewStatus "developing"
                }
            }

            # After max retries → failed-final
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "failed-final"

            $status = (Get-Content (Join-Path $roomDir "status") -Raw).Trim()
            $status | Should -Be "failed-final"

            $retries = [int](Get-Content (Join-Path $roomDir "retries") -Raw).Trim()
            $retries | Should -Be 3

            $failMsgs = @(& $script:ReadMessages -RoomDir $roomDir -FilterType "fail" -AsObject)
            $failMsgs.Count | Should -Be 3
        }
    }
}

# ═══════════════════════════════════════════════════════════════════════════════
# 4. MULTI-ROOM CONCURRENCY — Team allocation
# ═══════════════════════════════════════════════════════════════════════════════

Describe "Multi-Room Team Allocation" {

    Context "Concurrent room management" {
        It "creates multiple rooms from a single plan scope" {
            $wd = Join-Path $TestDrive "wr-multi-$(Get-Random)"
            New-Item -ItemType Directory -Path $wd -Force | Out-Null

            # Create 3 rooms (simulating Start-Plan behavior)
            & $script:NewWarRoom -RoomId "room-001" -TaskRef "EPIC-001" `
                -TaskDescription "Auth system" -WarRoomsDir $wd | Out-Null
            & $script:NewWarRoom -RoomId "room-002" -TaskRef "TASK-001" `
                -TaskDescription "Login page" -WarRoomsDir $wd | Out-Null
            & $script:NewWarRoom -RoomId "room-003" -TaskRef "TASK-002" `
                -TaskDescription "Dashboard" -WarRoomsDir $wd | Out-Null

            $rooms = Get-ChildItem $wd -Directory -Filter "room-*"
            $rooms.Count | Should -Be 3

            # All start as pending
            foreach ($r in $rooms) {
                $s = (Get-Content (Join-Path $r.FullName "status") -Raw).Trim()
                $s | Should -Be "pending"
            }
        }

        It "count active rooms correctly for concurrency control" {
            $wd = Join-Path $TestDrive "wr-active-$(Get-Random)"
            New-Item -ItemType Directory -Path $wd -Force | Out-Null

            & $script:NewWarRoom -RoomId "room-a01" -TaskRef "TASK-A01" `
                -TaskDescription "A" -WarRoomsDir $wd | Out-Null
            & $script:NewWarRoom -RoomId "room-a02" -TaskRef "TASK-A02" `
                -TaskDescription "B" -WarRoomsDir $wd | Out-Null
            & $script:NewWarRoom -RoomId "room-a03" -TaskRef "TASK-A03" `
                -TaskDescription "C" -WarRoomsDir $wd | Out-Null

            # Set different statuses
            Set-WarRoomStatus -RoomDir (Join-Path $wd "room-a01") -NewStatus "developing"
            Set-WarRoomStatus -RoomDir (Join-Path $wd "room-a02") -NewStatus "review"
            # room-a03 stays pending

            # Count active (developing, review, fixing)
            $activeCount = 0
            Get-ChildItem $wd -Directory -Filter "room-*" | ForEach-Object {
                $s = (Get-Content (Join-Path $_.FullName "status") -Raw).Trim()
                if ($s -in @('developing', 'review', 'fixing')) { $activeCount++ }
            }
            $activeCount | Should -Be 2
        }

        It "detects all-passed for release gate" {
            $wd = Join-Path $TestDrive "wr-release-$(Get-Random)"
            New-Item -ItemType Directory -Path $wd -Force | Out-Null

            & $script:NewWarRoom -RoomId "room-r01" -TaskRef "TASK-R01" `
                -TaskDescription "A" -WarRoomsDir $wd | Out-Null
            & $script:NewWarRoom -RoomId "room-r02" -TaskRef "TASK-R02" `
                -TaskDescription "B" -WarRoomsDir $wd | Out-Null

            Set-WarRoomStatus -RoomDir (Join-Path $wd "room-r01") -NewStatus "passed"
            Set-WarRoomStatus -RoomDir (Join-Path $wd "room-r02") -NewStatus "passed"

            $allPassed = $true
            Get-ChildItem $wd -Directory -Filter "room-*" | ForEach-Object {
                $s = (Get-Content (Join-Path $_.FullName "status") -Raw).Trim()
                if ($s -notin @('passed')) { $allPassed = $false }
            }
            $allPassed | Should -BeTrue
        }

        It "detects NOT all-passed when one room is failed-final" {
            $wd = Join-Path $TestDrive "wr-notall-$(Get-Random)"
            New-Item -ItemType Directory -Path $wd -Force | Out-Null

            & $script:NewWarRoom -RoomId "room-n01" -TaskRef "TASK-N01" `
                -TaskDescription "A" -WarRoomsDir $wd | Out-Null
            & $script:NewWarRoom -RoomId "room-n02" -TaskRef "TASK-N02" `
                -TaskDescription "B" -WarRoomsDir $wd | Out-Null

            Set-WarRoomStatus -RoomDir (Join-Path $wd "room-n01") -NewStatus "passed"
            Set-WarRoomStatus -RoomDir (Join-Path $wd "room-n02") -NewStatus "failed-final"

            $allPassed = $true
            Get-ChildItem $wd -Directory -Filter "room-*" | ForEach-Object {
                $s = (Get-Content (Join-Path $_.FullName "status") -Raw).Trim()
                if ($s -notin @('passed')) { $allPassed = $false }
            }
            $allPassed | Should -BeFalse
        }
    }
}

# ═══════════════════════════════════════════════════════════════════════════════
# 5. DONE-COUNT GATE — The key routing trigger
# ═══════════════════════════════════════════════════════════════════════════════

Describe "Done-Count Gate Logic" {

    Context "First attempt (retries=0, expects done≥1)" {
        It "routes to QA on first done message" {
            $roomDir = New-OrcTestRoom -RoomId "room-gate-01" -TaskRef "TASK-G01"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "developing"

            $retries = [int](Get-Content (Join-Path $roomDir "retries") -Raw).Trim()
            $retries | Should -Be 0

            & $script:PostMessage -RoomDir $roomDir -From "engineer" -To "manager" `
                -Type "done" -Ref "TASK-G01" -Body "First attempt"

            $doneMsgs = @(& $script:ReadMessages -RoomDir $roomDir -FilterType "done" -AsObject)
            $expected = $retries + 1
            ($doneMsgs.Count -ge $expected) | Should -BeTrue
        }
    }

    Context "Second attempt (retries=1, expects done≥2)" {
        It "waits for 2 done messages on retry" {
            $roomDir = New-OrcTestRoom -RoomId "room-gate-02" -TaskRef "TASK-G02"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "fixing"
            "1" | Out-File -FilePath (Join-Path $roomDir "retries") -NoNewline

            # Only 1 done message — NOT enough
            & $script:PostMessage -RoomDir $roomDir -From "engineer" -To "manager" `
                -Type "done" -Ref "TASK-G02" -Body "First attempt"

            $retries = [int](Get-Content (Join-Path $roomDir "retries") -Raw).Trim()
            $doneMsgs = @(& $script:ReadMessages -RoomDir $roomDir -FilterType "done" -AsObject)
            ($doneMsgs.Count -ge ($retries + 1)) | Should -BeFalse

            # Add 2nd done message — NOW enough
            & $script:PostMessage -RoomDir $roomDir -From "engineer" -To "manager" `
                -Type "done" -Ref "TASK-G02" -Body "Second attempt"

            $doneMsgs = @(& $script:ReadMessages -RoomDir $roomDir -FilterType "done" -AsObject)
            ($doneMsgs.Count -ge ($retries + 1)) | Should -BeTrue
        }
    }
}

# ═══════════════════════════════════════════════════════════════════════════════
# 6. STATE TIMEOUT DETECTION
# ═══════════════════════════════════════════════════════════════════════════════

Describe "State Timeout Detection" {

    Context "state_changed_at file mechanics" {
        It "Set-WarRoomStatus writes state_changed_at epoch" {
            $roomDir = New-OrcTestRoom -RoomId "room-to-01" -TaskRef "TASK-TO1"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "developing"

            $changedFile = Join-Path $roomDir "state_changed_at"
            Test-Path $changedFile | Should -BeTrue

            $epoch = [int](Get-Content $changedFile -Raw).Trim()
            $now = [int][double]::Parse((Get-Date -UFormat %s))
            ($now - $epoch) | Should -BeLessThan 10  # Should be within last 10 seconds
        }

        It "detects timeout when state_changed_at is old" {
            $roomDir = New-OrcTestRoom -RoomId "room-to-02" -TaskRef "TASK-TO2"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "developing"

            # Backdate state_changed_at by 1000 seconds
            $oldEpoch = [int][double]::Parse((Get-Date -UFormat %s)) - 1000
            $oldEpoch.ToString() | Out-File -FilePath (Join-Path $roomDir "state_changed_at") -NoNewline

            $changedAt = [int](Get-Content (Join-Path $roomDir "state_changed_at") -Raw).Trim()
            $now = [int][double]::Parse((Get-Date -UFormat %s))
            $elapsed = $now - $changedAt
            $elapsed | Should -BeGreaterThan 900  # Default timeout
        }

        It "does NOT detect timeout for fresh state" {
            $roomDir = New-OrcTestRoom -RoomId "room-to-03" -TaskRef "TASK-TO3"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "developing"

            $changedAt = [int](Get-Content (Join-Path $roomDir "state_changed_at") -Raw).Trim()
            $now = [int][double]::Parse((Get-Date -UFormat %s))
            $elapsed = $now - $changedAt
            $elapsed | Should -BeLessThan 900
        }
    }
}

# ═══════════════════════════════════════════════════════════════════════════════
# 7. DEADLOCK DETECTION — Stall cycle mechanics
# ═══════════════════════════════════════════════════════════════════════════════

Describe "Deadlock Detection" {

    Context "Stall cycle counting" {
        It "identifies all-active-no-PID condition" {
            $wd = Join-Path $TestDrive "wr-deadlock-$(Get-Random)"
            New-Item -ItemType Directory -Path $wd -Force | Out-Null

            & $script:NewWarRoom -RoomId "room-dl-01" -TaskRef "TASK-DL1" `
                -TaskDescription "A" -WarRoomsDir $wd | Out-Null
            & $script:NewWarRoom -RoomId "room-dl-02" -TaskRef "TASK-DL2" `
                -TaskDescription "B" -WarRoomsDir $wd | Out-Null

            Set-WarRoomStatus -RoomDir (Join-Path $wd "room-dl-01") -NewStatus "developing"
            Set-WarRoomStatus -RoomDir (Join-Path $wd "room-dl-02") -NewStatus "fixing"

            # Count active rooms and check PIDs
            $totalActive = 0
            $activeWithNoPid = 0

            Get-ChildItem $wd -Directory -Filter "room-*" | ForEach-Object {
                $rd = $_.FullName
                $s = (Get-Content (Join-Path $rd "status") -Raw).Trim()
                if ($s -in @('developing', 'review', 'fixing')) {
                    $totalActive++
                    # No PID files exist → no agent running
                    $pidDir = Join-Path $rd "pids"
                    $pidFiles = Get-ChildItem $pidDir -Filter "*.pid" -ErrorAction SilentlyContinue
                    if (-not $pidFiles -or $pidFiles.Count -eq 0) {
                        $activeWithNoPid++
                    }
                }
            }

            $totalActive | Should -Be 2
            $activeWithNoPid | Should -Be 2  # All active, no PIDs = deadlock condition
            ($totalActive -gt 0 -and $activeWithNoPid -eq $totalActive) | Should -BeTrue
        }

        It "does NOT detect deadlock when PIDs are alive" {
            $wd = Join-Path $TestDrive "wr-nodeadlock-$(Get-Random)"
            New-Item -ItemType Directory -Path $wd -Force | Out-Null

            & $script:NewWarRoom -RoomId "room-ndl-01" -TaskRef "TASK-NDL1" `
                -TaskDescription "A" -WarRoomsDir $wd | Out-Null

            Set-WarRoomStatus -RoomDir (Join-Path $wd "room-ndl-01") -NewStatus "developing"

            # Write a PID file (use current PID so it's alive)
            $PID.ToString() | Out-File -FilePath (Join-Path $wd "room-ndl-01" "pids" "engineer.pid") -NoNewline

            $pidDir = Join-Path $wd "room-ndl-01" "pids"
            $pidFiles = @(Get-ChildItem $pidDir -Filter "*.pid" -ErrorAction SilentlyContinue)
            $pidFiles.Count | Should -BeGreaterThan 0
        }
    }
}

# ═══════════════════════════════════════════════════════════════════════════════
# 8. CONFIG.JSON GOAL CONTRACT — Verified throughout lifecycle
# ═══════════════════════════════════════════════════════════════════════════════

Describe "Goal Contract Propagation" {

    Context "Goals flow from plan to room config" {
        It "config.json contains DoD from room creation" {
            $roomDir = New-OrcTestRoom -RoomId "room-gc-01" -TaskRef "EPIC-GC1" `
                -Extra @{
                    DoD = @("JWT authentication working", "Tests pass with 80% coverage")
                    AC  = @("POST /login returns 200", "Protected routes reject bad tokens")
                }

            $config = Get-Content (Join-Path $roomDir "config.json") -Raw | ConvertFrom-Json
            $config.goals.definition_of_done.Count | Should -Be 2
            $config.goals.definition_of_done[0] | Should -Match "JWT"
            $config.goals.acceptance_criteria.Count | Should -Be 2
            $config.goals.acceptance_criteria[0] | Should -Match "POST /login"
        }

        It "goal contract includes quality requirements" {
            $roomDir = New-OrcTestRoom -RoomId "room-gc-02" -TaskRef "TASK-GC2"

            $config = Get-Content (Join-Path $roomDir "config.json") -Raw | ConvertFrom-Json
            $config.goals.quality_requirements.test_coverage_min | Should -Be 80
            $config.goals.quality_requirements.lint_clean | Should -BeTrue
            $config.goals.quality_requirements.security_scan_pass | Should -BeTrue
        }

        It "Epic detection in config" {
            $roomDir = New-OrcTestRoom -RoomId "room-gc-03" -TaskRef "EPIC-100" `
                                       -Description "Big epic feature"

            $config = Get-Content (Join-Path $roomDir "config.json") -Raw | ConvertFrom-Json
            $config.assignment.type | Should -Be "epic"
        }

        It "Task detection in config" {
            $roomDir = New-OrcTestRoom -RoomId "room-gc-04" -TaskRef "TASK-100" `
                                       -Description "Small task"

            $config = Get-Content (Join-Path $roomDir "config.json") -Raw | ConvertFrom-Json
            $config.assignment.type | Should -Be "task"
        }
    }
}

# ═══════════════════════════════════════════════════════════════════════════════
# 9. AUDIT TRAIL — Complete history verification
# ═══════════════════════════════════════════════════════════════════════════════

Describe "Audit Trail" {

    Context "Full lifecycle audit" {
        It "records every status transition with timestamp" {
            $roomDir = New-OrcTestRoom -RoomId "room-audit-01" -TaskRef "TASK-AUD"

            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "developing"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "review"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "fixing"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "developing"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "review"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "passed"

            $audit = @(Get-Content (Join-Path $roomDir "audit.log"))
            $audit.Count | Should -Be 6

            # Verify ordering
            $audit[0] | Should -Match "pending -> developing"
            $audit[1] | Should -Match "developing -> review"
            $audit[2] | Should -Match "review -> fixing"
            $audit[3] | Should -Match "fixing -> developing"
            $audit[4] | Should -Match "developing -> review"
            $audit[5] | Should -Match "review -> passed"

            # Verify timestamps
            foreach ($line in $audit) {
                $line | Should -Match "\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
            }
        }
    }

    Context "Channel message history" {
        It "preserves complete message ordering" {
            $roomDir = New-OrcTestRoom -RoomId "room-audit-02" -TaskRef "TASK-AUD2"

            # Simulate full lifecycle messages
            Start-Sleep -Milliseconds 10
            & $script:PostMessage -RoomDir $roomDir -From "engineer" -To "manager" `
                -Type "done" -Ref "TASK-AUD2" -Body "Done"
            Start-Sleep -Milliseconds 10
            & $script:PostMessage -RoomDir $roomDir -From "qa" -To "manager" `
                -Type "fail" -Ref "TASK-AUD2" -Body "VERDICT: FAIL"
            Start-Sleep -Milliseconds 10
            & $script:PostMessage -RoomDir $roomDir -From "manager" -To "engineer" `
                -Type "fix" -Ref "TASK-AUD2" -Body "Fix the bug"
            Start-Sleep -Milliseconds 10
            & $script:PostMessage -RoomDir $roomDir -From "engineer" -To "manager" `
                -Type "done" -Ref "TASK-AUD2" -Body "Fixed"
            Start-Sleep -Milliseconds 10
            & $script:PostMessage -RoomDir $roomDir -From "qa" -To "manager" `
                -Type "done" -Ref "TASK-AUD2" -Body "VERDICT: DONE"

            $allMsgs = @(& $script:ReadMessages -RoomDir $roomDir -AsObject)
            $allMsgs.Count | Should -Be 5  # done + fail + fix + done + done

            # Verify ordering by type sequence
            $types = $allMsgs | ForEach-Object { $_.type }
            $types[0] | Should -Be "done"
            $types[1] | Should -Be "fail"
            $types[2] | Should -Be "fix"
            $types[3] | Should -Be "done"
            $types[4] | Should -Be "done"
        }
    }
}
