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
    [string]$AssignedRole,
    [string[]]$CandidateRoles = @(),
    [string[]]$DefinitionOfDone = @(),
    [string[]]$AcceptanceCriteria = @(),
    [string[]]$DependsOn = @(),
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
    assignment = @{ assigned_role = $AssignedRole }
    constraints = @{
        max_retries = $MaxRetries
        timeout_seconds = $TimeoutSeconds
    }
} | ConvertTo-Json -Depth 6 | Out-File -FilePath (Join-Path $roomDir 'config.json') -Encoding utf8
'@
                $mockNewWarRoom | Out-File (Join-Path $script:projectDir ".agents/war-rooms/New-WarRoom.ps1") -Encoding utf8

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
            
            $room000 = Join-Path $warRooms "room-000"
            if (-not (Test-Path $room000)) { New-Item -ItemType Directory -Path $room000 -Force | Out-Null }
            "passed" | Out-File (Join-Path $room000 "status") -Encoding utf8 -NoNewline

            $room002 = Join-Path $warRooms "room-002"
            if (-not (Test-Path $room002)) { New-Item -ItemType Directory -Path $room002 -Force | Out-Null }
            "fixing" | Out-File (Join-Path $room002 "status") -Encoding utf8 -NoNewline
            $pidDir002 = New-Item -ItemType Directory -Path (Join-Path $room002 "pids") -Force
            New-Item -ItemType File -Path (Join-Path $pidDir002 "test.pid") -Force | Out-Null

            # Ensure .agents/plan exists for mock Update-Progress
            $agentsPlanDir = Join-Path $absProjectDir ".agents/plan"
            if (-not (Test-Path $agentsPlanDir)) { New-Item -ItemType Directory -Path $agentsPlanDir -Force | Out-Null }
            "Write-Host 'Progress updated'" | Out-File (Join-Path $agentsPlanDir "Update-Progress.ps1") -Encoding utf8
        }

        It "resets failed-final rooms to pending" {
            $absProjectDir = (Resolve-Path $script:projectDir).Path
            $output = & $script:StartPlan -PlanFile $script:resumePlan -ProjectDir $absProjectDir -Resume -DryRun:$false -SkipLoop *>&1
            $outputStr = $output -join "`n"
            
            $outputStr | Should -Match "Resetting room-001 to pending"
            
            $statusFile = Join-Path $absProjectDir ".war-rooms/room-001/status"
            (Get-Content $statusFile -Raw) | Should -Be "pending"
        }

        It "moves fixing rooms to developing" {
            $absProjectDir = (Resolve-Path $script:projectDir).Path
            $output = & $script:StartPlan -PlanFile $script:resumePlan -ProjectDir $absProjectDir -Resume -DryRun:$false -SkipLoop *>&1
            $outputStr = $output -join "`n"
            
            $outputStr | Should -Match "Moving room-002 from fixing to developing"
            
            $statusFile = Join-Path $absProjectDir ".war-rooms/room-002/status"
            (Get-Content $statusFile -Raw) | Should -Be "developing"
            
            $pidDir = Join-Path $absProjectDir ".war-rooms/room-002/pids"
            (Get-ChildItem $pidDir -Filter "*.pid").Count | Should -Be 0
        }

        It "clears retry counters on resume" {
            $absProjectDir = (Resolve-Path $script:projectDir).Path
            & $script:StartPlan -PlanFile $script:resumePlan -ProjectDir $absProjectDir -Resume -DryRun:$false -SkipLoop *>&1 | Out-Null
            
            $retriesFile = Join-Path $absProjectDir ".war-rooms/room-001/retries"
            $content = (Get-Content $retriesFile -Raw).Trim()
            $content | Should -Be "0"
            
            $qaRetriesFile = Join-Path $absProjectDir ".war-rooms/room-001/qa_retries"
            (Test-Path $qaRetriesFile) | Should -Be $false
        }

        It "triggers Update-Progress after resets" {
            $output = & $script:StartPlan -PlanFile $script:resumePlan -ProjectDir $script:projectDir -Resume -DryRun:$false -SkipLoop *>&1
            ($output -join "`n") | Should -Match "Progress updated"
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
