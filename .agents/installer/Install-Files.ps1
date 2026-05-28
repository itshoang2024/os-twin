# ──────────────────────────────────────────────────────────────────────────────
# Install-Files.ps1 — File installation, robocopy, MCP seeding, symlinks,
#                      migrations
#
# Provides: Install-Files, Compute-BuildHash
#
# Requires: Lib.ps1, Versions.ps1, Detect-OS.ps1,
#           globals: $script:InstallDir, $script:ScriptDir, $script:SourceDir,
#                    $script:VenvDir
# ──────────────────────────────────────────────────────────────────────────────

if ($script:_InstallFilesPs1Loaded) { return }
$script:_InstallFilesPs1Loaded = $true

# Installer scripts dir for Python helpers
$script:InstallerScriptsDir = Join-Path $PSScriptRoot "scripts"

function Install-Files {
    [CmdletBinding()]
    param()

    # Suppress PowerShell progress bars (Remove-Item -Recurse shows file-delete progress on Windows)
    $oldProgressPref = $ProgressPreference
    $ProgressPreference = 'SilentlyContinue'

    try {

    Write-Step "Installing OS Twin to $script:InstallDir..."

    $agentsDir = Join-Path $script:InstallDir ".agents"
    if (-not (Test-Path $agentsDir)) {
        New-Item -ItemType Directory -Path $agentsDir -Force | Out-Null
    }

    # Ensure clean slate for core roles
    $rolesDir = Join-Path $agentsDir "roles"
    if (Test-Path $rolesDir) {
        & cmd.exe /c "rd /s /q `"$rolesDir`"" 2>$null
    }

    # Sync ScriptDir contents using robocopy (preferred) or Copy-Item
    $excludeDirs = @('.venv', 'logs', '__pycache__', 'plans')
    $excludeFiles = @('*.pid', 'dashboard.pid', '*.pyc', 'config.json', '.env.mcp')

    if (Get-Command robocopy -ErrorAction SilentlyContinue) {
        # robocopy: /E = recurse, /XD = exclude dirs, /XF = exclude files, /NFL /NDL /NJH /NJS = quiet
        $robocopyExclDirs = $excludeDirs + @('mcp')
        & robocopy $script:ScriptDir $agentsDir /E /XD $robocopyExclDirs /XF $excludeFiles /NFL /NDL /NJH /NJS /NP /R:1 /W:1 2>&1 | Out-Null
        # robocopy returns non-zero on success (1 = files copied, 0 = no changes)
        # Only exit codes >= 8 are actual errors
    }
    else {
        # Fallback: Copy-Item with manual exclusions
        Get-ChildItem -Path $script:ScriptDir -Exclude @('mcp', 'plans') |
            Where-Object { $_.Name -notin $excludeDirs } |
            ForEach-Object {
                $dest = Join-Path $agentsDir $_.Name
                if ($_.PSIsContainer) {
                    Copy-Item -Path $_.FullName -Destination $dest -Recurse -Force -ErrorAction SilentlyContinue
                }
                else {
                    Copy-Item -Path $_.FullName -Destination $dest -Force -ErrorAction SilentlyContinue
                }
            }
    }

    # Seed plans/ on first install — never overwrite
    $plansDir = Join-Path $agentsDir "plans"
    if (-not (Test-Path $plansDir)) {
        New-Item -ItemType Directory -Path $plansDir -Force | Out-Null
    }
    $planTemplate = Join-Path $plansDir "PLAN.template.md"
    $srcPlanTemplate = Join-Path $script:ScriptDir "plans\PLAN.template.md"
    if (-not (Test-Path $planTemplate) -and (Test-Path $srcPlanTemplate)) {
        Copy-Item -Path $srcPlanTemplate -Destination $planTemplate
    }

    # MCP: seed config on first install, never overwrite
    Seed-McpConfig

    # Symlink ~/.ostwin/mcp -> ~/.ostwin/.agents/mcp
    Setup-McpSymlink

    # MCP: migrate legacy mcp-config.json → config.json
    Migrate-McpConfig

    # Dashboard: always override from source repo
    Sync-Dashboard

    # Contributed roles
    Load-ContributedRoles

    # Make scripts executable (Windows doesn't need chmod, but mark .ps1 files)
    Write-Ok "Files installed"

    } finally {
        # Restore progress preference even if an exception occurred
        $ProgressPreference = $oldProgressPref
    }
}

# ─── Internal helpers ────────────────────────────────────────────────────────

function Seed-McpConfig {
    [CmdletBinding()]
    param()

    $mcpDir = Join-Path $script:InstallDir ".agents\mcp"
    $mcpConfig = Join-Path $mcpDir "config.json"

    # Find seed source
    $seedSrc = ""
    $srcBuiltinJson = Join-Path $script:ScriptDir "mcp\mcp-builtin.json"
    $srcConfigJson = Join-Path $script:ScriptDir "mcp\config.json"
    $srcMcpConfigJson = Join-Path $script:ScriptDir "mcp\mcp-config.json"

    if (Test-Path $srcBuiltinJson) { $seedSrc = $srcBuiltinJson }
    elseif (Test-Path $srcConfigJson) { $seedSrc = $srcConfigJson }
    elseif (Test-Path $srcMcpConfigJson) { $seedSrc = $srcMcpConfigJson }

    # Ensure mcp dir exists
    if (-not (Test-Path $mcpDir)) {
        New-Item -ItemType Directory -Path $mcpDir -Force | Out-Null
    }

    # Seed or update config.json
    if (-not (Test-Path $mcpConfig)) {
        if ($seedSrc) {
            Write-Step "Seeding mcp/config.json (first install)..."
            Copy-Item -Path $seedSrc -Destination $mcpConfig
            Write-Ok "mcp/config.json seeded from $(Split-Path $seedSrc -Leaf)"
        }
        else {
            Write-Warn "No source mcp config found — skipping seed"
        }
    }
    else {
        # Always update the builtin template
        $srcBuiltin = Join-Path $script:ScriptDir "mcp\mcp-builtin.json"
        $dstBuiltin = Join-Path $mcpDir "mcp-builtin.json"
        if (Test-Path $srcBuiltin) {
            Copy-Item -Path $srcBuiltin -Destination $dstBuiltin -Force
        }

        # Always update catalog
        $srcCatalog = Join-Path $script:ScriptDir "mcp\mcp-catalog.json"
        $dstCatalog = Join-Path $mcpDir "mcp-catalog.json"
        if (Test-Path $srcCatalog) {
            Copy-Item -Path $srcCatalog -Destination $dstCatalog -Force
        }

        # Merge new built-in servers into config.json
        if ((Test-Path $mcpConfig) -and (Test-Path $dstBuiltin)) {
            # Prefer venv python, fall back to system python
            $mergePy = Join-Path $script:VenvDir "Scripts\python.exe"
            if (-not (Test-Path $mergePy)) {
                $mergePy = $script:PythonCmd
                if (-not $mergePy) { $mergePy = "python" }
            }
            $mergeScript = Join-Path $script:InstallerScriptsDir "merge_mcp_builtin.py"
            if (Test-Path $mergeScript) {
                try {
                    & $mergePy $mergeScript $mcpConfig $dstBuiltin 2>$null
                    Write-Ok "Merged new built-in MCP servers"
                }
                catch {
                    Write-Warn "Failed to merge MCP built-in servers: $_"
                }
            }
        }
    }

    # Always sync MCP server scripts (.py, .sh, requirements.txt)
    # Only sync specific static JSON files - do NOT overwrite runtime state (config.json, extensions.json)
    $mcpSrcDir = Join-Path $script:ScriptDir "mcp"
    if (Test-Path $mcpSrcDir) {
        # Sync scripts
        foreach ($ext in @("*.py", "*.sh", "requirements.txt")) {
            Get-ChildItem -Path $mcpSrcDir -Filter $ext -ErrorAction SilentlyContinue |
                ForEach-Object { Copy-Item -Path $_.FullName -Destination $mcpDir -Force }
        }
        # Sync only specific static JSON files (not config.json or extensions.json which are runtime state)
        foreach ($jsonName in @("mcp-builtin.json", "mcp-catalog.json")) {
            $src = Join-Path $mcpSrcDir $jsonName
            if (Test-Path $src) {
                Copy-Item -Path $src -Destination (Join-Path $mcpDir $jsonName) -Force
            }
        }
        foreach ($legacyName in @("obscura-browser-server.py", "test_obscura_browser.py")) {
            $legacyPath = Join-Path $mcpDir $legacyName
            if (Test-Path $legacyPath) {
                Remove-Item -Path $legacyPath -Force
            }
        }
        Write-Ok "mcp/ scripts synced"
    }
}

function Setup-McpSymlink {
    [CmdletBinding()]
    param()

    $mcpLink = Join-Path $script:InstallDir "mcp"
    $mcpReal = Join-Path $script:InstallDir ".agents\mcp"

    if (Test-Path $mcpLink) {
        $item = Get-Item $mcpLink -Force
        if ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
            # Already a symlink — update if target changed
            $currentTarget = $item.Target
            if ($currentTarget -ne $mcpReal) {
                Remove-Item $mcpLink -Force
                New-Item -ItemType SymbolicLink -Path $mcpLink -Target $mcpReal -Force | Out-Null
            }
        }
        elseif ($item.PSIsContainer) {
            # Legacy real directory — migrate
            Write-Step "Migrating $mcpLink to symlink..."
            Get-ChildItem -Path $mcpLink -File | ForEach-Object {
                $dstFile = Join-Path $mcpReal $_.Name
                if (-not (Test-Path $dstFile)) {
                    Copy-Item -Path $_.FullName -Destination $mcpReal
                }
            }
            Remove-Item $mcpLink -Recurse -Force
            try {
                New-Item -ItemType SymbolicLink -Path $mcpLink -Target $mcpReal -Force | Out-Null
                Write-Ok "Migrated $mcpLink -> .agents\mcp (symlink)"
            }
            catch {
                # If symlink fails (no dev mode), use junction
                & cmd.exe /c "mklink /J `"$mcpLink`" `"$mcpReal`"" 2>$null | Out-Null
                Write-Ok "Migrated $mcpLink -> .agents\mcp (junction)"
            }
        }
    }
    else {
        if (Test-Path $mcpReal) {
            try {
                New-Item -ItemType SymbolicLink -Path $mcpLink -Target $mcpReal -Force | Out-Null
            }
            catch {
                # Fallback to junction (doesn't require Developer Mode)
                & cmd.exe /c "mklink /J `"$mcpLink`" `"$mcpReal`"" 2>$null | Out-Null
            }
        }
    }
}

function Migrate-McpConfig {
    [CmdletBinding()]
    param()

    $mcpDir = Join-Path $script:InstallDir ".agents\mcp"
    $oldConfig = Join-Path $mcpDir "mcp-config.json"
    $newConfig = Join-Path $mcpDir "config.json"

    if ((Test-Path $oldConfig) -and -not (Test-Path $newConfig)) {
        Write-Step "Migrating mcp-config.json → config.json..."
        Move-Item -Path $oldConfig -Destination $newConfig
        Write-Ok "Renamed mcp-config.json → config.json"
    }
    elseif ((Test-Path $oldConfig) -and (Test-Path $newConfig)) {
        Remove-Item $oldConfig -Force
        Write-Ok "Removed legacy mcp-config.json (config.json exists)"
    }
}

function Sync-Dashboard {
    [CmdletBinding()]
    param()

    $dashSrc = ""
    $candidates = @(
        (Join-Path $script:SourceDir "dashboard"),
        (Join-Path (Split-Path $script:ScriptDir -Parent) "dashboard"),
        (Join-Path $script:ScriptDir "dashboard")
    )

    foreach ($c in $candidates) {
        if ($c -and (Test-Path (Join-Path $c "api.py"))) {
            $dashSrc = (Resolve-Path $c).Path
            break
        }
    }

    if ($dashSrc) {
        Write-Step "Syncing dashboard from $dashSrc (override)..."
        $dashDst = Join-Path $script:InstallDir "dashboard"
        if (Test-Path $dashDst) {
            & cmd.exe /c "rd /s /q `"$dashDst`"" 2>$null
        }
        New-Item -ItemType Directory -Path $dashDst -Force | Out-Null

        if (Get-Command robocopy -ErrorAction SilentlyContinue) {
            & robocopy $dashSrc $dashDst /E /XD '__pycache__' 'node_modules' '.next' /XF '*.pyc' '.DS_Store' /NFL /NDL /NJH /NJS /NP /R:1 /W:1 2>&1 | Out-Null
        }
        else {
            Copy-Item -Path "$dashSrc\*" -Destination $dashDst -Recurse -Force
        }
        Write-Ok "Dashboard → $dashDst"
    }
    else {
        Write-Warn "Dashboard source not found — dashboard/ not updated"
        Write-Info "Pass the repo root: .\install.ps1 -SourceDir C:\path\to\agent-os"
    }
}

function Load-ContributedRoles {
    [CmdletBinding()]
    param()

    $contributesRoles = ""
    $candidates = @(
        (Join-Path $script:SourceDir "contributes\roles"),
        (Join-Path (Split-Path $script:ScriptDir -Parent) "contributes\roles")
    )

    foreach ($c in $candidates) {
        if (Test-Path $c) {
            $contributesRoles = (Resolve-Path $c).Path
            break
        }
    }

    if ($contributesRoles) {
        Write-Step "Loading contributed roles..."
        $rolesDir = Join-Path $script:InstallDir ".agents\roles"
        if (-not (Test-Path $rolesDir)) {
            New-Item -ItemType Directory -Path $rolesDir -Force | Out-Null
        }
        $loaded = 0
        Get-ChildItem -Path $contributesRoles -Directory | ForEach-Object {
            $targetRole = Join-Path $rolesDir $_.Name
            if (-not (Test-Path $targetRole)) {
                Copy-Item -Path $_.FullName -Destination $targetRole -Recurse
                $loaded++
            }
        }
        Write-Ok "$loaded contributed role(s) loaded"
    }
}

# ─── Build hash ──────────────────────────────────────────────────────────────

function Compute-BuildHash {
    [CmdletBinding()]
    param()

    Write-Step "Computing build hash..."

    $excludePatterns = @(
        "*.pid", ".env", ".build-hash"
    )
    $excludeDirs = @(
        ".venv", ".zvec", "logs", "node_modules", "__pycache__"
    )

    try {
        $files = Get-ChildItem -Path $script:InstallDir -Recurse -File -ErrorAction SilentlyContinue |
            Where-Object {
                $filePath = $_.FullName
                $excluded = $false
                foreach ($dir in $excludeDirs) {
                    if ($filePath -like "*\$dir\*" -or $filePath -like "*/$dir/*") {
                        $excluded = $true
                        break
                    }
                }
                if (-not $excluded) {
                    foreach ($pat in $excludePatterns) {
                        if ($_.Name -like $pat) {
                            $excluded = $true
                            break
                        }
                    }
                }
                -not $excluded
            } |
            Sort-Object FullName

        $sha = [System.Security.Cryptography.SHA256]::Create()
        $allHashes = ""
        foreach ($file in $files) {
            try {
                $fileHash = Get-FileHash -Path $file.FullName -Algorithm SHA256 -ErrorAction SilentlyContinue
                if ($fileHash) {
                    $allHashes += $fileHash.Hash
                }
            }
            catch { continue }
        }

        $bytes = [System.Text.Encoding]::UTF8.GetBytes($allHashes)
        $hashBytes = $sha.ComputeHash($bytes)
        $hash = [BitConverter]::ToString($hashBytes).Replace("-", "").Substring(0, 8).ToLower()

        $hashFile = Join-Path $script:InstallDir ".build-hash"
        Set-Content -Path $hashFile -Value $hash -NoNewline
        Write-Ok "Build hash: $hash"
    }
    catch {
        Write-Warn "Failed to compute build hash: $_"
    }
}

# ──────────────────────────────────────────────────────────────────────────────
# Sync-Bot — copies the bot/ directory from source to install, excluding
# node_modules. No-op if bot/ does not exist in source.
# ──────────────────────────────────────────────────────────────────────────────
function Sync-Bot {
    [CmdletBinding()]
    param()

    $botSrc = Join-Path $script:SourceDir "bot"
    if (-not (Test-Path $botSrc)) { return }
    if (-not (Test-Path (Join-Path $botSrc "package.json"))) { return }

    $botDst = Join-Path $script:InstallDir "bot"
    if (Test-Path $botDst) { Remove-Item $botDst -Recurse -Force }

    # Copy everything except node_modules
    $items = Get-ChildItem -Path $botSrc -Recurse |
        Where-Object { $_.FullName -notmatch '[/\\]node_modules[/\\]?' }
    foreach ($item in $items) {
        $relativePath = $item.FullName.Substring($botSrc.Length)
        $destPath = Join-Path $botDst $relativePath
        if ($item.PSIsContainer) {
            New-Item -ItemType Directory -Path $destPath -Force | Out-Null
        } else {
            $destDir = Split-Path $destPath
            if (-not (Test-Path $destDir)) {
                New-Item -ItemType Directory -Path $destDir -Force | Out-Null
            }
            Copy-Item -Path $item.FullName -Destination $destPath -Force
        }
    }
}
