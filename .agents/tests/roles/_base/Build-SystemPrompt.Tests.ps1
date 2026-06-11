# Agent OS — Build-SystemPrompt Pester Tests

BeforeAll {
    $script:BuildPrompt = Join-Path (Resolve-Path "$PSScriptRoot/../../../roles/_base").Path "Build-SystemPrompt.ps1"
    $script:agentsDir = (Resolve-Path (Join-Path (Resolve-Path "$PSScriptRoot/../../../roles/_base").Path ".." "..")).Path
    $script:NewWarRoom = Join-Path $script:agentsDir "war-rooms" "New-WarRoom.ps1"
    . (Join-Path $script:agentsDir "tests" "TestChannelHelpers.ps1")
    $script:PostMessage = New-TestChannelWriter
}

Describe "Build-SystemPrompt" {
    Context "Role-based prompt" {
        It "builds prompt from JSON role definition" {
            $rolePath = Join-Path $TestDrive "role-bp-$(Get-Random)"
            New-Item -ItemType Directory -Path $rolePath -Force | Out-Null

            @{
                name         = "test-role"
                description  = "A test role for validation"
                capabilities = @("code-gen", "testing")
                prompt_file  = "ROLE.md"
                quality_gates = @("lint", "tests")
                skills       = @("python", "go")
            } | ConvertTo-Json -Depth 3 | Out-File (Join-Path $rolePath "role.json") -Encoding utf8

            "# Test Role`nYou are a test role agent." |
                Out-File (Join-Path $rolePath "ROLE.md") -Encoding utf8

            $prompt = & $script:BuildPrompt -RolePath $rolePath
            $prompt | Should -Match "# test-role"
            $prompt | Should -Match "A test role for validation"
            $prompt | Should -Not -Match "test role agent"
        }

        It "includes capabilities section" {
            $rolePath = Join-Path $TestDrive "role-cap-$(Get-Random)"
            New-Item -ItemType Directory -Path $rolePath -Force | Out-Null

            @{
                name         = "cap-role"
                capabilities = @("code-gen", "file-editing", "shell-execution")
            } | ConvertTo-Json -Depth 3 | Out-File (Join-Path $rolePath "role.json") -Encoding utf8

            $prompt = & $script:BuildPrompt -RolePath $rolePath
            $prompt | Should -Match "Capabilities"
            $prompt | Should -Match "code-gen"
            $prompt | Should -Match "shell-execution"
        }

        It "includes quality gates section" {
            $rolePath = Join-Path $TestDrive "role-qg-$(Get-Random)"
            New-Item -ItemType Directory -Path $rolePath -Force | Out-Null

            @{
                name          = "qg-role"
                quality_gates = @("unit-tests", "lint-clean", "security-scan")
            } | ConvertTo-Json -Depth 3 | Out-File (Join-Path $rolePath "role.json") -Encoding utf8

            $prompt = & $script:BuildPrompt -RolePath $rolePath
            $prompt | Should -Match "Quality Gates"
            $prompt | Should -Match "unit-tests"
            $prompt | Should -Match "security-scan"
        }

        It "does NOT concatenate skills into the prompt (skills via AGENT_OS_SKILLS_DIR)" {
            $rolePath = Join-Path $TestDrive "role-sk-$(Get-Random)"
            New-Item -ItemType Directory -Path $rolePath -Force | Out-Null

            # Create global skill — should NOT appear in the prompt
            $skillsDir = Join-Path $TestDrive "skills"
            New-Item -ItemType Directory -Path (Join-Path $skillsDir "global" "test-skill") -Force | Out-Null
            "Test Skill content" | Out-File (Join-Path $skillsDir "global" "test-skill" "SKILL.md")

            @{
                name   = "sk-role"
            } | ConvertTo-Json -Depth 3 | Out-File (Join-Path $rolePath "role.json") -Encoding utf8

            $prompt = & $script:BuildPrompt -RolePath $rolePath
            # Skills should NOT be in the prompt — they are loaded via AGENT_OS_SKILLS_DIR by Invoke-Agent.ps1
            $prompt | Should -Not -Match "## Skills"
            $prompt | Should -Not -Match "## Available Skills"
            $prompt | Should -Not -Match "### Skill:"
            $prompt | Should -Not -Match "Test Skill content"
        }
    }

    Context "War-room context injection" {
        BeforeEach {
            $script:warRoomsDir = Join-Path $TestDrive "wr-bp-$(Get-Random)"
            New-Item -ItemType Directory -Path $script:warRoomsDir -Force | Out-Null

            & $script:NewWarRoom -RoomId "room-bp-001" -TaskRef "TASK-BP" `
                -TaskDescription "Build the auth module" `
                -WarRoomsDir $script:warRoomsDir `
                -DefinitionOfDone @("JWT working", "Tests pass") `
                -AcceptanceCriteria @("POST /login returns 200")

            $script:roomDir = Join-Path $script:warRoomsDir "room-bp-001"

            $script:rolePath = Join-Path $TestDrive "role-ctx-$(Get-Random)"
            New-Item -ItemType Directory -Path $script:rolePath -Force | Out-Null
            @{ name = "ctx-role" } | ConvertTo-Json | Out-File (Join-Path $script:rolePath "role.json")
        }

        It "includes task brief from war-room" {
            $prompt = & $script:BuildPrompt -RolePath $script:rolePath -RoomDir $script:roomDir
            $prompt | Should -Match "Build the auth module"
        }

        It "does NOT include a separate Goals section from config.json (brief.md has its own)" {
            $prompt = & $script:BuildPrompt -RolePath $script:rolePath -RoomDir $script:roomDir
            # Build-SystemPrompt no longer reads config.json to build a separate "## Goals" section.
            # Goals info in brief.md is still included (via Task Assignment), which is expected.
            $prompt | Should -Not -Match "## Goals"
            $prompt | Should -Not -Match "Quality Requirements"
        }

        It "does NOT include QA feedback (callers handle fix-cycle context)" {
            & $script:PostMessage -RoomDir $script:roomDir -From "qa" -To "manager" `
                -Type "fail" -Ref "TASK-BP" -Body "Missing input validation"

            $prompt = & $script:BuildPrompt -RolePath $script:rolePath -RoomDir $script:roomDir
            $prompt | Should -Not -Match "Missing input validation"
            $prompt | Should -Not -Match "Previous QA Feedback"
            $prompt | Should -Not -Match "Fix Instructions"
        }

        It "does not include TASKS.md directly" {
            "- [x] TASK-001 — Design`n- [ ] TASK-002 — Implement" |
                Out-File (Join-Path $script:roomDir "TASKS.md") -Encoding utf8

            $prompt = & $script:BuildPrompt -RolePath $script:rolePath -RoomDir $script:roomDir
            $prompt | Should -Not -Match "Sub-Tasks"
            $prompt | Should -Not -Match "TASK-001 — Design"
        }
    }

    Context "Override parameters" {
        BeforeEach {
            $script:rolePath = Join-Path $TestDrive "role-ov-$(Get-Random)"
            New-Item -ItemType Directory -Path $script:rolePath -Force | Out-Null
            @{ name = "ov-role" } | ConvertTo-Json | Out-File (Join-Path $script:rolePath "role.json")
        }

        It "includes task reference" {
            $prompt = & $script:BuildPrompt -RolePath $script:rolePath -TaskRef "EPIC-042"
            $prompt | Should -Match "EPIC-042"
        }

        It "includes task body" {
            $prompt = & $script:BuildPrompt -RolePath $script:rolePath `
                -TaskBody "Implement the dashboard widget"
            $prompt | Should -Match "Implement the dashboard widget"
        }

        It "includes extra context" {
            $prompt = & $script:BuildPrompt -RolePath $script:rolePath `
                -ExtraContext "The project uses React 19 with TypeScript."
            $prompt | Should -Match "React 19"
            $prompt | Should -Match "Additional Context"
        }

        It "appends plan roles system_prompt_override at the end when present" {
            $ostwinHome = Join-Path $TestDrive "ostwin-home-$(Get-Random)"
            $plansDir = Join-Path $ostwinHome ".agents" "plans"
            New-Item -ItemType Directory -Path $plansDir -Force | Out-Null
            $roomDir = Join-Path $TestDrive "room-override-$(Get-Random)"
            New-Item -ItemType Directory -Path $roomDir -Force | Out-Null
            @{ plan_id = "plan-override" } | ConvertTo-Json | Out-File (Join-Path $roomDir "config.json") -Encoding utf8
            @{
                "ov-role" = @{
                    system_prompt_override = "Final override instruction."
                }
            } | ConvertTo-Json -Depth 4 | Out-File (Join-Path $plansDir "plan-override.roles.json") -Encoding utf8

            $oldOstwinHome = $env:OSTWIN_HOME
            try {
                $env:OSTWIN_HOME = $ostwinHome
                $prompt = & $script:BuildPrompt -RolePath $script:rolePath -RoomDir $roomDir
            }
            finally {
                $env:OSTWIN_HOME = $oldOstwinHome
            }

            $prompt | Should -Match "System Prompt Override"
            $prompt.TrimEnd().EndsWith("Final override instruction.") | Should -BeTrue
        }

        It "does not add override section when plan roles file is absent" {
            $ostwinHome = Join-Path $TestDrive "ostwin-home-empty-$(Get-Random)"
            $roomDir = Join-Path $TestDrive "room-no-override-$(Get-Random)"
            New-Item -ItemType Directory -Path $roomDir -Force | Out-Null
            @{ plan_id = "plan-without-roles-file" } | ConvertTo-Json | Out-File (Join-Path $roomDir "config.json") -Encoding utf8

            $oldOstwinHome = $env:OSTWIN_HOME
            try {
                $env:OSTWIN_HOME = $ostwinHome
                $prompt = & $script:BuildPrompt -RolePath $script:rolePath -RoomDir $roomDir
            }
            finally {
                $env:OSTWIN_HOME = $oldOstwinHome
            }

            $prompt | Should -Not -Match "System Prompt Override"
        }
    }

    Context "Built-in roles" {
        It "builds prompt for engineer role" {
            $engPath = Join-Path $script:agentsDir "roles" "engineer"
            if (Test-Path $engPath) {
                $prompt = & $script:BuildPrompt -RolePath $engPath
                $prompt.Length | Should -BeGreaterThan 0
            }
        }

        It "builds prompt for qa role" {
            $qaPath = Join-Path $script:agentsDir "roles" "qa"
            if (Test-Path $qaPath) {
                $prompt = & $script:BuildPrompt -RolePath $qaPath
                $prompt.Length | Should -BeGreaterThan 0
            }
        }

        It "builds prompt for architect role" {
            $archPath = Join-Path $script:agentsDir "roles" "architect"
            if (Test-Path $archPath) {
                $prompt = & $script:BuildPrompt -RolePath $archPath
                $prompt | Should -Match "architect"
            }
        }
    }

    Context "Error handling" {
        It "fails when no role specified" {
            $ErrorActionPreference = 'Continue'
            $output = & $script:BuildPrompt 2>&1
            $output | Should -Match "must be specified"
        }
    }
}
