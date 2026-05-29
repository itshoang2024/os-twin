Describe "Resolve-RoleSkills" {
    BeforeAll {
        $script:resolveScript = Join-Path (Resolve-Path "$PSScriptRoot/../../../roles/_base").Path "Resolve-RoleSkills.ps1"
        $script:baseDir = Join-Path (Resolve-Path "$PSScriptRoot/../../../roles/_base").Path "test_skills"
        $script:testRolePath = Join-Path (Resolve-Path "$PSScriptRoot/../../../roles/_base").Path "test_role"
        $script:origHome = $env:HOME
        $script:fakeHome = Join-Path (Resolve-Path "$PSScriptRoot/../../../roles/_base").Path "test_fakehome"

        function script:New-TestRoom {
            param([string]$BriefContent = "", [string]$TasksContent = "", [string]$PlanId = "")
            $roomDir = Join-Path $TestDrive "room-$(Get-Random)"
            New-Item -ItemType Directory -Path $roomDir -Force | Out-Null
            if ($BriefContent) { $BriefContent | Out-File (Join-Path $roomDir "brief.md") -Encoding utf8 }
            if ($TasksContent) { $TasksContent | Out-File (Join-Path $roomDir "TASKS.md") -Encoding utf8 }
            if ($PlanId) {
                @{ plan_id = $PlanId; task_ref = "T1" } | ConvertTo-Json | Out-File (Join-Path $roomDir "config.json") -Encoding utf8
            }
            return $roomDir
        }

        function script:New-TestSkill {
            param([string]$Name, [string]$Location = "flat", [string]$Content = "# $Name skill", [string]$Frontmatter = "")
            $dir = switch ($Location) {
                "flat"   { Join-Path $script:baseDir $Name }
                "global" { Join-Path $script:baseDir "global" $Name }
                default  { Join-Path $script:baseDir $Location $Name }
            }
            New-Item -ItemType Directory -Path $dir -Force | Out-Null
            $full = if ($Frontmatter) { "$Frontmatter`n$Content" } else { $Content }
            $full | Out-File (Join-Path $dir "SKILL.md") -Encoding utf8
            return $dir
        }

        function script:New-PlanRoles {
            param([string]$PlanId, [hashtable]$Roles)
            $plansDir = Join-Path $script:fakeHome ".ostwin" ".agents" "plans"
            New-Item -ItemType Directory -Path $plansDir -Force | Out-Null
            $Roles | ConvertTo-Json -Depth 5 | Out-File (Join-Path $plansDir "$PlanId.roles.json") -Encoding utf8
        }
    }

    BeforeEach {
        if (Test-Path $script:baseDir) { Remove-Item $script:baseDir -Recurse -Force }
        if (Test-Path $script:fakeHome) { Remove-Item $script:fakeHome -Recurse -Force }
        if (Test-Path $script:testRolePath) { Remove-Item $script:testRolePath -Recurse -Force }
        New-Item -ItemType Directory -Path $script:baseDir -Force | Out-Null
        New-Item -ItemType Directory -Path $script:testRolePath -Force | Out-Null
        $env:HOME = $script:fakeHome
        $script:origApiKey = $env:OSTWIN_API_KEY
        $env:OSTWIN_API_KEY = ''
    }

    AfterEach { $env:OSTWIN_API_KEY = $script:origApiKey }

    AfterAll {
        $env:HOME = $script:origHome
        foreach ($p in @($script:baseDir, $script:testRolePath, $script:fakeHome)) {
            if (Test-Path $p) { Remove-Item $p -Recurse -Force }
        }
    }

    # === PHASE 1: PLAN-ROLES.JSON (Source 1) ===
    Context "Skill refs from plan-roles.json" {
        It "resolves skills from plan-roles config" {
            New-TestSkill -Name "brain-ops" -Location "flat"
            New-TestSkill -Name "war-room-communication" -Location "flat"
            New-PlanRoles -PlanId "plan-abc" -Roles @{
                engineer = @{ skill_refs = @("brain-ops", "war-room-communication") }
            }
            $roomDir = New-TestRoom -PlanId "plan-abc"

            $skills = & $script:resolveScript -RoleName "engineer" -RolePath $script:testRolePath `
                -SkillsBaseDir $script:baseDir -RoomDir $roomDir

            $skills.Count | Should -Be 2
            ($skills | Where-Object { $_.Name -eq "brain-ops" }) | Should -Not -BeNullOrEmpty
        }

        It "handles missing plan_id gracefully" {
            $roomDir = New-TestRoom
            $skills = & $script:resolveScript -RoleName "engineer" -RolePath $script:testRolePath `
                -SkillsBaseDir $script:baseDir -RoomDir $roomDir
            $skills.Count | Should -Be 0
        }

        It "handles role not present in plan config" {
            New-PlanRoles -PlanId "plan-xyz" -Roles @{ qa = @{ skill_refs = @("review-task") } }
            $roomDir = New-TestRoom -PlanId "plan-xyz"

            $skills = & $script:resolveScript -RoleName "engineer" -RolePath $script:testRolePath `
                -SkillsBaseDir $script:baseDir -RoomDir $roomDir
            $skills.Count | Should -Be 0
        }

        It "uses explicit PlanId parameter over room config" {
            New-TestSkill -Name "explicit-skill" -Location "flat"
            New-PlanRoles -PlanId "plan-explicit" -Roles @{
                engineer = @{ skill_refs = @("explicit-skill") }
            }
            New-PlanRoles -PlanId "plan-room" -Roles @{
                engineer = @{ skill_refs = @("room-skill") }
            }
            $roomDir = New-TestRoom -PlanId "plan-room"

            $skills = & $script:resolveScript -RoleName "engineer" -RolePath $script:testRolePath `
                -SkillsBaseDir $script:baseDir -RoomDir $roomDir -PlanId "plan-explicit"

            $skills.Count | Should -Be 1
            $skills[0].Name | Should -Be "explicit-skill"
        }
    }

    # === PHASE 1: HOME ROLE.JSON (Source 2) ===
    Context "Skill refs from HOME role.json fallback" {
        It "falls back to HOME role.json when plan has no skill_refs" {
            New-TestSkill -Name "auto-memory" -Location "global"
            $homeRoleDir = Join-Path $script:fakeHome ".ostwin" "roles" "engineer"
            New-Item -ItemType Directory -Path $homeRoleDir -Force | Out-Null
            @{ name = "engineer"; skill_refs = @("auto-memory") } |
                ConvertTo-Json | Out-File (Join-Path $homeRoleDir "role.json") -Encoding utf8

            $roomDir = New-TestRoom
            $skills = & $script:resolveScript -RoleName "engineer" -RolePath $script:testRolePath `
                -SkillsBaseDir $script:baseDir -RoomDir $roomDir
            $skills.Count | Should -Be 1
            $skills[0].Name | Should -Be "auto-memory"
        }

        It "plan-roles takes priority over HOME role.json" {
            New-TestSkill -Name "plan-skill" -Location "flat"
            New-TestSkill -Name "home-skill" -Location "flat"
            New-PlanRoles -PlanId "plan-pri" -Roles @{
                engineer = @{ skill_refs = @("plan-skill") }
            }
            $homeRoleDir = Join-Path $script:fakeHome ".ostwin" "roles" "engineer"
            New-Item -ItemType Directory -Path $homeRoleDir -Force | Out-Null
            @{ skill_refs = @("home-skill") } | ConvertTo-Json | Out-File (Join-Path $homeRoleDir "role.json") -Encoding utf8

            $roomDir = New-TestRoom -PlanId "plan-pri"
            $skills = & $script:resolveScript -RoleName "engineer" -RolePath $script:testRolePath `
                -SkillsBaseDir $script:baseDir -RoomDir $roomDir

            $skills.Count | Should -Be 1
            $skills[0].Name | Should -Be "plan-skill"
        }
    }

    # === PHASE 1: LOCAL ROLE.JSON (Source 3) ===
    Context "Skill refs from local role.json fallback" {
        It "falls back to local role.json when HOME has no skill_refs" {
            New-TestSkill -Name "critical-thinking" -Location "flat"
            $roleDir = Join-Path (Split-Path $script:resolveScript -Parent) ".." "test-role-fb"
            New-Item -ItemType Directory -Path $roleDir -Force | Out-Null
            @{ skill_refs = @("critical-thinking") } | ConvertTo-Json | Out-File (Join-Path $roleDir "role.json") -Encoding utf8

            $roomDir = New-TestRoom
            $skills = & $script:resolveScript -RoleName "test-role-fb" -RolePath $script:testRolePath `
                -SkillsBaseDir $script:baseDir -RoomDir $roomDir

            $skills.Count | Should -Be 1
            $skills[0].Name | Should -Be "critical-thinking"
            Remove-Item $roleDir -Recurse -Force -ErrorAction SilentlyContinue
        }
    }

    # === EMPTY / NO SKILL REFS ===
    Context "Returns empty when no skill_refs anywhere" {
        It "returns empty when no RoomDir and no role.json" {
            $skills = & $script:resolveScript -RoleName "engineer" -RolePath $script:testRolePath -SkillsBaseDir $script:baseDir
            $skills.Count | Should -Be 0
        }

        It "returns empty when skills base dir does not exist" {
            $roomDir = New-TestRoom
            $skills = & $script:resolveScript -RoleName "engineer" -RolePath $script:testRolePath `
                -SkillsBaseDir "/nonexistent/path" -RoomDir $roomDir
            $skills.Count | Should -Be 0
        }
    }

    # === PHASE 2a: LOCAL TASK-AWARE DISCOVERY (no API needed) ===
    Context "Local task-aware discovery (Phase 2a)" {
        It "discovers local skills by matching TASKS.md keywords against SKILL.md frontmatter" {
            $fm = "---`nname: write-tests`ndescription: Write unit and integration tests for quality gates`ntags: [engineer, testing, quality-assurance]`n---"
            New-TestSkill -Name "write-tests" -Location "flat" -Frontmatter $fm
            $roomDir = New-TestRoom -BriefContent "Implement authentication system" `
                -TasksContent "- [ ] Write unit tests for login`n- [ ] Add integration tests for OAuth2"

            $skills = & $script:resolveScript -RoleName "engineer" -RolePath $script:testRolePath `
                -SkillsBaseDir $script:baseDir -RoomDir $roomDir

            ($skills | Where-Object { $_.Name -eq "write-tests" }) | Should -Not -BeNullOrEmpty
        }

        It "discovers skills by matching skill directory name to task content" {
            $fm = "---`nname: code-review`ndescription: Review code for quality and correctness`n---"
            New-TestSkill -Name "code-review" -Location "flat" -Frontmatter $fm
            $roomDir = New-TestRoom -BriefContent "Complete the code review for the authentication module"

            $skills = & $script:resolveScript -RoleName "engineer" -RolePath $script:testRolePath `
                -SkillsBaseDir $script:baseDir -RoomDir $roomDir

            ($skills | Where-Object { $_.Name -eq "code-review" }) | Should -Not -BeNullOrEmpty
        }

        It "does not duplicate skills already in Phase 1 refs" {
            $fm = "---`nname: brain-ops`ndescription: Dual-layer context system for team operations`n---"
            New-TestSkill -Name "brain-ops" -Location "flat" -Frontmatter $fm
            New-PlanRoles -PlanId "plan-dedup2a" -Roles @{ engineer = @{ skill_refs = @("brain-ops") } }
            $roomDir = New-TestRoom -PlanId "plan-dedup2a" -BriefContent "Set up brain-ops and team context for the project"

            $skills = & $script:resolveScript -RoleName "engineer" -RolePath $script:testRolePath `
                -SkillsBaseDir $script:baseDir -RoomDir $roomDir

            ($skills | Where-Object { $_.Name -eq "brain-ops" }).Count | Should -Be 1
        }

        It "skips skills with no keyword overlap to task content" {
            $fm = "---`nname: overdrive`ndescription: Pushes interfaces past conventional limits with shaders and spring physics`n---"
            New-TestSkill -Name "overdrive" -Location "flat" -Frontmatter $fm
            $roomDir = New-TestRoom -BriefContent "Build a database migration system with schema versioning and rollback support"

            $skills = & $script:resolveScript -RoleName "engineer" -RolePath $script:testRolePath `
                -SkillsBaseDir $script:baseDir -RoomDir $roomDir

            ($skills | Where-Object { $_.Name -eq "overdrive" }) | Should -BeNullOrEmpty
        }

        It "skips discovery when task content is too short" {
            $fm = "---`nname: write-tests`ndescription: Write unit and integration tests`n---"
            New-TestSkill -Name "write-tests" -Location "flat" -Frontmatter $fm
            $roomDir = New-TestRoom -BriefContent "short"

            $skills = & $script:resolveScript -RoleName "engineer" -RolePath $script:testRolePath `
                -SkillsBaseDir $script:baseDir -RoomDir $roomDir

            $skills.Count | Should -Be 0
        }

        It "respects enabled gate on locally discovered skills" {
            $fm = "---`nname: disabled-review`nenabled: false`ndescription: Disabled code review skill for testing`n---"
            New-TestSkill -Name "disabled-review" -Location "flat" -Frontmatter $fm
            $roomDir = New-TestRoom -BriefContent "Run the disabled-review on the codebase for quality assurance"

            $skills = & $script:resolveScript -RoleName "engineer" -RolePath $script:testRolePath `
                -SkillsBaseDir $script:baseDir -RoomDir $roomDir

            ($skills | Where-Object { $_.Name -eq "disabled-review" }) | Should -BeNullOrEmpty
        }

        It "discovers skills from global directory" {
            $fm = "---`nname: brain-ops`ndescription: Dual-layer context system for team operations and knowledge`n---"
            New-TestSkill -Name "brain-ops" -Location "global" -Frontmatter $fm
            $roomDir = New-TestRoom -BriefContent "Set up team brain-ops context and knowledge system for operations"

            $skills = & $script:resolveScript -RoleName "engineer" -RolePath $script:testRolePath `
                -SkillsBaseDir $script:baseDir -RoomDir $roomDir

            ($skills | Where-Object { $_.Name -eq "brain-ops" }) | Should -Not -BeNullOrEmpty
        }

        It "limits discovery to 5 additional skills" {
            $skillNames = @("auth-review", "auth-tests", "auth-security", "auth-audit", "auth-hardening", "auth-logging")
            foreach ($sn in $skillNames) {
                $fm2 = "---`nname: $sn`ndescription: Authentication $sn for security and quality`n---"
                New-TestSkill -Name $sn -Location "flat" -Frontmatter $fm2
            }
            $roomDir = New-TestRoom -BriefContent "Review authentication security, write tests, audit, harden, and add logging for the auth system"

            $skills = & $script:resolveScript -RoleName "engineer" -RolePath $script:testRolePath `
                -SkillsBaseDir $script:baseDir -RoomDir $roomDir

            $skills.Count | Should -BeLessOrEqual 5
        }
    }

    # === PHASE 2b: TASK-AWARE API SEARCH ===
    Context "Task-aware API search (Phase 2b — requires ApiKey)" {
        BeforeAll {
            Mock Invoke-RestMethod {
                return @(
                    [PSCustomObject]@{ name = "discovered-a"; relative_path = "skills/roles/engineer/discovered-a"; content = "# A"; description = "A" },
                    [PSCustomObject]@{ name = "discovered-b"; relative_path = "skills/roles/engineer/discovered-b"; content = "# B"; description = "B" }
                )
            }
        }

        It "discovers skills from brief.md + TASKS.md content" {
            New-TestSkill -Name "discovered-a" -Location "flat"
            New-TestSkill -Name "discovered-b" -Location "flat"
            $roomDir = New-TestRoom -BriefContent "Build a comprehensive authentication system with OAuth2 and JWT tokens for the platform" `
                -TasksContent "- [ ] Implement login flow`n- [ ] Add token refresh"

            $skills = & $script:resolveScript -RoleName "engineer" -RolePath $script:testRolePath `
                -SkillsBaseDir $script:baseDir -RoomDir $roomDir -ApiKey "test-key"

            $skills.Count | Should -BeGreaterOrEqual 1
        }

        It "merges Phase 2 results with Phase 1 refs without duplicates" {
            New-TestSkill -Name "brain-ops" -Location "flat"
            New-TestSkill -Name "discovered-a" -Location "flat"
            New-PlanRoles -PlanId "plan-merge" -Roles @{
                engineer = @{ skill_refs = @("brain-ops") }
            }
            $roomDir = New-TestRoom -PlanId "plan-merge" `
                -BriefContent "Build a comprehensive authentication system with OAuth2 and JWT tokens for the platform"

            $skills = & $script:resolveScript -RoleName "engineer" -RolePath $script:testRolePath `
                -SkillsBaseDir $script:baseDir -RoomDir $roomDir -ApiKey "test-key"

            ($skills | Where-Object { $_.Name -eq "brain-ops" }) | Should -Not -BeNullOrEmpty
            # Phase 2 adds new refs
            $skills.Count | Should -BeGreaterThan 1
        }

        It "skips search when no ApiKey" {
            $roomDir = New-TestRoom -BriefContent "Build a comprehensive authentication system with OAuth2 and JWT tokens for the platform"
            $skills = & $script:resolveScript -RoleName "engineer" -RolePath $script:testRolePath `
                -SkillsBaseDir $script:baseDir -RoomDir $roomDir
            $skills.Count | Should -Be 0
        }

        It "skips search when brief content too short" {
            $roomDir = New-TestRoom -BriefContent "short"
            $skills = & $script:resolveScript -RoleName "engineer" -RolePath $script:testRolePath `
                -SkillsBaseDir $script:baseDir -RoomDir $roomDir -ApiKey "test-key"
            $skills.Count | Should -Be 0
        }
    }

    # === LOCAL RESOLUTION HIERARCHY ===
    Context "Hierarchical resolution: flat path" {
        It "resolves from flat skills/<ref>/SKILL.md" {
            New-TestSkill -Name "lang" -Location "flat"
            New-PlanRoles -PlanId "p1" -Roles @{ engineer = @{ skill_refs = @("lang") } }
            $roomDir = New-TestRoom -PlanId "p1"
            $skills = & $script:resolveScript -RoleName "engineer" -RolePath $script:testRolePath `
                -SkillsBaseDir $script:baseDir -RoomDir $roomDir
            $skills.Count | Should -Be 1
            $skills[0].Tier | Should -Be "Explicit"
        }
    }

    Context "Hierarchical resolution: own-role path" {
        It "resolves from skills/roles/<role>/<ref>/SKILL.md" {
            New-TestSkill -Name "build-ui" -Location "roles/game-engineer"
            New-PlanRoles -PlanId "p2" -Roles @{ "game-engineer" = @{ skill_refs = @("build-ui") } }
            $roomDir = New-TestRoom -PlanId "p2"
            $skills = & $script:resolveScript -RoleName "game-engineer" -RolePath $script:testRolePath `
                -SkillsBaseDir $script:baseDir -RoomDir $roomDir
            ($skills | Where-Object { $_.Name -eq "build-ui" }) | Should -Not -BeNullOrEmpty
        }
    }

    Context "Hierarchical resolution: global path" {
        It "resolves from skills/global/<ref>/SKILL.md" {
            New-TestSkill -Name "auto-memory" -Location "global"
            New-PlanRoles -PlanId "p3" -Roles @{ engineer = @{ skill_refs = @("auto-memory") } }
            $roomDir = New-TestRoom -PlanId "p3"
            $skills = & $script:resolveScript -RoleName "engineer" -RolePath $script:testRolePath `
                -SkillsBaseDir $script:baseDir -RoomDir $roomDir
            ($skills | Where-Object { $_.Name -eq "auto-memory" }) | Should -Not -BeNullOrEmpty
        }
    }

    Context "Hierarchical resolution: own-role priority" {
        It "prefers own role's skill directory over other roles" {
            New-TestSkill -Name "review-skill" -Location "roles/engineer" -Content "Engineer version"
            New-TestSkill -Name "review-skill" -Location "roles/qa" -Content "QA version"
            New-PlanRoles -PlanId "p4" -Roles @{ engineer = @{ skill_refs = @("review-skill") } }
            $roomDir = New-TestRoom -PlanId "p4"
            $skills = & $script:resolveScript -RoleName "engineer" -RolePath $script:testRolePath `
                -SkillsBaseDir $script:baseDir -RoomDir $roomDir
            $resolved = $skills | Where-Object { $_.Name -eq "review-skill" }
            $resolved.Path | Should -Match "roles[\\/]engineer[\\/]review-skill"
        }
    }

    # === PLATFORM & ENABLED GATES ===
    Context "Platform gate" {
        It "skips platform-incompatible skills" {
            $fm = "---`nname: win-only`nplatform: [`"windows`"]`n---"
            New-TestSkill -Name "win-only" -Location "flat" -Frontmatter $fm
            New-PlanRoles -PlanId "p5" -Roles @{ engineer = @{ skill_refs = @("win-only") } }
            $roomDir = New-TestRoom -PlanId "p5"
            $skills = & $script:resolveScript -RoleName "engineer" -RolePath $script:testRolePath `
                -SkillsBaseDir $script:baseDir -RoomDir $roomDir
            if (-not $IsWindows) { $skills.Count | Should -Be 0 }
        }
    }

    Context "Enabled gate" {
        It "skips disabled skills" {
            $fm = "---`nname: disabled-skill`nenabled: false`n---"
            New-TestSkill -Name "disabled-skill" -Location "flat" -Frontmatter $fm
            New-PlanRoles -PlanId "p6" -Roles @{ engineer = @{ skill_refs = @("disabled-skill") } }
            $roomDir = New-TestRoom -PlanId "p6"
            $skills = & $script:resolveScript -RoleName "engineer" -RolePath $script:testRolePath `
                -SkillsBaseDir $script:baseDir -RoomDir $roomDir
            ($skills | Where-Object { $_.Name -eq "disabled-skill" }) | Should -BeNullOrEmpty
        }
    }

    # === DEDUPLICATION ===
    Context "Deduplication" {
        It "deduplicates when skill_refs has the same name twice" {
            New-TestSkill -Name "lang" -Location "flat"
            New-PlanRoles -PlanId "p7" -Roles @{ engineer = @{ skill_refs = @("lang", "lang") } }
            $roomDir = New-TestRoom -PlanId "p7"
            $skills = & $script:resolveScript -RoleName "engineer" -RolePath $script:testRolePath `
                -SkillsBaseDir $script:baseDir -RoomDir $roomDir
            $skills.Count | Should -Be 1
        }
    }

    # === GRACEFUL ERROR HANDLING ===
    Context "Error handling — never throws" {
        It "skips gracefully when skill ref is not found locally" {
            New-PlanRoles -PlanId "p8" -Roles @{ engineer = @{ skill_refs = @("non-existent") } }
            $roomDir = New-TestRoom -PlanId "p8"
            $skills = & $script:resolveScript -RoleName "engineer" -RolePath $script:testRolePath `
                -SkillsBaseDir $script:baseDir -RoomDir $roomDir
            $skills.Count | Should -Be 0
        }
    }

    Context "Partial resolution" {
        It "resolves found skills even when some are missing" {
            New-TestSkill -Name "lang" -Location "flat"
            New-PlanRoles -PlanId "p9" -Roles @{ engineer = @{ skill_refs = @("lang", "missing-one") } }
            $roomDir = New-TestRoom -PlanId "p9"
            $skills = & $script:resolveScript -RoleName "engineer" -RolePath $script:testRolePath `
                -SkillsBaseDir $script:baseDir -RoomDir $roomDir
            $skills.Count | Should -Be 1
            $skills[0].Name | Should -Be "lang"
        }
    }

    # === BACKEND FETCH (Strategy 3) ===
    Context "Backend fetch for skills not found locally" {
        BeforeAll {
            Mock Invoke-RestMethod {
                return @([PSCustomObject]@{
                    name = "remote-skill"; description = "A remote skill"
                    relative_path = "skills/roles/engineer/remote-skill"
                    content = "# Remote Skill`nDoes remote things."
                })
            }
        }

        It "downloads and writes skill from backend API response" {
            New-PlanRoles -PlanId "p10" -Roles @{ engineer = @{ skill_refs = @("remote-skill") } }
            $roomDir = New-TestRoom -PlanId "p10"
            $env:OSTWIN_API_KEY = "test-key-123"
            $skills = & $script:resolveScript -RoleName "engineer" -RolePath $script:testRolePath `
                -SkillsBaseDir $script:baseDir -RoomDir $roomDir `
                -DashboardUrl "http://mocked:3366" -ApiKey "test-key-123"
            $skills.Count | Should -Be 1
            $skills[0].Tier | Should -Be "Backend"
            Test-Path $skills[0].Path | Should -BeTrue
        }
    }

    # === INSTANCE SUFFIX HANDLING ===
    Context "Instance suffix (role:variant) handling" {
        It "strips instance suffix when resolving plan-roles config" {
            New-TestSkill -Name "build-ui" -Location "roles/game-engineer"
            New-PlanRoles -PlanId "p11" -Roles @{ "game-engineer" = @{ skill_refs = @("build-ui") } }
            $roomDir = New-TestRoom -PlanId "p11"
            $skills = & $script:resolveScript -RoleName "game-engineer:ui" -RolePath $script:testRolePath `
                -SkillsBaseDir $script:baseDir -RoomDir $roomDir
            ($skills | Where-Object { $_.Name -eq "build-ui" }) | Should -Not -BeNullOrEmpty
        }
    }

    # === PHASE 2.5: LEGAL GUARDRAIL EXPANSION ===
    Context "Phase 2.5: Legal guardrail expansion" {

        It "adds legal-common and source-document-intake for a legal NDA PDF task" {
            New-TestSkill -Name "legal-nda-triage" -Location "global" `
                -Frontmatter "---`nname: legal-nda-triage`ndescription: NDA triage and risk analysis for legal review`ntags: [legal, nda, contracts]`n---"
            New-TestSkill -Name "legal-common" -Location "global" `
                -Frontmatter "---`nname: legal-common`ndescription: Shared legal workflow guardrails and attorney-review gate`n---"
            New-TestSkill -Name "source-document-intake" -Location "global" `
                -Frontmatter "---`nname: source-document-intake`ndescription: Source document extraction, provenance, and citation discipline`n---"
            New-PlanRoles -PlanId "legal-p1" -Roles @{ audit = @{ skill_refs = @("legal-nda-triage") } }
            $roomDir = New-TestRoom `
                -BriefContent "Review the uploaded NDA PDF for business and legal risks." `
                -TasksContent "Summarize key clauses and escalation issues." `
                -PlanId "legal-p1"

            $skills = & $script:resolveScript -RoleName "audit" -RolePath $script:testRolePath `
                -SkillsBaseDir $script:baseDir -RoomDir $roomDir

            $names = $skills.Name
            $names | Should -Contain "legal-common"
            $names | Should -Contain "source-document-intake"
            $names | Should -Contain "legal-nda-triage"
        }

        It "adds legal-common and source-document-intake for a vendor contract DOCX task" {
            New-TestSkill -Name "legal-contract-review" -Location "global" `
                -Frontmatter "---`nname: legal-contract-review`ndescription: Contract review and clause risk analysis for legal counsel`ntags: [legal, contracts, review]`n---"
            New-TestSkill -Name "legal-common" -Location "global" `
                -Frontmatter "---`nname: legal-common`ndescription: Shared legal workflow guardrails and attorney-review gate`n---"
            New-TestSkill -Name "source-document-intake" -Location "global" `
                -Frontmatter "---`nname: source-document-intake`ndescription: Source document extraction, provenance, and citation discipline`n---"
            New-PlanRoles -PlanId "legal-p2" -Roles @{ audit = @{ skill_refs = @("legal-contract-review") } }
            $roomDir = New-TestRoom `
                -BriefContent "Review the attached vendor contract DOCX." `
                -TasksContent "Find risky clauses and summarize issues for counsel." `
                -PlanId "legal-p2"

            $skills = & $script:resolveScript -RoleName "audit" -RolePath $script:testRolePath `
                -SkillsBaseDir $script:baseDir -RoomDir $roomDir

            $names = $skills.Name
            $names | Should -Contain "legal-common"
            $names | Should -Contain "source-document-intake"
        }

        It "adds legal-common but not source-document-intake for a DSAR task without source-doc signal" {
            New-TestSkill -Name "legal-dsar-response" -Location "global" `
                -Frontmatter "---`nname: legal-dsar-response`ndescription: DSAR response workflow and deadline management`ntags: [legal, privacy, dsar]`n---"
            New-TestSkill -Name "legal-common" -Location "global" `
                -Frontmatter "---`nname: legal-common`ndescription: Shared legal workflow guardrails and attorney-review gate`n---"
            New-TestSkill -Name "source-document-intake" -Location "global" `
                -Frontmatter "---`nname: source-document-intake`ndescription: Source document extraction, provenance, and citation discipline`n---"
            New-PlanRoles -PlanId "legal-p3" -Roles @{ audit = @{ skill_refs = @("legal-dsar-response") } }
            $roomDir = New-TestRoom `
                -BriefContent "Handle a data subject access request and determine response workflow." `
                -TasksContent "Classify DSAR, deadline, identity verification, systems search, exemptions." `
                -PlanId "legal-p3"

            $skills = & $script:resolveScript -RoleName "audit" -RolePath $script:testRolePath `
                -SkillsBaseDir $script:baseDir -RoomDir $roomDir

            $names = $skills.Name
            $names | Should -Contain "legal-common"
            $names | Should -Not -Contain "source-document-intake"
        }

        It "does not add legal-common for a non-legal PDF task" {
            New-TestSkill -Name "legal-common" -Location "global" `
                -Frontmatter "---`nname: legal-common`ndescription: Shared legal workflow guardrails and attorney-review gate`n---"
            New-TestSkill -Name "source-document-intake" -Location "global" `
                -Frontmatter "---`nname: source-document-intake`ndescription: Source document extraction, provenance, and citation discipline`n---"
            $roomDir = New-TestRoom `
                -BriefContent "Analyze the uploaded quarterly report PDF for financial metrics." `
                -TasksContent "Extract revenue figures and growth rates from the report."

            $skills = & $script:resolveScript -RoleName "audit" -RolePath $script:testRolePath `
                -SkillsBaseDir $script:baseDir -RoomDir $roomDir

            $names = $skills.Name
            $names | Should -Not -Contain "legal-common"
        }
    }
}
