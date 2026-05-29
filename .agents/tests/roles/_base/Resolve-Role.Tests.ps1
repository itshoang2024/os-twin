<#
.SYNOPSIS
    Tests for Resolve-Role.ps1 — the 4-tier role resolution system.
.DESCRIPTION
    Validates all resolution tiers:
      Tier 1: Static registry match (registry.json)
      Tier 2: Dynamic filesystem discovery (roles/{name}/role.json)
      Tier 3: Capability-based matching (best overlap score)
      Tier 4: Ephemeral agent fallback (Start-EphemeralAgent.ps1)
    Also tests: instance suffix parsing, AvailableRoles cache,
    model/timeout propagation, and edge cases.
#>

Describe "Resolve-Role" {
    BeforeAll {
        $script:resolveRole = Join-Path (Resolve-Path "$PSScriptRoot/../../../roles/_base").Path "Resolve-Role.ps1"

        # Create an isolated test environment
        $script:testRoot = Join-Path ([System.IO.Path]::GetTempPath()) "resolve-role-tests-$(Get-Random)"
        $script:agentsDir = Join-Path $script:testRoot ".agents"
        $script:warRoomsDir = Join-Path $script:testRoot ".war-rooms"

        # Build directory structure
        New-Item -ItemType Directory -Path (Join-Path $script:agentsDir "roles" "_base") -Force | Out-Null
        New-Item -ItemType Directory -Path (Join-Path $script:agentsDir "roles" "engineer") -Force | Out-Null
        New-Item -ItemType Directory -Path (Join-Path $script:agentsDir "roles" "qa") -Force | Out-Null
        New-Item -ItemType Directory -Path $script:warRoomsDir -Force | Out-Null

        # --- Create runner scripts (just touch files so Test-Path passes) ---
        $script:engineerRunner = Join-Path $script:agentsDir "roles" "engineer" "Start-Engineer.ps1"
        "# stub" | Out-File -FilePath $script:engineerRunner -Encoding utf8
        $script:qaRunner = Join-Path $script:agentsDir "roles" "qa" "Start-QA.ps1"
        "# stub" | Out-File -FilePath $script:qaRunner -Encoding utf8

        # --- Create Start-EphemeralAgent.ps1 (Tier 4 fallback) ---
        $script:ephemeralRunner = Join-Path $script:agentsDir "roles" "_base" "Start-EphemeralAgent.ps1"
        "# stub ephemeral" | Out-File -FilePath $script:ephemeralRunner -Encoding utf8

        # --- Create Start-DynamicRole.ps1 (Tier 2 dynamic fallback) ---
        $script:dynamicRunner = Join-Path $script:agentsDir "roles" "_base" "Start-DynamicRole.ps1"
        "# stub dynamic" | Out-File -FilePath $script:dynamicRunner -Encoding utf8

        # --- Create Get-AvailableRoles.ps1 (for Tier 3) ---
        $script:getAvailableRoles = Join-Path $script:agentsDir "roles" "_base" "Get-AvailableRoles.ps1"
        # Stub that returns the cached roles based on AgentsDir
        @'
[CmdletBinding()]
param([string]$AgentsDir, [string]$WarRoomsDir)
# Return an empty list — tests using Tier 3 will provide AvailableRoles directly
Write-Output @()
'@ | Out-File -FilePath $script:getAvailableRoles -Encoding utf8

        # --- Build registry.json ---
        $script:registry = @{
            roles = @(
                @{
                    name           = "engineer"
                    runner         = "roles/engineer/Start-Engineer.ps1"
                    default_model  = "google-vertex/gemini-3-flash-preview"
                    capabilities   = @("code-generation", "file-editing", "shell-execution", "testing")
                },
                @{
                    name           = "qa"
                    runner         = "roles/qa/Start-QA.ps1"
                    default_model  = "google-vertex/gemini-3.1-pro-preview"
                    capabilities   = @("code-review", "test-execution", "security-review")
                }
            )
        }
        $script:registryPath = Join-Path $script:agentsDir "roles" "registry.json"
        $script:registry | ConvertTo-Json -Depth 5 | Out-File -FilePath $script:registryPath -Encoding utf8

        # --- Create role.json for engineer (discovery support) ---
        @{
            name         = "engineer"
            capabilities = @("code-generation", "file-editing")
            model        = "google-vertex/gemini-3-flash-preview"
            timeout_seconds = 600
        } | ConvertTo-Json | Out-File -FilePath (Join-Path $script:agentsDir "roles" "engineer" "role.json") -Encoding utf8

        # --- Create role.json for qa (discovery support) ---
        @{
            name         = "qa"
            capabilities = @("code-review", "test-execution", "security-review")
            model        = "google-vertex/gemini-3.1-pro-preview"
            timeout_seconds = 300
        } | ConvertTo-Json | Out-File -FilePath (Join-Path $script:agentsDir "roles" "qa" "role.json") -Encoding utf8
    }

    AfterAll {
        if (Test-Path $script:testRoot) {
            Remove-Item $script:testRoot -Recurse -Force
        }
    }

    # =====================================================
    # TIER 1: Static Registry Match
    # =====================================================
    Context "Tier 1 — Static Registry Match" {

        It "resolves 'engineer' to the registry runner script" {
            $result = & $script:resolveRole -RoleName "engineer" -AgentsDir $script:agentsDir
            $result.Runner | Should -Be $script:engineerRunner
            $result.Source | Should -Be "registry"
            $result.BaseRole | Should -Be "engineer"
            $result.Name | Should -Be "engineer"
        }

        It "resolves 'qa' to the registry runner script" {
            $result = & $script:resolveRole -RoleName "qa" -AgentsDir $script:agentsDir
            $result.Runner | Should -Be $script:qaRunner
            $result.Source | Should -Be "registry"
            $result.BaseRole | Should -Be "qa"
        }

        It "propagates default_model from registry" {
            $result = & $script:resolveRole -RoleName "qa" -AgentsDir $script:agentsDir
            $result.Model | Should -Be "google-vertex/gemini-3.1-pro-preview"
        }

        It "propagates capabilities from registry" {
            $result = & $script:resolveRole -RoleName "engineer" -AgentsDir $script:agentsDir
            $result.Capabilities | Should -Contain "code-generation"
            $result.Capabilities | Should -Contain "file-editing"
            $result.Capabilities | Should -Contain "shell-execution"
            $result.Capabilities | Should -Contain "testing"
        }

        It "parses instance suffix from role name (e.g. engineer:fe)" {
            $result = & $script:resolveRole -RoleName "engineer:fe" -AgentsDir $script:agentsDir
            $result.BaseRole | Should -Be "engineer"
            $result.Name | Should -Be "engineer:fe"
            $result.Runner | Should -Be $script:engineerRunner
            $result.Source | Should -Be "registry"
        }

        It "parses instance suffix from role name (e.g. engineer:be)" {
            $result = & $script:resolveRole -RoleName "engineer:be" -AgentsDir $script:agentsDir
            $result.BaseRole | Should -Be "engineer"
            $result.Name | Should -Be "engineer:be"
            $result.Runner | Should -Be $script:engineerRunner
        }
    }

    # =====================================================
    # TIER 2: Dynamic Filesystem Discovery
    # =====================================================
    Context "Tier 2 — Filesystem Discovery" {

        BeforeAll {
            # Create a role NOT in registry but on disk
            $script:customRoleDir = Join-Path $script:agentsDir "roles" "security-auditor"
            New-Item -ItemType Directory -Path $script:customRoleDir -Force | Out-Null

            @{
                name         = "security-auditor"
                capabilities = @("security-review", "vulnerability-scanning")
                model        = "google-vertex/gemini-3.1-pro-preview"
                timeout_seconds = 900
            } | ConvertTo-Json | Out-File -FilePath (Join-Path $script:customRoleDir "role.json") -Encoding utf8
        }

        AfterAll {
            if (Test-Path $script:customRoleDir) {
                Remove-Item $script:customRoleDir -Recurse -Force
            }
        }

        It "discovers a role from disk when not in registry" {
            $result = & $script:resolveRole -RoleName "security-auditor" -AgentsDir $script:agentsDir
            $result.Source | Should -Be "discovered"
            $result.BaseRole | Should -Be "security-auditor"
        }

        It "uses Start-DynamicRole.ps1 when no custom Start-*.ps1 exists" {
            $result = & $script:resolveRole -RoleName "security-auditor" -AgentsDir $script:agentsDir
            $result.Runner | Should -Be $script:dynamicRunner
        }

        It "uses custom Start-*.ps1 when present" {
            $customRunner = Join-Path $script:customRoleDir "Start-security-auditor.ps1"
            "# custom runner" | Out-File -FilePath $customRunner -Encoding utf8

            $result = & $script:resolveRole -RoleName "security-auditor" -AgentsDir $script:agentsDir
            $result.Runner | Should -Be $customRunner
            $result.Source | Should -Be "discovered"

            Remove-Item $customRunner -Force
        }

        It "propagates model and timeout from discovered role.json" {
            $result = & $script:resolveRole -RoleName "security-auditor" -AgentsDir $script:agentsDir
            $result.Model | Should -Be "google-vertex/gemini-3.1-pro-preview"
            $result.Timeout | Should -Be 900
        }

        It "propagates capabilities from discovered role.json" {
            $result = & $script:resolveRole -RoleName "security-auditor" -AgentsDir $script:agentsDir
            $result.Capabilities | Should -Contain "security-review"
            $result.Capabilities | Should -Contain "vulnerability-scanning"
        }
    }

    # =====================================================
    # TIER 3: Capability-Based Matching
    # =====================================================
    Context "Tier 3 — Capability-Based Matching" {

        It "matches by capability overlap when role name is unknown" {
            $mockRoles = @(
                [PSCustomObject]@{
                    Name         = "engineer"
                    Runner       = $script:engineerRunner
                    Model        = "google-vertex/gemini-3-flash-preview"
                    Timeout      = 600
                    Capabilities = @("code-generation", "file-editing", "shell-execution")
                    Source       = "registry"
                },
                [PSCustomObject]@{
                    Name         = "qa"
                    Runner       = $script:qaRunner
                    Model        = "google-vertex/gemini-3.1-pro-preview"
                    Timeout      = 300
                    Capabilities = @("code-review", "test-execution", "security-review")
                    Source       = "registry"
                }
            )

            # Request capabilities that overlap more with qa
            $result = & $script:resolveRole `
                -RoleName "" `
                -RequiredCapabilities @("code-review", "security-review") `
                -AgentsDir $script:agentsDir `
                -AvailableRoles $mockRoles

            $result.Source | Should -Be "capability-match"
            $result.BaseRole | Should -Be "qa"
            $result.Runner | Should -Be $script:qaRunner
        }

        It "picks the role with the highest capability overlap" {
            $mockRoles = @(
                [PSCustomObject]@{
                    Name         = "engineer"
                    Runner       = $script:engineerRunner
                    Model        = "google-vertex/gemini-3-flash-preview"
                    Timeout      = 600
                    Capabilities = @("code-generation", "file-editing", "shell-execution")
                    Source       = "registry"
                },
                [PSCustomObject]@{
                    Name         = "qa"
                    Runner       = $script:qaRunner
                    Model        = "google-vertex/gemini-3.1-pro-preview"
                    Timeout      = 300
                    Capabilities = @("code-review", "test-execution", "security-review")
                    Source       = "registry"
                }
            )

            # Request capabilities that overlap with engineer (2 vs 0)
            $result = & $script:resolveRole `
                -RoleName "" `
                -RequiredCapabilities @("code-generation", "shell-execution") `
                -AgentsDir $script:agentsDir `
                -AvailableRoles $mockRoles

            $result.BaseRole | Should -Be "engineer"
            $result.Source | Should -Be "capability-match"
        }

        It "falls through to Tier 4 when no capabilities match" {
            $mockRoles = @(
                [PSCustomObject]@{
                    Name         = "engineer"
                    Runner       = $script:engineerRunner
                    Capabilities = @("code-generation")
                    Source       = "registry"
                }
            )

            $result = & $script:resolveRole `
                -RoleName "" `
                -RequiredCapabilities @("quantum-computing", "teleportation") `
                -AgentsDir $script:agentsDir `
                -AvailableRoles $mockRoles

            $result.Source | Should -Be "ephemeral"
        }
    }

    # =====================================================
    # TIER 4: Ephemeral Agent Fallback
    # =====================================================
    Context "Tier 4 — Ephemeral Agent Fallback" {

        It "falls back to Start-EphemeralAgent.ps1 for unknown roles" {
            $result = & $script:resolveRole -RoleName "completely-unknown-role" -AgentsDir $script:agentsDir
            $result.Runner | Should -Be $script:ephemeralRunner
            $result.Source | Should -Be "ephemeral"
        }

        It "falls back to ephemeral when no role name and no capabilities given" {
            $result = & $script:resolveRole -RoleName "" -AgentsDir $script:agentsDir
            $result.Runner | Should -Be $script:ephemeralRunner
            $result.Source | Should -Be "ephemeral"
        }

        It "sets default model for ephemeral roles" {
            $result = & $script:resolveRole -RoleName "unknown-role" -AgentsDir $script:agentsDir
            $result.Model | Should -Be "google-vertex/gemini-3-flash-preview"
        }
    }

    # =====================================================
    # AvailableRoles Cache (Fast Path)
    # =====================================================
    Context "AvailableRoles Cache — Fast Path" {

        It "uses cached AvailableRoles for Tier 1/2 fast lookup" {
            $cachedRoles = @(
                [PSCustomObject]@{
                    Name         = "engineer"
                    Runner       = "/custom/path/Start-Engineer.ps1"
                    Model        = "google-vertex/gemini-turbo"
                    Timeout      = 999
                    Capabilities = @("everything")
                    Source       = "registry"
                }
            )

            $result = & $script:resolveRole -RoleName "engineer" -AgentsDir $script:agentsDir -AvailableRoles $cachedRoles
            $result.Runner | Should -Be "/custom/path/Start-Engineer.ps1"
            $result.Model | Should -Be "google-vertex/gemini-turbo"
            $result.Timeout | Should -Be 999
            $result.Capabilities | Should -Contain "everything"
        }

        It "falls through cache miss to registry lookup" {
            # Cache says "qa" only, request "engineer" → not in cache → falls to Tier 1 registry
            $cachedRoles = @(
                [PSCustomObject]@{
                    Name         = "qa"
                    Runner       = "/cached/qa"
                    Model        = "model"
                    Capabilities = @()
                    Source       = "registry"
                }
            )

            $result = & $script:resolveRole -RoleName "engineer" -AgentsDir $script:agentsDir -AvailableRoles $cachedRoles
            # Should resolve from registry (Tier 1), not cache
            $result.Runner | Should -Be $script:engineerRunner
            $result.Source | Should -Be "registry"
        }
    }

    # =====================================================
    # Edge Cases
    # =====================================================
    Context "Edge Cases" {

        It "handles missing registry.json gracefully" {
            $tempAgents = Join-Path ([System.IO.Path]::GetTempPath()) "resolve-role-empty-$(Get-Random)"
            New-Item -ItemType Directory -Path (Join-Path $tempAgents "roles" "_base") -Force | Out-Null
            # Create ephemeral stub
            "# stub" | Out-File -FilePath (Join-Path $tempAgents "roles" "_base" "Start-EphemeralAgent.ps1") -Encoding utf8

            # Isolate from ~/.ostwin so globally-scaffolded roles don't interfere
            $savedOstwinHome = $env:OSTWIN_HOME
            $env:OSTWIN_HOME = Join-Path ([System.IO.Path]::GetTempPath()) "ostwin-empty-$(Get-Random)"
            try {
                $result = & $script:resolveRole -RoleName "engineer" -AgentsDir $tempAgents
                $result.Source | Should -Be "ephemeral"
            }
            finally {
                $env:OSTWIN_HOME = $savedOstwinHome
                Remove-Item $tempAgents -Recurse -Force
            }
        }

        It "handles registry with runner that doesn't exist on disk" {
            $tempAgents = Join-Path ([System.IO.Path]::GetTempPath()) "resolve-role-bad-runner-$(Get-Random)"
            New-Item -ItemType Directory -Path (Join-Path $tempAgents "roles" "_base") -Force | Out-Null
            "# stub" | Out-File -FilePath (Join-Path $tempAgents "roles" "_base" "Start-EphemeralAgent.ps1") -Encoding utf8

            @{
                roles = @(@{
                    name   = "broken"
                    runner = "roles/broken/Start-Broken.ps1"  # file doesn't exist
                })
            } | ConvertTo-Json -Depth 3 | Out-File -FilePath (Join-Path $tempAgents "roles" "registry.json") -Encoding utf8

            $result = & $script:resolveRole -RoleName "broken" -AgentsDir $tempAgents
            # Runner file missing → falls through to ephemeral
            $result.Source | Should -Be "ephemeral"

            Remove-Item $tempAgents -Recurse -Force
        }

        It "tier precedence: registry beats discovery" {
            # Engineer exists in BOTH registry AND on disk.
            # Tier 1 (registry) should win.
            $result = & $script:resolveRole -RoleName "engineer" -AgentsDir $script:agentsDir
            $result.Source | Should -Be "registry"
        }

        It "tier precedence: cache beats registry" {
            $cachedRoles = @(
                [PSCustomObject]@{
                    Name         = "engineer"
                    Runner       = "/cached/engineer/run.ps1"
                    Model        = "cached-model"
                    Capabilities = @("cached-cap")
                    Source       = "cached"
                }
            )

            $result = & $script:resolveRole -RoleName "engineer" -AgentsDir $script:agentsDir -AvailableRoles $cachedRoles
            $result.Runner | Should -Be "/cached/engineer/run.ps1"
            $result.Source | Should -Be "cached"
        }

        It "returns clean PSCustomObject with all required properties" {
            $result = & $script:resolveRole -RoleName "engineer" -AgentsDir $script:agentsDir
            $result.PSObject.Properties.Name | Should -Contain "Name"
            $result.PSObject.Properties.Name | Should -Contain "BaseRole"
            $result.PSObject.Properties.Name | Should -Contain "Runner"
            $result.PSObject.Properties.Name | Should -Contain "Model"
            $result.PSObject.Properties.Name | Should -Contain "Timeout"
            $result.PSObject.Properties.Name | Should -Contain "Capabilities"
            $result.PSObject.Properties.Name | Should -Contain "Source"
        }
    }

    # =====================================================
    # @ Prefix Stripping (Markdown role notation)
    # =====================================================
    Context "@ Prefix Stripping — Markdown Role Notation" {

        It "resolves '@engineer' the same as 'engineer' (Tier 1)" {
            $result = & $script:resolveRole -RoleName "@engineer" -AgentsDir $script:agentsDir
            $result.Runner | Should -Be $script:engineerRunner
            $result.Source | Should -Be "registry"
            $result.BaseRole | Should -Be "engineer"
            $result.Name | Should -Be "engineer"
        }

        It "resolves '@qa' the same as 'qa' (Tier 1)" {
            $result = & $script:resolveRole -RoleName "@qa" -AgentsDir $script:agentsDir
            $result.Runner | Should -Be $script:qaRunner
            $result.Source | Should -Be "registry"
            $result.BaseRole | Should -Be "qa"
        }

        It "strips @ and preserves instance suffix (@engineer:fe)" {
            $result = & $script:resolveRole -RoleName "@engineer:fe" -AgentsDir $script:agentsDir
            $result.BaseRole | Should -Be "engineer"
            $result.Name | Should -Be "engineer:fe"
            $result.Runner | Should -Be $script:engineerRunner
            $result.Source | Should -Be "registry"
        }

        It "propagates model correctly when using @ prefix" {
            $result = & $script:resolveRole -RoleName "@qa" -AgentsDir $script:agentsDir
            $result.Model | Should -Be "google-vertex/gemini-3.1-pro-preview"
        }

        It "propagates capabilities correctly when using @ prefix" {
            $result = & $script:resolveRole -RoleName "@engineer" -AgentsDir $script:agentsDir
            $result.Capabilities | Should -Contain "code-generation"
            $result.Capabilities | Should -Contain "file-editing"
        }

        It "falls back to ephemeral for unknown @-prefixed role" {
            $result = & $script:resolveRole -RoleName "@unknown-role" -AgentsDir $script:agentsDir
            $result.Runner | Should -Be $script:ephemeralRunner
            $result.Source | Should -Be "ephemeral"
        }

        It "uses cached AvailableRoles with @ prefix" {
            $cachedRoles = @(
                [PSCustomObject]@{
                    Name         = "engineer"
                    Runner       = "/cached/path/Start-Engineer.ps1"
                    Model        = "cached-model"
                    Timeout      = 777
                    Capabilities = @("cached-cap")
                    Source       = "cached"
                }
            )

            $result = & $script:resolveRole -RoleName "@engineer" -AgentsDir $script:agentsDir -AvailableRoles $cachedRoles
            $result.Runner | Should -Be "/cached/path/Start-Engineer.ps1"
            $result.Source | Should -Be "cached"
        }
    }

    # =====================================================
    # Registry timeout propagation (security-engineer scenario)
    # =====================================================
    # security-engineer is the first role to carry a per-role `timeout` in
    # registry.json. These tests pin that the registry-tier reads it, that the
    # `timeout_seconds` alias still works, and that the default fallback
    # remains 600 when neither key is present.
    Context "Registry timeout propagation" {

        BeforeAll {
            $script:tempTimeoutRoot = Join-Path ([System.IO.Path]::GetTempPath()) "resolve-role-timeout-$(Get-Random)"
            $script:tempTimeoutAgents = Join-Path $script:tempTimeoutRoot ".agents"
            New-Item -ItemType Directory -Path (Join-Path $script:tempTimeoutAgents "roles" "_base") -Force | Out-Null
            New-Item -ItemType Directory -Path (Join-Path $script:tempTimeoutAgents "roles" "security-engineer") -Force | Out-Null
            New-Item -ItemType Directory -Path (Join-Path $script:tempTimeoutAgents "roles" "alias-role") -Force | Out-Null
            New-Item -ItemType Directory -Path (Join-Path $script:tempTimeoutAgents "roles" "no-timeout-role") -Force | Out-Null

            $script:dynRunner = Join-Path $script:tempTimeoutAgents "roles" "_base" "Start-DynamicRole.ps1"
            "# stub dynamic" | Out-File -FilePath $script:dynRunner -Encoding utf8
            "# stub ephemeral" | Out-File -FilePath (Join-Path $script:tempTimeoutAgents "roles" "_base" "Start-EphemeralAgent.ps1") -Encoding utf8

            @{
                roles = @(
                    @{
                        name          = "security-engineer"
                        runner        = "roles/_base/Start-DynamicRole.ps1"
                        capabilities  = @("security", "secure-code-review")
                        default_model = "google-vertex/zai-org/glm-5-maas"
                        timeout       = 3600
                    },
                    @{
                        name            = "alias-role"
                        runner          = "roles/_base/Start-DynamicRole.ps1"
                        capabilities    = @("audit")
                        timeout_seconds = 1800
                    },
                    @{
                        name         = "no-timeout-role"
                        runner       = "roles/_base/Start-DynamicRole.ps1"
                        capabilities = @("misc")
                    }
                )
            } | ConvertTo-Json -Depth 5 | Out-File -FilePath (Join-Path $script:tempTimeoutAgents "roles" "registry.json") -Encoding utf8
        }

        AfterAll {
            if (Test-Path $script:tempTimeoutRoot) {
                Remove-Item $script:tempTimeoutRoot -Recurse -Force
            }
        }

        It "propagates the registry 'timeout' field to Resolve-Role result" {
            $result = & $script:resolveRole -RoleName "security-engineer" -AgentsDir $script:tempTimeoutAgents
            $result.Source | Should -Be "registry"
            $result.Runner | Should -Be $script:dynRunner
            $result.Timeout | Should -Be 3600
            $result.Capabilities | Should -Contain "security"
        }

        It "honours the 'timeout_seconds' alias when 'timeout' is absent" {
            $result = & $script:resolveRole -RoleName "alias-role" -AgentsDir $script:tempTimeoutAgents
            $result.Timeout | Should -Be 1800
        }

        It "falls back to the default 600s timeout when neither key is set" {
            $result = & $script:resolveRole -RoleName "no-timeout-role" -AgentsDir $script:tempTimeoutAgents
            $result.Timeout | Should -Be 600
        }

        It "routes the 'security' capability to security-engineer via capability-match" {
            # Tier 3 capability matching: when no role name is given, the
            # 'security' capability should land on security-engineer (the
            # routing fix that supersedes the dead 'security-auditor' mapping).
            $mockRoles = @(
                [PSCustomObject]@{
                    Name         = "engineer"
                    Runner       = $script:engineerRunner
                    Capabilities = @("code-generation", "file-editing")
                    Source       = "registry"
                },
                [PSCustomObject]@{
                    Name         = "security-engineer"
                    Runner       = $script:dynRunner
                    Capabilities = @("security", "secure-code-review", "threat-modeling")
                    Source       = "registry"
                }
            )

            $result = & $script:resolveRole `
                -RoleName "" `
                -RequiredCapabilities @("security") `
                -AgentsDir $script:tempTimeoutAgents `
                -AvailableRoles $mockRoles

            $result.Source | Should -Be "capability-match"
            $result.BaseRole | Should -Be "security-engineer"
        }
    }
}
