# Agent OS — Start-Architect Pester Tests

BeforeAll {
    $script:StartArchitect = Join-Path (Resolve-Path "$PSScriptRoot/../../../roles/architect").Path "Start-Architect.ps1"
    $script:agentsDir = (Resolve-Path (Join-Path (Resolve-Path "$PSScriptRoot/../../../roles/architect").Path ".." "..")).Path
    . (Join-Path $script:agentsDir "tests" "TestChannelHelpers.ps1")
    $script:PostMessage = New-TestChannelWriter
    $script:ReadMessages = Join-Path $script:agentsDir "channel" "Read-Messages.ps1"

    function New-CaptureArchitectAgent {
        param([Parameter(Mandatory)][string]$CapturePath)

        $scriptPath = Join-Path $TestDrive "capture-architect-$(Get-Random).ps1"
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
Write-Output 'VERDICT: DONE'
"@ | Out-File $scriptPath -Encoding utf8

        $escapedScript = $scriptPath -replace "'", "'\''"
        return "pwsh -NoProfile -File '$escapedScript'"
    }
}

Describe "Start-Architect" {
    BeforeEach {
        $script:roomDir = Join-Path $TestDrive "room-arch-$(Get-Random)"
        New-Item -ItemType Directory -Path $script:roomDir -Force | Out-Null
        New-Item -ItemType Directory -Path (Join-Path $script:roomDir "pids") -Force | Out-Null
        New-Item -ItemType Directory -Path (Join-Path $script:roomDir "artifacts") -Force | Out-Null

        # Create minimal room state
        "EPIC-001" | Out-File (Join-Path $script:roomDir "task-ref") -NoNewline
        @"
# EPIC-001

Implement user authentication

## Working Directory
$TestDrive

## Created
2026-01-01T00:00:00Z
"@ | Out-File (Join-Path $script:roomDir "brief.md") -Encoding utf8

        "review" | Out-File (Join-Path $script:roomDir "status") -NoNewline
        New-Item -ItemType File -Path (Join-Path $script:roomDir "channel.jsonl") -Force | Out-Null

        # Create a PowerShell mock that ignores the prompt and prints MOCK_OUT
        # Must use .ps1 on all platforms — Invoke-Agent.ps1 tokenizes AgentCmd
        # and calls it via PowerShell's call operator in a pwsh wrapper.
        $script:mockAgentPath = Join-Path $TestDrive "mock-arch.ps1"
        "Write-Output `"`$env:MOCK_OUT`"" | Out-File $script:mockAgentPath -Encoding ascii
        $escapedMockAgentPath = $script:mockAgentPath -replace "'", "'\''"
        $mockCli = "pwsh -NoProfile -File '$escapedMockAgentPath'"
        $script:configFile = Join-Path $TestDrive "config-arch.json"
        @{
            engineer = @{
                cli              = $mockCli
                default_model    = "test-model"
                timeout_seconds  = 10
            }
            qa = @{
                cli             = $mockCli
                default_model   = "test-model"
                timeout_seconds = 10
            }
            architect = @{
                cli             = $mockCli
                default_model   = "test-model"
                timeout_seconds = 10
            }
            channel = @{
                format                 = "jsonl"
                max_message_size_bytes = 65536
            }
        } | ConvertTo-Json -Depth 3 | Out-File $script:configFile -Encoding utf8
        $env:AGENT_OS_CONFIG = $script:configFile
        $env:ARCHITECT_CMD = $mockCli
    }

    AfterEach {
        Remove-Item Env:AGENT_OS_CONFIG -ErrorAction SilentlyContinue
        Remove-Item Env:ARCHITECT_CMD -ErrorAction SilentlyContinue
    }

    Context "Room state reading" {
        It "reads task-ref from room" {
            $taskRef = (Get-Content (Join-Path $script:roomDir "task-ref") -Raw).Trim()
            $taskRef | Should -Be "EPIC-001"
        }

        It "reads brief.md for original assignment" {
            $brief = Get-Content (Join-Path $script:roomDir "brief.md") -Raw
            $brief | Should -Match "user authentication"
        }
    }



    Context "QA feedback reading" {
        It "reads escalate messages when present" {
            & $script:PostMessage -RoomDir $script:roomDir -From "qa" -To "manager" `
                                  -Type "escalate" -Ref "EPIC-001" -Body "This is a design problem"

            $msgs = & $script:ReadMessages -RoomDir $script:roomDir -FilterType "escalate" -Last 1 -AsObject
            $msgs.Count | Should -Be 1
            $msgs[0].body | Should -Match "design problem"
        }

        It "falls back to fail messages when no escalate" {
            & $script:PostMessage -RoomDir $script:roomDir -From "qa" -To "manager" `
                                  -Type "fail" -Ref "EPIC-001" -Body "Tests failing"

            $escalateMsgs = & $script:ReadMessages -RoomDir $script:roomDir -FilterType "escalate" -Last 1 -AsObject
            if (-not $escalateMsgs -or $escalateMsgs.Count -eq 0) {
                $failMsgs = & $script:ReadMessages -RoomDir $script:roomDir -FilterType "fail" -Last 1 -AsObject
                $failMsgs.Count | Should -Be 1
                $failMsgs[0].body | Should -Match "Tests failing"
            }
        }
    }

    Context "Design review messages" {
        It "reads manager's design-review request" {
            & $script:PostMessage -RoomDir $script:roomDir -From "manager" -To "architect" `
                                  -Type "design-review" -Ref "EPIC-001" -Body "Please review this design issue"

            $msgs = & $script:ReadMessages -RoomDir $script:roomDir -FilterType "design-review" -Last 1 -AsObject
            $msgs.Count | Should -Be 1
            $msgs[0].body | Should -Match "design issue"
        }
    }

    Context "Wrapper failure handling" {
        It "marks role config failed without posting channel error when agent exits non-zero" {
            $failingAgent = Join-Path $TestDrive "architect-fails.ps1"
            "Write-Output 'architect failed'; exit 7" | Out-File $failingAgent -Encoding ascii
            $escapedFailingAgent = $failingAgent -replace "'", "'\''"
            $env:ARCHITECT_CMD = "pwsh -NoProfile -File '$escapedFailingAgent'"

            & pwsh -NoProfile -File $script:StartArchitect -RoomDir $script:roomDir -TimeoutSeconds 10 2>&1 | Out-Null
            $LASTEXITCODE | Should -Be 7

            $roleConfig = Get-Content (Join-Path $script:roomDir "architect_001.json") -Raw | ConvertFrom-Json
            $roleConfig.status | Should -Be "failed"
            $roleConfig.status_updated_epoch | Should -Not -BeNullOrEmpty

            $channelRaw = Get-Content (Join-Path $script:roomDir "channel.jsonl") -Raw
            $channelRaw | Should -Not -Match '"(msg_type|type)"\s*:\s*"error"'
        }
    }

    Context "PLAN-REVIEW prompt assembly" {
        It "includes latest manager review or plan-update body in prompt.txt" {
            "PLAN-REVIEW" | Out-File (Join-Path $script:roomDir "task-ref") -Encoding utf8 -NoNewline
            "# PLAN-REVIEW`n`nUnified Plan Negotiation" |
                Out-File (Join-Path $script:roomDir "brief.md") -Encoding utf8

            $capturedPrompt = Join-Path $TestDrive "captured-architect-prompt-$(Get-Random).txt"
            $env:ARCHITECT_CMD = New-CaptureArchitectAgent -CapturePath $capturedPrompt

            & $script:PostMessage -RoomDir $script:roomDir -From "manager" -To "architect" `
                -Type "review" -Ref "PLAN-REVIEW" -Body "OLD PLAN BODY" | Out-Null
            & $script:PostMessage -RoomDir $script:roomDir -From "manager" -To "architect" `
                -Type "plan-update" -Ref "PLAN-REVIEW" -Body "LATEST PLAN UPDATE BODY" | Out-Null
            & $script:PostMessage -RoomDir $script:roomDir -From "qa" -To "manager" `
                -Type "pass" -Ref "PLAN-REVIEW" -Body "Irrelevant last physical channel line" | Out-Null

            & $script:StartArchitect -RoomDir $script:roomDir -TimeoutSeconds 10

            $prompt = Get-Content $capturedPrompt -Raw
            $prompt | Should -Match "## Current Plan Review Body"
            $prompt | Should -Match "LATEST PLAN UPDATE BODY"
        }
    }
}
