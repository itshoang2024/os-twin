# Agent OS — Resolve-Pipeline.ps1 Unit Tests

BeforeAll {
    $script:agentsDir = (Resolve-Path (Join-Path (Resolve-Path "$PSScriptRoot/../../lifecycle").Path "..")).Path
    $script:ResolvePipeline = Join-Path $script:agentsDir "lifecycle" "Resolve-Pipeline.ps1"

    function Assert-NoLifecycleErrorSignal {
        param([Parameter(Mandatory)]$Lifecycle)

        $stateEntries = if ($Lifecycle.states -is [System.Collections.IDictionary]) {
            $Lifecycle.states.GetEnumerator()
        } else {
            $Lifecycle.states.PSObject.Properties | ForEach-Object {
                [pscustomobject]@{ Key = $_.Name; Value = $_.Value }
            }
        }

        foreach ($entry in $stateEntries) {
            $signals = $entry.Value.signals
            if (-not $signals) { continue }
            $signalNames = if ($signals -is [System.Collections.IDictionary]) {
                @($signals.Keys)
            } else {
                @($signals.PSObject.Properties.Name)
            }
            $signalNames | Should -Not -Contain "error" -Because "state '$($entry.Key)' must not model runtime failures as lifecycle signals"
        }
    }
}

Describe "Resolve-Pipeline.ps1 — Dynamic Lifecycle Generation" {
    It "Builds lifecycle with three candidates as worker plus one canonical reviewer" {
        # Position-based: [0]=worker, [1]=reviewer.
        # Additional candidates remain advisory metadata outside the lifecycle.
        # RoleOverrides kept for backward compat — InstanceType is ignored,
        # only Name and position matter.
        $roles = @(
            [PSCustomObject]@{ Name = 'architect'; InstanceType = 'worker' },
            [PSCustomObject]@{ Name = 'engineer'; InstanceType = 'worker' },
            [PSCustomObject]@{ Name = 'qa'; InstanceType = 'evaluator' }
        )

        . $script:ResolvePipeline -PipelineString "just_to_source_functions" -ErrorAction SilentlyContinue

        $lc = Build-LifecycleV2 -RoleOverrides $roles -MaxRetries 3

        # State check — position-based: [0]=worker, [1]=reviewer
        $lc.initial_state | Should -Be "developing"
        $lc.states.developing.role | Should -Be "architect"
        $lc.states.developing.type | Should -Be "work"
        $lc.states.developing.signals.done.target | Should -Be "review"

        # Position [1] is the only lifecycle reviewer.
        $lc.states.review.role | Should -Be "engineer"
        $lc.states.review.type | Should -Be "review"
        $lc.states.review.signals.done.target | Should -Be "done"
        $lc.states.review.signals.pass.target | Should -Be "done" -Because "pass remains a legacy accepted success signal"
        @($lc.states.review.signals.Keys)[0] | Should -Be "done"

        @($lc.states.Keys) | Should -Not -Contain "review-2"

        # Review fail routes to manager triage; manager decides whether to retry.
        $lc.states.review.signals.fail.target | Should -Be "triage"
        $lc.states.review.signals.fail.PSObject.Properties.Name | Should -Not -Contain "actions"
        $lc.states.optimize.role | Should -Be "architect"
        $lc.states.optimize.type | Should -Be "work"
        $lc.states.optimize.signals.done.target | Should -Be "review"
        @($lc.states.Keys) | Should -Not -Contain "fixing"
        Assert-NoLifecycleErrorSignal $lc
    }

    It "Builds lifecycle with single candidate — QA review injected" {
        $roles = @(
            [PSCustomObject]@{ Name = 'analyst'; InstanceType = 'worker' }
        )

        . $script:ResolvePipeline -PipelineString "just_to_source_functions" -ErrorAction SilentlyContinue

        $lc = Build-LifecycleV2 -RoleOverrides $roles -MaxRetries 3

        $lc.initial_state | Should -Be "developing"
        $lc.states.developing.role | Should -Be "analyst"
        # Single candidate → QA review injected as final gate
        $lc.states.developing.signals.done.target | Should -Be "review"

        $lc.states.optimize.role | Should -Be "analyst"
        $lc.states.optimize.signals.done.target | Should -Be "review"

        # Injected QA review state
        $lc.states.review.role | Should -Be "qa"
        $lc.states.review.type | Should -Be "review"
        $lc.states.review.signals.done.target | Should -Be "done"
        $lc.states.review.signals.pass.target | Should -Be "done" -Because "pass remains a legacy accepted success signal"
        @($lc.states.review.signals.Keys)[0] | Should -Be "done"
    }

    It "Single candidate via -Roles string array also works" {
        . $script:ResolvePipeline -PipelineString "just_to_source_functions" -ErrorAction SilentlyContinue

        $lc = Build-LifecycleV2 -Roles @('qa') -MaxRetries 3

        # Position [0] is always the worker regardless of role name
        $lc.initial_state | Should -Be "developing"
        $lc.states.developing.role | Should -Be "qa"

        # Single candidate → QA review injected
        $lc.states.review.role | Should -Be "qa"
        $lc.states.review.signals.fail.target | Should -Be "triage"
        $lc.states.review.signals.fail.PSObject.Properties.Name | Should -Not -Contain "actions"
        $lc.states.review.signals.done.target | Should -Be "done"
        $lc.states.review.signals.pass.target | Should -Be "done" -Because "pass remains a legacy accepted success signal"

        Assert-NoLifecycleErrorSignal $lc
    }

    It "JSON output is valid and contains version 2" {
        $roles = @(
            [PSCustomObject]@{ Name = 'architect'; InstanceType = 'worker' },
            [PSCustomObject]@{ Name = 'qa'; InstanceType = 'evaluator' }
        )

        . $script:ResolvePipeline -PipelineString "just_to_source_functions" -ErrorAction SilentlyContinue

        $lc = Build-LifecycleV2 -RoleOverrides $roles -MaxRetries 3
        $json = $lc | ConvertTo-Json -Depth 10

        # Must be valid JSON
        $parsed = $json | ConvertFrom-Json
        $parsed.version | Should -Be 2
        $parsed.initial_state | Should -Be "developing"
        $parsed.states.done.type | Should -Be "terminal"
        $parsed.states.failed.type | Should -Be "terminal"
        @($parsed.states.PSObject.Properties.Name) | Should -Not -Contain "passed"
        @($parsed.states.PSObject.Properties.Name) | Should -Not -Contain "failed-final"
    }

    It "All generated states omit error lifecycle signals" {
        $roles = @(
            [PSCustomObject]@{ Name = 'designer'; InstanceType = 'worker' },
            [PSCustomObject]@{ Name = 'design-reviewer'; InstanceType = 'evaluator' },
            [PSCustomObject]@{ Name = 'final-qa'; InstanceType = 'evaluator' }
        )

        . $script:ResolvePipeline -PipelineString "just_to_source_functions" -ErrorAction SilentlyContinue

        $lc = Build-LifecycleV2 -RoleOverrides $roles -MaxRetries 3

        $lc.states.review | Should -Not -BeNullOrEmpty -Because "canonical review state should exist"
        $lc.states.review.type | Should -Be 'review'
        @($lc.states.Keys) | Should -Not -Contain 'review-2'
        Assert-NoLifecycleErrorSignal $lc
    }

    It "Worker and evaluator states both omit error lifecycle signals" {
        $roles = @(
            [PSCustomObject]@{ Name = 'eng'; InstanceType = 'worker' },
            [PSCustomObject]@{ Name = 'qa'; InstanceType = 'evaluator' }
        )

        . $script:ResolvePipeline -PipelineString "just_to_source_functions" -ErrorAction SilentlyContinue

        $lc = Build-LifecycleV2 -RoleOverrides $roles -MaxRetries 3

        Assert-NoLifecycleErrorSignal $lc
    }

    It "Routes security capability review to security-specialist while keeping assigned role as worker" {
        $lifecycleFile = Join-Path $TestDrive "security-lifecycle.json"

        & $script:ResolvePipeline `
            -RequiredCapabilities @("security") `
            -AssignedRole "security-engineer" `
            -OutputPath $lifecycleFile `
            -AgentsDir $script:agentsDir

        $lc = Get-Content $lifecycleFile -Raw | ConvertFrom-Json

        $lc.states.developing.role | Should -Be "security-engineer"
        $lc.states.developing.type | Should -Be "work"
        $lc.states.review.role | Should -Be "security-specialist"
        $lc.states.review.type | Should -Be "review"
    }

    It "Keeps non-security capabilities as reviewer-only routing" {
        $lifecycleFile = Join-Path $TestDrive "database-lifecycle.json"

        & $script:ResolvePipeline `
            -RequiredCapabilities @("database") `
            -AssignedRole "engineer" `
            -OutputPath $lifecycleFile `
            -AgentsDir $script:agentsDir

        $lc = Get-Content $lifecycleFile -Raw | ConvertFrom-Json

        $lc.states.developing.role | Should -Be "engineer"
        $lc.states.review.role | Should -Be "database-architect"
        $lc.states.review.type | Should -Be "review"
    }
}
