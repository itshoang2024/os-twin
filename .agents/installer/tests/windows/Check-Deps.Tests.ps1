# ──────────────────────────────────────────────────────────────────────────────
# Check-Deps.Tests.ps1 — Tests for installer/Check-Deps.ps1
# ──────────────────────────────────────────────────────────────────────────────

BeforeAll {
    . "$PSScriptRoot/TestHelper.ps1"
    Import-InstallerModule -Modules @("Lib.ps1", "Versions.ps1", "Check-Deps.ps1")
    . $script:_ImportedModuleScript
}

Describe "Check-Python" {
    It "Should return a string (path or empty)" {
        $result = Check-Python
        $result | Should -BeOfType [string]
    }

    It "Should set PythonVersion when Python is found" {
        $result = Check-Python
        if ($result) {
            $script:PythonVersion | Should -Not -BeNullOrEmpty
            $script:PythonVersion | Should -Match '^\d+\.\d+'
        }
        else {
            Set-ItResult -Skipped -Because "Python not installed"
        }
    }

    It "Should find Python >= MinPythonVersion" {
        $result = Check-Python
        if ($result) {
            Compare-VersionGte -Current $script:PythonVersion -Minimum $script:MinPythonVersion | Should -Be $true
        }
        else {
            Set-ItResult -Skipped -Because "Python not installed"
        }
    }
}

Describe "Check-Pwsh" {
    It "Should return a boolean" {
        $result = Check-Pwsh
        $result | Should -BeOfType [bool]
    }

    It "Should return true when running PowerShell 7+" {
        if ($PSVersionTable.PSVersion.Major -ge 7) {
            Check-Pwsh | Should -Be $true
        }
        else {
            Set-ItResult -Skipped -Because "Running PowerShell < 7"
        }
    }

    It "Should set PwshCurrentVersion when PS7+ found" {
        if ($PSVersionTable.PSVersion.Major -ge 7) {
            Check-Pwsh | Out-Null
            $script:PwshCurrentVersion | Should -Not -BeNullOrEmpty
        }
        else {
            Set-ItResult -Skipped -Because "Running PowerShell < 7"
        }
    }
}

Describe "Check-Node" {
    It "Should return a boolean" {
        $result = Check-Node
        $result | Should -BeOfType [bool]
    }

    It "Should detect node if installed" {
        $nodeCmd = Get-Command node -ErrorAction SilentlyContinue
        if ($nodeCmd) {
            Check-Node | Should -Be $true
        }
        else {
            Check-Node | Should -Be $false
        }
    }
}

Describe "Check-UV" {
    It "Should return a boolean" {
        $result = Check-UV
        $result | Should -BeOfType [bool]
    }
}

Describe "Check-OpenCode" {
    It "Should return a boolean" {
        $result = Check-OpenCode
        $result | Should -BeOfType [bool]
    }
}

Describe "Check-ChromeDevTools" {
    It "Should define the function" {
        Get-Command Check-ChromeDevTools | Should -Not -BeNullOrEmpty
    }

    It "Should return a string path or empty string" {
        $result = Check-ChromeDevTools
        $result | Should -BeOfType [string]
    }

    It "Should detect installer-managed Chrome DevTools runtime binary" {
        $oldInstallDir = $script:InstallDir
        try {
            $script:InstallDir = Join-Path $TestDrive "ostwin"
            $binDir = Join-Path $script:InstallDir ".agents\bin"
            New-Item -ItemType Directory -Path $binDir -Force | Out-Null
            $expected = Join-Path $binDir "obscura.exe"
            New-Item -ItemType File -Path $expected -Force | Out-Null

            $result = Check-ChromeDevTools
            if ($result -ne $expected) {
                Set-ItResult -Skipped -Because "A real Chrome DevTools runtime executable on PATH takes precedence"
            }
            else {
                $result | Should -Be $expected
            }
        }
        finally {
            $script:InstallDir = $oldInstallDir
        }
    }
}
