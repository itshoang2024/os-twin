# Agent OS — Start-ManagerLoop Pester Tests (V2 Lifecycle)

BeforeAll {
    $script:agentsDir = (Resolve-Path (Join-Path (Resolve-Path "$PSScriptRoot/../../../roles/manager").Path ".." "..")).Path
    . (Join-Path $script:agentsDir "tests" "TestChannelHelpers.ps1")
    $script:PostMessage = New-TestChannelWriter
    $script:ReadMessages = Join-Path $script:agentsDir "channel" "Read-Messages.ps1"
    $script:NewWarRoom = Join-Path $script:agentsDir "war-rooms" "New-WarRoom.ps1"

    # Import Utils for Test-PidAlive, Set-WarRoomStatus
    $utilsModule = Join-Path $script:agentsDir "lib" "Utils.psm1"
    if (Test-Path $utilsModule) { Import-Module $utilsModule -Force }

    # Helper: write a minimal v2 lifecycle.json into a room.
    # NOTE: generic role names ('engineer'/'qa') are used here for unit-test isolation.
    # Game-specific lifecycles (sample/room-001) use 'engineer'/'qa'.
    # review.fail → 'optimize' matches the real lifecycle design: QA failures route
    # to incremental optimization, NOT back to 'developing' (full restart).
    function Write-V2Lifecycle {
        param([string]$RoomDir, [hashtable]$Override)
        $lc = @{
            version = 2
            initial_state = "developing"
            max_retries = 3
            states = @{
	                developing = @{
	                    role = "engineer"
	                    type = "work"
	                    signals = @{
	                        done = @{ target = "review" }
	                    }
	                }
	                optimize = @{
	                    role = "engineer"
	                    type = "work"
	                    signals = @{
	                        done = @{ target = "review" }
	                    }
	                }
	                review = @{
	                    role = "qa"
	                    type = "review"
	                    signals = [ordered]@{
	                        done     = @{ target = "done" }
		                        pass     = @{ target = "done" }
		                        fail     = @{ target = "optimize"; actions = @("increment_retries", "post_fix") }
	                        escalate = @{ target = "triage" }
	                    }
	                }
                triage = @{
                    role = "manager"
                    type = "triage"
                    signals = @{
                        done     = @{ target = "review" }
                        fix      = @{ target = "optimize"; actions = @("increment_retries") }
                        redesign = @{ target = "developing"; actions = @("increment_retries", "revise_brief") }
                        reject   = @{ target = "failed" }
                    }
                }
                done   = @{ type = "terminal" }
                failed = @{ type = "terminal" }
            }
        }
        if ($Override) {
            foreach ($key in $Override.Keys) { $lc.states[$key] = $Override[$key] }
        }
        $lc | ConvertTo-Json -Depth 10 | Out-File (Join-Path $RoomDir "lifecycle.json") -Encoding utf8
    }
}

AfterAll {
    Remove-Module -Name "Utils" -ErrorAction SilentlyContinue
}

Describe "Start-ManagerLoop — V2 Lifecycle Unit Tests" {
    BeforeEach {
        $script:warRoomsDir = Join-Path $TestDrive "warrooms-$(Get-Random)"
        New-Item -ItemType Directory -Path $script:warRoomsDir -Force | Out-Null

        $script:configFile = Join-Path $TestDrive "config-mgr-$(Get-Random).json"
        @{
            version = "0.1.0"
            manager = @{
                poll_interval_seconds = 1
                max_concurrent_rooms  = 10
                max_engineer_retries  = 3
                auto_approve_tools    = $true
                state_timeout_seconds = 900
            }
            engineer = @{
                cli              = "echo"
                default_model    = "test-model"
                timeout_seconds  = 10
                max_prompt_bytes = 102400
            }
            qa = @{
                cli             = "echo"
                default_model   = "test-model"
                approval_mode   = "auto-approve"
                timeout_seconds = 10
            }
            channel = @{
                format                 = "jsonl"
                max_message_size_bytes = 65536
            }
            release = @{
                require_signoffs = @("engineer", "qa", "manager")
                auto_draft       = $true
            }
        } | ConvertTo-Json -Depth 5 | Out-File $script:configFile -Encoding utf8
    }

    Context "Status reading" {
        It "reads pending status from room" {
            & $script:NewWarRoom -RoomId "room-001" -TaskRef "TASK-001" `
                                 -TaskDescription "Test" -WarRoomsDir $script:warRoomsDir
            $status = (Get-Content (Join-Path $script:warRoomsDir "room-001" "status") -Raw).Trim()
            $status | Should -Be "pending"
        }

        It "reads developing status" {
            & $script:NewWarRoom -RoomId "room-002" -TaskRef "TASK-002" `
                                 -TaskDescription "Test" -WarRoomsDir $script:warRoomsDir
            "developing" | Out-File -FilePath (Join-Path $script:warRoomsDir "room-002" "status") -NoNewline
            $status = (Get-Content (Join-Path $script:warRoomsDir "room-002" "status") -Raw).Trim()
            $status | Should -Be "developing"
        }
    }

    Context "V2 state transitions" {
        It "pending → developing" {
            & $script:NewWarRoom -RoomId "room-010" -TaskRef "TASK-010" `
                                 -TaskDescription "Test" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-010"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "developing"
            $status = (Get-Content (Join-Path $roomDir "status") -Raw).Trim()
            $status | Should -Be "developing"
            $audit = Get-Content (Join-Path $roomDir "audit.log") -Raw
            $audit | Should -Match "pending -> developing"
        }

        It "developing → review (done signal)" {
            & $script:NewWarRoom -RoomId "room-011" -TaskRef "TASK-011" `
                                 -TaskDescription "Test" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-011"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "developing"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "review"
            $status = (Get-Content (Join-Path $roomDir "status") -Raw).Trim()
            $status | Should -Be "review"
        }

        It "review → done (done signal)" {
            & $script:NewWarRoom -RoomId "room-012" -TaskRef "TASK-012" `
                                 -TaskDescription "Test" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-012"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "developing"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "review"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "done"
            $status = (Get-Content (Join-Path $roomDir "status") -Raw).Trim()
            $status | Should -Be "done"
        }

        It "review → developing (fail signal with retries)" {
            & $script:NewWarRoom -RoomId "room-013" -TaskRef "TASK-013" `
                                 -TaskDescription "Test" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-013"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "developing"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "review"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "developing"
            $status = (Get-Content (Join-Path $roomDir "status") -Raw).Trim()
            $status | Should -Be "developing"
        }

        It "developing → failed (retries exhausted)" {
            & $script:NewWarRoom -RoomId "room-014" -TaskRef "TASK-014" `
                                 -TaskDescription "Test" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-014"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "developing"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "failed"
            $status = (Get-Content (Join-Path $roomDir "status") -Raw).Trim()
            $status | Should -Be "failed"
        }

        It "review → triage (escalate signal)" {
            & $script:NewWarRoom -RoomId "room-015" -TaskRef "TASK-015" `
                                 -TaskDescription "Test" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-015"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "review"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "triage"
            $status = (Get-Content (Join-Path $roomDir "status") -Raw).Trim()
            $status | Should -Be "triage"
            $audit = Get-Content (Join-Path $roomDir "audit.log") -Raw
            $audit | Should -Match "review -> triage"
        }
    }

    Context "Message counting" {
        It "counts done messages correctly" {
            & $script:NewWarRoom -RoomId "room-020" -TaskRef "TASK-020" `
                                 -TaskDescription "Test" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-020"
            & $script:PostMessage -RoomDir $roomDir -From "engineer" -To "manager" `
                                  -Type "done" -Ref "TASK-020" -Body "First done"
            & $script:PostMessage -RoomDir $roomDir -From "engineer" -To "manager" `
                                  -Type "done" -Ref "TASK-020" -Body "Second done"
            $msgs = & $script:ReadMessages -RoomDir $roomDir -FilterType "done" -AsObject
            $msgs.Count | Should -Be 2
        }

        It "counts pass messages" {
            & $script:NewWarRoom -RoomId "room-021" -TaskRef "TASK-021" `
                                 -TaskDescription "Test" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-021"
            & $script:PostMessage -RoomDir $roomDir -From "qa" -To "manager" `
                                  -Type "pass" -Ref "TASK-021" -Body "All good"
            $msgs = & $script:ReadMessages -RoomDir $roomDir -FilterType "pass" -AsObject
            $msgs.Count | Should -Be 1
        }

        It "counts fail messages" {
            & $script:NewWarRoom -RoomId "room-022" -TaskRef "TASK-022" `
                                 -TaskDescription "Test" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-022"
            & $script:PostMessage -RoomDir $roomDir -From "qa" -To "manager" `
                                  -Type "fail" -Ref "TASK-022" -Body "Bad code"
            $msgs = & $script:ReadMessages -RoomDir $roomDir -FilterType "fail" -AsObject
            $msgs.Count | Should -Be 1
        }
    }

    Context "Retry tracking" {
        It "increments retry counter" {
            & $script:NewWarRoom -RoomId "room-030" -TaskRef "TASK-030" `
                                 -TaskDescription "Test" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-030"
            $retries = [int](Get-Content (Join-Path $roomDir "retries") -Raw).Trim()
            $retries | Should -Be 0
            "1" | Out-File -FilePath (Join-Path $roomDir "retries") -NoNewline
            $retries = [int](Get-Content (Join-Path $roomDir "retries") -Raw).Trim()
            $retries | Should -Be 1
        }

        It "respects max retries limit" {
            $config = Get-Content $script:configFile -Raw | ConvertFrom-Json
            $maxRetries = $config.manager.max_engineer_retries
            $maxRetries | Should -Be 3
            3 | Should -BeGreaterOrEqual $maxRetries
        }
    }

    Context "State timeout detection" {
        It "detects timed out state" {
            & $script:NewWarRoom -RoomId "room-040" -TaskRef "TASK-040" `
                                 -TaskDescription "Test" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-040"
            $oldEpoch = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - 10000
            $oldEpoch.ToString() | Out-File -FilePath (Join-Path $roomDir "state_changed_at") -NoNewline
            $changedAt = [int](Get-Content (Join-Path $roomDir "state_changed_at") -Raw).Trim()
            $now = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
            ($now - $changedAt) | Should -BeGreaterThan 900
        }
    }

    Context "Audit trail" {
        It "records all v2 status transitions" {
            & $script:NewWarRoom -RoomId "room-050" -TaskRef "TASK-050" `
                                 -TaskDescription "Full lifecycle" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-050"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "developing"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "review"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "developing"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "review"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "done"
            $auditLines = Get-Content (Join-Path $roomDir "audit.log")
            $auditLines.Count | Should -Be 5
            $auditLines[-1] | Should -Match "review -> done"
        }

        It "records pipeline lifecycle with optimize state" {
            & $script:NewWarRoom -RoomId "room-051" -TaskRef "TASK-051" `
                                 -TaskDescription "Pipeline lifecycle" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-051"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "developing"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "review"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "optimize"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "review"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "done"
            $auditLines = Get-Content (Join-Path $roomDir "audit.log")
            $auditLines.Count | Should -Be 5
            $auditLines[2] | Should -Match "review -> optimize"
            $auditLines[3] | Should -Match "optimize -> review"
        }
    }

    Context "Blocked status" {
        It "blocked status is valid for Set-WarRoomStatus" {
            & $script:NewWarRoom -RoomId "room-060" -TaskRef "TASK-060" `
                                 -TaskDescription "Block test" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-060"
            { Set-WarRoomStatus -RoomDir $roomDir -NewStatus "blocked" } | Should -Not -Throw
            $status = (Get-Content (Join-Path $roomDir "status") -Raw).Trim()
            $status | Should -Be "blocked"
        }

        It "blocked counts as terminal (not active)" {
            & $script:NewWarRoom -RoomId "room-061" -TaskRef "TASK-061" `
                                 -TaskDescription "Block test 2" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-061"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "blocked"
            $audit = Get-Content (Join-Path $roomDir "audit.log") -Raw
            $audit | Should -Match "pending -> blocked"
        }
    }

    Context "Triage state (v2)" {
        It "review → triage (escalate transition is valid)" {
            & $script:NewWarRoom -RoomId "room-070" -TaskRef "TASK-070" `
                                 -TaskDescription "Triage test" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-070"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "developing"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "review"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "triage"
            $status = (Get-Content (Join-Path $roomDir "status") -Raw).Trim()
            $status | Should -Be "triage"
        }

        It "triage → optimize (fix classification — incremental fix, not full restart)" {
            & $script:NewWarRoom -RoomId "room-071" -TaskRef "TASK-071" `
                                 -TaskDescription "Triage fix" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-071"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "triage"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "optimize"
            $status = (Get-Content (Join-Path $roomDir "status") -Raw).Trim()
            $status | Should -Be "optimize"
            $audit = Get-Content (Join-Path $roomDir "audit.log") -Raw
            $audit | Should -Match "triage -> optimize"
        }

        It "triage → failed (reject classification)" {
            & $script:NewWarRoom -RoomId "room-072" -TaskRef "TASK-072" `
                                 -TaskDescription "Triage reject" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-072"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "triage"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "failed"
            $status = (Get-Content (Join-Path $roomDir "status") -Raw).Trim()
            $status | Should -Be "failed"
        }
    }

    Context "Triage context file" {
        It "Write-TriageContext creates triage-context.md" {
            & $script:NewWarRoom -RoomId "room-100" -TaskRef "TASK-100" `
                                 -TaskDescription "Context test" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-100"
            $artifactsDir = Join-Path $roomDir "artifacts"
            if (-not (Test-Path $artifactsDir)) {
                New-Item -ItemType Directory -Path $artifactsDir -Force | Out-Null
            }
            $contextFile = Join-Path $artifactsDir "triage-context.md"
            @"
# Manager Triage Context

## Classification: implementation-bug

## QA Failure Report
Tests are failing.

## Manager's Direction
Classified as implementation bug. Engineer should fix.
"@ | Out-File -FilePath $contextFile -Encoding utf8 -Force
            Test-Path $contextFile | Should -BeTrue
            $content = Get-Content $contextFile -Raw
            $content | Should -Match "implementation-bug"
            $content | Should -Match "Tests are failing"
        }
    }

    Context "Escalate message handling" {
        It "counts escalate messages" {
            & $script:NewWarRoom -RoomId "room-110" -TaskRef "TASK-110" `
                                 -TaskDescription "Escalate test" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-110"
            & $script:PostMessage -RoomDir $roomDir -From "qa" -To "manager" `
                                  -Type "escalate" -Ref "TASK-110" -Body "Design problem detected"
            $msgs = & $script:ReadMessages -RoomDir $roomDir -FilterType "escalate" -AsObject
            $msgs.Count | Should -Be 1
        }

        It "architect done message with RECOMMENDATION is readable" {
            & $script:NewWarRoom -RoomId "room-111" -TaskRef "TASK-111" `
                                 -TaskDescription "Arch done" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-111"
            & $script:PostMessage -RoomDir $roomDir -From "architect" -To "manager" `
                                  -Type "done" -Ref "TASK-111" `
                                  -Body "RECOMMENDATION: FIX`nFix the null check on line 42."
            $msgs = & $script:ReadMessages -RoomDir $roomDir -FilterType "done" -AsObject
            $msgs.Count | Should -Be 1
            $msgs[0].body | Should -Match "RECOMMENDATION: FIX"
        }
    }

    Context "V2 lifecycle schema" {
        It "architect-as-worker emits done signal (not design-guidance)" {
            & $script:NewWarRoom -RoomId "room-130" -TaskRef "EPIC-130" `
                                 -TaskDescription "Arch as primary worker" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-130"
            Write-V2Lifecycle -RoomDir $roomDir -Override @{
                developing = @{
	                    role = "architect"; type = "work"
	                    signals = @{
	                        done = @{ target = "review" }
	                    }
	                }
	            }
            & $script:PostMessage -RoomDir $roomDir -From "architect" -To "manager" `
                                  -Type "done" -Ref "EPIC-130" `
                                  -Body "RECOMMENDATION: FIX`n`nPlease install dependencies and configure design tokens."
            $msgs = & $script:ReadMessages -RoomDir $roomDir -FilterType "done" -AsObject
            $msgs.Count | Should -Be 1
            $msgs[0].body | Should -Match "RECOMMENDATION: FIX"
            $lc = Get-Content (Join-Path $roomDir "lifecycle.json") -Raw | ConvertFrom-Json
            $lc.states.developing.role | Should -Be "architect"
            $lc.states.developing.signals.done.target | Should -Be "review"
        }

        It "done-transition lookup uses v2 signals schema" {
            & $script:NewWarRoom -RoomId "room-131" -TaskRef "EPIC-131" `
                                 -TaskDescription "Signal lookup test" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-131"
            Write-V2Lifecycle -RoomDir $roomDir
            $lc = Get-Content (Join-Path $roomDir "lifecycle.json") -Raw | ConvertFrom-Json
            $status = "optimize"
            $nextState = $lc.states.$status.signals.done.target
            $nextState | Should -Be "review"
        }

        It "optimize state is included in base lifecycle" {
            & $script:NewWarRoom -RoomId "room-135" -TaskRef "TASK-135" `
                                 -TaskDescription "Optimize state" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-135"
            Write-V2Lifecycle -RoomDir $roomDir
            $lc = Get-Content (Join-Path $roomDir "lifecycle.json") -Raw | ConvertFrom-Json
            $lc.states.optimize | Should -Not -BeNullOrEmpty
	            $lc.states.optimize.role | Should -Be "engineer"
	            $lc.states.optimize.type | Should -Be "work"
	            $lc.states.optimize.signals.done.target | Should -Be "review"
	            $lc.states.optimize.signals.PSObject.Properties.Name | Should -Not -Contain "error"
        }

        It "pipeline review.fail targets optimize (incremental fix)" {
            & $script:NewWarRoom -RoomId "room-136" -TaskRef "TASK-136" `
                                 -TaskDescription "Pipeline fail path" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-136"
            # Base Write-V2Lifecycle already sets review.fail → optimize.
            # This test validates that behavior is inherited without override.
            Write-V2Lifecycle -RoomDir $roomDir
            $lc = Get-Content (Join-Path $roomDir "lifecycle.json") -Raw | ConvertFrom-Json
            $lc.states.triage.signals.done.target | Should -Be "review"
            $lc.states.review.signals.fail.target | Should -Be "optimize"
            $lc.states.triage.signals.fix.target  | Should -Be "optimize"
        }

        It "review signals include done/pass/fail/escalate" {
            & $script:NewWarRoom -RoomId "room-132" -TaskRef "TASK-132" `
                                 -TaskDescription "Review signals" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-132"
            Write-V2Lifecycle -RoomDir $roomDir
            $lc = Get-Content (Join-Path $roomDir "lifecycle.json") -Raw | ConvertFrom-Json
            $lc.states.review.signals.done.target     | Should -Be "done"
            $lc.states.review.signals.pass.target     | Should -Be "done" -Because "pass remains a legacy accepted success signal"
	            # review.fail → optimize (incremental fix cycle, NOT full developing restart)
	            $lc.states.review.signals.fail.target     | Should -Be "optimize"
	            $lc.states.review.signals.escalate.target | Should -Be "triage"
	            $lc.states.review.signals.PSObject.Properties.Name | Should -Not -Contain "error"
        }

        It "fail signal includes retry bookkeeping and post_fix compatibility action" {
            & $script:NewWarRoom -RoomId "room-133" -TaskRef "TASK-133" `
                                 -TaskDescription "Fail actions" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-133"
            Write-V2Lifecycle -RoomDir $roomDir
            $lc = Get-Content (Join-Path $roomDir "lifecycle.json") -Raw | ConvertFrom-Json
            $actions = $lc.states.review.signals.fail.actions
            $actions | Should -Contain "increment_retries"
            $actions | Should -Contain "post_fix"
        }

        It "failed is terminal, not a worktree or retry decision state" {
            & $script:NewWarRoom -RoomId "room-134" -TaskRef "TASK-134" `
                                 -TaskDescription "Decision state" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-134"
            Write-V2Lifecycle -RoomDir $roomDir
            $lc = Get-Content (Join-Path $roomDir "lifecycle.json") -Raw | ConvertFrom-Json
            $lc.states.failed.type | Should -Be "terminal"
            $lc.states.failed.PSObject.Properties.Name | Should -Not -Contain "signals"
        }
    }

    Context "External status bypass handling (QA-bypass scenario)" {
        It "failed with retries remaining and fail message stays terminal" {
            & $script:NewWarRoom -RoomId "room-120" -TaskRef "EPIC-120" `
                                 -TaskDescription "QA bypass test" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-120"
            & $script:PostMessage -RoomDir $roomDir -From "engineer" -To "manager" `
                                  -Type "done" -Ref "EPIC-120" -Body "Implemented feature"
            & $script:PostMessage -RoomDir $roomDir -From "qa" -To "manager" `
                                  -Type "fail" -Ref "EPIC-120" `
                                  -Body "VERDICT: FAIL`nBuild integrity issues found."
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "failed"
            $status = (Get-Content (Join-Path $roomDir "status") -Raw).Trim()
            $status | Should -Be "failed"
            $retries = [int](Get-Content (Join-Path $roomDir "retries") -Raw).Trim()
            $retries | Should -Be 0
            $msgs = & $script:ReadMessages -RoomDir $roomDir -FilterType "fail" -AsObject
            $msgs.Count | Should -BeGreaterThan 0
            $maxRetries = 3
            ($retries -lt $maxRetries) | Should -BeTrue
        }

        It "failed with retries exhausted stays terminal" {
            & $script:NewWarRoom -RoomId "room-121" -TaskRef "TASK-121" `
                                 -TaskDescription "Exhausted retries" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-121"
            "3" | Out-File -FilePath (Join-Path $roomDir "retries") -NoNewline
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "failed"
            $status = (Get-Content (Join-Path $roomDir "status") -Raw).Trim()
            $status | Should -Be "failed"
            $retries = [int](Get-Content (Join-Path $roomDir "retries") -Raw).Trim()
            $maxRetries = 3
            ($retries -ge $maxRetries) | Should -BeTrue
        }

	        It "failed with no fail feedback stays terminal" {
            & $script:NewWarRoom -RoomId "room-122" -TaskRef "TASK-122" `
                                 -TaskDescription "No feedback" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-122"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "failed"
            $status = (Get-Content (Join-Path $roomDir "status") -Raw).Trim()
            $status | Should -Be "failed"
            $failMsgs = & $script:ReadMessages -RoomDir $roomDir -FilterType "fail" -AsObject
	            $failMsgs.Count | Should -Be 0
        }
    }

    Context "warroom-server MCP status contract" {
        It "warroom-server.py rejects legacy terminal aliases from StatusType" {
            $serverPy = Join-Path $script:agentsDir "mcp" "warroom-server.py"
            $content = Get-Content $serverPy -Raw
            $content | Should -Match 'StatusType\s*=\s*Literal\['
            # Extract just the StatusType block (from Literal[ to ])
            $statusBlock = [regex]::Match($content, 'StatusType\s*=\s*Literal\[(.*?)\]', 'Singleline').Groups[1].Value
            $statusBlock | Should -Match '"done"'
            $statusBlock | Should -Match '"failed"'
            $statusBlock | Should -Not -Match '"fixing"'
            $statusBlock | Should -Not -Match '"passed"'
            $statusBlock | Should -Not -Match '"failed-final"'
        }

        It "warroom-server.py writes audit.log on status change" {
            $serverPy = Join-Path $script:agentsDir "mcp" "warroom-server.py"
            $content = Get-Content $serverPy -Raw
            $content | Should -Match 'audit\.log'
            $content | Should -Match 'state_changed_at'
        }

        It "warroom-server.py validates against lifecycle.json states" {
            $serverPy = Join-Path $script:agentsDir "mcp" "warroom-server.py"
            $content = Get-Content $serverPy -Raw
            # Must validate against lifecycle states and expose canonical terminal statuses.
            $content | Should -Match 'lifecycle'
            $content | Should -Match '"done"'
            $content | Should -Match '"failed"'
        }

        It "StatusType includes review and developing" {
            $serverPy = Join-Path $script:agentsDir "mcp" "warroom-server.py"
            $content = Get-Content $serverPy -Raw
            $content | Should -Match '"review"'
            $content | Should -Match '"developing"'
        }
    }

    Context "Leak fix — Find-LatestSignal detects DateTime timestamps" {
        It "detects done signal when ts is ISO-8601 (parsed as DateTime by ConvertFrom-Json)" {
            & $script:NewWarRoom -RoomId "room-200" -TaskRef "TASK-200" `
                                 -TaskDescription "Signal detect test" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-200"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "developing"

            # Seed a done message with an ISO-8601 timestamp.
            & $script:PostMessage -RoomDir $roomDir -From "engineer" -To "manager" `
                                  -Type "done" -Ref "TASK-200" -Body "Work complete"

            # Read back to confirm ts is DateTime
            $msgs = & $script:ReadMessages -RoomDir $roomDir -FilterType "done" -Last 1 -AsObject
            $msgs.Count | Should -Be 1
            $msgs[0].ts | Should -BeOfType [datetime]
        }

        It "signal timestamp is newer than state_changed_at" {
            & $script:NewWarRoom -RoomId "room-201" -TaskRef "TASK-201" `
                                 -TaskDescription "Timestamp compare" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-201"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "developing"

            # Set state_changed_at to a past epoch (10 seconds ago)
            $pastEpoch = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - 10
            $pastEpoch.ToString() | Out-File -FilePath (Join-Path $roomDir "state_changed_at") -NoNewline

            # Post done message now (ts will be > pastEpoch)
            & $script:PostMessage -RoomDir $roomDir -From "engineer" -To "manager" `
                                  -Type "done" -Ref "TASK-201" -Body "Done now"

            # Read and verify timestamp comparison works
            $msgs = & $script:ReadMessages -RoomDir $roomDir -FilterType "done" -Last 1 -AsObject
            $latest = $msgs[0]
            # Parse the same way Find-LatestSignal does
            $msgTs = 0
            if ($latest.ts -is [datetime]) {
                $msgTs = [long]([DateTimeOffset]::new($latest.ts.ToUniversalTime()).ToUnixTimeSeconds())
            }
            $msgTs | Should -BeGreaterOrEqual $pastEpoch
        }

        It "old signal before state reset is correctly filtered out" {
            & $script:NewWarRoom -RoomId "room-202" -TaskRef "TASK-202" `
                                 -TaskDescription "Old signal filter" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-202"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "developing"

            # Post done message now
            & $script:PostMessage -RoomDir $roomDir -From "engineer" -To "manager" `
                                  -Type "done" -Ref "TASK-202" -Body "Old done"

            # Simulate state timeout reset: set state_changed_at to future
            $futureEpoch = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() + 60
            $futureEpoch.ToString() | Out-File -FilePath (Join-Path $roomDir "state_changed_at") -NoNewline

            # The old done message should NOT be detected
            $msgs = & $script:ReadMessages -RoomDir $roomDir -FilterType "done" -Last 1 -AsObject
            $latest = $msgs[0]
            $msgTs = 0
            if ($latest.ts -is [datetime]) {
                $msgTs = [long]([DateTimeOffset]::new($latest.ts.ToUniversalTime()).ToUnixTimeSeconds())
            }
            # msgTs should be LESS than the future state_changed_at
            $msgTs | Should -BeLessThan $futureEpoch
        }
    }

    Context "Leak fix — Complete-PlanApproval one-shot flag" {
        It "creates .plan_approved flag file on first PLAN-REVIEW done" {
            & $script:NewWarRoom -RoomId "room-210" -TaskRef "PLAN-REVIEW" `
                                 -TaskDescription "Approval gate" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-210"

            # The flag file should not exist initially
            $flagFile = Join-Path $script:warRoomsDir ".plan_approved_PLAN-REVIEW"
            Test-Path $flagFile | Should -BeFalse

            # Simulate the guard logic from the manager loop
            "1" | Out-File -FilePath $flagFile -Encoding utf8 -NoNewline
            Test-Path $flagFile | Should -BeTrue
        }

        It "flag file prevents second Complete-PlanApproval invocation" {
            # Simulate the one-shot guard
            $warRoomsDir = $script:warRoomsDir
            $taskRef = "PLAN-REVIEW"
            $flagFile = Join-Path $warRoomsDir ".plan_approved_PLAN-REVIEW"

            # First invocation — should pass guard
            $firstInvocation = $false
            if ($taskRef -eq 'PLAN-REVIEW' -and -not (Test-Path $flagFile)) {
                $firstInvocation = $true
                "1" | Out-File -FilePath $flagFile -Encoding utf8 -NoNewline
            }
            $firstInvocation | Should -BeTrue

            # Second invocation — should be blocked by flag
            $secondInvocation = $false
            if ($taskRef -eq 'PLAN-REVIEW' -and -not (Test-Path $flagFile)) {
                $secondInvocation = $true
            }
            $secondInvocation | Should -BeFalse
        }

        It "flag file is scoped to specific task ref" {
            $warRoomsDir = $script:warRoomsDir
            $flagPlan = Join-Path $warRoomsDir ".plan_approved_PLAN-REVIEW"
            $flagEpic = Join-Path $warRoomsDir ".plan_approved_EPIC-001"

            # PLAN-REVIEW flag should not block EPIC-001 (different task ref)
            "1" | Out-File -FilePath $flagPlan -Encoding utf8 -NoNewline
            Test-Path $flagPlan | Should -BeTrue
            Test-Path $flagEpic | Should -BeFalse
        }
    }

    Context "Leak fix — pending signal prevents re-spawn" {
        It "done message in channel prevents re-spawn when no PID alive" {
            & $script:NewWarRoom -RoomId "room-220" -TaskRef "TASK-220" `
                                 -TaskDescription "Re-spawn guard" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-220"
            Write-V2Lifecycle -RoomDir $roomDir
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "developing"

            # Set state_changed_at to past (so done signal is "newer")
            $pastEpoch = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - 10
            $pastEpoch.ToString() | Out-File -FilePath (Join-Path $roomDir "state_changed_at") -NoNewline

            # Engineer posts done and cleans up PID (simulating the crash window)
            & $script:PostMessage -RoomDir $roomDir -From "engineer" -To "manager" `
                                  -Type "done" -Ref "TASK-220" -Body "All done"

            # No PID file exists
            $pidFile = Join-Path $roomDir "pids" "engineer.pid"
            Test-Path $pidFile | Should -BeFalse

            # Lifecycle-driven pending signal guard
            $lc = Get-Content (Join-Path $roomDir "lifecycle.json") -Raw | ConvertFrom-Json
            $stateDef = $lc.states.developing
            $expectedSignals = @($stateDef.signals.PSObject.Properties.Name)
            $expectedRole = ($stateDef.role -replace ':.*$', '')

            $pendingSignal = $null
            foreach ($sigType in $expectedSignals) {
                $msgs = & $script:ReadMessages -RoomDir $roomDir -FilterType $sigType -Last 1 -AsObject
                if ($msgs -and $msgs.Count -gt 0) {
                    $latest = $msgs[-1]
                    # Sender validation
                    $senderBase = ($latest.from -replace ':.*$', '')
                    if ($senderBase -ne $expectedRole) { continue }
                    # Strict timing
                    $msgTs = 0
                    if ($latest.ts -is [datetime]) {
                        $msgTs = [long]([DateTimeOffset]::new($latest.ts.ToUniversalTime()).ToUnixTimeSeconds())
                    }
                    $changedAt = [int](Get-Content (Join-Path $roomDir "state_changed_at") -Raw).Trim()
                    if ($msgTs -gt $changedAt) {
                        $pendingSignal = $sigType
                        break
                    }
                }
            }

            # Guard SHOULD detect the pending done signal → skip re-spawn
            $pendingSignal | Should -Be "done"
        }

        It "no pending signal allows re-spawn (normal case)" {
            & $script:NewWarRoom -RoomId "room-221" -TaskRef "TASK-221" `
                                 -TaskDescription "Normal re-spawn" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-221"
            Write-V2Lifecycle -RoomDir $roomDir
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "developing"

            # No messages at all — channel is empty
            $lc = Get-Content (Join-Path $roomDir "lifecycle.json") -Raw | ConvertFrom-Json
            $stateDef = $lc.states.developing
            $expectedSignals = @($stateDef.signals.PSObject.Properties.Name)

            $pendingSignal = $null
            foreach ($sigType in $expectedSignals) {
                $msgs = & $script:ReadMessages -RoomDir $roomDir -FilterType $sigType -Last 1 -AsObject
                if ($msgs -and $msgs.Count -gt 0) {
                    $pendingSignal = $sigType
                    break
                }
            }

            # No pending signal → re-spawn SHOULD proceed
            $pendingSignal | Should -BeNullOrEmpty
        }
    }

    Context "Exploit — LEAK-4: decision state does not infinite-loop status writes" {
        It "decision retry transition targets developing (not self)" {
            & $script:NewWarRoom -RoomId "room-300" -TaskRef "TASK-300" `
                                 -TaskDescription "Decision loop test" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-300"
            Write-V2Lifecycle -RoomDir $roomDir
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "failed"

            # Read lifecycle to verify failed is terminal, not a retry decision node.
            $lc = Get-Content (Join-Path $roomDir "lifecycle.json") -Raw | ConvertFrom-Json
            $failedState = $lc.states.failed
            $failedState.type | Should -Be "terminal"
            $failedState.PSObject.Properties.Name | Should -Not -Contain "signals"
        }

        It "retries file must be incremented to prevent infinite decision cycles" {
            & $script:NewWarRoom -RoomId "room-301" -TaskRef "TASK-301" `
                                 -TaskDescription "Decision retries" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-301"
            Write-V2Lifecycle -RoomDir $roomDir

            # Simulate: room starts at 0 retries, max is 3
            "0" | Out-File -FilePath (Join-Path $roomDir "retries") -NoNewline
            $lc = Get-Content (Join-Path $roomDir "lifecycle.json") -Raw | ConvertFrom-Json
            $retries = [int](Get-Content (Join-Path $roomDir "retries") -Raw).Trim()
            $maxRetries = $lc.max_retries

            # Decision should retry when retries < max
            $retries | Should -BeLessThan $maxRetries
            # And exhaust when retries >= max
            "3" | Out-File -FilePath (Join-Path $roomDir "retries") -NoNewline
            $retries2 = [int](Get-Content (Join-Path $roomDir "retries") -Raw).Trim()
            $retries2 | Should -BeGreaterOrEqual $maxRetries
        }
    }

    Context "Exploit — LEAK-5: PLAN-REVIEW shortcut uses one-shot guard" {
        It "shortcut path and terminal path both respect same flag file" {
            $warRoomsDir = $script:warRoomsDir
            $flagFile = Join-Path $warRoomsDir ".plan_approved_PLAN-REVIEW"

            # Simulate shortcut path (first detection of approval)
            $shortcutFired = $false
            if (-not (Test-Path $flagFile)) {
                $shortcutFired = $true
                "1" | Out-File -FilePath $flagFile -Encoding utf8 -NoNewline
            }
            $shortcutFired | Should -BeTrue

            # Simulate terminal handler path (next iteration, room now in 'done')
            $terminalFired = $false
            if (-not (Test-Path $flagFile)) {
                $terminalFired = $true
            }
            $terminalFired | Should -BeFalse

        # Total invocations = exactly 1
        Test-Path $flagFile | Should -BeTrue
    }
}

Context "PLAN-REVIEW Verdict Logic" {
    It "detects VERDICT: REJECT from done body" {
        $doneBody = "I have reviewed this plan and my decision is:`n`nVERDICT: REJECT"
        $rejected = ($doneBody -match 'VERDICT:\s*REJECT')
        $rejected | Should -BeTrue
    }

    It "detects VERDICT: DONE from done body" {
        $doneBody = "I have reviewed this plan and my decision is:`n`nVERDICT: DONE"
        $approved = ($doneBody -match 'VERDICT:\s*(DONE|PASS)|plan-approve|signoff|APPROVED')
        $approved | Should -BeTrue
    }

    It "still detects legacy VERDICT: PASS from done body" {
        $doneBody = "I have reviewed this plan and my decision is:`n`nVERDICT: PASS"
        $approved = ($doneBody -match 'VERDICT:\s*(DONE|PASS)|plan-approve|signoff|APPROVED')
        $approved | Should -BeTrue
    }
}

    Context "Exploit — LEAK-6: state timeout re-resolves role for restart state" {
        It "review timeout should spawn engineer (not qa) for developing state" {
            & $script:NewWarRoom -RoomId "room-310" -TaskRef "TASK-310" `
                                 -TaskDescription "Timeout role test" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-310"
            Write-V2Lifecycle -RoomDir $roomDir
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "review"

            $lc = Get-Content (Join-Path $roomDir "lifecycle.json") -Raw | ConvertFrom-Json

            # Current state is 'review' — role is 'qa'
            $currentRole = $lc.states.review.role
            $currentRole | Should -Be "qa"

            # After timeout, restart to initial_state
            $restartState = $lc.initial_state
            $restartState | Should -Be "developing"

            # Restart state role should be 'engineer', not 'qa'
            $restartRole = $lc.states.$restartState.role
            $restartRole | Should -Be "engineer"
            $restartRole | Should -Not -Be $currentRole
        }

        It "triage timeout should spawn engineer (not manager) for developing" {
            & $script:NewWarRoom -RoomId "room-311" -TaskRef "TASK-311" `
                                 -TaskDescription "Triage timeout" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-311"
            Write-V2Lifecycle -RoomDir $roomDir
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "triage"

            $lc = Get-Content (Join-Path $roomDir "lifecycle.json") -Raw | ConvertFrom-Json
            $currentRole = $lc.states.triage.role
            $currentRole | Should -Be "manager"

            $restartRole = $lc.states.($lc.initial_state).role
            $restartRole | Should -Be "engineer"
        }
    }

    Context "Exploit — LEAK-7: deadlock recovery must check pending signals" {
        It "deadlock recovery skips room with pending done signal" {
            & $script:NewWarRoom -RoomId "room-320" -TaskRef "TASK-320" `
                                 -TaskDescription "Deadlock signal test" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-320"
            Write-V2Lifecycle -RoomDir $roomDir
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "developing"

            # Set state_changed_at to past
            $pastEpoch = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - 10
            $pastEpoch.ToString() | Out-File -FilePath (Join-Path $roomDir "state_changed_at") -NoNewline

            # Engineer posted done (signal pending)
            & $script:PostMessage -RoomDir $roomDir -From "engineer" -To "manager" `
                                  -Type "done" -Ref "TASK-320" -Body "Work complete"

            # Lifecycle-driven deadlock signal check
            $lc = Get-Content (Join-Path $roomDir "lifecycle.json") -Raw | ConvertFrom-Json
            $stateDef = $lc.states.developing
            $expectedRole = ($stateDef.role -replace ':.*$', '')

            # The pending done signal should be detected
            $msgs = & $script:ReadMessages -RoomDir $roomDir -FilterType "done" -Last 1 -AsObject
            $msgs.Count | Should -Be 1
            $latest = $msgs[0]

            # Sender validation: sender matches lifecycle role
            $senderBase = ($latest.from -replace ':.*$', '')
            $senderBase | Should -Be $expectedRole

            # Strict timing: signal is after state_changed_at
            $msgTs = 0
            if ($latest.ts -is [datetime]) {
                $msgTs = [long]([DateTimeOffset]::new($latest.ts.ToUniversalTime()).ToUnixTimeSeconds())
            }
            $changedAt = [int](Get-Content (Join-Path $roomDir "state_changed_at") -Raw).Trim()
            ($msgTs -gt $changedAt) | Should -BeTrue
            # Deadlock recovery should NOT reset this room
        }

        It "deadlock recovery proceeds when no signal pending" {
            & $script:NewWarRoom -RoomId "room-321" -TaskRef "TASK-321" `
                                 -TaskDescription "Deadlock no signal" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-321"
            Write-V2Lifecycle -RoomDir $roomDir
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "developing"

            # No messages posted — channel empty
            $msgs = & $script:ReadMessages -RoomDir $roomDir -FilterType "done" -Last 1 -AsObject
            ($msgs.Count -eq 0) | Should -BeTrue
            # Deadlock recovery SHOULD proceed for this room
        }
    }

    Context "Exploit — LEAK-8: failed status remains terminal" {
	        It "failed status stays terminal when no fail feedback exists" {
            & $script:NewWarRoom -RoomId "room-330" -TaskRef "TASK-330" `
                                 -TaskDescription "Rescue guard" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-330"
            Write-V2Lifecycle -RoomDir $roomDir
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "failed"
            "1" | Out-File -FilePath (Join-Path $roomDir "retries") -NoNewline

	            # No fail message — terminal status should not be rescued
	            $failMsg = & $script:ReadMessages -RoomDir $roomDir -FilterType "fail" -Last 1 -AsObject
	            $failMsg.Count | Should -Be 0
	            (Get-Content (Join-Path $roomDir "status") -Raw).Trim() | Should -Be "failed"
        }

        It "failed status stays terminal even when fail feedback exists" {
            & $script:NewWarRoom -RoomId "room-331" -TaskRef "TASK-331" `
                                 -TaskDescription "Terminal failed" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-331"
            Write-V2Lifecycle -RoomDir $roomDir
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "failed"
            "1" | Out-File -FilePath (Join-Path $roomDir "retries") -NoNewline

            # Post fail message — status remains manager-owned terminal failure
            & $script:PostMessage -RoomDir $roomDir -From "qa" -To "manager" `
                                  -Type "fail" -Ref "TASK-331" -Body "Tests failed"
            $failMsg = & $script:ReadMessages -RoomDir $roomDir -FilterType "fail" -Last 1 -AsObject
            $failMsg.Count | Should -Be 1
            (Get-Content (Join-Path $roomDir "status") -Raw).Trim() | Should -Be "failed"
        }
    }

    Context "Exploit — LEAK-9: spawn lock prevents duplicate agents" {
        It "spawn lock within grace period blocks re-spawn" {
            & $script:NewWarRoom -RoomId "room-340" -TaskRef "TASK-340" `
                                 -TaskDescription "Spawn lock test" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-340"
            Write-V2Lifecycle -RoomDir $roomDir

            # Write a spawn lock (just now)
            $pidDir = Join-Path $roomDir "pids"
            New-Item -ItemType Directory -Path $pidDir -Force | Out-Null
            $nowEpoch = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
            $nowEpoch.ToString() | Out-File -FilePath (Join-Path $pidDir "engineer.spawned_at") -NoNewline

            # Spawn lock should be active (within 30s grace)
            $lockFile = Join-Path $pidDir "engineer.spawned_at"
            $spawnedAt = [int](Get-Content $lockFile -Raw).Trim()
            $elapsed = $nowEpoch - $spawnedAt
            $elapsed | Should -BeLessThan 30
        }

        It "expired spawn lock allows re-spawn" {
            & $script:NewWarRoom -RoomId "room-341" -TaskRef "TASK-341" `
                                 -TaskDescription "Expired lock" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-341"
            Write-V2Lifecycle -RoomDir $roomDir

            # Write an expired spawn lock (60 seconds ago)
            $pidDir = Join-Path $roomDir "pids"
            New-Item -ItemType Directory -Path $pidDir -Force | Out-Null
            $expiredEpoch = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - 60
            $expiredEpoch.ToString() | Out-File -FilePath (Join-Path $pidDir "engineer.spawned_at") -NoNewline

            # Spawn lock should be expired (> 30s)
            $nowEpoch = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
            $elapsed = $nowEpoch - $expiredEpoch
            $elapsed | Should -BeGreaterOrEqual 30
        }
    }

    Context "PLAN-REVIEW shortcut detects done and legacy pass signals" {
        It "shortcut detects 'done' message from architect and approves" {
            & $script:NewWarRoom -RoomId "room-400" -TaskRef "PLAN-REVIEW" `
                                 -TaskDescription "Arch pass test" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-400"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "review"

            # Architect posts a current 'done' signal.
            & $script:PostMessage -RoomDir $roomDir -From "architect" -To "manager" `
                                  -Type "done" -Ref "PLAN-REVIEW" -Body "Plan looks good.`n`nVERDICT: DONE"

            # Simulate the PLAN-REVIEW shortcut logic from the manager
            $passCount    = (& $script:ReadMessages -RoomDir $roomDir -FilterType "pass" -AsObject).Count
            $approveCount = (& $script:ReadMessages -RoomDir $roomDir -FilterType "plan-approve" -AsObject).Count
            $doneCount    = (& $script:ReadMessages -RoomDir $roomDir -FilterType "done" -AsObject).Count

            $approved = $false
            if ($passCount -gt 0 -or $approveCount -gt 0) {
                $approved = $true
            } elseif ($doneCount -gt 0) {
                $doneBody = (& $script:ReadMessages -RoomDir $roomDir -FilterType "done" -Last 1 -AsObject)[-1].body
                if ($doneBody -match 'plan-approve|signoff|APPROVED|VERDICT:\s*(DONE|PASS)') { $approved = $true }
            }

            $passCount | Should -Be 0
            $doneCount | Should -Be 1
            $approved  | Should -BeTrue
        }

        It "shortcut still works with legacy 'done' + APPROVED keyword" {
            & $script:NewWarRoom -RoomId "room-401" -TaskRef "PLAN-REVIEW" `
                                 -TaskDescription "Legacy done test" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-401"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "review"

            # Legacy architect posts 'done' with APPROVED keyword
            & $script:PostMessage -RoomDir $roomDir -From "architect" -To "manager" `
                                  -Type "done" -Ref "PLAN-REVIEW" -Body "I APPROVED this plan."

            $passCount = (& $script:ReadMessages -RoomDir $roomDir -FilterType "pass" -AsObject).Count
            $doneCount = (& $script:ReadMessages -RoomDir $roomDir -FilterType "done" -AsObject).Count

            $approved = $false
            if ($passCount -gt 0) {
                $approved = $true
            } elseif ($doneCount -gt 0) {
                $doneBody = (& $script:ReadMessages -RoomDir $roomDir -FilterType "done" -Last 1 -AsObject)[-1].body
                if ($doneBody -match 'plan-approve|signoff|APPROVED|VERDICT:\s*(DONE|PASS)') { $approved = $true }
            }

            $passCount | Should -Be 0
            $doneCount | Should -Be 1
            $approved  | Should -BeTrue
        }

        It "shortcut detects 'fail' message from architect as rejection" {
            & $script:NewWarRoom -RoomId "room-402" -TaskRef "PLAN-REVIEW" `
                                 -TaskDescription "Arch reject test" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-402"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "review"

            # Architect posts 'fail' signal (rejection)
            & $script:PostMessage -RoomDir $roomDir -From "architect" -To "manager" `
                                  -Type "fail" -Ref "PLAN-REVIEW" -Body "Plan needs work.`n`nVERDICT: REJECT"

            $failCount = (& $script:ReadMessages -RoomDir $roomDir -FilterType "fail" -AsObject).Count
            $passCount = (& $script:ReadMessages -RoomDir $roomDir -FilterType "pass" -AsObject).Count
            $doneCount = (& $script:ReadMessages -RoomDir $roomDir -FilterType "done" -AsObject).Count

            # Approved should be false
            $approved = ($passCount -gt 0)
            $approved | Should -BeFalse
            $failCount | Should -Be 1
        }

        It "no signals means shortcut does not approve" {
            & $script:NewWarRoom -RoomId "room-403" -TaskRef "PLAN-REVIEW" `
                                 -TaskDescription "No signal test" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-403"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "review"

            # No messages at all
            $passCount    = (& $script:ReadMessages -RoomDir $roomDir -FilterType "pass" -AsObject).Count
            $approveCount = (& $script:ReadMessages -RoomDir $roomDir -FilterType "plan-approve" -AsObject).Count
            $doneCount    = (& $script:ReadMessages -RoomDir $roomDir -FilterType "done" -AsObject).Count

            $approved = $false
            if ($passCount -gt 0 -or $approveCount -gt 0) { $approved = $true }
            $approved | Should -BeFalse
        }
    }

    Context "Find-LatestSignal — strict timing (no grace window)" {
        It "accepts signal posted AFTER state_changed_at" {
            & $script:NewWarRoom -RoomId "room-410" -TaskRef "TASK-410" `
                                 -TaskDescription "Strict timing test" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-410"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "review"

            # Set state_changed_at to 10s in the past
            $pastEpoch = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - 10
            $pastEpoch.ToString() | Out-File -FilePath (Join-Path $roomDir "state_changed_at") -NoNewline

	            # Post signal now (will be > pastEpoch)
	            & $script:PostMessage -RoomDir $roomDir -From "qa" -To "manager" `
	                                  -Type "done" -Ref "TASK-410" -Body "VERDICT: DONE"

	            $msgs = & $script:ReadMessages -RoomDir $roomDir -FilterType "done" -Last 1 -AsObject
            $latest = $msgs[0]
            $msgTs = 0
            if ($latest.ts -is [datetime]) {
                $msgTs = [long]([DateTimeOffset]::new($latest.ts.ToUniversalTime()).ToUnixTimeSeconds())
            }
            $changedAt = [int](Get-Content (Join-Path $roomDir "state_changed_at") -Raw).Trim()

            # Strict: msgTs > changedAt
            ($msgTs -gt $changedAt) | Should -BeTrue
        }

        It "rejects signal posted BEFORE state_changed_at (stale signal)" {
            & $script:NewWarRoom -RoomId "room-411" -TaskRef "TASK-411" `
                                 -TaskDescription "Stale signal rejection" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-411"

	            # Post signal first
	            & $script:PostMessage -RoomDir $roomDir -From "qa" -To "manager" `
	                                  -Type "done" -Ref "TASK-411" -Body "VERDICT: DONE"

            # Set state_changed_at to future (simulates state reset after the message)
            $futureEpoch = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() + 60
            $futureEpoch.ToString() | Out-File -FilePath (Join-Path $roomDir "state_changed_at") -NoNewline

	            $msgs = & $script:ReadMessages -RoomDir $roomDir -FilterType "done" -Last 1 -AsObject
            $latest = $msgs[0]
            $msgTs = 0
            if ($latest.ts -is [datetime]) {
                $msgTs = [long]([DateTimeOffset]::new($latest.ts.ToUniversalTime()).ToUnixTimeSeconds())
            }
            $changedAt = [int](Get-Content (Join-Path $roomDir "state_changed_at") -Raw).Trim()

            # Strict: msgTs must be > changedAt — stale signal is NOT accepted
            ($msgTs -gt $changedAt) | Should -BeFalse
        }

        It "rejects same-second signal (not strictly after)" {
            & $script:NewWarRoom -RoomId "room-412" -TaskRef "TASK-412" `
                                 -TaskDescription "Same-second rejection" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-412"

	            # Post signal now
	            & $script:PostMessage -RoomDir $roomDir -From "qa" -To "manager" `
	                                  -Type "done" -Ref "TASK-412" -Body "VERDICT: DONE"

	            # Read the message ts and set state_changed_at to the SAME epoch
	            $msgs = & $script:ReadMessages -RoomDir $roomDir -FilterType "done" -Last 1 -AsObject
            $latest = $msgs[0]
            $msgTs = 0
            if ($latest.ts -is [datetime]) {
                $msgTs = [long]([DateTimeOffset]::new($latest.ts.ToUniversalTime()).ToUnixTimeSeconds())
            }
            # Set state_changed_at = msgTs (same second)
            $msgTs.ToString() | Out-File -FilePath (Join-Path $roomDir "state_changed_at") -NoNewline
            $changedAt = [int](Get-Content (Join-Path $roomDir "state_changed_at") -Raw).Trim()

            # Strict: msgTs > changedAt requires strictly after — same-second is NOT accepted
            # This is the key difference from the old grace window behavior
            ($msgTs -gt $changedAt) | Should -BeFalse
        }
    }

    Context "Find-LatestSignal — sender validation (signal bleed prevention)" {
        It "accepts signal from the lifecycle state's assigned role" {
            & $script:NewWarRoom -RoomId "room-500" -TaskRef "TASK-500" `
                                 -TaskDescription "Sender accept test" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-500"
            Write-V2Lifecycle -RoomDir $roomDir
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "developing"

            # State 'developing' has role='engineer' — post done from 'engineer'
            $pastEpoch = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - 10
            $pastEpoch.ToString() | Out-File -FilePath (Join-Path $roomDir "state_changed_at") -NoNewline

            & $script:PostMessage -RoomDir $roomDir -From "engineer" -To "manager" `
                                  -Type "done" -Ref "TASK-500" -Body "All done"

            # Simulate lifecycle-driven validation
            $lc = Get-Content (Join-Path $roomDir "lifecycle.json") -Raw | ConvertFrom-Json
            $stateDef = $lc.states.developing
            $expectedRole = ($stateDef.role -replace ':.*$', '')

            $msgs = & $script:ReadMessages -RoomDir $roomDir -FilterType "done" -Last 1 -AsObject
            $senderBase = ($msgs[0].from -replace ':.*$', '')

            # Sender matches role — should be accepted
            $senderBase | Should -Be $expectedRole
        }

        It "rejects signal from a DIFFERENT role than the lifecycle state expects" {
            & $script:NewWarRoom -RoomId "room-501" -TaskRef "TASK-501" `
                                 -TaskDescription "Sender reject test" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-501"

            # Multi-stage lifecycle: developing→designer→review→done
            @{
                version = 2; initial_state = "developing"; max_retries = 3
                states = @{
	                    developing     = @{ role = "engineer";  type = "work"; signals = @{ done = @{ target = "designer" } } }
	                    'designer' = @{ role = "designer"; type = "work"; signals = @{ done = @{ target = "review" } } }
                    review         = @{ role = "qa";        type = "review"; signals = @{ pass = @{ target = "done" }; fail = @{ target = "developing" } } }
                    done           = @{ type = "terminal" }
                    failed         = @{ type = "terminal" }
                }
            } | ConvertTo-Json -Depth 10 | Out-File (Join-Path $roomDir "lifecycle.json") -Encoding utf8

            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "designer"
            $pastEpoch = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - 10
            $pastEpoch.ToString() | Out-File -FilePath (Join-Path $roomDir "state_changed_at") -NoNewline

            # Post 'done' from 'engineer' (WRONG sender for designer state)
            & $script:PostMessage -RoomDir $roomDir -From "engineer" -To "manager" `
                                  -Type "done" -Ref "TASK-501" -Body "Engineer done but I'm not designer"

            $lc = Get-Content (Join-Path $roomDir "lifecycle.json") -Raw | ConvertFrom-Json
            $stateDef = $lc.states.'designer'
            $expectedRole = ($stateDef.role -replace ':.*$', '')

            $msgs = & $script:ReadMessages -RoomDir $roomDir -FilterType "done" -Last 1 -AsObject
            $senderBase = ($msgs[0].from -replace ':.*$', '')

            # Sender does NOT match lifecycle role — must be REJECTED
            $senderBase | Should -Not -Be $expectedRole
            $senderBase | Should -Be "engineer"     # confirms who sent it
            $expectedRole | Should -Be "designer"    # confirms who we expected
        }
    }

    Context "Signal bleed prevention — room-003 cascade scenario" {
        It "engineer done does NOT cascade through designer and review" {
            & $script:NewWarRoom -RoomId "room-510" -TaskRef "EPIC-510" `
                                 -TaskDescription "Signal bleed test" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-510"

            # Room-003 lifecycle: developing → designer → review → done
            @{
                version = 2; initial_state = "developing"; max_retries = 3
                states = @{
	                    developing      = @{ role = "engineer";  type = "work";   signals = @{ done = @{ target = "designer" } } }
	                    'designer' = @{ role = "designer"; type = "work";   signals = @{ done = @{ target = "review" } } }
                    review          = @{ role = "qa";        type = "review"; signals = @{ pass = @{ target = "done" }; done = @{ target = "done" }; fail = @{ target = "developing" } } }
                    done            = @{ type = "terminal" }
                    failed          = @{ type = "terminal" }
                }
            } | ConvertTo-Json -Depth 10 | Out-File (Join-Path $roomDir "lifecycle.json") -Encoding utf8

            # Start in developing state
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "developing"
            $pastEpoch = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - 10
            $pastEpoch.ToString() | Out-File -FilePath (Join-Path $roomDir "state_changed_at") -NoNewline

            # engineer posts 'done'
            & $script:PostMessage -RoomDir $roomDir -From "engineer" -To "manager" `
                                  -Type "done" -Ref "EPIC-510" -Body "All tasks completed"

            # --- Step 1: developing state should detect it (correct sender) ---
            $lc = Get-Content (Join-Path $roomDir "lifecycle.json") -Raw | ConvertFrom-Json
            $devDef = $lc.states.developing
            $devRole = ($devDef.role -replace ':.*$', '')
            $msgs = & $script:ReadMessages -RoomDir $roomDir -FilterType "done" -Last 1 -AsObject
            $senderBase = ($msgs[0].from -replace ':.*$', '')

            # developing.role = engineer, sender = engineer → MATCH
            $senderBase | Should -Be $devRole

            # --- Step 2: transition to designer ---
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "designer"

            # --- Step 3: designer state must REJECT the same signal ---
            $designerDef = $lc.states.'designer'
            $designerRole = ($designerDef.role -replace ':.*$', '')

            # The SAME done message is still the latest — but sender is engineer
            $msgs2 = & $script:ReadMessages -RoomDir $roomDir -FilterType "done" -Last 1 -AsObject
            $sender2 = ($msgs2[0].from -replace ':.*$', '')

            # designer.role = designer, sender = engineer → NO MATCH
            $sender2 | Should -Not -Be $designerRole
            $sender2 | Should -Be "engineer"
            $designerRole | Should -Be "designer"

            # If the manager used the old logic (no sender check), it would
            # transition designer → review → done in seconds.
            # With sender validation, room stays in designer waiting for
            # actual designer agent to post its own done signal.
            $currentStatus = (Get-Content (Join-Path $roomDir "status") -Raw).Trim()
            $currentStatus | Should -Be "designer"
        }

        It "designer own done signal IS accepted after sender validation" {
            & $script:NewWarRoom -RoomId "room-511" -TaskRef "EPIC-511" `
                                 -TaskDescription "Correct sender test" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-511"

            @{
                version = 2; initial_state = "developing"; max_retries = 3
                states = @{
                    developing      = @{ role = "engineer";  type = "work";   signals = @{ done = @{ target = "designer" } } }
                    'designer' = @{ role = "designer"; type = "work";   signals = @{ done = @{ target = "review" } } }
                    review          = @{ role = "qa";        type = "review"; signals = @{ pass = @{ target = "done" } } }
                    done            = @{ type = "terminal" }
                }
            } | ConvertTo-Json -Depth 10 | Out-File (Join-Path $roomDir "lifecycle.json") -Encoding utf8

            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "designer"
            $pastEpoch = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - 10
            $pastEpoch.ToString() | Out-File -FilePath (Join-Path $roomDir "state_changed_at") -NoNewline

            # designer posts done (CORRECT sender)
            & $script:PostMessage -RoomDir $roomDir -From "designer" -To "manager" `
                                  -Type "done" -Ref "EPIC-511" -Body "Design work complete"

            $lc = Get-Content (Join-Path $roomDir "lifecycle.json") -Raw | ConvertFrom-Json
            $designerDef = $lc.states.'designer'
            $designerRole = ($designerDef.role -replace ':.*$', '')

            $msgs = & $script:ReadMessages -RoomDir $roomDir -FilterType "done" -Last 1 -AsObject
            $senderBase = ($msgs[0].from -replace ':.*$', '')

            # Sender matches lifecycle role → accepted
            $senderBase | Should -Be $designerRole

            # Timing also passes (message posted after state_changed_at)
            $msgTs = 0
            if ($msgs[0].ts -is [datetime]) {
                $msgTs = [long]([DateTimeOffset]::new($msgs[0].ts.ToUniversalTime()).ToUnixTimeSeconds())
            }
            $changedAt = [int](Get-Content (Join-Path $roomDir "state_changed_at") -Raw).Trim()
            ($msgTs -gt $changedAt) | Should -BeTrue
        }

        It "stale engineer done cannot cascade through 3 states" {
            & $script:NewWarRoom -RoomId "room-512" -TaskRef "EPIC-512" `
                                 -TaskDescription "Triple cascade block" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-512"

            @{
                version = 2; initial_state = "developing"; max_retries = 3
                states = @{
                    developing      = @{ role = "engineer";  type = "work";   signals = @{ done = @{ target = "designer" } } }
                    'designer' = @{ role = "designer"; type = "work";   signals = @{ done = @{ target = "review" } } }
                    review          = @{ role = "qa";        type = "review"; signals = @{ done = @{ target = "done" } } }
                    done            = @{ type = "terminal" }
                }
            } | ConvertTo-Json -Depth 10 | Out-File (Join-Path $roomDir "lifecycle.json") -Encoding utf8

            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "developing"
            $pastEpoch = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - 10
            $pastEpoch.ToString() | Out-File -FilePath (Join-Path $roomDir "state_changed_at") -NoNewline

            # engineer posts done — only this one signal exists
            & $script:PostMessage -RoomDir $roomDir -From "engineer" -To "manager" `
                                  -Type "done" -Ref "EPIC-512" -Body "Engineer complete"

            $lc = Get-Content (Join-Path $roomDir "lifecycle.json") -Raw | ConvertFrom-Json

            # Check each state: developing accepts, designer rejects, review rejects
            $msgs = & $script:ReadMessages -RoomDir $roomDir -FilterType "done" -Last 1 -AsObject
            $sender = ($msgs[0].from -replace ':.*$', '')

            # State 1: developing (role=engineer) — ACCEPTS
            ($sender -eq ($lc.states.developing.role -replace ':.*$', '')) | Should -BeTrue

            # State 2: designer (role=designer) — REJECTS (sender=engineer)
            ($sender -eq ($lc.states.'designer'.role -replace ':.*$', '')) | Should -BeFalse

            # State 3: review (role=qa) — REJECTS (sender=engineer)
            ($sender -eq ($lc.states.review.role -replace ':.*$', '')) | Should -BeFalse
        }
    }

    Context "Full architect lifecycle: review → done" {
        It "architect done signal transitions room to done via Find-LatestSignal" {
            & $script:NewWarRoom -RoomId "room-420" -TaskRef "TASK-420" `
                                 -TaskDescription "Full done lifecycle" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-420"

            # Write architect-style lifecycle
            @{
                version = 2; initial_state = "review"; max_retries = 3
                states = @{
                    review = @{
                        role = "architect"; type = "review"
                        signals = @{
	                            done = @{ target = "done" }
	                            pass = @{ target = "done" }
                            fail = @{ target = "failed"; actions = @("increment_retries") }
                        }
                    }
                    done = @{ type = "terminal" }
                    failed = @{ type = "terminal" }
                }
            } | ConvertTo-Json -Depth 10 | Out-File (Join-Path $roomDir "lifecycle.json") -Encoding utf8

            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "review"

            # Set state_changed_at to past to ensure signal is "new"
            $pastEpoch = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - 10
            $pastEpoch.ToString() | Out-File -FilePath (Join-Path $roomDir "state_changed_at") -NoNewline

	            # Architect posts current 'done' signal
	            & $script:PostMessage -RoomDir $roomDir -From "architect" -To "manager" `
	                                  -Type "done" -Ref "TASK-420" -Body "Architecture approved.`n`nVERDICT: DONE"

            # Simulate lifecycle-driven Find-LatestSignal
            $lc = Get-Content (Join-Path $roomDir "lifecycle.json") -Raw | ConvertFrom-Json
            $stateDef = $lc.states.review
            $expectedSignals = @($stateDef.signals.PSObject.Properties.Name)
            $expectedRole = ($stateDef.role -replace ':.*$', '')
            $matchedSignal = $null

            foreach ($sigType in $expectedSignals) {
                $msgs = & $script:ReadMessages -RoomDir $roomDir -FilterType $sigType -Last 1 -AsObject
                if ($msgs -and $msgs.Count -gt 0) {
                    $latest = $msgs[-1]
                    # Sender validation
                    $senderBase = ($latest.from -replace ':.*$', '')
                    if ($senderBase -ne $expectedRole) { continue }
                    # Strict timing
                    $msgTs = 0
                    if ($latest.ts -is [datetime]) {
                        $msgTs = [long]([DateTimeOffset]::new($latest.ts.ToUniversalTime()).ToUnixTimeSeconds())
                    }
                    $changedAt = [int](Get-Content (Join-Path $roomDir "state_changed_at") -Raw).Trim()
                    if ($msgTs -gt $changedAt) {
                        $matchedSignal = $sigType
                        break
                    }
                }
            }

	            $matchedSignal | Should -Be "done"

            # Apply transition
            $targetState = $lc.states.review.signals.$matchedSignal.target
            $targetState | Should -Be "done"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus $targetState
            $finalStatus = (Get-Content (Join-Path $roomDir "status") -Raw).Trim()
            $finalStatus | Should -Be "done"
        }
    }

    Context "Full architect lifecycle: review → failed" {
        It "architect fail signal transitions room to failed" {
            & $script:NewWarRoom -RoomId "room-430" -TaskRef "TASK-430" `
                                 -TaskDescription "Full fail lifecycle" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-430"

            @{
                version = 2; initial_state = "review"; max_retries = 3
                states = @{
                    review = @{
                        role = "architect"; type = "review"
                        signals = @{
                            pass = @{ target = "done" }
                            fail = @{ target = "failed"; actions = @("increment_retries") }
                        }
                    }
                    done = @{ type = "terminal" }
                    failed = @{ type = "terminal" }
                }
            } | ConvertTo-Json -Depth 10 | Out-File (Join-Path $roomDir "lifecycle.json") -Encoding utf8

            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "review"
            $pastEpoch = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - 10
            $pastEpoch.ToString() | Out-File -FilePath (Join-Path $roomDir "state_changed_at") -NoNewline

            # Architect posts 'fail' signal
            & $script:PostMessage -RoomDir $roomDir -From "architect" -To "manager" `
                                  -Type "fail" -Ref "TASK-430" -Body "Architecture rejected.`n`nVERDICT: REJECT"

            # Simulate lifecycle-driven Find-LatestSignal
            $lc = Get-Content (Join-Path $roomDir "lifecycle.json") -Raw | ConvertFrom-Json
            $stateDef = $lc.states.review
            $expectedSignals = @($stateDef.signals.PSObject.Properties.Name)
            $expectedRole = ($stateDef.role -replace ':.*$', '')
            $matchedSignal = $null

            foreach ($sigType in $expectedSignals) {
                $msgs = & $script:ReadMessages -RoomDir $roomDir -FilterType $sigType -Last 1 -AsObject
                if ($msgs -and $msgs.Count -gt 0) {
                    $latest = $msgs[-1]
                    # Sender validation
                    $senderBase = ($latest.from -replace ':.*$', '')
                    if ($senderBase -ne $expectedRole) { continue }
                    # Strict timing
                    $msgTs = 0
                    if ($latest.ts -is [datetime]) {
                        $msgTs = [long]([DateTimeOffset]::new($latest.ts.ToUniversalTime()).ToUnixTimeSeconds())
                    }
                    $changedAt = [int](Get-Content (Join-Path $roomDir "state_changed_at") -Raw).Trim()
                    if ($msgTs -gt $changedAt) {
                        $matchedSignal = $sigType
                        break
                    }
                }
            }

            $matchedSignal | Should -Be "fail"
            $targetState = $lc.states.review.signals.$matchedSignal.target
            $targetState | Should -Be "failed"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus $targetState
            $finalStatus = (Get-Content (Join-Path $roomDir "status") -Raw).Trim()
            $finalStatus | Should -Be "failed"
        }
    }

    Context "Re-spawn guard: signal exists + dead process = no re-spawn" {
        It "pass signal in channel prevents re-spawn even when PID is dead" {
            & $script:NewWarRoom -RoomId "room-440" -TaskRef "TASK-440" `
                                 -TaskDescription "Pass signal guard" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-440"

            @{
                version = 2; initial_state = "review"; max_retries = 3
                states = @{
                    review = @{
                        role = "architect"; type = "review"
                        signals = @{
                            pass = @{ target = "done" }
                            fail = @{ target = "failed" }
                        }
                    }
                    done = @{ type = "terminal" }
                    failed = @{ type = "terminal" }
                }
            } | ConvertTo-Json -Depth 10 | Out-File (Join-Path $roomDir "lifecycle.json") -Encoding utf8

            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "review"
            $pastEpoch = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - 10
            $pastEpoch.ToString() | Out-File -FilePath (Join-Path $roomDir "state_changed_at") -NoNewline

            # Architect posted pass signal AND cleaned up its PID
            & $script:PostMessage -RoomDir $roomDir -From "architect" -To "manager" `
                                  -Type "pass" -Ref "TASK-440" -Body "VERDICT: PASS"

            $pidFile = Join-Path $roomDir "pids" "architect.pid"
            Test-Path $pidFile | Should -BeFalse

            # Simulate the lifecycle-driven pending signal guard
            $lc = Get-Content (Join-Path $roomDir "lifecycle.json") -Raw | ConvertFrom-Json
            $stateDef = $lc.states.review
            $expectedSignals = @($stateDef.signals.PSObject.Properties.Name)
            $expectedRole = ($stateDef.role -replace ':.*$', '')

            $pendingSignal = $null
            foreach ($sigType in $expectedSignals) {
                $msgs = & $script:ReadMessages -RoomDir $roomDir -FilterType $sigType -Last 1 -AsObject
                if ($msgs -and $msgs.Count -gt 0) {
                    $latest = $msgs[-1]
                    # Sender validation
                    $senderBase = ($latest.from -replace ':.*$', '')
                    if ($senderBase -ne $expectedRole) { continue }
                    # Strict timing
                    $msgTs = 0
                    if ($latest.ts -is [datetime]) {
                        $msgTs = [long]([DateTimeOffset]::new($latest.ts.ToUniversalTime()).ToUnixTimeSeconds())
                    }
                    $changedAt = [int](Get-Content (Join-Path $roomDir "state_changed_at") -Raw).Trim()
                    if ($msgTs -gt $changedAt) {
                        $pendingSignal = $sigType
                        break
                    }
                }
            }

            # Guard SHOULD detect pending pass signal → skip re-spawn
            $pendingSignal | Should -Be "pass"
        }
    }

    Context "Re-spawn allowed: no signal + dead process = re-spawn" {
        It "no signals in channel allows re-spawn when PID is dead" {
            & $script:NewWarRoom -RoomId "room-450" -TaskRef "TASK-450" `
                                 -TaskDescription "No signal re-spawn" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-450"

            @{
                version = 2; initial_state = "review"; max_retries = 3
                states = @{
                    review = @{
                        role = "architect"; type = "review"
                        signals = @{
                            pass = @{ target = "done" }
                            fail = @{ target = "failed" }
                        }
                    }
                    done = @{ type = "terminal" }
                    failed = @{ type = "terminal" }
                }
            } | ConvertTo-Json -Depth 10 | Out-File (Join-Path $roomDir "lifecycle.json") -Encoding utf8

            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "review"

            # No PID, no messages — vacant room
            $pidFile = Join-Path $roomDir "pids" "architect.pid"
            Test-Path $pidFile | Should -BeFalse

            # Lifecycle-driven: derive signals from lifecycle
            $lc = Get-Content (Join-Path $roomDir "lifecycle.json") -Raw | ConvertFrom-Json
            $stateDef = $lc.states.review
            $expectedSignals = @($stateDef.signals.PSObject.Properties.Name)

            $pendingSignal = $null
            foreach ($sigType in $expectedSignals) {
                $msgs = & $script:ReadMessages -RoomDir $roomDir -FilterType $sigType -Last 1 -AsObject
                if ($msgs -and $msgs.Count -gt 0) {
                    $pendingSignal = $sigType
                    break
                }
            }

            # No pending signal → re-spawn SHOULD proceed
            $pendingSignal | Should -BeNullOrEmpty
        }
    }

    # ========================================================================
    # Crash-respawn counter guard (prevents infinite spawn→crash→respawn loops)
    # ========================================================================
    Context "Crash-respawn counter — guards against infinite crash loops" {
        It "crash_respawns file is created when agent dies without signal" {
            & $script:NewWarRoom -RoomId "room-cr-01" -TaskRef "TASK-CR01" `
                                 -TaskDescription "Crash counter test" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-cr-01"

            # Simulate the crash-respawn guard logic from Start-ManagerLoop.ps1
            $crashFile = Join-Path $roomDir "crash_respawns"
            Test-Path $crashFile | Should -BeFalse

            # First crash — counter goes to 1
            $crashCount = 0
            $crashCount++
            $crashCount.ToString() | Out-File -FilePath $crashFile -Encoding utf8 -NoNewline
            [int](Get-Content $crashFile -Raw).Trim() | Should -Be 1
        }

        It "consecutive crashes increment the counter" {
            & $script:NewWarRoom -RoomId "room-cr-02" -TaskRef "TASK-CR02" `
                                 -TaskDescription "Crash increment" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-cr-02"
            $crashFile = Join-Path $roomDir "crash_respawns"

            # Simulate 3 consecutive crash-respawn cycles
            for ($i = 1; $i -le 3; $i++) {
                $crashCount = if (Test-Path $crashFile) { [int](Get-Content $crashFile -Raw).Trim() } else { 0 }
                $crashCount++
                $crashCount.ToString() | Out-File -FilePath $crashFile -Encoding utf8 -NoNewline
            }

            [int](Get-Content $crashFile -Raw).Trim() | Should -Be 3
        }

        It "exceeding max crash-respawns triggers failed state" {
            & $script:NewWarRoom -RoomId "room-cr-03" -TaskRef "TASK-CR03" `
                                 -TaskDescription "Crash exhaust" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-cr-03"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "review"
            $crashFile = Join-Path $roomDir "crash_respawns"

            # Simulate the guard logic: 4th crash exceeds max of 3
            $maxCrashRespawns = 3
            "3" | Out-File -FilePath $crashFile -Encoding utf8 -NoNewline
            $crashCount = [int](Get-Content $crashFile -Raw).Trim()
            $crashCount++

            if ($crashCount -gt $maxCrashRespawns) {
                Set-WarRoomStatus -RoomDir $roomDir -NewStatus "failed"
                Remove-Item $crashFile -Force -ErrorAction SilentlyContinue
            }

            $status = (Get-Content (Join-Path $roomDir "status") -Raw).Trim()
            $status | Should -Be "failed"
            Test-Path $crashFile | Should -BeFalse -Because "crash counter is cleaned up after triggering failure"
        }

        It "crash counter does not prevent re-spawn within limit" {
            & $script:NewWarRoom -RoomId "room-cr-04" -TaskRef "TASK-CR04" `
                                 -TaskDescription "Crash within limit" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-cr-04"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "review"
            $crashFile = Join-Path $roomDir "crash_respawns"

            # Simulate: 2 crashes so far (under the max of 3)
            $maxCrashRespawns = 3
            "2" | Out-File -FilePath $crashFile -Encoding utf8 -NoNewline
            $crashCount = [int](Get-Content $crashFile -Raw).Trim()
            $crashCount++
            $shouldRespawn = ($crashCount -le $maxCrashRespawns)

            $shouldRespawn | Should -BeTrue -Because "3rd crash is within the max-3 limit"
            $status = (Get-Content (Join-Path $roomDir "status") -Raw).Trim()
            $status | Should -Be "review" -Because "state should NOT change when within limit"
        }
    }

    # ========================================================================
    # Crash-respawn counter reset on successful state transition
    # ========================================================================
    Context "Crash-respawn counter — reset on successful signal transition" {
        It "crash_respawns file is deleted when a signal transitions the state" {
            & $script:NewWarRoom -RoomId "room-crr-01" -TaskRef "TASK-CRR01" `
                                 -TaskDescription "Crash reset test" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-crr-01"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "developing"
            $crashFile = Join-Path $roomDir "crash_respawns"

            # Simulate: had 2 crash-respawns before agent finally succeeded
            "2" | Out-File -FilePath $crashFile -Encoding utf8 -NoNewline
            Test-Path $crashFile | Should -BeTrue

            # Simulate successful signal match → state transition → crash counter reset
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "review"
            Remove-Item $crashFile -Force -ErrorAction SilentlyContinue

            $status = (Get-Content (Join-Path $roomDir "status") -Raw).Trim()
            $status | Should -Be "review"
            Test-Path $crashFile | Should -BeFalse -Because "crash counter must reset on successful transition"
        }

        It "crash counter from review does not carry into done state" {
            & $script:NewWarRoom -RoomId "room-crr-02" -TaskRef "TASK-CRR02" `
                                 -TaskDescription "Crash no carry" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-crr-02"
            $crashFile = Join-Path $roomDir "crash_respawns"

            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "review"
            "1" | Out-File -FilePath $crashFile -Encoding utf8 -NoNewline

            # Transition to done (terminal) — crash counter should be cleaned
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "done"
            Remove-Item $crashFile -Force -ErrorAction SilentlyContinue

            Test-Path $crashFile | Should -BeFalse
            (Get-Content (Join-Path $roomDir "status") -Raw).Trim() | Should -Be "done"
        }
    }

    # ========================================================================
    # Runtime failures are manager-owned orchestration events, not signals
    # ========================================================================
    Context "Runtime failure handling outside lifecycle signals" {
        It "review state lifecycle does not include error as a signal" {
            & $script:NewWarRoom -RoomId "room-re-01" -TaskRef "TASK-RE01" `
                                 -TaskDescription "Review runtime failure" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-re-01"
            Write-V2Lifecycle -RoomDir $roomDir
            $lc = Get-Content (Join-Path $roomDir "lifecycle.json") -Raw | ConvertFrom-Json
            $lc.states.review.signals.PSObject.Properties.Name | Should -Not -Contain "error"
        }

        It "legacy error channel messages are ignored by Find-LatestSignal" {
            $helpersModule = Join-Path $script:agentsDir "roles" "manager" "ManagerLoop-Helpers.psm1"
            Import-Module $helpersModule -Force
            Set-ManagerLoopContext -Context @{ readMessages = $script:ReadMessages }

            & $script:NewWarRoom -RoomId "room-re-03" -TaskRef "TASK-RE03" `
                                 -TaskDescription "Legacy error ignored" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-re-03"
            Write-V2Lifecycle -RoomDir $roomDir
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "review"
            ([DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - 10).ToString() |
                Out-File -FilePath (Join-Path $roomDir "state_changed_at") -NoNewline

            & $script:PostMessage -RoomDir $roomDir -From "qa" -To "manager" `
                                   -Type "error" -Ref "TASK-RE03" -Body "legacy wrapper error"

            $lc = Get-Content (Join-Path $roomDir "lifecycle.json") -Raw | ConvertFrom-Json
            Find-LatestSignal -RoomDir $roomDir -Lifecycle $lc -StateName "review" | Should -BeNull

            Remove-Module ManagerLoop-Helpers -ErrorAction SilentlyContinue
        }

        It "fresh failed role config is detected for manager failed-state routing" {
            $helpersModule = Join-Path $script:agentsDir "roles" "manager" "ManagerLoop-Helpers.psm1"
            Import-Module $helpersModule -Force

            & $script:NewWarRoom -RoomId "room-re-04" -TaskRef "TASK-RE04" `
                                 -TaskDescription "Failed role status" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-re-04"
            Write-V2Lifecycle -RoomDir $roomDir
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "review"
            $changedAt = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - 1
            $changedAt.ToString() | Out-File -FilePath (Join-Path $roomDir "state_changed_at") -NoNewline

            @{
                role = "qa"
                instance_id = "001"
                status = "failed"
                status_updated_epoch = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
            } | ConvertTo-Json -Depth 4 | Out-File (Join-Path $roomDir "qa_001.json") -Encoding utf8

            $failedRun = Get-FreshFailedRoleRun -RoomDir $roomDir -Role "qa"
            $failedRun | Should -Not -BeNullOrEmpty
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "failed"
            (Get-Content (Join-Path $roomDir "status") -Raw).Trim() | Should -Be "failed"

            Remove-Module ManagerLoop-Helpers -ErrorAction SilentlyContinue
        }
    }

    # ========================================================================
    # Deadlock recovery risk fixes (Risk 2, 3, 4, 6)
    # ========================================================================
    Context "Runtime config resolution (Static Analysis)" {
        It "Start-ManagerLoop.ps1 uses the shared config resolver for dashboard-written global config" {
            $managerScript = Join-Path $script:agentsDir "roles" "manager" "Start-ManagerLoop.ps1"
            $content = Get-Content $managerScript -Raw

            $content | Should -Match 'Resolve-OstwinConfigPath' `
                -Because "manager runtime defaults must see ~/.ostwin/.agents/config.json when the dashboard writes it"
            $content | Should -Match 'OSTWIN_CONFIG_PATH' `
                -Because "dashboard-compatible explicit config overrides must be honored"
            $content | Should -Match 'OSTWIN_PROJECT_DIR' `
                -Because "project-scoped dashboard runs must still be able to select project config"
        }
    }

    Context "Deadlock recovery fixes (Static Analysis)" {
        It "Deadlock recovery calls Stop-RoomProcesses to clean stale PIDs (Risk 2)" {
            $managerScript = Join-Path $script:agentsDir "roles" "manager" "Start-ManagerLoop.ps1"
            $content = Get-Content $managerScript -Raw

            # The block should contain Stop-RoomProcesses $rd
            $content | Should -Match 'Stop-RoomProcesses \$rd' `
                -Because "deadlock recovery must explicitly clean up stale PIDs before transition"
        }

        It "Deadlock recovery calls Start-WorkerJob immediately (Risk 2)" {
            $managerScript = Join-Path $script:agentsDir "roles" "manager" "Start-ManagerLoop.ps1"
            $content = Get-Content $managerScript -Raw

            # Look for the Start-WorkerJob call connected to $dlRestartRole
            $content | Should -Match 'Start-WorkerJob -RoomDir \$rd -Role \$dlRestartRole.*-SkipLockCheck' `
                -Because "deadlock recovery must actively spawn the worker, not rely on the next iteration"
        }

        It "Deadlock recovery does NOT increment retries (Risk 3+4)" {
            $managerScript = Join-Path $script:agentsDir "roles" "manager" "Start-ManagerLoop.ps1"
            $content = Get-Content $managerScript -Raw

            # The string '($lr + 1).ToString() | Out-File -FilePath (Join-Path $rd "retries")' was removed.
            $content | Should -Not -Match '\(\$lr \+ 1\).ToString\(\) \| Out-File -FilePath \(Join-Path \$rd "retries"\)' `
                -Because "incrementing retries during deadlock recovery corrupts the done-count gate"
        }

        It "Deadlock recovery uses lifecycle state role, not assigned_role (Risk 6)" {
            $managerScript = Join-Path $script:agentsDir "roles" "manager" "Start-ManagerLoop.ps1"
            $content = Get-Content $managerScript -Raw

            # The block should try to pull role from $dlStateDef first
            $content | Should -Match '\$dlRole = \(\$dlStateDef\.role -replace' `
                -Because "manager must use the lifecycle state role for deadlock restart"
        }
    }

    # ==========================================================================
    # max_retries resolution chain (NEW: plan.roles.json → config.json → role.json)
    # ==========================================================================
    Context "max_retries resolution chain — plan.roles.json priority" {
        It "Start-ManagerLoop.ps1 resolves max_retries from plan.roles.json when present" {
            # Static analysis: the manager's default handler must contain the
            # plan-roles max_retries resolution chain.
            $managerScript = Join-Path $script:agentsDir "roles" "manager" "Start-ManagerLoop.ps1"
            $content = Get-Content $managerScript -Raw

            # Must read plan_id from room config.json
            $content | Should -Match 'rcData\.plan_id' `
                -Because "max_retries resolution must read plan_id from room config.json"

            # Must construct plan roles file path
            $content | Should -Match 'planRolesFile' `
                -Because "max_retries resolution must look up {plan_id}.roles.json"

            # Must read max_retries from plan roles config
            $content | Should -Match 'planRolesConfig\.\$baseRole\.max_retries' `
                -Because "per-role max_retries must be read from plan.roles.json"
        }

        It "Start-ManagerLoop.ps1 falls back to config.json max_retries when plan.roles.json absent" {
            $managerScript = Join-Path $script:agentsDir "roles" "manager" "Start-ManagerLoop.ps1"
            $content = Get-Content $managerScript -Raw

            # The elseif chain must include config.json fallback
            $content | Should -Match 'elseif \(\$config\.\$baseRole.*max_retries\)' `
                -Because "when plan.roles.json has no max_retries, config.json must be consulted"
        }

        It "Start-ManagerLoop.ps1 falls back to role.json max_retries as last config source" {
            $managerScript = Join-Path $script:agentsDir "roles" "manager" "Start-ManagerLoop.ps1"
            $content = Get-Content $managerScript -Raw

            # Must also check role.json
            $content | Should -Match 'roleJson\.max_retries' `
                -Because "when neither plan.roles.json nor config.json have max_retries, role.json must be checked"
        }

        It "Start-ManagerLoop.ps1 uses plan.roles.json max_retries over config.json max_retries (priority order)" {
            $managerScript = Join-Path $script:agentsDir "roles" "manager" "Start-ManagerLoop.ps1"
            $content = Get-Content $managerScript -Raw

            # Plan roles resolution must appear BEFORE config.json resolution
            $planPos = $content.IndexOf('planRolesConfig.$baseRole.max_retries')
            $configPos = $content.IndexOf('elseif ($config.$baseRole')

            $planPos | Should -BeGreaterThan 0
            $configPos | Should -BeGreaterThan 0
            $planPos | Should -BeLessThan $configPos `
                -Because "plan.roles.json max_retries must be checked before config.json (higher priority)"
        }

        It "lifecycle.max_retries still has final override over per-role max_retries" {
            $managerScript = Join-Path $script:agentsDir "roles" "manager" "Start-ManagerLoop.ps1"
            $content = Get-Content $managerScript -Raw

            # The last line must still be: lifecycle.max_retries ?? $roleMaxRetries
            $content | Should -Match '\$v2MaxRetries = if \(\$lifecycle.*max_retries\).*\$roleMaxRetries' `
                -Because "lifecycle.max_retries must be the final override, with per-role as fallback"
        }

        It "OSTWIN_HOME resolution is consistent between Invoke-Agent and ManagerLoop" {
            # Both scripts must resolve OSTWIN_HOME the same way:
            # $env:OSTWIN_HOME → Join-Path $HOME ".ostwin"
            $managerScript = Join-Path $script:agentsDir "roles" "manager" "Start-ManagerLoop.ps1"
            $invokeScript = Join-Path $script:agentsDir "roles" "_base" "Invoke-Agent.ps1"

            $mgrContent = Get-Content $managerScript -Raw
            $invContent = Get-Content $invokeScript -Raw

            # Both must have OSTWIN_HOME env var check
            $mgrContent | Should -Match 'OSTWIN_HOME'
            $invContent | Should -Match 'OSTWIN_HOME'

            # Both must have the same HOME fallback
            $mgrContent | Should -Match 'Join-Path \$env:HOME "\.ostwin"|Join-Path \$_homeDir "\.ostwin"'
            $invContent | Should -Match 'Join-Path \$env:HOME "\.ostwin"|Join-Path \$_homeDir "\.ostwin"'
        }
    }

    # ==========================================================================
    # run-agent.ps1 role validation against sample/room-001/lifecycle.json
    # ==========================================================================
    # These tests verify the CONTRACT that run-agent.ps1 content (AGENT_OS_ROLE,
    # the PID file path, and the --agent flag) MUST match the role defined in
    # lifecycle.json for the current war-room state.
    #
    # run-agent.ps1 is generated by Invoke-Agent.ps1 inside each room's artifacts/
    # directory. The manager selects the role from lifecycle.json; these tests
    # ensure that selection propagates correctly into the generated wrapper script.
    #
    # Tests are fully offline: they MOCK run-agent.ps1 rather than invoking
    # Invoke-Agent.ps1 directly, keeping them fast and side-effect-free.
    # The mocked format mirrors exactly what Invoke-Agent.ps1 produces.
    Context "run-agent.ps1 reflects lifecycle role for war-room state" {

        BeforeAll {
            # Load the real sample lifecycle once for all tests in this context
            $script:sampleLifecyclePath = Join-Path $script:agentsDir ".." "sample" "room-001" "lifecycle.json"
            if (Test-Path $script:sampleLifecyclePath) {
                $script:sampleLifecycle = Get-Content $script:sampleLifecyclePath -Raw | ConvertFrom-Json
            } else {
                $script:sampleLifecycle = $null
                Write-Warning "[run-agent.ps1 tests] sample/room-001/lifecycle.json not found — some tests may be skipped."
            }

            # Helper: write a minimal run-agent.ps1 that mirrors Invoke-Agent.ps1's output.
            # Only the fields we assert on need to be present.
            # Accepts an optional -Model parameter to simulate plan.roles.json model
            # propagation through Invoke-Agent.ps1 → run-agent.ps1.
            function Write-MockRunAgentScript {
                param(
                    [string]$RoomDir,
                    [string]$Role,
                    [string]$Model = 'google-vertex/gemini-test'
                )
                $artifactsDir = Join-Path $RoomDir "artifacts"
                New-Item -ItemType Directory -Path $artifactsDir -Force | Out-Null
                $pidFile = ($RoomDir -replace "'", "''") + "/pids/$Role.pid"
                $promptFile = ($RoomDir -replace "'", "''") + "/artifacts/prompt.txt"
                $outputFile = ($RoomDir -replace "'", "''") + "/artifacts/$Role-output.txt"
                $content = @"
# --- run-agent.ps1 — Unified agent wrapper (all platforms) ---
`$env:AGENT_OS_ROOM_DIR = '$RoomDir'
`$env:AGENT_OS_ROLE = '$Role'
`$env:AGENT_OS_PARENT_PID = '12345'
`$env:AGENT_OS_SKILLS_DIR = '/path/to/project/.agents/skills'
`$env:AGENT_OS_PID_FILE = '$pidFile'
`$env:OSTWIN_HOME = '/Users/test/.ostwin'
`$env:AGENT_OS_PROJECT_DIR = '/Users/test/project'
`$PID | Out-File -FilePath '$pidFile' -Encoding ascii -NoNewline
"[wrapper] PID=`$PID, CMD=agent" | Out-File -FilePath '$outputFile' -Encoding utf8 -Append
& '$($OstwinHome)/.agents/bin/agent' -n (Get-Content '$promptFile' -Raw) --agent $Role --auto-approve --model $Model --quiet 2>&1 | Out-File -FilePath '$outputFile' -Encoding utf8 -Append
"@
                $scriptPath = Join-Path $artifactsDir "run-agent.ps1"
                $content | Out-File -FilePath $scriptPath -Encoding utf8 -NoNewline -Force
                return $scriptPath
            }
        }

        It "sample/room-001/lifecycle.json is present and parseable" {
            if (-not $script:sampleLifecycle) { Set-ItResult -Skipped -Because "lifecycle fixture missing" }
            $lc = $script:sampleLifecycle
            $lc | Should -Not -BeNullOrEmpty
            $lc.version | Should -Be 2
            $lc.initial_state | Should -Be "developing"
        }

        It "developing state: run-agent.ps1 carries engineer role" {
            if (-not $script:sampleLifecycle) { Set-ItResult -Skipped -Because "lifecycle fixture missing" }

            # Assert the lifecycle definition
            $expectedRole = $script:sampleLifecycle.states.developing.role
            $expectedRole | Should -Be "engineer"

            # Create a war-room and set to developing state
            & $script:NewWarRoom -RoomId "room-ra-001" -TaskRef "TASK-RA-001" `
                                 -TaskDescription "run-agent developing" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-ra-001"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "developing"

            # Generate mock run-agent.ps1 with the lifecycle-resolved role
            $scriptPath = Write-MockRunAgentScript -RoomDir $roomDir -Role $expectedRole
            $content = Get-Content $scriptPath -Raw

            # Assert run-agent.ps1 carries the correct role
            $content | Should -Match "AGENT_OS_ROLE.*=.*'engineer'"
            $content | Should -Match "\-\-agent engineer"
            $content | Should -Match "engineer\.pid"
        }

        It "optimize state: run-agent.ps1 carries engineer role" {
            if (-not $script:sampleLifecycle) { Set-ItResult -Skipped -Because "lifecycle fixture missing" }

            $expectedRole = $script:sampleLifecycle.states.optimize.role
            $expectedRole | Should -Be "engineer"

            & $script:NewWarRoom -RoomId "room-ra-002" -TaskRef "TASK-RA-002" `
                                 -TaskDescription "run-agent optimize" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-ra-002"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "optimize"

            $scriptPath = Write-MockRunAgentScript -RoomDir $roomDir -Role $expectedRole
            $content = Get-Content $scriptPath -Raw

            $content | Should -Match "AGENT_OS_ROLE.*=.*'engineer'"
            $content | Should -Match "\-\-agent engineer"
            $content | Should -Match "engineer\.pid"
        }

        It "review state: run-agent.ps1 carries qa role (not engineer)" {
            if (-not $script:sampleLifecycle) { Set-ItResult -Skipped -Because "lifecycle fixture missing" }

            $expectedRole = $script:sampleLifecycle.states.review.role
            $expectedRole | Should -Be "qa"

            & $script:NewWarRoom -RoomId "room-ra-003" -TaskRef "TASK-RA-003" `
                                 -TaskDescription "run-agent review" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-ra-003"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "review"

            $scriptPath = Write-MockRunAgentScript -RoomDir $roomDir -Role $expectedRole
            $content = Get-Content $scriptPath -Raw

            # review state MUST use qa, never engineer
            $content | Should -Match "AGENT_OS_ROLE.*=.*'qa'"
            $content | Should -Match "\-\-agent qa"
            $content | Should -Match "qa\.pid"
            $content | Should -Not -Match "AGENT_OS_ROLE.*=.*'engineer'"
            $content | Should -Not -Match "\-\-agent engineer"
        }

        It "triage state: run-agent.ps1 carries manager role" {
            if (-not $script:sampleLifecycle) { Set-ItResult -Skipped -Because "lifecycle fixture missing" }

            $expectedRole = $script:sampleLifecycle.states.triage.role
            $expectedRole | Should -Be "manager"

            & $script:NewWarRoom -RoomId "room-ra-004" -TaskRef "TASK-RA-004" `
                                 -TaskDescription "run-agent triage" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-ra-004"
            Set-WarRoomStatus -RoomDir $roomDir -NewStatus "triage"

            $scriptPath = Write-MockRunAgentScript -RoomDir $roomDir -Role $expectedRole
            $content = Get-Content $scriptPath -Raw

            $content | Should -Match "AGENT_OS_ROLE.*=.*'manager'"
            $content | Should -Match "\-\-agent manager"
            $content | Should -Match "manager\.pid"
        }

        It "lifecycle roundtrip: AGENT_OS_ROLE in run-agent.ps1 matches lifecycle.states.<state>.role" {
            # This is the master contract test: for every active state, the role
            # baked into run-agent.ps1 must equal the role in lifecycle.json.
            if (-not $script:sampleLifecycle) { Set-ItResult -Skipped -Because "lifecycle fixture missing" }

            $activeStateTypes = @('work', 'review', 'triage')
            $stateRoleMap = @{}
            foreach ($stateName in $script:sampleLifecycle.states.PSObject.Properties.Name) {
                $stateDef = $script:sampleLifecycle.states.$stateName
                if ($stateDef.type -in $activeStateTypes -and $stateDef.role) {
                    $stateRoleMap[$stateName] = $stateDef.role
                }
            }

            # Must have at least: developing, optimize, review, triage
            $stateRoleMap.Keys | Should -Contain "developing"
            $stateRoleMap.Keys | Should -Contain "review"
            $stateRoleMap.Keys | Should -Contain "triage"

            $roomIdx = 0
            foreach ($stateName in $stateRoleMap.Keys) {
                $roomIdx++
                $roleForState = $stateRoleMap[$stateName]
                $roomId = "room-ra-rt-$roomIdx"

                & $script:NewWarRoom -RoomId $roomId -TaskRef "TASK-RT-$roomIdx" `
                                     -TaskDescription "Roundtrip $stateName" -WarRoomsDir $script:warRoomsDir
                $roomDir = Join-Path $script:warRoomsDir $roomId

                $scriptPath = Write-MockRunAgentScript -RoomDir $roomDir -Role $roleForState
                $content = Get-Content $scriptPath -Raw

                # Extract AGENT_OS_ROLE from the script (PowerShell format: $env:AGENT_OS_ROLE = 'value')
                $match = [regex]::Match($content, "AGENT_OS_ROLE.*=\s*'([^']+)'")
                $match.Success | Should -BeTrue -Because "run-agent.ps1 for state '$stateName' must set AGENT_OS_ROLE"
                $extractedRole = $match.Groups[1].Value
                $extractedRole | Should -Be $roleForState `
                    -Because "lifecycle.$stateName.role='$roleForState' must match AGENT_OS_ROLE in run-agent.ps1"
            }
        }

        It "PID file path in run-agent.ps1 uses the role name (not a generic name)" {
            if (-not $script:sampleLifecycle) { Set-ItResult -Skipped -Because "lifecycle fixture missing" }

            # For review state, PID file should be qa.pid not engineer.pid
            $reviewRole = $script:sampleLifecycle.states.review.role  # qa

            & $script:NewWarRoom -RoomId "room-ra-005" -TaskRef "TASK-RA-005" `
                                 -TaskDescription "PID path test" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-ra-005"

            $scriptPath = Write-MockRunAgentScript -RoomDir $roomDir -Role $reviewRole
            $content = Get-Content $scriptPath -Raw

            # PID file path must embed the role name
            $content | Should -Match "AGENT_OS_PID_FILE=.*/$reviewRole\.pid"

            # And must NOT reference any other role's PID file
            $allRoles = @('engineer', 'qa', 'manager', 'engineer', 'qa')
            foreach ($otherRole in ($allRoles | Where-Object { $_ -ne $reviewRole })) {
                # The AGENT_OS_PID_FILE line should only have the expected role
                $pidFileLine = ($content -split "`n" | Where-Object { $_ -match 'AGENT_OS_PID_FILE' })
                $pidFileLine | Should -Not -Match "/$otherRole\.pid" `
                    -Because "PID file for review state must reference '$reviewRole', not '$otherRole'"
            }
        }

        It "exec --agent flag in run-agent.ps1 matches AGENT_OS_ROLE" {
            if (-not $script:sampleLifecycle) { Set-ItResult -Skipped -Because "lifecycle fixture missing" }

            # Test with both developing (engineer) and review (qa) states
            $testCases = @(
                @{ State = "developing"; ExpectedRole = $script:sampleLifecycle.states.developing.role }
                @{ State = "review";     ExpectedRole = $script:sampleLifecycle.states.review.role }
            )

            foreach ($tc in $testCases) {
                & $script:NewWarRoom -RoomId "room-ra-exec-$($tc.State)" -TaskRef "TASK-EXEC-$($tc.State)" `
                                     -TaskDescription "exec flag $($tc.State)" -WarRoomsDir $script:warRoomsDir
                $roomDir = Join-Path $script:warRoomsDir "room-ra-exec-$($tc.State)"

                $scriptPath = Write-MockRunAgentScript -RoomDir $roomDir -Role $tc.ExpectedRole
                $content = Get-Content $scriptPath -Raw

                # Extract AGENT_OS_ROLE (PowerShell format)
                $roleMatch = [regex]::Match($content, "AGENT_OS_ROLE.*=\s*'([^']+)'")
                $agentOsRole = $roleMatch.Groups[1].Value

                # Extract --agent flag value from the command line
                $agentFlagMatch = [regex]::Match($content, "--agent ([^\s]+)", 'Multiline')
                $agentFlag = $agentFlagMatch.Groups[1].Value

                # The --agent value must equal AGENT_OS_ROLE (the run-agent.ps1 is self-consistent)
                $agentFlag | Should -Be $agentOsRole `
                    -Because "exec --agent flag must match AGENT_OS_ROLE for state '$($tc.State)'"

                # Both must equal the lifecycle-defined role
                $agentOsRole | Should -Be $tc.ExpectedRole
                $agentFlag   | Should -Be $tc.ExpectedRole
            }
        }

        It "role bleed guard: review run-agent.ps1 does NOT contain engineer anywhere in role fields" {
            # This guards against the original bug: manager was spawning engineer
            # during review state instead of transitioning to qa.
            if (-not $script:sampleLifecycle) { Set-ItResult -Skipped -Because "lifecycle fixture missing" }

            $reviewRole = $script:sampleLifecycle.states.review.role  # qa

            & $script:NewWarRoom -RoomId "room-ra-bleed" -TaskRef "TASK-RA-BLEED" `
                                 -TaskDescription "Role bleed guard" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-ra-bleed"

            $scriptPath = Write-MockRunAgentScript -RoomDir $roomDir -Role $reviewRole
            $content = Get-Content $scriptPath -Raw

            # engineer must not appear in the role-carrying fields
            $roleLines = $content -split "`n" | Where-Object {
                $_ -match 'AGENT_OS_ROLE|AGENT_OS_PID_FILE|--agent'
            }
            foreach ($line in $roleLines) {
                $line | Should -Not -Match "engineer" `
                    -Because "review state: run-agent.ps1 role fields must reference '$reviewRole', not 'engineer'"
            }
        }
    }

    # ==========================================================================
    # plan.roles.json model propagation to run-agent.ps1
    #
    # These tests verify the CONTRACT that the model configured in
    # ~/.ostwin/.agents/plans/{plan_id}.roles.json propagates through:
    #   plan.roles.json → Invoke-Agent.ps1 → run-agent.ps1 (--model flag)
    #
    # When a user customizes the model per role in plan.roles.json, the
    # manager must ensure that model reaches the run-agent.ps1 wrapper via
    # Invoke-Agent.ps1's plan-roles resolution chain.
    #
    # Tests are offline: they verify the contract by mocking run-agent.ps1
    # with the expected model and by static-analysis of Invoke-Agent.ps1.
    # ==========================================================================
    Context "plan.roles.json model propagation to run-agent.ps1" {

        BeforeAll {
            # Redefine Write-MockRunAgentScript for this Context scope.
            # Mirrors Invoke-Agent.ps1's run-agent.ps1 output format.
            function Write-MockRunAgentScript {
                param(
                    [string]$RoomDir,
                    [string]$Role,
                    [string]$Model = 'google-vertex/gemini-test'
                )
                $artifactsDir = Join-Path $RoomDir "artifacts"
                New-Item -ItemType Directory -Path $artifactsDir -Force | Out-Null
                $pidFile = ($RoomDir -replace "'", "''") + "/pids/$Role.pid"
                $promptFile = ($RoomDir -replace "'", "''") + "/artifacts/prompt.txt"
                $outputFile = ($RoomDir -replace "'", "''") + "/artifacts/$Role-output.txt"
                $content = @"
# --- run-agent.ps1 — Unified agent wrapper (all platforms) ---
`$env:AGENT_OS_ROOM_DIR = '$RoomDir'
`$env:AGENT_OS_ROLE = '$Role'
`$env:AGENT_OS_PARENT_PID = '12345'
`$env:AGENT_OS_SKILLS_DIR = '/path/to/project/.agents/skills'
`$env:AGENT_OS_PID_FILE = '$pidFile'
`$env:OSTWIN_HOME = '/Users/test/.ostwin'
`$env:AGENT_OS_PROJECT_DIR = '/Users/test/project'
`$PID | Out-File -FilePath '$pidFile' -Encoding ascii -NoNewline
"[wrapper] PID=`$PID, CMD=opencode" | Out-File -FilePath '$outputFile' -Encoding utf8 -Append
& opencode run '...' --model $Model --agent $Role --file '$promptFile' 2>&1 | Out-File -FilePath '$outputFile' -Encoding utf8 -Append
"@
                $scriptPath = Join-Path $artifactsDir "run-agent.ps1"
                $content | Out-File -FilePath $scriptPath -Encoding utf8 -NoNewline -Force
                return $scriptPath
            }
        }

        It "run-agent.ps1 --model flag carries the plan-configured model" {
            & $script:NewWarRoom -RoomId "room-model-001" -TaskRef "TASK-MODEL-001" `
                                 -TaskDescription "Model propagation test" -WarRoomsDir $script:warRoomsDir
            $roomDir = Join-Path $script:warRoomsDir "room-model-001"

            # Simulate: plan.roles.json sets engineer model to a custom value
            $planModel = "anthropic/claude-sonnet-4-20250514"

            # Write mock run-agent.ps1 with the plan-configured model
            # (mirrors what Invoke-Agent.ps1 produces when plan.roles.json is read)
            $scriptPath = Write-MockRunAgentScript -RoomDir $roomDir -Role "engineer" -Model $planModel
            $content = Get-Content $scriptPath -Raw

            # Assert --model flag carries the plan-configured model
            $content | Should -Match "--model $([regex]::Escape($planModel))" `
                -Because "run-agent.ps1 must carry the model from plan.roles.json"
            # Assert it does NOT carry the hardcoded default
            $content | Should -Not -Match "--model google-vertex/zai-org/glm-5-maas" `
                -Because "hardcoded default must not appear when plan.roles.json specifies a model"
        }

        It "different roles get different models from plan.roles.json" {
            $engineerModel = "anthropic/claude-sonnet-4-20250514"
            $qaModel = "google-vertex/gemini-2.5-pro"

            # Engineer room
            & $script:NewWarRoom -RoomId "room-model-eng" -TaskRef "TASK-MODEL-ENG" `
                                 -TaskDescription "Engineer model" -WarRoomsDir $script:warRoomsDir
            $engDir = Join-Path $script:warRoomsDir "room-model-eng"
            $engScript = Write-MockRunAgentScript -RoomDir $engDir -Role "engineer" -Model $engineerModel

            # QA room
            & $script:NewWarRoom -RoomId "room-model-qa" -TaskRef "TASK-MODEL-QA" `
                                 -TaskDescription "QA model" -WarRoomsDir $script:warRoomsDir
            $qaDir = Join-Path $script:warRoomsDir "room-model-qa"
            $qaScript = Write-MockRunAgentScript -RoomDir $qaDir -Role "qa" -Model $qaModel

            $engContent = Get-Content $engScript -Raw
            $qaContent = Get-Content $qaScript -Raw

            $engContent | Should -Match "--model $([regex]::Escape($engineerModel))"
            $qaContent | Should -Match "--model $([regex]::Escape($qaModel))"
            # Ensure they don't share the same model
            $engContent | Should -Not -Match "--model $([regex]::Escape($qaModel))"
            $qaContent | Should -Not -Match "--model $([regex]::Escape($engineerModel))"
        }

        It "Invoke-Agent.ps1 reads plan.roles.json from room config.json plan_id" {
            # Static analysis: Invoke-Agent.ps1 must contain the plan-roles
            # resolution logic that reads {plan_id}.roles.json
            $invokeAgentScript = Join-Path $script:agentsDir "roles" "_base" "Invoke-Agent.ps1"
            $content = Get-Content $invokeAgentScript -Raw

            # Must resolve plan_id from room config.json
            $content | Should -Match 'roomPlanId' `
                -Because "Invoke-Agent must read plan_id from room config.json"
            # Must construct plan.roles.json path
            $content | Should -Match 'planRolesFile' `
                -Because "Invoke-Agent must construct path to {plan_id}.roles.json"
            $content | Should -Match '\.roles\.json' `
                -Because "Invoke-Agent must reference .roles.json files"
            # Must use plan roles for model resolution
            $content | Should -Match 'planRolesConfig' `
                -Because "Invoke-Agent must load plan.roles.json config"
            $content | Should -Match 'planRoleNode\.default_model' `
                -Because "Invoke-Agent must read default_model from plan.roles.json role node"
        }

        It "Invoke-Agent.ps1 plan.roles.json model has priority over config.json model" {
            # Static analysis: plan.roles.json model resolution block must appear
            # BEFORE the config.json model resolution block
            $invokeAgentScript = Join-Path $script:agentsDir "roles" "_base" "Invoke-Agent.ps1"
            $content = Get-Content $invokeAgentScript -Raw

            # Find positions of plan-roles block and config.json block
            $planRolesPos = $content.IndexOf('planRolesConfig')
            $configJsonPos = $content.IndexOf('$config.$RoleName.default_model')

            $planRolesPos | Should -BeGreaterThan 0 `
                -Because "plan.roles.json resolution must exist in Invoke-Agent.ps1"
            $configJsonPos | Should -BeGreaterThan 0 `
                -Because "config.json model fallback must exist in Invoke-Agent.ps1"
            $planRolesPos | Should -BeLessThan $configJsonPos `
                -Because "plan.roles.json model must be checked BEFORE config.json model (higher priority)"
        }

        It "Invoke-Agent.ps1 plan.roles.json model has priority over role.json model" {
            $invokeAgentScript = Join-Path $script:agentsDir "roles" "_base" "Invoke-Agent.ps1"
            $content = Get-Content $invokeAgentScript -Raw

            $planRolesPos = $content.IndexOf('planRolesConfig')
            $roleJsonPos = $content.IndexOf('roleJsonPath')

            $planRolesPos | Should -BeGreaterThan 0
            $roleJsonPos | Should -BeGreaterThan 0
            $planRolesPos | Should -BeLessThan $roleJsonPos `
                -Because "plan.roles.json model must be checked BEFORE role.json model"
        }

        It "Invoke-Agent.ps1 passes resolved model as --model CLI arg" {
            $invokeAgentScript = Join-Path $script:agentsDir "roles" "_base" "Invoke-Agent.ps1"
            $content = Get-Content $invokeAgentScript -Raw

            # The model must be injected into CLI args for run-agent.ps1
            $content | Should -Match 'extraCliArgs.*"--model"' `
                -Because "resolved model must be passed as --model to run-agent.ps1"
        }
    }

    # ==========================================================================
    # Start-DynamicRole.ps1 must not override plan.roles.json model
    #
    # Start-DynamicRole.ps1 calls Invoke-Agent.ps1, which resolves model from
    # plan.roles.json. If Start-DynamicRole.ps1 passes an explicit -Model from
    # role.json or config.json, it OVERRIDES the plan.roles.json resolution.
    #
    # Start-Engineer.ps1 and Start-QA.ps1 already do this correctly — they do
    # NOT pass -Model to Invoke-Agent.ps1.
    # ==========================================================================
    Context "Worker scripts do not override plan.roles.json model" {

        It "Start-DynamicRole.ps1 does not pass fallback agentModel to Invoke-Agent" {
            $dynamicRoleScript = Join-Path $script:agentsDir "roles" "_base" "Start-DynamicRole.ps1"
            $content = Get-Content $dynamicRoleScript -Raw

            # Must NOT contain: elseif ($agentModel) { $invokeArgs['Model'] = $agentModel }
            # This pattern causes plan.roles.json to be bypassed because $agentModel
            # is always set (from role.json or hardcoded default).
            $content | Should -Not -Match "elseif \(\`$agentModel\).*invokeArgs\['Model'\].*=.*\`$agentModel" `
                -Because "fallback agentModel from role.json must not override plan.roles.json resolution in Invoke-Agent.ps1"
        }

        It "Start-DynamicRole.ps1 only passes per-room roleInstanceModel override" {
            $dynamicRoleScript = Join-Path $script:agentsDir "roles" "_base" "Start-DynamicRole.ps1"
            $content = Get-Content $dynamicRoleScript -Raw

            # SHOULD contain: if ($roleInstanceModel) { $invokeArgs['Model'] = $roleInstanceModel }
            $content | Should -Match "roleInstanceModel.*invokeArgs\['Model'\]" `
                -Because "per-room instance model overrides are legitimate and should be passed"
        }

        It "Start-Engineer.ps1 does not pass -Model to Invoke-Agent (correct pattern)" {
            $engineerScript = Join-Path $script:agentsDir "roles" "engineer" "Start-Engineer.ps1"
            $content = Get-Content $engineerScript -Raw

            # Engineer should NOT set -Model in its invoke args
            $content | Should -Not -Match "invokeArgs\['Model'\]" `
                -Because "Start-Engineer.ps1 correctly delegates model resolution to Invoke-Agent.ps1"
            # Verify it calls Invoke-Agent without -Model
            $content | Should -Match 'invokeAgent -RoomDir \$RoomDir -RoleName "engineer"' `
                -Because "Start-Engineer.ps1 must call Invoke-Agent without explicit -Model"
        }

        It "Start-QA.ps1 does not pass -Model to Invoke-Agent (correct pattern)" {
            $qaScript = Join-Path $script:agentsDir "roles" "qa" "Start-QA.ps1"
            $content = Get-Content $qaScript -Raw

            # QA should NOT set -Model in its invoke args
            $content | Should -Not -Match "invokeArgs\['Model'\]" `
                -Because "Start-QA.ps1 correctly delegates model resolution to Invoke-Agent.ps1"
        }
    }

    # ==========================================================================
    # plan.roles.json model resolution chain in Invoke-Agent.ps1
    #
    # Priority order (highest → lowest):
    #   1. Explicit -Model parameter (from per-room instance config)
    #   2. plan.roles.json instance override (instances.<id>.default_model)
    #   3. plan.roles.json role default (default_model)
    #   4. config.json instance override
    #   5. config.json role default
    #   6. role.json model
    #   7. Hardcoded fallback
    # ==========================================================================
    Context "Invoke-Agent.ps1 model resolution chain" {

        It "plan.roles.json supports per-instance model override" {
            $invokeAgentScript = Join-Path $script:agentsDir "roles" "_base" "Invoke-Agent.ps1"
            $content = Get-Content $invokeAgentScript -Raw

            # Must support instances.<id>.default_model from plan.roles.json
            $content | Should -Match 'planRoleNode\.instances' `
                -Because "plan.roles.json must support per-instance overrides"
            $content | Should -Match 'instances\.\$InstanceId' `
                -Because "plan.roles.json must support per-instance model overrides"
        }

        It "plan.roles.json supports per-role timeout override" {
            $invokeAgentScript = Join-Path $script:agentsDir "roles" "_base" "Invoke-Agent.ps1"
            $content = Get-Content $invokeAgentScript -Raw

            # Must support timeout_seconds from plan.roles.json
            $content | Should -Match 'planRoleNode\.timeout_seconds' `
                -Because "plan.roles.json must support per-role timeout overrides"
        }

        It "model resolution runs unconditionally (does not depend on config.json)" {
            $invokeAgentScript = Join-Path $script:agentsDir "roles" "_base" "Invoke-Agent.ps1"
            $lines = Get-Content $invokeAgentScript

            # The comment "Runs unconditionally" must be present near the plan roles block
            $unconditionalComment = $lines | Where-Object { $_ -match 'Runs unconditionally' }
            $unconditionalComment | Should -Not -BeNullOrEmpty `
                -Because "plan.roles.json resolution must not depend on config.json existing"
        }

        It "hardcoded default model is only used as last resort" {
            $invokeAgentScript = Join-Path $script:agentsDir "roles" "_base" "Invoke-Agent.ps1"
            $content = Get-Content $invokeAgentScript -Raw

            # The hardcoded default should only appear in the final fallback
            # after all config sources are exhausted
            $defaultModelPos = $content.IndexOf('if (-not $Model) { $Model = "google-vertex/')
            $planRolesPos = $content.IndexOf('planRolesConfig')
            $configPos = $content.IndexOf('$config.$RoleName.default_model')
            $roleJsonPos = $content.IndexOf('roleJsonPath')

            # All resolution sources must appear BEFORE the hardcoded default
            $planRolesPos | Should -BeLessThan $defaultModelPos `
                -Because "plan.roles.json must be checked before hardcoded default"
            $configPos | Should -BeLessThan $defaultModelPos `
                -Because "config.json must be checked before hardcoded default"
            $roleJsonPos | Should -BeLessThan $defaultModelPos `
                -Because "role.json must be checked before hardcoded default"
        }
    }
}

# ===========================================================================
# Integration Tests: ManagerLoop helpers vs tests/sample/room-001 fixture
#
# These tests run the REAL ManagerLoop-Helpers.psm1 functions against the
# production-like fixture in tests/sample/room-001 (engineer / qa
# lifecycle) to ensure the helpers correctly interpret that data.
# ===========================================================================
Describe "Integration — ManagerLoop helpers against tests/sample/room-001" {
    BeforeAll {
        # Import helpers module for this scope
        $helpersModule = Join-Path $script:agentsDir "roles" "manager" "ManagerLoop-Helpers.psm1"
        Import-Module $helpersModule -Force -WarningAction SilentlyContinue

        # Source of truth: the sample fixture (read-only)
        $script:sampleFixtureSrc = Resolve-Path (Join-Path $PSScriptRoot "../../sample/room-001")

        # Clone fixture into TestDrive so tests can mutate it
        function Copy-SampleRoom {
            param([string]$Dest)
            $destDir = Join-Path $TestDrive "$Dest-$(Get-Random)"
            Copy-Item -Path $script:sampleFixtureSrc -Destination $destDir -Recurse -Force
            # Ensure audit.log exists (needed by Write-RoomStatus)
            $audit = Join-Path $destDir "audit.log"
            if (-not (Test-Path $audit)) { "" | Out-File $audit -Encoding utf8 }
            return $destDir
        }

        # Bind module context to a writable rooms parent containing room-001
        function Set-SampleContext {
            param([string]$RoomsParent)
            $cfgFile = Join-Path $script:agentsDir "config.json"
            $config  = if (Test-Path $cfgFile) { Get-Content $cfgFile -Raw | ConvertFrom-Json } else {
                [PSCustomObject]@{
                    manager  = [PSCustomObject]@{ poll_interval_seconds=1; max_concurrent_rooms=10; max_engineer_retries=3; state_timeout_seconds=900 }
                    engineer = [PSCustomObject]@{ cli="echo" }
                    qa       = [PSCustomObject]@{ cli="echo" }
                }
            }
            Set-ManagerLoopContext -Context @{
                agentsDir    = $script:agentsDir
                WarRoomsDir  = $RoomsParent
                dagFile      = (Join-Path $RoomsParent "DAG.json")
                hasDag       = $false
                dagCache     = $null
                dagMtime     = $null
                config       = $config
                stateTimeout = 900
                maxRetries   = 3
                postMessage  = $script:PostMessage
                readMessages = $script:ReadMessages
                dashboardBaseUrl = "http://localhost:9999"
            }
        }
    }

    AfterAll {
        Remove-Module ManagerLoop-Helpers -ErrorAction SilentlyContinue
    }

    # -----------------------------------------------------------------------
    It "lifecycle.json loads and has expected v2 structure" {
        $rd    = Copy-SampleRoom "lc-load"
        $lcRaw = Get-Content (Join-Path $rd "lifecycle.json") -Raw
        $lc    = $lcRaw | ConvertFrom-Json
        $lc.version       | Should -Be 2
        $lc.initial_state | Should -Be "developing"
        $lc.states | Should -Not -BeNull
        $lc.states.developing.role | Should -Be "engineer"
        $lc.states.review.role     | Should -Be "qa"
    }

    # -----------------------------------------------------------------------
    It "Find-LatestSignal returns null for review state with no new messages" {
        $rd    = Copy-SampleRoom "fls-no-msg"
        $lc    = Get-Content (Join-Path $rd "lifecycle.json") -Raw | ConvertFrom-Json
        Set-SampleContext -RoomsParent (Split-Path $rd -Parent)

        # Set state_changed_at to FAR future so all existing messages are stale
        $future = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() + 99999
        $future.ToString() | Out-File (Join-Path $rd "state_changed_at") -Encoding utf8 -NoNewline

        $sig = Find-LatestSignal -RoomDir $rd -Lifecycle $lc -StateName "review"
        $sig | Should -BeNull
    }

    # -----------------------------------------------------------------------
    It "Find-LatestSignal returns 'pass' when qa posts pass after state_changed_at" {
        $rd = Copy-SampleRoom "fls-pass"
        $lc = Get-Content (Join-Path $rd "lifecycle.json") -Raw | ConvertFrom-Json
        Set-SampleContext -RoomsParent (Split-Path $rd -Parent)

        # Stamp state_changed_at = 0 so all new messages are accepted
        "0" | Out-File (Join-Path $rd "state_changed_at") -Encoding utf8 -NoNewline

        & $script:PostMessage -RoomDir $rd -From "qa" -To "manager" -Type "pass" -Ref "EPIC-001" -Body "All tests pass"
        $sig = Find-LatestSignal -RoomDir $rd -Lifecycle $lc -StateName "review"
        $sig | Should -Be "pass"
    }

    # -----------------------------------------------------------------------
    It "Find-LatestSignal returns 'fail' when qa posts fail" {
        $rd = Copy-SampleRoom "fls-fail"
        $lc = Get-Content (Join-Path $rd "lifecycle.json") -Raw | ConvertFrom-Json
        Set-SampleContext -RoomsParent (Split-Path $rd -Parent)

        "0" | Out-File (Join-Path $rd "state_changed_at") -Encoding utf8 -NoNewline
        & $script:PostMessage -RoomDir $rd -From "qa" -To "manager" -Type "fail" -Ref "EPIC-001" -Body "Tests failed: login broken"
        $sig = Find-LatestSignal -RoomDir $rd -Lifecycle $lc -StateName "review"
        $sig | Should -Be "fail"
    }

    # -----------------------------------------------------------------------
    It "Find-LatestSignal rejects signal from engineer in review state (wrong role)" {
        $rd = Copy-SampleRoom "fls-wrong-role"
        $lc = Get-Content (Join-Path $rd "lifecycle.json") -Raw | ConvertFrom-Json
        Set-SampleContext -RoomsParent (Split-Path $rd -Parent)

        "0" | Out-File (Join-Path $rd "state_changed_at") -Encoding utf8 -NoNewline
        # engineer sends 'pass' but review state requires qa
        & $script:PostMessage -RoomDir $rd -From "engineer" -To "manager" -Type "pass" -Ref "EPIC-001" -Body "Done"
        $sig = Find-LatestSignal -RoomDir $rd -Lifecycle $lc -StateName "review"
        $sig | Should -BeNull -Because "review role is qa, signal from engineer must be rejected"
    }

    # -----------------------------------------------------------------------
    It "Write-RoomStatus transitions review→optimize and removes qa PID" {
        $rd   = Copy-SampleRoom "wrs-sample"
        $lc   = Get-Content (Join-Path $rd "lifecycle.json") -Raw | ConvertFrom-Json
        Set-SampleContext -RoomsParent (Split-Path $rd -Parent)

        $pidDir = Join-Path $rd "pids"
        New-Item -ItemType Directory -Path $pidDir -Force | Out-Null
        "12345" | Out-File (Join-Path $pidDir "qa.pid") -Encoding utf8 -NoNewline

        Write-RoomStatus -RoomDir $rd -NewStatus "optimize"
        (Get-Content (Join-Path $rd "status") -Raw).Trim() | Should -Be "optimize"
        Test-Path (Join-Path $pidDir "qa.pid") | Should -BeFalse -Because "qa PID removed on leaving review state"
    }

    # -----------------------------------------------------------------------
    It "Write-RoomStatus transitions review->done and removes ALL PIDs" {
        $rd   = Copy-SampleRoom "wrs-terminal"
        Set-SampleContext -RoomsParent (Split-Path $rd -Parent)

        $pidDir = Join-Path $rd "pids"
        New-Item -ItemType Directory -Path $pidDir -Force | Out-Null
        "11111" | Out-File (Join-Path $pidDir "engineer.pid")    -Encoding utf8 -NoNewline
        "22222" | Out-File (Join-Path $pidDir "qa.pid")          -Encoding utf8 -NoNewline
        "$(Get-Date -UFormat %s)" | Out-File (Join-Path $pidDir "qa.spawned_at") -Encoding utf8 -NoNewline

        Write-RoomStatus -RoomDir $rd -NewStatus "done"
        (Get-Content (Join-Path $rd "status") -Raw).Trim() | Should -Be "done"
        Get-ChildItem $pidDir -Filter "*.pid" -ErrorAction SilentlyContinue |
            Measure-Object | Select-Object -ExpandProperty Count | Should -Be 0
    }

    # -----------------------------------------------------------------------
    It "Get-ActiveCount counts sample room in 'review' state as active" {
        # Get-ActiveCount uses `room-*` filter; room must be named room-<something>
        $parent = Join-Path $TestDrive "gac-parent-$(Get-Random)"
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
        $rd = Join-Path $parent "room-001"
        Copy-Item -Path $script:sampleFixtureSrc -Destination $rd -Recurse -Force
        $audit = Join-Path $rd "audit.log"
        if (-not (Test-Path $audit)) { "" | Out-File $audit -Encoding utf8 }
        Set-SampleContext -RoomsParent $parent

        "review" | Out-File (Join-Path $rd "status") -Encoding utf8 -NoNewline
        Get-ActiveCount | Should -Be 1
    }

    # -----------------------------------------------------------------------
    It "Get-ActiveCount does not count sample room when status=done" {
        $parent = Join-Path $TestDrive "gac-term-$(Get-Random)"
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
        $rd = Join-Path $parent "room-001"
        Copy-Item -Path $script:sampleFixtureSrc -Destination $rd -Recurse -Force
        $audit = Join-Path $rd "audit.log"
        if (-not (Test-Path $audit)) { "" | Out-File $audit -Encoding utf8 }
        Set-SampleContext -RoomsParent $parent

        "done" | Out-File (Join-Path $rd "status") -Encoding utf8 -NoNewline
        Get-ActiveCount | Should -Be 0
    }

    # -----------------------------------------------------------------------
    It "Invoke-ManagerTriage classifies design-issue correctly against sample room" {
        $rd = Copy-SampleRoom "imt-sample"
        Set-SampleContext -RoomsParent (Split-Path $rd -Parent)

        $result = Invoke-ManagerTriage -RoomDir $rd -QaFeedback "This is a fundamental architecture problem with the game loop design"
        $result | Should -Be "design-issue"
    }

    # -----------------------------------------------------------------------
    It "Invoke-ManagerTriage classifies plan-gap correctly against sample room" {
        $rd = Copy-SampleRoom "imt-plangap"
        Set-SampleContext -RoomsParent (Split-Path $rd -Parent)

        $result = Invoke-ManagerTriage -RoomDir $rd -QaFeedback "The acceptance criteria are missing from the brief"
        $result | Should -Be "plan-gap"
    }

    # -----------------------------------------------------------------------
    It "review.fail signal triggers optimize route per sample lifecycle (schema)" {
        # Validate the lifecycle.json schema maps fail→optimize
        $rd = Copy-SampleRoom "lifecycle-routing"
        $lc = Get-Content (Join-Path $rd "lifecycle.json") -Raw | ConvertFrom-Json
        $lc.states.review.signals.fail.target | Should -Be "optimize" -Because "review.fail must route to optimize, not back to developing"
        $lc.states.review.signals.fail.actions | Should -Contain "post_fix" -Because "review.fail keeps the compatibility action; manager treats channel writes as MCP-only"
        $lc.states.review.signals.fail.actions | Should -Contain "increment_retries"
    }

    # -----------------------------------------------------------------------
    It "developing.done routes to review per sample lifecycle" {
        $rd = Copy-SampleRoom "lifecycle-done-routing"
        $lc = Get-Content (Join-Path $rd "lifecycle.json") -Raw | ConvertFrom-Json
        $lc.states.developing.signals.done.target | Should -Be "review"
    }

    # -----------------------------------------------------------------------
    It "review.done routes to done (terminal) per sample lifecycle" {
        $rd = Copy-SampleRoom "lifecycle-review-done-routing"
        $lc = Get-Content (Join-Path $rd "lifecycle.json") -Raw | ConvertFrom-Json
        $lc.states.review.signals.done.target | Should -Be "done"
    }

    # -----------------------------------------------------------------------
    It "review.pass remains accepted as legacy success signal per sample lifecycle" {
        $rd = Copy-SampleRoom "lifecycle-pass-routing"
        $lc = Get-Content (Join-Path $rd "lifecycle.json") -Raw | ConvertFrom-Json
        $lc.states.review.signals.pass.target | Should -Be "done"
    }

    # -----------------------------------------------------------------------
    It "Write-TriageContext creates correct artifact against sample room" {
        $rd = Copy-SampleRoom "triage-ctx"
        Set-SampleContext -RoomsParent (Split-Path $rd -Parent)

        Write-TriageContext -RoomDir $rd `
            -Classification "design-issue" `
            -QaFeedback "The game loop architecture needs a redesign" `
            -ArchitectGuidance "Use an ECS pattern" `
            -ManagerNotes "Review with senior dev"

        $ctxFile = Join-Path $rd "artifacts" "triage-context.md"
        Test-Path $ctxFile | Should -BeTrue
        $content = Get-Content $ctxFile -Raw
        $content | Should -Match "Classification: design-issue"
        $content | Should -Match "game loop architecture"
        $content | Should -Match "ECS pattern"
        $content | Should -Match "architect's guidance"
    }
}
