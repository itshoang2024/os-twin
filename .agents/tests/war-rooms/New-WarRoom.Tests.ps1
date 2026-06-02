# Agent OS — New-WarRoom Pester Tests

BeforeAll {
    $script:NewWarRoom = Join-Path (Resolve-Path "$PSScriptRoot/../../war-rooms").Path "New-WarRoom.ps1"
}

Describe "New-WarRoom" {
    BeforeEach {
        $script:warRoomsDir = Join-Path $TestDrive "warrooms-$(Get-Random)"
        New-Item -ItemType Directory -Path $script:warRoomsDir -Force | Out-Null
    }

    Context "Basic creation" {
        It "creates the room directory structure" {
            & $script:NewWarRoom -RoomId "room-001" -TaskRef "TASK-001" `
                                 -TaskDescription "Implement feature" `
                                 -WarRoomsDir $script:warRoomsDir

            $roomDir = Join-Path $script:warRoomsDir "room-001"
            Test-Path $roomDir | Should -BeTrue
            Test-Path (Join-Path $roomDir "pids") | Should -BeTrue
            Test-Path (Join-Path $roomDir "artifacts") | Should -BeTrue
            Test-Path (Join-Path $roomDir "channel.jsonl") | Should -BeTrue
        }

        It "creates the status file with 'pending'" {
            & $script:NewWarRoom -RoomId "room-002" -TaskRef "TASK-002" `
                                 -TaskDescription "Test" -WarRoomsDir $script:warRoomsDir

            $status = (Get-Content (Join-Path $script:warRoomsDir "room-002" "status") -Raw).Trim()
            $status | Should -Be "pending"
        }

        It "creates the retries file with '0'" {
            & $script:NewWarRoom -RoomId "room-003" -TaskRef "TASK-003" `
                                 -TaskDescription "Test" -WarRoomsDir $script:warRoomsDir

            $retries = (Get-Content (Join-Path $script:warRoomsDir "room-003" "retries") -Raw).Trim()
            $retries | Should -Be "0"
        }

        It "creates the task-ref file" {
            & $script:NewWarRoom -RoomId "room-004" -TaskRef "EPIC-001" `
                                 -TaskDescription "Epic work" -WarRoomsDir $script:warRoomsDir

            $ref = (Get-Content (Join-Path $script:warRoomsDir "room-004" "task-ref") -Raw).Trim()
            $ref | Should -Be "EPIC-001"
        }

        It "creates the brief.md file" {
            & $script:NewWarRoom -RoomId "room-005" -TaskRef "TASK-005" `
                                 -TaskDescription "Brief content here" `
                                 -WarRoomsDir $script:warRoomsDir

            $brief = Get-Content (Join-Path $script:warRoomsDir "room-005" "brief.md") -Raw
            $brief | Should -Match "TASK-005"
            $brief | Should -Match "Brief content here"
        }
    }

    Context "Config.json goal contract" {
        It "creates config.json with required structure" {
            & $script:NewWarRoom -RoomId "room-010" -TaskRef "EPIC-001" `
                                 -TaskDescription "Auth system" `
                                 -WarRoomsDir $script:warRoomsDir

            $configFile = Join-Path $script:warRoomsDir "room-010" "config.json"
            Test-Path $configFile | Should -BeTrue
            $config = Get-Content $configFile -Raw | ConvertFrom-Json

            $config.room_id | Should -Be "room-010"
            $config.task_ref | Should -Be "EPIC-001"
            $config.created_at.ToString("o") | Should -Match "\d{4}-\d{2}-\d{2}T"
        }

        It "stores assignment metadata" {
            & $script:NewWarRoom -RoomId "room-011" -TaskRef "EPIC-002" `
                                 -TaskDescription "Dashboard v2`nBuild a new dashboard" `
                                 -WarRoomsDir $script:warRoomsDir

            $config = Get-Content (Join-Path $script:warRoomsDir "room-011" "config.json") -Raw | ConvertFrom-Json
            $config.assignment.title | Should -Be "Dashboard v2"
            $config.assignment.description | Should -Match "Build a new dashboard"
            $config.assignment.assigned_role | Should -Be "engineer"
            $config.assignment.type | Should -Be "epic"
        }

        It "detects task type from TASK- prefix" {
            & $script:NewWarRoom -RoomId "room-012" -TaskRef "TASK-001" `
                                 -TaskDescription "Small fix" -WarRoomsDir $script:warRoomsDir

            $config = Get-Content (Join-Path $script:warRoomsDir "room-012" "config.json") -Raw | ConvertFrom-Json
            $config.assignment.type | Should -Be "task"
        }

        It "detects epic type from EPIC- prefix" {
            & $script:NewWarRoom -RoomId "room-013" -TaskRef "EPIC-003" `
                                 -TaskDescription "Big feature" -WarRoomsDir $script:warRoomsDir

            $config = Get-Content (Join-Path $script:warRoomsDir "room-013" "config.json") -Raw | ConvertFrom-Json
            $config.assignment.type | Should -Be "epic"
        }

        It "stores definition_of_done goals" {
            $dod = @("JWT working", "Tests at 80%", "No hardcoded secrets")
            & $script:NewWarRoom -RoomId "room-014" -TaskRef "EPIC-004" `
                                 -TaskDescription "Auth" -WarRoomsDir $script:warRoomsDir `
                                 -DefinitionOfDone $dod

            $config = Get-Content (Join-Path $script:warRoomsDir "room-014" "config.json") -Raw | ConvertFrom-Json
            $config.goals.definition_of_done.Count | Should -Be 3
            $config.goals.definition_of_done[0] | Should -Be "JWT working"
            $config.goals.definition_of_done[2] | Should -Be "No hardcoded secrets"
        }

        It "stores acceptance_criteria" {
            $ac = @("POST /login returns 200", "GET /protected returns 401 without token")
            & $script:NewWarRoom -RoomId "room-015" -TaskRef "TASK-010" `
                                 -TaskDescription "API" -WarRoomsDir $script:warRoomsDir `
                                 -AcceptanceCriteria $ac

            $config = Get-Content (Join-Path $script:warRoomsDir "room-015" "config.json") -Raw | ConvertFrom-Json
            $config.goals.acceptance_criteria.Count | Should -Be 2
        }

        It "includes default quality_requirements" {
            & $script:NewWarRoom -RoomId "room-016" -TaskRef "TASK-011" `
                                 -TaskDescription "Test" -WarRoomsDir $script:warRoomsDir

            $config = Get-Content (Join-Path $script:warRoomsDir "room-016" "config.json") -Raw | ConvertFrom-Json
            $config.goals.quality_requirements.test_coverage_min | Should -Be 80
            $config.goals.quality_requirements.lint_clean | Should -Be $true
        }

        It "stores constraints" {
            & $script:NewWarRoom -RoomId "room-017" -TaskRef "TASK-012" `
                                 -TaskDescription "Test" -WarRoomsDir $script:warRoomsDir `
                                 -MaxRetries 5 -TimeoutSeconds 1200

            $config = Get-Content (Join-Path $script:warRoomsDir "room-017" "config.json") -Raw | ConvertFrom-Json
            $config.constraints.max_retries | Should -Be 5
            $config.constraints.timeout_seconds | Should -Be 1200
        }

        It "stores status with pending state" {
            & $script:NewWarRoom -RoomId "room-018" -TaskRef "TASK-013" `
                                 -TaskDescription "Test" -WarRoomsDir $script:warRoomsDir

            $config = Get-Content (Join-Path $script:warRoomsDir "room-018" "config.json") -Raw | ConvertFrom-Json
            $config.status.current | Should -Be "pending"
            $config.status.retries | Should -Be 0
        }

        It "stores plan_id when provided" {
            & $script:NewWarRoom -RoomId "room-019" -TaskRef "EPIC-005" `
                                 -TaskDescription "Feature" -WarRoomsDir $script:warRoomsDir `
                                 -PlanId "001-auth-system"

            $config = Get-Content (Join-Path $script:warRoomsDir "room-019" "config.json") -Raw | ConvertFrom-Json
            $config.plan_id | Should -Be "001-auth-system"
        }
    }

    Context "Error handling" {
        It "prevents overwriting existing room" {
            & $script:NewWarRoom -RoomId "room-dup" -TaskRef "TASK-001" `
                                 -TaskDescription "First" -WarRoomsDir $script:warRoomsDir

            { & $script:NewWarRoom -RoomId "room-dup" -TaskRef "TASK-002" `
                                   -TaskDescription "Second" -WarRoomsDir $script:warRoomsDir } |
                Should -Throw "*already exists*"
        }
    }

    Context "Empty goals" {
        It "creates config.json with empty goals arrays when no goals provided" {
            & $script:NewWarRoom -RoomId "room-020" -TaskRef "TASK-020" `
                                 -TaskDescription "No goals" -WarRoomsDir $script:warRoomsDir

            $config = Get-Content (Join-Path $script:warRoomsDir "room-020" "config.json") -Raw | ConvertFrom-Json
            $config.goals.definition_of_done.Count | Should -Be 0
            $config.goals.acceptance_criteria.Count | Should -Be 0
        }
    }

    Context "AssignedRole support" {
        It "writes AssignedRole into config.json" {
            & $script:NewWarRoom -RoomId "room-role-01" -TaskRef "TASK-100" `
                                 -TaskDescription "FE work" -WarRoomsDir $script:warRoomsDir `
                                 -AssignedRole "engineer:fe"

            $config = Get-Content (Join-Path $script:warRoomsDir "room-role-01" "config.json") -Raw | ConvertFrom-Json
            $config.assignment.assigned_role | Should -Be "engineer:fe"
        }

        It "defaults AssignedRole to engineer" {
            & $script:NewWarRoom -RoomId "room-role-02" -TaskRef "TASK-101" `
                                 -TaskDescription "Generic work" -WarRoomsDir $script:warRoomsDir

            $config = Get-Content (Join-Path $script:warRoomsDir "room-role-02" "config.json") -Raw | ConvertFrom-Json
            $config.assignment.assigned_role | Should -Be "engineer"
        }

        It "supports backend engineer instance" {
            & $script:NewWarRoom -RoomId "room-role-03" -TaskRef "TASK-102" `
                                 -TaskDescription "BE work" -WarRoomsDir $script:warRoomsDir `
                                 -AssignedRole "engineer:be"

            $config = Get-Content (Join-Path $script:warRoomsDir "room-role-03" "config.json") -Raw | ConvertFrom-Json
            $config.assignment.assigned_role | Should -Be "engineer:be"
        }
    }

    Context "Contexts directory" {
        It "creates contexts/ directory in new room" {
            & $script:NewWarRoom -RoomId "room-ctx-01" -TaskRef "TASK-200" `
                                 -TaskDescription "Test contexts" -WarRoomsDir $script:warRoomsDir

            Test-Path (Join-Path $script:warRoomsDir "room-ctx-01" "contexts") | Should -BeTrue
        }
    }

    Context "Tasks block extraction from TaskDescription" {
        BeforeEach {
            # Simulate a real EPIC with a ### Tasks block (3 hashes)
            $script:epicWithTasks = @"
Roles: @architect, @engineer
**Goal**: Define the overall system architecture, technology decisions, and create ADRs.

### Tasks

- [ ] Define bounded contexts and module boundaries
- [ ] Select ORM and database migration strategy
- [ ] Create ADR-001: Modular Monolith Architecture
- [ ] Create ADR-002: API Design (REST vs GraphQL)

### Definition of Done

- [ ] All ADRs are documented and reviewed
- [ ] Architecture diagram exists

### Acceptance Criteria

- [ ] Each ADR follows the template
- [ ] Team has reviewed and approved
"@
            # Simulate a real EPIC with a #### Tasks block (4 hashes)
            # This is the format produced by PlanParser when sections are appended
            $script:epicWithFourHashTasks = @"
Roles: @engineer

#### Mục tiêu

Build the document scanner and classification pipeline.

#### Tasks

- [ ] TASK-1.1 — Scanner with deduplication
- [ ] TASK-1.2 — Classify into 4 SAV groups
- [ ] TASK-1.3 — Map to SAV appendices

#### Definition of Done

- 100% documents classified
- Cross-reference matrix complete
"@

            $script:epicWithoutTasks = @"
**Goal**: Scaffold the NestJS backend following DDD and modular monolith principles.

Set up health checks, Swagger docs, global error handling, and Docker-based local development.
"@
        }

        It "brief.md excludes ### Tasks block when present in TaskDescription" {
            & $script:NewWarRoom -RoomId "room-tasks-01" -TaskRef "EPIC-001" `
                -TaskDescription $script:epicWithTasks `
                -WarRoomsDir $script:warRoomsDir

            $brief = Get-Content (Join-Path $script:warRoomsDir "room-tasks-01" "brief.md") -Raw
            $brief | Should -Not -Match "### Tasks"
            $brief | Should -Not -Match "Define bounded contexts"
            $brief | Should -Not -Match "Select ORM and database"
        }

        It "brief.md retains non-tasks content when tasks block extracted" {
            & $script:NewWarRoom -RoomId "room-tasks-02" -TaskRef "EPIC-001" `
                -TaskDescription $script:epicWithTasks `
                -WarRoomsDir $script:warRoomsDir

            $brief = Get-Content (Join-Path $script:warRoomsDir "room-tasks-02" "brief.md") -Raw
            $brief | Should -Match "Define the overall system architecture"
            $brief | Should -Match "EPIC-001"
        }

        It "TASKS.md contains extracted tasks from TaskDescription for epics" {
            & $script:NewWarRoom -RoomId "room-tasks-03" -TaskRef "EPIC-001" `
                -TaskDescription $script:epicWithTasks `
                -WarRoomsDir $script:warRoomsDir

            $tasks = Get-Content (Join-Path $script:warRoomsDir "room-tasks-03" "TASKS.md") -Raw
            $tasks | Should -Match "Define bounded contexts"
            $tasks | Should -Match "Select ORM and database migration"
            $tasks | Should -Match "Create ADR-001"
            $tasks | Should -Match "Create ADR-002"
        }

        It "TASKS.md includes header with EPIC reference" {
            & $script:NewWarRoom -RoomId "room-tasks-04" -TaskRef "EPIC-001" `
                -TaskDescription $script:epicWithTasks `
                -WarRoomsDir $script:warRoomsDir

            $tasks = Get-Content (Join-Path $script:warRoomsDir "room-tasks-04" "TASKS.md") -Raw
            $tasks | Should -Match "EPIC-001"
        }

        It "TASKS.md falls back to skeleton when no tasks block in description" {
            & $script:NewWarRoom -RoomId "room-tasks-05" -TaskRef "EPIC-002" `
                -TaskDescription $script:epicWithoutTasks `
                -WarRoomsDir $script:warRoomsDir

            $tasksFile = Join-Path $script:warRoomsDir "room-tasks-05" "TASKS.md"
            Test-Path $tasksFile | Should -BeTrue
            $tasks = Get-Content $tasksFile -Raw
            # Fallback skeleton still created
            $tasks | Should -Match "EPIC-002"
        }

        It "brief.md still contains DoD/AC when tasks block is extracted" {
            & $script:NewWarRoom -RoomId "room-tasks-06" -TaskRef "EPIC-001" `
                -TaskDescription $script:epicWithTasks `
                -WarRoomsDir $script:warRoomsDir `
                -DefinitionOfDone @("All ADRs documented", "Arch diagram exists") `
                -AcceptanceCriteria @("ADR follows template", "Team approved")

            $brief = Get-Content (Join-Path $script:warRoomsDir "room-tasks-06" "brief.md") -Raw
            $brief | Should -Match "## Definition of Done"
            $brief | Should -Match "## Acceptance Criteria"
            $brief | Should -Match "All ADRs documented"
            $brief | Should -Not -Match "### Tasks"
        }

        It "TASK prefix does not create TASKS.md even with tasks-like content" {
            & $script:NewWarRoom -RoomId "room-tasks-07" -TaskRef "TASK-001" `
                -TaskDescription "Some task with a checklist" `
                -WarRoomsDir $script:warRoomsDir

            Test-Path (Join-Path $script:warRoomsDir "room-tasks-07" "TASKS.md") | Should -BeFalse
        }

        It "brief.md is unchanged when no Tasks block exists" {
            & $script:NewWarRoom -RoomId "room-tasks-08" -TaskRef "EPIC-002" `
                -TaskDescription $script:epicWithoutTasks `
                -WarRoomsDir $script:warRoomsDir

            $brief = Get-Content (Join-Path $script:warRoomsDir "room-tasks-08" "brief.md") -Raw
            $brief | Should -Match "Scaffold the NestJS backend"
            $brief | Should -Match "health checks"
        }

        # --- #### Tasks (4-hash) heading level tests ---
        # Covers the production format where PlanParser sections use ####

        It "brief.md excludes #### Tasks block (4-hash heading)" {
            & $script:NewWarRoom -RoomId "room-tasks-09" -TaskRef "EPIC-010" `
                -TaskDescription $script:epicWithFourHashTasks `
                -WarRoomsDir $script:warRoomsDir

            $brief = Get-Content (Join-Path $script:warRoomsDir "room-tasks-09" "brief.md") -Raw
            $brief | Should -Not -Match "#### Tasks"
            $brief | Should -Not -Match "TASK-1\.1"
            $brief | Should -Not -Match "TASK-1\.3"
            # Mục tiêu and non-task content preserved
            $brief | Should -Match "document scanner"
        }

        It "TASKS.md extracts #### Tasks block content (4-hash heading)" {
            & $script:NewWarRoom -RoomId "room-tasks-10" -TaskRef "EPIC-010" `
                -TaskDescription $script:epicWithFourHashTasks `
                -WarRoomsDir $script:warRoomsDir

            $tasks = Get-Content (Join-Path $script:warRoomsDir "room-tasks-10" "TASKS.md") -Raw
            $tasks | Should -Match "TASK-1\.1"
            $tasks | Should -Match "TASK-1\.2"
            $tasks | Should -Match "TASK-1\.3"
            $tasks | Should -Match "EPIC-010"
            # DoD should NOT bleed into TASKS.md
            $tasks | Should -Not -Match "Cross-reference matrix"
        }

        It "brief.md preserves #### Definition of Done when #### Tasks stripped" {
            & $script:NewWarRoom -RoomId "room-tasks-11" -TaskRef "EPIC-010" `
                -TaskDescription $script:epicWithFourHashTasks `
                -WarRoomsDir $script:warRoomsDir `
                -DefinitionOfDone @("100% documents classified")

            $brief = Get-Content (Join-Path $script:warRoomsDir "room-tasks-11" "brief.md") -Raw
            $brief | Should -Match "## Definition of Done"
            $brief | Should -Match "100% documents classified"
            $brief | Should -Not -Match "#### Tasks"
        }
    }

    Context "Plan-specific roles.json resolution" {
        BeforeEach {
            # Create a mock ~/.ostwin/.agents/plans directory with plan roles config
            $script:plansDir = Join-Path $TestDrive "ostwin-plans-$(Get-Random)"
            New-Item -ItemType Directory -Path $script:plansDir -Force | Out-Null
            $script:testPlanId = "test-plan-$(Get-Random)"

            $planRolesConfig = @{
                engineer = @{
                    default_model   = "google-vertex/gemini-plan-custom-model"
                    timeout_seconds = 1800
                    skill_refs      = @("write-tests", "code-review")
                }
                qa = @{
                    default_model = "qa-plan-model"
                }
            }
            $planRolesFile = Join-Path $script:plansDir "$($script:testPlanId).roles.json"
            $planRolesConfig | ConvertTo-Json -Depth 5 | Out-File -FilePath $planRolesFile -Encoding utf8

            # Point HOME to TestDrive so the script finds ~/.ostwin/.agents/plans/
            $script:origHome = $env:HOME
            $script:fakeHome = Join-Path $TestDrive "fakehome-$(Get-Random)"
            New-Item -ItemType Directory -Path (Join-Path $script:fakeHome ".ostwin" ".agents" "plans") -Force | Out-Null
            Copy-Item $planRolesFile (Join-Path $script:fakeHome ".ostwin" ".agents" "plans")
            $env:HOME = $script:fakeHome
        }

        AfterEach {
            $env:HOME = $script:origHome
        }

        It "uses model from plan roles.json when PlanId is provided" {
            & $script:NewWarRoom -RoomId "room-plan-01" -TaskRef "EPIC-010" `
                                 -TaskDescription "Plan test" -WarRoomsDir $script:warRoomsDir `
                                 -PlanId $script:testPlanId

            $roleFile = Get-ChildItem (Join-Path $script:warRoomsDir "room-plan-01") -Filter "engineer_*.json" | Select-Object -First 1
            $roleFile | Should -Not -BeNullOrEmpty
            $roleConfig = Get-Content $roleFile.FullName -Raw | ConvertFrom-Json
            $roleConfig.model | Should -Be "google-vertex/gemini-plan-custom-model"
        }

        It "uses timeout from plan roles.json" {
            & $script:NewWarRoom -RoomId "room-plan-02" -TaskRef "EPIC-011" `
                                 -TaskDescription "Timeout test" -WarRoomsDir $script:warRoomsDir `
                                 -PlanId $script:testPlanId

            $roleFile = Get-ChildItem (Join-Path $script:warRoomsDir "room-plan-02") -Filter "engineer_*.json" | Select-Object -First 1
            $roleConfig = Get-Content $roleFile.FullName -Raw | ConvertFrom-Json
            $roleConfig.timeout_seconds | Should -Be 1800
        }

        It "includes skill_refs from plan roles.json" {
            & $script:NewWarRoom -RoomId "room-plan-03" -TaskRef "EPIC-012" `
                                 -TaskDescription "Skills test" -WarRoomsDir $script:warRoomsDir `
                                 -PlanId $script:testPlanId

            $roleFile = Get-ChildItem (Join-Path $script:warRoomsDir "room-plan-03") -Filter "engineer_*.json" | Select-Object -First 1
            $roleConfig = Get-Content $roleFile.FullName -Raw | ConvertFrom-Json
            $roleConfig.skill_refs | Should -Contain "write-tests"
            $roleConfig.skill_refs | Should -Contain "code-review"
        }

        It "falls back to default model when PlanId has no roles.json" {
            & $script:NewWarRoom -RoomId "room-plan-04" -TaskRef "EPIC-013" `
                                 -TaskDescription "Fallback test" -WarRoomsDir $script:warRoomsDir `
                                 -PlanId "nonexistent-plan-id"

            $roleFile = Get-ChildItem (Join-Path $script:warRoomsDir "room-plan-04") -Filter "engineer_*.json" | Select-Object -First 1
            $roleConfig = Get-Content $roleFile.FullName -Raw | ConvertFrom-Json
            # Should fall back to global config or default
            $roleConfig.model | Should -Not -Be "google-vertex/gemini-plan-custom-model"
        }
    }

    Context "Role.json skill_refs fallback when no plan roles.json" {
        BeforeEach {
            # Create a fake HOME with a role.json that has skill_refs
            $script:origHome = $env:HOME
            $script:fakeHome = Join-Path $TestDrive "fakehome-rolejson-$(Get-Random)"

            # Create role.json with skill_refs for game-engineer
            $roleDir = Join-Path $script:fakeHome ".ostwin" "roles" "game-engineer"
            New-Item -ItemType Directory -Path $roleDir -Force | Out-Null
            @{
                name       = "game-engineer"
                skill_refs = @("build-ui", "detect-ui", "unity-dev-principles")
                model      = "test-model"
            } | ConvertTo-Json | Out-File -FilePath (Join-Path $roleDir "role.json") -Encoding utf8

            # Also create empty plans dir (no plan-specific roles.json)
            New-Item -ItemType Directory -Path (Join-Path $script:fakeHome ".ostwin" ".agents" "plans") -Force | Out-Null

            $env:HOME = $script:fakeHome
        }

        AfterEach {
            $env:HOME = $script:origHome
        }

        It "populates skill_refs from role.json when plan roles.json is missing" {
            & $script:NewWarRoom -RoomId "room-rolejson-01" -TaskRef "EPIC-020" `
                                 -TaskDescription "Game feature" -WarRoomsDir $script:warRoomsDir `
                                 -AssignedRole "game-engineer" `
                                 -PlanId "nonexistent-plan-id"

            $roleFile = Get-ChildItem (Join-Path $script:warRoomsDir "room-rolejson-01") -Filter "game-engineer_*.json" | Select-Object -First 1
            $roleFile | Should -Not -BeNullOrEmpty
            $roleConfig = Get-Content $roleFile.FullName -Raw | ConvertFrom-Json
            $roleConfig.skill_refs | Should -Not -BeNullOrEmpty
            $roleConfig.skill_refs | Should -Contain "build-ui"
            $roleConfig.skill_refs | Should -Contain "detect-ui"
            $roleConfig.skill_refs | Should -Contain "unity-dev-principles"
        }

        It "populates skill_refs from role.json when PlanId is empty" {
            & $script:NewWarRoom -RoomId "room-rolejson-02" -TaskRef "EPIC-021" `
                                 -TaskDescription "Another game feature" -WarRoomsDir $script:warRoomsDir `
                                 -AssignedRole "game-engineer"

            $roleFile = Get-ChildItem (Join-Path $script:warRoomsDir "room-rolejson-02") -Filter "game-engineer_*.json" | Select-Object -First 1
            $roleFile | Should -Not -BeNullOrEmpty
            $roleConfig = Get-Content $roleFile.FullName -Raw | ConvertFrom-Json
            $roleConfig.skill_refs | Should -Not -BeNullOrEmpty
            $roleConfig.skill_refs | Should -Contain "build-ui"
        }

        It "plan roles.json skill_refs take priority over role.json skill_refs" {
            # Create a plan roles.json that overrides the role.json skills
            $planId = "plan-override-$(Get-Random)"
            $planRolesFile = Join-Path $script:fakeHome ".ostwin" ".agents" "plans" "$planId.roles.json"
            @{
                "game-engineer" = @{
                    skill_refs = @("custom-plan-skill-a", "custom-plan-skill-b")
                }
            } | ConvertTo-Json -Depth 5 | Out-File -FilePath $planRolesFile -Encoding utf8

            & $script:NewWarRoom -RoomId "room-rolejson-03" -TaskRef "EPIC-022" `
                                 -TaskDescription "Plan override test" -WarRoomsDir $script:warRoomsDir `
                                 -AssignedRole "game-engineer" `
                                 -PlanId $planId

            $roleFile = Get-ChildItem (Join-Path $script:warRoomsDir "room-rolejson-03") -Filter "game-engineer_*.json" | Select-Object -First 1
            $roleConfig = Get-Content $roleFile.FullName -Raw | ConvertFrom-Json
            # Should use plan's skills, NOT role.json's
            $roleConfig.skill_refs | Should -Contain "custom-plan-skill-a"
            $roleConfig.skill_refs | Should -Not -Contain "build-ui"
        }

        It "returns empty skill_refs when neither plan roles.json nor role.json have skills" {
            # Create a role with no skill_refs
            $noSkillRoleDir = Join-Path $script:fakeHome ".ostwin" "roles" "engineer"
            New-Item -ItemType Directory -Path $noSkillRoleDir -Force | Out-Null
            @{
                name  = "engineer"
                model = "test-model"
            } | ConvertTo-Json | Out-File -FilePath (Join-Path $noSkillRoleDir "role.json") -Encoding utf8

            & $script:NewWarRoom -RoomId "room-rolejson-04" -TaskRef "TASK-030" `
                                 -TaskDescription "No skills test" -WarRoomsDir $script:warRoomsDir `
                                 -AssignedRole "engineer" `
                                 -PlanId "nonexistent-plan-id"

            $roleFile = Get-ChildItem (Join-Path $script:warRoomsDir "room-rolejson-04") -Filter "engineer_*.json" | Select-Object -First 1
            $roleConfig = Get-Content $roleFile.FullName -Raw | ConvertFrom-Json
            # skill_refs should not exist or be empty
            if ($roleConfig.PSObject.Properties.Name -contains "skill_refs") {
                $roleConfig.skill_refs.Count | Should -Be 0
            }
        }
    }

    Context "WorkingDir support" {
        It "stores absolute working_dir in config.json" {
            & $script:NewWarRoom -RoomId "room-wd-01" -TaskRef "EPIC-001" `
                                 -TaskDescription "Feature" -WarRoomsDir $script:warRoomsDir `
                                 -WorkingDir "/tmp/project/src"

            $config = Get-Content (Join-Path $script:warRoomsDir "room-wd-01" "config.json") -Raw | ConvertFrom-Json
            $config.working_dir | Should -BeOfType [string]
            $config.working_dir | Should -Be "/tmp/project/src"
        }

        It "defaults to current directory when no WorkingDir provided" {
            & $script:NewWarRoom -RoomId "room-wd-03" -TaskRef "TASK-001" `
                                 -TaskDescription "No dirs" -WarRoomsDir $script:warRoomsDir

            $config = Get-Content (Join-Path $script:warRoomsDir "room-wd-03" "config.json") -Raw | ConvertFrom-Json
            $config.working_dir | Should -Not -BeNullOrEmpty
        }

        It "preserves absolute paths without Resolve-Path failure" {
            $nonExistentDir = "/tmp/nonexistent-project-$(Get-Random)/src"
            & $script:NewWarRoom -RoomId "room-wd-04" -TaskRef "EPIC-003" `
                                 -TaskDescription "Future dir" -WarRoomsDir $script:warRoomsDir `
                                 -WorkingDir $nonExistentDir

            $config = Get-Content (Join-Path $script:warRoomsDir "room-wd-04" "config.json") -Raw | ConvertFrom-Json
            $config.working_dir | Should -Be $nonExistentDir
        }
    }
}
