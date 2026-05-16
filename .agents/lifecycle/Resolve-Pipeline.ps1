<#
.SYNOPSIS
    Generates a lifecycle.json (v2) for a war-room based on explicit pipeline,
    capabilities, candidate roles, or default fallback.
 
.PARAMETER PipelineString
    Explicit pipeline like "engineer -> security-review -> qa".
.PARAMETER RequiredCapabilities
    Array of capabilities. Used to insert review stages.
.PARAMETER AssignedRole
    The primary role. Used for role-derived pipeline generation.
.PARAMETER CandidateRoles
    Ordered list of candidate roles from DAG.json. [0] = primary worker,
    [1..N] = reviewers. Takes precedence over RequiredCapabilities.
.PARAMETER MaxRetries
    Max retries for the lifecycle. Default: 3.
.PARAMETER OutputPath
    Where to write the lifecycle.json. If empty, outputs JSON to stdout.
.PARAMETER AgentsDir
    Path to the .agents directory.
 
.OUTPUTS
    JSON string (lifecycle definition) or writes to OutputPath.
#>
[CmdletBinding()]
param(
    [string]$PipelineString = '',
    [string[]]$RequiredCapabilities = @(),
    [string]$AssignedRole = 'engineer',
    [string[]]$CandidateRoles = @(),
    [int]$MaxRetries = 3,
    [string]$OutputPath = '',
    [string]$AgentsDir = ''
)
 
if (-not $AgentsDir) {
    $AgentsDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}
 
$defaultLifecyclePath = Join-Path $AgentsDir "lifecycle" "default.json"
 
# ------------------------------------------------------------------
# V2 LIFECYCLE BUILDER — signal-based, role-per-state state machine
#
# Position-based role assignment:
#   Roles[0]    = worker     → "developing" + "optimize" + "fixing" states
#   Roles[1..N] = evaluators → "review", "review-2", … states
#   No evaluators? → inject default QA review as "review" state
# ------------------------------------------------------------------
function Build-LifecycleV2 {
    param(
        [string[]]$Roles,              # Ordered list: [0] = worker, [1..N] = evaluators
        [PSCustomObject[]]$RoleOverrides,  # Backward-compat: array of @{ Name; InstanceType }
        [int]$MaxRetries = 3
    )

    # --- Backward compatibility: normalize -RoleOverrides to -Roles ---
    if (-not $Roles -and $RoleOverrides) {
        $Roles = @($RoleOverrides | ForEach-Object { $_.Name })
    }

    $states = [ordered]@{}

    # Position-based: first role is always the worker
    $workerRole = $Roles[0]
    $evaluatorRoles = @()
    if ($Roles.Count -gt 1) {
        $evaluatorRoles = @($Roles[1..($Roles.Count - 1)])
    }

    # Compute evaluator state names: review, review-2, review-3, ...
    $evaluatorStateNames = @()
    for ($i = 0; $i -lt $evaluatorRoles.Count; $i++) {
        if ($i -eq 0) {
            $evaluatorStateNames += "review"
        } else {
            $evaluatorStateNames += "review-$($i + 1)"
        }
    }

    # First evaluator target (or injected QA "review" when no evaluators)
    $hasExplicitEvaluators = $evaluatorRoles.Count -gt 0
    $firstEvalTarget = if ($hasExplicitEvaluators) {
        $evaluatorStateNames[0]
    } else {
        'review'
    }

    # --- Worker states: developing + optimize + fixing ---
    $states['developing'] = [ordered]@{
        role    = $workerRole
        type    = 'work'
        signals = [ordered]@{
            done  = [ordered]@{ target = $firstEvalTarget }
            error = [ordered]@{ target = 'failed'; actions = @('increment_retries') }
        }
    }
    $states['optimize'] = [ordered]@{
        role    = $workerRole
        type    = 'work'
        signals = [ordered]@{
            done  = [ordered]@{ target = $firstEvalTarget }
            error = [ordered]@{ target = 'failed'; actions = @('increment_retries') }
        }
    }
    $states['fixing'] = [ordered]@{
        role    = $workerRole
        type    = 'work'
        signals = [ordered]@{
            done  = [ordered]@{ target = $firstEvalTarget }
            error = [ordered]@{ target = 'failed'; actions = @('increment_retries') }
        }
    }

    # --- Evaluator states: review, review-2, ... ---
    for ($i = 0; $i -lt $evaluatorRoles.Count; $i++) {
        $evalRole = $evaluatorRoles[$i]
        $stateName = $evaluatorStateNames[$i]
        $nextTarget = if ($i -lt ($evaluatorRoles.Count - 1)) {
            $evaluatorStateNames[$i + 1]
        } else {
            'passed'
        }

        $states[$stateName] = [ordered]@{
            role    = $evalRole
            type    = 'review'
            signals = [ordered]@{
                pass     = [ordered]@{ target = $nextTarget }
                done     = [ordered]@{ target = 'passed' }
                fail     = [ordered]@{ target = 'optimize'; actions = @('increment_retries', 'post_fix') }
                escalate = [ordered]@{ target = 'triage' }
                error    = [ordered]@{ target = 'failed'; actions = @('increment_retries') }
            }
        }
    }

    # --- Injected QA review (when no evaluators in candidate list) ---
    if (-not $hasExplicitEvaluators) {
        $states['review'] = [ordered]@{
            role    = 'qa'
            type    = 'review'
            signals = [ordered]@{
                pass     = [ordered]@{ target = 'passed' }
                done     = [ordered]@{ target = 'passed' }
                fail     = [ordered]@{ target = 'optimize'; actions = @('increment_retries', 'post_fix') }
                escalate = [ordered]@{ target = 'triage' }
                error    = [ordered]@{ target = 'failed'; actions = @('increment_retries') }
            }
        }
    }

    # --- triage: manager handles escalations ---
    $states['triage'] = [ordered]@{
        role    = 'manager'
        type    = 'triage'
        signals = [ordered]@{
            fix      = [ordered]@{ target = 'optimize'; actions = @('increment_retries') }
            redesign = [ordered]@{ target = 'developing'; actions = @('increment_retries', 'revise_brief') }
            reject   = [ordered]@{ target = 'failed-final' }
        }
    }

    # --- failed: auto-decision node ---
    $states['failed'] = [ordered]@{
        role            = 'manager'
        type            = 'decision'
        auto_transition = $true
        signals         = [ordered]@{
            retry   = [ordered]@{ target = 'developing'; guard = 'retries < max_retries' }
            exhaust = [ordered]@{ target = 'failed-final'; guard = 'retries >= max_retries' }
        }
    }

    # --- terminal states ---
    $states['passed']       = [ordered]@{ type = 'terminal' }
    $states['failed-final'] = [ordered]@{ type = 'terminal' }

    return [ordered]@{
        version       = 2
        initial_state = 'developing'
        max_retries   = $MaxRetries
        states        = $states
    }
}

# ------------------------------------------------------------------
# RESOLVE ROLES
# ------------------------------------------------------------------
$resolver = Join-Path $AgentsDir "roles" "_base" "Resolve-Role.ps1"
$candidateList = @()

# MODE 1: Explicit pipeline string
if ($PipelineString) {
    $candidateList = @(($PipelineString -split '\s*->\s*') | ForEach-Object { $_.Trim() } | Where-Object { $_ })
}
# MODE 2: CandidateRoles from DAG
elseif ($CandidateRoles.Count -gt 0) {
    $orchestratorRoles = @('manager')
    $candidateList = @($CandidateRoles | Where-Object { $_ -notin $orchestratorRoles })
}
# MODE 3: Capability-derived pipeline
elseif ($RequiredCapabilities.Count -gt 0) {
    $baseRole = $AssignedRole -replace ':.*$', ''
    $capReviewerMap = @{
        'security'       = 'security-engineer'
        'database'       = 'database-architect'
        'architecture'   = 'architect'
        'infrastructure' = 'devops'
        'accessibility'  = 'accessibility-specialist'
    }
    $candidateList = @($baseRole)
    foreach ($cap in $RequiredCapabilities) {
        $capLower = $cap.ToLower()
        if ($capReviewerMap.ContainsKey($capLower)) {
            $candidateList += $capReviewerMap[$capLower]
        }
    }
}
# MODE 4: Default fallback
else {
    if (Test-Path $defaultLifecyclePath) {
        $resolvedLifecycle = Get-Content $defaultLifecyclePath -Raw | ConvertFrom-Json
    } else {
        $candidateList = @($AssignedRole)
    }
}

if (-not $resolvedLifecycle -and $candidateList.Count -gt 0) {
    # Strip instance suffixes (e.g. "engineer:fe" → "engineer") for state naming
    $roleNames = @($candidateList | ForEach-Object { $_ -replace ':.*$', '' })
    $resolvedLifecycle = Build-LifecycleV2 -Roles $roleNames -MaxRetries $MaxRetries
}

# ------------------------------------------------------------------
# Output
# ------------------------------------------------------------------
$json = $resolvedLifecycle | ConvertTo-Json -Depth 10
 
if ($OutputPath) {
    $json | Out-File -FilePath $OutputPath -Encoding utf8 -Force
} else {
    Write-Output $json
}