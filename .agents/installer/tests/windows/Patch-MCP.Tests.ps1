# ──────────────────────────────────────────────────────────────────────────────
# Patch-MCP.Tests.ps1 — Tests for installer/Patch-MCP.ps1
# ──────────────────────────────────────────────────────────────────────────────

BeforeAll {
    . "$PSScriptRoot/TestHelper.ps1"
    Import-InstallerModule -Modules @("Lib.ps1", "Patch-MCP.ps1")
    . $script:_ImportedModuleScript
}

Describe "Patch-McpConfig" {
    BeforeEach {
        $testDir = Join-Path $TestDrive "test-patch-$(Get-Random)"
        $mcpDir = Join-Path $testDir ".agents\mcp"
        New-Item -ItemType Directory -Path $mcpDir -Force | Out-Null
        $script:InstallDir = $testDir
        $script:VenvDir = Join-Path $testDir ".venv"
    }

    It "Should return silently when config.json doesn't exist" {
        { Patch-McpConfig } | Should -Not -Throw
    }

    It "Should add AGENT_DIR, OSTWIN_PYTHON, and PATH to .env when not present" {
        Set-Content -Path (Join-Path $mcpDir "config.json") -Value '{"mcpServers": {}}'
        $envFile = Join-Path $testDir ".env"
        Set-Content -Path $envFile -Value "SOME_KEY=value"

        # Mock the python calls since we don't have a real venv
        $script:PatchScriptsDir = Join-Path $TestDrive "fake-scripts"
        New-Item -ItemType Directory -Path $script:PatchScriptsDir -Force | Out-Null

        Patch-McpConfig 2>$null

        $content = Get-Content $envFile -Raw
        $content | Should -Match 'AGENT_DIR='
        $content | Should -Match 'OSTWIN_PYTHON='
        $content | Should -Match 'PATH='
    }

    It "Should not duplicate AGENT_DIR, OSTWIN_PYTHON, and PATH in .env" {
        Set-Content -Path (Join-Path $mcpDir "config.json") -Value '{"mcpServers": {}}'
        $venvPython = Join-Path $script:VenvDir "Scripts\python.exe"
        $envFile = Join-Path $testDir ".env"
        Set-Content -Path $envFile -Value "AGENT_DIR=$testDir`nOSTWIN_PYTHON=$venvPython`nPATH=C:\old"

        $script:PatchScriptsDir = Join-Path $TestDrive "fake-scripts"
        New-Item -ItemType Directory -Path $script:PatchScriptsDir -Force | Out-Null

        Patch-McpConfig 2>$null

        $agentDirLines = Get-Content $envFile | Where-Object { $_ -match 'AGENT_DIR=' }
        $ostwinPythonLines = Get-Content $envFile | Where-Object { $_ -match 'OSTWIN_PYTHON=' }
        $pathLines = Get-Content $envFile | Where-Object { $_ -match '^PATH=' }
        $agentDirLines.Count | Should -Be 1
        $ostwinPythonLines.Count | Should -Be 1
        $pathLines.Count | Should -Be 1
    }

    It "Should create .env when it doesn't exist" {
        Set-Content -Path (Join-Path $mcpDir "config.json") -Value '{"mcpServers": {}}'

        $script:PatchScriptsDir = Join-Path $TestDrive "fake-scripts"
        New-Item -ItemType Directory -Path $script:PatchScriptsDir -Force | Out-Null

        Patch-McpConfig 2>$null

        $envFile = Join-Path $testDir ".env"
        Test-Path $envFile | Should -Be $true
    }

    It "Should write AGENT_DIR, OSTWIN_PYTHON, and PATH in KEY=VALUE format (no export prefix)" {
        Set-Content -Path (Join-Path $mcpDir "config.json") -Value '{"mcpServers": {}}'
        $envFile = Join-Path $testDir ".env"

        $script:PatchScriptsDir = Join-Path $TestDrive "fake-scripts"
        New-Item -ItemType Directory -Path $script:PatchScriptsDir -Force | Out-Null

        Patch-McpConfig 2>$null

        $content = Get-Content $envFile -Raw
        # .env files use plain KEY=VALUE format, NOT 'export KEY=VALUE'
        # Use (?m) multiline flag since -Raw returns the entire file as one string
        $content | Should -Match '(?m)^AGENT_DIR='
        $content | Should -Match '(?m)^OSTWIN_PYTHON='
        $content | Should -Match '(?m)^PATH='
        $content | Should -Not -Match 'export AGENT_DIR='
        $content | Should -Not -Match 'export OSTWIN_PYTHON='
        $content | Should -Not -Match 'export PATH='
    }

    It "inject_env_to_mcp.py should resolve {env:*} in command arrays" {
        # Test inject_env_to_mcp.py directly
        $testConfig = @{
            mcp = @{
                testserver = @{
                    type = "local"
                    command = @("{env:OSTWIN_PYTHON}", "{env:AGENT_DIR}/mcp/test.py")
                    environment = @{}
                }
            }
        }
        $testConfigPath = Join-Path $TestDrive "test-config.json"
        $testEnvPath = Join-Path $TestDrive "test.env"
        $fakePythonPath = Join-Path $TestDrive "python.exe"
        $fakeAgentDir = Join-Path $TestDrive "ostwin"

        Set-Content -Path $testConfigPath -Value ($testConfig | ConvertTo-Json -Depth 10)
        Set-Content -Path $testEnvPath -Value "OSTWIN_PYTHON=$fakePythonPath`nAGENT_DIR=$fakeAgentDir"

        # Run inject script
        $injectScript = Join-Path $PSScriptRoot "..\..\scripts\inject_env_to_mcp.py"
        if (Test-Path $injectScript) {
            python $injectScript $testConfigPath $testEnvPath 2>$null

            $result = Get-Content $testConfigPath -Raw | ConvertFrom-Json
            $result.mcp.testserver.command[0] | Should -Be $fakePythonPath
            $result.mcp.testserver.command[1] | Should -Be "$fakeAgentDir/mcp/test.py"
        } else {
            Set-TestInconclusive -Message "inject_env_to_mcp.py not found"
        }
    }

    It "merge_mcp_to_opencode.py should use Windows venv path (Scripts/python.exe)" {
        # Test that merge script uses correct Windows path
        $mergeScript = Join-Path $PSScriptRoot "..\..\scripts\merge_mcp_to_opencode.py"
        if (-not (Test-Path $mergeScript)) {
            Set-TestInconclusive -Message "merge_mcp_to_opencode.py not found"
            return
        }

        # Check the script contains Windows path handling
        $scriptContent = Get-Content $mergeScript -Raw
        $scriptContent | Should -Match "Scripts.*python"
    }
}

Describe "mcp-builtin.json Server Configuration" {
    BeforeAll {
        $script:BuiltinConfigPath = Join-Path $PSScriptRoot "..\..\..\mcp\mcp-builtin.json"
    }

    It "Should include chrome-devtools server" {
        Test-Path $script:BuiltinConfigPath | Should -Be $true
        $config = Get-Content $script:BuiltinConfigPath -Raw | ConvertFrom-Json
        $config.mcp.PSObject.Properties.Name | Should -Contain "chrome-devtools"
    }

    It "Should NOT include deprecated browser MCP server names" {
        $config = Get-Content $script:BuiltinConfigPath -Raw | ConvertFrom-Json
        $config.mcp.PSObject.Properties.Name | Should -Not -Contain "obscura-browser"
        $config.mcp.PSObject.Properties.Name | Should -Not -Contain "chrom-devtools"
    }

    It "chrome-devtools command should use native Obscura MCP server" {
        $config = Get-Content $script:BuiltinConfigPath -Raw | ConvertFrom-Json
        $chromeDevToolsCmd = $config.mcp.'chrome-devtools'.command
        $chromeDevToolsCmd[0] | Should -Be "obscura"
        $chromeDevToolsCmd[1] | Should -Be "mcp"
    }

    It "chrome-devtools command should NOT use Python or the legacy adapter" {
        $config = Get-Content $script:BuiltinConfigPath -Raw | ConvertFrom-Json
        $chromeDevToolsCmd = $config.mcp.'chrome-devtools'.command -join " "
        $chromeDevToolsCmd | Should -Not -Match "OSTWIN_PYTHON"
        $chromeDevToolsCmd | Should -Not -Match "obscura-browser-server.py"
        $chromeDevToolsCmd | Should -Not -Match "C:\\.*python"
        $chromeDevToolsCmd | Should -Not -Match "/usr/bin/python"
        $chromeDevToolsCmd | Should -Not -Match "/usr/local/bin/python"
    }

    It "chrome-devtools environment should include PATH placeholder" {
        $config = Get-Content $script:BuiltinConfigPath -Raw | ConvertFrom-Json
        $env = $config.mcp.'chrome-devtools'.environment
        $env.PATH | Should -Be "{env:PATH}"
    }

    It "chrome-devtools should NOT set OBSCURA_ARGS by default (stealth is opt-in)" {
        $config = Get-Content $script:BuiltinConfigPath -Raw | ConvertFrom-Json
        $env = $config.mcp.'chrome-devtools'.environment
        $env.PSObject.Properties.Name | Should -Not -Contain "OBSCURA_ARGS"
    }

    It "playwright server should still be present" {
        $config = Get-Content $script:BuiltinConfigPath -Raw | ConvertFrom-Json
        $config.mcp.PSObject.Properties.Name | Should -Contain "playwright"
    }
}
