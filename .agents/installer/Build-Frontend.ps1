# ──────────────────────────────────────────────────────────────────────────────
# Build-Frontend.ps1 — Unified frontend build function
#
# Provides: Build-Frontend
#
# Replaces the need for separate build functions with a single parameterized
# function that can build any frontend project.
#
# Requires: Lib.ps1, globals: $script:SourceDir, $script:ScriptDir
# ──────────────────────────────────────────────────────────────────────────────

if ($script:_BuildFrontendPs1Loaded) { return }
$script:_BuildFrontendPs1Loaded = $true

function Test-FrontendCiMode {
    [CmdletBinding()]
    param()

    $env:CI -in @("1", "true", "TRUE")
}

function Install-FrontendDependencies {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)][string]$PackageManager
    )

    switch ($PackageManager) {
        "bun" {
            if ((Test-Path "bun.lockb") -or (Test-Path "bun.lock")) {
                $installOutput = & bun install --frozen-lockfile 2>&1
                if ($LASTEXITCODE -eq 0) {
                    $installOutput | ForEach-Object { Write-Host $_ }
                    return
                }
                if (-not (Test-FrontendCiMode)) {
                    Write-Warn "Bun lockfile install failed; retrying without --frozen-lockfile"
                    $installOutput | ForEach-Object { Write-Host $_ }
                    & bun install
                    return
                }
                $installOutput | ForEach-Object { Write-Host $_ }
                throw "bun install --frozen-lockfile failed"
            }
            & bun install
        }
        "npm" {
            if ((Test-Path "package-lock.json") -or (Test-Path "npm-shrinkwrap.json")) {
                $installOutput = & npm ci 2>&1
                if ($LASTEXITCODE -eq 0) {
                    $installOutput | ForEach-Object { Write-Host $_ }
                    return
                }
                if (-not (Test-FrontendCiMode)) {
                    Write-Warn "npm lockfile install failed; retrying with npm install"
                    $installOutput | ForEach-Object { Write-Host $_ }
                    & npm install
                    return
                }
                $installOutput | ForEach-Object { Write-Host $_ }
                throw "npm ci failed"
            }
            & npm install
        }
        default {
            throw "Unsupported JavaScript package manager: $PackageManager"
        }
    }
}

function Build-Frontend {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$SubDir,
        [string]$Label,
        [switch]$Required
    )

    if (-not $Label) { $Label = $SubDir }

    # Locate the frontend directory relative to the source repo
    $feDir = ""
    $candidates = @(
        (Join-Path $script:SourceDir $SubDir),
        (Join-Path (Split-Path $script:ScriptDir -Parent) $SubDir),
        (Join-Path $script:ScriptDir $SubDir)
    )

    foreach ($c in $candidates) {
        if ($c -and (Test-Path $c) -and (Test-Path (Join-Path $c "package.json"))) {
            $feDir = (Resolve-Path $c).Path
            break
        }
    }

    if (-not $feDir) {
        Write-Warn "$Label not found — skipping build"
        Write-Info "Expected at $SubDir\package.json"
        if ($Required) {
            throw "$Label not found at $SubDir\package.json"
        }
        return
    }

    # Installer builds intentionally support only Bun and npm. Prefer the
    # package manager with a committed lockfile, then fall back to npm because
    # Node.js includes it by default.
    $pm = ""
    $lockPrefs = @(
        @{ File = "bun.lockb"; Tool = "bun" },
        @{ File = "bun.lock"; Tool = "bun" },
        @{ File = "package-lock.json"; Tool = "npm" },
        @{ File = "npm-shrinkwrap.json"; Tool = "npm" }
    )

    foreach ($pref in $lockPrefs) {
        $lockFile = $pref["File"]
        $tool = $pref["Tool"]
        if ((Test-Path (Join-Path $feDir $lockFile)) -and (Get-Command $tool -ErrorAction SilentlyContinue)) {
            $pm = $tool
            break
        }
    }

    if (-not $pm) {
        foreach ($tool in @("npm", "bun")) {
            if (Get-Command $tool -ErrorAction SilentlyContinue) {
                $pm = $tool
                break
            }
        }
    }

    if (-not $pm) {
        Write-Warn "No package manager (bun/npm) found — skipping $Label build"
        Write-Info "Install Bun or npm to enable $Label"
        if ($Required) {
            throw "No package manager found for required $Label build"
        }
        return
    }

    Write-Step "Building $Label ($pm) at $feDir..."
    $originalDir = Get-Location
    try {
        Set-Location $feDir

        Write-Step "Installing JavaScript dependencies with $pm..."
        Install-FrontendDependencies -PackageManager $pm
        if ($LASTEXITCODE -ne 0) {
            throw "$pm install failed"
        }

        & $pm run build
        if ($LASTEXITCODE -ne 0) {
            Write-Warn "$Label build failed (exit code $LASTEXITCODE)"
            if ($Required) {
                throw "$Label build failed (exit code $LASTEXITCODE)"
            }
            return
        }
        Write-Ok "$Label build complete"
    }
    catch {
        Write-Warn "$Label build failed: $_"
        if ($Required) {
            throw
        }
    }
    finally {
        Set-Location $originalDir
    }
}
