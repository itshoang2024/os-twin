# Agent OS — Multi-Room DAG Launch Tests

BeforeAll {
    $script:StartPlan = Join-Path (Resolve-Path "$PSScriptRoot/..").Path "../plan/Start-Plan.ps1"
    $script:repoLibDir = Join-Path (Resolve-Path "$PSScriptRoot/../..").Path "lib"
    $script:planParserModule = Join-Path $script:repoLibDir "PlanParser.psm1"
    
    function global:Get-OstwinConfig {
        return [PSCustomObject]@{
            manager = [PSCustomObject]@{
                auto_expand_plan = $false
                unified_plan_negotiation = $false
            }
        }
    }
    
    function global:Test-Underspecified {
        param([string]$Content)
        return $false
    }
    
    function global:Write-OstwinLog {
        param([string]$Message, [string]$Level, [string]$Caller)
    }
}

Describe "Multi-Room DAG Launch" {
    BeforeEach {
        $env:WARROOMS_DIR = $null
        $script:projectDir = Join-Path $TestDrive "project-$(Get-Random)"
        New-Item -ItemType Directory -Path $script:projectDir -Force | Out-Null
        $agentsDir = Join-Path $script:projectDir ".agents"
        New-Item -ItemType Directory -Path $agentsDir -Force | Out-Null
        
        # Create necessary subdirectories
        $subDirs = @("plan", "war-rooms", "roles/manager", "channel", "lib")
        foreach ($sd in $subDirs) {
            New-Item -ItemType Directory -Path (Join-Path $agentsDir $sd) -Force | Out-Null
        }

        # Create dummy scripts
        "param(`$Nodes, [switch]`$Validate) if (`$Validate) { return `$Nodes | ForEach-Object { [PSCustomObject]@{ Id = `$_.Id } } } else { Write-Host 'Dummy BuildDag' }" | Out-File (Join-Path $agentsDir "plan/Build-DependencyGraph.ps1") -Encoding utf8
        "param(`$RoomId, `$TaskRef, `$WarRoomsDir, `$TaskDescription, `$WorkingDir, `$PlanId, `$AssignedRole, `$DefinitionOfDone, `$AcceptanceCriteria, `$DependsOn) New-Item -ItemType Directory -Path (Join-Path `$WarRoomsDir `$RoomId) -Force | Out-Null; Write-Host `"Created `$RoomId for `$TaskRef`"" | Out-File (Join-Path $agentsDir "war-rooms/New-WarRoom.ps1") -Encoding utf8 -Force
        "param([switch]`$Review, `$WarRoomsDir, `$PlanFile) Write-Host 'Dummy ManagerLoop'" | Out-File (Join-Path $agentsDir "roles/manager/Start-ManagerLoop.ps1") -Encoding utf8 -Force
        "Write-Host 'Dummy WaitForMessage'" | Out-File (Join-Path $agentsDir "channel/Wait-ForMessage.ps1") -Encoding utf8
        "Write-Host 'Dummy ReadMessages'" | Out-File (Join-Path $agentsDir "channel/Read-Messages.ps1") -Encoding utf8
        "Write-Host 'Dummy ExpandPlan'" | Out-File (Join-Path $agentsDir "plan/Expand-Plan.ps1") -Encoding utf8

        # Copy only PlanParser.psm1 — other modules (Config, Log, Utils) have global
        # test mocks that must not be shadowed by real Import-Module
        Copy-Item -Path $script:planParserModule -Destination (Join-Path $agentsDir "lib")
    }

    It "creates 5 rooms for a 4-EPIC plan (4 epics + room-000)" {
        $planFile = Join-Path $TestDrive "4-epic-plan.md"
        $content = @"
# Plan: 4 Epics
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
        $content | Out-File $planFile -Encoding utf8

        $output = & $script:StartPlan -PlanFile $planFile -ProjectDir $script:projectDir -SkipLoop *>&1
        $outputStr = $output -join "`n"
        
        # room-000 creation output is suppressed by | Out-Null in Start-Plan.ps1
        $outputStr | Should -Match "Created room-001 for EPIC-001"
        $outputStr | Should -Match "Created room-002 for EPIC-002"
        $outputStr | Should -Match "Created room-003 for EPIC-003"
        $outputStr | Should -Match "Created room-004 for EPIC-004"
        
        $warRooms = Join-Path $script:projectDir ".war-rooms"
        Test-Path (Join-Path $warRooms "room-000") | Should -Be $true
        $rooms = Get-ChildItem $warRooms -Directory -Filter "room-*"
        $rooms.Count | Should -Be 5
    }

    It "injects PLAN-REVIEW and explicit deps correctly" {
        $planFile = Join-Path $TestDrive "deps-plan.md"
        $content = @"
# Plan: Deps
## EPIC-001 - Epic 1
#### Definition of Done
- [ ] D1
## EPIC-002 - Epic 2
depends_on: ["EPIC-001"]
#### Definition of Done
- [ ] D2
"@
        $content | Out-File $planFile -Encoding utf8

        $output = & $script:StartPlan -PlanFile $planFile -ProjectDir $script:projectDir -DryRun *>&1
        $outputStr = $output -join "`n"
        
        $outputStr | Should -Match "room-001 → EPIC-001.*\[depends_on: PLAN-REVIEW\]"
        $outputStr | Should -Match "room-002 → EPIC-002.*\[depends_on: PLAN-REVIEW, EPIC-001\]"
        $outputStr | Should -Match "PLAN-REVIEW -> EPIC-001 -> EPIC-002"
    }

    It "creates rooms and DAG before handing off to unified manager loop" {
        $planFile = Join-Path $TestDrive "unified-plan.md"
        $content = @"
# Plan: Unified
## EPIC-001 - Epic 1
#### Definition of Done
- [ ] D1
"@
        $content | Out-File $planFile -Encoding utf8

        # Mock config for unified
        function global:Get-OstwinConfig {
            return [PSCustomObject]@{
                manager = [PSCustomObject]@{
                    auto_expand_plan = $false
                    unified_plan_negotiation = $true
                }
            }
        }

        # We use -Review to trigger the handoff
        $output = & $script:StartPlan -PlanFile $planFile -ProjectDir $script:projectDir -Review *>&1
        $outputStr = $output -join "`n"
        
        $outputStr | Should -Match "Created room-001 for EPIC-001"
        $outputStr | Should -Match "\[DAG\] Building dependency graph"
        $outputStr | Should -Match "\[UNIFIED\] Handing off plan negotiation to Manager Loop"
        
        $warRooms = Join-Path $script:projectDir ".war-rooms"
        Test-Path (Join-Path $warRooms "room-000") | Should -Be $true
        $rooms = Get-ChildItem $warRooms -Directory -Filter "room-*"
        $rooms.Count | Should -Be 2
    }

    It "shows DAG structure in dry-run without creating rooms" {
        $planFile = Join-Path $TestDrive "dryrun-plan.md"
        $content = @"
# Plan: DryRun
## EPIC-001 - Epic 1
#### Definition of Done
- [ ] D1
"@
        $content | Out-File $planFile -Encoding utf8

        $output = & $script:StartPlan -PlanFile $planFile -ProjectDir $script:projectDir -DryRun *>&1
        $outputStr = $output -join "`n"
        
        $outputStr | Should -Match "Dependency Graph \(Topological Order\):"
        $outputStr | Should -Match "PLAN-REVIEW -> EPIC-001"
        $outputStr | Should -Match "\[DRY RUN\] No rooms created"
        
        $warRooms = Join-Path $script:projectDir ".war-rooms"
        Test-Path $warRooms | Should -Be $false
    }
}
