<#
.SYNOPSIS
    Shows status of all war-rooms with optional JSON or live watch mode.

.DESCRIPTION
    Scans the war-rooms directory and displays status, retries, message count,
    active PIDs, goal completion, and last activity for each room.

    Replaces: war-rooms/status.sh

.PARAMETER WarRoomsDir
    Base directory to scan for war-rooms. Default: WARROOMS_DIR env or script dir.
.PARAMETER JsonOutput
    Output as JSON instead of formatted table.
.PARAMETER Watch
    Continuously refresh the display every few seconds.
.PARAMETER WatchInterval
    Seconds between refreshes in watch mode. Default: 3.
.PARAMETER ProjectDir
    Optional project directory (resolves war-rooms from project/.war-rooms).

.EXAMPLE
    ./Get-WarRoomStatus.ps1
    ./Get-WarRoomStatus.ps1 -JsonOutput
    ./Get-WarRoomStatus.ps1 -Watch
#>
[CmdletBinding()]
param(
    [string]$WarRoomsDir = '',
    [switch]$JsonOutput,
    [switch]$Watch,
    [int]$WatchInterval = 3,
    [string]$ProjectDir = ''
)

# --- Status index helper: efficient room-by-status lookup ---
function Get-RoomsByStatus {
    <#
    .SYNOPSIS
        Returns room directories that match a given status, without loading full room data.
    .DESCRIPTION
        Reads only the lightweight 'status' file in each room directory to filter rooms.
        Rooms without a status file are treated as 'unknown'.
        This avoids the overhead of loading config.json, channel.jsonl, and other files
        when you only need to know which rooms are in a particular state.
    #>
    [CmdletBinding()]
    [OutputType([System.IO.DirectoryInfo[]])]
    param(
        [Parameter(Mandatory)][string]$BaseDir,
        [Parameter(Mandatory)][string[]]$Status
    )

    Get-ChildItem -Path $BaseDir -Directory -Filter "room-*" -ErrorAction SilentlyContinue |
        Where-Object {
            $statusFile = Join-Path $_.FullName "status"
            if (Test-Path $statusFile) {
                $roomStatus = (Get-Content $statusFile -Raw).Trim()
                $roomStatus -in $Status
            } else {
                'unknown' -in $Status
            }
        }
}

# --- Resolve war-rooms directory ---
if ($ProjectDir) {
    $WarRoomsDir = Join-Path $ProjectDir ".war-rooms"
}
if (-not $WarRoomsDir) {
    $WarRoomsDir = if ($env:WARROOMS_DIR) { $env:WARROOMS_DIR }
                   else { $PSScriptRoot }
}

function Get-StatusData {
    param([string]$BaseDir)

    $rooms = @()
    $summary = @{
        total       = 0
        pending     = 0
        developing  = 0
        optimize    = 0
        review      = 0
        done        = 0
        passed      = 0
        failed      = 0
    }

    $roomDirs = Get-ChildItem -Path $BaseDir -Directory -Filter "room-*" -ErrorAction SilentlyContinue
    foreach ($dir in $roomDirs) {
        $summary.total++
        $roomPath = $dir.FullName

        $status = if (Test-Path (Join-Path $roomPath "status")) {
            (Get-Content (Join-Path $roomPath "status") -Raw).Trim()
        } else { "unknown" }

        $taskRef = if (Test-Path (Join-Path $roomPath "task-ref")) {
            (Get-Content (Join-Path $roomPath "task-ref") -Raw).Trim()
        } else { "N/A" }

        $retries = if (Test-Path (Join-Path $roomPath "retries")) {
            (Get-Content (Join-Path $roomPath "retries") -Raw).Trim()
        } else { "0" }

        # Message count and last activity - efficient streaming approach
        # Uses StreamReader to avoid loading entire channel.jsonl into memory.
        # For rooms with thousands of messages this prevents large RAM spikes.
        $msgCount = 0
        $lastActivity = "N/A"
        $channelFile = Join-Path $roomPath "channel.jsonl"
        if (Test-Path $channelFile) {
            $fileInfo = [System.IO.FileInfo]::new($channelFile)
            if ($fileInfo.Length -gt 0) {
                # Count lines without loading entire file
                $reader = [System.IO.StreamReader]::new($channelFile)
                $lastLine = $null
                try {
                    while ($null -ne ($line = $reader.ReadLine())) {
                        if ($line.Trim()) {
                            $msgCount++
                            $lastLine = $line
                        }
                    }
                } finally {
                    $reader.Close()
                    $reader.Dispose()
                }
                # Parse only the last line for timestamp
                if ($lastLine) {
                    try {
                        $lastMsg = $lastLine | ConvertFrom-Json
                        $lastActivity = $lastMsg.ts
                    } catch {
                        Write-Verbose "Failed to parse last channel message in $($dir.Name): $($_.Exception.Message)"
                    }
                }
            }
        }

        # Active PIDs
        $activePids = @()
        $pidDir = Join-Path $roomPath "pids"
        if (Test-Path $pidDir) {
            Get-ChildItem -Path $pidDir -Filter "*.pid" -ErrorAction SilentlyContinue | ForEach-Object {
                $pidVal = (Get-Content $_.FullName -Raw).Trim()
                if ($pidVal -match '^\d+$') {
                    try {
                        $proc = Get-Process -Id ([int]$pidVal) -ErrorAction Stop
                        if ($proc) { $activePids += $pidVal }
                    }
                    catch { Write-Verbose "PID $pidVal in $($dir.Name) is no longer running" }
                }
            }
        }
        $pidStr = if ($activePids.Count -gt 0) { $activePids -join ',' } else { '-' }

        # Goal completion (from config.json)
        $goalsMet = 0
        $goalsTotal = 0
        $configFile = Join-Path $roomPath "config.json"
        if (Test-Path $configFile) {
            try {
                $roomConfig = Get-Content $configFile -Raw | ConvertFrom-Json
                $goalsTotal = $roomConfig.goals.definition_of_done.Count
            }
            catch { Write-Verbose "Failed to parse config.json in $($dir.Name): $($_.Exception.Message)" }
        }
        $goalVerifFile = Join-Path $roomPath "goal-verification.json"
        if (Test-Path $goalVerifFile) {
            try {
                $goalReport = Get-Content $goalVerifFile -Raw | ConvertFrom-Json
                $goalsMet = ($goalReport.goals | Where-Object { $_.status -eq "met" }).Count
            }
            catch { Write-Verbose "Failed to parse goal-verification.json in $($dir.Name): $($_.Exception.Message)" }
        }

        # Count by status — canonical state names (principle 5)
        # 'engineering' is a legacy alias for 'developing'; both map to the same counter.
        # 'review', 'review-2', 'review-3' are position-based evaluator states.
        $canonicalStatus = switch ($status) {
            'passed'       { 'done' }
            'failed-final' { 'failed' }
            'fixing'       { 'optimize' }
            default        { $status }
        }

        switch -Regex ($canonicalStatus) {
            '^pending$'         { $summary.pending++ }
            '^(engineering|developing)$' { $summary.developing++ }
            '^optimize$'        { $summary.optimize++ }
            '^review(-\d+)?$'   { $summary.review++ }
            '^done$'            { $summary.done++; $summary.passed++ }
            '^failed$'          { $summary.failed++ }
        }

        $rooms += [PSCustomObject]@{
            room_id       = $dir.Name
            task_ref      = $taskRef
            status        = $canonicalStatus
            raw_status    = $status
            retries       = [int]$retries
            messages      = $msgCount
            active_pids   = $pidStr
            goals         = "$goalsMet/$goalsTotal"
            last_activity = $lastActivity
        }
    }

    return @{
        rooms   = $rooms
        summary = $summary
    }
}

function Show-FormattedStatus {
    param($Data)

    Write-Host ""
    Write-Host "=== Ostwin War-Room Dashboard ===" -ForegroundColor Cyan
    Write-Host ""

    if ($Data.summary.total -eq 0) {
        Write-Host "  No war-rooms found." -ForegroundColor DarkGray
        Write-Host ""
        return
    }

    # Header
    $fmt = "  {0,-12} {1,-10} {2,-14} {3,-8} {4,-6} {5,-8} {6,-10} {7}"
    Write-Host ($fmt -f "ROOM", "REF", "STATUS", "RETRIES", "MSGS", "GOALS", "PIDS", "LAST ACTIVITY") -ForegroundColor White
    Write-Host ($fmt -f "----", "---", "------", "-------", "----", "-----", "----", "-------------") -ForegroundColor DarkGray

    foreach ($room in $Data.rooms) {
        $statusColor = switch -Regex ($room.status) {
            '^pending$'         { 'DarkGray' }
            '^(engineering|developing)$' { 'Yellow' }
            '^optimize$'        { 'DarkYellow' }
            '^review(-\d+)?$'   { 'Cyan' }
            '^done$'            { 'Green' }
            '^failed$'          { 'Red' }
            '^triage$'          { 'Magenta' }
            default             { 'White' }
        }

        $line = $fmt -f $room.room_id, $room.task_ref, $room.status, $room.retries, $room.messages, $room.goals, $room.active_pids, $room.last_activity
        Write-Host $line -ForegroundColor $statusColor
    }

    $s = $Data.summary
    $active = $s.developing + $s.optimize
    Write-Host ""
    Write-Host "  Summary: $($s.total) total | $($s.pending) pending | $active active | $($s.review) review | $($s.done) done | $($s.failed) failed" -ForegroundColor White
    Write-Host ""
}

# --- Main execution ---
if ($Watch) {
    while ($true) {
        Clear-Host
        $data = Get-StatusData -BaseDir $WarRoomsDir
        Show-FormattedStatus -Data $data
        Start-Sleep -Seconds $WatchInterval
    }
}
else {
    $data = Get-StatusData -BaseDir $WarRoomsDir

    if ($JsonOutput) {
        $data | ConvertTo-Json -Depth 5
    }
    else {
        Show-FormattedStatus -Data $data
    }
}
