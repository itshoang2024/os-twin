# Agent OS — Lifecycle Role Transition Tests
# Covers: the bug where Invoke-Agent received 'engineer' when the
# lifecycle state required 'qa'. Regression tests for the role
# resolution fix in Start-DynamicRole.ps1 and Start-ManagerLoop.ps1.

# ---------------------------------------------------------------------------
# Helper module: written to TestDrive at discovery time so mock scripts can
# reference it during test execution.
# ---------------------------------------------------------------------------
BeforeAll {
    $script:agentsDir = (Resolve-Path (Join-Path (Resolve-Path "$PSScriptRoot/../../../roles/manager").Path ".." "..")).Path
    . (Join-Path $script:agentsDir "tests" "TestChannelHelpers.ps1")
    $script:PostMessage      = New-TestChannelWriter
    $script:ReadMessages     = Join-Path $script:agentsDir "channel"   "Read-Messages.ps1"
    $script:NewWarRoom       = Join-Path $script:agentsDir "war-rooms" "New-WarRoom.ps1"
    $script:StartDynamicRole = Join-Path $script:agentsDir "roles"     "_base" "Start-DynamicRole.ps1"

    $utilsModule = Join-Path $script:agentsDir "lib" "Utils.psm1"
    if (Test-Path $utilsModule) { Import-Module $utilsModule -Force }

    # --- Write the room-001-style lifecycle (engineer -> qa) ---
    function Write-GameLifecycle {
        param([string]$RoomDir)
        @{
            version       = 2
            initial_state = "developing"
            max_retries   = 3
            states        = @{
	                developing   = @{
	                    role    = "engineer"
	                    type    = "work"
	                    signals = @{
	                        done = @{ target = "review" }
	                    }
	                }
	                optimize     = @{
	                    role    = "engineer"
	                    type    = "work"
	                    signals = @{
	                        done = @{ target = "review" }
	                    }
	                }
	                review       = @{
	                    role    = "qa"
	                    type    = "review"
	                    signals = @{
	                        done     = @{ target = "passed" }
		                        pass     = @{ target = "passed" }
		                        fail     = @{ target = "triage" }
	                        escalate = @{ target = "triage" }
	                    }
	                }
                triage       = @{
                    role    = "manager"
                    type    = "triage"
                    signals = @{
                        done     = @{ target = "review" }
                        fix      = @{ target = "optimize"; actions = @("increment_retries") }
                        redesign = @{ target = "developing"; actions = @("increment_retries", "revise_brief") }
                        reject   = @{ target = "failed-final" }
                    }
                }
                failed       = @{
                    role    = "manager"
                    type    = "decision"
                    signals = @{
                        retry   = @{ target = "developing"; guard = "retries < max_retries" }
                        exhaust = @{ target = "failed-final"; guard = "retries >= max_retries" }
                    }
                }
                passed         = @{ type = "terminal" }
                "failed-final" = @{ type = "terminal" }
            }
        } | ConvertTo-Json -Depth 10 | Out-File (Join-Path $RoomDir "lifecycle.json") -Encoding utf8
    }

    # --- Write a mock Invoke-Agent script that records what RoleName it received ---
    # The mock writes mock_invoked_role.txt and a run-agent.ps1 reflecting the role.
    # Uses Add-Content to avoid nested here-string parse errors.
    function New-InvokeAgentMock {
        param([string]$Path, [string]$ResponseText = "Done.")
        Set-Content  -Path $Path -Encoding utf8 -Value 'param('
        Add-Content  -Path $Path -Value '    [string]$RoomDir = ".",'
        Add-Content  -Path $Path -Value '    [string]$RoleName = "unknown",'
        Add-Content  -Path $Path -Value '    [string]$Prompt = "",'
        Add-Content  -Path $Path -Value '    [string]$Model = "",'
        Add-Content  -Path $Path -Value '    [int]$TimeoutSeconds = 600,'
        Add-Content  -Path $Path -Value '    [string]$AgentCmd = "",'
        Add-Content  -Path $Path -Value '    [bool]$AutoApprove = $true,'
        Add-Content  -Path $Path -Value '    [string]$InstanceId = "",'
        Add-Content  -Path $Path -Value '    [string]$WorkingDir = "",'
        Add-Content  -Path $Path -Value '    [string]$McpConfig = "",'
        Add-Content  -Path $Path -Value '    [string[]]$ExtraArgs = @()'
        Add-Content  -Path $Path -Value ')'
        Add-Content  -Path $Path -Value '$RoleName | Out-File (Join-Path $RoomDir "mock_invoked_role.txt") -Encoding utf8 -NoNewline'
        Add-Content  -Path $Path -Value '$artifactsDir = Join-Path $RoomDir "artifacts"'
        Add-Content  -Path $Path -Value 'New-Item -ItemType Directory -Path $artifactsDir -Force | Out-Null'
        Add-Content  -Path $Path -Value '$pidDir = Join-Path $RoomDir "pids"'
        Add-Content  -Path $Path -Value 'New-Item -ItemType Directory -Path $pidDir -Force | Out-Null'
        Add-Content  -Path $Path -Value '$pidFile = Join-Path $pidDir "$RoleName.pid"'
        Add-Content  -Path $Path -Value '$PID | Out-File -FilePath $pidFile -Encoding utf8 -NoNewline'
        # Build run-agent.ps1 content with AGENT_OS_ROLE env var
        Add-Content  -Path $Path -Value '$nl = [Environment]::NewLine'
        Add-Content  -Path $Path -Value ('$ps1Content = "# run-agent.ps1 — unified wrapper" + $nl + "`$env:AGENT_OS_ROLE = " + [char]39 + $RoleName + [char]39')
        Add-Content  -Path $Path -Value '$ps1Content | Out-File (Join-Path $artifactsDir "run-agent.ps1") -Encoding utf8 -NoNewline'
        $safeOut = $ResponseText -replace "'", "''"
        Add-Content  -Path $Path -Value "return [PSCustomObject]@{ ExitCode=0; Output='$safeOut'; PidFile=`$pidFile; RoleName=`$RoleName; TimedOut=`$false }"
    }
}

AfterAll {
    Remove-Module -Name "Utils" -ErrorAction SilentlyContinue
}

# ===========================================================================
Describe "Lifecycle Role Transition — engineer to qa" {
# ===========================================================================

    # -------------------------------------------------------------------
    Context "Lifecycle schema — room-001 lifecycle.json structure" {
    # -------------------------------------------------------------------
        It "review state uses qa role" {
            $d = Join-Path $TestDrive "room-schema-$(Get-Random)"
            New-Item -ItemType Directory -Path $d -Force | Out-Null
            Write-GameLifecycle -RoomDir $d
            $lc = Get-Content (Join-Path $d "lifecycle.json") -Raw | ConvertFrom-Json
            $lc.states.review.role | Should -Be "qa"
        }

        It "developing state uses engineer role" {
            $d = Join-Path $TestDrive "room-schema2-$(Get-Random)"
            New-Item -ItemType Directory -Path $d -Force | Out-Null
            Write-GameLifecycle -RoomDir $d
            $lc = Get-Content (Join-Path $d "lifecycle.json") -Raw | ConvertFrom-Json
            $lc.states.developing.role | Should -Be "engineer"
        }

        It "optimize state uses engineer role (same as developing)" {
            $d = Join-Path $TestDrive "room-schema3-$(Get-Random)"
            New-Item -ItemType Directory -Path $d -Force | Out-Null
            Write-GameLifecycle -RoomDir $d
            $lc = Get-Content (Join-Path $d "lifecycle.json") -Raw | ConvertFrom-Json
            $lc.states.optimize.role | Should -Be "engineer"
        }

        It "review.done signal targets 'passed'" {
            $d = Join-Path $TestDrive "room-schema4-$(Get-Random)"
            New-Item -ItemType Directory -Path $d -Force | Out-Null
            Write-GameLifecycle -RoomDir $d
            $lc = Get-Content (Join-Path $d "lifecycle.json") -Raw | ConvertFrom-Json
            $lc.states.review.signals.done.target | Should -Be "passed"
        }

        It "review.fail signal targets triage without retry actions" {
            $d = Join-Path $TestDrive "room-schema5-$(Get-Random)"
            New-Item -ItemType Directory -Path $d -Force | Out-Null
            Write-GameLifecycle -RoomDir $d
            $lc = Get-Content (Join-Path $d "lifecycle.json") -Raw | ConvertFrom-Json
            $lc.states.review.signals.fail.target          | Should -Be "triage"
            $lc.states.review.signals.fail.PSObject.Properties.Name | Should -Not -Contain "actions"
        }
    }

    # -------------------------------------------------------------------
    Context "Find-LatestSignal — sender validation across role boundary" {
    # -------------------------------------------------------------------
        BeforeEach {
            $script:warRoomsDir = Join-Path $TestDrive "warrooms-$(Get-Random)"
            New-Item -ItemType Directory -Path $script:warRoomsDir -Force | Out-Null
        }

        It "accepts 'done' from engineer when state=developing" {
            & $script:NewWarRoom -RoomId "room-lc001" -TaskRef "EPIC-LC001" `
                                 -TaskDescription "Signal test" -WarRoomsDir $script:warRoomsDir
            $rd = Join-Path $script:warRoomsDir "room-lc001"
            Write-GameLifecycle -RoomDir $rd
            Set-WarRoomStatus -RoomDir $rd -NewStatus "developing"
            ([int][double]::Parse((Get-Date -UFormat %s)) - 10).ToString() |
                Out-File (Join-Path $rd "state_changed_at") -NoNewline

            & $script:PostMessage -RoomDir $rd -From "engineer" -To "manager" `
                                  -Type "done" -Ref "EPIC-LC001" -Body "Feature implemented"

            $lc          = Get-Content (Join-Path $rd "lifecycle.json") -Raw | ConvertFrom-Json
            $expectedRole = ($lc.states.developing.role -replace ':.*$', '')
            $expectedRole | Should -Be "engineer"

            $msgs        = & $script:ReadMessages -RoomDir $rd -FilterType "done" -Last 1 -AsObject
            $msgs.Count  | Should -Be 1
            ($msgs[0].from -replace ':.*$', '') | Should -Be $expectedRole
        }

        It "rejects 'done' from engineer when state=review (wrong sender)" {
            & $script:NewWarRoom -RoomId "room-lc002" -TaskRef "EPIC-LC002" `
                                 -TaskDescription "Sender filter" -WarRoomsDir $script:warRoomsDir
            $rd = Join-Path $script:warRoomsDir "room-lc002"
            Write-GameLifecycle -RoomDir $rd
            Set-WarRoomStatus -RoomDir $rd -NewStatus "review"
            ([int][double]::Parse((Get-Date -UFormat %s)) - 10).ToString() |
                Out-File (Join-Path $rd "state_changed_at") -NoNewline

            & $script:PostMessage -RoomDir $rd -From "engineer" -To "manager" `
                                  -Type "done" -Ref "EPIC-LC002" -Body "Already done"

            $lc          = Get-Content (Join-Path $rd "lifecycle.json") -Raw | ConvertFrom-Json
            $expectedRole = ($lc.states.review.role -replace ':.*$', '')
            $expectedRole | Should -Be "qa"

            $msgs        = & $script:ReadMessages -RoomDir $rd -FilterType "done" -Last 1 -AsObject
            $msgs.Count  | Should -Be 1
            $senderBase   = ($msgs[0].from -replace ':.*$', '')
            # engineer != qa => sender should NOT match review's expected role
            ($senderBase -ne $expectedRole) | Should -BeTrue
        }

        It "accepts 'pass' from qa when state=review" {
            & $script:NewWarRoom -RoomId "room-lc003" -TaskRef "EPIC-LC003" `
                                 -TaskDescription "QA pass" -WarRoomsDir $script:warRoomsDir
            $rd = Join-Path $script:warRoomsDir "room-lc003"
            Write-GameLifecycle -RoomDir $rd
            Set-WarRoomStatus -RoomDir $rd -NewStatus "review"
            ([int][double]::Parse((Get-Date -UFormat %s)) - 10).ToString() |
                Out-File (Join-Path $rd "state_changed_at") -NoNewline

            & $script:PostMessage -RoomDir $rd -From "qa" -To "manager" `
                                  -Type "pass" -Ref "EPIC-LC003" -Body "All tests pass"

            $lc          = Get-Content (Join-Path $rd "lifecycle.json") -Raw | ConvertFrom-Json
            $expectedRole = ($lc.states.review.role -replace ':.*$', '')

            $msgs        = & $script:ReadMessages -RoomDir $rd -FilterType "pass" -Last 1 -AsObject
            $msgs.Count  | Should -Be 1
            ($msgs[0].from -replace ':.*$', '') | Should -Be $expectedRole
        }

        It "rejects 'pass' signal in developing state ('pass' is not a valid developing signal)" {
            & $script:NewWarRoom -RoomId "room-lc004" -TaskRef "EPIC-LC004" `
                                 -TaskDescription "Wrong signal" -WarRoomsDir $script:warRoomsDir
            $rd = Join-Path $script:warRoomsDir "room-lc004"
            Write-GameLifecycle -RoomDir $rd
            Set-WarRoomStatus -RoomDir $rd -NewStatus "developing"

            $lc          = Get-Content (Join-Path $rd "lifecycle.json") -Raw | ConvertFrom-Json
            $validSignals = @($lc.states.developing.signals.PSObject.Properties.Name)
            $validSignals | Should -Not -Contain "pass"
        }
    }

    # -------------------------------------------------------------------
    Context "Start-DynamicRole — explicit RoleName takes precedence over config.json" {
    # -------------------------------------------------------------------
        BeforeEach {
            $script:roomDir = Join-Path $TestDrive "room-dr-$(Get-Random)"
            New-Item -ItemType Directory -Path (Join-Path $script:roomDir "artifacts") -Force | Out-Null
            New-Item -ItemType Directory -Path (Join-Path $script:roomDir "pids")      -Force | Out-Null

            # Config carries the ORIGINAL room-creation role (engineer)
            @{
                task_ref   = "EPIC-TEST"
                assignment = @{
                    assigned_role = "engineer"
                    title         = "Build grid system"
                    description   = "Build the grid"
                }
            } | ConvertTo-Json -Depth 5 | Out-File (Join-Path $script:roomDir "config.json") -Encoding utf8

            "EPIC-TEST" | Out-File (Join-Path $script:roomDir "task-ref")  -Encoding utf8 -NoNewline
            "review"    | Out-File (Join-Path $script:roomDir "status")    -Encoding utf8 -NoNewline
            "Build grid"| Out-File (Join-Path $script:roomDir "brief.md")  -Encoding utf8 -NoNewline

            # --- Mock: BuildSystemPrompt returns a fixed string ---
            $script:mockPrompt = Join-Path $TestDrive "Mock-Prompt-$(Get-Random).ps1"
            Set-Content  -Path $script:mockPrompt -Encoding utf8 `
                -Value 'param([string]$RoomDir="",[string]$RoleName="",[string]$RolePath=""); return "MOCK PROMPT"'

            # --- Mock: GetRoleDef returns evaluator for qa, worker otherwise ---
            $script:mockGetRole = Join-Path $TestDrive "Mock-GetRole-$(Get-Random).ps1"
            Set-Content  -Path $script:mockGetRole -Encoding utf8 -Value 'param([string]$RoleName="",[string]$RolePath="")'
            Add-Content  -Path $script:mockGetRole `
                -Value 'return [PSCustomObject]@{ Name=$RoleName; InstanceType=if($RoleName -eq "qa"){"evaluator"}else{"worker"}; Model="test"; Timeout=60 }'

            # --- Mock: InvokeAgent records RoleName, writes run-agent.ps1 ---
            $script:mockInvoke = Join-Path $TestDrive "Mock-Invoke-$(Get-Random).ps1"
            New-InvokeAgentMock -Path $script:mockInvoke -ResponseText "VERDICT: PASS`nAll tests OK."

            $script:overrides = @{
                OverrideInvokeAgent       = $script:mockInvoke
                OverrideBuildSystemPrompt = $script:mockPrompt
                OverrideGetRoleDef        = $script:mockGetRole
            }
        }

        It "uses qa (not engineer) for invocation when -RoleName qa is passed" {
            & $script:StartDynamicRole -RoomDir $script:roomDir `
                                       -RoleName "qa" `
                                       -AgentsDir $script:agentsDir `
                                       -TimeoutSeconds 10 `
                                       @script:overrides

            $invokedRole = (Get-Content (Join-Path $script:roomDir "mock_invoked_role.txt") -Raw).Trim()
            $invokedRole | Should -Be "qa"
        }

        It "generates run-agent.ps1 with AGENT_OS_ROLE=qa (not engineer) in review state" {
            & $script:StartDynamicRole -RoomDir $script:roomDir `
                                       -RoleName "qa" `
                                       -AgentsDir $script:agentsDir `
                                       -TimeoutSeconds 10 `
                                       @script:overrides

            $runPs1 = Get-Content (Join-Path $script:roomDir "artifacts" "run-agent.ps1") -Raw
            $runPs1 | Should -Match "AGENT_OS_ROLE.*=.*'qa'"
            $runPs1 | Should -Not -Match "AGENT_OS_ROLE.*=.*'engineer'"
        }

        It "maps legacy evaluator VERDICT: PASS to done when lifecycle accepts done" {
            Write-GameLifecycle -RoomDir $script:roomDir

            & $script:StartDynamicRole -RoomDir $script:roomDir `
                                       -RoleName "qa" `
                                       -AgentsDir $script:agentsDir `
                                       -TimeoutSeconds 10 `
                                       @script:overrides

            $doneMsgs = & $script:ReadMessages -RoomDir $script:roomDir -FilterType "done" -Last 1 -AsObject
            $passMsgs = & $script:ReadMessages -RoomDir $script:roomDir -FilterType "pass" -Last 1 -AsObject

            $doneMsgs.Count | Should -Be 1
            $doneMsgs[-1].from | Should -Be "qa"
            $doneMsgs[-1].body | Should -Match "VERDICT: DONE"
            $passMsgs.Count | Should -Be 0
        }

        It "falls back to engineer from config.json when -RoleName is not passed" {
            & $script:StartDynamicRole -RoomDir $script:roomDir `
                                       -AgentsDir $script:agentsDir `
                                       -TimeoutSeconds 10 `
                                       @script:overrides

            $invokedRole = (Get-Content (Join-Path $script:roomDir "mock_invoked_role.txt") -Raw).Trim()
            $invokedRole | Should -Be "engineer"
        }
    }

    # -------------------------------------------------------------------
    Context "Full lifecycle path — role at each state" {
    # -------------------------------------------------------------------
        BeforeEach {
            $script:warRoomsDir = Join-Path $TestDrive "warrooms-full-$(Get-Random)"
            New-Item -ItemType Directory -Path $script:warRoomsDir -Force | Out-Null
        }

        It "lifecycle correctly maps each state to the expected role" {
            & $script:NewWarRoom -RoomId "room-flc001" -TaskRef "EPIC-FLC" `
                                 -TaskDescription "Full lifecycle" -WarRoomsDir $script:warRoomsDir
            $rd = Join-Path $script:warRoomsDir "room-flc001"
            Write-GameLifecycle -RoomDir $rd
            $lc = Get-Content (Join-Path $rd "lifecycle.json") -Raw | ConvertFrom-Json

            $expected = @{
                "developing" = "engineer"
                "optimize"   = "engineer"
                "review"     = "qa"
                "triage"     = "manager"
                "failed"     = "manager"
            }
            foreach ($state in $expected.Keys) {
                $lc.states.$state.role |
                    Should -Be $expected[$state] -Because "state '$state' must use role '$($expected[$state])'"
            }
        }

        It "developing→review transition changes expected role from engineer to qa" {
            & $script:NewWarRoom -RoomId "room-flc002" -TaskRef "EPIC-FLC2" `
                                 -TaskDescription "Transition roles" -WarRoomsDir $script:warRoomsDir
            $rd = Join-Path $script:warRoomsDir "room-flc002"
            Write-GameLifecycle -RoomDir $rd
            $lc = Get-Content (Join-Path $rd "lifecycle.json") -Raw | ConvertFrom-Json

            $developingRole = $lc.states.developing.role
            $developingRole  | Should -Be "engineer"

            $targetState    = $lc.states.developing.signals.done.target
            $targetState     | Should -Be "review"

            $reviewRole     = $lc.states.$targetState.role
            $reviewRole      | Should -Be "qa"

            # Critical assertion: the role changes across the transition
            $reviewRole | Should -Not -Be $developingRole
        }

        It "engineer signal is valid in developing, but NOT in review" {
            & $script:NewWarRoom -RoomId "room-flc003" -TaskRef "EPIC-FLC3" `
                                 -TaskDescription "Cross-role signal" -WarRoomsDir $script:warRoomsDir
            $rd = Join-Path $script:warRoomsDir "room-flc003"
            Write-GameLifecycle -RoomDir $rd
            $lc = Get-Content (Join-Path $rd "lifecycle.json") -Raw | ConvertFrom-Json

            ($lc.states.developing.role -replace ':.*$', '') | Should -Be "engineer"
            ($lc.states.review.role     -replace ':.*$', '') | Should -Not -Be "engineer"
            ($lc.states.review.role     -replace ':.*$', '') | Should -Be "qa"
        }

        It "optimize → review transition changes expected role from engineer to qa" {
            & $script:NewWarRoom -RoomId "room-flc004" -TaskRef "EPIC-FLC4" `
                                 -TaskDescription "Optimize to review" -WarRoomsDir $script:warRoomsDir
            $rd = Join-Path $script:warRoomsDir "room-flc004"
            Write-GameLifecycle -RoomDir $rd
            $lc = Get-Content (Join-Path $rd "lifecycle.json") -Raw | ConvertFrom-Json

            # optimize state is serviced by engineer
            $optimizeRole = $lc.states.optimize.role
            $optimizeRole | Should -Be "engineer"

            # optimize.done targets review
            $targetState  = $lc.states.optimize.signals.done.target
            $targetState  | Should -Be "review"

            # review is serviced by qa — role changes across the transition
            $reviewRole   = $lc.states.$targetState.role
            $reviewRole   | Should -Be "qa"
            $reviewRole   | Should -Not -Be $optimizeRole
        }

        It "triage → optimize (fix signal) routes to engineer, not manager" {
            & $script:NewWarRoom -RoomId "room-flc005" -TaskRef "EPIC-FLC5" `
                                 -TaskDescription "Triage fix to optimize" -WarRoomsDir $script:warRoomsDir
            $rd = Join-Path $script:warRoomsDir "room-flc005"
            Write-GameLifecycle -RoomDir $rd
            $lc = Get-Content (Join-Path $rd "lifecycle.json") -Raw | ConvertFrom-Json

            # triage is serviced by manager
            $triageRole  = $lc.states.triage.role
            $triageRole  | Should -Be "manager"

            # triage.fix targets optimize
            $targetState = $lc.states.triage.signals.fix.target
            $targetState | Should -Be "optimize"

            # optimize is serviced by engineer — role changes
            $optimizeRole = $lc.states.$targetState.role
            $optimizeRole | Should -Be "engineer"
            $optimizeRole | Should -Not -Be $triageRole
        }

        It "triage → review (done signal) returns to evaluator when escalation is resolved" {
            & $script:NewWarRoom -RoomId "room-flc005b" -TaskRef "EPIC-FLC5B" `
                                 -TaskDescription "Triage done to review" -WarRoomsDir $script:warRoomsDir
            $rd = Join-Path $script:warRoomsDir "room-flc005b"
            Write-GameLifecycle -RoomDir $rd
            $lc = Get-Content (Join-Path $rd "lifecycle.json") -Raw | ConvertFrom-Json

            $lc.states.triage.role | Should -Be "manager"
            $targetState = $lc.states.triage.signals.done.target
            $targetState | Should -Be "review"
            $lc.states.$targetState.role | Should -Be "qa"
        }

        It "triage → developing (redesign signal) routes to engineer for full restart" {
            & $script:NewWarRoom -RoomId "room-flc006" -TaskRef "EPIC-FLC6" `
                                 -TaskDescription "Triage redesign" -WarRoomsDir $script:warRoomsDir
            $rd = Join-Path $script:warRoomsDir "room-flc006"
            Write-GameLifecycle -RoomDir $rd
            $lc = Get-Content (Join-Path $rd "lifecycle.json") -Raw | ConvertFrom-Json

            # triage.redesign targets developing (full restart, different from triage.fix)
            $targetState = $lc.states.triage.signals.redesign.target
            $targetState | Should -Be "developing"

            # developing uses engineer
            $lc.states.$targetState.role | Should -Be "engineer"

            # redesign actions include revise_brief
            $lc.states.triage.signals.redesign.actions | Should -Contain "revise_brief"
        }
    }
}
