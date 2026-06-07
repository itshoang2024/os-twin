#Requires -Version 7.0

<#
.SYNOPSIS
    Runtime dependency gate — checks if a room's dependencies are satisfied.

.DESCRIPTION
    Reads DAG.json and checks the status of all upstream dependencies for a
    given room. Returns a hashtable indicating readiness.

    Returns:
      @{ Ready = $true }                                          — all deps done
      @{ Ready = $false; Reason = 'waiting'; WaitingOn = $ref }   — dep still in progress
      @{ Ready = $false; Reason = 'blocked'; BlockedBy = $ref }   — dep failed or blocked

.PARAMETER RoomDir
    Path to the war-room directory to check.
.PARAMETER WarRoomsDir
    Path to the war-rooms base directory containing DAG.json.

.EXAMPLE
    $result = ./Test-DependenciesReady.ps1 -RoomDir ".war-rooms/room-002" -WarRoomsDir ".war-rooms"
    if ($result.Ready) { # proceed }
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$RoomDir,

    [Parameter(Mandatory)]
    [string]$WarRoomsDir
)

# --- Read DAG.json ---
$dagFile = Join-Path $WarRoomsDir "DAG.json"
if (-not (Test-Path $dagFile)) {
    # No DAG = legacy mode, all rooms are independent
    return @{ Ready = $true }
}

$dag = Get-Content $dagFile -Raw | ConvertFrom-Json

# --- Get this room's task ref ---
$taskRefFile = Join-Path $RoomDir "task-ref"
if (-not (Test-Path $taskRefFile)) {
    # Can't identify this room, allow it to proceed
    return @{ Ready = $true }
}
$taskRef = (Get-Content $taskRefFile -Raw).Trim()

# --- Look up dependencies ---
$myNode = $dag.nodes.$taskRef
if (-not $myNode) {
    # Node not in DAG, allow to proceed
    return @{ Ready = $true }
}

$depsOn = $myNode.depends_on
if (-not $depsOn -or $depsOn.Count -eq 0) {
    return @{ Ready = $true }
}

# --- Check each dependency's status ---
foreach ($depRef in $depsOn) {
    $depNode = $dag.nodes.$depRef
    if (-not $depNode) {
        # Dependency not in DAG — skip (shouldn't happen if DAG was validated)
        continue
    }

    $depRoomDir = Join-Path $WarRoomsDir $depNode.room_id
    $depStatusFile = Join-Path $depRoomDir "status"

    # If the room directory doesn't exist at all, handle gracefully
    if (-not (Test-Path $depRoomDir)) {
        if ($depRef -eq 'PLAN-REVIEW') {
            # PLAN-REVIEW is implicitly approved when Start-Plan runs without --review
            # The room may not have been scaffolded if $warRoomsDir resolved differently
            continue
        }
        return @{
            Ready     = $false
            Reason    = 'waiting'
            WaitingOn = $depRef
        }
    }

    $depStatus = if (Test-Path $depStatusFile) {
        (Get-Content $depStatusFile -Raw).Trim()
    } else { "pending" }

    $depCanonical = switch ($depStatus) {
        'passed'       { 'done' }
        'failed-final' { 'failed' }
        'fixing'       { 'optimize' }
        default        { $depStatus }
    }

    switch ($depCanonical) {
        'done' {
            # This dependency is satisfied, continue checking others
        }
        { $_ -in @('failed', 'blocked') } {
            return @{
                Ready    = $false
                Reason   = 'blocked'
                BlockedBy = $depRef
            }
        }
        default {
            # pending, developing, optimize, review, triage — still in progress
            return @{
                Ready     = $false
                Reason    = 'waiting'
                WaitingOn = $depRef
            }
        }
    }
}

# All dependencies done
return @{ Ready = $true }
