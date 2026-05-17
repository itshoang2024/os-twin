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

    # Pick the package manager that matches the committed lockfile.
    $pm = ""
    $lockPrefs = @(
        @{ File = "pnpm-lock.yaml"; Tool = "pnpm" },
        @{ File = "package-lock.json"; Tool = "npm" },
        @{ File = "npm-shrinkwrap.json"; Tool = "npm" },
        @{ File = "yarn.lock"; Tool = "yarn" },
        @{ File = "bun.lockb"; Tool = "bun" },
        @{ File = "bun.lock"; Tool = "bun" }
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
        foreach ($tool in @("pnpm", "npm", "yarn", "bun")) {
            if (Get-Command $tool -ErrorAction SilentlyContinue) {
                $pm = $tool
                break
            }
        }
    }

    if (-not $pm) {
        Write-Warn "No package manager (bun/pnpm/npm/yarn) found — skipping $Label build"
        Write-Info "Install Node.js and a package manager to enable $Label"
        if ($Required) {
            throw "No package manager found for required $Label build"
        }
        return
    }

    Write-Step "Building $Label ($pm) at $feDir..."
    $originalDir = Get-Location
    try {
        Set-Location $feDir

        Write-Step "Installing npm dependencies..."
        switch ($pm) {
            "pnpm" {
                $installOutput = & pnpm install --frozen-lockfile 2>&1
                if ($LASTEXITCODE -ne 0) {
                    $installText = ($installOutput | Out-String)
                    $isCi = $env:CI -in @("1", "true", "TRUE")
                    if ($installText -like "*ERR_PNPM_OUTDATED_LOCKFILE*" -and -not $isCi) {
                        Write-Warn "pnpm lockfile is out of date; retrying with --no-frozen-lockfile"
                        & pnpm install --no-frozen-lockfile
                    }
                    else {
                        $installOutput | ForEach-Object { Write-Host $_ }
                        throw "pnpm install --frozen-lockfile failed"
                    }
                }
                else {
                    $installOutput | ForEach-Object { Write-Host $_ }
                }
            }
            "npm" {
                if ((Test-Path "package-lock.json") -or (Test-Path "npm-shrinkwrap.json")) {
                    & npm ci
                }
                else {
                    & npm install
                }
            }
            "yarn" {
                & yarn install --frozen-lockfile
            }
            "bun" {
                & bun install --frozen-lockfile
            }
            default {
                & $pm install
            }
        }

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
