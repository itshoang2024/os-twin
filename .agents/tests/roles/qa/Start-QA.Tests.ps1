# Agent OS — Start-QA Pester Tests

BeforeAll {
    $script:StartQA = Join-Path (Resolve-Path "$PSScriptRoot/../../../roles/qa").Path "Start-QA.ps1"
    $script:agentsDir = (Resolve-Path (Join-Path (Resolve-Path "$PSScriptRoot/../../../roles/qa").Path ".." "..")).Path
    Import-Module (Join-Path $script:agentsDir "roles" "_base" "LifecycleSignal.psm1") -Force
}

Describe "Start-QA" {
    BeforeEach {
        $script:roomDir = Join-Path $TestDrive "room-qa-$(Get-Random)"
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

        "review" | Out-File (Join-Path $script:roomDir "status") -NoNewline
        New-Item -ItemType File -Path (Join-Path $script:roomDir "channel.jsonl") -Force | Out-Null

        # Create a config with echo mock
        $script:configFile = Join-Path $TestDrive "config-qa.json"
        @{
            engineer = @{
                cli              = "echo"
                default_model    = "test-model"
                timeout_seconds  = 10
            }
            qa = @{
                cli             = "echo"
                default_model   = "test-model"
                approval_mode   = "auto-approve"
                timeout_seconds = 10
            }
        } | ConvertTo-Json -Depth 3 | Out-File $script:configFile -Encoding utf8
        $env:AGENT_OS_CONFIG = $script:configFile
        $env:QA_CMD = "echo"
    }

    AfterEach {
        Remove-Item Env:AGENT_OS_CONFIG -ErrorAction SilentlyContinue
        Remove-Item Env:QA_CMD -ErrorAction SilentlyContinue
    }

    Context "Room state reading" {
        It "reads task-ref from room" {
            $taskRef = (Get-Content (Join-Path $script:roomDir "task-ref") -Raw).Trim()
            $taskRef | Should -Be "TASK-001"
        }

        It "reads brief.md for original assignment" {
            $brief = Get-Content (Join-Path $script:roomDir "brief.md") -Raw
            $brief | Should -Match "hello world"
        }
    }

    Context "Epic detection" {
        It "detects EPIC prefix for epic-specific review" {
            "EPIC-001" | Out-File (Join-Path $script:roomDir "task-ref") -NoNewline
            $taskRef = (Get-Content (Join-Path $script:roomDir "task-ref") -Raw).Trim()
            ($taskRef -match '^EPIC-') | Should -BeTrue
        }

        It "task prefix uses standard review" {
            $taskRef = (Get-Content (Join-Path $script:roomDir "task-ref") -Raw).Trim()
            ($taskRef -match '^EPIC-') | Should -BeFalse
        }
    }

    Context "Verdict parsing" {
        It "parses VERDICT: DONE from strict format" {
            $output = "Review complete.`nVERDICT: DONE`nAll tests pass."
            Get-AgentVerdict -Output $output | Should -Be "DONE"
        }

        It "parses VERDICT: FAIL from strict format" {
            $output = "Found issues.`nVERDICT: FAIL`nMissing tests."
            Get-AgentVerdict -Output $output | Should -Be "FAIL"
        }

        It "parses VERDICT: DONE from inline format" {
            $output = "The result is VERDICT: DONE because..."
            Get-AgentVerdict -Output $output | Should -Be "DONE"
        }

        It "accepts legacy VERDICT: PASS and maps it to the selected success signal" {
            $output = "Review complete.`nVERDICT: PASS`nAll tests pass."
            $verdict = Get-AgentVerdict -Output $output
            $verdict | Should -Be "PASS"
            Convert-VerdictToLifecycleSignal -Verdict $verdict -DefaultSuccessSignal "done" | Should -Be "done"
        }

        It "maps legacy VERDICT: PASS to pass when the lifecycle only accepts pass" {
            $verdict = Get-AgentVerdict -Output "VERDICT: PASS"
            Convert-VerdictToLifecycleSignal -Verdict $verdict -DefaultSuccessSignal "pass" | Should -Be "pass"
        }

        It "returns empty for no verdict" {
            $output = "Indeterminate review result."
            Get-AgentVerdict -Output $output | Should -Be ""
        }

        It "parses VERDICT: ESCALATE from strict format" {
            $output = "This is a design problem.`nVERDICT: ESCALATE`nArchitecture needs rethinking."
            Get-AgentVerdict -Output $output | Should -Be "ESCALATE"
        }

        It "parses VERDICT: ESCALATE from inline format" {
            $output = "The result is VERDICT: ESCALATE because the requirements are wrong."
            Get-AgentVerdict -Output $output | Should -Be "ESCALATE"
        }
    }

    Context "TASKS.md for epics" {
        It "reads TASKS.md when reviewing an epic" {
            "EPIC-001" | Out-File (Join-Path $script:roomDir "task-ref") -NoNewline
            $tasksContent = "- [x] TASK-001 — Auth`n- [x] TASK-002 — Dashboard"
            $tasksContent | Out-File (Join-Path $script:roomDir "TASKS.md") -Encoding utf8

            $tasksMd = Get-Content (Join-Path $script:roomDir "TASKS.md") -Raw
            $tasksMd | Should -Match "TASK-001"
            $tasksMd | Should -Match "TASK-002"
        }

        It "handles missing TASKS.md gracefully" {
            "EPIC-001" | Out-File (Join-Path $script:roomDir "task-ref") -NoNewline
            $tasksFile = Join-Path $script:roomDir "TASKS.md"
            Test-Path $tasksFile | Should -BeFalse
            # Should not throw
        }
    }
}
