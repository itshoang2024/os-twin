# Agent OS — Get-RoleDefinition Pester Tests

BeforeAll {
    $script:GetRoleDef = Join-Path (Resolve-Path "$PSScriptRoot/../../../roles/_base").Path "Get-RoleDefinition.ps1"
    $script:rolesDir = Join-Path (Resolve-Path "$PSScriptRoot/../../../roles/_base").Path ".."
}

Describe "Get-RoleDefinition" {
    Context "JSON role definition" {
        BeforeEach {
            $script:rolePath = Join-Path $TestDrive "role-json-$(Get-Random)"
            New-Item -ItemType Directory -Path $script:rolePath -Force | Out-Null

            @{
                name          = "test-engineer"
                description   = "Test engineer for CI validation"
                capabilities  = @("code-generation", "file-editing", "shell-execution", "testing")
                prompt_file   = "ROLE.md"
                quality_gates = @("unit-tests", "lint")
                skills        = @("python", "javascript", "sql")
                cli           = "agent"
                model         = "google-vertex/gemini-3-flash"
                timeout       = 300
            } | ConvertTo-Json -Depth 3 | Out-File (Join-Path $script:rolePath "role.json") -Encoding utf8

            "# Test Engineer`nYou are a test engineer..." |
                Out-File (Join-Path $script:rolePath "ROLE.md") -Encoding utf8
        }

        It "loads role name" {
            $role = & $script:GetRoleDef -RolePath $script:rolePath
            $role.Name | Should -Be "test-engineer"
        }

        It "loads description" {
            $role = & $script:GetRoleDef -RolePath $script:rolePath
            $role.Description | Should -Be "Test engineer for CI validation"
        }

        It "loads capabilities" {
            $role = & $script:GetRoleDef -RolePath $script:rolePath
            $role.Capabilities | Should -Contain "code-generation"
            $role.Capabilities | Should -Contain "testing"
            $role.Capabilities.Count | Should -Be 4
        }

        It "loads quality gates" {
            $role = & $script:GetRoleDef -RolePath $script:rolePath
            $role.QualityGates | Should -Contain "unit-tests"
            $role.QualityGates | Should -Contain "lint"
        }

        It "loads skills" {
            $role = & $script:GetRoleDef -RolePath $script:rolePath
            $role.Skills | Should -Contain "python"
            $role.Skills.Count | Should -Be 3
        }

        It "loads CLI config" {
            $role = & $script:GetRoleDef -RolePath $script:rolePath
            $role.CLI | Should -Be "agent"
            $role.Model | Should -Be "google-vertex/gemini-3-flash"
            $role.Timeout | Should -Be 300
        }

        It "loads prompt template from ROLE.md" {
            $role = & $script:GetRoleDef -RolePath $script:rolePath
            $role.PromptTemplate | Should -Match "You are a test engineer"
        }

        It "stores source file path" {
            $role = & $script:GetRoleDef -RolePath $script:rolePath
            $role.SourceFile | Should -Match "role\.json"
        }
    }

    Context "Default from ROLE.md" {
        BeforeEach {
            $script:rolePath = Join-Path $TestDrive "role-default-$(Get-Random)"
            New-Item -ItemType Directory -Path $script:rolePath -Force | Out-Null
            "# Custom Role`nYou do custom things." |
                Out-File (Join-Path $script:rolePath "ROLE.md") -Encoding utf8
        }

        It "generates default role from ROLE.md when no definition file" {
            $role = & $script:GetRoleDef -RolePath $script:rolePath
            $role.Name | Should -Not -BeNullOrEmpty
            $role.Description | Should -Match "Custom Role"
        }

        It "sets default capabilities" {
            $role = & $script:GetRoleDef -RolePath $script:rolePath
            $role.Capabilities | Should -Contain "code-generation"
        }

        It "loads prompt from ROLE.md" {
            $role = & $script:GetRoleDef -RolePath $script:rolePath
            $role.PromptTemplate | Should -Match "custom things"
        }

        It "uses default CLI" {
            $role = & $script:GetRoleDef -RolePath $script:rolePath
            $role.CLI | Should -Be "agent"
        }

        It "uses default timeout" {
            $role = & $script:GetRoleDef -RolePath $script:rolePath
            $role.Timeout | Should -Be 600
        }
    }

    Context "Built-in roles" {
        It "loads engineer role from standard path" {
            $engPath = Join-Path $script:rolesDir "engineer"
            if (Test-Path $engPath) {
                $role = & $script:GetRoleDef -RolePath $engPath
                $role.Name | Should -Not -BeNullOrEmpty
            }
        }

        It "loads qa role from standard path" {
            $qaPath = Join-Path $script:rolesDir "qa"
            if (Test-Path $qaPath) {
                $role = & $script:GetRoleDef -RolePath $qaPath
                $role.Name | Should -Not -BeNullOrEmpty
            }
        }
    }

    Context "Role by name" {
        It "resolves role by name when RolePath not provided" {
            $engPath = Join-Path $script:rolesDir "engineer"
            if (Test-Path $engPath) {
                $role = & $script:GetRoleDef -RoleName "engineer"
                $role.Name | Should -Not -BeNullOrEmpty
                $role.RolePath | Should -Match "engineer"
            }
        }
    }

    Context "Error handling" {
        It "fails when neither path nor name provided" {
            $ErrorActionPreference = 'Continue'
            $output = & $script:GetRoleDef 2>&1
            $output | Should -Match "not found"
        }
    }

    Context "Empty role directory" {
        It "generates minimal default for empty directory" {
            $emptyPath = Join-Path $TestDrive "empty-role-$(Get-Random)"
            New-Item -ItemType Directory -Path $emptyPath -Force | Out-Null

            $role = & $script:GetRoleDef -RolePath $emptyPath
            $role.Name | Should -Not -BeNullOrEmpty
            $role.Description | Should -Match "role"
        }
    }
}
