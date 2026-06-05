# Agent OS — New-WarRoom Lifecycle Pester Tests (V2 Schema)
# Verifies that lifecycle.json is purely derived from candidate_roles (DAG.json design)

BeforeAll {
    $script:NewWarRoom = Join-Path (Resolve-Path "$PSScriptRoot/../../war-rooms").Path "New-WarRoom.ps1"
}

Describe "New-WarRoom lifecycle.json" {
    BeforeEach {
        $script:warRoomsDir = Join-Path $TestDrive "warrooms-$(Get-Random)"
        New-Item -ItemType Directory -Path $script:warRoomsDir -Force | Out-Null
    }

    Context "Always created" {
        It "creates lifecycle.json even without Pipeline or Capabilities" {
            & $script:NewWarRoom -RoomId "room-lc-01" -TaskRef "EPIC-001" `
                                 -TaskDescription "Basic epic" `
                                 -WarRoomsDir $script:warRoomsDir

            Test-Path (Join-Path $script:warRoomsDir "room-lc-01" "lifecycle.json") | Should -BeTrue
        }

        It "sets initial_state to developing (v2)" {
            & $script:NewWarRoom -RoomId "room-lc-02" -TaskRef "EPIC-002" `
                                 -TaskDescription "Test" -WarRoomsDir $script:warRoomsDir

            $lc = Get-Content (Join-Path $script:warRoomsDir "room-lc-02" "lifecycle.json") -Raw | ConvertFrom-Json
            $lc.initial_state | Should -Be "developing"
            $lc.version | Should -Be 2
        }
    }

    Context "Single candidate — developing goes through review to passed" {
        It "candidate_roles=['engineer'] → developing role is engineer" {
            & $script:NewWarRoom -RoomId "room-sc-01" -TaskRef "EPIC-001" `
                                 -TaskDescription "Engineer only" `
                                 -WarRoomsDir $script:warRoomsDir `
                                 -AssignedRole "engineer" `
                                 -CandidateRoles @("engineer")

            $lc = Get-Content (Join-Path $script:warRoomsDir "room-sc-01" "lifecycle.json") -Raw | ConvertFrom-Json
            $lc.states.developing.role | Should -Be "engineer"
            $lc.states.developing.signals.done.target | Should -Be "review"
        }

        It "candidate_roles=['reporter'] → reporter does developing" {
            & $script:NewWarRoom -RoomId "room-sc-03" -TaskRef "EPIC-003" `
                                 -TaskDescription "Reporter only" `
                                 -WarRoomsDir $script:warRoomsDir `
                                 -AssignedRole "reporter" `
                                 -CandidateRoles @("reporter")

            $lc = Get-Content (Join-Path $script:warRoomsDir "room-sc-03" "lifecycle.json") -Raw | ConvertFrom-Json
            $lc.states.developing.role | Should -Be "reporter"
        }

        It "optimize and fixing states exist with same role as developing" {
            & $script:NewWarRoom -RoomId "room-sc-04" -TaskRef "EPIC-004" `
                                 -TaskDescription "Optimize state" `
                                 -WarRoomsDir $script:warRoomsDir `
                                 -CandidateRoles @("engineer")

            $lc = Get-Content (Join-Path $script:warRoomsDir "room-sc-04" "lifecycle.json") -Raw | ConvertFrom-Json
            $lc.states.optimize.role | Should -Be "engineer"
            $lc.states.optimize.type | Should -Be "work"
            $lc.states.fixing.role | Should -Be "engineer"
            $lc.states.fixing.type | Should -Be "work"
            $lc.states.fixing.signals.done.target | Should -Be "review"
        }
    }

    Context "Multi-candidate — review chain from candidate_roles[1..N]" {
        It "candidate_roles=['engineer','qa'] → review is final gate" {
            & $script:NewWarRoom -RoomId "room-mc-01" -TaskRef "EPIC-010" `
                                 -TaskDescription "With QA" `
                                 -WarRoomsDir $script:warRoomsDir `
                                 -AssignedRole "engineer" `
                                 -CandidateRoles @("engineer", "qa")

            $lc = Get-Content (Join-Path $script:warRoomsDir "room-mc-01" "lifecycle.json") -Raw | ConvertFrom-Json
            $lc.states.developing.signals.done.target | Should -Be "review"
            $lc.states.'review'.role | Should -Be "qa"
            $lc.states.'review'.signals.done.target | Should -Be "passed"
            $lc.states.'review'.signals.pass.target | Should -Be "passed" -Because "pass remains a legacy accepted success signal"
            $lc.states.'review'.signals.fail.target | Should -Be "optimize"
        }

        It "candidate_roles=['architect','manager'] → architect develops, manager excluded from review" {
            & $script:NewWarRoom -RoomId "room-mc-02" -TaskRef "PLAN-REVIEW" `
                                 -TaskDescription "Plan negotiation" `
                                 -WarRoomsDir $script:warRoomsDir `
                                 -AssignedRole "architect" `
                                 -CandidateRoles @("architect", "manager")

            $lc = Get-Content (Join-Path $script:warRoomsDir "room-mc-02" "lifecycle.json") -Raw | ConvertFrom-Json
            $lc.states.developing.role | Should -Be "architect"
            # manager excluded from review chain (orchestrator); QA review is final gate
            $lc.states.review.role | Should -Be "qa"
        }

        It "three candidates chain correctly: developing → review → review-2 → passed" {
            & $script:NewWarRoom -RoomId "room-mc-04" -TaskRef "EPIC-012" `
                                 -TaskDescription "Full pipeline" `
                                 -WarRoomsDir $script:warRoomsDir `
                                 -AssignedRole "engineer" `
                                 -CandidateRoles @("engineer", "architect", "qa")

            $lc = Get-Content (Join-Path $script:warRoomsDir "room-mc-04" "lifecycle.json") -Raw | ConvertFrom-Json
            $lc.states.developing.signals.done.target | Should -Be "review"
            $lc.states.'review'.role | Should -Be "architect"
            $lc.states.'review'.signals.done.target | Should -Be "review-2"
            $lc.states.'review'.signals.pass.target | Should -Be "review-2" -Because "pass remains a legacy accepted success signal"
            $lc.states.'review-2'.role | Should -Be "qa"
            $lc.states.'review-2'.signals.done.target | Should -Be "passed"
            $lc.states.'review-2'.signals.pass.target | Should -Be "passed" -Because "pass remains a legacy accepted success signal"
        }
    }

    Context "V2 structural states always present" {
        It "triage and failed states exist for single candidate" {
            & $script:NewWarRoom -RoomId "room-bi-01" -TaskRef "EPIC-020" `
                                 -TaskDescription "Builtins" `
                                 -WarRoomsDir $script:warRoomsDir `
                                 -CandidateRoles @("engineer")

            $lc = Get-Content (Join-Path $script:warRoomsDir "room-bi-01" "lifecycle.json") -Raw | ConvertFrom-Json
            $lc.states.triage.type | Should -Be "triage"
            $lc.states.triage.role | Should -Be "manager"
            $lc.states.failed.type | Should -Be "decision"
            $lc.states.passed.type | Should -Be "terminal"
            $lc.states.'failed-final'.type | Should -Be "terminal"
        }
    }

    Context "Pipeline precedence" {
        It "explicit Pipeline overrides candidate-derived lifecycle" {
            & $script:NewWarRoom -RoomId "room-pp-01" -TaskRef "EPIC-030" `
                                 -TaskDescription "Pipeline room" `
                                 -WarRoomsDir $script:warRoomsDir `
                                 -AssignedRole "engineer" `
                                 -CandidateRoles @("engineer") `
                                 -Pipeline "engineer -> security-review -> qa"

            $lc = Get-Content (Join-Path $script:warRoomsDir "room-pp-01" "lifecycle.json") -Raw | ConvertFrom-Json
            # Pipeline produces review state for security-review evaluator
            $lc.states.'review' | Should -Not -BeNullOrEmpty
        }
    }

    Context "Capabilities-derived lifecycle — security" {
        It "RequiredCapabilities=['security'] with engineer creates security-engineer worker and security-specialist evaluator" {
            # When a plan declares Capabilities: security with no explicit Roles:,
            # Start-Plan passes AssignedRole='engineer' and RequiredCapabilities=@('security').
            # Resolve-Pipeline must upgrade the worker to security-engineer and add
            # security-specialist as the evaluator.
            & $script:NewWarRoom -RoomId "room-cap-sec-01" -TaskRef "EPIC-SEC-01" `
                                 -TaskDescription "Security hardening epic" `
                                 -WarRoomsDir $script:warRoomsDir `
                                 -AssignedRole "engineer" `
                                 -RequiredCapabilities @("security")

            $lc = Get-Content (Join-Path $script:warRoomsDir "room-cap-sec-01" "lifecycle.json") -Raw | ConvertFrom-Json

            $lc.states.developing.role | Should -Be "security-engineer" `
                -Because "security capability must upgrade generic engineer worker"
            $lc.states.developing.type | Should -Be "work"
            $lc.states.optimize.role   | Should -Be "security-engineer"
            $lc.states.fixing.role     | Should -Be "security-engineer"
            $lc.states.review.role     | Should -Be "security-specialist" `
                -Because "security capability maps reviewer to security-specialist"
            $lc.states.review.type     | Should -Be "review"
        }

        It "RequiredCapabilities=['security'] with explicit security-engineer keeps security-engineer as worker" {
            # When the plan explicitly specifies Roles: security-engineer, the assigned
            # role already is security-engineer — upgrade map must not interfere.
            & $script:NewWarRoom -RoomId "room-cap-sec-02" -TaskRef "EPIC-SEC-02" `
                                 -TaskDescription "Explicit security-engineer epic" `
                                 -WarRoomsDir $script:warRoomsDir `
                                 -AssignedRole "security-engineer" `
                                 -RequiredCapabilities @("security")

            $lc = Get-Content (Join-Path $script:warRoomsDir "room-cap-sec-02" "lifecycle.json") -Raw | ConvertFrom-Json

            $lc.states.developing.role | Should -Be "security-engineer"
            $lc.states.review.role     | Should -Be "security-specialist"
        }

        It "RequiredCapabilities=['security'] lifecycle includes triage and terminal states" {
            & $script:NewWarRoom -RoomId "room-cap-sec-03" -TaskRef "EPIC-SEC-03" `
                                 -TaskDescription "Security audit" `
                                 -WarRoomsDir $script:warRoomsDir `
                                 -AssignedRole "engineer" `
                                 -RequiredCapabilities @("security")

            $lc = Get-Content (Join-Path $script:warRoomsDir "room-cap-sec-03" "lifecycle.json") -Raw | ConvertFrom-Json

            $lc.states.triage.type        | Should -Be "triage"
            $lc.states.failed.type        | Should -Be "decision"
            $lc.states.passed.type        | Should -Be "terminal"
            $lc.states.'failed-final'.type | Should -Be "terminal"
            # Review must have error signal to handle evaluator crashes
            $lc.states.review.signals.error | Should -Not -BeNullOrEmpty
            $lc.states.review.signals.error.target | Should -Be "failed"
        }
    }

    Context "Unknown role gets generic state name" {
        It "unknown role 'data-scientist' gets 'review' state" {
            & $script:NewWarRoom -RoomId "room-ur-01" -TaskRef "EPIC-040" `
                                 -TaskDescription "Custom role" `
                                 -WarRoomsDir $script:warRoomsDir `
                                 -AssignedRole "engineer" `
                                 -CandidateRoles @("engineer", "data-scientist")

            $lc = Get-Content (Join-Path $script:warRoomsDir "room-ur-01" "lifecycle.json") -Raw | ConvertFrom-Json
            $lc.states.'review'.role | Should -Be "data-scientist"
            $lc.states.'review'.signals.done | Should -Not -BeNullOrEmpty
            $lc.states.'review'.signals.pass | Should -Not -BeNullOrEmpty
        }
    }
}
