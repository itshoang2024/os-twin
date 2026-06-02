# Agent OS — Start-Reporter Pester Tests

BeforeAll {
    $script:StartReporter = Join-Path (Resolve-Path "$PSScriptRoot/../../../roles/reporter").Path "Start-Reporter.ps1"
    $script:agentsDir = (Resolve-Path (Join-Path (Resolve-Path "$PSScriptRoot/../../../roles/reporter").Path ".." "..")).Path
    $script:PostMessage = Join-Path $script:agentsDir "channel" "Post-Message.ps1"
    $script:ReadMessages = Join-Path $script:agentsDir "channel" "Read-Messages.ps1"
}

Describe "Start-Reporter" {
    BeforeEach {
        $script:roomDir = Join-Path $TestDrive "room-reporter-$(Get-Random)"
        New-Item -ItemType Directory -Path $script:roomDir -Force | Out-Null
        New-Item -ItemType Directory -Path (Join-Path $script:roomDir "pids") -Force | Out-Null
        New-Item -ItemType Directory -Path (Join-Path $script:roomDir "artifacts") -Force | Out-Null

        # Create minimal room state
        "TASK-010" | Out-File (Join-Path $script:roomDir "task-ref") -NoNewline
        @"
# TASK-010

Generate a project status report from the sprint data.

## Working Directory
$TestDrive

## Created
2026-01-15T00:00:00Z
"@ | Out-File (Join-Path $script:roomDir "brief.md") -Encoding utf8

        @{
            task_ref = "TASK-010"
            assignment = @{
                assigned_role = "reporter"
                candidate_roles = @("reporter")
            }
        } | ConvertTo-Json -Depth 3 | Out-File (Join-Path $script:roomDir "config.json") -Encoding utf8

        New-Item -ItemType File -Path (Join-Path $script:roomDir "channel.jsonl") -Force | Out-Null

        # Create a config with echo mock
        $script:configFile = Join-Path $TestDrive "config-reporter.json"
        @{
            engineer = @{
                cli              = "echo"
                default_model    = "test-model"
                timeout_seconds  = 10
            }
            reporter = @{
                cli             = "echo"
                default_model   = "test-model"
                timeout_seconds = 10
            }
            channel = @{
                format                 = "jsonl"
                max_message_size_bytes = 65536
            }
        } | ConvertTo-Json -Depth 3 | Out-File $script:configFile -Encoding utf8
        $env:AGENT_OS_CONFIG = $script:configFile
        $env:REPORTER_CMD = "echo"
    }

    AfterEach {
        Remove-Item Env:AGENT_OS_CONFIG -ErrorAction SilentlyContinue
        Remove-Item Env:REPORTER_CMD -ErrorAction SilentlyContinue
    }

    Context "Room state reading" {
        It "reads task-ref from room" {
            $taskRef = (Get-Content (Join-Path $script:roomDir "task-ref") -Raw).Trim()
            $taskRef | Should -Be "TASK-010"
        }

        It "reads brief.md for task description" {
            $brief = Get-Content (Join-Path $script:roomDir "brief.md") -Raw
            $brief | Should -Match "project status report"
        }

        It "reads assigned_role from config.json" {
            $config = Get-Content (Join-Path $script:roomDir "config.json") -Raw | ConvertFrom-Json
            $config.assignment.assigned_role | Should -Be "reporter"
        }
    }

    Context "Reporter prompt assembly" {
        It "SKILL.md exists and contains reporter instructions" {
            $skillPath = Join-Path (Resolve-Path "$PSScriptRoot/../../../skills/roles/reporter/generate-report").Path "SKILL.md"
            Test-Path $skillPath | Should -BeTrue
            $skill = Get-Content $skillPath -Raw
            $skill | Should -Match "generate-report"
        }

        It "role.json has correct capabilities" {
            $roleJson = Get-Content (Join-Path (Resolve-Path "$PSScriptRoot/../../../roles/reporter").Path "role.json") -Raw | ConvertFrom-Json
            $roleJson.name | Should -Be "reporter"
            $roleJson.capabilities | Should -Contain "report-generation"
            $roleJson.capabilities | Should -Contain "pdf-output"
        }

        It "role.json has quality gates" {
            $roleJson = Get-Content (Join-Path (Resolve-Path "$PSScriptRoot/../../../roles/reporter").Path "role.json") -Raw | ConvertFrom-Json
            $roleJson.quality_gates | Should -Contain "report-renders"
            $roleJson.quality_gates | Should -Contain "no-empty-pages"
        }
    }

    Context "Registry integration" {
        It "registry.json points to Start-Reporter.ps1 runner" {
            $registryPath = Join-Path $script:agentsDir "roles" "registry.json"
            $registry = Get-Content $registryPath -Raw | ConvertFrom-Json
            $reporterEntry = $registry.roles | Where-Object { $_.name -eq "reporter" }
            $reporterEntry | Should -Not -BeNullOrEmpty
            $reporterEntry.runner | Should -Be "roles/reporter/Start-Reporter.ps1"
        }

        It "registry runner path resolves to an existing file" {
            $registryPath = Join-Path $script:agentsDir "roles" "registry.json"
            $registry = Get-Content $registryPath -Raw | ConvertFrom-Json
            $reporterEntry = $registry.roles | Where-Object { $_.name -eq "reporter" }
            $runnerPath = Join-Path $script:agentsDir $reporterEntry.runner
            Test-Path $runnerPath | Should -BeTrue
        }

        It "registry definition path resolves to role.json" {
            $registryPath = Join-Path $script:agentsDir "roles" "registry.json"
            $registry = Get-Content $registryPath -Raw | ConvertFrom-Json
            $reporterEntry = $registry.roles | Where-Object { $_.name -eq "reporter" }
            $defPath = Join-Path $script:agentsDir $reporterEntry.definition
            Test-Path $defPath | Should -BeTrue
        }
    }

    Context "Epic detection" {
        It "detects EPIC task refs" {
            "EPIC-005" | Out-File (Join-Path $script:roomDir "task-ref") -NoNewline
            $taskRef = (Get-Content (Join-Path $script:roomDir "task-ref") -Raw).Trim()
            ($taskRef -match '^EPIC-') | Should -BeTrue
        }

        It "detects non-EPIC task refs" {
            $taskRef = (Get-Content (Join-Path $script:roomDir "task-ref") -Raw).Trim()
            ($taskRef -match '^EPIC-') | Should -BeFalse
        }
    }

    Context "Channel message posting" {
        It "can post done message to channel" {
            & $script:PostMessage -RoomDir $script:roomDir -From "reporter" -To "manager" `
                                  -Type "done" -Ref "TASK-010" -Body "Report generated: report.pdf"

            $msgs = & $script:ReadMessages -RoomDir $script:roomDir -FilterType "done" -Last 1 -AsObject
            $msgs.Count | Should -Be 1
            $msgs[0].body | Should -Match "report.pdf"
            $msgs[0].from | Should -Be "reporter"
        }

        It "can post error message to channel" {
            & $script:PostMessage -RoomDir $script:roomDir -From "reporter" -To "manager" `
                                  -Type "error" -Ref "TASK-010" -Body "Failed to generate PDF"

            $msgs = & $script:ReadMessages -RoomDir $script:roomDir -FilterType "error" -Last 1 -AsObject
            $msgs.Count | Should -Be 1
            $msgs[0].body | Should -Match "Failed to generate PDF"
        }
    }

    Context "Python module availability" {
        It "reporter Python package has __main__.py" {
            Test-Path (Join-Path (Resolve-Path "$PSScriptRoot/../../../roles/reporter").Path "__main__.py") | Should -BeTrue
        }

        It "reporter Python package has cli.py" {
            Test-Path (Join-Path (Resolve-Path "$PSScriptRoot/../../../roles/reporter").Path "cli.py") | Should -BeTrue
        }

        It "reporter Python package has engine.py" {
            Test-Path (Join-Path (Resolve-Path "$PSScriptRoot/../../../roles/reporter").Path "engine.py") | Should -BeTrue
        }

        It "reporter Python package has components.py" {
            Test-Path (Join-Path (Resolve-Path "$PSScriptRoot/../../../roles/reporter").Path "components.py") | Should -BeTrue
        }

        It "reporter Python package has brand.json" {
            Test-Path (Join-Path (Resolve-Path "$PSScriptRoot/../../../roles/reporter").Path "brand.json") | Should -BeTrue
        }
    }

    Context "Working directory parsing" {
        It "parses working_dir from brief metadata" {
            @"
# TASK-020
## Working Directory
/tmp/test-project
Generate a report
"@ | Out-File (Join-Path $script:roomDir "brief.md") -Encoding utf8

            $brief = Get-Content (Join-Path $script:roomDir "brief.md") -Raw
            $workingDir = ''
            if ($brief -match '## Working Directory\s*\n(.+)') {
                $workingDir = $Matches[1].Trim()
            }
            $workingDir | Should -Be "/tmp/test-project"
        }

        It "parses Working Directory from markdown heading" {
            $brief = Get-Content (Join-Path $script:roomDir "brief.md") -Raw
            if ($brief -match '## Working Directory\s*\n(.+)') {
                $dir = $Matches[1].Trim()
                $dir | Should -Not -BeNullOrEmpty
            }
        }
    }

    Context "Predecessor context injection" {
        It "builds predecessor section from DAG.json" {
            $warRoomsDir = Split-Path $script:roomDir
            $dagFile = Join-Path $warRoomsDir "DAG.json"

            # Create a predecessor room
            $predRoom = Join-Path $warRoomsDir "room-pred-001"
            New-Item -ItemType Directory -Path $predRoom -Force | Out-Null
            New-Item -ItemType File -Path (Join-Path $predRoom "channel.jsonl") -Force | Out-Null

            & $script:PostMessage -RoomDir $predRoom -From "engineer" -To "manager" `
                                  -Type "done" -Ref "EPIC-001" -Body "Implemented data pipeline"

            @{
                nodes = @{
                    "EPIC-001" = @{
                        room_id = "room-pred-001"
                        depends_on = @()
                    }
                    "TASK-010" = @{
                        room_id = (Split-Path $script:roomDir -Leaf)
                        depends_on = @("EPIC-001")
                    }
                }
            } | ConvertTo-Json -Depth 4 | Out-File $dagFile -Encoding utf8

            # Verify DAG can be loaded and predecessor resolved
            $dag = Get-Content $dagFile -Raw | ConvertFrom-Json
            $myNode = $dag.nodes."TASK-010"
            $myNode.depends_on | Should -Contain "EPIC-001"

            $depNode = $dag.nodes."EPIC-001"
            $depRoomDir = Join-Path $warRoomsDir $depNode.room_id
            $doneMsgs = & $script:ReadMessages -RoomDir $depRoomDir -FilterType "done" -Last 1 -AsObject
            $doneMsgs.Count | Should -Be 1
            $doneMsgs[0].body | Should -Match "data pipeline"
        }
    }
}
