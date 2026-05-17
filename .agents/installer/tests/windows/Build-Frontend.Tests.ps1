# ──────────────────────────────────────────────────────────────────────────────
# Build-Frontend.Tests.ps1 — Tests for installer/Build-Frontend.ps1
# ──────────────────────────────────────────────────────────────────────────────

BeforeAll {
    . "$PSScriptRoot/TestHelper.ps1"
    Import-InstallerModule -Modules @("Lib.ps1", "Build-Frontend.ps1")
    . $script:_ImportedModuleScript
}

Describe "Build-Frontend" {
    BeforeEach {
        $testDir = Join-Path $TestDrive "test-fe-$(Get-Random)"
        $sourceDir = Join-Path $testDir "source"
        New-Item -ItemType Directory -Path $sourceDir -Force | Out-Null
        $script:SourceDir = $sourceDir
        $script:ScriptDir = Join-Path $sourceDir ".agents"
    }

    It "Should warn when frontend directory not found" {
        # No package.json exists, so should warn and return
        { Build-Frontend -SubDir "nonexistent\dir" -Label "Test FE" } | Should -Not -Throw
    }

    It "Should throw when required frontend directory not found" {
        { Build-Frontend -SubDir "nonexistent\dir" -Label "Required FE" -Required } | Should -Throw
    }

    It "Should warn when no package manager found" {
        # Create a fake frontend dir with package.json
        $feDir = Join-Path $sourceDir "dashboard\fe"
        New-Item -ItemType Directory -Path $feDir -Force | Out-Null
        Set-Content -Path (Join-Path $feDir "package.json") -Value '{"name": "test"}'

        # Mock: no package managers available
        Mock Get-Command { $null } -ParameterFilter {
            $Name -in @("bun", "pnpm", "npm", "yarn")
        }

        { Build-Frontend -SubDir "dashboard\fe" -Label "Test FE" } | Should -Not -Throw
    }

    It "Should throw when no package manager found for required frontend" {
        $feDir = Join-Path $sourceDir "dashboard\fe"
        New-Item -ItemType Directory -Path $feDir -Force | Out-Null
        Set-Content -Path (Join-Path $feDir "package.json") -Value '{"name": "test"}'

        Mock Get-Command { $null } -ParameterFilter {
            $Name -in @("bun", "pnpm", "npm", "yarn")
        }

        { Build-Frontend -SubDir "dashboard\fe" -Label "Test FE" -Required } | Should -Throw
    }

    It "Should use default label when not specified" {
        { Build-Frontend -SubDir "test\dir" } | Should -Not -Throw
    }
}
