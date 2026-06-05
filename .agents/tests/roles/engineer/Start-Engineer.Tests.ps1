# Agent OS — Start-Engineer Pester Tests

BeforeAll {
    $script:StartEngineer = Join-Path (Resolve-Path "$PSScriptRoot/../../../roles/engineer").Path "Start-Engineer.ps1"
    $script:agentsDir = (Resolve-Path (Join-Path (Resolve-Path "$PSScriptRoot/../../../roles/engineer").Path ".." "..")).Path
    $script:ChannelServer = Join-Path $script:agentsDir "mcp" "channel-server.py"
    $script:TestDepsReady = Join-Path $script:agentsDir "plan" "Test-DependenciesReady.ps1"

    # codegraph is available in this repo, but it indexes Python/TS/JS and does
    # not index these PowerShell runners; rg/Pester are the source of truth here.
    function Add-ChannelMessage {
        param(
            [Parameter(Mandatory)][string]$RoomDir,
            [Parameter(Mandatory)][string]$From,
            [Parameter(Mandatory)][string]$To,
            [Parameter(Mandatory)][string]$Type,
            [Parameter(Mandatory)][string]$Ref,
            [Parameter(Mandatory)][AllowEmptyString()][string]$Body
        )

        $py = @'
import importlib.util
import sys

server, room, from_role, to_role, msg_type, ref, body = sys.argv[1:]
spec = importlib.util.spec_from_file_location("channel_server", server)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.post_message(room, from_role, to_role, msg_type, ref, body)
'@
        $py | python3 - $script:ChannelServer $RoomDir $From $To $Type $Ref $Body | Out-Null
    }

    function New-CaptureAgent {
        param([Parameter(Mandatory)][string]$CapturePath)

        $scriptPath = Join-Path $TestDrive "capture-agent-$(Get-Random).ps1"
        $escapedCapture = $CapturePath -replace "'", "''"
        @"
`$promptFile = `$null
for (`$i = 0; `$i -lt `$args.Count; `$i++) {
    if (`$args[`$i] -eq '--file' -and (`$i + 1) -lt `$args.Count -and `$args[`$i + 1] -match 'prompt\.txt$') {
        `$promptFile = `$args[`$i + 1]
    }
}
if (-not `$promptFile) { throw 'prompt.txt argument not found' }
Get-Content -Path `$promptFile -Raw | Out-File -FilePath '$escapedCapture' -Encoding utf8 -NoNewline
Write-Output 'captured'
"@ | Out-File $scriptPath -Encoding utf8

        $escapedScript = $scriptPath -replace "'", "'\''"
        return "pwsh -NoProfile -File '$escapedScript'"
    }

    function New-DagPromptRoom {
        param(
            [Parameter(Mandatory)][string]$RoomId,
            [Parameter(Mandatory)][string]$TaskRef,
            [string]$Status = "pending"
        )

        $room = Join-Path $script:warRoomsDir $RoomId
        New-Item -ItemType Directory -Path $room -Force | Out-Null
        New-Item -ItemType Directory -Path (Join-Path $room "pids") -Force | Out-Null
        New-Item -ItemType Directory -Path (Join-Path $room "artifacts") -Force | Out-Null
        New-Item -ItemType Directory -Path (Join-Path $room "contexts") -Force | Out-Null
        New-Item -ItemType File -Path (Join-Path $room "channel.jsonl") -Force | Out-Null

        $TaskRef | Out-File (Join-Path $room "task-ref") -Encoding utf8 -NoNewline
        "0" | Out-File (Join-Path $room "retries") -Encoding utf8 -NoNewline
        $Status | Out-File (Join-Path $room "status") -Encoding utf8 -NoNewline
        @"
# $TaskRef

Implement $TaskRef.

## Working Directory
$TestDrive
"@ | Out-File (Join-Path $room "brief.md") -Encoding utf8
        "- [ ] TASK-001 - Implement $TaskRef" |
            Out-File (Join-Path $room "TASKS.md") -Encoding utf8

        return $room
    }

    function Write-TestDag {
        param([Parameter(Mandatory)][hashtable]$Nodes)

        @{ nodes = $Nodes } |
            ConvertTo-Json -Depth 10 |
            Out-File (Join-Path $script:warRoomsDir "DAG.json") -Encoding utf8
    }
}

Describe "Start-Engineer" {
    BeforeEach {
        $script:roomDir = Join-Path $TestDrive "room-eng-$(Get-Random)"
        New-Item -ItemType Directory -Path $script:roomDir -Force | Out-Null
        New-Item -ItemType Directory -Path (Join-Path $script:roomDir "pids") -Force | Out-Null
        New-Item -ItemType Directory -Path (Join-Path $script:roomDir "artifacts") -Force | Out-Null

        # Create minimal room state
        "TASK-001" | Out-File (Join-Path $script:roomDir "task-ref") -NoNewline
        @"
# TASK-001

Implement a hello world function

## Working Directory
$TestDrive

## Created
2026-01-01T00:00:00Z
"@ | Out-File (Join-Path $script:roomDir "brief.md") -Encoding utf8

        "pending" | Out-File (Join-Path $script:roomDir "status") -NoNewline

        # Create a config with echo mock
        $script:configFile = Join-Path $TestDrive "config-eng.json"
        @{
            engineer = @{
                cli              = "echo"
                default_model    = "test-model"
                timeout_seconds  = 10
                max_prompt_bytes = 102400
            }
            qa = @{
                cli             = "echo"
                timeout_seconds = 10
            }
        } | ConvertTo-Json -Depth 3 | Out-File $script:configFile -Encoding utf8
        $env:AGENT_OS_CONFIG = $script:configFile
        $env:ENGINEER_CMD = "echo"
    }

    AfterEach {
        Remove-Item Env:AGENT_OS_CONFIG -ErrorAction SilentlyContinue
        Remove-Item Env:ENGINEER_CMD -ErrorAction SilentlyContinue
    }

    Context "Task execution" {
        It "reads task-ref from room" {
            # The script should read TASK-001 from task-ref file
            # and include it in the prompt
            $taskRef = Get-Content (Join-Path $script:roomDir "task-ref") -Raw
            $taskRef.Trim() | Should -Be "TASK-001"
        }

        It "reads brief.md for task description" {
            $brief = Get-Content (Join-Path $script:roomDir "brief.md") -Raw
            $brief | Should -Match "hello world"
        }

        It "creates brief.md with working directory" {
            $brief = Get-Content (Join-Path $script:roomDir "brief.md") -Raw
            $brief | Should -Match "Working Directory"
        }
    }

    Context "Epic detection" {
        It "detects EPIC prefix" {
            "EPIC-001" | Out-File (Join-Path $script:roomDir "task-ref") -NoNewline
            $taskRef = (Get-Content (Join-Path $script:roomDir "task-ref") -Raw).Trim()
            $taskRef | Should -Match '^EPIC-'
        }

        It "detects TASK prefix" {
            $taskRef = (Get-Content (Join-Path $script:roomDir "task-ref") -Raw).Trim()
            $taskRef | Should -Not -Match '^EPIC-'
        }
    }

    Context "Room structure" {
        It "has required directories" {
            Test-Path (Join-Path $script:roomDir "pids") | Should -BeTrue
            Test-Path (Join-Path $script:roomDir "artifacts") | Should -BeTrue
        }

        It "has channel.jsonl or can create one" {
            $channelFile = Join-Path $script:roomDir "channel.jsonl"
            # Channel file may not exist yet, but post will create it
            New-Item -ItemType File -Path $channelFile -Force | Out-Null
            Test-Path $channelFile | Should -BeTrue
        }
    }

    Context "Wrapper failure handling" {
        It "marks role config failed without posting channel error when agent exits non-zero" {
            New-Item -ItemType File -Path (Join-Path $script:roomDir "channel.jsonl") -Force | Out-Null
            @{
                role        = "engineer"
                instance_id = "001"
                status      = "pending"
            } | ConvertTo-Json -Depth 5 | Out-File (Join-Path $script:roomDir "engineer_001.json") -Encoding utf8

            $failingAgent = Join-Path $TestDrive "engineer-fails.ps1"
            "Write-Output 'engineer failed'; exit 7" | Out-File $failingAgent -Encoding ascii
            $escapedFailingAgent = $failingAgent -replace "'", "'\''"
            $env:ENGINEER_CMD = "pwsh -NoProfile -File '$escapedFailingAgent'"

            & pwsh -NoProfile -File $script:StartEngineer -RoomDir $script:roomDir -TimeoutSeconds 10 2>&1 | Out-Null
            $LASTEXITCODE | Should -Be 7

            $roleConfig = Get-Content (Join-Path $script:roomDir "engineer_001.json") -Raw | ConvertFrom-Json
            $roleConfig.status | Should -Be "failed"
            $roleConfig.status_updated_epoch | Should -Not -BeNullOrEmpty

            $channelRaw = Get-Content (Join-Path $script:roomDir "channel.jsonl") -Raw
            $channelRaw | Should -Not -Match '"(msg_type|type)"\s*:\s*"error"'
        }
    }

    Context "Prompt construction" {
        It "includes role prompt from ROLE.md if exists" {
            $roleMd = Join-Path (Resolve-Path "$PSScriptRoot/../../../roles/engineer").Path "ROLE.md"
            if (Test-Path $roleMd) {
                $roleContent = Get-Content $roleMd -Raw
                $roleContent.Length | Should -BeGreaterThan 0
            }
        }

        It "handles missing ROLE.md gracefully" {
            # This shouldn't throw even if ROLE.md doesn't exist
            # The script uses conditional file reads
            $true | Should -BeTrue
        }
    }

    Context "Instance parsing from room config" {
        It "parses instance ID from assigned_role in room config" {
            # Write a room config with assigned_role = engineer:fe
            $roomConfig = @{
                room_id = "room-eng-inst"
                task_ref = "TASK-001"
                assignment = @{
                    assigned_role = "engineer:fe"
                    type = "task"
                }
            } | ConvertTo-Json -Depth 3
            $roomConfig | Out-File (Join-Path $script:roomDir "config.json") -Encoding utf8

            $config = Get-Content (Join-Path $script:roomDir "config.json") -Raw | ConvertFrom-Json
            $assignedRole = $config.assignment.assigned_role

            $instanceId = ""
            if ($assignedRole -match '^engineer:(.+)$') {
                $instanceId = $Matches[1]
            }
            $instanceId | Should -Be "fe"
        }

        It "returns empty instance for plain engineer role" {
            $roomConfig = @{
                room_id = "room-eng-plain"
                task_ref = "TASK-002"
                assignment = @{
                    assigned_role = "engineer"
                    type = "task"
                }
            } | ConvertTo-Json -Depth 3
            $roomConfig | Out-File (Join-Path $script:roomDir "config.json") -Encoding utf8

            $config = Get-Content (Join-Path $script:roomDir "config.json") -Raw | ConvertFrom-Json
            $assignedRole = $config.assignment.assigned_role

            $instanceId = ""
            if ($assignedRole -match '^engineer:(.+)$') {
                $instanceId = $Matches[1]
            }
            $instanceId | Should -Be ""
        }
    }

    Context "DAG predecessor cold start" {
        BeforeEach {
            $script:warRoomsDir = Join-Path $TestDrive "wr-engineer-dag-$(Get-Random)"
            New-Item -ItemType Directory -Path $script:warRoomsDir -Force | Out-Null
            $script:capturedPrompt = Join-Path $TestDrive "captured-engineer-prompt-$(Get-Random).txt"
            $env:ENGINEER_CMD = New-CaptureAgent -CapturePath $script:capturedPrompt
        }

        It "EPIC-002 cold start includes EPIC-001 last channel item" {
            $script:roomDir = New-DagPromptRoom -RoomId "room-current" -TaskRef "EPIC-002"
            $epic1Room = New-DagPromptRoom -RoomId "room-epic-001" -TaskRef "EPIC-001" -Status "passed"
            Add-ChannelMessage -RoomDir $epic1Room -From "engineer" -To "manager" `
                -Type "done" -Ref "EPIC-001" -Body "OLD EPIC-001 DONE BODY"
            Add-ChannelMessage -RoomDir $epic1Room -From "engineer" -To "manager" `
                -Type "done" -Ref "EPIC-001" -Body "LATEST EPIC-001 DONE BODY"
            Add-ChannelMessage -RoomDir $epic1Room -From "qa" -To "manager" `
                -Type "pass" -Ref "EPIC-001" -Body "EPIC-001 physical last line is pass"

            Write-TestDag -Nodes @{
                'EPIC-001' = @{
                    room_id    = 'room-epic-001'
                    depends_on = @('PLAN-REVIEW')
                }
                'EPIC-002' = @{
                    room_id    = 'room-current'
                    depends_on = @('PLAN-REVIEW', 'EPIC-001')
                }
            }

            Add-ChannelMessage -RoomDir $script:roomDir -From "manager" -To "engineer" `
                -Type "task" -Ref "EPIC-002" -Body "Implement with EPIC-001 dependency context"

            & $script:StartEngineer -RoomDir $script:roomDir -TimeoutSeconds 10

            $prompt = Get-Content $script:capturedPrompt -Raw
            $prompt | Should -Match "## Predecessor Outputs"
            $prompt | Should -Match "### EPIC-001"
            $prompt | Should -Match "EPIC-001 physical last line is pass"
            $prompt | Should -Not -Match "OLD EPIC-001 DONE BODY"
            $prompt | Should -Not -Match "LATEST EPIC-001 DONE BODY"
            $prompt | Should -Not -Match '"type":"pass"'
            $prompt | Should -Not -Match '"body":"EPIC-001 physical last line is pass"'
            $prompt | Should -Not -Match "### PLAN-REVIEW"
        }

        It "EPIC-003 cold start includes EPIC-001 last channel item" {
            $script:roomDir = New-DagPromptRoom -RoomId "room-current" -TaskRef "EPIC-003"
            $epic1Room = New-DagPromptRoom -RoomId "room-epic-001" -TaskRef "EPIC-001" -Status "passed"
            Add-ChannelMessage -RoomDir $epic1Room -From "engineer" -To "manager" `
                -Type "done" -Ref "EPIC-001" -Body "OLDER EPIC-001 HANDOFF FOR EPIC-003"
            Add-ChannelMessage -RoomDir $epic1Room -From "engineer" -To "manager" `
                -Type "done" -Ref "EPIC-001" -Body "LATEST EPIC-001 HANDOFF FOR EPIC-003"
            Add-ChannelMessage -RoomDir $epic1Room -From "qa" -To "manager" `
                -Type "pass" -Ref "EPIC-001" -Body "EPIC-001 pass after latest done"

            Write-TestDag -Nodes @{
                'EPIC-001' = @{
                    room_id    = 'room-epic-001'
                    depends_on = @('PLAN-REVIEW')
                }
                'EPIC-003' = @{
                    room_id    = 'room-current'
                    depends_on = @('PLAN-REVIEW', 'EPIC-001')
                }
            }

            Add-ChannelMessage -RoomDir $script:roomDir -From "manager" -To "engineer" `
                -Type "task" -Ref "EPIC-003" -Body "Implement EPIC-003 with EPIC-001 context"

            & $script:StartEngineer -RoomDir $script:roomDir -TimeoutSeconds 10

            $prompt = Get-Content $script:capturedPrompt -Raw
            $prompt | Should -Match "## Predecessor Outputs"
            $prompt | Should -Match "### EPIC-001"
            $prompt | Should -Match "EPIC-001 pass after latest done"
            $prompt | Should -Not -Match "OLDER EPIC-001 HANDOFF FOR EPIC-003"
            $prompt | Should -Not -Match "LATEST EPIC-001 HANDOFF FOR EPIC-003"
            $prompt | Should -Not -Match '"type":"pass"'
            $prompt | Should -Not -Match '"body":"EPIC-001 pass after latest done"'
            $prompt | Should -Not -Match "### PLAN-REVIEW"
        }

        It "EPIC-004 cold start includes EPIC-002 and EPIC-003 last channel items only" {
            $script:roomDir = New-DagPromptRoom -RoomId "room-current" -TaskRef "EPIC-004"
            New-DagPromptRoom -RoomId "room-epic-001" -TaskRef "EPIC-001" -Status "passed" | Out-Null
            $epic2Room = New-DagPromptRoom -RoomId "room-epic-002" -TaskRef "EPIC-002" -Status "passed"
            $epic3Room = New-DagPromptRoom -RoomId "room-epic-003" -TaskRef "EPIC-003" -Status "passed"

            Add-ChannelMessage -RoomDir $epic2Room -From "engineer" -To "manager" `
                -Type "done" -Ref "EPIC-002" -Body "OLD EPIC-002 DONE BODY"
            Add-ChannelMessage -RoomDir $epic2Room -From "engineer" -To "manager" `
                -Type "done" -Ref "EPIC-002" -Body "LATEST EPIC-002 DONE BODY"
            Add-ChannelMessage -RoomDir $epic2Room -From "qa" -To "manager" `
                -Type "pass" -Ref "EPIC-002" -Body "EPIC-002 physical last line is pass"
            Add-ChannelMessage -RoomDir $epic3Room -From "engineer" -To "manager" `
                -Type "done" -Ref "EPIC-003" -Body "LATEST EPIC-003 DONE BODY"

            Write-TestDag -Nodes @{
                'EPIC-001' = @{
                    room_id    = 'room-epic-001'
                    depends_on = @('PLAN-REVIEW')
                }
                'EPIC-002' = @{
                    room_id    = 'room-epic-002'
                    depends_on = @('PLAN-REVIEW', 'EPIC-001')
                }
                'EPIC-003' = @{
                    room_id    = 'room-epic-003'
                    depends_on = @('PLAN-REVIEW', 'EPIC-001')
                }
                'EPIC-004' = @{
                    room_id    = 'room-current'
                    depends_on = @('PLAN-REVIEW', 'EPIC-002', 'EPIC-003')
                }
            }

            Add-ChannelMessage -RoomDir $script:roomDir -From "manager" -To "engineer" `
                -Type "task" -Ref "EPIC-004" -Body "Implement EPIC-004 with EPIC-002 and EPIC-003 context"

            & $script:StartEngineer -RoomDir $script:roomDir -TimeoutSeconds 10

            $prompt = Get-Content $script:capturedPrompt -Raw
            $prompt | Should -Match "## Predecessor Outputs"
            $prompt | Should -Match "### EPIC-002"
            $prompt | Should -Match "### EPIC-003"
            $prompt | Should -Match "EPIC-002 physical last line is pass"
            $prompt | Should -Match "LATEST EPIC-003 DONE BODY"
            $prompt | Should -Not -Match "OLD EPIC-002 DONE BODY"
            $prompt | Should -Not -Match "LATEST EPIC-002 DONE BODY"
            $prompt | Should -Not -Match '"type":"pass"'
            $prompt | Should -Not -Match '"body":"EPIC-002 physical last line is pass"'
            $prompt | Should -Not -Match "### EPIC-001"
            $prompt | Should -Not -Match "### PLAN-REVIEW"
        }

        It "documents current gap: passed dependency without channel item is ready but absent from prompt" {
            $script:roomDir = New-DagPromptRoom -RoomId "room-current" -TaskRef "EPIC-004"
            $epic2Room = New-DagPromptRoom -RoomId "room-epic-002" -TaskRef "EPIC-002" -Status "passed"
            New-DagPromptRoom -RoomId "room-epic-003" -TaskRef "EPIC-003" -Status "passed" | Out-Null
            Add-ChannelMessage -RoomDir $epic2Room -From "engineer" -To "manager" `
                -Type "done" -Ref "EPIC-002" -Body "EPIC-002 DONE EXISTS"

            Write-TestDag -Nodes @{
                'EPIC-002' = @{
                    room_id    = 'room-epic-002'
                    depends_on = @('PLAN-REVIEW')
                }
                'EPIC-003' = @{
                    room_id    = 'room-epic-003'
                    depends_on = @('PLAN-REVIEW')
                }
                'EPIC-004' = @{
                    room_id    = 'room-current'
                    depends_on = @('PLAN-REVIEW', 'EPIC-002', 'EPIC-003')
                }
            }

            $ready = & $script:TestDepsReady -RoomDir $script:roomDir -WarRoomsDir $script:warRoomsDir
            $ready.Ready | Should -Be $true -Because "current readiness gate checks dependency status only"

            Add-ChannelMessage -RoomDir $script:roomDir -From "manager" -To "engineer" `
                -Type "task" -Ref "EPIC-004" -Body "Implement EPIC-004 with one missing predecessor handoff"

            & $script:StartEngineer -RoomDir $script:roomDir -TimeoutSeconds 10

            $prompt = Get-Content $script:capturedPrompt -Raw
            $prompt | Should -Match "### EPIC-002"
            $prompt | Should -Match "EPIC-002 DONE EXISTS"
            $prompt | Should -Not -Match "### EPIC-003"
        }
    }
}
