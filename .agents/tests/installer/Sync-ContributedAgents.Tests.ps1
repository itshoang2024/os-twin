# Agent OS — Sync-ContributedAgents Pester Tests
# Verifies that Sync-ContributedAgents.ps1 correctly mirrors role definitions
# from the project into the OpenCode agents directory.

BeforeAll {
    $script:SyncScript = Join-Path (Resolve-Path "$PSScriptRoot/../../plan").Path "Sync-ContributedAgents.ps1"
}

Describe "Sync-ContributedAgents — basic sync" {
    BeforeEach {
        # Build a minimal fake project tree inside TestDrive
        $script:ProjectDir = Join-Path $TestDrive "project-$(Get-Random)"
        $script:AgentsOut  = Join-Path $TestDrive "oc-agents-$(Get-Random)"

        New-Item -ItemType Directory -Path $script:ProjectDir -Force | Out-Null
        New-Item -ItemType Directory -Path $script:AgentsOut  -Force | Out-Null
    }

    Context "Built-in roles (.agents/roles/)" {
        It "copies ROLE.md from a valid built-in role" {
            # Arrange: create .agents/roles/engineer with role.json + ROLE.md
            $roleDir = Join-Path $script:ProjectDir ".agents" "roles" "engineer"
            New-Item -ItemType Directory -Path $roleDir -Force | Out-Null
            '{"name":"engineer"}' | Set-Content (Join-Path $roleDir "role.json")
            "# Engineer Role" | Set-Content (Join-Path $roleDir "ROLE.md")

            # Act
            & $script:SyncScript -ProjectDir $script:ProjectDir -AgentsDir $script:AgentsOut

            # Assert
            $dest = Join-Path $script:AgentsOut "engineer.md"
            Test-Path $dest | Should -BeTrue
            Get-Content $dest -Raw | Should -Match "Engineer Role"
        }

        It "skips a role directory that has no role.json" {
            $roleDir = Join-Path $script:ProjectDir ".agents" "roles" "orphan"
            New-Item -ItemType Directory -Path $roleDir -Force | Out-Null
            # No role.json — only ROLE.md
            "# Orphan" | Set-Content (Join-Path $roleDir "ROLE.md")

            & $script:SyncScript -ProjectDir $script:ProjectDir -AgentsDir $script:AgentsOut

            Test-Path (Join-Path $script:AgentsOut "orphan.md") | Should -BeFalse
        }

        It "skips _base directory" {
            $baseDir = Join-Path $script:ProjectDir ".agents" "roles" "_base"
            New-Item -ItemType Directory -Path $baseDir -Force | Out-Null
            '{"name":"_base"}' | Set-Content (Join-Path $baseDir "role.json")
            "# Base" | Set-Content (Join-Path $baseDir "ROLE.md")

            & $script:SyncScript -ProjectDir $script:ProjectDir -AgentsDir $script:AgentsOut

            Test-Path (Join-Path $script:AgentsOut "_base.md") | Should -BeFalse
        }
    }

    Context "Contributed roles (contributes/roles/)" {
        It "copies ROLE.md from a valid contributed role" {
            $roleDir = Join-Path $script:ProjectDir "contributes" "roles" "security-specialist"
            New-Item -ItemType Directory -Path $roleDir -Force | Out-Null
            '{"name":"security-specialist"}' | Set-Content (Join-Path $roleDir "role.json")
            "# Security Specialist" | Set-Content (Join-Path $roleDir "ROLE.md")

            & $script:SyncScript -ProjectDir $script:ProjectDir -AgentsDir $script:AgentsOut

            $dest = Join-Path $script:AgentsOut "security-specialist.md"
            Test-Path $dest | Should -BeTrue
            Get-Content $dest -Raw | Should -Match "Security Specialist"
        }

        It "does NOT auto-scaffold a generic definition — only copies what exists" {
            # Contributed role exists with role.json but NO ROLE.md
            $roleDir = Join-Path $script:ProjectDir "contributes" "roles" "data-analyst"
            New-Item -ItemType Directory -Path $roleDir -Force | Out-Null
            '{"name":"data-analyst"}' | Set-Content (Join-Path $roleDir "role.json")
            # No ROLE.md

            & $script:SyncScript -ProjectDir $script:ProjectDir -AgentsDir $script:AgentsOut

            # Should NOT create a file (no scaffold, no generic content)
            Test-Path (Join-Path $script:AgentsOut "data-analyst.md") | Should -BeFalse
        }
    }

    Context "Contributed role wins over built-in role of the same name" {
        It "contributed ROLE.md overwrites built-in ROLE.md in the output" {
            # Built-in engineer
            $builtinDir = Join-Path $script:ProjectDir ".agents" "roles" "engineer"
            New-Item -ItemType Directory -Path $builtinDir -Force | Out-Null
            '{"name":"engineer"}' | Set-Content (Join-Path $builtinDir "role.json")
            "# Generic Engineer" | Set-Content (Join-Path $builtinDir "ROLE.md")

            # Contributed engineer (overriding with a specialised definition)
            $contribDir = Join-Path $script:ProjectDir "contributes" "roles" "engineer"
            New-Item -ItemType Directory -Path $contribDir -Force | Out-Null
            '{"name":"engineer"}' | Set-Content (Join-Path $contribDir "role.json")
            "# Project-Specific Engineer Override" | Set-Content (Join-Path $contribDir "ROLE.md")

            & $script:SyncScript -ProjectDir $script:ProjectDir -AgentsDir $script:AgentsOut

            $content = Get-Content (Join-Path $script:AgentsOut "engineer.md") -Raw
            $content | Should -Match "Project-Specific Engineer Override"
            $content | Should -Not -Match "Generic Engineer"
        }
    }

    Context "Idempotency" {
        It "running sync twice produces identical output" {
            $roleDir = Join-Path $script:ProjectDir ".agents" "roles" "qa"
            New-Item -ItemType Directory -Path $roleDir -Force | Out-Null
            '{"name":"qa"}' | Set-Content (Join-Path $roleDir "role.json")
            "# QA Engineer" | Set-Content (Join-Path $roleDir "ROLE.md")

            # Run twice
            & $script:SyncScript -ProjectDir $script:ProjectDir -AgentsDir $script:AgentsOut
            & $script:SyncScript -ProjectDir $script:ProjectDir -AgentsDir $script:AgentsOut

            $dest = Join-Path $script:AgentsOut "qa.md"
            Test-Path $dest | Should -BeTrue
            Get-Content $dest -Raw | Should -Match "QA Engineer"
        }

        It "updating ROLE.md source and re-syncing reflects the change" {
            $roleDir = Join-Path $script:ProjectDir "contributes" "roles" "security-specialist"
            New-Item -ItemType Directory -Path $roleDir -Force | Out-Null
            '{"name":"security-specialist"}' | Set-Content (Join-Path $roleDir "role.json")
            "# Security Specialist v1" | Set-Content (Join-Path $roleDir "ROLE.md")

            & $script:SyncScript -ProjectDir $script:ProjectDir -AgentsDir $script:AgentsOut

            # Update the source
            "# Security Specialist v2" | Set-Content (Join-Path $roleDir "ROLE.md")

            # Re-sync
            & $script:SyncScript -ProjectDir $script:ProjectDir -AgentsDir $script:AgentsOut

            $content = Get-Content (Join-Path $script:AgentsOut "security-specialist.md") -Raw
            $content | Should -Match "v2"
            $content | Should -Not -Match "v1"
        }
    }

    Context "security-specialist contributed role invariant" {
        It "after sync, security-specialist.md exists with contributed ROLE.md content" {
            # This is the canonical invariant: after ostwin init, opencode can find
            # security-specialist because its ROLE.md was synced from contributes/roles/
            $roleDir = Join-Path $script:ProjectDir "contributes" "roles" "security-specialist"
            New-Item -ItemType Directory -Path $roleDir -Force | Out-Null
            '{"name":"security-specialist","trust_level":"core"}' | Set-Content (Join-Path $roleDir "role.json")
            @"
---
name: security-specialist
description: Evaluates security work as a specialist reviewer
tags: [security, specialist, evaluator]
trust_level: core
---
# Security Specialist
"@ | Set-Content (Join-Path $roleDir "ROLE.md")

            & $script:SyncScript -ProjectDir $script:ProjectDir -AgentsDir $script:AgentsOut

            $dest = Join-Path $script:AgentsOut "security-specialist.md"
            Test-Path $dest | Should -BeTrue -Because "opencode run --agent security-specialist needs this file"
            $content = Get-Content $dest -Raw
            $content | Should -Match "security-specialist" -Because "should contain contributed ROLE.md, not a generic scaffold"
        }

        It "generic scaffold is NOT written when contributed role has no ROLE.md" {
            # Corner-case: contributed role exists with role.json but ROLE.md missing.
            # Sync must not write any placeholder/generic file — it should only copy
            # what actually exists.
            $roleDir = Join-Path $script:ProjectDir "contributes" "roles" "security-specialist"
            New-Item -ItemType Directory -Path $roleDir -Force | Out-Null
            '{"name":"security-specialist"}' | Set-Content (Join-Path $roleDir "role.json")
            # NO ROLE.md

            & $script:SyncScript -ProjectDir $script:ProjectDir -AgentsDir $script:AgentsOut

            Test-Path (Join-Path $script:AgentsOut "security-specialist.md") | Should -BeFalse `
                -Because "sync must not auto-scaffold generic content"
        }
    }

    Context "Missing source directories handled gracefully" {
        It "does not throw when .agents/roles/ does not exist" {
            # Only contributes/roles/ exists
            $roleDir = Join-Path $script:ProjectDir "contributes" "roles" "reporter"
            New-Item -ItemType Directory -Path $roleDir -Force | Out-Null
            '{"name":"reporter"}' | Set-Content (Join-Path $roleDir "role.json")
            "# Reporter" | Set-Content (Join-Path $roleDir "ROLE.md")

            { & $script:SyncScript -ProjectDir $script:ProjectDir -AgentsDir $script:AgentsOut } | Should -Not -Throw

            Test-Path (Join-Path $script:AgentsOut "reporter.md") | Should -BeTrue
        }

        It "does not throw when neither roles directory exists" {
            { & $script:SyncScript -ProjectDir $script:ProjectDir -AgentsDir $script:AgentsOut } | Should -Not -Throw
        }
    }
}
