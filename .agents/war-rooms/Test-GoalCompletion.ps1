<#
.SYNOPSIS
    Cross-checks war-room goals against engineer output to verify completion.

.DESCRIPTION
    Reads the config.json goal contract (definition_of_done, acceptance_criteria)
    and the engineer's output/artifacts, then evaluates each goal as met/not_met/partial.

    This is the automated goal gate that runs after QA pass but before final "done" status.

.PARAMETER RoomDir
    Path to the war-room directory.
.PARAMETER EngineerOutput
    Optional. If not provided, reads from artifacts/engineer-output.txt.
.PARAMETER Strict
    If set, all goals must be met for overall pass. Default: true.

.OUTPUTS
    PSCustomObject with OverallStatus, GoalResults, and Summary.

.EXAMPLE
    $result = ./Test-GoalCompletion.ps1 -RoomDir "./war-rooms/room-001"
    if ($result.OverallStatus -eq "passed") { Write-Host "All goals met!" }
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$RoomDir,

    [string]$EngineerOutput = '',

    [bool]$Strict = $true
)

# --- Load config.json goal contract ---
$configFile = Join-Path $RoomDir "config.json"
if (-not (Test-Path $configFile)) {
    throw "No config.json found in war-room: $RoomDir"
}

$config = Get-Content $configFile -Raw | ConvertFrom-Json

# --- Gather evidence sources ---
# 1. Engineer output
if (-not $EngineerOutput) {
    $outputFile = Join-Path $RoomDir "artifacts" "engineer-output.txt"
    if (Test-Path $outputFile) {
        $EngineerOutput = Get-Content $outputFile -Raw
    }
    else {
        $EngineerOutput = ""
    }
}

# 2. QA output
$qaOutput = ""
$qaFile = Join-Path $RoomDir "artifacts" "qa-output.txt"
if (Test-Path $qaFile) {
    $qaOutput = Get-Content $qaFile -Raw
}

# 3. Channel messages (done messages)
$channelEvidence = ""
$channelFile = Join-Path $RoomDir "channel.jsonl"
if (Test-Path $channelFile) {
    $lines = Get-Content $channelFile -Encoding utf8 | Where-Object { $_.Trim() }
    foreach ($line in $lines) {
        try {
            $msg = $line | ConvertFrom-Json
            if ($msg.type -in @('done', 'pass')) {
                $channelEvidence += "$($msg.body)`n"
            }
        }
        catch { Write-Verbose "Skipping malformed channel line: $($_.Exception.Message)" }
    }
}

# 4. TASKS.md (for epics)
$tasksMd = ""
$tasksFile = Join-Path $RoomDir "TASKS.md"
if (Test-Path $tasksFile) {
    $tasksMd = Get-Content $tasksFile -Raw
}

# Combined evidence corpus for searching
$allEvidence = @($EngineerOutput, $qaOutput, $channelEvidence, $tasksMd) -join "`n"

# --- Negation context detection ---
function Test-NegationContext {
    <#
    .SYNOPSIS
        Checks if a match in text appears within a negation context.
    .DESCRIPTION
        Looks for negation words (not, no, never, cannot, didn't, won't, etc.)
        within a window of ~80 characters before the match position.
        80 chars ≈ 5 average English words, giving enough context to catch
        "was not implemented" or "hasn't been completed" while avoiding
        false positives from negations in a different clause.
    #>
    [CmdletBinding()]
    [OutputType([bool])]
    param(
        [Parameter(Mandatory)][string]$Text,
        [Parameter(Mandatory)][int]$MatchIndex,
        [Parameter(Mandatory)][int]$MatchLength
    )

    $negationWords = @('not', 'no', 'never', 'neither', 'cannot', 'cant', "can't",
                       "couldn't", "didn't", "doesn't", "don't", "hasn't", "haven't",
                       "hadn't", "isn't", "aren't", "wasn't", "weren't", "won't",
                       "wouldn't", "shouldn't", "mustn't", 'without', 'unable',
                       'failed', 'failing', 'fail', 'missing', 'lack', 'lacks')

    # Get the ~80 chars before the match
    $windowStart = [Math]::Max(0, $MatchIndex - 80)
    $beforeText = $Text.Substring($windowStart, $MatchIndex - $windowStart)

    # Check if any negation word appears in the preceding context
    foreach ($neg in $negationWords) {
        if ($beforeText -match "\b$([regex]::Escape($neg))\b") {
            return $true
        }
    }
    return $false
}

# --- Goal evaluation function with negation awareness ---
function Test-GoalMet {
    param(
        [string]$Goal,
        [string]$Evidence
    )

    $goalLower = $Goal.ToLower().Trim()
    $evidenceLower = $Evidence.ToLower()

    # --- Strategy 1: Exact or near-exact phrase match ---
    $escapedGoal = [regex]::Escape($goalLower)
    if ($evidenceLower -match $escapedGoal) {
        # Check for negation near the match
        $matchIdx = $evidenceLower.IndexOf($goalLower)
        if (-not (Test-NegationContext -Text $evidenceLower -MatchIndex $matchIdx -MatchLength $goalLower.Length)) {
            return [PSCustomObject]@{
                Status   = "met"
                Evidence = "Exact phrase match found in evidence"
                Score    = 1.0
            }
        }
    }

    # --- Strategy 2: Key term matching with negation awareness ---
    $stopWords = @('the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been',
                   'has', 'have', 'had', 'do', 'does', 'did', 'will', 'would',
                   'could', 'should', 'may', 'might', 'must', 'shall', 'can',
                   'with', 'for', 'and', 'or', 'but', 'in', 'on', 'at', 'to',
                   'of', 'by', 'from', 'up', 'out', 'if', 'about', 'into',
                   'through', 'during', 'before', 'after', 'above', 'below',
                   'between', 'each', 'all', 'any', 'both', 'few', 'more',
                   'most', 'other', 'some', 'such', 'no', 'nor', 'not', 'only',
                   'own', 'same', 'so', 'than', 'too', 'very', 'that', 'this',
                   'these', 'those')

    $keyTerms = ($goalLower -split '\W+') | Where-Object {
        $_.Length -gt 2 -and $_ -notin $stopWords
    }

    if ($keyTerms.Count -eq 0) {
        return [PSCustomObject]@{
            Status   = "not_met"
            Evidence = "No key terms extracted from goal"
            Score    = 0.0
        }
    }

    $matchedTerms = @()
    $negatedTerms = @()
    foreach ($term in $keyTerms) {
        $termPattern = "\b$([regex]::Escape($term))\b"
        $termMatches = [regex]::Matches($evidenceLower, $termPattern)
        if ($termMatches.Count -gt 0) {
            # Check if ANY occurrence is in a non-negated context
            $hasPositiveMatch = $false
            foreach ($tm in $termMatches) {
                if (-not (Test-NegationContext -Text $evidenceLower -MatchIndex $tm.Index -MatchLength $tm.Length)) {
                    $hasPositiveMatch = $true
                    break
                }
            }
            if ($hasPositiveMatch) {
                $matchedTerms += $term
            } else {
                $negatedTerms += $term
            }
        }
    }

    $matchRatio = $matchedTerms.Count / $keyTerms.Count

    # Penalize if key terms were found but negated
    $negationPenalty = if ($negatedTerms.Count -gt 0) { " (negated: $($negatedTerms -join ', '))" } else { "" }

    if ($matchRatio -ge 0.7) {
        return [PSCustomObject]@{
            Status   = "met"
            Evidence = "Key terms matched: $($matchedTerms -join ', ') ($([math]::Round($matchRatio * 100))%)$negationPenalty"
            Score    = $matchRatio
        }
    }
    elseif ($matchRatio -ge 0.4) {
        return [PSCustomObject]@{
            Status   = "partial"
            Evidence = "Partial key terms: $($matchedTerms -join ', ') ($([math]::Round($matchRatio * 100))%)$negationPenalty"
            Score    = $matchRatio
        }
    }
    else {
        return [PSCustomObject]@{
            Status   = "not_met"
            Evidence = "Low match: $($matchedTerms -join ', ') ($([math]::Round($matchRatio * 100))%)$negationPenalty"
            Score    = $matchRatio
        }
    }
}

# --- Evaluate Definition of Done ---
$dodResults = [System.Collections.Generic.List[PSObject]]::new()
$dodGoals = $config.goals.definition_of_done
if ($dodGoals) {
    foreach ($goal in $dodGoals) {
        $result = Test-GoalMet -Goal $goal -Evidence $allEvidence
        $dodResults.Add([PSCustomObject]@{
            category = "definition_of_done"
            goal     = $goal
            status   = $result.Status
            evidence = $result.Evidence
            score    = $result.Score
        })
    }
}

# --- Evaluate Acceptance Criteria ---
$acResults = [System.Collections.Generic.List[PSObject]]::new()
$acGoals = $config.goals.acceptance_criteria
if ($acGoals) {
    foreach ($goal in $acGoals) {
        $result = Test-GoalMet -Goal $goal -Evidence $allEvidence
        $acResults.Add([PSCustomObject]@{
            category = "acceptance_criteria"
            goal     = $goal
            status   = $result.Status
            evidence = $result.Evidence
            score    = $result.Score
        })
    }
}

# --- Check TASKS.md completion (for epics) ---
$taskResults = [System.Collections.Generic.List[PSObject]]::new()
if ($tasksMd) {
    $totalTasks = ([regex]::Matches($tasksMd, '- \[[ x]\]')).Count
    $completedTasks = ([regex]::Matches($tasksMd, '- \[x\]')).Count

    $taskResults.Add([PSCustomObject]@{
        category = "task_completion"
        goal     = "All sub-tasks completed"
        status   = if ($totalTasks -gt 0 -and $completedTasks -eq $totalTasks) { "met" }
                   elseif ($completedTasks -gt 0) { "partial" }
                   else { "not_met" }
        evidence = "$completedTasks/$totalTasks tasks checked off"
        score    = if ($totalTasks -gt 0) { [math]::Round($completedTasks / $totalTasks, 2) } else { 0 }
    })
}

# --- Aggregate results ---
$allResults = @()
$allResults += $dodResults.ToArray()
$allResults += $acResults.ToArray()
$allResults += $taskResults.ToArray()

$totalGoals = $allResults.Count
$metGoals = ($allResults | Where-Object { $_.status -eq "met" }).Count
$partialGoals = ($allResults | Where-Object { $_.status -eq "partial" }).Count
$notMetGoals = ($allResults | Where-Object { $_.status -eq "not_met" }).Count

# --- Determine overall status ---
$overallStatus = if ($totalGoals -eq 0) {
    "passed"  # No goals defined = auto-pass
}
elseif ($Strict) {
    if ($metGoals -eq $totalGoals) { "passed" }
    elseif ($notMetGoals -gt 0) { "failed" }
    else { "partial" }
}
else {
    if ($metGoals -ge [math]::Ceiling($totalGoals * 0.7)) { "passed" }
    elseif ($notMetGoals -gt [math]::Floor($totalGoals * 0.5)) { "failed" }
    else { "partial" }
}

$avgScore = if ($totalGoals -gt 0) {
    [math]::Round(($allResults | Measure-Object -Property score -Average).Average, 2)
} else { 1.0 }

# --- Build output ---
$output = [PSCustomObject]@{
    OverallStatus = $overallStatus
    Score         = $avgScore
    GoalResults   = $allResults
    Summary       = [PSCustomObject]@{
        total   = $totalGoals
        met     = $metGoals
        partial = $partialGoals
        not_met = $notMetGoals
    }
}

Write-Output $output
