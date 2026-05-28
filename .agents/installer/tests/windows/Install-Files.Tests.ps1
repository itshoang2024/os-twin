# ──────────────────────────────────────────────────────────────────────────────
# Install-Files.Tests.ps1 — Tests for installer/Install-Files.ps1
# ──────────────────────────────────────────────────────────────────────────────

BeforeAll {
    . "$PSScriptRoot/TestHelper.ps1"
    Import-InstallerModule -Modules @("Lib.ps1", "Versions.ps1", "Install-Files.ps1")
    . $script:_ImportedModuleScript
}

Describe "Compute-BuildHash" {
    BeforeEach {
        $testDir = Join-Path $TestDrive "test-install"
        New-Item -ItemType Directory -Path $testDir -Force | Out-Null
        # Create a test file
        Set-Content -Path (Join-Path $testDir "test.txt") -Value "hello world"
        $script:InstallDir = $testDir
    }

    It "Should create .build-hash file" {
        Compute-BuildHash
        $hashFile = Join-Path $testDir ".build-hash"
        Test-Path $hashFile | Should -Be $true
    }

    It "Should create an 8-character hash" {
        Compute-BuildHash
        $hashFile = Join-Path $testDir ".build-hash"
        $hash = Get-Content $hashFile -Raw
        $hash.Length | Should -Be 8
    }

    It "Should produce consistent hashes" {
        Compute-BuildHash
        $hash1 = Get-Content (Join-Path $testDir ".build-hash") -Raw

        # Recompute
        Compute-BuildHash
        $hash2 = Get-Content (Join-Path $testDir ".build-hash") -Raw

        $hash1 | Should -Be $hash2
    }
}

Describe "Migrate-McpConfig" {
    BeforeEach {
        $testDir = Join-Path $TestDrive "test-mcp"
        $mcpDir = Join-Path $testDir ".agents\mcp"
        New-Item -ItemType Directory -Path $mcpDir -Force | Out-Null
        $script:InstallDir = $testDir
    }

    It "Should rename mcp-config.json to config.json when only old exists" {
        Set-Content -Path (Join-Path $mcpDir "mcp-config.json") -Value '{"test": true}'
        Migrate-McpConfig
        Test-Path (Join-Path $mcpDir "config.json") | Should -Be $true
        Test-Path (Join-Path $mcpDir "mcp-config.json") | Should -Be $false
    }

    It "Should remove old config when both exist" {
        Set-Content -Path (Join-Path $mcpDir "mcp-config.json") -Value '{"old": true}'
        Set-Content -Path (Join-Path $mcpDir "config.json") -Value '{"new": true}'
        Migrate-McpConfig
        Test-Path (Join-Path $mcpDir "mcp-config.json") | Should -Be $false
        Test-Path (Join-Path $mcpDir "config.json") | Should -Be $true
        $content = Get-Content (Join-Path $mcpDir "config.json") -Raw
        $content | Should -Match '"new"'
    }

    It "Should do nothing when only config.json exists" {
        Set-Content -Path (Join-Path $mcpDir "config.json") -Value '{"current": true}'
        { Migrate-McpConfig } | Should -Not -Throw
        Test-Path (Join-Path $mcpDir "config.json") | Should -Be $true
    }
}

Describe "Seed-McpConfig" {
    BeforeEach {
        $testDir = Join-Path $TestDrive "test-seed-$(Get-Random)"
        $scriptDir = Join-Path $testDir "source"
        $installDir = Join-Path $testDir "install"
        $mcpSrcDir = Join-Path $scriptDir "mcp"
        $mcpDstDir = Join-Path $installDir ".agents\mcp"

        New-Item -ItemType Directory -Path $mcpSrcDir -Force | Out-Null
        New-Item -ItemType Directory -Path $mcpDstDir -Force | Out-Null

        $script:ScriptDir = $scriptDir
        $script:InstallDir = $installDir
        $script:VenvDir = Join-Path $installDir ".venv"
        $script:PythonCmd = "python"
        $script:InstallerScriptsDir = Join-Path $scriptDir "installer\scripts"
    }

    It "Should seed config.json on first install" {
        Set-Content -Path (Join-Path $mcpSrcDir "config.json") -Value '{"mcpServers": {}}'
        Seed-McpConfig
        Test-Path (Join-Path $mcpDstDir "config.json") | Should -Be $true
    }

    It "Should prefer mcp-builtin.json over ignored config.json on first install" {
        Set-Content -Path (Join-Path $mcpSrcDir "config.json") -Value '{"mcp": {"stale": {"type": "local"}}}'
        Set-Content -Path (Join-Path $mcpSrcDir "mcp-builtin.json") -Value '{"mcp": {"chrome-devtools": {"type": "local", "command": ["obscura", "mcp"]}}}'

        Seed-McpConfig

        $content = Get-Content (Join-Path $mcpDstDir "config.json") -Raw
        $content | Should -Match "chrome-devtools"
        $content | Should -Not -Match '"stale"'
    }

    It "Should not overwrite existing config.json" {
        Set-Content -Path (Join-Path $mcpDstDir "config.json") -Value '{"existing": true}'
        Set-Content -Path (Join-Path $mcpSrcDir "config.json") -Value '{"new": true}'
        Seed-McpConfig
        $content = Get-Content (Join-Path $mcpDstDir "config.json") -Raw
        $content | Should -Match '"existing"'
    }
}

Describe "Load-ContributedRoles" {
    BeforeEach {
        $testDir = Join-Path $TestDrive "test-roles-$(Get-Random)"
        $installDir = Join-Path $testDir "install"
        $rolesDir = Join-Path $installDir ".agents\roles"
        $contributes = Join-Path $testDir "source\contributes\roles"
        $sourceDir = Join-Path $testDir "source"

        New-Item -ItemType Directory -Path $rolesDir -Force | Out-Null
        New-Item -ItemType Directory -Path $contributes -Force | Out-Null

        $script:InstallDir = $installDir
        $script:SourceDir = $sourceDir
        $script:ScriptDir = Join-Path $sourceDir ".agents"
    }

    It "Should load roles from contributes directory" {
        $roleDir = Join-Path $contributes "test-role"
        New-Item -ItemType Directory -Path $roleDir -Force | Out-Null
        Set-Content -Path (Join-Path $roleDir "role.json") -Value '{}'

        Load-ContributedRoles

        $targetRole = Join-Path $rolesDir "test-role"
        Test-Path $targetRole | Should -Be $true
    }

    It "Should not overwrite existing roles" {
        $roleDir = Join-Path $contributes "existing-role"
        New-Item -ItemType Directory -Path $roleDir -Force | Out-Null
        Set-Content -Path (Join-Path $roleDir "role.json") -Value '{"src": "contributes"}'

        $existingRole = Join-Path $rolesDir "existing-role"
        New-Item -ItemType Directory -Path $existingRole -Force | Out-Null
        Set-Content -Path (Join-Path $existingRole "role.json") -Value '{"src": "existing"}'

        Load-ContributedRoles

        $content = Get-Content (Join-Path $existingRole "role.json") -Raw
        $content | Should -Match '"existing"'
    }
}

Describe "MCP file sync" {
    BeforeEach {
        $testDir = Join-Path $TestDrive "test-mcp-sync-$(Get-Random)"
        $sourceDir = Join-Path $testDir "source"
        $installDir = Join-Path $testDir "install"
        $mcpSrcDir = Join-Path $sourceDir ".agents\mcp"
        $mcpDstDir = Join-Path $installDir ".agents\mcp"

        New-Item -ItemType Directory -Path $mcpSrcDir -Force | Out-Null
        New-Item -ItemType Directory -Path $mcpDstDir -Force | Out-Null

        $script:InstallDir = $installDir
        $script:SourceDir = $sourceDir
        $script:ScriptDir = Join-Path $sourceDir ".agents"
        $script:VenvDir = Join-Path $installDir ".venv"
        $script:PythonCmd = "python"
        $script:InstallerScriptsDir = Join-Path $PSScriptRoot ".."
    }

    It "Should not overwrite extensions.json (runtime state) when calling Seed-McpConfig" {
        $extensionsDst = Join-Path $mcpDstDir "extensions.json"
        Set-Content -Path $extensionsDst -Value '{"installed": ["my-extension"]}'

        $extensionsSrc = Join-Path $mcpSrcDir "extensions.json"
        Set-Content -Path $extensionsSrc -Value '{"installed": ["different-extension"]}'

        Set-Content -Path (Join-Path $mcpSrcDir "server.py") -Value "# server"
        Set-Content -Path (Join-Path $mcpSrcDir "mcp-builtin.json") -Value '{"builtin": true}'
        Set-Content -Path (Join-Path $mcpSrcDir "mcp-catalog.json") -Value '{"catalog": true}'
        Set-Content -Path (Join-Path $mcpDstDir "config.json") -Value '{"mcpServers": {}}'
        Set-Content -Path (Join-Path $mcpDstDir "obscura-browser-server.py") -Value "# old adapter"
        Set-Content -Path (Join-Path $mcpDstDir "test_obscura_browser.py") -Value "# old test"

        Seed-McpConfig

        $content = Get-Content $extensionsDst -Raw
        $content | Should -Match '"my-extension"' -Because "extensions.json is runtime state and should not be overwritten by Seed-McpConfig"
        Test-Path (Join-Path $mcpDstDir "mcp-builtin.json") | Should -Be $true -Because "mcp-builtin.json should be synced by Seed-McpConfig"
        Test-Path (Join-Path $mcpDstDir "mcp-catalog.json") | Should -Be $true -Because "mcp-catalog.json should be synced by Seed-McpConfig"
        Test-Path (Join-Path $mcpDstDir "server.py") | Should -Be $true -Because ".py files should be synced by Seed-McpConfig"
        Test-Path (Join-Path $mcpDstDir "obscura-browser-server.py") | Should -Be $false -Because "legacy browser adapter should be removed"
        Test-Path (Join-Path $mcpDstDir "test_obscura_browser.py") | Should -Be $false -Because "legacy adapter tests should be removed"
    }
}

Describe "Sync-Bot" {
    BeforeEach {
        $testDir = Join-Path $TestDrive "test-bot-$(Get-Random)"
        $installDir = Join-Path $testDir "install"
        $sourceDir = Join-Path $testDir "source"
        $botSrc = Join-Path $sourceDir "bot"
        $botDst = Join-Path $installDir "bot"

        New-Item -ItemType Directory -Path $botSrc -Force | Out-Null
        New-Item -ItemType Directory -Path $installDir -Force | Out-Null

        $script:InstallDir = $installDir
        $script:SourceDir = $sourceDir
        $script:ScriptDir = Join-Path $sourceDir ".agents"
    }

    It "Should sync bot directory when package.json exists" {
        Set-Content -Path (Join-Path $botSrc "package.json") -Value '{"name": "test-bot"}'
        New-Item -ItemType Directory -Path (Join-Path $botSrc "src") -Force | Out-Null
        Set-Content -Path (Join-Path $botSrc "src" "index.ts") -Value "console.log('hello')"

        Sync-Bot

        Test-Path $botDst | Should -Be $true
        Test-Path (Join-Path $botDst "package.json") | Should -Be $true
    }

    It "Should exclude node_modules from sync" {
        Set-Content -Path (Join-Path $botSrc "package.json") -Value '{}'
        New-Item -ItemType Directory -Path (Join-Path $botSrc "node_modules" "some-package") -Force | Out-Null
        Set-Content -Path (Join-Path $botSrc "node_modules" "some-package" "index.js") -Value "module.exports = {}"

        Sync-Bot

        Test-Path (Join-Path $botDst "node_modules") | Should -Be $false
    }

    It "Should not fail when bot source not found" {
        { Sync-Bot } | Should -Not -Throw
    }
}
