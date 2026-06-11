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
#   Roles[0]    = worker     -> "developing" + "optimize"
#   Roles[1]    = evaluator  -> "review"
#   No evaluator? -> inject default QA review as "review"
#
# Lifecycle state names are intentionally small and canonical. Extra candidate
# roles can remain in room metadata, but they no longer expand the state graph.
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

    $reviewRole = if ($evaluatorRoles.Count -gt 0) { $evaluatorRoles[0] } else { 'qa' }

    # --- Worker states: developing + optimize ---
    $states['developing'] = [ordered]@{
        role    = $workerRole
        type    = 'work'
        signals = [ordered]@{
            done = [ordered]@{ target = 'review' }
        }
    }
    $states['optimize'] = [ordered]@{
        role    = $workerRole
        type    = 'work'
        signals = [ordered]@{
            done = [ordered]@{ target = 'review' }
        }
    }

    # --- Single canonical review state ---
    $states['review'] = [ordered]@{
        role    = $reviewRole
        type    = 'review'
        signals = [ordered]@{
            done     = [ordered]@{ target = 'done' }
            pass     = [ordered]@{ target = 'done' } # legacy success signal
            fail     = [ordered]@{ target = 'triage' }
            escalate = [ordered]@{ target = 'triage' }
        }
    }

    # --- triage: manager handles escalations ---
    $states['triage'] = [ordered]@{
        role    = 'manager'
        type    = 'triage'
        signals = [ordered]@{
            done     = [ordered]@{ target = 'review' }
            fix      = [ordered]@{ target = 'optimize'; actions = @('increment_retries') }
            redesign = [ordered]@{ target = 'developing'; actions = @('increment_retries', 'revise_brief') }
            reject   = [ordered]@{ target = 'failed' }
        }
    }

    # --- terminal states ---
    $states['done']   = [ordered]@{ type = 'terminal' }
    $states['failed'] = [ordered]@{ type = 'terminal' }

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

    # Security is special in this PR: it has a dedicated worker/evaluator pair,
    # so Capabilities: security should use security-engineer as the worker and
    # security-specialist as the reviewer. Other capabilities keep the existing
    # behavior: assigned worker + capability-specific reviewer.
    $capPrimaryMap = @{
        'security' = 'security-engineer'
    }
    if ($baseRole -eq 'engineer') {
        foreach ($cap in $RequiredCapabilities) {
            $capLower = $cap.ToLower()
            if ($capPrimaryMap.ContainsKey($capLower)) {
                $baseRole = $capPrimaryMap[$capLower]
                break   # first matching capability sets the primary worker
            }
        }
    }

    $capReviewerMap = @{
        'security'       = 'security-specialist'
        'database'       = 'database-architect'
        'architecture'   = 'architect'
        'infrastructure' = 'devops'
        'accessibility'  = 'accessibility-specialist'
    }
    $candidateList = @($baseRole)
    foreach ($cap in $RequiredCapabilities) {
        $capLower = $cap.ToLower()
        if ($capReviewerMap.ContainsKey($capLower)) {
            $reviewer = $capReviewerMap[$capLower]
            # Only add reviewer when it is distinct from the primary worker
            if ($reviewer -ne $baseRole -and $candidateList -notcontains $reviewer) {
                $candidateList += $reviewer
            }
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
