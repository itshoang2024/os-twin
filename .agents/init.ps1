<#
.SYNOPSIS
    Agent OS — MCP Initialization (PowerShell port of init.sh)

.DESCRIPTION
    Sets up the per-project MCP configuration and optionally installs
    MCP extensions from the catalog.

.PARAMETER TargetDir
    Directory to initialize. Defaults to current directory.

.PARAMETER Yes
    Non-interactive mode — auto-approve all prompts.

.PARAMETER Help
    Show help text.

.EXAMPLE
    .\init.ps1 ~/my-project
    .\init.ps1 ~/my-project -Yes
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$TargetDir = ".",

    [string]$PlanId = "",

    [Alias('y')]
    [switch]$Yes,

    [Alias('q')]
    [switch]$Quick,

    [Alias('h')]
    [switch]$Help
)

$ErrorActionPreference = "Stop"

if ($Help) {
    Get-Help $PSCommandPath -Detailed
    exit 0
}

$ScriptDir = Split-Path $PSCommandPath -Parent
$TargetAgents = Join-Path $TargetDir ".agents"

# ─── Helper functions ─────────────────────────────────────────────────────────

function Write-Ok    { param([string]$Msg) Write-Host "    [OK] $Msg" }
function Write-Warn  { param([string]$Msg) Write-Host "    [WARN] $Msg" }
function Write-Fail  { param([string]$Msg) Write-Host "    [FAIL] $Msg" }
function Write-Info  { param([string]$Msg) Write-Host "    $Msg" }
function Write-Step  { param([string]$Msg) Write-Host "  -> $Msg" }

function Remove-OstwinManagedLegacyOpencodeMcp {
    param([string]$HomeDir)

    if (-not $HomeDir) { return }

    $legacyOpencodeFile = Join-Path (Join-Path $HomeDir ".opencode") "opencode.json"
    if (-not (Test-Path $legacyOpencodeFile)) { return }

    $managedServerNames = @(
        "channel",
        "warroom",
        "memory",
        "knowledge",
        "obscura-browser",
        "playwright",
        "chrome-devtools",
        "chrom-devtools"
    )

    try {
        $legacyJson = Get-Content $legacyOpencodeFile -Raw | ConvertFrom-Json -AsHashtable
        $removed = @()

        foreach ($mcpKey in @("mcp", "mcpServers")) {
            if (-not $legacyJson.ContainsKey($mcpKey)) { continue }
            $mcpBlock = $legacyJson[$mcpKey]
            if (-not ($mcpBlock -is [System.Collections.IDictionary])) { continue }

            foreach ($serverName in $managedServerNames) {
                if ($mcpBlock.Contains($serverName)) {
                    $mcpBlock.Remove($serverName)
                    $removed += "$mcpKey.$serverName"
                }
            }

            if ($mcpBlock.Count -eq 0) {
                $legacyJson.Remove($mcpKey)
            }
        }

        if ($removed.Count -eq 0) { return }

        $backupFile = "$legacyOpencodeFile.ostwin.bak"
        if (-not (Test-Path $backupFile)) {
            Copy-Item -Path $legacyOpencodeFile -Destination $backupFile -Force
        }

        $legacyJson | ConvertTo-Json -Depth 20 | Set-Content -Path $legacyOpencodeFile -Encoding UTF8
        Write-Ok "Removed legacy ~/.opencode MCP overrides ($($removed -join ', '))"
    }
    catch {
        Write-Warn "Could not clean legacy ~/.opencode/opencode.json MCP overrides: $_"
    }
}

function Invoke-Ask {
    param([string]$Prompt)
    if ($Yes) { return $true }
    $answer = Read-Host "    ? $Prompt [Y/n]"
    return (-not $answer -or $answer -match '^[Yy]')
}

# ─── Idempotency check (opt-in via --quick) ───────────────────────────────────
# By default, init always runs to guarantee a fresh .opencode/opencode.json.
# With --quick, fast-exits when the project is already fully initialized.
# ostwin run uses -Force by default; --resume skips init entirely.

if ($Quick) {
    $mcpConfigExists    = Test-Path (Join-Path $TargetAgents "mcp" "config.json")
    $opencodeFile       = Join-Path $TargetDir ".opencode" "opencode.json"
    $opencodeExists     = Test-Path $opencodeFile

    # Check if plan_id is already bound in the opencode.json memory URL
    $planIdBound = $true
    if ($PlanId -and $opencodeExists) {
        $ocCheck = Get-Content $opencodeFile -Raw
        $planIdBound = $ocCheck -match [regex]::Escape("plan_id=$PlanId")
    }

    if ($mcpConfigExists -and $opencodeExists -and $planIdBound) {
        Write-Host "  [OK] Project already initialized: $TargetDir"
        exit 0
    }
}

# ─── Banner ───────────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "  +==================================================+"
Write-Host "  |          Ostwin -- MCP Configuration              |"
Write-Host "  +==================================================+"
Write-Host ""
Write-Host "  Project: $TargetDir"
Write-Host ""

# ─── Ensure .agents/mcp exists ────────────────────────────────────────────────

Write-Step "Scaffolding MCP directory..."

if (-not (Test-Path $TargetAgents)) { New-Item -ItemType Directory -Path $TargetAgents -Force | Out-Null }
$mcpDir = Join-Path $TargetAgents "mcp"
if (-not (Test-Path $mcpDir)) { New-Item -ItemType Directory -Path $mcpDir -Force | Out-Null }

# Seed extensions.json if not present
$extensionsFile = Join-Path $mcpDir "extensions.json"
if (-not (Test-Path $extensionsFile)) {
    '{"extensions":[]}' | Set-Content -Path $extensionsFile -Encoding UTF8
}

# Copy catalog from source if not present or outdated
$srcCatalog = Join-Path $ScriptDir "mcp" "mcp-catalog.json"
if (Test-Path $srcCatalog) {
    Copy-Item -Path $srcCatalog -Destination (Join-Path $mcpDir "mcp-catalog.json") -Force -ErrorAction SilentlyContinue
}

# Copy builtin config from source
$srcBuiltin = Join-Path $ScriptDir "mcp" "mcp-builtin.json"
if (Test-Path $srcBuiltin) {
    Copy-Item -Path $srcBuiltin -Destination (Join-Path $mcpDir "mcp-builtin.json") -Force -ErrorAction SilentlyContinue
}

# Copy extension manager script
$srcExtScript = Join-Path $ScriptDir "mcp" "mcp-extension.sh"
if (Test-Path $srcExtScript) {
    $dstExtScript = Join-Path $mcpDir "mcp-extension.sh"
    $srcResolved = (Resolve-Path $srcExtScript -ErrorAction SilentlyContinue).Path ?? $srcExtScript
    $dstResolved = $dstExtScript
    if (Test-Path $dstExtScript) { $dstResolved = (Resolve-Path $dstExtScript -ErrorAction SilentlyContinue).Path ?? $dstExtScript }
    if ($srcResolved -ne $dstResolved) {
        Copy-Item -Path $srcExtScript -Destination $dstExtScript -Force
    }
}

# Copy vault.py and config_resolver.py
foreach ($pyFile in @("vault.py", "config_resolver.py")) {
    $srcPy = Join-Path $ScriptDir "mcp" $pyFile
    if (Test-Path $srcPy) {
        Copy-Item -Path $srcPy -Destination (Join-Path $mcpDir $pyFile) -Force -ErrorAction SilentlyContinue
    }
}

$ProjectMcpConfig = Join-Path $mcpDir "config.json"
$LegacyConfig = Join-Path $mcpDir "mcp-config.json"

if (-not (Test-Path $ProjectMcpConfig)) {
    $srcMcpConfig = Join-Path $ScriptDir "mcp" "mcp-config.json"
    $builtinConfig = Join-Path $mcpDir "mcp-builtin.json"

    if (Test-Path $srcMcpConfig) {
        Copy-Item -Path $srcMcpConfig -Destination $ProjectMcpConfig -Force
    }
    elseif (Test-Path $LegacyConfig) {
        Copy-Item -Path $LegacyConfig -Destination $ProjectMcpConfig -Force
    }
    elseif (Test-Path $builtinConfig) {
        Copy-Item -Path $builtinConfig -Destination $ProjectMcpConfig -Force
    }
    else {
        '{"mcp":{}}' | Set-Content -Path $ProjectMcpConfig -Encoding UTF8
    }
    Write-Ok "MCP config seeded"
}
else {
    Write-Ok "MCP config exists (will recompile)"
}

Write-Info "Config: $ProjectMcpConfig"

# ─── Global MCP config ───────────────────────────────────────────────────────

$HomeDir = if ($env:USERPROFILE) { $env:USERPROFILE } else { $HOME }
$GlobalMcpDir = Join-Path $HomeDir ".ostwin" ".agents" "mcp"
$GlobalMcpConfig = Join-Path $GlobalMcpDir "config.json"

if (-not (Test-Path $GlobalMcpDir)) { New-Item -ItemType Directory -Path $GlobalMcpDir -Force | Out-Null }

if (-not (Test-Path $GlobalMcpConfig)) {
    $globalBuiltin = Join-Path $GlobalMcpDir "mcp-builtin.json"
    if (Test-Path $globalBuiltin) {
        Copy-Item -Path $globalBuiltin -Destination $GlobalMcpConfig -Force
    }
    else {
        '{"mcp":{}}' | Set-Content -Path $GlobalMcpConfig -Encoding UTF8
    }
    Write-Ok "Global MCP config created at $GlobalMcpConfig"
}
else {
    Write-Ok "Global MCP config exists (preserved)"
}

# ─── Compile opencode.json ────────────────────────────────────────────────────

$McpExtensionScript = Join-Path $ScriptDir "mcp" "mcp-extension.sh"
if ((Test-Path $McpExtensionScript) -and (Get-Command bash -ErrorAction SilentlyContinue)) {
    Write-Step "Compiling project-level MCP config..."
    try {
        & bash $McpExtensionScript --project-dir $TargetDir compile
    } catch {
        Write-Warn "MCP compile returned non-zero (non-critical): $_"
    }
}

# ─── Sync MCP to global ~/.config/opencode/opencode.json ─────────────────────
# Runs the same logic as `ostwin mcp sync`:
#   resolve_opencode.py sync → resolves servers + generates agent permissions
#   from role.json mcp_refs → writes to ~/.config/opencode/opencode.json.

$ResolveScript = Join-Path $ScriptDir "mcp" "resolve_opencode.py"
$GlobalOpencodeDir = if ($env:XDG_CONFIG_HOME) { Join-Path $env:XDG_CONFIG_HOME "opencode" } else { Join-Path $HOME ".config" "opencode" }

if (Test-Path $ResolveScript) {
    Write-Step "Syncing MCP config (ostwin mcp sync)..."

    # Find python: prefer venv, fall back to system
    $pythonCmd = "python3"
    $globalVenvPython = Join-Path $HOME ".ostwin" "venv" "bin" "python"
    if (Test-Path $globalVenvPython) { $pythonCmd = $globalVenvPython }

    # Collect optional flags
    $syncArgs = @($ResolveScript, "sync")

    # Pass project's config.json so project-level extensions are resolved
    # (without this, sync only reads the global mcp-builtin.json and misses
    # any extensions installed into the project's .agents/mcp/config.json)
    $projectMcpConfig = Join-Path $TargetAgents "mcp" "config.json"
    if (Test-Path $projectMcpConfig) {
        $syncArgs += @("--config", $projectMcpConfig)
    }

    # Pass env file if available
    $projectEnv = Join-Path $TargetDir ".env"
    $mcpEnv = Join-Path $TargetAgents "mcp" ".env.mcp"
    if (Test-Path $projectEnv)      { $syncArgs += @("--env-file", $projectEnv) }
    elseif (Test-Path $mcpEnv)      { $syncArgs += @("--env-file", $mcpEnv) }

    try {
        & $pythonCmd @syncArgs
    } catch {
        Write-Warn "Failed to sync global config-oc.json (non-critical): $_"
    }
}

# ─── Sync project role definitions to OpenCode agents directory ──────────────
# Ensures that roles defined in .agents/roles/ and contributes/roles/ are
# available as named agents for `opencode run --agent <role>`.
# This runs on every init so contributed roles (e.g. security-specialist) are
# always present even on a clean machine that hasn't run the full installer.

$SyncAgentsScript = Join-Path $ScriptDir "plan" "Sync-ContributedAgents.ps1"
if (Test-Path $SyncAgentsScript) {
    Write-Step "Syncing role definitions to OpenCode agents..."
    try {
        & $SyncAgentsScript -ProjectDir $TargetDir
    } catch {
        Write-Warn "Agent sync returned non-zero (non-critical): $_"
    }
}

# ─── Clone global opencode.json to project .opencode/ ────────────────────────
# Ensures agents running in the project context (via Invoke-Agent.ps1) have the
# full config: MCP servers, agent permissions, tools blocks, provider definitions.
#
# MERGE LOGIC (not simple copy):
#   - If project .opencode/opencode.json doesn't exist → copy from global
#   - If it DOES exist (created by mcp-extension.sh compile with project MCP
#     servers) → merge global keys (agent permissions, tools, provider, model)
#     while preserving the project's MCP server block.
#   - This prevents the global sync from overwriting project-level extensions
#     that were just compiled by the previous step.

$ProjectOpencodeDir = Join-Path $TargetDir ".opencode"
if (-not (Test-Path $ProjectOpencodeDir)) {
    New-Item -ItemType Directory -Path $ProjectOpencodeDir -Force | Out-Null
}

$GlobalOpencodeFile = Join-Path $GlobalOpencodeDir "opencode.json"
$ProjectOpencodeFile = Join-Path $ProjectOpencodeDir "opencode.json"

if (Test-Path $GlobalOpencodeFile) {
    if (-not (Test-Path $ProjectOpencodeFile)) {
        # No project file yet — simple copy from global
        Copy-Item -Path $GlobalOpencodeFile -Destination $ProjectOpencodeFile -Force
        Write-Ok "Created .opencode/opencode.json from global config"
    }
    else {
        # Project file exists (likely from mcp-extension.sh compile).
        # Merge: keep project MCP servers, add global agent/tools/permission blocks.
        try {
            $globalJson = Get-Content $GlobalOpencodeFile -Raw | ConvertFrom-Json -AsHashtable
            $projectJson = Get-Content $ProjectOpencodeFile -Raw | ConvertFrom-Json -AsHashtable

            # Keys that the global sync is authoritative for (role permissions, tools, provider)
            $managedKeys = @("agent", "tools", "permission", "provider", "model")

            foreach ($key in $managedKeys) {
                if ($globalJson.ContainsKey($key)) {
                    $projectJson[$key] = $globalJson[$key]
                }
                elseif ($projectJson.ContainsKey($key)) {
                    # Key exists in project but not in global — remove stale entry
                    $projectJson.Remove($key)
                }
            }

            # Write merged result
            $projectJson | ConvertTo-Json -Depth 10 | Set-Content -Path $ProjectOpencodeFile -Encoding UTF8
            Write-Ok "Merged global agent/tools/permissions into project .opencode/opencode.json"
        }
        catch {
            # Fallback: if merge fails, overwrite with global (better than nothing)
            Write-Warn "Merge failed, falling back to global copy: $_"
            Copy-Item -Path $GlobalOpencodeFile -Destination $ProjectOpencodeFile -Force
        }
    }
}
elseif (-not (Test-Path $ProjectOpencodeFile)) {
    # Neither global nor project file exists — leave empty (compile may have failed)
    Write-Warn "No global or project opencode.json found"
}

Remove-OstwinManagedLegacyOpencodeMcp -HomeDir $HomeDir

# ─── Bind plan_id to memory MCP URL ──────────────────────────────────────────
# When -PlanId is provided, patch the memory-pool URL in .opencode/opencode.json
# so all agents in this plan automatically scope memory to the correct namespace.
# Also creates the centralized memory directory and a symlink from project/.memory.

if ($PlanId -and (Test-Path $ProjectOpencodeFile)) {
    # Strip any existing query params (?plan_id=... or ?persist_dir=...) then append plan_id.
    # PowerShell string replacement (works on all platforms):
    $ocContent = Get-Content $ProjectOpencodeFile -Raw
    # Remove any query string from the memory-pool URL
    $ocContent = $ocContent -replace '(/api/memory-pool/mcp)\?[^"]*', '$1'
    # Append the plan_id
    $ocContent = $ocContent -replace '(/api/memory-pool/mcp)"', "`$1?plan_id=$PlanId`""
    $ocContent | Out-File -FilePath $ProjectOpencodeFile -Encoding utf8 -NoNewline
    Write-Ok "Bound plan_id=$PlanId to memory MCP URL"

    # Create centralized memory directory + symlink from project/.memory
    # Use "memory-$PlanId" naming to match global-memory-server.py convention
    # (it discovers directories with the "memory-" prefix).
    $memoryBase = Join-Path $env:HOME ".ostwin" "memory"
    $centralDir = Join-Path $memoryBase "memory-$PlanId"
    $symlinkPath = Join-Path $TargetDir ".memory"

    if (-not (Test-Path $centralDir)) {
        New-Item -ItemType Directory -Path $centralDir -Force | Out-Null
    }

    # ── Step 1: Migrate from old bare-name directory (without "memory-" prefix) ──
    $legacyDir = Join-Path $memoryBase $PlanId
    if ((Test-Path $legacyDir) -and ($legacyDir -ne $centralDir)) {
        if (Get-Command rsync -ErrorAction SilentlyContinue) {
            & rsync -a "$legacyDir/" "$centralDir/" 2>$null
        } else {
            Copy-Item "$legacyDir/*" "$centralDir/" -Recurse -Force -ErrorAction SilentlyContinue
        }
        # Update any existing .memory symlink to point at the new location FIRST,
        # then remove the old bare-name directory.
        if (Test-Path $symlinkPath) {
            try {
                $di = [System.IO.DirectoryInfo]::new($symlinkPath)
                if ($di.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
                    # Symlink exists — repoint it to the new centralDir
                    if (Get-Command ln -ErrorAction SilentlyContinue) {
                        & ln -sfn $centralDir $symlinkPath
                    } else {
                        Remove-Item $symlinkPath -Force -ErrorAction SilentlyContinue
                        New-Item -ItemType SymbolicLink -Path $symlinkPath -Target $centralDir -Force | Out-Null
                    }
                }
            } catch {
                # Broken symlink — will be replaced in Step 3
            }
        }
        Remove-Item $legacyDir -Recurse -Force -ErrorAction SilentlyContinue
        Write-Ok "Migrated legacy memory dir: $legacyDir -> $centralDir"
    }

    # ── Step 2: If .memory is a real directory (not a symlink), migrate contents ──
    # Use [System.IO.DirectoryInfo] instead of Get-Item because Get-Item throws
    # on broken symlinks (target doesn't resolve) even though the link entry
    # exists on disk and Test-Path returns $true.
    $existingIsSymlink = $false
    $existingIsBrokenSymlink = $false

    if (Test-Path $symlinkPath) {
        try {
            $dirInfo = [System.IO.DirectoryInfo]::new($symlinkPath)
            $existingIsSymlink = $dirInfo.Attributes -band [System.IO.FileAttributes]::ReparsePoint
            # DirectoryInfo.Exists returns $false when the symlink target
            # doesn't resolve (broken symlink), even though the link entry is on disk
            if ($existingIsSymlink -and -not $dirInfo.Exists) {
                $existingIsBrokenSymlink = $true
            }
        } catch {
            # Unexpected failure — treat as a broken symlink so we replace it
            $existingIsSymlink = $true
            $existingIsBrokenSymlink = $true
        }
    }

    if ((Test-Path $symlinkPath) -and -not $existingIsSymlink) {
        if (Get-Command rsync -ErrorAction SilentlyContinue) {
            & rsync -a "$symlinkPath/" "$centralDir/" 2>$null
        } else {
            Copy-Item "$symlinkPath/*" "$centralDir/" -Recurse -Force -ErrorAction SilentlyContinue
        }
        Remove-Item $symlinkPath -Recurse -Force
    }

    # ── Step 3: Create symlink if needed ──
    # Test-Path returns $true for broken symlinks (checks link entry, not target),
    # so we must also check $existingIsBrokenSymlink to replace dangling links.
    if (-not (Test-Path $symlinkPath) -or $existingIsBrokenSymlink) {
        if (Get-Command ln -ErrorAction SilentlyContinue) {
            & ln -sfn $centralDir $symlinkPath
        } else {
            New-Item -ItemType SymbolicLink -Path $symlinkPath -Target $centralDir -Force | Out-Null
        }
        Write-Ok "Memory symlink: .memory -> $centralDir"
    }
}

# ─── Update .gitignore ────────────────────────────────────────────────────────

$Gitignore = Join-Path $TargetDir ".gitignore"

$OstwinBlock = @"
# Ostwin generated
.opencode/opencode.json
.war-rooms/
.agents/*
!.agents/memory/
.memory
"@

if (Test-Path $Gitignore) {
    $content = Get-Content $Gitignore -Raw
    if ($content -match '# Ostwin generated') {
        # Remove existing Ostwin block and re-add
        $lines = Get-Content $Gitignore
        $filtered = $lines | Where-Object {
            $_ -ne '# Ostwin generated' -and
            $_ -ne '.opencode/opencode.json' -and
            $_ -ne '.war-rooms/' -and
            $_ -ne '.agents/*' -and
            $_ -ne '!.agents/memory/' -and
            $_ -ne '.agents/' -and
            $_ -ne '.memory'
        }
        # Remove trailing blank lines
        while ($filtered.Count -gt 0 -and [string]::IsNullOrWhiteSpace($filtered[-1])) {
            $filtered = $filtered[0..($filtered.Count - 2)]
        }
        $filtered += ""
        $filtered += $OstwinBlock -split "`n"
        $filtered | Set-Content -Path $Gitignore -Encoding UTF8
        Write-Ok "Updated Ostwin entries in .gitignore"
    }
    else {
        Add-Content -Path $Gitignore -Value "`n$OstwinBlock" -Encoding UTF8
        Write-Ok "Added Ostwin entries to .gitignore"
    }
}
else {
    $OstwinBlock | Set-Content -Path $Gitignore -Encoding UTF8
    Write-Ok "Created .gitignore with Ostwin entries"
}

# ─── Summary ─────────────────────────────────────────────────────────────────

$OpencodeConfig = Join-Path $TargetDir ".opencode" "opencode.json"
Write-Host ""
Write-Host "  Manage extensions:"
Write-Host "    ostwin mcp catalog              Show available packages"
Write-Host "    ostwin mcp install <name>       Install an extension"
Write-Host "    ostwin mcp list                 Show installed extensions"
Write-Host "    ostwin mcp sync                 Rebuild config.json"
Write-Host ""
