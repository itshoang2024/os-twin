# ──────────────────────────────────────────────────────────────────────────────
# Setup-OpenCode.ps1 — OpenCode permissions patching
#
# Provides: Setup-OpenCodePermissions
#
# Requires: Lib.ps1, globals: $script:VenvDir
#           Python script: installer/scripts/patch_opencode_permissions.py
# ──────────────────────────────────────────────────────────────────────────────

if ($script:_SetupOpenCodePs1Loaded) { return }
$script:_SetupOpenCodePs1Loaded = $true

$script:OpenCodeScriptsDir = Join-Path $PSScriptRoot "scripts"

function Setup-OpenCodePermissions {
    [CmdletBinding()]
    param()

    # OpenCode config location on Windows
    $ocDir = if ($env:XDG_CONFIG_HOME) {
        Join-Path $env:XDG_CONFIG_HOME "opencode"
    }
    elseif ($env:USERPROFILE) {
        Join-Path $env:USERPROFILE ".config\opencode"
    }
    else {
        Join-Path $HOME ".config\opencode"
    }
    $ocConfig = Join-Path $ocDir "opencode.json"

    # Find Python
    $venvPython = Join-Path $script:VenvDir "Scripts\python.exe"
    $pyCmd = if (Test-Path $venvPython) { $venvPython } else { "python" }

    if (-not (Get-Command $pyCmd -ErrorAction SilentlyContinue) -and -not (Test-Path $pyCmd)) {
        Write-Warn "Python not available — skipping OpenCode permission patch"
        return
    }

    Write-Step "Patching OpenCode permissions (allow file reads + external directories)..."
    if (-not (Test-Path $ocDir)) {
        New-Item -ItemType Directory -Path $ocDir -Force | Out-Null
    }

    $patchScript = Join-Path $script:OpenCodeScriptsDir "patch_opencode_permissions.py"
    if (Test-Path $patchScript) {
        try {
            & $pyCmd $patchScript $ocConfig 2>$null
            if ($LASTEXITCODE -eq 0) {
                Write-Ok "OpenCode permissions ensured at $ocConfig"
            }
            else {
                throw "Script returned exit code $LASTEXITCODE"
            }
        }
        catch {
            Write-Warn "Failed to patch OpenCode permissions — headless agents may wait on file-read prompts"
            Write-Info "Manually add to ${ocConfig}:"
            Write-Info '  "permission": { "read": { "*": "allow" }, "external_directory": { "*": "allow" } }'
        }
    }
}
