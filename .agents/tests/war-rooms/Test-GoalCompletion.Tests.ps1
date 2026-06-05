# Agent OS — Test-GoalCompletion Pester Tests

BeforeAll {
    $script:TestGoalCompletion = Join-Path (Resolve-Path "$PSScriptRoot/../../war-rooms").Path "Test-GoalCompletion.ps1"
    $script:NewWarRoom = Join-Path (Resolve-Path "$PSScriptRoot/../../war-rooms").Path "New-WarRoom.ps1"
    $script:agentsDir = Split-Path (Resolve-Path "$PSScriptRoot/../../war-rooms").Path
    . (Join-Path $script:agentsDir "tests" "TestChannelHelpers.ps1")
    $script:PostMessage = New-TestChannelWriter
}

Describe "Test-GoalCompletion" {
    BeforeEach {
        $script:warRoomsDir = Join-Path $TestDrive "wr-$(Get-Random)"
        New-Item -ItemType Directory -Path $script:warRoomsDir -Force | Out-Null
    }

    BeforeAll {
        function New-TestRoom {
            param(
                [string]$RoomId,
                [string[]]$DoD = @(),
                [string[]]$AC = @(),
                [string]$EngOutput = "",
                [string]$TasksMd = ""
            )
            & $script:NewWarRoom -RoomId $RoomId -TaskRef "TASK-TEST" `
                                 -TaskDescription "Test goal verification" `
                                 -WarRoomsDir $script:warRoomsDir `
                                 -DefinitionOfDone $DoD `
                                 -AcceptanceCriteria $AC | Out-Null

            $roomDir = Join-Path $script:warRoomsDir $RoomId
            if ($EngOutput) {
                $EngOutput | Out-File (Join-Path $roomDir "artifacts" "engineer-output.txt") -Encoding utf8
            }
            if ($TasksMd) {
                $TasksMd | Out-File (Join-Path $roomDir "TASKS.md") -Encoding utf8
            }
            return [string]$roomDir
        }
    }

    Context "All goals met" {
        It "passes when all DoD goals match evidence" {
            $roomDir = New-TestRoom -RoomId "room-g01" `
                -DoD @("JWT token generation working", "Tests passing with 80% coverage") `
                -EngOutput "Implemented JWT token generation working perfectly. Tests passing with 80% coverage achieved."

            $result = & $script:TestGoalCompletion -RoomDir $roomDir
            $result.OverallStatus | Should -Be "passed"
            $result.Summary.met | Should -Be 2
            $result.Summary.not_met | Should -Be 0
        }

        It "passes when all AC goals match" {
            $roomDir = New-TestRoom -RoomId "room-g02" `
                -AC @("POST /login returns 200", "Protected routes reject invalid tokens") `
                -EngOutput "POST /login returns 200 with valid JWT. Protected routes reject invalid tokens with 401."

            $result = & $script:TestGoalCompletion -RoomDir $roomDir
            $result.OverallStatus | Should -Be "passed"
        }

        It "returns score of 1.0 for exact matches" {
            $roomDir = New-TestRoom -RoomId "room-g03" `
                -DoD @("feature complete") `
                -EngOutput "The feature complete and deployed."

            $result = & $script:TestGoalCompletion -RoomDir $roomDir
            $result.Score | Should -Be 1.0
        }
    }

    Context "Goals not met" {
        It "fails when DoD goals don't match evidence" {
            $roomDir = New-TestRoom -RoomId "room-g10" `
                -DoD @("WebSocket real-time updates", "GraphQL API integration") `
                -EngOutput "Added a REST API endpoint for user login."

            $result = & $script:TestGoalCompletion -RoomDir $roomDir
            $result.OverallStatus | Should -Not -Be "passed"
            $result.Summary.not_met | Should -BeGreaterThan 0
        }

        It "reports not_met for completely unrelated evidence" {
            $roomDir = New-TestRoom -RoomId "room-g11" `
                -DoD @("Kubernetes cluster deployment") `
                -EngOutput "Fixed a CSS typo in the footer."

            $result = & $script:TestGoalCompletion -RoomDir $roomDir
            $goals = $result.GoalResults
            $goals[0].status | Should -Be "not_met"
        }
    }

    Context "Partial goals" {
        It "detects partial match when some key terms present" {
            $roomDir = New-TestRoom -RoomId "room-g20" `
                -DoD @("JWT authentication with refresh token support") `
                -EngOutput "Implemented JWT authentication. Refresh token is planned for next sprint."

            $result = & $script:TestGoalCompletion -RoomDir $roomDir
            # Should have match from "JWT" and "authentication" terms
            $result.GoalResults[0].status | Should -BeIn @("met", "partial")
        }
    }

    Context "Mixed goals" {
        It "reports mixed results (some met, some not)" {
            $roomDir = New-TestRoom -RoomId "room-g30" `
                -DoD @("Login page working", "Dashboard analytics") `
                -AC @("User can log in", "Charts render") `
                -EngOutput "Login page working with all validations. User can log in with email and password."

            $result = & $script:TestGoalCompletion -RoomDir $roomDir
            $result.Summary.met | Should -BeGreaterThan 0
            # "Dashboard analytics" and "Charts render" won't match
            $result.Summary.total | Should -Be 4
        }
    }

    Context "No goals defined" {
        It "auto-passes when no goals in config" {
            $roomDir = New-TestRoom -RoomId "room-g40" `
                -EngOutput "Did some work."

            $result = & $script:TestGoalCompletion -RoomDir $roomDir
            $result.OverallStatus | Should -Be "passed"
            $result.Summary.total | Should -Be 0
        }
    }

    Context "TASKS.md completion check" {
        It "marks task completion as met when all tasks checked" {
            $roomDir = New-TestRoom -RoomId "room-g50" `
                -TasksMd "- [x] TASK-001 — Design`n- [x] TASK-002 — Implement`n- [x] TASK-003 — Test"

            $result = & $script:TestGoalCompletion -RoomDir $roomDir
            $taskGoal = $result.GoalResults | Where-Object { $_.category -eq "task_completion" }
            $taskGoal.status | Should -Be "met"
            $taskGoal.evidence | Should -Match "3/3"
        }

        It "marks task completion as partial when some tasks incomplete" {
            $roomDir = New-TestRoom -RoomId "room-g51" `
                -TasksMd "- [x] TASK-001 — Design`n- [ ] TASK-002 — Implement`n- [x] TASK-003 — Test"

            $result = & $script:TestGoalCompletion -RoomDir $roomDir
            $taskGoal = $result.GoalResults | Where-Object { $_.category -eq "task_completion" }
            $taskGoal.status | Should -Be "partial"
            $taskGoal.evidence | Should -Match "2/3"
        }

        It "marks task completion as not_met when no tasks checked" {
            $roomDir = New-TestRoom -RoomId "room-g52" `
                -TasksMd "- [ ] TASK-001 — Design`n- [ ] TASK-002 — Implement"

            $result = & $script:TestGoalCompletion -RoomDir $roomDir
            $taskGoal = $result.GoalResults | Where-Object { $_.category -eq "task_completion" }
            $taskGoal.status | Should -Be "not_met"
        }
    }

    Context "Evidence gathering" {
        It "uses channel messages as evidence" {
            $roomDir = New-TestRoom -RoomId "room-g60" `
                -DoD @("authentication module complete")

            # Seed a done message to the channel
            & $script:PostMessage -RoomDir $roomDir -From "engineer" -To "manager" `
                           -Type "done" -Ref "TASK-TEST" -Body "authentication module complete and tested"

            $result = & $script:TestGoalCompletion -RoomDir $roomDir
            $result.GoalResults[0].status | Should -Be "met"
        }

        It "uses custom EngineerOutput parameter" {
            $roomDir = New-TestRoom -RoomId "room-g61" `
                -DoD @("custom output verified")

            $result = & $script:TestGoalCompletion -RoomDir $roomDir `
                        -EngineerOutput "The custom output verified successfully."
            $result.GoalResults[0].status | Should -Be "met"
        }
    }

    Context "Result structure" {
        It "returns all expected properties" {
            $roomDir = New-TestRoom -RoomId "room-g70" `
                -DoD @("test goal")

            $result = & $script:TestGoalCompletion -RoomDir $roomDir
            $result.PSObject.Properties.Name | Should -Contain "OverallStatus"
            $result.PSObject.Properties.Name | Should -Contain "Score"
            $result.PSObject.Properties.Name | Should -Contain "GoalResults"
            $result.PSObject.Properties.Name | Should -Contain "Summary"
        }

        It "includes goal category in results" {
            $roomDir = New-TestRoom -RoomId "room-g71" `
                -DoD @("dod goal") `
                -AC @("ac goal")

            $result = & $script:TestGoalCompletion -RoomDir $roomDir
            $categories = $result.GoalResults | ForEach-Object { $_.category }
            $categories | Should -Contain "definition_of_done"
            $categories | Should -Contain "acceptance_criteria"
        }
    }

    Context "Error handling" {
        It "fails when config.json is missing" {
            $badRoom = Join-Path $TestDrive "no-config-room"
            New-Item -ItemType Directory -Path $badRoom -Force | Out-Null

            { & $script:TestGoalCompletion -RoomDir $badRoom } |
                Should -Throw "*config.json*"
        }
    }
}
