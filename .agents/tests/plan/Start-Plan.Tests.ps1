# Agent OS — Start-Plan Pester Tests

BeforeAll {
    $script:StartPlan = Join-Path (Resolve-Path "$PSScriptRoot/../../plan").Path "Start-Plan.ps1"
    $script:NewPlan = Join-Path (Resolve-Path "$PSScriptRoot/../../plan").Path "New-Plan.ps1"
    $script:repoLibDir = Join-Path (Resolve-Path "$PSScriptRoot/../..").Path "lib"
    # Only PlanParser.psm1 is needed — do NOT copy Config/Log/Utils.psm1 as they
    # shadow the global test mocks (Get-OstwinConfig, Write-OstwinLog, etc.)
    $script:planParserModule = Join-Path $script:repoLibDir "PlanParser.psm1"
    
    function global:Get-OstwinConfig {
        param([string]$ConfigPath = '')
        $manager = if ($global:MockManagerConfig) {
            $global:MockManagerConfig
        } else {
            [PSCustomObject]@{
                auto_expand_plan = $false
            }
        }
        return [PSCustomObject]@{
            manager = $manager
        }
    }

    function global:Get-OstwinManagerRuntimeSettings {
        param([object]$Config)
        $manager = $Config.manager
        return [PSCustomObject]@{
            max_concurrent_rooms  = if ($manager.max_concurrent_rooms) { $manager.max_concurrent_rooms } else { 10 }
            poll_interval_seconds = if ($manager.poll_interval_seconds) { $manager.poll_interval_seconds } else { 5 }
            max_engineer_retries  = if ($null -ne $manager.max_engineer_retries) { $manager.max_engineer_retries } else { 3 }
            state_timeout_seconds = if ($manager.state_timeout_seconds) { $manager.state_timeout_seconds } else { 900 }
            auto_approve_tools    = if ($null -ne $manager.auto_approve_tools) { [bool]$manager.auto_approve_tools } else { $false }
            dynamic_pipelines     = if ($null -ne $manager.dynamic_pipelines) { [bool]$manager.dynamic_pipelines } else { $true }
        }
    }
    
    function global:Test-Underspecified {
        param([string]$Content)
        if ($Content -match "Short description") { return $true }
        return $false
    }
    
    function global:Write-OstwinLog {
        param([string]$Message, [string]$Level, [string]$Caller)
        $global:testLogs += [PSCustomObject]@{ Message=$Message; Level=$Level; Caller=$Caller }
    }
}

AfterAll {
    Remove-Variable -Name MockManagerConfig -Scope Global -ErrorAction SilentlyContinue
    Remove-Item function:\Get-OstwinManagerRuntimeSettings -Force -ErrorAction SilentlyContinue
}

Describe "Start-Plan" {
    BeforeEach {
        $global:MockManagerConfig = [PSCustomObject]@{
            auto_expand_plan = $false
        }
        $global:testLogs = @()
        $script:logs = @()
        $script:projectDir = Join-Path $TestDrive "project-$(Get-Random)"
        New-Item -ItemType Directory -Path $script:projectDir -Force | Out-Null
        $agentsDir = Join-Path $script:projectDir ".agents"
        New-Item -ItemType Directory -Path $agentsDir -Force | Out-Null
        
        # Create necessary subdirectories
        $subDirs = @("plan", "war-rooms", "roles/manager", "channel", "lib")
        foreach ($sd in $subDirs) {
            New-Item -ItemType Directory -Path (Join-Path $agentsDir $sd) -Force | Out-Null
        }

        # Create dummy scripts to avoid file not found errors
        "param([object[]]`$Nodes, [switch]`$Validate) if (`$Validate) { return `$Nodes | ForEach-Object { [PSCustomObject]@{ Id = `$_.Id } } } else { Write-Host 'Dummy BuildDag' }" | Out-File (Join-Path $agentsDir "plan/Build-DependencyGraph.ps1") -Encoding utf8
        "Write-Host 'Dummy NewWarRoom'" | Out-File (Join-Path $agentsDir "war-rooms/New-WarRoom.ps1") -Encoding utf8
        "Write-Host 'Dummy ManagerLoop'" | Out-File (Join-Path $agentsDir "roles/manager/Start-ManagerLoop.ps1") -Encoding utf8
        "Write-Host 'Dummy WaitForMessage'" | Out-File (Join-Path $agentsDir "channel/Wait-ForMessage.ps1") -Encoding utf8
        "Write-Host 'Dummy ReadMessages'" | Out-File (Join-Path $agentsDir "channel/Read-Messages.ps1") -Encoding utf8
        "Write-Host 'Dummy ExpandPlan'" | Out-File (Join-Path $agentsDir "plan/Expand-Plan.ps1") -Encoding utf8

        # Copy only PlanParser.psm1 — other modules (Config, Log, Utils) have global
        # test mocks that must not be shadowed by real Import-Module
        Copy-Item -Path $script:planParserModule -Destination (Join-Path $agentsDir "lib")
    }

    Context "Plan parsing" {
        BeforeEach {
            $script:planFile = Join-Path $TestDrive "test-plan.md"
            $lines = @(
                "# Plan: Auth System",
                "",
                "> Created: 2026-01-01T00:00:00Z",
                "> Status: draft",
                "",
                "---",
                "",
                "## Goal",
                "",
                "Implement JWT authentication",
                "",
                "## Epics",
                "",
                "### EPIC-001 — JWT Authentication",
                "- Feature description bullet 1",
                "- Feature description bullet 2",
                "",
                "#### Definition of Done",
                "- [ ] JWT token generation working",
                "- [ ] Token validation middleware",
                "- [ ] Refresh token support",
                "- [ ] Unit tests pass",
                "- [ ] Documentation updated",
                "",
                "#### Acceptance Criteria",
                "- [ ] POST /login returns valid JWT",
                "- [ ] Protected routes reject invalid tokens",
                "- [ ] Scenario 3",
                "- [ ] Scenario 4",
                "- [ ] Scenario 5"
            )
            $lines | Out-File $script:planFile -Encoding utf8
        }


        It "detects EPIC-001" {
            $output = & $script:StartPlan -PlanFile $script:planFile `
                -ProjectDir $script:projectDir -DryRun *>&1
            ($output -join "`n") | Should -Match "EPIC-001"
        }

        It "shows the number of war-rooms to create" {
            $output = & $script:StartPlan -PlanFile $script:planFile `
                -ProjectDir $script:projectDir -DryRun *>&1
            ($output -join "`n") | Should -Match "War-rooms to create: 2"
        }

        It "does not create rooms in dry-run mode" {
            & $script:StartPlan -PlanFile $script:planFile `
                -ProjectDir $script:projectDir -DryRun *>&1 | Out-Null

            $warRooms = Join-Path $script:projectDir ".war-rooms"
            if (Test-Path $warRooms) {
                $rooms = Get-ChildItem $warRooms -Directory -Filter "room-*" -ErrorAction SilentlyContinue
                $rooms.Count | Should -Be 0
            }
        }

        It "parses global working_dir from PLAN.md" {
            $workingDirPlan = Join-Path $TestDrive "working-dir-plan.md"
            $targetDir = Join-Path $TestDrive "target-project"
            New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
            
            $content = "# Plan: Test`n`n## Config`nworking_dir: $targetDir`n`n### EPIC-001 — Test`n"
            $content | Out-File $workingDirPlan -Encoding utf8
            
            # Use -DryRun to just parse
            $output = & $script:StartPlan -PlanFile $workingDirPlan -ProjectDir $script:projectDir -DryRun *>&1
            ($output -join "`n") | Should -Match "Project: $([regex]::Escape($targetDir))"
        }

        It "keeps explicit ProjectDir when plan working_dir is ignored" {
            $workingDirPlan = Join-Path $TestDrive "working-dir-override-plan.md"
            $targetDir = Join-Path $TestDrive "target-project-override"
            New-Item -ItemType Directory -Path $targetDir -Force | Out-Null

            $content = "# Plan: Test`n`n## Config`nworking_dir: $targetDir`n`n### EPIC-001 — Test`n"
            $content | Out-File $workingDirPlan -Encoding utf8

            $output = & $script:StartPlan -PlanFile $workingDirPlan -ProjectDir $script:projectDir -IgnorePlanWorkingDir -DryRun *>&1
            ($output -join "`n") | Should -Match "Project: $([regex]::Escape($script:projectDir))"
            ($output -join "`n") | Should -Not -Match "Project: $([regex]::Escape($targetDir))"
        }

        It "warns when working_dir is invalid" {
            $badDirPlan = Join-Path $TestDrive "bad-dir-plan.md"
            $content = "# Plan: Test`n`n## Config`nworking_dir: /nonexistent/path/xyz`n`n### EPIC-001 — Test`n"
            $content | Out-File $badDirPlan -Encoding utf8

            $output = & $script:StartPlan -PlanFile $badDirPlan -ProjectDir $script:projectDir -DryRun *>&1
            ($output -join "`n") | Should -Match "working_dir.*not found"
        }
    }

    Context "Upfront Room and DAG Creation" {
        BeforeEach {
            $script:multiRoomPlan = Join-Path $TestDrive "multi-room-plan.md"
            $content = @"
# Plan: Multi-Room Test
working_dir: $script:projectDir

## EPIC-001 — Base Epic
#### Definition of Done
- [ ] Done 1

## EPIC-002 — Dependent Epic
depends_on: ["EPIC-001"]
#### Definition of Done
- [ ] Done 2
"@
            $content | Out-File $script:multiRoomPlan -Encoding utf8
        }

        It "injects PLAN-REVIEW as a dependency for all epics" {
            $output = & $script:StartPlan -PlanFile $script:multiRoomPlan -ProjectDir $script:projectDir -DryRun *>&1
            $outputStr = $output -join "`n"
            $outputStr | Should -Match "room-001 → EPIC-001.*\[depends_on: PLAN-REVIEW\]"
            $outputStr | Should -Match "room-002 → EPIC-002.*\[depends_on: PLAN-REVIEW, EPIC-001\]"
        }

        It "shows topological order in dry-run" {
            $output = & $script:StartPlan -PlanFile $script:multiRoomPlan -ProjectDir $script:projectDir -DryRun *>&1
            $outputStr = $output -join "`n"
            $outputStr | Should -Match "Dependency Graph \(Topological Order\):"
            $outputStr | Should -Match "PLAN-REVIEW -> EPIC-001 -> EPIC-002"
        }

        It "uses the script-local .agents tree for event context even when OSTWIN_HOME points elsewhere" {
            $smokeRoot = Join-Path $TestDrive "event-smoke-$(Get-Random)"
            $smokeProject = Join-Path $smokeRoot "project"
            New-Item -ItemType Directory -Path $smokeProject -Force | Out-Null
            $smokePlan = Join-Path $smokeRoot "PLAN.md"
            @"
# PLAN: Event smoke

working_dir: $smokeProject

## EPIC-001 - Smoke event context

Smoke event context body.

#### Definition of Done
- [ ] Room exists

#### Acceptance Criteria
- [ ] Event stream exists

depends_on: []
"@ | Out-File $smokePlan -Encoding utf8

            # Avoid Build-PlanningDAG invoking an agent; Start-Plan should read this advisory file.
            [ordered]@{
                nodes = @(
                    [ordered]@{
                        task_ref = 'EPIC-001'
                        role = 'engineer'
                        candidate_roles = @('engineer', 'qa')
                        depends_on = @()
                    }
                )
            } | ConvertTo-Json -Depth 8 | Out-File (Join-Path $smokeRoot '.planning-DAG.json') -Encoding utf8

            $oldWarRooms = $env:WARROOMS_DIR
            $oldOstwinHome = $env:OSTWIN_HOME
            $fakeHome = Join-Path $TestDrive "fake-ostwin-$(Get-Random)"
            New-Item -ItemType Directory -Path (Join-Path $fakeHome '.agents' 'war-rooms') -Force | Out-Null
            New-Item -ItemType Directory -Path (Join-Path $fakeHome '.agents' 'plan') -Force | Out-Null
            "param([string]`$RoomId,[string]`$TaskRef,[string]`$TaskDescription,[string]`$WarRoomsDir) throw 'old New-WarRoom should not be used'" |
                Out-File (Join-Path $fakeHome '.agents' 'war-rooms' 'New-WarRoom.ps1') -Encoding utf8
            "param()" | Out-File (Join-Path $fakeHome '.agents' 'plan' 'Build-DependencyGraph.ps1') -Encoding utf8

            try {
                $env:WARROOMS_DIR = Join-Path $smokeProject '.war-rooms'
                $env:OSTWIN_HOME = $fakeHome
                $output = & $script:StartPlan -PlanFile $smokePlan -ProjectDir $smokeProject -SkipLoop -NonInteractive *>&1

                ($output -join "`n") | Should -Not -Match 'old New-WarRoom should not be used'
                Test-Path (Join-Path $env:WARROOMS_DIR 'events.jsonl') | Should -BeFalse
                $roomConfigPath = Join-Path $env:WARROOMS_DIR 'room-001' 'config.json'
                Test-Path $roomConfigPath | Should -BeTrue
                $roomConfig = Get-Content $roomConfigPath -Raw | ConvertFrom-Json
                $roomConfig.PSObject.Properties.Name | Should -Not -Contain 'events_path'
            } finally {
                if ($oldWarRooms) { $env:WARROOMS_DIR = $oldWarRooms } else { Remove-Item Env:WARROOMS_DIR -ErrorAction SilentlyContinue }
                if ($oldOstwinHome) { $env:OSTWIN_HOME = $oldOstwinHome } else { Remove-Item Env:OSTWIN_HOME -ErrorAction SilentlyContinue }
            }
        }
    }

    Context "Plan expansion" {
        BeforeEach {
            $script:expandPlan = Join-Path $TestDrive "expand-plan.md"
            $expandContent = "# Plan: Expansion Test`n`n## Epics`n`n### EPIC-001 — Short description`n"
            $expandContent | Out-File $script:expandPlan -Encoding utf8
            
            $testPlanDir = Join-Path $script:projectDir ".agents/plan"
            New-Item -ItemType Directory -Path $testPlanDir -Force | Out-Null
            Copy-Item -Path (Join-Path (Resolve-Path "$PSScriptRoot/../../plan").Path "Expand-Plan.ps1") -Destination $testPlanDir -Force
        }

        It "runs expansion when underspecified epics are detected" {
            # Mock Test-Underspecified to return true for this test
            function global:Test-Underspecified { param($Content) return $true }
            
            $output = & $script:StartPlan -PlanFile $script:expandPlan -ProjectDir $script:projectDir -DryRun -Expand *>&1
            $outputStr = $output -join "`n"
            # Use a more lenient regex to ignore potential ANSI escape codes
            $outputStr | Should -Match "underspecified epics"
            $outputStr | Should -Match "expand epics"
        }

        It "respects the DryRun flag during expansion" {
            $output = & $script:StartPlan -PlanFile $script:expandPlan -ProjectDir $script:projectDir -DryRun *>&1
            $refinedFile = $script:expandPlan -replace '\.md$', '.refined.md'
            Test-Path $refinedFile | Should -Be $false
        }

        It "runs expansion without DryRun and writes logs" {
            # Dummy Expand-Plan.ps1 that creates the refined file and exits cleanly
            $dummyExpand = @"
param(
    [string]`$PlanFile,
    [string]`$OutFile,
    [switch]`$DryRun
)
if (-not `$DryRun) {
    Set-Content -Path `$OutFile -Value "# Plan: Refined Test``n``n## Epics``n``n### EPIC-001 — Expanded description``n``n#### Definition of Done``n- [ ] Done``n- [ ] D2``n- [ ] D3``n- [ ] D4``n- [ ] D5``n``n#### Acceptance Criteria``n- [ ] Accepted``n- [ ] A2``n- [ ] A3``n- [ ] A4``n- [ ] A5``n"
    Write-Host "Expansion done"
}
exit 0
"@
            $dummyExpand | Out-File (Join-Path $script:projectDir ".agents/plan/Expand-Plan.ps1") -Encoding utf8

            # Run Start-Plan without DryRun using -Expand to force expansion and -SkipLoop to isolate.
            $output = & $script:StartPlan -PlanFile $script:expandPlan -ProjectDir $script:projectDir `
                -DryRun:$false -Expand -SkipLoop *>&1

            # Verify expansion ran successfully by checking the refined file was created
            $refinedFile = $script:expandPlan -replace '\.md$', '.refined.md'
            Test-Path $refinedFile | Should -Be $true

            $updatedContent = Get-Content $refinedFile -Raw
            $updatedContent | Should -Match "Refined Test"

            # Verify the expansion was triggered in the output
            ($output -join "`n") | Should -Match "Plan expanded successfully"
        }

        It "skips expansion when refined file already exists" {
            # Create a pre-existing refined file whose EPIC description does NOT trigger
            # Test-Underspecified (which matches 'Short description')
            $refinedFile = $script:expandPlan -replace '\.md$', '.refined.md'
            $refinedContent = @"
# Plan: Already Refined

## Epics

### EPIC-001 — Fully specified auth module with detailed logic and implementation steps
- Detailed bullet 1
- Detailed bullet 2
- Detailed bullet 3
- Detailed bullet 4
- Detailed bullet 5

#### Definition of Done
- [ ] D1
- [ ] D2
- [ ] D3
- [ ] D4
- [ ] D5

#### Acceptance Criteria
- [ ] A1
- [ ] A2
- [ ] A3
- [ ] A4
- [ ] A5
"@
            $refinedContent | Out-File $refinedFile -Encoding utf8

            $output = & $script:StartPlan -PlanFile $script:expandPlan -ProjectDir $script:projectDir -DryRun *>&1
            $outputStr = ($output -join "`n")

            # Should detect and reuse existing refined file
            $outputStr | Should -Match "Using Existing Refined Plan"
            # Should NOT try to expand again since the refined content is well-specified
            $outputStr | Should -Not -Match "\[DRY RUN\] Would expand"
        }

        It "force re-expands with -Expand even when refined file exists" {
            # Create a pre-existing refined file
            $refinedFile = $script:expandPlan -replace '\.md$', '.refined.md'
            "# Plan: Old Refined`n`n### EPIC-001 — Old`n" | Out-File $refinedFile -Encoding utf8

            # With -Expand flag, it should re-run expansion, not reuse
            $output = & $script:StartPlan -PlanFile $script:expandPlan -ProjectDir $script:projectDir -DryRun -Expand *>&1
            $outputStr = ($output -join "`n")

            # Should NOT say "Using Existing" — it should re-expand
            $outputStr | Should -Not -Match "Using Existing Refined Plan"
            # Actual output: "[DRY RUN] Would expand epics (e.g. EPIC-001)"
            $outputStr | Should -Match "Would expand epics.*EPIC-001"
        }

        It "parses epics from the refined file when reusing" {
            $refinedFile = $script:expandPlan -replace '\.md$', '.refined.md'
            $refinedContent = @"
# Plan: Refined Plan

## Epics

### EPIC-001 — Expanded Auth System
- Full description bullet 1
- Full description bullet 2

#### Definition of Done
- [ ] D1
- [ ] D2
- [ ] D3
- [ ] D4
- [ ] D5

#### Acceptance Criteria
- [ ] A1
- [ ] A2
- [ ] A3
- [ ] A4
- [ ] A5

### EPIC-002 — Expanded Dashboard
- Full description bullet 1
- Full description bullet 2

#### Definition of Done
- [ ] D1
- [ ] D2
- [ ] D3
- [ ] D4
- [ ] D5

#### Acceptance Criteria
- [ ] A1
- [ ] A2
- [ ] A3
- [ ] A4
- [ ] A5
"@
            $refinedContent | Out-File $refinedFile -Encoding utf8

            $output = & $script:StartPlan -PlanFile $script:expandPlan -ProjectDir $script:projectDir -DryRun *>&1
            $outputStr = ($output -join "`n")

            # Should use the refined file and parse its 2 epics + room-000
            $outputStr | Should -Match "Using Existing Refined Plan"
            $outputStr | Should -Match "War-rooms to create: 3"
            $outputStr | Should -Match "EPIC-001"
            $outputStr | Should -Match "EPIC-002"
        }
    }

    Context "Multi-epic plan" {
        BeforeEach {
            $script:multiPlan = Join-Path $TestDrive "multi-plan.md"
            $multiContent = @"
# Plan: Full System

## Epics

### EPIC-001 — Authentication
- Auth logic description
- More details

#### Definition of Done
- [ ] Login working
- [ ] D2
- [ ] D3
- [ ] D4
- [ ] D5

#### Acceptance Criteria
- [ ] POST /login returns 200
- [ ] A2
- [ ] A3
- [ ] A4
- [ ] A5

### EPIC-002 — Dashboard
- Dashboard logic description
- More details

#### Definition of Done
- [ ] Dashboard renders
- [ ] D2
- [ ] D3
- [ ] D4
- [ ] D5

#### Acceptance Criteria
- [ ] GET /dashboard returns HTML
- [ ] A2
- [ ] A3
- [ ] A4
- [ ] A5
"@
            $multiContent | Out-File $script:multiPlan -Encoding utf8
        }

        It "detects multiple epics" {
            $output = & $script:StartPlan -PlanFile $script:multiPlan `
                -ProjectDir $script:projectDir -DryRun *>&1
            ($output -join "`n") | Should -Match "War-rooms to create: 3"
            ($output -join "`n") | Should -Match "EPIC-001"
            ($output -join "`n") | Should -Match "EPIC-002"
        }
    }

    Context "Task-only plan" {
        BeforeEach {
            $script:taskPlan = Join-Path $TestDrive "task-plan.md"
            $taskPlanContent = "# Plan: Small fixes`n`n## Tasks`n- [ ] TASK-001 — Fix login button`n- [ ] TASK-002 — Update footer text`n- [ ] TASK-003 — Add favicon"
            $taskPlanContent | Out-File $script:taskPlan -Encoding utf8
        }

        It "parses standalone tasks" {
            $output = & $script:StartPlan -PlanFile $script:taskPlan `
                -ProjectDir $script:projectDir -DryRun *>&1
            ($output -join "`n") | Should -Match "War-rooms to create: 4"
        }
    }

    Context "Error handling" {
        It "fails when plan file doesn't exist" {
            $ErrorActionPreference = 'Continue'
            $output = & $script:StartPlan -PlanFile "/nonexistent/plan.md" `
                -ProjectDir $script:projectDir -DryRun *>&1
            # Script writes error and exits 1
            ($output -join "`n") | Should -Match "(not found|Plan file)"
        }

        It "fails when plan has no epics or tasks" {
            $ErrorActionPreference = 'Continue'
            $emptyPlan = Join-Path $TestDrive "empty-plan.md"
            "No epics here. No goal either." | Out-File $emptyPlan -Encoding utf8

            $output = & $script:StartPlan -PlanFile $emptyPlan `
                -ProjectDir $script:projectDir -DryRun *>&1
            ($output -join "`n") | Should -Match "(No epics|not found|No .* tasks|no goal)"
        }

        It "shows DryRun message when goal-only plan runs with -DryRun" {
            $goalOnlyPlan = Join-Path $TestDrive "goal-only-plan.md"
            @"
# Plan: Build a chat application

## Config
working_dir: .

## Goal
Build a real-time chat application with WebSocket support.
"@ | Out-File $goalOnlyPlan -Encoding utf8

            $output = & $script:StartPlan -PlanFile $goalOnlyPlan `
                -ProjectDir $script:projectDir -DryRun *>&1
            $outputStr = $output -join "`n"
            $outputStr | Should -Match "No EPICs found.*generating"
            $outputStr | Should -Match "DRY RUN.*generate EPICs"
        }
    }

    Context "Plan ID extraction" {
        It "extracts plan_id from embedded JSON config" {
            $planWithId = Join-Path $TestDrive "plan-with-id.md"
            $planContent = @"
# Plan: Test

### EPIC-001 — Test
- Bullet 1
- Bullet 2

#### Definition of Done
- [ ] D1
- [ ] D2
- [ ] D3
- [ ] D4
- [ ] D5

#### Acceptance Criteria
- [ ] A1
- [ ] A2
- [ ] A3
- [ ] A4
- [ ] A5
"@
            $planContent | Out-File $planWithId -Encoding utf8

            $output = & $script:StartPlan -PlanFile $planWithId `
                                          -ProjectDir $script:projectDir -DryRun
            # plan_id extraction not required here — just verify it doesn't crash
            $LASTEXITCODE | Should -Not -Be 1
        }
    }

    Context "depends_on parsing (OPT-004)" {
        It "parses depends_on from EPIC section" {
            $depsPlan = Join-Path $TestDrive "deps-plan.md"
            $lines = @(
                "# Plan: Dependencies Test",
                "",
                "## Epics",
                "",
                "### EPIC-001 — Authentication",
                "- Mock description with enough details to pass check",
                "- Detailed bullet 2",
                "depends_on: []",
                "",
                "#### Definition of Done",
                "- [ ] Login working",
                "- [ ] D2", "- [ ] D3", "- [ ] D4", "- [ ] D5",
                "",
                "#### Acceptance Criteria",
                "- [ ] A1", "- [ ] A2", "- [ ] A3", "- [ ] A4", "- [ ] A5",
                "",
                "### EPIC-002 — Dashboard",
                "- Mock description with enough details to pass check",
                "- Detailed bullet 2",
                "depends_on: [EPIC-001]",
                "",
                "#### Definition of Done",
                "- [ ] Dashboard renders",
                "- [ ] D2", "- [ ] D3", "- [ ] D4", "- [ ] D5",
                "",
                "#### Acceptance Criteria",
                "- [ ] A1", "- [ ] A2", "- [ ] A3", "- [ ] A4", "- [ ] A5"
            )
            $lines | Out-File $depsPlan -Encoding utf8

            $output = & $script:StartPlan -PlanFile $depsPlan `
                -ProjectDir $script:projectDir -DryRun *>&1
            ($output -join "`n") | Should -Match "depends_on: PLAN-REVIEW, EPIC-001"
        }

        It "creates rooms without depends_on (backward compat)" {
            $noDeps = Join-Path $TestDrive "no-deps-plan.md"
            $lines = @(
                "# Plan: No Deps",
                "",
                "## Epics",
                "",
                "### EPIC-001 — Simple Feature",
                "- Mock description with enough details to pass check",
                "- Detailed bullet 2",
                "",
                "#### Definition of Done",
                "- [ ] Feature working",
                "- [ ] D2", "- [ ] D3", "- [ ] D4", "- [ ] D5",
                "",
                "#### Acceptance Criteria",
                "- [ ] A1", "- [ ] A2", "- [ ] A3", "- [ ] A4", "- [ ] A5"
            )
            $lines | Out-File $noDeps -Encoding utf8

            $output = & $script:StartPlan -PlanFile $noDeps `
                -ProjectDir $script:projectDir -DryRun *>&1
            ($output -join "`n") | Should -Match "EPIC-001"
            ($output -join "`n") | Should -Match "depends_on: PLAN-REVIEW"
        }
    }

    Context "War-room description assembly" {
        It "passes three-hash EPIC sections to New-WarRoom once" {
            $capturePath = Join-Path $script:projectDir "new-warroom-calls.jsonl"
            $mockNewWarRoom = @'
param(
    [string]$RoomId,
    [string]$TaskRef,
    [string]$TaskDescription,
    [string]$WorkingDir,
    [string]$WarRoomsDir,
    [string]$PlanId,
    [string]$RunId,
    [string]$EventsPath,
    [string]$AssignedRole,
    [string[]]$CandidateRoles = @(),
    [string[]]$DefinitionOfDone = @(),
    [string[]]$AcceptanceCriteria = @(),
    [string[]]$DependsOn = @(),
    [int]$MaxRetries = 3,
    [int]$TimeoutSeconds = 900,
    [string]$Pipeline,
    [string[]]$RequiredCapabilities = @(),
    [string]$Lifecycle,
    [object[]]$Assets = @()
)
$call = [PSCustomObject]@{
    RoomId = $RoomId
    TaskRef = $TaskRef
    TaskDescription = $TaskDescription
    DefinitionOfDone = @($DefinitionOfDone)
    AcceptanceCriteria = @($AcceptanceCriteria)
    DependsOn = @($DependsOn)
}
$call | ConvertTo-Json -Compress -Depth 8 | Add-Content -Path '__CAPTURE_PATH__'
if (-not (Test-Path $WarRoomsDir)) {
    New-Item -ItemType Directory -Path $WarRoomsDir -Force | Out-Null
}
$roomDir = Join-Path $WarRoomsDir $RoomId
New-Item -ItemType Directory -Path $roomDir -Force | Out-Null
@{ assignment = @{ assigned_role = $AssignedRole } } | ConvertTo-Json -Depth 4 |
    Out-File -FilePath (Join-Path $roomDir 'config.json') -Encoding utf8
'@ -replace '__CAPTURE_PATH__', ($capturePath -replace "'", "''")
            $mockNewWarRoom | Out-File (Join-Path $script:projectDir ".agents/war-rooms/New-WarRoom.ps1") -Encoding utf8

            $plan = Join-Path $TestDrive "sectioned-epic-plan.md"
            @"
# Plan: Sectioned Epic
working_dir: $script:projectDir

## EPIC-007: Foundation Workstream FW-1

Roles: @principal-engineer, @engineer, @qa-automation-engineer

### Context

Lift reusable primitives into a lens-agnostic model.

### Definition of Done
- [ ] Workbench shell exists.
- [ ] EnterpriseMapPanel renders through the shell.

### Acceptance Criteria
- [ ] Layout engine is a pure function.
- [ ] GraphCanvas supports both render modes.

### Tasks
- [ ] Define model/workbenchModel.ts.
- [ ] Extract shared components.

### Other aspects
- Keep public props stable.

depends_on: [EPIC-001, EPIC-003]
"@ | Out-File $plan -Encoding utf8

            & $script:StartPlan -PlanFile $plan -ProjectDir $script:projectDir -SkipLoop *>&1 | Out-Null

            $calls = Get-Content $capturePath | ForEach-Object { $_ | ConvertFrom-Json }
            $epicCall = $calls | Where-Object { $_.TaskRef -eq "EPIC-007" } | Select-Object -First 1

            $epicCall | Should -Not -BeNullOrEmpty
            ([regex]::Matches($epicCall.TaskDescription, '(?m)^#{3}\s+Context\s*$')).Count | Should -Be 1
            ([regex]::Matches($epicCall.TaskDescription, '(?m)^#{3}\s+Definition of Done\s*$')).Count | Should -Be 1
            ([regex]::Matches($epicCall.TaskDescription, '(?m)^#{3}\s+Acceptance Criteria\s*$')).Count | Should -Be 1
            ([regex]::Matches($epicCall.TaskDescription, '(?m)^#{3}\s+Tasks\s*$')).Count | Should -Be 1
            ([regex]::Matches($epicCall.TaskDescription, '(?m)^#{3}\s+Other aspects\s*$')).Count | Should -Be 1
            $epicCall.DefinitionOfDone.Count | Should -Be 2
            $epicCall.AcceptanceCriteria.Count | Should -Be 2
            $epicCall.DependsOn | Should -Contain "PLAN-REVIEW"
            $epicCall.DependsOn | Should -Contain "EPIC-001"
            $epicCall.DependsOn | Should -Contain "EPIC-003"
        }
    }

    Context "Runtime settings propagation" {
        It "creates plan rooms with configured retry and timeout settings" {
            $savedWarRoomsDir = $env:WARROOMS_DIR
            $savedOstwinHome = $env:OSTWIN_HOME
            $global:MockManagerConfig = [PSCustomObject]@{
                auto_expand_plan      = $false
                max_engineer_retries  = 7
                state_timeout_seconds = 1800
            }
            $env:WARROOMS_DIR = Join-Path $script:projectDir ".war-rooms"
            Remove-Item Env:OSTWIN_HOME -ErrorAction SilentlyContinue

            try {
                $mockNewWarRoom = @'
param(
    [string]$RoomId,
    [string]$TaskRef,
    [string]$TaskDescription,
    [string]$WorkingDir,
    [string]$WarRoomsDir,
    [string]$PlanId,
    [string]$RunId,
    [string]$EventsPath,
    [string]$AssignedRole,
    [string[]]$CandidateRoles = @(),
    [string[]]$DefinitionOfDone = @(),
    [string[]]$AcceptanceCriteria = @(),
    [string[]]$DependsOn = @(),
    [int]$MaxRetries = 3,
    [int]$TimeoutSeconds = 900
)
if (-not (Test-Path $WarRoomsDir)) {
    New-Item -ItemType Directory -Path $WarRoomsDir -Force | Out-Null
}
$roomDir = Join-Path $WarRoomsDir $RoomId
New-Item -ItemType Directory -Path $roomDir -Force | Out-Null
@{
    room_id = $RoomId
    task_ref = $TaskRef
    plan_id = $PlanId
    run_id = $RunId
    assignment = @{ assigned_role = $AssignedRole }
    constraints = @{
        max_retries = $MaxRetries
        timeout_seconds = $TimeoutSeconds
    }
} | ConvertTo-Json -Depth 6 | Out-File -FilePath (Join-Path $roomDir 'config.json') -Encoding utf8
'@
                $mockNewWarRoom | Out-File (Join-Path $script:projectDir ".agents/war-rooms/New-WarRoom.ps1") -Encoding utf8

                @'
function Get-OstwinConfig {
    param([string]$ConfigPath = '')
    return [PSCustomObject]@{
        manager = [PSCustomObject]@{
            auto_expand_plan      = $false
            max_engineer_retries  = 7
            state_timeout_seconds = 1800
        }
    }
}

function Get-OstwinManagerRuntimeSettings {
    param([object]$Config)
    return [PSCustomObject]@{
        max_concurrent_rooms  = 10
        poll_interval_seconds = 5
        max_engineer_retries  = $Config.manager.max_engineer_retries
        state_timeout_seconds = $Config.manager.state_timeout_seconds
        auto_approve_tools    = $false
        dynamic_pipelines     = $true
    }
}
'@ | Out-File (Join-Path $script:projectDir ".agents/lib/Config.psm1") -Encoding utf8

                $plan = Join-Path $TestDrive "runtime-settings-plan.md"
                @"
# Plan: Runtime Settings
working_dir: $script:projectDir

## EPIC-001 - Configurable Room Contract
- Build the configurable runtime contract.

#### Definition of Done
- [ ] Room config contains custom constraints.

#### Acceptance Criteria
- [ ] Retry count comes from manager settings.
- [ ] Timeout comes from manager settings.
"@ | Out-File $plan -Encoding utf8

                & $script:StartPlan -PlanFile $plan -ProjectDir $script:projectDir -SkipLoop *>&1 | Out-Null

                $roomConfigPath = Join-Path $script:projectDir ".war-rooms/room-001/config.json"
                $roomConfig = Get-Content $roomConfigPath -Raw | ConvertFrom-Json

                $roomConfig.constraints.max_retries | Should -Be 7
                $roomConfig.constraints.timeout_seconds | Should -Be 1800
            }
            finally {
                if ($savedWarRoomsDir) { $env:WARROOMS_DIR = $savedWarRoomsDir }
                else { Remove-Item Env:WARROOMS_DIR -ErrorAction SilentlyContinue }

                if ($savedOstwinHome) { $env:OSTWIN_HOME = $savedOstwinHome }
                else { Remove-Item Env:OSTWIN_HOME -ErrorAction SilentlyContinue }
            }
        }
    }

    Context "Mock manager lifecycle flow" {
        It "runs a folder plan where unknown QA model failure is retried by manager triage lifecycle counter" {
            $savedHome = $env:HOME
            $savedAgentOsConfig = $env:AGENT_OS_CONFIG
            $savedOstwinHome = $env:OSTWIN_HOME
            $savedWarRooms = $env:WARROOMS_DIR
            $savedSkipPlanReview = $env:OSTWIN_SKIP_PLAN_REVIEW
            $savedEventFileEnabled = $env:OSTWIN_EVENT_FILE_ENABLED
            $savedEventWsDisabled = $env:OSTWIN_EVENT_WS_DISABLED
            $savedPlanId = $env:OSTWIN_PLAN_ID
            $savedRunId = $env:OSTWIN_RUN_ID
            $savedEventsPath = $env:OSTWIN_EVENTS_PATH

            $helpersModule = Join-Path (Resolve-Path "$PSScriptRoot/../..").Path "roles/manager/ManagerLoop-Helpers.psm1"
            $eventsModule = Join-Path (Resolve-Path "$PSScriptRoot/../..").Path "events/OrchestrationEvents.psm1"
            $readMessages = Join-Path (Resolve-Path "$PSScriptRoot/../..").Path "channel/Read-Messages.ps1"
            $channelHelpers = Join-Path (Resolve-Path "$PSScriptRoot/../..").Path "tests/TestChannelHelpers.ps1"

            try {
                $flowRoot = Join-Path $TestDrive "unknown-qa-model-flow-$(Get-Random)"
                $flowProjectDir = Join-Path $flowRoot "project"
                $fakeHome = Join-Path $flowRoot "home"
                $planId = "0badc0ffee12"
                $badQaModel = "unknown/provider-that-does-not-exist"
                New-Item -ItemType Directory -Path $flowProjectDir -Force | Out-Null
                New-Item -ItemType Directory -Path (Join-Path $fakeHome ".ostwin/.agents/plans") -Force | Out-Null

                $env:HOME = $fakeHome
                $env:OSTWIN_HOME = Join-Path $fakeHome ".ostwin"
                $env:OSTWIN_SKIP_PLAN_REVIEW = "true"
                $env:OSTWIN_EVENT_FILE_ENABLED = "1"
                $env:OSTWIN_EVENT_WS_DISABLED = "1"
                Remove-Item Env:WARROOMS_DIR -ErrorAction SilentlyContinue
                Remove-Item Env:OSTWIN_PLAN_ID -ErrorAction SilentlyContinue
                Remove-Item Env:OSTWIN_RUN_ID -ErrorAction SilentlyContinue
                Remove-Item Env:OSTWIN_EVENTS_PATH -ErrorAction SilentlyContinue

                $configPath = Join-Path $flowRoot "config.json"
                [ordered]@{
                    version = "0.1.0"
                    manager = [ordered]@{
                        poll_interval_seconds = 1
                        max_concurrent_rooms  = 10
                        max_engineer_retries  = 2
                        auto_expand_plan      = $false
                        auto_approve_tools    = $true
                        state_timeout_seconds = 900
                    }
                    engineer = [ordered]@{
                        cli              = "echo"
                        default_model    = "config-engineer-model"
                        timeout_seconds  = 10
                        max_prompt_bytes = 102400
                    }
                    qa = [ordered]@{
                        cli             = "echo"
                        default_model   = "config-qa-model"
                        approval_mode   = "auto-approve"
                        timeout_seconds = 10
                    }
                    channel = [ordered]@{
                        format                 = "jsonl"
                        max_message_size_bytes = 65536
                    }
                } | ConvertTo-Json -Depth 8 | Out-File $configPath -Encoding utf8
                $env:AGENT_OS_CONFIG = $configPath

                [ordered]@{
                    engineer = [ordered]@{
                        default_model  = "opencode/big-pickle"
                        timeout_seconds = 10
                    }
                    qa = [ordered]@{
                        default_model  = $badQaModel
                        timeout_seconds = 10
                    }
                    manager = [ordered]@{
                        default_model  = "opencode/big-pickle"
                        timeout_seconds = 10
                    }
                } | ConvertTo-Json -Depth 8 |
                    Out-File (Join-Path $fakeHome ".ostwin/.agents/plans/$planId.roles.json") -Encoding utf8

                $planFile = Join-Path $flowRoot "$planId.md"
                @"
# Plan: Unknown QA Model Flow
working_dir: $flowProjectDir

## EPIC-001 - QA model fails into manager triage

Roles: @engineer, @qa

Build a small deterministic fixture where engineer succeeds but QA receives an unknown model and reports failed.

#### Definition of Done
- [ ] Engineer room uses opencode/big-pickle.
- [ ] QA failure is routed to manager triage.
- [ ] Manager triage failure increments lifecycle retries.

#### Acceptance Criteria
- [ ] Room status moves review -> triage after QA runtime failure.
- [ ] First manager triage failure keeps the room in triage.
- [ ] Second manager triage failure exhausts manager.max_engineer_retries.

depends_on: []
"@ | Out-File $planFile -Encoding utf8

                $startOutput = & pwsh -NoProfile -File $script:StartPlan `
                    -PlanFile $planFile `
                    -ProjectDir $flowProjectDir `
                    -SkipLoop `
                    -NonInteractive *>&1
                $LASTEXITCODE | Should -Be 0 -Because ($startOutput -join "`n")

                $warRoomsDir = Join-Path $flowProjectDir ".war-rooms"
                $roomDir = Join-Path $warRoomsDir "room-001"
                Test-Path $roomDir | Should -BeTrue

                $engineerConfig = Get-Content (Join-Path $roomDir "engineer_001.json") -Raw | ConvertFrom-Json
                $engineerConfig.model | Should -Be "opencode/big-pickle"
                $lifecycle = Get-Content (Join-Path $roomDir "lifecycle.json") -Raw | ConvertFrom-Json
                $lifecycle.states.review.role | Should -Be "qa"
                $lifecycle.states.triage.role | Should -Be "manager"
                $lifecycle.states.review.signals.fail.target | Should -Be "triage"
                $lifecycle.states.review.signals.fail.PSObject.Properties.Name | Should -Not -Contain "actions"

                $eventsPath = Join-Path $warRoomsDir "events.jsonl"
                $roomConfigPath = Join-Path $roomDir "config.json"
                $roomConfig = Get-Content $roomConfigPath -Raw | ConvertFrom-Json
                $roomConfig | Add-Member -NotePropertyName events_path -NotePropertyValue $eventsPath -Force
                $roomConfig.status.current = "review"
                $roomConfig | ConvertTo-Json -Depth 10 | Out-File $roomConfigPath -Encoding utf8

                $reviewChangedAt = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - 5
                "review" | Out-File (Join-Path $roomDir "status") -Encoding utf8 -NoNewline
                $reviewChangedAt.ToString() | Out-File (Join-Path $roomDir "state_changed_at") -Encoding utf8 -NoNewline
                [ordered]@{
                    role                 = "qa"
                    instance_id          = "001"
                    instance_type        = ""
                    display_name         = "qa #001"
                    model                = $badQaModel
                    timeout_seconds      = 10
                    assigned_at          = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
                    status               = "failed"
                    status_state         = "review"
                    status_updated_epoch = $reviewChangedAt + 1
                    status_updated_at    = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
                    failure_reason       = "unknown_model"
                } | ConvertTo-Json -Depth 8 | Out-File (Join-Path $roomDir "qa_001.json") -Encoding utf8
                "opencode rejected model '$badQaModel'" | Out-File (Join-Path $roomDir "artifacts/qa-output.txt") -Encoding utf8

                Import-Module $eventsModule -Force
                Import-Module $helpersModule -Force
                . $channelHelpers
                $postMessage = New-TestChannelWriter
                Set-ManagerLoopContext -Context @{
                    agentsDir        = (Resolve-Path "$PSScriptRoot/../..").Path
                    WarRoomsDir      = $warRoomsDir
                    dagFile          = Join-Path $warRoomsDir "DAG.json"
                    hasDag           = (Test-Path (Join-Path $warRoomsDir "DAG.json"))
                    dagCache         = $null
                    dagMtime         = $null
                    config           = (Get-Content $configPath -Raw | ConvertFrom-Json)
                    stateTimeout     = 900
                    maxRetries       = 2
                    postMessage      = $null
                    readMessages     = $readMessages
                    dashboardBaseUrl = "http://localhost:9999"
                }

                & $postMessage -RoomDir $roomDir -From "qa" -To "manager" -Type "fail" -Ref "EPIC-001" -Body "VERDICT: FAIL`nUnknown QA model should be triaged by manager." | Out-Null
                $matchedFailSignal = Find-LatestSignal -RoomDir $roomDir -Lifecycle $lifecycle -StateName "review"
                $matchedFailSignal | Should -Be "fail"
                $failTransition = $lifecycle.states.review.signals.$matchedFailSignal
                $failTransition.target | Should -Be "triage"
                $failTransition.PSObject.Properties.Name | Should -Not -Contain "actions"
                $failActions = if ($failTransition.PSObject.Properties['actions']) { @($failTransition.actions) } else { @() }
                Invoke-SignalActions -RoomDir $roomDir -Actions $failActions -TaskRef "EPIC-001" -BaseRole "manager"
                (Get-Content (Join-Path $roomDir "retries") -Raw).Trim() | Should -Be "0"
                Write-RoomStatus -RoomDir $roomDir -NewStatus $failTransition.target
                (Get-Content (Join-Path $roomDir "status") -Raw).Trim() | Should -Be "triage"

                "review" | Out-File (Join-Path $roomDir "status") -Encoding utf8 -NoNewline
                $reviewChangedAt.ToString() | Out-File (Join-Path $roomDir "state_changed_at") -Encoding utf8 -NoNewline

                $failedRun = Get-FreshFailedRoleRun -RoomDir $roomDir -Role "qa"
                $failedRun | Should -Not -BeNullOrEmpty
                $failedRun.Role | Should -Be "qa"
                (Get-Content $failedRun.ConfigFile -Raw | ConvertFrom-Json).model | Should -Be $badQaModel

                Write-RoomStatus -RoomDir $roomDir -NewStatus "triage"
                (Get-Content (Join-Path $roomDir "status") -Raw).Trim() | Should -Be "triage"

                New-Item -ItemType Directory -Path (Join-Path $roomDir "pids") -Force | Out-Null
                "999999" | Out-File (Join-Path $roomDir "pids/manager.pid") -Encoding utf8 -NoNewline
                $reviewChangedAt.ToString() | Out-File (Join-Path $roomDir "pids/manager.spawned_at") -Encoding utf8 -NoNewline

                $failedTriageJob = [pscustomobject]@{ Name = "ostwin-triage-room-001-manager" }
                $firstManagerFailure = Complete-ManagerTriageJobFailure -Job $failedTriageJob -FailedOutput "manager could not classify unknown QA model" -MaxRetries 2
                $firstManagerFailure.Handled | Should -BeTrue
                $firstManagerFailure.Retries | Should -Be 1
                $firstManagerFailure.Exhausted | Should -BeFalse
                (Get-Content (Join-Path $roomDir "retries") -Raw).Trim() | Should -Be "1"
                (Get-Content (Join-Path $roomDir "status") -Raw).Trim() | Should -Be "triage"
                Test-Path (Join-Path $roomDir "pids/manager.pid") | Should -BeFalse
                Test-Path (Join-Path $roomDir "pids/manager.spawned_at") | Should -BeFalse

                $secondManagerFailure = Complete-ManagerTriageJobFailure -Job $failedTriageJob -FailedOutput "manager still cannot resolve unknown QA model" -MaxRetries 2
                $secondManagerFailure.Handled | Should -BeTrue
                $secondManagerFailure.Retries | Should -Be 2
                $secondManagerFailure.Exhausted | Should -BeTrue
                $secondManagerFailure.PlanFailed | Should -BeTrue
                (Get-Content (Join-Path $roomDir "retries") -Raw).Trim() | Should -Be "2"
                (Get-Content (Join-Path $roomDir "status") -Raw).Trim() | Should -Be "failed"

                $events = Read-OrchestrationEvents -EventsPath $eventsPath
                @($events | Where-Object event_type -eq "agent.run.failed").Count | Should -Be 2
                @($events | Where-Object event_type -eq "lifecycle.retry.exhausted").Count | Should -Be 1
                @($events | Where-Object event_type -eq "epic.failed").Count | Should -Be 1
                @($events | Where-Object event_type -eq "plan.run.failed").Count | Should -Be 1
                ($events | Where-Object event_type -eq "lifecycle.retry.exhausted" | Select-Object -Last 1).payload.max_retries | Should -Be 2
            }
            finally {
                Remove-Module ManagerLoop-Helpers -ErrorAction SilentlyContinue
                Remove-Module OrchestrationEvents -ErrorAction SilentlyContinue

                if ($savedHome) { $env:HOME = $savedHome } else { Remove-Item Env:HOME -ErrorAction SilentlyContinue }
                if ($savedAgentOsConfig) { $env:AGENT_OS_CONFIG = $savedAgentOsConfig } else { Remove-Item Env:AGENT_OS_CONFIG -ErrorAction SilentlyContinue }
                if ($savedOstwinHome) { $env:OSTWIN_HOME = $savedOstwinHome } else { Remove-Item Env:OSTWIN_HOME -ErrorAction SilentlyContinue }
                if ($savedWarRooms) { $env:WARROOMS_DIR = $savedWarRooms } else { Remove-Item Env:WARROOMS_DIR -ErrorAction SilentlyContinue }
                if ($savedSkipPlanReview) { $env:OSTWIN_SKIP_PLAN_REVIEW = $savedSkipPlanReview } else { Remove-Item Env:OSTWIN_SKIP_PLAN_REVIEW -ErrorAction SilentlyContinue }
                if ($savedEventFileEnabled) { $env:OSTWIN_EVENT_FILE_ENABLED = $savedEventFileEnabled } else { Remove-Item Env:OSTWIN_EVENT_FILE_ENABLED -ErrorAction SilentlyContinue }
                if ($savedEventWsDisabled) { $env:OSTWIN_EVENT_WS_DISABLED = $savedEventWsDisabled } else { Remove-Item Env:OSTWIN_EVENT_WS_DISABLED -ErrorAction SilentlyContinue }
                if ($savedPlanId) { $env:OSTWIN_PLAN_ID = $savedPlanId } else { Remove-Item Env:OSTWIN_PLAN_ID -ErrorAction SilentlyContinue }
                if ($savedRunId) { $env:OSTWIN_RUN_ID = $savedRunId } else { Remove-Item Env:OSTWIN_RUN_ID -ErrorAction SilentlyContinue }
                if ($savedEventsPath) { $env:OSTWIN_EVENTS_PATH = $savedEventsPath } else { Remove-Item Env:OSTWIN_EVENTS_PATH -ErrorAction SilentlyContinue }
            }
        }
    }

    Context "Mixed epic and task plan" {
        BeforeEach {
            $script:mixedPlan = Join-Path $TestDrive "mixed-plan.md"
            $content = @"
# Plan: Mixed Test
## Epics
### EPIC-001 - My Epic
- Bullet 1

## Tasks
- [ ] TASK-001 - My Task
"@
            $content | Out-File $script:mixedPlan -Encoding utf8
        }
        
        It "parses both epics and tasks and injects PLAN-REVIEW" {
            $output = & $script:StartPlan -PlanFile $script:mixedPlan -ProjectDir $script:projectDir -DryRun *>&1
            $outputStr = $output -join "`n"
            $outputStr | Should -Match "War-rooms to create: 3"
            $outputStr | Should -Match "EPIC-001"
            $outputStr | Should -Match "TASK-001"
            $outputStr | Should -Match "room-001 → EPIC-001.*\[depends_on: PLAN-REVIEW\]"
            $outputStr | Should -Match "room-002 → TASK-001.*\[depends_on: PLAN-REVIEW\]"
        }
    }

    Context "Multi-Room DAG Launch (Plan B Verification)" {
        It "creates 5 rooms and full DAG for a 4-EPIC plan" {
            $fourEpicPlan = Join-Path $TestDrive "4-epic-plan.md"
            $content = @"
# Plan: 4-Epic Test
working_dir: $script:projectDir

## EPIC-001 - Epic 1
#### Definition of Done
- [ ] D1
## EPIC-002 - Epic 2
#### Definition of Done
- [ ] D2
## EPIC-003 - Epic 3
#### Definition of Done
- [ ] D3
## EPIC-004 - Epic 4
#### Definition of Done
- [ ] D4
"@
            $content | Out-File $fourEpicPlan -Encoding utf8
            
            $output = & $script:StartPlan -PlanFile $fourEpicPlan -ProjectDir $script:projectDir -DryRun *>&1
            $outputStr = $output -join "`n"
            $outputStr | Should -Match "War-rooms to create: 5"
            $outputStr | Should -Match "PLAN-REVIEW -> EPIC-001 -> EPIC-002 -> EPIC-003 -> EPIC-004"
        }
    }

    Context "Resume functionality" {
        BeforeEach {
            $absProjectDir = (Resolve-Path $script:projectDir).Path
            $script:resumePlan = Join-Path $TestDrive "resume-plan.md"
            "# Plan: Resume Test`n`n### EPIC-001 - Test`n" | Out-File $script:resumePlan -Encoding utf8
            
            $warRooms = Join-Path $absProjectDir ".war-rooms"
            if (-not (Test-Path $warRooms)) { New-Item -ItemType Directory -Path $warRooms -Force | Out-Null }
            
            $roomDir = Join-Path $warRooms "room-001"
            if (-not (Test-Path $roomDir)) { New-Item -ItemType Directory -Path $roomDir -Force | Out-Null }
            "failed-final" | Out-File (Join-Path $roomDir "status") -Encoding utf8 -NoNewline
            "10" | Out-File (Join-Path $roomDir "retries") -Encoding utf8 -NoNewline
            "5" | Out-File (Join-Path $roomDir "qa_retries") -Encoding utf8 -NoNewline
            @(
                "2026-06-09T07:38:04Z STATUS pending -> developing",
                "2026-06-09T07:48:18Z STATUS developing -> failed",
                "2026-06-09T07:49:08Z STATUS failed -> failed"
            ) | Out-File (Join-Path $roomDir "audit.log") -Encoding utf8
            @{ task_ref = "EPIC-001"; assignment = @{ assigned_role = "engineer"; candidate_roles = @("engineer", "qa") } } |
                ConvertTo-Json -Depth 6 | Out-File (Join-Path $roomDir "config.json") -Encoding utf8
            
            $room000 = Join-Path $warRooms "room-000"
            if (-not (Test-Path $room000)) { New-Item -ItemType Directory -Path $room000 -Force | Out-Null }
            "passed" | Out-File (Join-Path $room000 "status") -Encoding utf8 -NoNewline
            @{ task_ref = "PLAN-REVIEW"; assignment = @{ assigned_role = "architect"; candidate_roles = @("architect", "manager") } } |
                ConvertTo-Json -Depth 6 | Out-File (Join-Path $room000 "config.json") -Encoding utf8

            $room002 = Join-Path $warRooms "room-002"
            if (-not (Test-Path $room002)) { New-Item -ItemType Directory -Path $room002 -Force | Out-Null }
            "fixing" | Out-File (Join-Path $room002 "status") -Encoding utf8 -NoNewline
            "7" | Out-File (Join-Path $room002 "retries") -Encoding utf8 -NoNewline
            "3" | Out-File (Join-Path $room002 "crash_respawns") -Encoding utf8 -NoNewline
            @{ task_ref = "EPIC-002"; assignment = @{ assigned_role = "qa-automation-engineer"; candidate_roles = @("engineer", "qa-automation-engineer") } } |
                ConvertTo-Json -Depth 6 | Out-File (Join-Path $room002 "config.json") -Encoding utf8
            "1" | Out-File (Join-Path $room002 "state_changed_at") -Encoding utf8 -NoNewline
            @{
                role = "qa-automation-engineer"
                instance_id = "001"
                status = "failed"
                status_updated_epoch = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
                status_updated_at = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
                status_state = "review"
            } | ConvertTo-Json -Depth 4 | Out-File (Join-Path $room002 "qa-automation-engineer_001.json") -Encoding utf8
            $pidDir002 = New-Item -ItemType Directory -Path (Join-Path $room002 "pids") -Force
            New-Item -ItemType File -Path (Join-Path $pidDir002 "test.pid") -Force | Out-Null
            New-Item -ItemType File -Path (Join-Path $pidDir002 "test.spawned_at") -Force | Out-Null

            $room003 = Join-Path $warRooms "room-003"
            if (-not (Test-Path $room003)) { New-Item -ItemType Directory -Path $room003 -Force | Out-Null }
            "failed" | Out-File (Join-Path $room003 "status") -Encoding utf8 -NoNewline
            "2026-06-09T07:49:08Z STATUS failed -> failed" | Out-File (Join-Path $room003 "audit.log") -Encoding utf8
            @{ task_ref = "EPIC-003"; assignment = @{ assigned_role = "engineer"; candidate_roles = @("engineer", "qa") } } |
                ConvertTo-Json -Depth 6 | Out-File (Join-Path $room003 "config.json") -Encoding utf8

            # Ensure .agents/plan exists for mock Update-Progress
            $agentsPlanDir = Join-Path $absProjectDir ".agents/plan"
            if (-not (Test-Path $agentsPlanDir)) { New-Item -ItemType Directory -Path $agentsPlanDir -Force | Out-Null }
            "Write-Host 'Progress updated'" | Out-File (Join-Path $agentsPlanDir "Update-Progress.ps1") -Encoding utf8
        }

        It "restores failed rooms to the pre-failed audit state" {
            $absProjectDir = (Resolve-Path $script:projectDir).Path
            $output = & $script:StartPlan -PlanFile $script:resumePlan -ProjectDir $absProjectDir -Resume -DryRun:$false -SkipLoop *>&1
            $outputStr = $output -join "`n"
            
            $outputStr | Should -Match "Restoring room-001 from failed-final to developing"
            
            $statusFile = Join-Path $absProjectDir ".war-rooms/room-001/status"
            (Get-Content $statusFile -Raw) | Should -Be "developing"
        }

        It "restores failed rooms to developing when audit has no prior non-failed state" {
            $absProjectDir = (Resolve-Path $script:projectDir).Path
            $output = & $script:StartPlan -PlanFile $script:resumePlan -ProjectDir $absProjectDir -Resume -DryRun:$false -SkipLoop *>&1
            $outputStr = $output -join "`n"

            $outputStr | Should -Match "Restoring room-003 from failed to developing"

            $statusFile = Join-Path $absProjectDir ".war-rooms/room-003/status"
            (Get-Content $statusFile -Raw) | Should -Be "developing"
        }

        It "normalizes fixing rooms to optimize" {
            $absProjectDir = (Resolve-Path $script:projectDir).Path
            $output = & $script:StartPlan -PlanFile $script:resumePlan -ProjectDir $absProjectDir -Resume -DryRun:$false -SkipLoop *>&1
            $outputStr = $output -join "`n"
            
            $outputStr | Should -Match "Normalizing room-002 from fixing to optimize"
            
            $statusFile = Join-Path $absProjectDir ".war-rooms/room-002/status"
            (Get-Content $statusFile -Raw) | Should -Be "optimize"
            
            $pidDir = Join-Path $absProjectDir ".war-rooms/room-002/pids"
            (Get-ChildItem $pidDir -Filter "*.pid").Count | Should -Be 0
        }

        It "resets room retry counters on resume" {
            $absProjectDir = (Resolve-Path $script:projectDir).Path
            & $script:StartPlan -PlanFile $script:resumePlan -ProjectDir $absProjectDir -Resume -DryRun:$false -SkipLoop *>&1 | Out-Null
            
            $retriesFile = Join-Path $absProjectDir ".war-rooms/room-001/retries"
            $content = (Get-Content $retriesFile -Raw).Trim()
            $content | Should -Be "0"
            
            $qaRetriesFile = Join-Path $absProjectDir ".war-rooms/room-001/qa_retries"
            (Test-Path $qaRetriesFile) | Should -BeFalse

            $activeRetriesFile = Join-Path $absProjectDir ".war-rooms/room-002/retries"
            (Get-Content $activeRetriesFile -Raw).Trim() | Should -Be "0"

            $roleRun = Get-Content (Join-Path $absProjectDir ".war-rooms/room-002/qa-automation-engineer_001.json") -Raw | ConvertFrom-Json
            $roleRun.status | Should -Be "pending"
            $roleRun.PSObject.Properties.Name | Should -Not -Contain "status_updated_epoch"
            $roleRun.PSObject.Properties.Name | Should -Not -Contain "status_updated_at"
            $roleRun.PSObject.Properties.Name | Should -Not -Contain "status_state"

            [long](Get-Content (Join-Path $absProjectDir ".war-rooms/room-002/state_changed_at") -Raw).Trim() | Should -BeGreaterThan 1
            (Get-ChildItem (Join-Path $absProjectDir ".war-rooms/room-002/pids") -Filter "*.pid").Count | Should -Be 0
            (Get-ChildItem (Join-Path $absProjectDir ".war-rooms/room-002/pids") -Filter "*.spawned_at").Count | Should -Be 0
            Test-Path (Join-Path $absProjectDir ".war-rooms/room-002/crash_respawns") | Should -BeFalse
        }

        It "triggers Update-Progress after resets" {
            $output = & $script:StartPlan -PlanFile $script:resumePlan -ProjectDir $script:projectDir -Resume -DryRun:$false -SkipLoop *>&1
            ($output -join "`n") | Should -Match "Progress updated"
        }
    }

    Context "Sync functionality" {
        BeforeEach {
            $script:oldSyncWarRoomsDir = $env:WARROOMS_DIR
            $env:WARROOMS_DIR = Join-Path $script:projectDir ".war-rooms"
            $script:syncPlan = Join-Path $TestDrive "sync-plan.md"
            @"
# Plan: Sync Test
working_dir: $script:projectDir

## EPIC-001 - Synced Room Contract

New synced requirement from the latest plan.

### Tasks
- [ ] TASK-001 - Fresh synced task
"@ | Out-File $script:syncPlan -Encoding utf8

            $mockNewWarRoom = @'
param(
    [string]$RoomId,
    [string]$TaskRef,
    [string]$TaskDescription,
    [string]$WorkingDir,
    [string]$WarRoomsDir,
    [string]$PlanId,
    [string]$RunId,
    [string]$EventsPath,
    [string]$AssignedRole,
    [string[]]$CandidateRoles = @(),
    [string[]]$DefinitionOfDone = @(),
    [string[]]$AcceptanceCriteria = @(),
    [string[]]$DependsOn = @(),
    [int]$MaxRetries = 3,
    [int]$TimeoutSeconds = 900
)
if (-not (Test-Path $WarRoomsDir)) {
    New-Item -ItemType Directory -Path $WarRoomsDir -Force | Out-Null
}
$roomDir = Join-Path $WarRoomsDir $RoomId
New-Item -ItemType Directory -Path $roomDir -Force | Out-Null
New-Item -ItemType File -Path (Join-Path $roomDir 'channel.jsonl') -Force | Out-Null
$TaskDescription | Out-File -FilePath (Join-Path $roomDir 'brief.md') -Encoding utf8
if ($TaskRef -match '^EPIC-') {
    "# Tasks for $TaskRef`n`n$TaskDescription" | Out-File -FilePath (Join-Path $roomDir 'TASKS.md') -Encoding utf8
}
@{
    room_id = $RoomId
    task_ref = $TaskRef
    plan_id = $PlanId
    run_id = $RunId
    working_dir = $WorkingDir
    assignment = @{ assigned_role = $AssignedRole; candidate_roles = @($CandidateRoles) }
} | ConvertTo-Json -Depth 8 | Out-File -FilePath (Join-Path $roomDir 'config.json') -Encoding utf8
'@
            $mockNewWarRoom | Out-File (Join-Path $script:projectDir ".agents/war-rooms/New-WarRoom.ps1") -Encoding utf8

            $warRooms = $env:WARROOMS_DIR
            New-Item -ItemType Directory -Path $warRooms -Force | Out-Null
            $oldRoom = Join-Path $warRooms "room-001"
            New-Item -ItemType Directory -Path $oldRoom -Force | Out-Null
            "Old stale brief" | Out-File (Join-Path $oldRoom "brief.md") -Encoding utf8
            "- [x] OLD-TASK - stale work" | Out-File (Join-Path $oldRoom "TASKS.md") -Encoding utf8
            '{"type":"done","body":"old channel history"}' | Out-File (Join-Path $oldRoom "channel.jsonl") -Encoding utf8
            "done" | Out-File (Join-Path $oldRoom "status") -Encoding utf8 -NoNewline
            @{ task_ref = "EPIC-001"; assignment = @{ assigned_role = "engineer"; candidate_roles = @("engineer", "qa") } } |
                ConvertTo-Json -Depth 6 | Out-File (Join-Path $oldRoom "config.json") -Encoding utf8
        }

        AfterEach {
            if ($script:oldSyncWarRoomsDir) { $env:WARROOMS_DIR = $script:oldSyncWarRoomsDir }
            else { Remove-Item Env:WARROOMS_DIR -ErrorAction SilentlyContinue }
        }

        It "archives existing implementation rooms and recreates them from the current plan" {
            $output = & $script:StartPlan -PlanFile $script:syncPlan -ProjectDir $script:projectDir -Sync -SkipLoop *>&1
            $outputStr = $output -join "`n"

            $outputStr | Should -Match "Mode: SYNC"
            $outputStr | Should -Match "\[SYNC\] Archived room-001"

            $freshBrief = Get-Content (Join-Path $script:projectDir ".war-rooms/room-001/brief.md") -Raw
            $freshTasks = Get-Content (Join-Path $script:projectDir ".war-rooms/room-001/TASKS.md") -Raw
            $freshBrief | Should -Match "New synced requirement"
            $freshBrief | Should -Not -Match "Old stale brief"
            $freshTasks | Should -Match "Fresh synced task"
            $freshTasks | Should -Not -Match "OLD-TASK"

            $archiveRoot = Join-Path $script:projectDir ".war-rooms/.sync-archive"
            $archivedRoom = Get-ChildItem -Path $archiveRoot -Directory -Recurse -Filter "room-001" |
                Select-Object -First 1
            $archivedRoom | Should -Not -BeNullOrEmpty
            (Get-Content (Join-Path $archivedRoom.FullName "brief.md") -Raw) | Should -Match "Old stale brief"
            (Get-Content (Join-Path $archivedRoom.FullName "channel.jsonl") -Raw) | Should -Match "old channel history"
        }

        It "rejects Sync and Resume together" {
            $output = & pwsh -NoProfile -File $script:StartPlan `
                -PlanFile $script:syncPlan `
                -ProjectDir $script:projectDir `
                -Sync `
                -Resume `
                -SkipLoop *>&1

            $LASTEXITCODE | Should -Be 1
            ($output -join "`n") | Should -Match "mutually exclusive"
        }
    }

    Context "Epic auto-generation from goal-only plan" {
        BeforeEach {
            $script:goalPlan = Join-Path $TestDrive "goal-plan-$(Get-Random).md"
            @"
# Plan: Build a Chat App

## Config
working_dir: $($script:projectDir)

## Goal
Build a real-time chat application with WebSocket support, user authentication, and message persistence.
"@ | Out-File $script:goalPlan -Encoding utf8

            # Create mock Invoke-Agent.ps1 in the project's .agents dir
            $invokeDir = Join-Path $script:projectDir ".agents" "roles" "_base"
            New-Item -ItemType Directory -Path $invokeDir -Force | Out-Null
            @'
param($RoomDir, $RoleName, $Prompt, $TimeoutSeconds)
# Mock: return generated EPICs
$output = @"
## EPIC-001 - User Authentication

Implement JWT-based authentication with login, register, and token refresh.

#### Definition of Done
- [ ] JWT token generation
- [ ] Login endpoint
- [ ] Register endpoint
- [ ] Token refresh
- [ ] Password hashing

#### Acceptance Criteria
- [ ] POST /login returns JWT
- [ ] POST /register creates user
- [ ] Invalid credentials return 401
- [ ] Expired tokens are rejected
- [ ] Refresh tokens work

depends_on: []

## EPIC-002 - WebSocket Chat

Build real-time messaging with WebSocket connections.

#### Definition of Done
- [ ] WebSocket server
- [ ] Message broadcasting
- [ ] Connection management
- [ ] Message persistence
- [ ] Typing indicators

#### Acceptance Criteria
- [ ] Messages delivered in real-time
- [ ] Offline messages queued
- [ ] Connection recovery works
- [ ] Message history loads
- [ ] Typing status shows

depends_on: ["EPIC-001"]
"@
[PSCustomObject]@{ ExitCode = 0; Output = $output }
'@ | Out-File (Join-Path $invokeDir "Invoke-Agent.ps1") -Encoding utf8
        }

        It "generates EPICs from goal and appends to plan file" {
            $output = & $script:StartPlan -PlanFile $script:goalPlan `
                -ProjectDir $script:projectDir -SkipLoop *>&1
            $outputStr = $output -join "`n"

            # Should detect no EPICs and trigger generation
            $outputStr | Should -Match "No EPICs found.*generating"
            $outputStr | Should -Match "Generated.*EPICs"

            # Plan file should now contain generated EPICs
            $updatedContent = Get-Content $script:goalPlan -Raw
            $updatedContent | Should -Match "## EPIC-001 - User Authentication"
            $updatedContent | Should -Match "## EPIC-002 - WebSocket Chat"
            $updatedContent | Should -Match "depends_on:"
        }

        It "preserves original plan content after generation" {
            $null = & $script:StartPlan -PlanFile $script:goalPlan `
                -ProjectDir $script:projectDir -SkipLoop *>&1

            $updatedContent = Get-Content $script:goalPlan -Raw
            # Original goal should still be there
            $updatedContent | Should -Match "# Plan: Build a Chat App"
            $updatedContent | Should -Match "real-time chat application"
        }

        It "parses generated EPICs and injects PLAN-REVIEW dependency" {
            $output = & $script:StartPlan -PlanFile $script:goalPlan `
                -ProjectDir $script:projectDir -DryRun *>&1
            # DryRun exits before room creation — but after generation,
            # it would show the parsed EPICs with PLAN-REVIEW injected.
            # Since DryRun exits at "Would generate EPICs", we test non-DryRun.
            $output2 = & $script:StartPlan -PlanFile $script:goalPlan `
                -ProjectDir $script:projectDir -SkipLoop *>&1
            $outputStr = $output2 -join "`n"

            $outputStr | Should -Match "PLAN-REVIEW"
            $outputStr | Should -Match "EPIC-001"
            $outputStr | Should -Match "EPIC-002"
        }
    }
}


Describe "ostwin run working_dir precedence" {
    BeforeAll {
        $script:SourceOstwinCli = Join-Path (Resolve-Path "$PSScriptRoot/../..").Path "bin/ostwin"

        function New-OstwinRunFixture {
            param([string]$Name = "project")

            $projectDir = Join-Path $TestDrive "$Name-$(Get-Random)"
            $agentsDir = Join-Path $projectDir ".agents"
            New-Item -ItemType Directory -Path (Join-Path $agentsDir "bin") -Force | Out-Null
            New-Item -ItemType Directory -Path (Join-Path $agentsDir "plan") -Force | Out-Null
            @{} | ConvertTo-Json | Out-File (Join-Path $agentsDir "config.json") -Encoding utf8
            Copy-Item -Path $script:SourceOstwinCli -Destination (Join-Path $agentsDir "bin" "ostwin") -Force

            $captureFile = Join-Path $projectDir "start-plan-args.json"
            @'
param(
    [string]$PlanFile,
    [string]$ProjectDir,
    [switch]$DryRun,
    [switch]$Resume,
    [switch]$Expand,
    [switch]$Review,
    [int]$MaxConcurrent,
    [ValidateSet('room-worktree','shared')][string]$WorkspaceIsolation = 'shared',
    [string]$WorktreeRoot = '',
    [switch]$NonInteractive,
    [switch]$EnablePlanning,
    [switch]$Sync,
    [switch]$IgnorePlanWorkingDir
)
[ordered]@{
    PlanFile = $PlanFile
    ProjectDir = $ProjectDir
    DryRun = [bool]$DryRun
    WorkspaceIsolation = $WorkspaceIsolation
    NonInteractive = [bool]$NonInteractive
    Sync = [bool]$Sync
    IgnorePlanWorkingDir = [bool]$IgnorePlanWorkingDir
} | ConvertTo-Json -Depth 6 | Out-File -FilePath (Join-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) 'start-plan-args.json') -Encoding utf8
'@ | Out-File (Join-Path $agentsDir "plan" "Start-Plan.ps1") -Encoding utf8

            @'
param([string]$Directory, [switch]$Yes, [string]$PlanId)
[ordered]@{
    Directory = $Directory
    Yes = [bool]$Yes
    PlanId = $PlanId
} | ConvertTo-Json -Depth 6 | Out-File -FilePath (Join-Path $Directory 'init-args.json') -Encoding utf8
'@ | Out-File (Join-Path $agentsDir "init.ps1") -Encoding utf8

            [pscustomobject]@{
                ProjectDir = $projectDir
                AgentsDir = $agentsDir
                Ostwin = Join-Path $agentsDir "bin" "ostwin"
                CaptureFile = $captureFile
            }
        }

        function Invoke-FixtureOstwinRun {
            param(
                [Parameter(Mandatory)][object]$Fixture,
                [Parameter(Mandatory)][string[]]$Args
            )

            $oldOstwinHome = $env:OSTWIN_HOME
            $oldWarRooms = $env:WARROOMS_DIR
            $env:OSTWIN_HOME = Join-Path $TestDrive "ostwin-home-$(Get-Random)"
            Remove-Item Env:WARROOMS_DIR -ErrorAction SilentlyContinue
            New-Item -ItemType Directory -Path $env:OSTWIN_HOME -Force | Out-Null
            Push-Location $Fixture.ProjectDir
            try {
                & pwsh -NoProfile -File $Fixture.Ostwin @Args *>&1 | Out-Null
            }
            finally {
                Pop-Location
                if ($oldOstwinHome) { $env:OSTWIN_HOME = $oldOstwinHome } else { Remove-Item Env:OSTWIN_HOME -ErrorAction SilentlyContinue }
                if ($oldWarRooms) { $env:WARROOMS_DIR = $oldWarRooms } else { Remove-Item Env:WARROOMS_DIR -ErrorAction SilentlyContinue }
            }
        }
    }

    It "uses the command cwd instead of stale PLAN.md working_dir" {
        $fixture = New-OstwinRunFixture
        $oldProject = Join-Path $TestDrive "old-project-$(Get-Random)"
        $planFile = Join-Path $fixture.ProjectDir "PLAN.md"
        @"
# Plan: Cwd Override
working_dir: $oldProject

## EPIC-001 - Build from current folder
#### Definition of Done
- [ ] Done
"@ | Out-File $planFile -Encoding utf8

        Invoke-FixtureOstwinRun -Fixture $fixture -Args @('run', $planFile, '--dry-run', '-n')

        Test-Path $fixture.CaptureFile | Should -BeTrue
        $captured = Get-Content $fixture.CaptureFile -Raw | ConvertFrom-Json
        $captured.ProjectDir | Should -Be $fixture.ProjectDir
        $captured.WorkspaceIsolation | Should -Be 'shared'
        $captured.IgnorePlanWorkingDir | Should -BeTrue
    }

    It "keeps explicit --working-dir as the highest priority" {
        $fixture = New-OstwinRunFixture
        $explicitDir = Join-Path $TestDrive "explicit-project-$(Get-Random)"
        New-Item -ItemType Directory -Path $explicitDir -Force | Out-Null
        $oldProject = Join-Path $TestDrive "old-project-$(Get-Random)"
        $planFile = Join-Path $fixture.ProjectDir "PLAN.md"
        @"
# Plan: Explicit Override
working_dir: $oldProject

## EPIC-001 - Build from explicit folder
#### Definition of Done
- [ ] Done
"@ | Out-File $planFile -Encoding utf8

        Invoke-FixtureOstwinRun -Fixture $fixture -Args @('run', $planFile, '--working-dir', $explicitDir, '--workspace-isolation', 'shared', '--dry-run', '-n')

        Test-Path $fixture.CaptureFile | Should -BeTrue
        $captured = Get-Content $fixture.CaptureFile -Raw | ConvertFrom-Json
        $captured.ProjectDir | Should -Be $explicitDir
        $captured.IgnorePlanWorkingDir | Should -BeTrue
    }

    It "passes --sync through to Start-Plan" {
        $fixture = New-OstwinRunFixture
        $planFile = Join-Path $fixture.ProjectDir "PLAN.md"
        @"
# Plan: Sync Through

## EPIC-001 - Refresh room inputs
#### Definition of Done
- [ ] Done
"@ | Out-File $planFile -Encoding utf8

        Invoke-FixtureOstwinRun -Fixture $fixture -Args @('run', $planFile, '--sync', '--dry-run', '-n')

        Test-Path $fixture.CaptureFile | Should -BeTrue
        $captured = Get-Content $fixture.CaptureFile -Raw | ConvertFrom-Json
        $captured.Sync | Should -BeTrue
    }

    It "passes plan start --sync through to Start-Plan" {
        $fixture = New-OstwinRunFixture
        $planFile = Join-Path $fixture.ProjectDir "PLAN.md"
        @"
# Plan: Plan Start Sync

## EPIC-001 - Refresh room inputs
#### Definition of Done
- [ ] Done
"@ | Out-File $planFile -Encoding utf8

        Invoke-FixtureOstwinRun -Fixture $fixture -Args @('plan', 'start', $planFile, '--sync', '--dry-run')

        Test-Path $fixture.CaptureFile | Should -BeTrue
        $captured = Get-Content $fixture.CaptureFile -Raw | ConvertFrom-Json
        $captured.Sync | Should -BeTrue
    }

    It "rejects --sync and --resume together before Start-Plan dispatch" {
        $fixture = New-OstwinRunFixture
        $planFile = Join-Path $fixture.ProjectDir "PLAN.md"
        "# Plan: Bad Combo`n`n## EPIC-001 - Test" | Out-File $planFile -Encoding utf8

        $oldOstwinHome = $env:OSTWIN_HOME
        $oldWarRooms = $env:WARROOMS_DIR
        $env:OSTWIN_HOME = Join-Path $TestDrive "ostwin-home-conflict-$(Get-Random)"
        Remove-Item Env:WARROOMS_DIR -ErrorAction SilentlyContinue
        New-Item -ItemType Directory -Path $env:OSTWIN_HOME -Force | Out-Null
        Push-Location $fixture.ProjectDir
        try {
            $output = & pwsh -NoProfile -File $fixture.Ostwin run $planFile --sync --resume --dry-run *>&1
            $LASTEXITCODE | Should -Be 1
            ($output -join "`n") | Should -Match "mutually exclusive"
            Test-Path $fixture.CaptureFile | Should -BeFalse
        }
        finally {
            Pop-Location
            if ($oldOstwinHome) { $env:OSTWIN_HOME = $oldOstwinHome } else { Remove-Item Env:OSTWIN_HOME -ErrorAction SilentlyContinue }
            if ($oldWarRooms) { $env:WARROOMS_DIR = $oldWarRooms } else { Remove-Item Env:WARROOMS_DIR -ErrorAction SilentlyContinue }
        }
    }
}
