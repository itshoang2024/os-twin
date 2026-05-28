# ──────────────────────────────────────────────────────────────────────────────
# Verify.ps1 — Component status display
#
# Provides: Verify-Components, Print-CompletionBanner
#
# Requires: Lib.ps1, Check-Deps.ps1, globals: $script:InstallDir, $script:VenvDir,
#           $script:DashboardOnly, $script:PythonVersion, $script:PwshCurrentVersion,
#           $script:DashboardPort, $script:StartChannel, $script:TunnelUrl
# ──────────────────────────────────────────────────────────────────────────────

if ($script:_VerifyPs1Loaded) { return }
$script:_VerifyPs1Loaded = $true

function Verify-Components {
    [CmdletBinding()]
    param()

    Write-Host ""

    if ($script:DashboardOnly) {
        Write-Host "  Dashboard-Only Component Status:" -ForegroundColor White

        $pyCmd = Check-Python
        if ($pyCmd) {
            Write-Host "    python:           ✅ $($script:PythonVersion)" -ForegroundColor Green
        }
        else {
            Write-Host "    python:           ❌ not found" -ForegroundColor Red
        }

        if (Test-Path $script:VenvDir) {
            Write-Host "    venv:             ✅ $($script:VenvDir)" -ForegroundColor Green
        }
        else {
            Write-Host "    venv:             ❌ not created" -ForegroundColor Red
        }

        $dashApi = Join-Path $script:InstallDir "dashboard\api.py"
        if (Test-Path $dashApi) {
            Write-Host "    dashboard api:    ✅ installed" -ForegroundColor Green
        }
        else {
            Write-Host "    dashboard api:    ❌ not found" -ForegroundColor Red
        }
    }
    else {
        Write-Host "  Component Status:" -ForegroundColor White

        # PowerShell version (we're running in it)
        $psVer = "$($PSVersionTable.PSVersion.Major).$($PSVersionTable.PSVersion.Minor)"
        Write-Host "    powershell:       ✅ $psVer" -ForegroundColor Green

        # Windows version
        Write-Host "    windows:          ✅ $($script:WinVersion) (build $($script:WinBuild))" -ForegroundColor Green

        # Python
        $pyCmd = Check-Python
        if ($pyCmd) {
            Write-Host "    python:           ✅ $($script:PythonVersion)" -ForegroundColor Green
        }
        else {
            Write-Host "    python:           ❌ not found" -ForegroundColor Red
        }

        # uv
        if (Check-UV) {
            $uvVer = (& uv --version 2>&1) -replace '[^0-9.]', '' | Select-Object -First 1
            Write-Host "    uv:               ✅ $uvVer" -ForegroundColor Green
        }
        else {
            Write-Host "    uv:               ⚠️  not installed" -ForegroundColor Yellow
        }

        # opencode
        if (Check-OpenCode) {
            $ocVer = (& opencode --version 2>&1) -replace '[^0-9.]', '' | Select-Object -First 1
            if (-not $ocVer) { $ocVer = "installed" }
            Write-Host "    opencode:         ✅ $ocVer" -ForegroundColor Green
        }
        else {
            Write-Host "    opencode:         ⚠️  not in PATH" -ForegroundColor Yellow
        }

        # Node.js
        if (Check-Node) {
            $nodeVer = (& node --version 2>&1) | Select-Object -First 1
            Write-Host "    node:             ✅ $nodeVer" -ForegroundColor Green
        }
        else {
            Write-Host "    node:             ⚠️  not installed" -ForegroundColor Yellow
        }

        $chromeDevToolsPath = Check-ChromeDevTools
        if ($chromeDevToolsPath) {
            Write-Host "    chrome-devtools:  ✅ installed" -ForegroundColor Green
        }
        else {
            Write-Host "    chrome-devtools:  ⚠️  not installed" -ForegroundColor Yellow
        }

        # venv
        if (Test-Path $script:VenvDir) {
            Write-Host "    venv:             ✅ $($script:VenvDir)" -ForegroundColor Green
        }
        else {
            Write-Host "    venv:             ❌ not created" -ForegroundColor Red
        }

        # Developer Mode
        if ($script:DevModeEnabled) {
            Write-Host "    developer mode:   ✅ enabled" -ForegroundColor Green
        }
        else {
            Write-Host "    developer mode:   ⚠️  disabled (symlinks may require elevation)" -ForegroundColor Yellow
        }
    }
}

function Print-CompletionBanner {
    [CmdletBinding()]
    param()

    Write-Host ""
    Write-Host "  Installation complete! ✅" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Next steps:" -ForegroundColor White
    Write-Host ""
    Write-Host "    1. Restart your terminal" -ForegroundColor Cyan -NoNewline
    Write-Host "     (or run: refreshenv)" -ForegroundColor DarkGray
    Write-Host "    2. Verify installation:" -ForegroundColor Cyan -NoNewline
    Write-Host "       ostwin health" -ForegroundColor DarkGray
    Write-Host "    3. Initialize a project:" -ForegroundColor Cyan -NoNewline
    Write-Host "      ostwin init ~\my-project" -ForegroundColor DarkGray
    Write-Host "    4. Set your API key:" -ForegroundColor Cyan -NoNewline
    Write-Host "        `$env:GOOGLE_API_KEY = 'your-key'" -ForegroundColor DarkGray
    Write-Host "    5. Run your first plan:" -ForegroundColor Cyan -NoNewline
    Write-Host "      ostwin run plans\my-plan.md" -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "  Dashboard:" -ForegroundColor White

    if ($script:TunnelUrl) {
        Write-Host "    Local:  http://localhost:$($script:DashboardPort)" -ForegroundColor DarkGray
        Write-Host "    Public: $($script:TunnelUrl)" -ForegroundColor DarkGray
    }
    else {
        Write-Host "    Dashboard running at http://localhost:$($script:DashboardPort)" -ForegroundColor DarkGray
    }
    Write-Host "    Stop with: ostwin stop" -ForegroundColor DarkGray

    if ($script:StartChannel) {
        Write-Host ""
        Write-Host "  Channels (Telegram + Discord + Slack):" -ForegroundColor White
        Write-Host "    Running in background — log: $($script:InstallDir)\logs\channel.log" -ForegroundColor DarkGray
        Write-Host "    Stop with: ostwin channel stop" -ForegroundColor DarkGray
    }
    Write-Host ""

    # Display OSTWIN_API_KEY
    $apiKey = $env:OSTWIN_API_KEY
    if (-not $apiKey) {
        $envFile = Join-Path $script:InstallDir ".env"
        if (Test-Path $envFile) {
            $match = Get-Content $envFile | Where-Object { $_ -match '^OSTWIN_API_KEY=(.+)$' }
            if ($match -and $match -match '^OSTWIN_API_KEY=(.+)$') {
                $apiKey = $Matches[1]
            }
        }
    }
    if ($apiKey) {
        Write-Host "  🔑 Dashboard Authentication Key:" -ForegroundColor White
        Write-Host ""
        Write-Host "    $apiKey" -ForegroundColor Yellow
        Write-Host ""
        Write-Host "    Use this key to authenticate with the dashboard frontend." -ForegroundColor DarkGray
        Write-Host "    The frontend will prompt you to enter this key on first visit." -ForegroundColor DarkGray
        Write-Host "    Stored in: $($script:InstallDir)\.env" -ForegroundColor DarkGray
        Write-Host ""
    }

    Write-Host "  AI Provider Keys:" -ForegroundColor White
    Write-Host "    Edit your .env file (keys auto-migrated if already in environment):" -ForegroundColor DarkGray
    Write-Host "    notepad $($script:InstallDir)\.env" -ForegroundColor DarkGray
    Write-Host "    Then restart dashboard: ostwin stop; ostwin start" -ForegroundColor DarkGray
    Write-Host ""
}
