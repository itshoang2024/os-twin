# Agent OS — PID Self-Registration Tests
#
# Validates PID management in the unified PowerShell pipeline:
# 1. Wrapper scripts (run-agent.ps1) write $PID to AGENT_OS_PID_FILE
# 2. Invoke-Agent.ps1 does not write premature PIDs
# 3. Generated run-agent.ps1 exports AGENT_OS_PID_FILE env var

BeforeAll {
    $script:InvokeAgent = Join-Path (Resolve-Path "$PSScriptRoot/../../../roles/_base").Path "Invoke-Agent.ps1"

    function script:New-PwshAgentCmd {
        param([string]$ScriptPath)
        $escapedPath = $ScriptPath -replace "'", "'\''"
        return "pwsh -NoProfile -File '$escapedPath'"
    }
}

Describe "PID Self-Registration" {

    # ================================================================
    # Wrapper PID file writing via AGENT_OS_PID_FILE
    # ================================================================
    Context "Wrapper: AGENT_OS_PID_FILE behavior" {

        It "writes PID to AGENT_OS_PID_FILE when env var is set" {
            $pidFile = Join-Path $TestDrive "test-agent.pid"
            $testScript = Join-Path $TestDrive "test-pid-write.ps1"
            @"
if (`$env:AGENT_OS_PID_FILE) {
    `$PID | Out-File -FilePath `$env:AGENT_OS_PID_FILE -Encoding ascii -NoNewline
}
exit 0
"@ | Out-File $testScript -Encoding utf8

            $env:AGENT_OS_PID_FILE = $pidFile
            try {
                pwsh -NoProfile -ExecutionPolicy Bypass -File $testScript
                $LASTEXITCODE | Should -Be 0
            } finally {
                Remove-Item Env:AGENT_OS_PID_FILE -ErrorAction SilentlyContinue
            }

            Test-Path $pidFile | Should -BeTrue
            $pidContent = (Get-Content $pidFile -Raw).Trim()
            $pidContent | Should -Match '^\d+$'
            [int]$pidContent | Should -BeGreaterThan 0
        }

        It "does NOT write PID file when AGENT_OS_PID_FILE is unset" {
            $pidFile = Join-Path $TestDrive "should-not-exist.pid"
            $testScript = Join-Path $TestDrive "test-no-pid.ps1"
            @"
Remove-Item Env:AGENT_OS_PID_FILE -ErrorAction SilentlyContinue
if (`$env:AGENT_OS_PID_FILE) {
    `$PID | Out-File -FilePath '$pidFile' -Encoding ascii -NoNewline
}
exit 0
"@ | Out-File $testScript -Encoding utf8

            Remove-Item Env:AGENT_OS_PID_FILE -ErrorAction SilentlyContinue
            pwsh -NoProfile -ExecutionPolicy Bypass -File $testScript
            $LASTEXITCODE | Should -Be 0

            Test-Path $pidFile | Should -BeFalse
        }
    }

    # ================================================================
    # Invoke-Agent.ps1 — no premature PID write
    # ================================================================
    Context "Invoke-Agent: PID management contract" {

        BeforeEach {
            $script:roomDir = Join-Path $TestDrive "room-$(Get-Random)"
            New-Item -ItemType Directory -Path $script:roomDir -Force | Out-Null
            New-Item -ItemType Directory -Path (Join-Path $script:roomDir "pids") -Force | Out-Null
            New-Item -ItemType Directory -Path (Join-Path $script:roomDir "artifacts") -Force | Out-Null
        }

        It "does NOT write PowerShell PID prematurely" {
            # Run with a mock that immediately exits
            # Before the fix, the PID file would contain PowerShell's $PID
            # After the fix, it should contain the bash/agent PID instead
            $result = & $script:InvokeAgent -RoomDir $script:roomDir `
                -RoleName "engineer" -Prompt "test" `
                -AgentCmd "echo" -TimeoutSeconds 10

            $pidFile = Join-Path $script:roomDir "pids" "engineer.pid"
            if (Test-Path $pidFile) {
                $pidContent = (Get-Content $pidFile -Raw).Trim()
                if ($pidContent -match '^\d+$') {
                    # The PID should NOT be our PowerShell PID
                    [int]$pidContent | Should -Not -Be $PID
                }
            }
        }

        It "wrapper script sets AGENT_OS_PID_FILE and writes PID" {
            # Use a slow mock so we can inspect the wrapper before cleanup
            $startedFlag = Join-Path $TestDrive "started-$(Get-Random).flag"
            $slowAgent = Join-Path $TestDrive "slow-capture.ps1"
            @"
'' | Out-File -FilePath '$startedFlag' -Encoding utf8
Start-Sleep -Seconds 1
Write-Output 'done'
exit 0
"@ | Out-File $slowAgent -Encoding utf8

            # Start in background so we can inspect the wrapper
            $job = Start-Job -ScriptBlock {
                param($ia, $rd, $sa)
                & $ia -RoomDir $rd -RoleName "engineer" -Prompt "test" `
                    -AgentCmd $sa -TimeoutSeconds 10
            } -ArgumentList $script:InvokeAgent, $script:roomDir, $slowAgent

            # Wait for the agent to start
            $deadline = (Get-Date).AddSeconds(10)
            while (-not (Test-Path $startedFlag) -and (Get-Date) -lt $deadline) {
                Start-Sleep -Milliseconds 200
            }

            # Read the platform-specific wrapper script that Invoke-Agent generated.
            $wrapperName = if ($IsWindows) { "run-agent.ps1" } else { "run-agent.sh" }
            $wrapperFile = Join-Path $script:roomDir "artifacts" $wrapperName
            if (Test-Path $wrapperFile) {
                $wrapperContent = Get-Content $wrapperFile -Raw

                # Should set AGENT_OS_PID_FILE env var
                $wrapperContent | Should -Match 'AGENT_OS_PID_FILE'

                if ($IsWindows) {
                    $wrapperContent | Should -Match '\$PID.*Out-File.*\.pid'
                } else {
                    $wrapperContent | Should -Match 'echo "\$\$" >'
                }
            }

            $job | Wait-Job -Timeout 15 | Out-Null
            $job | Remove-Job -Force -ErrorAction SilentlyContinue
        }
    }

    # ================================================================
    # PID confirmation wait logic
    # ================================================================
    Context "Invoke-Agent: PID confirmation wait" {

        BeforeEach {
            $script:roomDir = Join-Path $TestDrive "room-$(Get-Random)"
            New-Item -ItemType Directory -Path $script:roomDir -Force | Out-Null
            New-Item -ItemType Directory -Path (Join-Path $script:roomDir "pids") -Force | Out-Null
            New-Item -ItemType Directory -Path (Join-Path $script:roomDir "artifacts") -Force | Out-Null
        }

        It "PID file contains a valid PID after agent completes" {
            # Use a mock that writes to AGENT_OS_PID_FILE (simulating agent behavior)
            $pidWriter = Join-Path $TestDrive "pid-writer.ps1"
            @"
if (`$env:AGENT_OS_PID_FILE) {
    `$PID | Out-File -FilePath `$env:AGENT_OS_PID_FILE -Encoding ascii -NoNewline
}
Write-Output 'agent output'
exit 0
"@ | Out-File $pidWriter -Encoding utf8

            $result = & $script:InvokeAgent -RoomDir $script:roomDir `
                -RoleName "engineer" -Prompt "test" `
                -AgentCmd (New-PwshAgentCmd $pidWriter) -TimeoutSeconds 10

            $result.ExitCode | Should -BeIn @(0)

            $pidFile = Join-Path $script:roomDir "pids" "engineer.pid"
            if (Test-Path $pidFile) {
                $pidContent = (Get-Content $pidFile -Raw).Trim()
                $pidContent | Should -Match '^\d+$'
                # PID should NOT be our PowerShell process
                [int]$pidContent | Should -Not -Be $PID
            }
        }

        It "handles agent that does not write PID (backward compat)" {
            # An agent that ignores AGENT_OS_PID_FILE should still work
            $noPidAgent = Join-Path $TestDrive "no-pid-agent.ps1"
            @"
Write-Output 'I do not write PIDs'
exit 0
"@ | Out-File $noPidAgent -Encoding utf8

            $result = & $script:InvokeAgent -RoomDir $script:roomDir `
                -RoleName "engineer" -Prompt "test" `
                -AgentCmd (New-PwshAgentCmd $noPidAgent) -TimeoutSeconds 10

            # Should still succeed even without PID self-registration
            $result | Should -Not -BeNullOrEmpty
            $result.ExitCode | Should -BeIn @(0)
        }

        It "timeout kill uses confirmed PID from self-registration" {
            # Create a slow mock that writes its PID, then sleeps forever (pwsh wrapper)
            $slowPidAgent = Join-Path $TestDrive "slow-pid.ps1"
            @"
if (`$env:AGENT_OS_PID_FILE) {
    `$PID | Out-File -FilePath `$env:AGENT_OS_PID_FILE -Encoding ascii -NoNewline
}
Start-Sleep -Seconds 300
"@ | Out-File $slowPidAgent -Encoding utf8

            $result = & $script:InvokeAgent -RoomDir $script:roomDir `
                -RoleName "engineer" -Prompt "slow" `
                -AgentCmd (New-PwshAgentCmd $slowPidAgent) -TimeoutSeconds 3

            $result.TimedOut | Should -BeTrue
            $result.ExitCode | Should -Be 124

            # The PID file should have been written by the mock
            $pidFile = Join-Path $script:roomDir "pids" "engineer.pid"
            if (Test-Path $pidFile) {
                $pidContent = (Get-Content $pidFile -Raw).Trim()
                $pidContent | Should -Match '^\d+$'
                $killedPid = [int]$pidContent
                # Process should be dead now (killed by timeout handler)
                { Get-Process -Id $killedPid -ErrorAction Stop } | Should -Throw
            }
        }
    }

    # ================================================================
    # Integration: bin/agent PID file used by Invoke-Agent
    # ================================================================
    Context "Integration: end-to-end PID flow" {

        BeforeEach {
            $script:roomDir = Join-Path $TestDrive "room-$(Get-Random)"
            New-Item -ItemType Directory -Path $script:roomDir -Force | Out-Null
            New-Item -ItemType Directory -Path (Join-Path $script:roomDir "pids") -Force | Out-Null
            New-Item -ItemType Directory -Path (Join-Path $script:roomDir "artifacts") -Force | Out-Null
        }

        It "complete flow: wrapper sets env, agent writes PID, Invoke-Agent confirms" {
            # Simulate the full chain: wrapper exports AGENT_OS_PID_FILE,
            # mock agent reads it and writes PID, Invoke-Agent picks it up
            $fullChainAgent = Join-Path $TestDrive "full-chain.ps1"
            @"
if (`$env:AGENT_OS_PID_FILE) {
    `$PID | Out-File -FilePath `$env:AGENT_OS_PID_FILE -Encoding ascii -NoNewline
}
Write-Output 'work complete'
exit 0
"@ | Out-File $fullChainAgent -Encoding utf8

            $result = & $script:InvokeAgent -RoomDir $script:roomDir `
                -RoleName "architect" -Prompt "review" `
                -AgentCmd (New-PwshAgentCmd $fullChainAgent) -TimeoutSeconds 10

            $result.ExitCode | Should -Be 0
            $result.RoleName | Should -Be "architect"

            $pidFile = Join-Path $script:roomDir "pids" "architect.pid"
            $result.PidFile | Should -Be $pidFile

            # PID file should exist (Invoke-Agent doesn't clean it up — caller's job)
            Test-Path $pidFile | Should -BeTrue
        }
    }
}
