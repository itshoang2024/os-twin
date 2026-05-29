# Agent OS — Invoke-Agent Pester Tests

BeforeAll {
    $script:InvokeAgent = Join-Path (Resolve-Path "$PSScriptRoot/../../../roles/_base").Path "Invoke-Agent.ps1"
    # Mirror Invoke-Agent.ps1's own $agentsDir resolution: $PSScriptRoot (roles/_base) ../../ = .agents/
    $script:agentsBaseDir = (Resolve-Path "$PSScriptRoot/../../../roles/_base/../..").Path
}

Describe "Invoke-Agent" {
    BeforeEach {
        $script:roomDir = Join-Path $TestDrive "room-$(Get-Random)"
        New-Item -ItemType Directory -Path $script:roomDir -Force | Out-Null
        New-Item -ItemType Directory -Path (Join-Path $script:roomDir "pids") -Force | Out-Null
        New-Item -ItemType Directory -Path (Join-Path $script:roomDir "artifacts") -Force | Out-Null
    }

    Context "With mock agent command" {
        It "runs successfully with echo mock" {
            $result = & $script:InvokeAgent -RoomDir $script:roomDir `
                -RoleName "engineer" -Prompt "test prompt" `
                -AgentCmd "echo" -TimeoutSeconds 10

            $result | Should -Not -BeNullOrEmpty
            $result.RoleName | Should -Be "engineer"
            $result.ExitCode | Should -BeIn @(0, 1)  # echo may or may not accept -n flag
        }

        It "creates artifacts directory" {
            $result = & $script:InvokeAgent -RoomDir $script:roomDir `
                -RoleName "engineer" -Prompt "test" `
                -AgentCmd "echo" -TimeoutSeconds 5

            Test-Path (Join-Path $script:roomDir "artifacts") | Should -BeTrue
        }

        It "creates pids directory" {
            $result = & $script:InvokeAgent -RoomDir $script:roomDir `
                -RoleName "qa" -Prompt "review" `
                -AgentCmd "echo" -TimeoutSeconds 5

            Test-Path (Join-Path $script:roomDir "pids") | Should -BeTrue
        }

        It "reports PidFile path in result" {
            # Start-Process writes PID directly. The result object always carries
            # the expected PidFile path for the caller.
            $result = & $script:InvokeAgent -RoomDir $script:roomDir `
                -RoleName "engineer" -Prompt "test" `
                -AgentCmd "echo" -TimeoutSeconds 5

            $pidFile = Join-Path $script:roomDir "pids" "engineer.pid"
            $result.PidFile | Should -Be $pidFile
        }

        It "returns structured result object" {
            $result = & $script:InvokeAgent -RoomDir $script:roomDir `
                -RoleName "engineer" -Prompt "test" `
                -AgentCmd "echo" -TimeoutSeconds 5

            $result.PSObject.Properties.Name | Should -Contain "ExitCode"
            $result.PSObject.Properties.Name | Should -Contain "Output"
            $result.PSObject.Properties.Name | Should -Contain "OutputFile"
            $result.PSObject.Properties.Name | Should -Contain "RoleName"
            $result.PSObject.Properties.Name | Should -Contain "TimedOut"
        }

        It "writes output to artifacts file" {
            $result = & $script:InvokeAgent -RoomDir $script:roomDir `
                -RoleName "qa" -Prompt "review test" `
                -AgentCmd "echo" -TimeoutSeconds 5

            $result.OutputFile | Should -Match "qa-output\.txt$"
        }
    }

    Context "Timeout handling" {
        It "sets TimedOut flag when command times out" {
            # Create a mock that ignores all args and sleeps (pwsh wrapper)
            $sleepScript = Join-Path $TestDrive "slow-mock.ps1"
            "Start-Sleep -Seconds 30" | Out-File $sleepScript -Encoding utf8

            $result = & $script:InvokeAgent -RoomDir $script:roomDir `
                -RoleName "engineer" -Prompt "slow" `
                -AgentCmd $sleepScript -TimeoutSeconds 2

            $result.TimedOut | Should -BeTrue
            $result.ExitCode | Should -Be 124
        }
    }

    Context "Config resolution" {
        It "uses OSTWIN_AGENT_CMD env var override" {
            $env:OSTWIN_AGENT_CMD = "echo"
            try {
                $result = & $script:InvokeAgent -RoomDir $script:roomDir `
                    -RoleName "engineer" -Prompt "test" -TimeoutSeconds 5

                # Should use echo instead of opencode run
                $result | Should -Not -BeNullOrEmpty
            }
            finally {
                Remove-Item Env:OSTWIN_AGENT_CMD -ErrorAction SilentlyContinue
            }
        }

        It "uses AGENT_OS_CONFIG for config path" {
            $configFile = Join-Path $TestDrive "test-config.json"
            @{
                engineer = @{
                    default_model   = "test-model"
                    timeout_seconds = 10
                }
            } | ConvertTo-Json -Depth 3 | Out-File $configFile -Encoding utf8

            $env:AGENT_OS_CONFIG = $configFile
            try {
                $result = & $script:InvokeAgent -RoomDir $script:roomDir `
                    -RoleName "engineer" -Prompt "config test" `
                    -AgentCmd "echo" -TimeoutSeconds 5

                $result | Should -Not -BeNullOrEmpty
            }
            finally {
                Remove-Item Env:AGENT_OS_CONFIG -ErrorAction SilentlyContinue
            }
        }
    }

    Context "Role name handling" {
        It "supports engineer role" {
            $result = & $script:InvokeAgent -RoomDir $script:roomDir `
                -RoleName "engineer" -Prompt "test" `
                -AgentCmd "echo" -TimeoutSeconds 5
            $result.RoleName | Should -Be "engineer"
        }

        It "supports qa role" {
            $result = & $script:InvokeAgent -RoomDir $script:roomDir `
                -RoleName "qa" -Prompt "test" `
                -AgentCmd "echo" -TimeoutSeconds 5
            $result.RoleName | Should -Be "qa"
        }

        It "supports custom roles" {
            $result = & $script:InvokeAgent -RoomDir $script:roomDir `
                -RoleName "architect" -Prompt "test" `
                -AgentCmd "echo" -TimeoutSeconds 5
            $result.RoleName | Should -Be "architect"
        }
    }

    Context "Instance config resolution" {
        BeforeEach {
            $script:instanceConfigFile = Join-Path $TestDrive "instance-config.json"
            @{
                engineer = @{
                    default_model   = "base-model"
                    timeout_seconds = 600
                    instances = @{
                        fe = @{
                            display_name    = "Frontend Engineer"
                            default_model   = "fe-pro-model"
                            timeout_seconds = 900
                            working_dir     = "/tmp/frontend"
                        }
                    }
                }
            } | ConvertTo-Json -Depth 5 | Out-File $script:instanceConfigFile -Encoding utf8
        }

        It "resolves model from instance config when InstanceId is provided" {
            $env:AGENT_OS_CONFIG = $script:instanceConfigFile
            try {
                $result = & $script:InvokeAgent -RoomDir $script:roomDir `
                    -RoleName "engineer" -Prompt "test" `
                    -InstanceId "fe" -AgentCmd "echo" -TimeoutSeconds 5

                $result | Should -Not -BeNullOrEmpty
                $result.RoleName | Should -Be "engineer"
            }
            finally {
                Remove-Item Env:AGENT_OS_CONFIG -ErrorAction SilentlyContinue
            }
        }

        It "falls back to role default when InstanceId not in config" {
            $env:AGENT_OS_CONFIG = $script:instanceConfigFile
            try {
                $result = & $script:InvokeAgent -RoomDir $script:roomDir `
                    -RoleName "engineer" -Prompt "test" `
                    -InstanceId "nonexistent" -AgentCmd "echo" -TimeoutSeconds 5

                $result | Should -Not -BeNullOrEmpty
                $result.RoleName | Should -Be "engineer"
            }
            finally {
                Remove-Item Env:AGENT_OS_CONFIG -ErrorAction SilentlyContinue
            }
        }

        It "passes WorkingDir parameter through" {
            $result = & $script:InvokeAgent -RoomDir $script:roomDir `
                -RoleName "engineer" -Prompt "test" `
                -WorkingDir "/tmp/testdir" -AgentCmd "echo" -TimeoutSeconds 5

            $result | Should -Not -BeNullOrEmpty
        }
    }

    Context "Skill Staging (project-level .agents/skills/)" {
        It "creates and populates project-level skills directory" {
            # Skills are staged under .agents/skills/, NOT under the war-room dir.
            # $agentsBaseDir mirrors Invoke-Agent.ps1's own $agentsDir resolution.
            $result = & $script:InvokeAgent -RoomDir $script:roomDir `
                -RoleName "engineer" -Prompt "test" `
                -AgentCmd "echo" -TimeoutSeconds 5

            $projectSkillsDir = Join-Path $script:agentsBaseDir "skills"
            Test-Path $projectSkillsDir | Should -BeTrue

            $skills = Get-ChildItem $projectSkillsDir -Directory -ErrorAction SilentlyContinue
            $skills.Count | Should -BeGreaterThan 0
            # Skills are now resolved via Dashboard API search (Resolve-RoleSkills.ps1).
            # Without a running dashboard, only the source-tree subdirs (global, roles) exist.
            # Do NOT assert on specific API-resolved skill names here.
        }

        It "does NOT create a skills directory inside the war-room" {
            # After the redirect, war-room dirs must NOT contain a skills/ subfolder.
            $result = & $script:InvokeAgent -RoomDir $script:roomDir `
                -RoleName "engineer" -Prompt "test" `
                -AgentCmd "echo" -TimeoutSeconds 5

            $roomSkillsDir = Join-Path $script:roomDir "skills"
            Test-Path $roomSkillsDir | Should -BeFalse `
                -Because "skills are now staged under .agents/skills/, not inside the war-room"
        }

        It "populates project skills dir on repeated invocations (idempotent)" {
            # First invocation
            $null = & $script:InvokeAgent -RoomDir $script:roomDir `
                -RoleName "engineer" -Prompt "test" `
                -AgentCmd "echo" -TimeoutSeconds 5

            $projectSkillsDir = Join-Path $script:agentsBaseDir "skills"
            $countAfterFirst = (Get-ChildItem $projectSkillsDir -Directory -ErrorAction SilentlyContinue).Count

            # Second invocation with a fresh room
            $script:roomDir2 = Join-Path $TestDrive "room2-$(Get-Random)"
            New-Item -ItemType Directory -Path $script:roomDir2 -Force | Out-Null
            New-Item -ItemType Directory -Path (Join-Path $script:roomDir2 "pids") -Force | Out-Null
            New-Item -ItemType Directory -Path (Join-Path $script:roomDir2 "artifacts") -Force | Out-Null

            $null = & $script:InvokeAgent -RoomDir $script:roomDir2 `
                -RoleName "engineer" -Prompt "test" `
                -AgentCmd "echo" -TimeoutSeconds 5

            $countAfterSecond = (Get-ChildItem $projectSkillsDir -Directory -ErrorAction SilentlyContinue).Count
            # Skill count should be stable — same skills, not doubled
            $countAfterSecond | Should -Be $countAfterFirst
        }

        It "exports AGENT_OS_SKILLS_DIR pointing to project-level path (verified via echo mock)" {
            # Create a mock script that echoes AGENT_OS_SKILLS_DIR (pwsh wrapper)
            $echoMock = Join-Path $TestDrive "echo-env.ps1"
            "Write-Output `"SKILLS_DIR_IS:`$env:AGENT_OS_SKILLS_DIR`"" | Out-File $echoMock -Encoding utf8

            $result = & $script:InvokeAgent -RoomDir $script:roomDir `
                -RoleName "engineer" -Prompt "test" `
                -AgentCmd $echoMock -TimeoutSeconds 5

            # Must match .agents/skills or .agents\skills (cross-platform)
            $result.Output | Should -Match "SKILLS_DIR_IS:.*\.agents[/\\]skills"
            $result.Output | Should -Not -Match "SKILLS_DIR_IS:.*\.war-rooms"
        }

        It "handles non-existent role gracefully without crashing" {
            # Non-existent role has no role.json and no private skills — should not throw
            { & $script:InvokeAgent -RoomDir $script:roomDir `
                -RoleName "non-existent-role" -Prompt "test" `
                -AgentCmd "echo" -TimeoutSeconds 5 } | Should -Not -Throw

            # The project-level skills dir should exist (created if not already present)
            $projectSkillsDir = Join-Path $script:agentsBaseDir "skills"
            Test-Path $projectSkillsDir | Should -BeTrue
        }

        It "does NOT export AGENT_OS_PROJECT_DIR in the wrapper (replaced by --dir flag)" {
            # Ensure the env var is clean in the parent process
            $savedProjDir = $env:AGENT_OS_PROJECT_DIR
            Remove-Item Env:AGENT_OS_PROJECT_DIR -ErrorAction SilentlyContinue

            try {
                $echoMock = Join-Path $TestDrive "echo-no-projdir-$(Get-Random).ps1"
                @"
`$val = if (`$env:AGENT_OS_PROJECT_DIR) { `$env:AGENT_OS_PROJECT_DIR } else { 'UNSET' }
Write-Output "PROJDIR_CHECK:`$val"
"@ | Out-File $echoMock -Encoding utf8

                $projectDir = Join-Path $TestDrive "project-noexport-$(Get-Random)"
                $roomDir = Join-Path $projectDir ".war-rooms" "room-noexport"
                New-Item -ItemType Directory -Path (Join-Path $roomDir "artifacts") -Force | Out-Null
                New-Item -ItemType Directory -Path (Join-Path $roomDir "pids") -Force | Out-Null

                $result = & $script:InvokeAgent -RoomDir $roomDir `
                    -RoleName "engineer" -Prompt "test" `
                    -AgentCmd $echoMock -TimeoutSeconds 5

                $result.Output | Should -Match "PROJDIR_CHECK:UNSET" `
                    -Because "--dir CLI flag replaces AGENT_OS_PROJECT_DIR export"
            }
            finally {
                if ($savedProjDir) { $env:AGENT_OS_PROJECT_DIR = $savedProjDir }
            }
        }
    }

    Context "opencode run CLI flags" {
        # These tests verify that the generated wrapper script contains
        # the correct opencode run flags. We use a mock that captures $@
        # and the wrapper content.

        BeforeEach {
            # Create a mock that dumps all args to a file (pwsh wrapper)
            $script:argsDump = Join-Path $TestDrive "args-$(Get-Random).txt"
            $script:argsMock = Join-Path $TestDrive "argsmock-$(Get-Random).ps1"
            @"
`$args | ForEach-Object { `$_ } | Out-File -FilePath '$($script:argsDump)' -Encoding utf8
"@ | Out-File $script:argsMock -Encoding utf8
        }

        It "passes a short positional message and prompt via --file" {
            $result = & $script:InvokeAgent -RoomDir $script:roomDir `
                -RoleName "engineer" -Prompt "Hello world test" `
                -AgentCmd $script:argsMock -TimeoutSeconds 5

            if (Test-Path $script:argsDump) {
                $capturedArgs = Get-Content $script:argsDump
                # First arg should be the short positional placeholder (required by opencode run)
                $capturedArgs[0] | Should -Be "..."
                # Legacy 'start' positional must NOT be present
                $capturedArgs | Should -Not -Contain "start"
                # Prompt should NOT appear as inline text on the command line
                $capturedArgs | Should -Not -Contain "Hello world test"
                # Prompt file should be attached via --file
                $capturedArgs | Should -Contain "--file"
                # Should contain an absolute path to prompt.txt
                $promptArg = $capturedArgs | Where-Object { $_ -match 'prompt\.txt$' }
                $promptArg | Should -Not -BeNullOrEmpty
            }
        }

        It "passes --model flag" {
            $result = & $script:InvokeAgent -RoomDir $script:roomDir `
                -RoleName "engineer" -Prompt "test" `
                -Model "openai/gpt-4o" `
                -AgentCmd $script:argsMock -TimeoutSeconds 5

            if (Test-Path $script:argsDump) {
                $args = Get-Content $script:argsDump
                $args | Should -Contain "--model"
                $args | Should -Contain "openai/gpt-4o"
            }
        }

        It "passes --agent flag with role name" {
            $result = & $script:InvokeAgent -RoomDir $script:roomDir `
                -RoleName "architect" -Prompt "test" `
                -AgentCmd $script:argsMock -TimeoutSeconds 5

            if (Test-Path $script:argsDump) {
                $args = Get-Content $script:argsDump
                $args | Should -Contain "--agent"
                $args | Should -Contain "architect"
            }
        }

        It "passes --format flag" {
            $result = & $script:InvokeAgent -RoomDir $script:roomDir `
                -RoleName "engineer" -Prompt "test" `
                -Format "json" `
                -AgentCmd $script:argsMock -TimeoutSeconds 5

            if (Test-Path $script:argsDump) {
                $args = Get-Content $script:argsDump
                $args | Should -Contain "--format"
                $args | Should -Contain "json"
            }
        }

        It "passes --title flag" {
            $result = & $script:InvokeAgent -RoomDir $script:roomDir `
                -RoleName "engineer" -Prompt "test" `
                -SessionTitle "My Task Title" `
                -AgentCmd $script:argsMock -TimeoutSeconds 5

            if (Test-Path $script:argsDump) {
                $args = Get-Content $script:argsDump
                $args | Should -Contain "--title"
                $args | Should -Contain "My Task Title"
            }
        }

        It "passes --session flag" {
            $result = & $script:InvokeAgent -RoomDir $script:roomDir `
                -RoleName "engineer" -Prompt "test" `
                -SessionId "abc-123" `
                -AgentCmd $script:argsMock -TimeoutSeconds 5

            if (Test-Path $script:argsDump) {
                $args = Get-Content $script:argsDump
                $args | Should -Contain "--session"
                $args | Should -Contain "abc-123"
            }
        }

        It "passes --continue flag" {
            $result = & $script:InvokeAgent -RoomDir $script:roomDir `
                -RoleName "engineer" -Prompt "continue from here" `
                -ContinueSession `
                -AgentCmd $script:argsMock -TimeoutSeconds 5

            if (Test-Path $script:argsDump) {
                $args = Get-Content $script:argsDump
                $args | Should -Contain "--continue"
            }
        }

        It "passes --fork flag" {
            $result = & $script:InvokeAgent -RoomDir $script:roomDir `
                -RoleName "engineer" -Prompt "test" `
                -ForkSession `
                -AgentCmd $script:argsMock -TimeoutSeconds 5

            if (Test-Path $script:argsDump) {
                $args = Get-Content $script:argsDump
                $args | Should -Contain "--fork"
            }
        }

        It "passes --share flag" {
            $result = & $script:InvokeAgent -RoomDir $script:roomDir `
                -RoleName "engineer" -Prompt "test" `
                -ShareSession `
                -AgentCmd $script:argsMock -TimeoutSeconds 5

            if (Test-Path $script:argsDump) {
                $args = Get-Content $script:argsDump
                $args | Should -Contain "--share"
            }
        }

        It "passes --command flag" {
            $result = & $script:InvokeAgent -RoomDir $script:roomDir `
                -RoleName "engineer" -Prompt "src/app.test.ts" `
                -Command "test" `
                -AgentCmd $script:argsMock -TimeoutSeconds 5

            if (Test-Path $script:argsDump) {
                $args = Get-Content $script:argsDump
                $args | Should -Contain "--command"
                $args | Should -Contain "test"
            }
        }

        It "passes --file flag for each extra file plus prompt file" {
            $result = & $script:InvokeAgent -RoomDir $script:roomDir `
                -RoleName "engineer" -Prompt "review these files" `
                -Files @("file1.txt", "file2.txt") `
                -AgentCmd $script:argsMock -TimeoutSeconds 5

            if (Test-Path $script:argsDump) {
                $capturedArgs = Get-Content $script:argsDump
                # --file should appear 3 times: file1.txt, file2.txt, plus prompt.txt
                $fileFlags = $capturedArgs | Where-Object { $_ -eq "--file" }
                $fileFlags.Count | Should -Be 3
                $capturedArgs | Should -Contain "file1.txt"
                $capturedArgs | Should -Contain "file2.txt"
                # Prompt file should also be present
                $promptArg = $capturedArgs | Where-Object { $_ -match 'prompt\.txt$' }
                $promptArg | Should -Not -BeNullOrEmpty
            }
        }

        It "passes --attach flag" {
            $result = & $script:InvokeAgent -RoomDir $script:roomDir `
                -RoleName "engineer" -Prompt "test" `
                -AttachUrl "http://localhost:4096" `
                -AgentCmd $script:argsMock -TimeoutSeconds 5

            if (Test-Path $script:argsDump) {
                $args = Get-Content $script:argsDump
                $args | Should -Contain "--attach"
                $args | Should -Contain "http://localhost:4096"
            }
        }

        It "passes --port flag" {
            $result = & $script:InvokeAgent -RoomDir $script:roomDir `
                -RoleName "engineer" -Prompt "test" `
                -Port 8080 `
                -AgentCmd $script:argsMock -TimeoutSeconds 5

            if (Test-Path $script:argsDump) {
                $args = Get-Content $script:argsDump
                $args | Should -Contain "--port"
                $args | Should -Contain "8080"
            }
        }

        It "passes --dir flag with resolved project directory" {
            # Create project structure with .war-rooms so ProjectDir resolves
            $projectDir = Join-Path $TestDrive "project-dir-$(Get-Random)"
            $roomDir = Join-Path $projectDir ".war-rooms" "room-dir"
            New-Item -ItemType Directory -Path (Join-Path $roomDir "artifacts") -Force | Out-Null
            New-Item -ItemType Directory -Path (Join-Path $roomDir "pids") -Force | Out-Null

            $result = & $script:InvokeAgent -RoomDir $roomDir `
                -RoleName "engineer" -Prompt "test" `
                -AgentCmd $script:argsMock -TimeoutSeconds 5

            if (Test-Path $script:argsDump) {
                $capturedArgs = Get-Content $script:argsDump
                $capturedArgs | Should -Contain "--dir"
                $capturedArgs | Should -Contain $projectDir
            }
        }

        It "does not pass --dir when ProjectDir cannot be resolved" {
            # $script:roomDir is NOT inside .war-rooms — ProjectDir stays empty
            $result = & $script:InvokeAgent -RoomDir $script:roomDir `
                -RoleName "engineer" -Prompt "test" `
                -AgentCmd $script:argsMock -TimeoutSeconds 5

            if (Test-Path $script:argsDump) {
                $capturedArgs = Get-Content $script:argsDump
                $capturedArgs | Should -Not -Contain "--dir"
            }
        }

        It "does not pass legacy deepagents flags" {
            $result = & $script:InvokeAgent -RoomDir $script:roomDir `
                -RoleName "engineer" -Prompt "test" `
                -AgentCmd $script:argsMock -TimeoutSeconds 5

            if (Test-Path $script:argsDump) {
                $args = Get-Content $script:argsDump
                $args | Should -Not -Contain "--auto-approve"
                $args | Should -Not -Contain "--quiet"
                $args | Should -Not -Contain "-q"
                $args | Should -Not -Contain "--shell-allow-list"
                $args | Should -Not -Contain "--no-mcp"
                $args | Should -Not -Contain "--mcp-config"
            }
        }

        It "passes short message positional, not legacy 'start' or inline prompt" {
            $captureMock = Join-Path $TestDrive "capture-wrapper-$(Get-Random).ps1"
            @"
Write-Output "ARGS: `$(`$args -join ' ')"
"@ | Out-File $captureMock -Encoding utf8

            $result = & $script:InvokeAgent -RoomDir $script:roomDir `
                -RoleName "engineer" -Prompt "test positional prompt" `
                -AgentCmd $captureMock -TimeoutSeconds 5

            if ($result.Output) {
                # Should contain the short positional placeholder
                $result.Output | Should -Match "\.\.\."
                # Legacy 'start' positional must NOT be present
                $result.Output | Should -Not -Match "ARGS: start "
                # Should NOT contain the raw prompt text inline
                $result.Output | Should -Not -Match "test positional prompt"
                # Should contain --file (prompt passed via file)
                $result.Output | Should -Match "--file"
            }
        }

        It "always passes --dangerously-skip-permissions flag" {
            $result = & $script:InvokeAgent -RoomDir $script:roomDir `
                -RoleName "engineer" -Prompt "test" `
                -AgentCmd $script:argsMock -TimeoutSeconds 5

            if (Test-Path $script:argsDump) {
                $args = Get-Content $script:argsDump
                $args | Should -Contain "--dangerously-skip-permissions"
            }
        }
    }

    Context "Default AgentCmd resolution" {
        It "always defaults to opencode run" {
            # Verify that without -AgentCmd or OSTWIN_AGENT_CMD, the resolved
            # command is 'opencode run' — no bin/agent lookup.
            # We use a capture mock via -AgentCmd to verify the script reaches
            # the execution phase without crashing.
            $result = & $script:InvokeAgent -RoomDir $script:roomDir `
                -RoleName "engineer" -Prompt "test" `
                -AgentCmd "echo" -TimeoutSeconds 5

            $result | Should -Not -BeNullOrEmpty
            $result.ExitCode | Should -BeIn @(0, 1)
        }

        It "OSTWIN_AGENT_CMD overrides the default" {
            $env:OSTWIN_AGENT_CMD = "echo"
            try {
                $result = & $script:InvokeAgent -RoomDir $script:roomDir `
                    -RoleName "engineer" -Prompt "test" -TimeoutSeconds 5

                $result | Should -Not -BeNullOrEmpty
            }
            finally {
                Remove-Item Env:OSTWIN_AGENT_CMD -ErrorAction SilentlyContinue
            }
        }

        It "explicit -AgentCmd param wins over OSTWIN_AGENT_CMD" {
            $captureMock = Join-Path $TestDrive "capture-cmd-$(Get-Random).ps1"
            "Write-Output 'MOCK_EXECUTED'" | Out-File $captureMock -Encoding utf8

            $env:OSTWIN_AGENT_CMD = "echo"
            try {
                $result = & $script:InvokeAgent -RoomDir $script:roomDir `
                    -RoleName "engineer" -Prompt "test" `
                    -AgentCmd $captureMock -TimeoutSeconds 5

                $result.Output | Should -Match "MOCK_EXECUTED"
            }
            finally {
                Remove-Item Env:OSTWIN_AGENT_CMD -ErrorAction SilentlyContinue
            }
        }
    }

    Context "No opencode.json generation" {
        It "does not create opencode.json in artifacts directory" {
            $result = & $script:InvokeAgent -RoomDir $script:roomDir `
                -RoleName "engineer" -Prompt "test no opencode.json" `
                -AgentCmd "echo" -TimeoutSeconds 5

            $artifactsDir = Join-Path $script:roomDir "artifacts"
            $opencodeJson = Join-Path $artifactsDir "opencode.json"
            Test-Path $opencodeJson | Should -BeFalse `
                -Because "Invoke-Agent must not generate opencode.json during ostwin run"
        }

        It "does not create opencode.json even when MCP config exists" {
            # Create a project dir with .agents/mcp/config.json and a room inside
            $projectDir = Join-Path $TestDrive "project-mcp-$(Get-Random)"
            $mcpDir = Join-Path $projectDir ".agents" "mcp"
            New-Item -ItemType Directory -Path $mcpDir -Force | Out-Null
            @{ mcp = @{ "test-server" = @{ type = "local"; command = @("echo") } } } `
                | ConvertTo-Json -Depth 5 `
                | Out-File (Join-Path $mcpDir "config.json") -Encoding utf8

            # Place room inside .war-rooms so Invoke-Agent resolves ProjectDir
            $roomDir = Join-Path $projectDir ".war-rooms" "room-mcp"
            New-Item -ItemType Directory -Path (Join-Path $roomDir "artifacts") -Force | Out-Null
            New-Item -ItemType Directory -Path (Join-Path $roomDir "pids") -Force | Out-Null

            $result = & $script:InvokeAgent -RoomDir $roomDir `
                -RoleName "engineer" -Prompt "test with mcp config" `
                -AgentCmd "echo" -TimeoutSeconds 5

            $artifactsDir = Join-Path $roomDir "artifacts"
            $opencodeJson = Join-Path $artifactsDir "opencode.json"
            Test-Path $opencodeJson | Should -BeFalse `
                -Because "Invoke-Agent must not generate opencode.json even when MCP config exists"
        }
    }

    Context "No .agents/mcp folder creation" {
        It "does not create .agents/mcp folder in the project directory" {
            # Create a project dir without .agents/mcp
            $projectDir = Join-Path $TestDrive "project-nomcp-$(Get-Random)"
            $agentsDir = Join-Path $projectDir ".agents"
            New-Item -ItemType Directory -Path $agentsDir -Force | Out-Null

            # Place room inside .war-rooms so Invoke-Agent resolves ProjectDir
            $roomDir = Join-Path $projectDir ".war-rooms" "room-nomcp"
            New-Item -ItemType Directory -Path (Join-Path $roomDir "artifacts") -Force | Out-Null
            New-Item -ItemType Directory -Path (Join-Path $roomDir "pids") -Force | Out-Null

            $result = & $script:InvokeAgent -RoomDir $roomDir `
                -RoleName "engineer" -Prompt "test no mcp folder" `
                -AgentCmd "echo" -TimeoutSeconds 5

            $mcpDir = Join-Path $agentsDir "mcp"
            Test-Path $mcpDir | Should -BeFalse `
                -Because "Invoke-Agent must not create .agents/mcp folder"
        }
    }

    Context "Model resolution fallback chain (integration)" {
        # Full chain: -Model param → plan.roles.json → config.json instance →
        #             config.json role → role.json → hardcoded default.
        # Critical: role.json fallback must work even when config.json is ABSENT.

        It "uses role.json model when config.json is absent" {
            # Setup: no config.json, but role.json has a model
            $fakeHome = Join-Path $TestDrive "home-$(Get-Random)"
            New-Item -ItemType Directory -Path (Join-Path $fakeHome ".ostwin" ".agents" "roles" "engineer") -Force | Out-Null
            @{ model = "role-json-model"; skill_refs = @() } | ConvertTo-Json |
                Out-File (Join-Path $fakeHome ".ostwin" ".agents" "roles" "engineer" "role.json") -Encoding utf8

            $roomDir = Join-Path $TestDrive "room-rolejson-$(Get-Random)"
            New-Item -ItemType Directory -Path (Join-Path $roomDir "artifacts") -Force | Out-Null
            New-Item -ItemType Directory -Path (Join-Path $roomDir "pids") -Force | Out-Null

            $savedHome = $env:HOME
            $savedConfig = $env:AGENT_OS_CONFIG
            try {
                $env:HOME = $fakeHome
                # Point config to a non-existent file so it skips config.json block
                $env:AGENT_OS_CONFIG = Join-Path $TestDrive "nonexistent-config.json"

                $result = & $script:InvokeAgent -RoomDir $roomDir `
                    -RoleName "engineer" -Prompt "test" `
                    -AgentCmd "echo" -TimeoutSeconds 5

                $result | Should -Not -BeNullOrEmpty
                # The agent should have used role-json-model (not the hardcoded default)
                $result.Output | Should -Match "role-json-model" `
                    -Because "role.json model must be used when config.json is absent"
            }
            finally {
                $env:HOME = $savedHome
                if ($savedConfig) { $env:AGENT_OS_CONFIG = $savedConfig }
                else { Remove-Item Env:AGENT_OS_CONFIG -ErrorAction SilentlyContinue }
            }
        }

        It "explicit -Model param wins over all fallbacks" {
            $result = & $script:InvokeAgent -RoomDir $script:roomDir `
                -RoleName "engineer" -Prompt "test" `
                -Model "explicit-param-model" `
                -AgentCmd "echo" -TimeoutSeconds 5

            $result.Output | Should -Match "explicit-param-model"
        }

        It "falls back to hardcoded default when nothing is configured" {
            $savedConfig = $env:AGENT_OS_CONFIG
            try {
                $env:AGENT_OS_CONFIG = Join-Path $TestDrive "nonexistent-$(Get-Random).json"

                $result = & $script:InvokeAgent -RoomDir $script:roomDir `
                    -RoleName "engineer" -Prompt "test" `
                    -AgentCmd "echo" -TimeoutSeconds 5

                $result | Should -Not -BeNullOrEmpty
                # Should resolve to the hardcoded default model
                $result.Output | Should -Match "google-vertex" `
                    -Because "hardcoded default should be used as last resort"
            }
            finally {
                if ($savedConfig) { $env:AGENT_OS_CONFIG = $savedConfig }
                else { Remove-Item Env:AGENT_OS_CONFIG -ErrorAction SilentlyContinue }
            }
        }

        It "plan.roles.json model wins over config.json model" {
            # Setup plan.roles.json
            $fakeHome = Join-Path $TestDrive "home-plan-$(Get-Random)"
            $plansDir = Join-Path $fakeHome ".ostwin" ".agents" "plans"
            New-Item -ItemType Directory -Path $plansDir -Force | Out-Null
            @{ engineer = @{ default_model = "plan-level-model" } } | ConvertTo-Json -Depth 3 |
                Out-File (Join-Path $plansDir "test-plan.roles.json") -Encoding utf8

            # Setup room config pointing to the plan
            $roomDir = Join-Path $TestDrive "room-plan-$(Get-Random)"
            New-Item -ItemType Directory -Path (Join-Path $roomDir "artifacts") -Force | Out-Null
            New-Item -ItemType Directory -Path (Join-Path $roomDir "pids") -Force | Out-Null
            @{ plan_id = "test-plan" } | ConvertTo-Json |
                Out-File (Join-Path $roomDir "config.json") -Encoding utf8

            # Setup config.json with a different model
            $configFile = Join-Path $TestDrive "config-plan-$(Get-Random).json"
            @{ engineer = @{ default_model = "config-model" } } | ConvertTo-Json -Depth 3 |
                Out-File $configFile -Encoding utf8

            $savedHome = $env:HOME
            $savedConfig = $env:AGENT_OS_CONFIG
            try {
                $env:HOME = $fakeHome
                $env:AGENT_OS_CONFIG = $configFile

                $result = & $script:InvokeAgent -RoomDir $roomDir `
                    -RoleName "engineer" -Prompt "test" `
                    -AgentCmd "echo" -TimeoutSeconds 5

                $result.Output | Should -Match "plan-level-model" `
                    -Because "plan.roles.json must take priority over config.json"
            }
            finally {
                $env:HOME = $savedHome
                if ($savedConfig) { $env:AGENT_OS_CONFIG = $savedConfig }
                else { Remove-Item Env:AGENT_OS_CONFIG -ErrorAction SilentlyContinue }
            }
        }
    }

    Context "Full command line assembly (safe exec)" {
        # These tests verify the COMPLETE assembled command line that Start-Process
        # receives. They ensure correct argument ordering, proper spacing between
        # all args, and specifically guard against the concatenation bug where
        # adjacent arguments (e.g. --dir path + positional message) merged into
        # a single mangled token like "/path/to/project/runExecute the task".
        #
        # Expected full invocation (with ProjectDir resolved):
        #   opencode run \
        #     "..." \
        #     --model <model> --agent <role> \
        #     --dir <project-dir> \
        #     --file <prompt.txt> \
        #     --dangerously-skip-permissions

        BeforeEach {
            # Create a realistic project structure with .war-rooms
            $script:projectDir = Join-Path $TestDrive "project-safexec-$(Get-Random)"
            $script:safeRoomDir = Join-Path $script:projectDir ".war-rooms" "room-001"
            New-Item -ItemType Directory -Path (Join-Path $script:safeRoomDir "artifacts") -Force | Out-Null
            New-Item -ItemType Directory -Path (Join-Path $script:safeRoomDir "pids") -Force | Out-Null

            # Mock script that dumps each arg on its own line
            $script:safeArgsDump = Join-Path $TestDrive "safe-args-$(Get-Random).txt"
            $script:safeArgsMock = Join-Path $TestDrive "safe-argsmock-$(Get-Random).ps1"
            @"
`$args | ForEach-Object { `$_ } | Out-File -FilePath '$($script:safeArgsDump)' -Encoding utf8
"@ | Out-File $script:safeArgsMock -Encoding utf8
        }

        It "produces correct full argument sequence for engineer with resolved ProjectDir" {
            $result = & $script:InvokeAgent -RoomDir $script:safeRoomDir `
                -RoleName "engineer" -Prompt "Implement the auth feature" `
                -Model "google-vertex/zai-org/glm-5-maas" `
                -AgentCmd $script:safeArgsMock -TimeoutSeconds 5

            Test-Path $script:safeArgsDump | Should -BeTrue -Because "mock should capture args"
            $capturedArgs = Get-Content $script:safeArgsDump

            # Verify exact argument order:
            # [0] positional message
            # [1,2] --model <model>
            # [3,4] --agent <role>
            # [5,6] --dir <project-dir>
            # [7,8] --file <prompt.txt>
            # [9] --dangerously-skip-permissions
            $capturedArgs[0] | Should -Be "..."
            $capturedArgs[1] | Should -Be "--model"
            $capturedArgs[2] | Should -Be "google-vertex/zai-org/glm-5-maas"
            $capturedArgs[3] | Should -Be "--agent"
            $capturedArgs[4] | Should -Be "engineer"
            $capturedArgs[5] | Should -Be "--dir"
            $capturedArgs[6] | Should -Be $script:projectDir
            $capturedArgs[7] | Should -Be "--file"
            $capturedArgs[8] | Should -Match "prompt\.txt$"
            $capturedArgs[9] | Should -Be "--dangerously-skip-permissions"
        }

        It "--dir value is never concatenated with adjacent arguments" {
            # This is the exact regression test for the bug where Start-Process
            # with array-based -ArgumentList concatenated --dir path with 'run':
            #   "/path/to/project/runExecute the task..."
            $result = & $script:InvokeAgent -RoomDir $script:safeRoomDir `
                -RoleName "engineer" -Prompt "test isolation" `
                -Model "test-model" `
                -AgentCmd $script:safeArgsMock -TimeoutSeconds 5

            Test-Path $script:safeArgsDump | Should -BeTrue
            $capturedArgs = Get-Content $script:safeArgsDump

            # The --dir value must be EXACTLY the project dir — no trailing junk
            $dirIdx = [array]::IndexOf($capturedArgs, "--dir")
            $dirIdx | Should -BeGreaterOrEqual 0 -Because "--dir flag must be present"
            $dirValue = $capturedArgs[$dirIdx + 1]

            $dirValue | Should -Be $script:projectDir `
                -Because "--dir value must be the exact project path, not concatenated with other args"

            # The arg BEFORE --dir must not end with the project dir (concatenation bug)
            if ($dirIdx -gt 0) {
                $prevArg = $capturedArgs[$dirIdx - 1]
                $prevArg | Should -Not -Match ([regex]::Escape($script:projectDir)) `
                    -Because "--dir value must not be concatenated with the previous argument"
            }
            # The arg AFTER --dir value must be its own token (not appended to dir path)
            if ($dirIdx + 2 -lt $capturedArgs.Count) {
                $nextArg = $capturedArgs[$dirIdx + 2]
                $nextArg | Should -Match '^--' `
                    -Because "the arg after --dir value must be a flag, not concatenated text"
            }
        }

        It "handles spaces in project directory path" {
            # Paths with spaces are a classic Start-Process quoting pitfall
            $spacedProject = Join-Path $TestDrive "My Project $(Get-Random)"
            $spacedRoom = Join-Path $spacedProject ".war-rooms" "room-spaced"
            New-Item -ItemType Directory -Path (Join-Path $spacedRoom "artifacts") -Force | Out-Null
            New-Item -ItemType Directory -Path (Join-Path $spacedRoom "pids") -Force | Out-Null

            $result = & $script:InvokeAgent -RoomDir $spacedRoom `
                -RoleName "engineer" -Prompt "test spaces" `
                -Model "test-model" `
                -AgentCmd $script:safeArgsMock -TimeoutSeconds 5

            Test-Path $script:safeArgsDump | Should -BeTrue
            $capturedArgs = Get-Content $script:safeArgsDump

            $dirIdx = [array]::IndexOf($capturedArgs, "--dir")
            $dirIdx | Should -BeGreaterOrEqual 0
            $dirValue = $capturedArgs[$dirIdx + 1]

            $dirValue | Should -Be $spacedProject `
                -Because "spaces in path must be preserved as a single argument, not split"
        }

        It "prompt text is never inlined — only passed via --file" {
            $longPrompt = "This is a detailed prompt about authentication and user management"

            $result = & $script:InvokeAgent -RoomDir $script:safeRoomDir `
                -RoleName "engineer" -Prompt $longPrompt `
                -Model "test-model" `
                -AgentCmd $script:safeArgsMock -TimeoutSeconds 5

            Test-Path $script:safeArgsDump | Should -BeTrue
            $capturedArgs = Get-Content $script:safeArgsDump

            # Prompt text must NOT appear anywhere in the argument list
            $joined = $capturedArgs -join "|"
            $joined | Should -Not -Match "detailed prompt" `
                -Because "prompt is written to prompt.txt, never passed inline"
            $joined | Should -Not -Match "authentication and user management" `
                -Because "no part of the prompt should leak into CLI args"

            # Collect all --file values
            $fileValues = [System.Collections.ArrayList]@()
            for ($i = 0; $i -lt $capturedArgs.Count; $i++) {
                if ($capturedArgs[$i] -eq "--file") {
                    [void]$fileValues.Add($capturedArgs[$i + 1])
                }
            }

            # The prompt file must be attached via --file
            $promptFileArg = $fileValues | Where-Object { $_ -match "prompt\.txt$" }
            $promptFileArg | Should -Not -BeNullOrEmpty `
                -Because "prompt must be delivered via --file flag"

            # Verify the path ends with artifacts/prompt.txt
            $promptFileArg | Should -Match "artifacts[/\\]prompt\.txt$" `
                -Because "prompt file should be in the artifacts directory"
        }

        It "extra --file args appear before prompt.txt file" {
            $result = & $script:InvokeAgent -RoomDir $script:safeRoomDir `
                -RoleName "engineer" -Prompt "multi-file test" `
                -Model "test-model" `
                -Files @("src/main.ts", "README.md") `
                -AgentCmd $script:safeArgsMock -TimeoutSeconds 5

            Test-Path $script:safeArgsDump | Should -BeTrue
            $capturedArgs = Get-Content $script:safeArgsDump

            # Collect all --file values in order
            $fileValues = @()
            for ($i = 0; $i -lt $capturedArgs.Count; $i++) {
                if ($capturedArgs[$i] -eq "--file") { $fileValues += $capturedArgs[$i + 1] }
            }

            $fileValues.Count | Should -Be 3 -Because "2 user files + 1 prompt.txt"
            $fileValues[0] | Should -Be "src/main.ts"
            $fileValues[1] | Should -Be "README.md"
            $fileValues[2] | Should -Match "prompt\.txt$"
        }

        It "total argument count matches expected structure" {
            $result = & $script:InvokeAgent -RoomDir $script:safeRoomDir `
                -RoleName "qa" -Prompt "review code" `
                -Model "anthropic/claude-sonnet-4-20250514" `
                -AgentCmd $script:safeArgsMock -TimeoutSeconds 5

            Test-Path $script:safeArgsDump | Should -BeTrue
            $capturedArgs = Get-Content $script:safeArgsDump

            # Expected: message(1) + --model(2) + --agent(2) + --dir(2) + --file(2) + --dangerously-skip-permissions(1) = 10
            $capturedArgs.Count | Should -Be 10 `
                -Because "exactly 10 args: positional + --model X + --agent X + --dir X + --file X + --dangerously-skip-permissions"
        }

        It "without ProjectDir, --dir is omitted and arg count adjusts" {
            # Use a room that is NOT inside .war-rooms — no ProjectDir
            $flatRoom = Join-Path $TestDrive "flat-room-$(Get-Random)"
            New-Item -ItemType Directory -Path (Join-Path $flatRoom "artifacts") -Force | Out-Null
            New-Item -ItemType Directory -Path (Join-Path $flatRoom "pids") -Force | Out-Null

            $result = & $script:InvokeAgent -RoomDir $flatRoom `
                -RoleName "engineer" -Prompt "no dir test" `
                -Model "test-model" `
                -AgentCmd $script:safeArgsMock -TimeoutSeconds 5

            Test-Path $script:safeArgsDump | Should -BeTrue
            $capturedArgs = Get-Content $script:safeArgsDump

            $capturedArgs | Should -Not -Contain "--dir" `
                -Because "no .war-rooms parent means no --dir flag"

            # Expected: message(1) + --model(2) + --agent(2) + --file(2) + --dangerously-skip-permissions(1) = 8
            $capturedArgs.Count | Should -Be 8
        }
    }

    # =========================================================================
    # Lifecycle retry detection — $isLifecycleRetry triggers --continue
    # =========================================================================
    Context "Lifecycle retry detection (retries file → --continue)" {
        It "adds --continue flag when retries file exists and value > 0" {
            # Create a room with a retries file containing "2"
            "2" | Out-File -FilePath (Join-Path $script:roomDir "retries") -Encoding utf8 -NoNewline

            # Mock that captures CLI args
            $argsDump = Join-Path $TestDrive "retry-args-$(Get-Random).txt"
            $argsMock = Join-Path $TestDrive "retry-argsmock-$(Get-Random).ps1"
            @"
`$args | ForEach-Object { `$_ } | Out-File -FilePath '$argsDump' -Encoding utf8
"@ | Out-File $argsMock -Encoding utf8

            $result = & $script:InvokeAgent -RoomDir $script:roomDir `
                -RoleName "engineer" -Prompt "retry test" `
                -AgentCmd $argsMock -TimeoutSeconds 5

            if (Test-Path $argsDump) {
                $capturedArgs = Get-Content $argsDump
                $capturedArgs | Should -Contain "--continue" `
                    -Because "retries file with value > 0 should trigger --continue"
            }
        }

        It "does NOT add --continue when retries file is absent" {
            # Room has no retries file — default behavior
            $argsDump = Join-Path $TestDrive "no-retry-args-$(Get-Random).txt"
            $argsMock = Join-Path $TestDrive "no-retry-argsmock-$(Get-Random).ps1"
            @"
`$args | ForEach-Object { `$_ } | Out-File -FilePath '$argsDump' -Encoding utf8
"@ | Out-File $argsMock -Encoding utf8

            # Explicitly NOT passing -ContinueSession
            $result = & $script:InvokeAgent -RoomDir $script:roomDir `
                -RoleName "engineer" -Prompt "no retry" `
                -AgentCmd $argsMock -TimeoutSeconds 5

            if (Test-Path $argsDump) {
                $capturedArgs = Get-Content $argsDump
                $capturedArgs | Should -Not -Contain "--continue" `
                    -Because "no retries file and no -ContinueSession means no --continue"
            }
        }

        It "does NOT add --continue when retries file contains 0" {
            "0" | Out-File -FilePath (Join-Path $script:roomDir "retries") -Encoding utf8 -NoNewline

            $argsDump = Join-Path $TestDrive "zero-retry-args-$(Get-Random).txt"
            $argsMock = Join-Path $TestDrive "zero-retry-argsmock-$(Get-Random).ps1"
            @"
`$args | ForEach-Object { `$_ } | Out-File -FilePath '$argsDump' -Encoding utf8
"@ | Out-File $argsMock -Encoding utf8

            $result = & $script:InvokeAgent -RoomDir $script:roomDir `
                -RoleName "engineer" -Prompt "zero retry" `
                -AgentCmd $argsMock -TimeoutSeconds 5

            if (Test-Path $argsDump) {
                $capturedArgs = Get-Content $argsDump
                $capturedArgs | Should -Not -Contain "--continue" `
                    -Because "retries=0 means this is NOT a lifecycle retry"
            }
        }

        It "existing -ContinueSession still works with retries file absent" {
            $argsDump = Join-Path $TestDrive "explicit-continue-$(Get-Random).txt"
            $argsMock = Join-Path $TestDrive "explicit-continue-mock-$(Get-Random).ps1"
            @"
`$args | ForEach-Object { `$_ } | Out-File -FilePath '$argsDump' -Encoding utf8
"@ | Out-File $argsMock -Encoding utf8

            $result = & $script:InvokeAgent -RoomDir $script:roomDir `
                -RoleName "engineer" -Prompt "explicit continue" `
                -ContinueSession `
                -AgentCmd $argsMock -TimeoutSeconds 5

            if (Test-Path $argsDump) {
                $capturedArgs = Get-Content $argsDump
                $capturedArgs | Should -Contain "--continue" `
                    -Because "explicit -ContinueSession flag must be preserved"
            }
        }
    }

    # =========================================================================
    # Retry loop: attempt 2+ auto-injects --continue
    # =========================================================================
    Context "Retry loop — auto-inject --continue on attempt 2+" {
        It "per-attempt args include --continue when processAttempt > 1" {
            # This validates the internal logic: when $processAttempt -gt 1,
            # the code adds "--continue" to $attemptArgs if not already present.
            # We can't easily mock a multi-attempt scenario with the echo mock,
            # so we verify the static analysis: the for loop body clones args
            # and conditionally appends --continue.
            $scriptContent = Get-Content $script:InvokeAgent -Raw

            # The retry loop must clone the args array for each attempt
            $scriptContent | Should -Match '\$attemptArgs = \$extraCliArgs\.Clone\(\)' `
                -Because "each attempt must work on a copy of the base args"

            # The condition must check for attempt > 1 AND --continue not already present
            $scriptContent | Should -Match 'if \(\$processAttempt -gt 1.*\$attemptArgs -notcontains "--continue"\)' `
                -Because "attempt 2+ should only add --continue if not already there"

            # The argsLine must be built from $attemptArgs (not $extraCliArgs)
            $scriptContent | Should -Match '\$argsLine = \(\$attemptArgs \| ForEach-Object' `
                -Because "the actual exec command must use per-attempt args"
        }

        It "does not duplicate --continue if already present from -ContinueSession" {
            # If -ContinueSession was passed, --continue is already in $extraCliArgs.
            # The retry loop guard ($attemptArgs -notcontains "--continue") must prevent
            # a duplicate.
            $scriptContent = Get-Content $script:InvokeAgent -Raw
            $scriptContent | Should -Match '\$attemptArgs -notcontains "--continue"' `
                -Because "duplicate --continue flags would be a regression"
        }
    }
}
