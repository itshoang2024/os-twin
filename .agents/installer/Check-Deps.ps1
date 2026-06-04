# ──────────────────────────────────────────────────────────────────────────────
# Check-Deps.ps1 — Dependency presence checks (pure — no installs)
#
# Provides: Check-Python, Check-Pwsh, Check-Node, Check-Bun, Check-UV,
#           Check-OpenCode, Check-ChromeDevTools
#
# Requires: Lib.ps1 (Compare-VersionGte), Versions.ps1 (MinPythonVersion, MinPwshVersion)
#
# Side effects: sets $script:PythonVersion and $script:PwshCurrentVersion on success.
# ──────────────────────────────────────────────────────────────────────────────

if ($script:_CheckDepsPs1Loaded) { return }
$script:_CheckDepsPs1Loaded = $true

# ─── Python ──────────────────────────────────────────────────────────────────
# Returns the path to a suitable python command, or empty string.

function Check-Python {
    [CmdletBinding()]
    param()

    foreach ($cmd in @("python", "python3", "py")) {
        $exe = Get-Command $cmd -ErrorAction SilentlyContinue
        if ($exe) {
            try {
                $verOutput = & $cmd --version 2>&1
                if ($verOutput -match '(\d+\.\d+)') {
                    $ver = $Matches[1]
                    if (Compare-VersionGte -Current $ver -Minimum $script:MinPythonVersion) {
                        $script:PythonVersion = $ver
                        return $exe.Source
                    }
                }
            }
            catch {
                continue
            }
        }
    }

    # Fallback: check uv-managed Python
    if (Check-UV) {
        try {
            $uvPy = & uv python find 2>$null
            if ($uvPy -and (Test-Path $uvPy)) {
                $verOutput = & $uvPy --version 2>&1
                if ($verOutput -match '(\d+\.\d+)') {
                    $script:PythonVersion = $Matches[1]
                    return $uvPy
                }
            }
        }
        catch { }
    }

    return ""
}

# ─── PowerShell 7+ ──────────────────────────────────────────────────────────

function Check-Pwsh {
    [CmdletBinding()]
    param()

    # We're already running in PowerShell — check current version
    if ($PSVersionTable.PSVersion.Major -ge 7) {
        $script:PwshCurrentVersion = "$($PSVersionTable.PSVersion.Major).$($PSVersionTable.PSVersion.Minor)"
        return $true
    }

    # Check for pwsh.exe separately
    $pwshExe = Get-Command pwsh -ErrorAction SilentlyContinue
    if ($pwshExe) {
        try {
            $verOutput = & pwsh --version 2>&1
            if ($verOutput -match '(\d+\.\d+)') {
                $ver = $Matches[1]
                if (Compare-VersionGte -Current $ver -Minimum $script:MinPwshVersion) {
                    $script:PwshCurrentVersion = $ver
                    return $true
                }
            }
        }
        catch { }
    }

    return $false
}

# ─── Node.js ─────────────────────────────────────────────────────────────────

function Check-Node {
    [CmdletBinding()]
    param()

    $null -ne (Get-Command node -ErrorAction SilentlyContinue)
}

# ─── Bun (JavaScript runtime/package manager) ────────────────────────────────

function Check-Bun {
    [CmdletBinding()]
    param()

    $null -ne (Get-Command bun -ErrorAction SilentlyContinue)
}

# ─── uv (Python package manager) ────────────────────────────────────────────

function Check-UV {
    [CmdletBinding()]
    param()

    $null -ne (Get-Command uv -ErrorAction SilentlyContinue)
}

# ─── opencode (Agent execution engine) ──────────────────────────────────────

function Check-OpenCode {
    [CmdletBinding()]
    param()

    $null -ne (Get-Command opencode -ErrorAction SilentlyContinue)
}

# ─── Chrome DevTools browser runtime ────────────────────────────────────────

function Test-ChromeDevToolsMcpSupport {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)]
        [string]$Path
    )

    if (-not $Path -or -not (Test-Path -LiteralPath $Path)) {
        return $false
    }

    $previousLastExitCode = $global:LASTEXITCODE
    try {
        & $Path mcp --help *> $null
        return ($LASTEXITCODE -eq 0)
    }
    catch {
        return $false
    }
    finally {
        $global:LASTEXITCODE = $previousLastExitCode
    }
}

function Check-ChromeDevTools {
    [CmdletBinding()]
    param()

    if ($script:InstallDir) {
        $localBin = Join-Path $script:InstallDir ".agents\bin"
        $managedCandidates = @(
            (Join-Path $localBin "obscura.exe"),
            (Join-Path $localBin "obscura")
        )
        foreach ($candidate in $managedCandidates) {
            if (Test-Path -LiteralPath $candidate) {
                if (Test-ChromeDevToolsMcpSupport -Path $candidate) {
                    return [string]$candidate
                }
                return ""
            }
        }
    }

    $pathCandidates = Get-Command obscura -All -ErrorAction SilentlyContinue |
        Where-Object { $_.Source } |
        ForEach-Object { [string]$_.Source }

    foreach ($candidate in ($pathCandidates | Where-Object { $_ } | Select-Object -Unique)) {
        if (Test-ChromeDevToolsMcpSupport -Path $candidate) {
            return [string]$candidate
        }
    }

    return ""
}
