<#
.SYNOPSIS
    Agent OS — Health Check (PowerShell port of health.sh)

.DESCRIPTION
    Checks the health of a running Agent OS instance.

.PARAMETER JsonOutput
    Output results as JSON instead of human-readable text.
#>
[CmdletBinding()]
param(
    [Alias('json')]
    [switch]$JsonOutput
)

$ErrorActionPreference = "SilentlyContinue"

$ScriptDir = Split-Path $PSCommandPath -Parent
$AgentsDir = $ScriptDir
$HomeDir = if ($env:USERPROFILE) { $env:USERPROFILE } else { $HOME }
$OstwinHome = if ($env:OSTWIN_HOME) { $env:OSTWIN_HOME } else { Join-Path $HomeDir ".ostwin" }
$WarroomsDir = if ($env:WARROOMS_DIR) { $env:WARROOMS_DIR } else { Join-Path $AgentsDir "war-rooms" }
$ManagerPidFile = Join-Path $AgentsDir "manager.pid"

$ConfigModule = Join-Path $AgentsDir "lib" "Config.psm1"
if (Test-Path $ConfigModule) {
    Import-Module $ConfigModule -Force
}

function Resolve-HealthConfigPath {
    if (Get-Command Resolve-OstwinConfigPath -ErrorAction SilentlyContinue) {
        try { return Resolve-OstwinConfigPath } catch { }
    }

    $globalConfig = Join-Path (Join-Path $OstwinHome ".agents") "config.json"
    if ($env:AGENT_OS_CONFIG) { return $env:AGENT_OS_CONFIG }
    if ($env:OSTWIN_CONFIG_PATH) { return $env:OSTWIN_CONFIG_PATH }
    if ($env:OSTWIN_PROJECT_DIR) { return (Join-Path (Join-Path $env:OSTWIN_PROJECT_DIR ".agents") "config.json") }
    if ($env:AGENTS_DIR) { return (Join-Path $env:AGENTS_DIR "config.json") }
    if (Test-Path $globalConfig) { return $globalConfig }
    return (Join-Path $AgentsDir "config.json")
}

function Test-ActiveRoomState {
    param(
        [Parameter(Mandatory)][string]$RoomDir,
        [Parameter(Mandatory)][string]$Status
    )

    if ($Status -in @("", "unknown", "pending", "passed", "failed-final", "blocked", "paused", "signoff")) {
        return $false
    }

    $lifecycleFile = Join-Path $RoomDir "lifecycle.json"
    if (Test-Path $lifecycleFile) {
        try {
            $lifecycle = Get-Content $lifecycleFile -Raw | ConvertFrom-Json
            $stateDef = $lifecycle.states.$Status
            if ($stateDef -and $stateDef.type) {
                return ($stateDef.type -ne "terminal")
            }
        }
        catch { }
    }

    return $true
}

$ConfigFile = Resolve-HealthConfigPath

# ─── Resolve Python ──────────────────────────────────────────────────────────

$PythonCmd = $null
$localVenvPy = Join-Path $AgentsDir ".venv" "Scripts" "python.exe"
$localVenvPyUnix = Join-Path $AgentsDir ".venv" "bin" "python"
$globalVenvPy = Join-Path $HomeDir ".ostwin" ".venv" "Scripts" "python.exe"
$globalVenvPyUnix = Join-Path $HomeDir ".ostwin" ".venv" "bin" "python"

if (Test-Path $localVenvPy) { $PythonCmd = $localVenvPy }
elseif (Test-Path $localVenvPyUnix) { $PythonCmd = $localVenvPyUnix }
elseif (Test-Path $globalVenvPy) { $PythonCmd = $globalVenvPy }
elseif (Test-Path $globalVenvPyUnix) { $PythonCmd = $globalVenvPyUnix }
elseif (Get-Command python3 -ErrorAction SilentlyContinue) { $PythonCmd = "python3" }
elseif (Get-Command python -ErrorAction SilentlyContinue) { $PythonCmd = "python" }

$PythonAvailable = if ($PythonCmd) { "available" } else { "not found" }

# ─── Check manager ───────────────────────────────────────────────────────────

$ManagerPid = ""
$ManagerAlive = $false
if (Test-Path $ManagerPidFile) {
    $ManagerPid = (Get-Content $ManagerPidFile -Raw).Trim()
    try {
        $null = Get-Process -Id $ManagerPid -ErrorAction Stop
        $ManagerAlive = $true
    }
    catch { }
}

# ─── Read state_timeout from config ──────────────────────────────────────────

$StateTimeout = 900
if (Test-Path $ConfigFile) {
    try {
        $configData = Get-Content $ConfigFile -Raw | ConvertFrom-Json
        if (Get-Command Get-OstwinManagerRuntimeSettings -ErrorAction SilentlyContinue) {
            $StateTimeout = [int](Get-OstwinManagerRuntimeSettings -Config $configData).state_timeout_seconds
        }
        elseif ($null -ne $configData.manager -and $null -ne $configData.manager.state_timeout_seconds) {
            $StateTimeout = [int]$configData.manager.state_timeout_seconds
        }
        elseif ($null -ne $configData.runtime -and $null -ne $configData.runtime.state_timeout_seconds) {
            $StateTimeout = [int]$configData.runtime.state_timeout_seconds
        }
    }
    catch { }
}

# ─── Check rooms ─────────────────────────────────────────────────────────────

$TotalRooms = 0
$PassedRooms = 0
$FailedRooms = 0
$ActiveRooms = 0
$StuckRooms = 0
$Now = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()

if (Test-Path $WarroomsDir) {
    foreach ($roomDir in Get-ChildItem -Path $WarroomsDir -Directory -Filter "room-*" -ErrorAction SilentlyContinue) {
        $TotalRooms++
        $statusFile = Join-Path $roomDir.FullName "status"
        $status = if (Test-Path $statusFile) { (Get-Content $statusFile -Raw).Trim() } else { "unknown" }

        switch ($status) {
            "passed" { $PassedRooms++ }
            "failed-final" { $FailedRooms++ }
            { Test-ActiveRoomState -RoomDir $roomDir.FullName -Status $_ } {
                $ActiveRooms++

                # Check if stuck (active but no PID alive)
                $hasAlivePid = $false
                $pidsDir = Join-Path $roomDir.FullName "pids"
                if (Test-Path $pidsDir) {
                    foreach ($pidFile in Get-ChildItem -Path $pidsDir -Filter "*.pid" -ErrorAction SilentlyContinue) {
                        $pid = (Get-Content $pidFile.FullName -Raw).Trim()
                        try {
                            $null = Get-Process -Id $pid -ErrorAction Stop
                            $hasAlivePid = $true
                            break
                        }
                        catch { }
                    }
                }

                if (-not $hasAlivePid) {
                    $changedAtFile = Join-Path $roomDir.FullName "state_changed_at"
                    $changedAt = 0
                    if (Test-Path $changedAtFile) {
                        try { $changedAt = [long](Get-Content $changedAtFile -Raw).Trim() } catch { }
                    }
                    $elapsed = $Now - $changedAt
                    if ($elapsed -gt $StateTimeout) {
                        $StuckRooms++
                    }
                }
            }
        }
    }
}

# ─── Check agent CLI availability ────────────────────────────────────────────

$defaultAgentBin = Join-Path $OstwinHome ".agents" "bin" "agent"
$EngineerCmd = if ($env:ENGINEER_CMD) { $env:ENGINEER_CMD } else { $defaultAgentBin }
$QaCmd = if ($env:QA_CMD) { $env:QA_CMD } else { $defaultAgentBin }
$EngineerAvailable = if (Get-Command $EngineerCmd -ErrorAction SilentlyContinue) { "available" } else { "not found" }
$QaAvailable = if (Get-Command $QaCmd -ErrorAction SilentlyContinue) { "available" } else { "not found" }

# ─── Determine overall health ────────────────────────────────────────────────

$Health = "healthy"
if ($StuckRooms -gt 0) { $Health = "degraded" }
if ($PythonAvailable -ne "available") { $Health = "unhealthy" }
if (-not $ManagerAlive -and $ActiveRooms -gt 0) { $Health = "unhealthy" }

# ─── Output ──────────────────────────────────────────────────────────────────

if ($JsonOutput) {
    $result = [ordered]@{
        status  = $Health
        manager = [ordered]@{
            pid   = if ($ManagerPid) { $ManagerPid } else { $null }
            alive = $ManagerAlive
        }
        rooms   = [ordered]@{
            total  = $TotalRooms
            passed = $PassedRooms
            failed = $FailedRooms
            active = $ActiveRooms
            stuck  = $StuckRooms
        }
        agents  = [ordered]@{
            engineer = [ordered]@{ cmd = $EngineerCmd; status = $EngineerAvailable }
            qa       = [ordered]@{ cmd = $QaCmd; status = $QaAvailable }
            python3  = $PythonAvailable
        }
        config  = [ordered]@{
            state_timeout_seconds = $StateTimeout
        }
    }
    $result | ConvertTo-Json -Depth 5
}
else {
    Write-Host ""
    Write-Host "  Ostwin Health Check"
    Write-Host "  ====================="
    Write-Host ""

    switch ($Health) {
        "healthy"   { Write-Host "  Status: HEALTHY" }
        "degraded"  { Write-Host "  Status: DEGRADED" }
        "unhealthy" { Write-Host "  Status: UNHEALTHY" }
    }
    Write-Host ""

    Write-Host "  Manager:"
    if ($ManagerAlive) {
        Write-Host "    PID $ManagerPid -- running"
    }
    elseif ($ManagerPid) {
        Write-Host "    PID $ManagerPid -- NOT running (stale PID file)"
    }
    else {
        Write-Host "    Not started"
    }
    Write-Host ""

    Write-Host "  War-Rooms:"
    Write-Host "    Total:   $TotalRooms"
    Write-Host "    Passed:  $PassedRooms"
    Write-Host "    Failed:  $FailedRooms"
    Write-Host "    Active:  $ActiveRooms"
    if ($StuckRooms -gt 0) {
        Write-Host "    Stuck:   $StuckRooms (no PID alive, state timeout exceeded)"
    }
    Write-Host ""

    Write-Host "  Agent CLIs:"
    Write-Host "    Engineer ($EngineerCmd): $EngineerAvailable"
    Write-Host "    QA ($QaCmd): $QaAvailable"
    Write-Host "    Python3: $PythonAvailable"
    Write-Host ""
}
