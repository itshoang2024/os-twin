# ──────────────────────────────────────────────────────────────────────────────
# Install.Integration.Tests.ps1 — Integration tests for install.ps1
# ──────────────────────────────────────────────────────────────────────────────

Describe "install.ps1 module loading" {
    BeforeAll {
        . "$PSScriptRoot/TestHelper.ps1"
        $installerDir = $script:InstallerModDir
    }

    It "All module files should exist" {
        $modules = @(
            "Lib.ps1", "Versions.ps1", "Detect-OS.ps1", "Check-Deps.ps1",
            "Install-Deps.ps1", "Install-Files.ps1", "Setup-Venv.ps1",
            "Setup-Env.ps1", "Patch-MCP.ps1", "Build-Frontend.ps1",
            "Setup-Path.ps1", "Setup-OpenCode.ps1", "Sync-Agents.ps1",
            "Start-Dashboard.ps1", "Start-Channels.ps1", "Verify.ps1",
            "Orchestrate-Deps.ps1"
        )

        foreach ($mod in $modules) {
            $modPath = Join-Path $installerDir $mod
            Test-Path $modPath | Should -Be $true -Because "$mod should exist"
        }
    }

    It "All module files should parse without errors" {
        $modules = Get-ChildItem -Path $installerDir -Filter "*.ps1"
        foreach ($mod in $modules) {
            $errors = $null
            [System.Management.Automation.Language.Parser]::ParseFile(
                $mod.FullName,
                [ref]$null,
                [ref]$errors
            )
            $errors.Count | Should -Be 0 -Because "$($mod.Name) should parse cleanly"
        }
    }

    It "install.ps1 should exist and parse" {
        $installPs1 = $script:InstallPs1
        Test-Path $installPs1 | Should -Be $true

        $errors = $null
        [System.Management.Automation.Language.Parser]::ParseFile(
            $installPs1,
            [ref]$null,
            [ref]$errors
        )
        $errors.Count | Should -Be 0 -Because "install.ps1 should parse cleanly"
    }

    It "install.ps1 should have param block with correct parameters" {
        $installPs1 = $script:InstallPs1
        $ast = [System.Management.Automation.Language.Parser]::ParseFile(
            $installPs1,
            [ref]$null,
            [ref]$null
        )
        $params = $ast.ParamBlock.Parameters | ForEach-Object { $_.Name.VariablePath.UserPath }

        $params | Should -Contain "Yes"
        $params | Should -Contain "Dir"
        $params | Should -Contain "SourceDir"
        $params | Should -Contain "Port"
        $params | Should -Contain "DashboardOnly"
        $params | Should -Contain "Channel"
        $params | Should -Contain "SkipOptional"
        $params | Should -Contain "Help"
    }
}

Describe "Module function exports" {
    BeforeAll {
        . "$PSScriptRoot/TestHelper.ps1"
        Import-InstallerModule -Modules @(
            "Lib.ps1", "Versions.ps1", "Detect-OS.ps1", "Check-Deps.ps1",
            "Install-Deps.ps1", "Install-Files.ps1", "Setup-Venv.ps1",
            "Setup-Env.ps1", "Patch-MCP.ps1", "Build-Frontend.ps1",
            "Setup-Path.ps1", "Setup-OpenCode.ps1", "Sync-Agents.ps1",
            "Start-Dashboard.ps1", "Start-Channels.ps1", "Verify.ps1",
            "Orchestrate-Deps.ps1"
        )
        . $script:_ImportedModuleScript
    }

    It "Should export Write-Header" { Get-Command Write-Header | Should -Not -BeNullOrEmpty }
    It "Should export Write-Ok" { Get-Command Write-Ok | Should -Not -BeNullOrEmpty }
    It "Should export Write-Warn" { Get-Command Write-Warn | Should -Not -BeNullOrEmpty }
    It "Should export Write-Fail" { Get-Command Write-Fail | Should -Not -BeNullOrEmpty }
    It "Should export Write-Info" { Get-Command Write-Info | Should -Not -BeNullOrEmpty }
    It "Should export Write-Step" { Get-Command Write-Step | Should -Not -BeNullOrEmpty }
    It "Should export Ask-User" { Get-Command Ask-User | Should -Not -BeNullOrEmpty }
    It "Should export Compare-VersionGte" { Get-Command Compare-VersionGte | Should -Not -BeNullOrEmpty }
    It "Should export Detect-WindowsOS" { Get-Command Detect-WindowsOS | Should -Not -BeNullOrEmpty }
    It "Should export Check-Python" { Get-Command Check-Python | Should -Not -BeNullOrEmpty }
    It "Should export Check-Pwsh" { Get-Command Check-Pwsh | Should -Not -BeNullOrEmpty }
    It "Should export Check-Node" { Get-Command Check-Node | Should -Not -BeNullOrEmpty }
    It "Should export Check-UV" { Get-Command Check-UV | Should -Not -BeNullOrEmpty }
    It "Should export Check-OpenCode" { Get-Command Check-OpenCode | Should -Not -BeNullOrEmpty }
    It "Should export Check-ChromeDevTools" { Get-Command Check-ChromeDevTools | Should -Not -BeNullOrEmpty }
    It "Should export Install-UV" { Get-Command Install-UV | Should -Not -BeNullOrEmpty }
    It "Should export Install-Python" { Get-Command Install-Python | Should -Not -BeNullOrEmpty }
    It "Should export Install-Pwsh" { Get-Command Install-Pwsh | Should -Not -BeNullOrEmpty }
    It "Should export Install-Node" { Get-Command Install-Node | Should -Not -BeNullOrEmpty }
    It "Should export Install-OpenCode" { Get-Command Install-OpenCode | Should -Not -BeNullOrEmpty }
    It "Should export Install-ChromeDevTools" { Get-Command Install-ChromeDevTools | Should -Not -BeNullOrEmpty }
    It "Should export Install-PesterModule" { Get-Command Install-PesterModule | Should -Not -BeNullOrEmpty }
    It "Should export Install-Files" { Get-Command Install-Files | Should -Not -BeNullOrEmpty }
    It "Should export Compute-BuildHash" { Get-Command Compute-BuildHash | Should -Not -BeNullOrEmpty }
    It "Should export Setup-Venv" { Get-Command Setup-Venv | Should -Not -BeNullOrEmpty }
    It "Should export Setup-Env" { Get-Command Setup-Env | Should -Not -BeNullOrEmpty }
    It "Should export Patch-McpConfig" { Get-Command Patch-McpConfig | Should -Not -BeNullOrEmpty }
    It "Should export Build-Frontend" { Get-Command Build-Frontend | Should -Not -BeNullOrEmpty }
    It "Should export Setup-Path" { Get-Command Setup-Path | Should -Not -BeNullOrEmpty }
    It "Should export Setup-OpenCodePermissions" { Get-Command Setup-OpenCodePermissions | Should -Not -BeNullOrEmpty }
    It "Should export Sync-OpenCodeAgents" { Get-Command Sync-OpenCodeAgents | Should -Not -BeNullOrEmpty }
    It "Should export Start-Dashboard" { Get-Command Start-Dashboard | Should -Not -BeNullOrEmpty }
    It "Should export Publish-Skills" { Get-Command Publish-Skills | Should -Not -BeNullOrEmpty }
    It "Should export Install-Channels" { Get-Command Install-Channels | Should -Not -BeNullOrEmpty }
    It "Should export Start-Channels" { Get-Command Start-Channels | Should -Not -BeNullOrEmpty }
    It "Should export Verify-Components" { Get-Command Verify-Components | Should -Not -BeNullOrEmpty }
    It "Should export Print-CompletionBanner" { Get-Command Print-CompletionBanner | Should -Not -BeNullOrEmpty }
    It "Should export Invoke-DependencyOrchestration" { Get-Command Invoke-DependencyOrchestration | Should -Not -BeNullOrEmpty }
}

Describe "Bash module parity" {
    It "Should have matching PowerShell module for each bash module" {
        $bashModules = @(
            "lib.sh", "versions.conf", "detect-os.sh", "check-deps.sh",
            "install-deps.sh", "install-files.sh", "setup-venv.sh",
            "setup-env.sh", "patch-mcp.sh", "build-frontend.sh",
            "setup-path.sh", "setup-opencode.sh", "sync-agents.sh",
            "start-dashboard.sh", "start-channels.sh", "verify.sh",
            "_orchestrate-deps.sh"
        )

        $ps1Modules = @(
            "Lib.ps1", "Versions.ps1", "Detect-OS.ps1", "Check-Deps.ps1",
            "Install-Deps.ps1", "Install-Files.ps1", "Setup-Venv.ps1",
            "Setup-Env.ps1", "Patch-MCP.ps1", "Build-Frontend.ps1",
            "Setup-Path.ps1", "Setup-OpenCode.ps1", "Sync-Agents.ps1",
            "Start-Dashboard.ps1", "Start-Channels.ps1", "Verify.ps1",
            "Orchestrate-Deps.ps1"
        )

        $bashModules.Count | Should -Be $ps1Modules.Count -Because "PS1 module count should match bash module count"

        foreach ($ps1 in $ps1Modules) {
            Test-Path (Join-Path $script:InstallerModDir $ps1) | Should -Be $true -Because "$ps1 should exist"
        }
    }
}

Describe "CLI flag parity" {
    It "install.ps1 parameters should mirror install.sh flags" {
        $installPs1 = $script:InstallPs1
        $ast = [System.Management.Automation.Language.Parser]::ParseFile(
            $installPs1,
            [ref]$null,
            [ref]$null
        )
        $params = $ast.ParamBlock.Parameters | ForEach-Object { $_.Name.VariablePath.UserPath }

        # Bash equivalents: --yes -> -Yes, --dir -> -Dir, --source-dir -> -SourceDir,
        # --port -> -Port, --dashboard-only -> -DashboardOnly, --channel -> -Channel,
        # --skip-optional -> -SkipOptional, --help -> -Help
        $params | Should -Contain "Yes"
        $params | Should -Contain "Dir"
        $params | Should -Contain "SourceDir"
        $params | Should -Contain "Port"
        $params | Should -Contain "DashboardOnly"
        $params | Should -Contain "Channel"
        $params | Should -Contain "SkipOptional"
        $params | Should -Contain "Help"
    }
}

Describe "No WSL/Cygwin/Git Bash dependencies" {
    It "Should not reference bash in any module" {
        $ps1Files = Get-ChildItem -Path $script:InstallerModDir -Filter "*.ps1"

        foreach ($file in $ps1Files) {
            $content = Get-Content $file.FullName -Raw
            # Allow references in comments and the sync-skills fallback
            $codeLines = Get-Content $file.FullName | Where-Object {
                $_ -notmatch '^\s*#' -and $_ -notmatch 'sync-skills' -and $_ -match '\S'
            }
            $codeContent = $codeLines -join "`n"

            $codeContent | Should -Not -Match '\bwsl\b' -Because "$($file.Name) should not use WSL"
            $codeContent | Should -Not -Match '\bcygwin\b' -Because "$($file.Name) should not use Cygwin"
            $codeContent | Should -Not -Match '\bgit\s+bash\b' -Because "$($file.Name) should not use Git Bash"
        }
    }

    It "Should not use rsync in any module" {
        $ps1Files = Get-ChildItem -Path $script:InstallerModDir -Filter "*.ps1"

        foreach ($file in $ps1Files) {
            $content = Get-Content $file.FullName -Raw
            $content | Should -Not -Match '\brsync\b' -Because "$($file.Name) should use robocopy/Copy-Item, not rsync"
        }
    }

    It "Should not use sed in any module" {
        $ps1Files = Get-ChildItem -Path $script:InstallerModDir -Filter "*.ps1"

        foreach ($file in $ps1Files) {
            $codeLines = Get-Content $file.FullName | Where-Object { $_ -notmatch '^\s*#' }
            $codeContent = $codeLines -join "`n"
            $codeContent | Should -Not -Match '\bsed\b' -Because "$($file.Name) should use -replace, not sed"
        }
    }
}

Describe "Start-Dashboard.ps1 regression tests" {
    BeforeAll {
        . "$PSScriptRoot/TestHelper.ps1"
        $startDashboard = Join-Path $script:InstallerModDir "Start-Dashboard.ps1"
        $script:StartDashboardContent = Get-Content $startDashboard -Raw
    }

    It "Health check should only accept status codes 200, 401, 403" {
        # Regression: Previously accepted any status < 500, which could mask 500 errors
        $script:StartDashboardContent | Should -Match '\$statusCode\s+-in\s+@\(200,\s*401,\s*403\)' -Because "Health check should only accept expected dashboard codes"
    }

    It "Should validate PID before killing stale dashboard process" {
        # Regression: Previously killed any PID in file without validation
        $script:StartDashboardContent | Should -Match 'Get-CimInstance.*Win32_Process|Get-NetTCPConnection.*DashboardPort' -Because "Should validate PID is actually dashboard before taskkill"
    }

    It "Should require python AND uvicorn/api:app in PID validation (tight match)" {
        # Regression: Previously matched loose 'dashboard' keyword, risking false positives
        # Must have BOTH: $cmdLine -match "python" AND ($cmdLine -match "uvicorn" -or $cmdLine -match "api:app")
        $hasPythonCheck = $script:StartDashboardContent -match '\$cmdLine\s+-match\s+"python"'
        $hasUvicornOrApiCheck = $script:StartDashboardContent -match '\$cmdLine\s+-match\s+"uvicorn".*-or.*\$cmdLine\s+-match\s+"api:app"'
        $hasAndBetween = $script:StartDashboardContent -match '-and\s+\('
        $hasPythonCheck -and $hasUvicornOrApiCheck -and $hasAndBetween | Should -Be $true -Because "PID validation must be tight: python AND (uvicorn OR api:app)"
    }

    It "Should not use -Encoding ASCII for .cmd launcher files" {
        # Regression: -Encoding ASCII breaks paths with non-ASCII characters
        $script:StartDashboardContent | Should -Not -Match 'Set-Content.*-Encoding\s+ASCII' -Because "Should use UTF-8 without BOM or [System.IO.File]::WriteAllText for .cmd files"
    }

    It "Should use UTF-8 without BOM for any .cmd file creation" {
        $script:StartDashboardContent | Should -Match '\[System\.IO\.File\]::WriteAllText.*UTF8Encoding' -Because ".cmd files should use UTF-8 without BOM for path safety"
    }

    It "Should use .cmd wrapper for log redirection (not redirected streams owned by installer)" {
        # Regression: Using RedirectStandardOutput/RedirectStandardError ties child's stdio to installer's lifetime
        # The .cmd wrapper approach lets the child process own its own log pipes
        $script:StartDashboardContent | Should -Match 'Start-Process.*cmd\.exe' -Because "Should launch via cmd.exe wrapper so child owns its logs"
        $script:StartDashboardContent | Should -Not -Match 'RedirectStandardOutput\s*=\s*\$true' -Because "Redirected streams tie child to installer lifetime"
    }
}

Describe "Start-Channels.ps1 regression tests" {
    BeforeAll {
        . "$PSScriptRoot/TestHelper.ps1"
        $startChannels = Join-Path $script:InstallerModDir "Start-Channels.ps1"
        $script:StartChannelsContent = Get-Content $startChannels -Raw
    }

    It "Should not use -Encoding ASCII for .cmd launcher files" {
        # Regression: -Encoding ASCII breaks paths with non-ASCII characters
        $script:StartChannelsContent | Should -Not -Match 'Set-Content.*-Encoding\s+ASCII' -Because "Should use UTF-8 without BOM for .cmd files"
    }

    It "Should use UTF-8 without BOM for .cmd file creation" {
        $script:StartChannelsContent | Should -Match '\[System\.IO\.File\]::WriteAllText.*UTF8Encoding' -Because ".cmd files should use UTF-8 without BOM for path safety"
    }

    It "Should start channels through Bun instead of npm/pnpm/npx" {
        $script:StartChannelsContent | Should -Match 'bun.*run start|run start' -Because "Channel startup should use Bun"
        $script:StartChannelsContent | Should -Not -Match 'pnpm install|npm start|npx tsx' -Because "Channel flow should not depend on pnpm/npm/npx wrappers"
    }
}

Describe "Setup-Venv.ps1 regression tests" {
    BeforeAll {
        . "$PSScriptRoot/TestHelper.ps1"
        $setupVenv = Join-Path $script:InstallerModDir "Setup-Venv.ps1"
        $script:SetupVenvContent = Get-Content $setupVenv -Raw
    }

    It "should not use -Encoding ASCII for .cmd launcher files" {
        # Regression: -Encoding ASCII breaks paths with non-ASCII characters
        $script:SetupVenvContent | Should -Not -Match 'Set-Content.*-Encoding\s+ASCII' -Because "Should use UTF-8 without BOM for .cmd files"
    }

    It "should use UTF-8 without BOM for .cmd file creation" {
        $script:SetupVenvContent | Should -Match '\[System\.IO\.File\]::WriteAllText.*UTF8Encoding' -Because ".cmd files should use UTF-8 without BOM for path safety"
    }

    It "should use uv sync for dashboard deps (Phase 1)" {
        # Regression: Previously used 'uv pip install -r requirements.txt' which bypassed
        # pyproject.toml resolver constraints (requests>=2.31.0 pin for llama-index-core)
        $script:SetupVenvContent | Should -Match 'uv sync' -Because "Dashboard deps should use uv sync with pyproject.toml"
    }

    It "should NOT include dashboard/requirements.txt in Phase 2 collection" {
        # Regression: Old code collected dashboard/requirements.txt alongside mcp/memory reqs,
        # causing version conflicts because requirements.txt lacked the requests>=2.31.0 pin
        $script:SetupVenvContent | Should -Not -Match '\$dashReqs\s*=.*dashboard.*requirements\.txt.*\n.*\$reqPaths\s*\+=' -Because "Dashboard deps are handled in Phase 1, not Phase 2"
    }

    It "should set UV_PROJECT_ENVIRONMENT for shared venv" {
        $script:SetupVenvContent | Should -Match 'UV_PROJECT_ENVIRONMENT' -Because "uv sync must target the shared venv, not create a new one in dashboard/"
    }
}
