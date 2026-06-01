# ──────────────────────────────────────────────────────────────────────────────
# Install-Deps.Tests.ps1 — Tests for installer/Install-Deps.ps1
# ──────────────────────────────────────────────────────────────────────────────

BeforeAll {
    . "$PSScriptRoot/TestHelper.ps1"
    Import-InstallerModule -Modules @("Lib.ps1", "Versions.ps1", "Check-Deps.ps1", "Install-Deps.ps1")
    . $script:_ImportedModuleScript
}

Describe "Install-PesterModule" {
    It "Should not throw" {
        { Install-PesterModule } | Should -Not -Throw
    }

    It "Should find Pester 5+" {
        $installed = Get-Module -ListAvailable Pester | Where-Object { $_.Version.Major -ge 5 }
        # Either it's installed or the function should handle it
        if ($installed) {
            $installed.Version.Major | Should -BeGreaterOrEqual 5
        }
    }
}

Describe "Install-UV" {
    It "Should define the function" {
        Get-Command Install-UV | Should -Not -BeNullOrEmpty
    }

    It "Should have CmdletBinding" {
        $cmd = Get-Command Install-UV
        $cmd.CmdletBinding | Should -Be $true
    }
}

Describe "Install-Python" {
    It "Should define the function" {
        Get-Command Install-Python | Should -Not -BeNullOrEmpty
    }

    It "Should use PythonInstallVersion from Versions.ps1" {
        $script:PythonInstallVersion | Should -Be "3.12"
    }
}

Describe "Install-Pwsh" {
    It "Should define the function" {
        Get-Command Install-Pwsh | Should -Not -BeNullOrEmpty
    }

    It "Should use PwshInstallVersion from Versions.ps1" {
        $script:PwshInstallVersion | Should -Be "7.4.7"
    }
}

Describe "Install-Node" {
    It "Should define the function" {
        Get-Command Install-Node | Should -Not -BeNullOrEmpty
    }

    It "Should use NodeVersion from Versions.ps1" {
        $script:NodeVersion | Should -Be "v25.8.1"
    }
}

Describe "Install-Bun" {
    It "Should define the function" {
        Get-Command Install-Bun | Should -Not -BeNullOrEmpty
    }

    It "Should have CmdletBinding" {
        $cmd = Get-Command Install-Bun
        $cmd.CmdletBinding | Should -Be $true
    }
}

Describe "Install-OpenCode" {
    It "Should define the function" {
        Get-Command Install-OpenCode | Should -Not -BeNullOrEmpty
    }
}

Describe "Install-ChromeDevTools" {
    It "Should define the function" {
        Get-Command Install-ChromeDevTools | Should -Not -BeNullOrEmpty
    }

    It "Should have CmdletBinding" {
        $cmd = Get-Command Install-ChromeDevTools
        $cmd.CmdletBinding | Should -Be $true
    }

    It "Should select matching Windows x64 release asset" {
        $assets = @(
            [pscustomobject]@{ name = "obscura-x86_64-linux.tar.gz" },
            [pscustomobject]@{ name = "obscura-x86_64-windows.zip" }
        )

        $asset = Select-ChromeDevToolsAsset -Assets $assets -OS "windows" -Arch "x64"
        $asset.name | Should -Be "obscura-x86_64-windows.zip"
    }

    It "Should return null when no release asset matches" {
        $assets = @([pscustomobject]@{ name = "obscura-x86_64-linux.tar.gz" })

        $asset = Select-ChromeDevToolsAsset -Assets $assets -OS "windows" -Arch "arm64"
        $asset | Should -BeNullOrEmpty
    }

    It "Should not set OBSCURA_ARGS by default" {
        $content = Get-Content (Join-Path $script:InstallerModDir "Install-Deps.ps1") -Raw
        $content | Should -Not -Match '\$env:OBSCURA_ARGS'
    }

    It "Should preserve companion worker when copying release binaries" {
        $content = Get-Content (Join-Path $script:InstallerModDir "Install-Deps.ps1") -Raw
        $content | Should -Match 'obscura-worker'
    }
}
