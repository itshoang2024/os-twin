<#
.SYNOPSIS
    Updates progress tracking files for the current plan run.

.DESCRIPTION
    Scans all war-rooms, computes completion stats, and writes
    PROGRESS.md and progress.json to $WarRoomsDir.

.PARAMETER WarRoomsDir
    Path to the war-rooms base directory.

.EXAMPLE
    ./Update-Progress.ps1 -WarRoomsDir ".war-rooms"
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$WarRoomsDir
)

$rooms = Get-ChildItem -Path $WarRoomsDir -Directory -Filter "room-*" -ErrorAction SilentlyContinue

$total = 0
$done = 0
$failed = 0
$blocked = 0
$active = 0
$pending = 0
$roomDetails = @()

foreach ($rd in $rooms) {
    $total++
    $statusFile = Join-Path $rd.FullName "status"
    $status = if (Test-Path $statusFile) { (Get-Content $statusFile -Raw).Trim() } else { "pending" }
    $taskRef = if (Test-Path (Join-Path $rd.FullName "task-ref")) {
        (Get-Content (Join-Path $rd.FullName "task-ref") -Raw).Trim()
    } else { "?" }

    $canonicalStatus = switch ($status) {
        'passed'       { 'done' }
        'failed-final' { 'failed' }
        'fixing'       { 'optimize' }
        default        { $status }
    }

    switch ($canonicalStatus) {
        'done'    { $done++ }
        'failed'  { $failed++ }
        'blocked' { $blocked++ }
        'pending' { $pending++ }
        default   { $active++ }
    }

    $roomDetails += [ordered]@{
        room_id  = $rd.Name
        task_ref = $taskRef
        status   = $canonicalStatus
        raw_status = $status
    }
}

$pctComplete = if ($total -gt 0) { [math]::Round(($done / $total) * 100, 1) } else { 0 }

# --- Read DAG for critical path progress ---
$cpProgress = ""
$dagFile = Join-Path $WarRoomsDir "DAG.json"
if (Test-Path $dagFile) {
    $dag = Get-Content $dagFile -Raw | ConvertFrom-Json
    if ($dag.critical_path) {
        $cpLen = $dag.critical_path.Count
        $cpPassed = 0
        foreach ($cpRef in $dag.critical_path) {
            $cpNode = $dag.nodes.$cpRef
            if ($cpNode) {
                $cpRoomDir = Join-Path $WarRoomsDir $cpNode.room_id
                $cpStatus = if (Test-Path (Join-Path $cpRoomDir "status")) {
                    (Get-Content (Join-Path $cpRoomDir "status") -Raw).Trim()
                } else { "pending" }
                $cpCanonical = switch ($cpStatus) {
                    'passed'       { 'done' }
                    'failed-final' { 'failed' }
                    default        { $cpStatus }
                }
                if ($cpCanonical -eq 'done') { $cpPassed++ }
            }
        }
        $cpProgress = "$cpPassed/$cpLen"
    }
}

# --- Write progress.json ---
$progressData = [ordered]@{
    updated_at     = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    total          = $total
    done           = $done
    passed         = $done
    failed         = $failed
    blocked        = $blocked
    active         = $active
    pending        = $pending
    pct_complete   = $pctComplete
    critical_path  = $cpProgress
    rooms          = $roomDetails
}
$progressData | ConvertTo-Json -Depth 5 | Out-File -FilePath (Join-Path $WarRoomsDir "progress.json") -Encoding utf8

# --- Write PROGRESS.md ---
$blockedList = $roomDetails | Where-Object { $_.status -eq 'blocked' }
$failedList = $roomDetails | Where-Object { $_.status -eq 'failed' }

$md = @"
# Progress Report

> Updated: $(Get-Date -Format 'yyyy-MM-ddTHH:mm:ssZ' -AsUTC)

## Summary

| Metric | Value |
|--------|-------|
| Total | $total |
| Done | $done |
| Failed | $failed |
| Blocked | $blocked |
| Active | $active |
| Pending | $pending |
| Complete | $pctComplete% |
$(if ($cpProgress) { "| Critical Path | $cpProgress |" })

## Room Status

$(($roomDetails | ForEach-Object { "- **$($_.task_ref)** ($($_.room_id)): ``$($_.status)``" }) -join "`n")
$(if ($blockedList.Count -gt 0) {
"`n## Blocked Rooms`n`n$(($blockedList | ForEach-Object { "- $($_.task_ref) ($($_.room_id))" }) -join "`n")"
})
$(if ($failedList.Count -gt 0) {
"`n## Failed Rooms`n`n$(($failedList | ForEach-Object { "- $($_.task_ref) ($($_.room_id))" }) -join "`n")"
})
"@

$md | Out-File -FilePath (Join-Path $WarRoomsDir "PROGRESS.md") -Encoding utf8
