# ──────────────────────────────────────────────────────────────────────────────
# Start-Dashboard.ps1 — Dashboard launch, health check, tunnel detection
#
# Provides: Start-Dashboard, Publish-Skills
#
# Requires: Lib.ps1, Check-Deps.ps1,
#           globals: $script:InstallDir, $script:VenvDir,
#                    $script:DashboardPort, $script:OstwinApiKey
# ──────────────────────────────────────────────────────────────────────────────

if ($script:_StartDashboardPs1Loaded) { return }
$script:_StartDashboardPs1Loaded = $true

function Start-Dashboard {
    [CmdletBinding()]
    param()

    $dashboardApi = Join-Path $script:InstallDir "dashboard\api.py"
    if (-not (Test-Path $dashboardApi)) {
        Write-Warn "Dashboard not found — skipping auto-start"
        Write-Info "Re-run: .\install.ps1 -SourceDir C:\path\to\agent-os"
        return
    }

    # Stop any existing dashboard process (by PID file, then by port)
    $pidFile = Join-Path $script:InstallDir "dashboard.pid"
    if (Test-Path $pidFile) {
        $oldPid = Get-Content $pidFile -ErrorAction SilentlyContinue
        if ($oldPid) {
            # Validate PID is actually a python/uvicorn process before killing
            # Tight validation: must be python AND (uvicorn OR api:app) to avoid false matches
            $isValidDash = $false
            try {
                $proc = Get-Process -Id $oldPid -ErrorAction SilentlyContinue
                if ($proc) {
                    # Primary check: must be a python process running uvicorn/api:app
                    $cmdLine = (Get-CimInstance Win32_Process -Filter "ProcessId=$oldPid" -ErrorAction SilentlyContinue).CommandLine
                    if ($cmdLine -and $cmdLine -match "python" -and ($cmdLine -match "uvicorn" -or $cmdLine -match "api:app")) {
                        $isValidDash = $true
                    }
                    # Fallback: check if it's listening on the expected dashboard port
                    if (-not $isValidDash) {
                        try {
                            $portOwner = Get-NetTCPConnection -LocalPort $script:DashboardPort -State Listen -ErrorAction SilentlyContinue |
                                Select-Object -ExpandProperty OwningProcess -First 1
                            if ($portOwner -eq $oldPid) {
                                $isValidDash = $true
                            }
                        } catch {}
                    }
                }
            } catch {}
            if ($isValidDash) {
                try {
                    & taskkill /F /T /PID $oldPid 2>$null | Out-Null
                } catch {}
            }
            # Remove stale PID file
            Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
        }
    }
    try {
        $existingProcs = Get-NetTCPConnection -LocalPort $script:DashboardPort -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty OwningProcess -Unique
        if ($existingProcs) {
            Write-Step "Stopping existing process on :$($script:DashboardPort)..."
            foreach ($p in $existingProcs) {
                & taskkill /F /T /PID $p 2>$null | Out-Null
            }
        }
    }
    catch {
        # Get-NetTCPConnection may not be available — continue
    }
    Start-Sleep -Seconds 2

    # Load .env so the dashboard process inherits API keys
    $envFile = Join-Path $script:InstallDir ".env"
    if (Test-Path $envFile) {
        Get-Content $envFile | ForEach-Object {
            if ($_ -match '^\s*([^#][^=]+)=(.*)$') {
                [System.Environment]::SetEnvironmentVariable($Matches[1].Trim(), $Matches[2].Trim(), "Process")
            }
        }
    }

    $logsDir = Join-Path $script:InstallDir "logs"
    if (-not (Test-Path $logsDir)) {
        New-Item -ItemType Directory -Path $logsDir -Force | Out-Null
    }

    Write-Step "Starting dashboard on http://localhost:$($script:DashboardPort)..."

    $venvPython = Join-Path $script:VenvDir "Scripts\python.exe"
    $logFile = Join-Path $logsDir "dashboard.log"
    $errorLog = Join-Path $logsDir "dashboard-error.log"

    # Clear stale logs from previous runs
    if (Test-Path $logFile)  { Remove-Item $logFile -Force -ErrorAction SilentlyContinue }
    if (Test-Path $errorLog) { Remove-Item $errorLog -Force -ErrorAction SilentlyContinue }

    # Set project dir env var so api_utils.py picks it up
    [System.Environment]::SetEnvironmentVariable("OSTWIN_PROJECT_DIR", $script:InstallDir, "Process")

    # Start dashboard via .cmd wrapper so the child process owns its own log pipes.
    # This avoids the lifetime issue where redirected streams are tied to the installer process.
    # Use UTF-8 without BOM to handle paths with non-ASCII characters.
    $dashboardDir = Join-Path $script:InstallDir "dashboard"
    $pidFile = Join-Path $script:InstallDir "dashboard.pid"
    $batFile = Join-Path $logsDir "_start-dashboard.cmd"

    # Build .cmd content with proper escaping for paths
    $batContent = "@echo off`r`ncd /d `"$dashboardDir`"`r`n`"$venvPython`" -m uvicorn api:app --host 0.0.0.0 --port $($script:DashboardPort) >`"$logFile`" 2>`"$errorLog`""

    # Write with UTF-8 without BOM (handles non-ASCII paths correctly)
    [System.IO.File]::WriteAllText($batFile, $batContent, [System.Text.UTF8Encoding]::new($false))

    Start-Process -FilePath "cmd.exe" `
        -ArgumentList "/c", "`"$batFile`"" `
        -WindowStyle Hidden

    # The PID will be resolved after health check succeeds (port is listening)
    $dashPid = $null

    # Read OSTWIN_API_KEY for auth headers
    $script:OstwinApiKey = $env:OSTWIN_API_KEY
    if (-not $script:OstwinApiKey) {
        $script:OstwinApiKey = ""
    }

    # Health-check: poll /api/status up to 180s
    # First startup can spend extra time importing AI/vector-store dependencies.
    # Accept any HTTP response (including 401/403) as proof the server is up
    Write-Step "Waiting for dashboard to be healthy (up to 180s)..."
    $dashOk = $false
    for ($i = 1; $i -le 180; $i++) {
        try {
            # Use System.Net.Http directly — avoids PowerShell cmdlet exception handling quirks
            $httpClient = [System.Net.Http.HttpClient]::new()
            $httpClient.Timeout = [TimeSpan]::FromSeconds(10)
            $task = $httpClient.GetAsync("http://localhost:$($script:DashboardPort)/api/status")
            $task.Wait()
            $statusCode = [int]$task.Result.StatusCode
            $httpClient.Dispose()
            # Accept only expected dashboard status codes: 200 (OK), 401 (auth required), 403 (forbidden)
            # Reject 500+ (server error) and other unexpected codes
            if ($statusCode -in @(200, 401, 403)) {
                $dashOk = $true
                break
            }
            Start-Sleep -Seconds 1
        }
        catch {
            if ($httpClient) { $httpClient.Dispose() }
            Start-Sleep -Seconds 1
        }
    }

    if ($dashOk) {
        # Resolve the real python PID via port listening
        try {
            $dashPid = Get-NetTCPConnection -LocalPort $script:DashboardPort -State Listen -ErrorAction SilentlyContinue |
                Select-Object -ExpandProperty OwningProcess -First 1
        } catch {}
        if ($dashPid) {
            Set-Content -Path $pidFile -Value $dashPid -NoNewline
        }
        Write-Ok "Dashboard healthy at http://localhost:$($script:DashboardPort) (PID $dashPid)"
        $script:DashboardHealthy = $true
        Check-Tunnel
    }
    else {
        Write-Warn "Dashboard did not respond in 180s — check $errorLog"
        $dashDir = Join-Path $script:InstallDir "dashboard"
        Write-Info "Start manually: cd `"$dashDir`" && `"$venvPython`" api.py --port $($script:DashboardPort) --project-dir `"$($script:InstallDir)`""
        $script:DashboardHealthy = $false
    }
}

function Publish-Skills {
    [CmdletBinding()]
    param()

    Write-Header "9b. Publishing skills to backend"

    if (-not $script:DashboardHealthy) {
        Write-Warn "Dashboard not healthy — skipping skill sync (run 'ostwin sync-skills' later)"
        return
    }

    $syncScriptPs1 = Join-Path $script:InstallDir ".agents\sync-skills.ps1"

    # Run skill sync in background to avoid blocking the installer (~15 min on CPU)
    $logsDir = Join-Path $script:InstallDir "logs"
    $skillLogFile = Join-Path $logsDir "sync-skills.log"

    if (Test-Path $syncScriptPs1) {
        $env:OSTWIN_HOME = $script:InstallDir
        $env:DASHBOARD_PORT = $script:DashboardPort
        $installFrom = Join-Path $script:InstallDir ".agents"
        $batFile = Join-Path $logsDir "_sync-skills.cmd"
        $pwshExe = (Get-Command pwsh).Source
        $batContent = "@echo off`r`n`"$pwshExe`" -NoProfile -File `"$syncScriptPs1`" -InstallFrom `"$installFrom`" >`"$skillLogFile`" 2>&1"
        # Use UTF-8 without BOM to avoid encoding issues with non-ASCII paths
        [System.IO.File]::WriteAllText($batFile, $batContent, [System.Text.UTF8Encoding]::new($false))
        Start-Process -FilePath "cmd.exe" -ArgumentList "/c", "`"$batFile`"" -WindowStyle Hidden
        Write-Ok "Skill sync started in background — log: $skillLogFile"
    }
    else {
        Write-Warn "sync-skills.ps1 not found — skipping skill sync"
    }
}

# ─── Internal helpers ────────────────────────────────────────────────────────

function Check-Tunnel {
    [CmdletBinding()]
    param()

    $tunnelUrl = ""
    $tunnelError = ""

    try {
        $headers = @{}
        if ($script:OstwinApiKey) {
            $headers["X-API-Key"] = $script:OstwinApiKey
        }
        $tunnelJson = Invoke-RestMethod -Uri "http://localhost:$($script:DashboardPort)/api/tunnel/status" `
            -Headers $headers -TimeoutSec 5 -ErrorAction Stop

        if ($tunnelJson.url) { $tunnelUrl = $tunnelJson.url }
        if ($tunnelJson.error) { $tunnelError = $tunnelJson.error }
    }
    catch { }

    if ($tunnelUrl) {
        Write-Ok "Tunnel active: $tunnelUrl"
        $script:TunnelUrl = $tunnelUrl
    }
    elseif ($tunnelError) {
        Write-Warn "Tunnel failed: $tunnelError"
    }
    elseif (-not $env:NGROK_AUTHTOKEN) {
        Write-Info "Tunnel not configured — set NGROK_AUTHTOKEN in ~\.ostwin\.env to enable port forwarding"
    }
    else {
        Write-Warn "Tunnel not active — check dashboard logs"
    }
}
