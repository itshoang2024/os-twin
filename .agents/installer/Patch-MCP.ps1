# ──────────────────────────────────────────────────────────────────────────────
# Patch-MCP.ps1 — MCP config patching, env injection, OpenCode merge
#
# Provides: Patch-McpConfig
#
# Requires: Lib.ps1, globals: $script:InstallDir, $script:VenvDir
#           Python scripts in installer/scripts/ (reused from EPIC-001)
# ──────────────────────────────────────────────────────────────────────────────

if ($script:_PatchMcpPs1Loaded) { return }
$script:_PatchMcpPs1Loaded = $true

$script:PatchScriptsDir = Join-Path $PSScriptRoot "scripts"

function Patch-McpConfig {
    [CmdletBinding()]
    param()

    $mcpConfig = Join-Path $script:InstallDir ".agents\mcp\config.json"
    $envFile = Join-Path $script:InstallDir ".env"

    if (-not (Test-Path $mcpConfig)) {
        return
    }

    Write-Step "Patching MCP config..."

    # Windows venv Python path
    $venvPython = Join-Path $script:VenvDir "Scripts\python.exe"

    # 1. Ensure critical path env vars are set in .env
    # These are required for {env:AGENT_DIR}, {env:OSTWIN_PYTHON}, and {env:PATH}
    # resolution. PATH must include .agents\bin so native CLI-backed MCP servers
    # such as `obscura mcp` can start even before a new shell picks up PATH changes.
    # NOTE: .env files use KEY=VALUE format (no 'export' prefix - that's for shell scripts)
    $pathEntries = @(
        (Join-Path $script:VenvDir "Scripts"),
        (Join-Path $script:InstallDir ".agents\bin")
    )
    if ($env:USERPROFILE) {
        $pathEntries += Join-Path $env:USERPROFILE ".local\bin"
        $pathEntries += Join-Path $env:USERPROFILE ".opencode\bin"
    }
    if ($env:Path) {
        $pathEntries += ($env:Path -split ";" | Where-Object { $_ })
    }
    $mcpPath = ($pathEntries | Where-Object { $_ } | Select-Object -Unique) -join ";"

    $envEntries = @(
        "AGENT_DIR=$($script:InstallDir)",
        "OSTWIN_PYTHON=$venvPython",
        "PATH=$mcpPath"
    )

    # Read existing content
    $existingContent = if (Test-Path $envFile) { Get-Content $envFile -Raw } else { "" }

    # Remove old entries (with or without export) and add fresh ones
    $cleanedContent = $existingContent
    foreach ($key in @("AGENT_DIR", "OSTWIN_PYTHON", "PATH")) {
        $cleanedContent = $cleanedContent -replace "(?m)^export $key=.*\r?\n", ""
        $cleanedContent = $cleanedContent -replace "(?m)^$key=.*\r?\n", ""
    }

    # Append new entries
    $newEntries = $envEntries -join "`n"
    $finalContent = $cleanedContent.TrimEnd() + "`n" + $newEntries + "`n"
    Set-Content -Path $envFile -Value $finalContent -Encoding UTF8

    # 2. Inject all .env variables into every MCP server's "environment" block
    if (Test-Path $envFile) {
        $injectScript = Join-Path $script:PatchScriptsDir "inject_env_to_mcp.py"
        if (Test-Path $injectScript) {
            try {
                & $venvPython $injectScript $mcpConfig $envFile 2>$null
            }
            catch {
                Write-Warn "Failed to inject env to MCP config: $_"
            }
        }
    }

    # 3. Normalize + validate + merge MCP servers into opencode config
    # On Windows, XDG_CONFIG_HOME may not exist — use LOCALAPPDATA or USERPROFILE
    $opencodeHome = if ($env:XDG_CONFIG_HOME) {
        Join-Path $env:XDG_CONFIG_HOME "opencode"
    }
    elseif ($env:USERPROFILE) {
        Join-Path $env:USERPROFILE ".config\opencode"
    }
    else {
        Join-Path $HOME ".config\opencode"
    }

    if (-not (Test-Path $opencodeHome)) {
        New-Item -ItemType Directory -Path $opencodeHome -Force | Out-Null
    }

    $mergeScript = Join-Path $script:PatchScriptsDir "merge_mcp_to_opencode.py"
    $opencodeJson = Join-Path $opencodeHome "opencode.json"
    $mcpModuleDir = Join-Path $script:InstallDir ".agents\mcp"

    if (Test-Path $mergeScript) {
        try {
            & $venvPython $mergeScript $mcpConfig $opencodeJson $mcpModuleDir 2>$null
        }
        catch {
            Write-Warn "Failed to merge MCP to opencode config: $_"
        }
    }

    Write-Ok "MCP config synced"
}
