# ──────────────────────────────────────────────────────────────────────────────
# Orchestrate-Deps.ps1 — Dependency check & install orchestration (step 2)
#
# Provides: Invoke-DependencyOrchestration
#
# This mirrors _orchestrate-deps.sh — handles the branching logic for
# -DashboardOnly vs full install.
#
# Requires: Check-Deps.ps1, Install-Deps.ps1, Lib.ps1,
#           globals: $script:DashboardOnly, $script:AutoYes
# ──────────────────────────────────────────────────────────────────────────────

if ($script:_OrchestrateDepsPs1Loaded) { return }
$script:_OrchestrateDepsPs1Loaded = $true

function Invoke-DependencyOrchestration {
    [CmdletBinding()]
    param()

    if ($script:DashboardOnly) {
        Write-Header "2. Checking dependencies (dashboard-only — minimal)"

        # PowerShell version (we're already running)
        $psVer = "$($PSVersionTable.PSVersion.Major).$($PSVersionTable.PSVersion.Minor)"
        Write-Ok "PowerShell $psVer"

        # uv
        if (-not (Check-UV)) {
            Install-UV
        }

        # Python
        $script:PythonCmd = Check-Python
        if (-not $script:PythonCmd) {
            Install-Python
            $script:PythonCmd = Check-Python
            if (-not $script:PythonCmd) {
                Write-Fail "Python required for dashboard"
                throw "Python installation failed"
            }
        }
        Write-Ok "Python $($script:PythonVersion) ($($script:PythonCmd))"

        # Node.js
        if (-not (Check-Node)) {
            Install-Node
        }
        if (Check-Node) {
            $nodeVer = (& node --version 2>&1) | Select-Object -First 1
            Write-Ok "Node.js $nodeVer"

            if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) {
                if (Get-Command npm -ErrorAction SilentlyContinue) {
                    Write-Step "Installing pnpm..."
                    & npm install -g pnpm 2>$null
                }
            }
            if (-not (Get-Command clawhub -ErrorAction SilentlyContinue)) {
                if (Get-Command npm -ErrorAction SilentlyContinue) {
                    Write-Step "Installing clawhub CLI..."
                    & npm install -g clawhub 2>$null
                }
            }
        }
        else {
            Write-Fail "Node.js required for dashboard"
            throw "Node.js installation failed"
        }
    }
    else {
        Write-Header "2. Checking dependencies"

        # PowerShell version
        $psVer = "$($PSVersionTable.PSVersion.Major).$($PSVersionTable.PSVersion.Minor)"
        Write-Ok "PowerShell $psVer"

        # uv
        if (Check-UV) {
            $uvVer = (& uv --version 2>&1) -replace '[^0-9.]', '' | Select-Object -First 1
            Write-Ok "uv $uvVer"
        }
        else {
            Write-Warn "uv not found"
            if (Ask-User "Install uv? (recommended — fast Python package manager)") {
                Install-UV
            }
            else {
                Write-Info "Skipping uv — will use pip fallback"
            }
        }

        # Python
        $script:PythonCmd = Check-Python
        if ($script:PythonCmd) {
            Write-Ok "Python $($script:PythonVersion) ($($script:PythonCmd))"
        }
        else {
            Write-Warn "Python $($script:MinPythonVersion)+ not found"
            if (Ask-User "Install Python?") {
                Install-Python
                $script:PythonCmd = Check-Python
                if ($script:PythonCmd) {
                    Write-Ok "Python $($script:PythonVersion) installed"
                }
                else {
                    Write-Fail "Python installation failed"
                    throw "Python $($script:MinPythonVersion)+ is required"
                }
            }
            else {
                Write-Fail "Python $($script:MinPythonVersion)+ is required"
                throw "Python is required"
            }
        }

        # opencode
        if (Check-OpenCode) {
            $ocVer = (& opencode --version 2>&1) -replace '[^0-9.]', '' | Select-Object -First 1
            if (-not $ocVer) { $ocVer = "installed" }
            Write-Ok "opencode $ocVer"
        }
        elseif ($script:SkipOptional) {
            Write-Warn "opencode not found (skipped — SkipOptional)"
        }
        else {
            Install-OpenCode
        }

        # Chrome DevTools backs the built-in browser automation MCP server.
        # Install it before MCP config is seeded so fresh installs can start the server.
        $chromeDevToolsPath = Check-ChromeDevTools
        if ($chromeDevToolsPath) {
            Write-Ok "chrome-devtools runtime ($chromeDevToolsPath)"
        }
        elseif ($script:SkipOptional) {
            Write-Warn "chrome-devtools runtime not found (skipped — SkipOptional)"
        }
        else {
            Install-ChromeDevTools
        }

        # Node.js
        if (Check-Node) {
            $nodeVer = (& node --version 2>&1) | Select-Object -First 1
            Write-Ok "Node.js $nodeVer"

            if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) {
                if (Get-Command npm -ErrorAction SilentlyContinue) {
                    Write-Step "Installing pnpm..."
                    & npm install -g pnpm 2>$null
                }
            }
            if (-not (Get-Command clawhub -ErrorAction SilentlyContinue)) {
                if (Get-Command npm -ErrorAction SilentlyContinue) {
                    Write-Step "Installing clawhub CLI..."
                    & npm install -g clawhub 2>$null
                }
            }
        }
        else {
            Write-Warn "Node.js not found"
            if (Ask-User "Install Node.js? (required for Dashboard UI)") {
                Install-Node
                if (Check-Node) {
                    $nodeVer = (& node --version 2>&1) | Select-Object -First 1
                    Write-Ok "Node.js $nodeVer installed"

                    if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) {
                        if (Get-Command npm -ErrorAction SilentlyContinue) {
                            Write-Step "Installing pnpm..."
                            & npm install -g pnpm 2>$null
                        }
                    }
                    if (-not (Get-Command clawhub -ErrorAction SilentlyContinue)) {
                        if (Get-Command npm -ErrorAction SilentlyContinue) {
                            Write-Step "Installing clawhub CLI..."
                            & npm install -g clawhub 2>$null
                        }
                    }
                }
                else {
                    Write-Warn "Node.js installation failed"
                }
            }
            else {
                Write-Warn "Skipping Node.js — dashboard UI will not be built"
            }
        }
    }
}
