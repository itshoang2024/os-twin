<#
.SYNOPSIS
    agent.ps1 — PowerShell entry point for Agent OS CLI
    (PowerShell port of bin/agent)

.DESCRIPTION
    Wraps opencode with environment resolution so roles can invoke via:
      ostwin agent [args...]
      .agents/bin\agent.ps1 [args...]

.NOTES
    Environment variables (set automatically by Invoke-Agent.ps1):
      AGENT_OS_ROLE       — active role name (engineer, qa, etc.)
      AGENT_OS_SKILLS_DIR — isolated skills directory for this invocation
      AGENT_OS_ROOM_DIR   — war-room directory path
#>
[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments)]
    [string[]]$Arguments
)

$ErrorActionPreference = "Stop"

# --- Resolve AGENTS_DIR ---
$ScriptDir = Split-Path $PSCommandPath -Parent
$AgentsDir = (Resolve-Path (Join-Path $ScriptDir "..")).Path

# --- Load .env files ---
function Import-EnvFileAgent {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return }
    foreach ($line in Get-Content $Path) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith('#')) { continue }
        if ($trimmed -notmatch '=') { continue }
        $eqIdx = $trimmed.IndexOf('=')
        $key = $trimmed.Substring(0, $eqIdx).Trim()
        $val = $trimmed.Substring($eqIdx + 1).Trim()
        # Strip surrounding quotes
        if (($val.StartsWith('"') -and $val.EndsWith('"')) -or
            ($val.StartsWith("'") -and $val.EndsWith("'"))) {
            $val = $val.Substring(1, $val.Length - 2)
        }
        # Only set if not already defined
        if ($key -and -not [System.Environment]::GetEnvironmentVariable($key, 'Process')) {
            [System.Environment]::SetEnvironmentVariable($key, $val, 'Process')
        }
    }
}

$HomeDir = if ($env:USERPROFILE) { $env:USERPROFILE } else { $HOME }
Import-EnvFileAgent -Path (Join-Path $HomeDir ".ostwin" ".env")
Import-EnvFileAgent -Path (Join-Path $AgentsDir ".env")

# Force-disable Claude Code skill loading for every opencode run.
# Set after loading env files so local overrides cannot re-enable it.
$env:OPENCODE_DISABLE_CLAUDE_CODE = "1"

# --- Self-register PID for orchestration tracking ---
if ($env:AGENT_OS_PID_FILE) {
    $PID | Set-Content -Path $env:AGENT_OS_PID_FILE
}

# --- Ensure opencode is available ---
if (-not (Get-Command opencode -ErrorAction SilentlyContinue)) {
    Write-Error "[agent] ERROR: opencode not found in PATH."
    Write-Host "  Install with: brew install anomalyco/tap/opencode" -ForegroundColor Red
    Write-Host "            or: curl -fsSL https://opencode.ai/install | bash" -ForegroundColor Red
    exit 1
}

# --- Execute opencode run with all arguments ---
& opencode run @Arguments
exit $LASTEXITCODE
