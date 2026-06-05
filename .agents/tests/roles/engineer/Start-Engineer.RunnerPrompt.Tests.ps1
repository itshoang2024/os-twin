# Agent OS — Start-Engineer runner prompt handoff tests

BeforeAll {
    $script:StartEngineer = Join-Path (Resolve-Path "$PSScriptRoot/../../../roles/engineer").Path "Start-Engineer.ps1"
    $script:agentsDir = (Resolve-Path (Join-Path (Resolve-Path "$PSScriptRoot/../../../roles/engineer").Path ".." "..")).Path
    $script:TestDepsReady = Join-Path $script:agentsDir "plan" "Test-DependenciesReady.ps1"
    . (Join-Path $script:agentsDir "tests" "TestChannelHelpers.ps1")

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

        Write-TestChannelMessage -RoomDir $RoomDir -From $From -To $To `
            -Type $Type -Ref $Ref -Body $Body | Out-Null
    }

    function New-EngineerPromptTestRoom {
        param(
            [Parameter(Mandatory)][string]$RoomId,
            [Parameter(Mandatory)][string]$TaskRef,
            [string]$Brief = "Implement the dependent feature.",
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

$Brief

## Working Directory
$TestDrive
"@ | Out-File (Join-Path $room "brief.md") -Encoding utf8
        "- [ ] TASK-001 - Implement $TaskRef" |
            Out-File (Join-Path $room "TASKS.md") -Encoding utf8

        return $room
    }

    function Write-TestDag {
        param(
            [Parameter(Mandatory)][hashtable]$Nodes
        )

        @{ nodes = $Nodes } |
            ConvertTo-Json -Depth 10 |
            Out-File (Join-Path $script:warRoomsDir "DAG.json") -Encoding utf8
    }

    function New-CaptureAgent {
        param(
            [Parameter(Mandatory)][string]$CapturePath,
            [string]$Output = "captured"
        )

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
Write-Output '$Output'
"@ | Out-File $scriptPath -Encoding utf8

        $escapedScript = $scriptPath -replace "'", "'\''"
        return "pwsh -NoProfile -File '$escapedScript'"
    }
}

    Describe "Start-Engineer prompt handoff" {
    BeforeEach {
        $script:warRoomsDir = Join-Path $TestDrive "wr-engineer-runner-$(Get-Random)"
        New-Item -ItemType Directory -Path $script:warRoomsDir -Force | Out-Null
        $script:roomDir = New-EngineerPromptTestRoom -RoomId "room-current" -TaskRef "EPIC-002"

        $script:configFile = Join-Path $TestDrive "engineer-config-$(Get-Random).json"
        @{
            engineer = @{
                default_model   = "test-model"
                timeout_seconds = 10
            }
            channel = @{
                max_message_size_bytes = 65536
            }
        } | ConvertTo-Json -Depth 5 | Out-File $script:configFile -Encoding utf8

        $env:AGENT_OS_CONFIG = $script:configFile
        $script:capturedPrompt = Join-Path $TestDrive "captured-engineer-prompt-$(Get-Random).txt"
        $env:ENGINEER_CMD = New-CaptureAgent -CapturePath $script:capturedPrompt
    }

    AfterEach {
        Remove-Item Env:AGENT_OS_CONFIG -ErrorAction SilentlyContinue
        Remove-Item Env:ENGINEER_CMD -ErrorAction SilentlyContinue
    }

    It "passes the latest relevant task or fix body into prompt.txt" {
        Add-ChannelMessage -RoomDir $script:roomDir -From "manager" -To "engineer" `
            -Type "task" -Ref "EPIC-002" -Body "Initial task body"
        Add-ChannelMessage -RoomDir $script:roomDir -From "manager" -To "engineer" `
            -Type "fix" -Ref "EPIC-002" -Body "LATEST FIX BODY FOR ENGINEER"

        & $script:StartEngineer -RoomDir $script:roomDir -TimeoutSeconds 10

        $prompt = Get-Content $script:capturedPrompt -Raw
        $prompt | Should -Match "## Current Instruction"
        $prompt | Should -Match "LATEST FIX BODY FOR ENGINEER"
    }

    It "EPIC-002 cold start includes EPIC-001 last channel item" {
        $epic1Room = New-EngineerPromptTestRoom -RoomId "room-epic-001" -TaskRef "EPIC-001" -Status "passed"
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
        $prompt | Should -Not -Match "### PLAN-REVIEW"
    }

    It "EPIC-003 cold start includes EPIC-001 last channel item" {
        $script:roomDir = New-EngineerPromptTestRoom -RoomId "room-current" -TaskRef "EPIC-003"
        $script:capturedPrompt = Join-Path $TestDrive "captured-engineer-prompt-$(Get-Random).txt"
        $env:ENGINEER_CMD = New-CaptureAgent -CapturePath $script:capturedPrompt

        $epic1Room = New-EngineerPromptTestRoom -RoomId "room-epic-001" -TaskRef "EPIC-001" -Status "passed"
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
        $prompt | Should -Not -Match "### PLAN-REVIEW"
    }

    It "EPIC-004 cold start includes EPIC-002 and EPIC-003 last channel items only" {
        $script:roomDir = New-EngineerPromptTestRoom -RoomId "room-current" -TaskRef "EPIC-004"
        $script:capturedPrompt = Join-Path $TestDrive "captured-engineer-prompt-$(Get-Random).txt"
        $env:ENGINEER_CMD = New-CaptureAgent -CapturePath $script:capturedPrompt

        New-EngineerPromptTestRoom -RoomId "room-epic-001" -TaskRef "EPIC-001" -Status "passed" | Out-Null
        $epic2Room = New-EngineerPromptTestRoom -RoomId "room-epic-002" -TaskRef "EPIC-002" -Status "passed"
        $epic3Room = New-EngineerPromptTestRoom -RoomId "room-epic-003" -TaskRef "EPIC-003" -Status "passed"

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
        $prompt | Should -Not -Match "### EPIC-001"
        $prompt | Should -Not -Match "### PLAN-REVIEW"
    }

    It "documents current gap: passed dependency without channel item is ready but absent from prompt" {
        $script:roomDir = New-EngineerPromptTestRoom -RoomId "room-current" -TaskRef "EPIC-004"
        $script:capturedPrompt = Join-Path $TestDrive "captured-engineer-prompt-$(Get-Random).txt"
        $env:ENGINEER_CMD = New-CaptureAgent -CapturePath $script:capturedPrompt

        $epic2Room = New-EngineerPromptTestRoom -RoomId "room-epic-002" -TaskRef "EPIC-002" -Status "passed"
        New-EngineerPromptTestRoom -RoomId "room-epic-003" -TaskRef "EPIC-003" -Status "passed" | Out-Null
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

    It "includes last channel item from dependent epics and skips PLAN-REVIEW" {
        $depRoom = New-EngineerPromptTestRoom -RoomId "room-dep" -TaskRef "EPIC-001" -Status "passed"
        Add-ChannelMessage -RoomDir $depRoom -From "engineer" -To "manager" `
            -Type "done" -Ref "EPIC-001" -Body "DEPENDENCY EPIC OUTPUT BODY"

        Write-TestDag -Nodes @{
            'EPIC-001' = @{
                    room_id    = 'room-dep'
                    depends_on = @('PLAN-REVIEW')
                }
            'EPIC-002' = @{
                    room_id    = 'room-current'
                    depends_on = @('PLAN-REVIEW', 'EPIC-001')
                }
        }

        Add-ChannelMessage -RoomDir $script:roomDir -From "manager" -To "engineer" `
            -Type "task" -Ref "EPIC-002" -Body "Implement with dependency context"

        & $script:StartEngineer -RoomDir $script:roomDir -TimeoutSeconds 10

        $prompt = Get-Content $script:capturedPrompt -Raw
        $prompt | Should -Match "## Predecessor Outputs"
        $prompt | Should -Match "### EPIC-001"
        $prompt | Should -Match "DEPENDENCY EPIC OUTPUT BODY"
        $prompt | Should -Not -Match "### PLAN-REVIEW"
    }
}
