<#
.SYNOPSIS
    Generates a goal-verification.json report for a war-room.

.DESCRIPTION
    Runs Test-GoalCompletion and writes the structured report to
    goal-verification.json in the war-room directory.

    This report is read by:
    - Manager loop (gate before terminal "done" status)
    - Get-WarRoomStatus (dashboard goal completion display)
    - Remove-WarRoom archive mode

.PARAMETER RoomDir
    Path to the war-room directory.

.OUTPUTS
    The path to the generated goal-verification.json file.

.EXAMPLE
    ./New-GoalReport.ps1 -RoomDir "./war-rooms/room-001"
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$RoomDir
)

$testGoalCompletion = Join-Path $PSScriptRoot "Test-GoalCompletion.ps1"

if (-not (Test-Path $testGoalCompletion)) {
    throw "Test-GoalCompletion.ps1 not found at: $testGoalCompletion"
}

# --- Run goal verification ---
$verificationResult = & $testGoalCompletion -RoomDir $RoomDir

# --- Build the report ---
$ts = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
$taskRef = if (Test-Path (Join-Path $RoomDir "task-ref")) {
    (Get-Content (Join-Path $RoomDir "task-ref") -Raw).Trim()
} else { "UNKNOWN" }

$report = [ordered]@{
    version        = 1
    generated_at   = $ts
    room_id        = (Split-Path $RoomDir -Leaf)
    task_ref       = $taskRef
    overall_status = $verificationResult.OverallStatus
    overall_score  = $verificationResult.Score

    summary = [ordered]@{
        total_goals   = $verificationResult.Summary.total
        goals_met     = $verificationResult.Summary.met
        goals_partial = $verificationResult.Summary.partial
        goals_not_met = $verificationResult.Summary.not_met
    }

    goals = @()
}

# Add individual goal results
foreach ($goalResult in $verificationResult.GoalResults) {
    $report.goals += [ordered]@{
        category = $goalResult.category
        goal     = $goalResult.goal
        status   = $goalResult.status
        evidence = $goalResult.evidence
        score    = $goalResult.score
    }
}

# --- Write the report ---
$reportFile = Join-Path $RoomDir "goal-verification.json"
$report | ConvertTo-Json -Depth 10 | Out-File -FilePath $reportFile -Encoding utf8

# --- Console output ---
$statusColor = switch ($verificationResult.OverallStatus) {
    'passed'  { 'Green' }
    'partial' { 'Yellow' }
    'failed'  { 'Red' }
    default   { 'White' }
}

Write-Host ""
Write-Host "[GOAL VERIFICATION] $taskRef — $($verificationResult.OverallStatus.ToUpper())" -ForegroundColor $statusColor
Write-Host "  Score: $($verificationResult.Score)"
Write-Host "  Goals: $($verificationResult.Summary.met) met / $($verificationResult.Summary.partial) partial / $($verificationResult.Summary.not_met) not met (total: $($verificationResult.Summary.total))"

foreach ($g in $verificationResult.GoalResults) {
    $icon = switch ($g.status) {
        'met'     { '✅' }
        'partial' { '🟡' }
        'not_met' { '❌' }
    }
    Write-Host "  $icon $($g.goal) — $($g.evidence)"
}

Write-Host "  Report: $reportFile"
Write-Host ""

Write-Output $reportFile
