# Agent OS — Test-SkillCoverage.ps1 Pester Tests

BeforeAll {
    $script:TestSkillCoverage = Join-Path (Resolve-Path "$PSScriptRoot/../../plan").Path "Test-SkillCoverage.ps1"

    # Resolve global scaffold paths (same as the script under test)
    $script:homeDir = [Environment]::GetFolderPath('UserProfile')
    $script:ostwinRolesDir = Join-Path $script:homeDir ".ostwin" ".agents" "roles"
    $script:ostwinSkillsDir = Join-Path $script:homeDir ".ostwin" ".agents" "skills"
    $script:openCodeAgentsDir = Join-Path $script:homeDir ".config" "opencode" "agents"

    # Unique suffix to avoid collisions with real roles
    $script:testSuffix = "pester-$(Get-Random -Minimum 100000 -Maximum 999999)"

    function global:Get-OstwinConfig {
        return [PSCustomObject]@{
            manager = [PSCustomObject]@{
                preflight_skill_check = "warn"
            }
        }
    }

    # Helper: build a plan entry
    function global:New-PlanEntry {
        param(
            [string]$TaskRef = "EPIC-001",
            [string[]]$Roles = @("engineer"),
            [string]$Objective = ""
        )
        [PSCustomObject]@{
            TaskRef     = $TaskRef
            Roles       = $Roles
            Objective   = $Objective
            Description = ""
        }
    }
}

Describe "Test-SkillCoverage" {
    BeforeEach {
        # Isolated project directory per test
        $script:projectDir = Join-Path $TestDrive "project-$(Get-Random)"
        $script:agentsDir = Join-Path $script:projectDir ".agents"
        $script:rolesDir = Join-Path $script:agentsDir "roles"
        New-Item -ItemType Directory -Path $script:rolesDir -Force | Out-Null

        # Minimal registry.json
        $script:registryPath = Join-Path $script:rolesDir "registry.json"
        @{ roles = @() } | ConvertTo-Json -Depth 5 | Out-File -FilePath $script:registryPath -Encoding utf8

        # Track roles and skill dirs created during tests for cleanup
        $script:createdRoles = [System.Collections.Generic.List[string]]::new()
        $script:createdHomeSkillDirs = [System.Collections.Generic.List[string]]::new()
    }

    AfterEach {
        # Clean up any scaffolded roles in global dirs
        foreach ($roleName in $script:createdRoles) {
            $ostwinPath = Join-Path $script:ostwinRolesDir $roleName
            if (Test-Path $ostwinPath) {
                Remove-Item -Path $ostwinPath -Recurse -Force -ErrorAction SilentlyContinue
            }
            $openCodePath = Join-Path $script:openCodeAgentsDir "$roleName.md"
            if (Test-Path $openCodePath) {
                Remove-Item -Path $openCodePath -Force -ErrorAction SilentlyContinue
            }
        }

        # Clean up any skill dirs we seeded under ~/.ostwin/.agents/skills/
        foreach ($skillPath in $script:createdHomeSkillDirs) {
            if (Test-Path $skillPath) {
                Remove-Item -Path $skillPath -Recurse -Force -ErrorAction SilentlyContinue
            }
        }
    }

    # ═══════════════════════════════════════════════════════════════════════
    #  LOOKUP TESTS
    # ═══════════════════════════════════════════════════════════════════════

    Context "Role lookup in project .agents/roles/" {
        It "finds a role in project .agents/roles/ without scaffolding" {
            $roleName = "local-role-$script:testSuffix"
            $localRolePath = Join-Path $script:rolesDir $roleName
            New-Item -ItemType Directory -Path $localRolePath -Force | Out-Null
            @{ name = $roleName } | ConvertTo-Json | Out-File (Join-Path $localRolePath "role.json") -Encoding utf8

            $plan = @(New-PlanEntry -Roles @($roleName))

            $output = & $script:TestSkillCoverage -PlanParsed $plan -ProjectDir $script:projectDir *>&1
            $outputStr = $output -join "`n"

            # Should NOT warn about this role
            $outputStr | Should -Not -Match "Role '$roleName' not found"
            # Should NOT scaffold
            $outputStr | Should -Not -Match "Auto-scaffolded.*$roleName"
            $outputStr | Should -Match "All required skills and roles verified"
        }
    }

    Context "Role lookup in ~/.ostwin/.agents/roles/" {
        It "finds a role in ~/.ostwin/.agents/roles/ without scaffolding" {
            $roleName = "ostwin-role-$script:testSuffix"
            $script:createdRoles.Add($roleName)

            # Pre-create the role at ~/.ostwin/.agents/roles/<role>/
            $ostwinPath = Join-Path $script:ostwinRolesDir $roleName
            New-Item -ItemType Directory -Path $ostwinPath -Force | Out-Null
            @{ name = $roleName } | ConvertTo-Json | Out-File (Join-Path $ostwinPath "role.json") -Encoding utf8

            $plan = @(New-PlanEntry -Roles @($roleName))

            $output = & $script:TestSkillCoverage -PlanParsed $plan -ProjectDir $script:projectDir *>&1
            $outputStr = $output -join "`n"

            $outputStr | Should -Not -Match "Role '$roleName' not found"
            $outputStr | Should -Not -Match "Auto-scaffolded.*$roleName"
        }
    }

    Context "Role lookup in contributes/roles/" {
        It "finds a role in contributes/roles/ without scaffolding" {
            $roleName = "contrib-role-$script:testSuffix"

            # Pre-create the role inside the project's contributes/roles/
            $contributePath = Join-Path $script:projectDir "contributes" "roles" $roleName
            New-Item -ItemType Directory -Path $contributePath -Force | Out-Null
            @{ name = $roleName } | ConvertTo-Json | Out-File (Join-Path $contributePath "role.json") -Encoding utf8

            $plan = @(New-PlanEntry -Roles @($roleName))

            $output = & $script:TestSkillCoverage -PlanParsed $plan -ProjectDir $script:projectDir *>&1
            $outputStr = $output -join "`n"

            $outputStr | Should -Not -Match "Role '$roleName' not found"
            $outputStr | Should -Not -Match "Auto-scaffolded.*$roleName"
            $outputStr | Should -Match "All required skills and roles verified"
        }

        It "does not scaffold a role that already exists in contributes/roles/" {
            $roleName = "no-scaffold-contrib-$script:testSuffix"
            # Track for cleanup — even though we don't expect scaffolding, guard it
            $script:createdRoles.Add($roleName)

            # Pre-create the role inside the project's contributes/roles/
            $contributePath = Join-Path $script:projectDir "contributes" "roles" $roleName
            New-Item -ItemType Directory -Path $contributePath -Force | Out-Null
            @{ name = $roleName; capabilities = @("security") } |
                ConvertTo-Json | Out-File (Join-Path $contributePath "role.json") -Encoding utf8

            $plan = @(New-PlanEntry -Roles @($roleName))

            & $script:TestSkillCoverage -PlanParsed $plan -ProjectDir $script:projectDir *>&1 | Out-Null

            # The role must NOT have been scaffolded to ~/.ostwin or ~/.config/opencode
            $ostwinPath = Join-Path $script:ostwinRolesDir $roleName
            Test-Path $ostwinPath | Should -BeFalse `
                -Because "contributed roles must not be auto-scaffolded to ~/.ostwin"

            $openCodeFile = Join-Path $script:openCodeAgentsDir "$roleName.md"
            Test-Path $openCodeFile | Should -BeFalse `
                -Because "contributed roles must not be auto-scaffolded to ~/.config/opencode"
        }

        It "reads skill_refs from contributes/roles/<role>/role.json for coverage check" {
            $roleName = "contrib-skill-role-$script:testSuffix"
            $skillName = "contrib-skill-$script:testSuffix"

            # Contributed role with a skill_ref
            $contributePath = Join-Path $script:projectDir "contributes" "roles" $roleName
            New-Item -ItemType Directory -Path $contributePath -Force | Out-Null
            @{ name = $roleName; skill_refs = @($skillName) } |
                ConvertTo-Json | Out-File (Join-Path $contributePath "role.json") -Encoding utf8

            # The skill is present in the project's skills directory
            $skillDir = Join-Path $script:agentsDir "skills" "global" $skillName
            New-Item -ItemType Directory -Path $skillDir -Force | Out-Null
            "# $skillName" | Out-File -FilePath (Join-Path $skillDir "SKILL.md") -Encoding utf8

            $plan = @(New-PlanEntry -Roles @($roleName))

            $output = & $script:TestSkillCoverage -PlanParsed $plan -ProjectDir $script:projectDir *>&1
            $outputStr = $output -join "`n"

            $outputStr | Should -Not -Match "Skill '$skillName'.*not found"
            $outputStr | Should -Match "All required skills and roles verified"
        }
    }

    Context "Role lookup in ~/.config/opencode/agents/" {
        It "finds a role via ~/.config/opencode/agents/<role>.md without scaffolding" {
            $roleName = "opencode-role-$script:testSuffix"
            $script:createdRoles.Add($roleName)

            # Pre-create the agent .md file
            New-Item -ItemType Directory -Path $script:openCodeAgentsDir -Force | Out-Null
            $agentFile = Join-Path $script:openCodeAgentsDir "$roleName.md"
            "---`nname: $roleName`n---`n# $roleName" | Out-File -FilePath $agentFile -Encoding utf8

            $plan = @(New-PlanEntry -Roles @($roleName))

            $output = & $script:TestSkillCoverage -PlanParsed $plan -ProjectDir $script:projectDir *>&1
            $outputStr = $output -join "`n"

            $outputStr | Should -Not -Match "Role '$roleName' not found"
            $outputStr | Should -Not -Match "Auto-scaffolded.*$roleName"
        }
    }

    # ═══════════════════════════════════════════════════════════════════════
    #  SKILL LOOKUP TESTS — search ladder must mirror Resolve-RoleSkills.ps1
    # ═══════════════════════════════════════════════════════════════════════

    Context "Skill lookup in project .agents/skills/" {
        It "finds a skill_ref under <project>/.agents/skills/global/<skill>/" {
            $roleName = "skill-local-global-$script:testSuffix"
            $skillName = "local-global-skill-$script:testSuffix"

            # Local role with one skill_ref
            $localRolePath = Join-Path $script:rolesDir $roleName
            New-Item -ItemType Directory -Path $localRolePath -Force | Out-Null
            @{ name = $roleName; skill_refs = @($skillName) } |
                ConvertTo-Json | Out-File (Join-Path $localRolePath "role.json") -Encoding utf8

            # Skill physically present under the project's global tree
            $skillDir = Join-Path $script:agentsDir "skills" "global" $skillName
            New-Item -ItemType Directory -Path $skillDir -Force | Out-Null
            "# $skillName" | Out-File -FilePath (Join-Path $skillDir "SKILL.md") -Encoding utf8

            $plan = @(New-PlanEntry -Roles @($roleName))

            $output = & $script:TestSkillCoverage -PlanParsed $plan -ProjectDir $script:projectDir *>&1
            $outputStr = $output -join "`n"

            $outputStr | Should -Not -Match "Skill '$skillName'.*not found"
            $outputStr | Should -Match "All required skills and roles verified"
        }
    }

    Context "Skill lookup in ~/.ostwin/.agents/skills/" {
        It "finds a skill_ref under ~/.ostwin/.agents/skills/global/<skill>/" {
            $roleName = "skill-home-global-$script:testSuffix"
            $skillName = "home-global-skill-$script:testSuffix"

            # Local role with one skill_ref
            $localRolePath = Join-Path $script:rolesDir $roleName
            New-Item -ItemType Directory -Path $localRolePath -Force | Out-Null
            @{ name = $roleName; skill_refs = @($skillName) } |
                ConvertTo-Json | Out-File (Join-Path $localRolePath "role.json") -Encoding utf8

            # Skill physically present under the user-global tree
            $skillDir = Join-Path $script:ostwinSkillsDir "global" $skillName
            New-Item -ItemType Directory -Path $skillDir -Force | Out-Null
            "# $skillName" | Out-File -FilePath (Join-Path $skillDir "SKILL.md") -Encoding utf8
            $script:createdHomeSkillDirs.Add($skillDir)

            $plan = @(New-PlanEntry -Roles @($roleName))

            $output = & $script:TestSkillCoverage -PlanParsed $plan -ProjectDir $script:projectDir *>&1
            $outputStr = $output -join "`n"

            $outputStr | Should -Not -Match "Skill '$skillName'.*not found"
            $outputStr | Should -Match "All required skills and roles verified"
        }

        It "finds a skill_ref under ~/.ostwin/.agents/skills/<skill>/ (flat)" {
            $roleName = "skill-home-flat-$script:testSuffix"
            $skillName = "home-flat-skill-$script:testSuffix"

            $localRolePath = Join-Path $script:rolesDir $roleName
            New-Item -ItemType Directory -Path $localRolePath -Force | Out-Null
            @{ name = $roleName; skill_refs = @($skillName) } |
                ConvertTo-Json | Out-File (Join-Path $localRolePath "role.json") -Encoding utf8

            $skillDir = Join-Path $script:ostwinSkillsDir $skillName
            New-Item -ItemType Directory -Path $skillDir -Force | Out-Null
            "# $skillName" | Out-File -FilePath (Join-Path $skillDir "SKILL.md") -Encoding utf8
            $script:createdHomeSkillDirs.Add($skillDir)

            $plan = @(New-PlanEntry -Roles @($roleName))

            $output = & $script:TestSkillCoverage -PlanParsed $plan -ProjectDir $script:projectDir *>&1
            $outputStr = $output -join "`n"

            $outputStr | Should -Not -Match "Skill '$skillName'.*not found"
        }

        It "finds a skill_ref under ~/.ostwin/.agents/skills/roles/<role>/<skill>/" {
            $roleName = "skill-home-role-$script:testSuffix"
            $skillName = "home-role-skill-$script:testSuffix"
            $hostRole = "host-role-$script:testSuffix"

            $localRolePath = Join-Path $script:rolesDir $roleName
            New-Item -ItemType Directory -Path $localRolePath -Force | Out-Null
            @{ name = $roleName; skill_refs = @($skillName) } |
                ConvertTo-Json | Out-File (Join-Path $localRolePath "role.json") -Encoding utf8

            $hostRoleSkillsDir = Join-Path $script:ostwinSkillsDir "roles" $hostRole
            $skillDir = Join-Path $hostRoleSkillsDir $skillName
            New-Item -ItemType Directory -Path $skillDir -Force | Out-Null
            "# $skillName" | Out-File -FilePath (Join-Path $skillDir "SKILL.md") -Encoding utf8
            # Track the host-role dir so cleanup removes the whole subtree
            $script:createdHomeSkillDirs.Add($hostRoleSkillsDir)

            $plan = @(New-PlanEntry -Roles @($roleName))

            $output = & $script:TestSkillCoverage -PlanParsed $plan -ProjectDir $script:projectDir *>&1
            $outputStr = $output -join "`n"

            $outputStr | Should -Not -Match "Skill '$skillName'.*not found"
        }

        It "still warns when a skill_ref is missing from both project and home trees" {
            $roleName = "skill-missing-$script:testSuffix"
            $skillName = "definitely-not-installed-$script:testSuffix"

            $localRolePath = Join-Path $script:rolesDir $roleName
            New-Item -ItemType Directory -Path $localRolePath -Force | Out-Null
            @{ name = $roleName; skill_refs = @($skillName) } |
                ConvertTo-Json | Out-File (Join-Path $localRolePath "role.json") -Encoding utf8

            $plan = @(New-PlanEntry -Roles @($roleName))

            $output = & $script:TestSkillCoverage -PlanParsed $plan -ProjectDir $script:projectDir *>&1
            $outputStr = $output -join "`n"

            $outputStr | Should -Match "Skill '$skillName' required by role '$roleName' not found"
        }
    }

    # ═══════════════════════════════════════════════════════════════════════
    #  SCAFFOLDING TESTS
    # ═══════════════════════════════════════════════════════════════════════

    Context "Auto-scaffold to ~/.ostwin/.agents/roles/" {
        It "creates role directory with role.json at ~/.ostwin/.agents/roles/<role>/" {
            $roleName = "scaffold-ostwin-$script:testSuffix"
            $script:createdRoles.Add($roleName)

            $plan = @(New-PlanEntry -Roles @($roleName) -Objective "Test scaffold objective")

            & $script:TestSkillCoverage -PlanParsed $plan -ProjectDir $script:projectDir *>&1 | Out-Null

            $scaffoldPath = Join-Path $script:ostwinRolesDir $roleName
            Test-Path $scaffoldPath | Should -BeTrue -Because "role directory should be created at ~/.ostwin/.agents/roles/"

            $roleJsonPath = Join-Path $scaffoldPath "role.json"
            Test-Path $roleJsonPath | Should -BeTrue -Because "role.json should be created"

            $roleJson = Get-Content $roleJsonPath -Raw | ConvertFrom-Json
            $roleJson.name | Should -Be $roleName
            $roleJson.description | Should -Be "Test scaffold objective"
            $roleJson.cli | Should -Be "agent"
            $roleJson.prompt_file | Should -Be "ROLE.md"
        }

        It "creates ROLE.md at ~/.ostwin/.agents/roles/<role>/" {
            $roleName = "scaffold-rolemd-$script:testSuffix"
            $script:createdRoles.Add($roleName)

            $plan = @(New-PlanEntry -Roles @($roleName) -Objective "Role MD test")

            & $script:TestSkillCoverage -PlanParsed $plan -ProjectDir $script:projectDir *>&1 | Out-Null

            $roleMdPath = Join-Path $script:ostwinRolesDir $roleName "ROLE.md"
            Test-Path $roleMdPath | Should -BeTrue -Because "ROLE.md should be created"

            $content = Get-Content $roleMdPath -Raw
            $content | Should -Match "# $roleName"
            $content | Should -Match "You are a \*\*$roleName\*\* specialist agent"
            $content | Should -Match "Role MD test"
        }
    }

    Context "Auto-scaffold to ~/.config/opencode/agents/" {
        It "creates <role>.md at ~/.config/opencode/agents/" {
            $roleName = "scaffold-opencode-$script:testSuffix"
            $script:createdRoles.Add($roleName)

            $plan = @(New-PlanEntry -Roles @($roleName) -Objective "OpenCode agent test")

            & $script:TestSkillCoverage -PlanParsed $plan -ProjectDir $script:projectDir *>&1 | Out-Null

            $agentFile = Join-Path $script:openCodeAgentsDir "$roleName.md"
            Test-Path $agentFile | Should -BeTrue -Because "<role>.md should be created at ~/.config/opencode/agents/"

            $content = Get-Content $agentFile -Raw
            $content | Should -Match "^---"
            $content | Should -Match "name: $roleName"
            $content | Should -Match "description: OpenCode agent test"
            $content | Should -Match "model: google-vertex/gemini-3-flash-preview"
            $content | Should -Match "# $roleName"
        }

        It "scaffolds to both locations simultaneously" {
            $roleName = "scaffold-both-$script:testSuffix"
            $script:createdRoles.Add($roleName)

            $plan = @(New-PlanEntry -Roles @($roleName) -Objective "Dual scaffold")

            $output = & $script:TestSkillCoverage -PlanParsed $plan -ProjectDir $script:projectDir *>&1
            $outputStr = $output -join "`n"

            # Verify both locations exist
            $ostwinPath = Join-Path $script:ostwinRolesDir $roleName
            Test-Path $ostwinPath | Should -BeTrue -Because "~/.ostwin path should exist"

            $openCodeFile = Join-Path $script:openCodeAgentsDir "$roleName.md"
            Test-Path $openCodeFile | Should -BeTrue -Because "~/.config/opencode path should exist"

            # Verify scaffold message
            $outputStr | Should -Match "Auto-scaffolded.*$roleName.*~/.ostwin.*~/.config/opencode"
        }
    }

    Context "Scaffold uses plan entry description" {
        It "uses Objective as description when available" {
            $roleName = "desc-objective-$script:testSuffix"
            $script:createdRoles.Add($roleName)

            $plan = @(New-PlanEntry -Roles @($roleName) -Objective "Build the auth system")

            & $script:TestSkillCoverage -PlanParsed $plan -ProjectDir $script:projectDir *>&1 | Out-Null

            $roleJson = Get-Content (Join-Path $script:ostwinRolesDir $roleName "role.json") -Raw | ConvertFrom-Json
            $roleJson.description | Should -Be "Build the auth system"

            $agentMd = Get-Content (Join-Path $script:openCodeAgentsDir "$roleName.md") -Raw
            $agentMd | Should -Match "description: Build the auth system"
        }

        It "falls back to default description when no Objective or Description" {
            $roleName = "desc-default-$script:testSuffix"
            $script:createdRoles.Add($roleName)

            $plan = @([PSCustomObject]@{
                TaskRef     = "EPIC-001"
                Roles       = @($roleName)
                Objective   = ""
                Description = ""
            })

            & $script:TestSkillCoverage -PlanParsed $plan -ProjectDir $script:projectDir *>&1 | Out-Null

            $roleJson = Get-Content (Join-Path $script:ostwinRolesDir $roleName "role.json") -Raw | ConvertFrom-Json
            $roleJson.description | Should -Be "$roleName specialist agent"
        }
    }

    Context "Deduplication across epics" {
        It "scaffolds a role only once when referenced by multiple epics" {
            $roleName = "dedup-role-$script:testSuffix"
            $script:createdRoles.Add($roleName)

            $plan = @(
                New-PlanEntry -TaskRef "EPIC-001" -Roles @($roleName) -Objective "First epic"
                New-PlanEntry -TaskRef "EPIC-002" -Roles @($roleName) -Objective "Second epic"
                New-PlanEntry -TaskRef "EPIC-003" -Roles @($roleName) -Objective "Third epic"
            )

            $output = & $script:TestSkillCoverage -PlanParsed $plan -ProjectDir $script:projectDir *>&1
            $outputStr = $output -join "`n"

            # Should report scaffolding count as 1
            $outputStr | Should -Match "Scaffolded 1 dynamic role"
        }
    }

    Context "Registry registration" {
        It "registers scaffolded role in project registry.json" {
            $roleName = "registry-role-$script:testSuffix"
            $script:createdRoles.Add($roleName)

            $plan = @(New-PlanEntry -Roles @($roleName) -Objective "Registry test")

            & $script:TestSkillCoverage -PlanParsed $plan -ProjectDir $script:projectDir *>&1 | Out-Null

            $registry = Get-Content $script:registryPath -Raw | ConvertFrom-Json
            $registered = $registry.roles | Where-Object { $_.name -eq $roleName }

            $registered | Should -Not -BeNullOrEmpty -Because "role should be registered in registry.json"
            $registered.name | Should -Be $roleName
            $registered.description | Should -Be "Registry test"
            $registered.runner | Should -Be "roles/_base/Start-DynamicRole.ps1"
        }

        It "does not duplicate registry entry when role already registered" {
            $roleName = "nodup-registry-$script:testSuffix"
            $script:createdRoles.Add($roleName)

            # Pre-register the role
            $registry = @{
                roles = @(
                    @{
                        name        = $roleName
                        description = "Already registered"
                        runner      = "roles/_base/Start-DynamicRole.ps1"
                    }
                )
            }
            $registry | ConvertTo-Json -Depth 5 | Out-File -FilePath $script:registryPath -Encoding utf8

            $plan = @(New-PlanEntry -Roles @($roleName) -Objective "Should not duplicate")

            & $script:TestSkillCoverage -PlanParsed $plan -ProjectDir $script:projectDir *>&1 | Out-Null

            $updated = Get-Content $script:registryPath -Raw | ConvertFrom-Json
            $matches = @($updated.roles | Where-Object { $_.name -eq $roleName })
            $matches.Count | Should -Be 1 -Because "should not create duplicate registry entry"
            # Original description should be preserved
            $matches[0].description | Should -Be "Already registered"
        }
    }

    Context "Preflight mode" {
        It "skips entirely when mode is 'off'" {
            function global:Get-OstwinConfig {
                return [PSCustomObject]@{
                    manager = [PSCustomObject]@{
                        preflight_skill_check = "off"
                    }
                }
            }

            $roleName = "off-mode-$script:testSuffix"
            $plan = @(New-PlanEntry -Roles @($roleName))

            $output = & $script:TestSkillCoverage -PlanParsed $plan -ProjectDir $script:projectDir *>&1
            $outputStr = $output -join "`n"

            $outputStr | Should -Not -Match "Checking skill coverage"

            # Should NOT scaffold anything
            $ostwinPath = Join-Path $script:ostwinRolesDir $roleName
            Test-Path $ostwinPath | Should -BeFalse

            # Restore default mock
            function global:Get-OstwinConfig {
                return [PSCustomObject]@{
                    manager = [PSCustomObject]@{
                        preflight_skill_check = "warn"
                    }
                }
            }
        }
    }
}
