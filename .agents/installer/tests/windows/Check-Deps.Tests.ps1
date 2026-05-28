# ──────────────────────────────────────────────────────────────────────────────
# Check-Deps.Tests.ps1 — Tests for installer/Check-Deps.ps1
# ──────────────────────────────────────────────────────────────────────────────

BeforeAll {
    . "$PSScriptRoot/TestHelper.ps1"
    Import-InstallerModule -Modules @("Lib.ps1", "Versions.ps1", "Check-Deps.ps1")
    . $script:_ImportedModuleScript

    function New-FakeObscuraCommand {
        param(
            [Parameter(Mandatory=$true)]
            [string]$Directory,
            [bool]$SupportsMcp = $true
        )

        New-Item -ItemType Directory -Path $Directory -Force | Out-Null
        if ($IsWindows) {
            $path = Join-Path $Directory "obscura.cmd"
            $exitCode = if ($SupportsMcp) { 0 } else { 2 }
            Set-Content -Path $path -Value @"
@echo off
if "%1"=="mcp" if "%2"=="--help" exit /b $exitCode
exit /b 1
"@
            return $path
        }

        $path = Join-Path $Directory "obscura"
        $exitCode = if ($SupportsMcp) { 0 } else { 2 }
        Set-Content -Path $path -Value @"
#!/bin/sh
if [ "`$1" = "mcp" ] && [ "`$2" = "--help" ]; then
  exit $exitCode
fi
exit 1
"@
        & chmod +x $path
        return $path
    }

    function New-FakeObscuraExe {
        param(
            [Parameter(Mandatory=$true)]
            [string]$Path,
            [bool]$SupportsMcp = $true
        )

        New-Item -ItemType Directory -Path (Split-Path -Parent $Path) -Force | Out-Null
        $exitCode = if ($SupportsMcp) { 0 } else { 2 }
        Set-Content -Path $Path -Value @"
#!/bin/sh
if [ "`$1" = "mcp" ] && [ "`$2" = "--help" ]; then
  exit $exitCode
fi
exit 1
"@
        if (-not $IsWindows) {
            & chmod +x $Path
        }
    }
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
        if ($IsWindows) {
            Set-ItResult -Skipped -Because "Unit test uses a script-backed fake executable; Windows install smoke covers real obscura.exe"
            return
        }

        $oldInstallDir = $script:InstallDir
        $oldPath = $env:PATH
        try {
            $script:InstallDir = Join-Path $TestDrive "ostwin"
            $binDir = Join-Path $script:InstallDir ".agents\bin"
            $expected = Join-Path $binDir "obscura.exe"
            New-FakeObscuraExe -Path $expected -SupportsMcp $true
            $env:PATH = "/not/a/real/path"

            $result = Check-ChromeDevTools
            $result | Should -Be $expected
        }
        finally {
            $script:InstallDir = $oldInstallDir
            $env:PATH = $oldPath
        }
    }

    It "Should detect PATH Obscura only when native MCP is supported" {
        $oldInstallDir = $script:InstallDir
        $oldPath = $env:PATH
        try {
            $script:InstallDir = Join-Path $TestDrive "missing-install"
            $fakeBin = Join-Path $TestDrive "path-obscura"
            $expected = New-FakeObscuraCommand -Directory $fakeBin -SupportsMcp $true
            $env:PATH = $fakeBin

            Check-ChromeDevTools | Should -Be $expected
        }
        finally {
            $script:InstallDir = $oldInstallDir
            $env:PATH = $oldPath
        }
    }

    It "Should reject Obscura without native MCP support" {
        $oldInstallDir = $script:InstallDir
        $oldPath = $env:PATH
        try {
            $script:InstallDir = Join-Path $TestDrive "missing-install"
            $fakeBin = Join-Path $TestDrive "stale-obscura"
            New-FakeObscuraCommand -Directory $fakeBin -SupportsMcp $false | Out-Null
            $env:PATH = $fakeBin

            Check-ChromeDevTools | Should -Be ""
        }
        finally {
            $script:InstallDir = $oldInstallDir
            $env:PATH = $oldPath
        }
    }

    It "Should reject stale managed Obscura even when PATH has valid Obscura" {
        if ($IsWindows) {
            Set-ItResult -Skipped -Because "Unit test uses script-backed fake executables; Windows install smoke covers real obscura.exe"
            return
        }

        $oldInstallDir = $script:InstallDir
        $oldPath = $env:PATH
        try {
            $script:InstallDir = Join-Path $TestDrive "ostwin-stale-managed"
            $managedPath = Join-Path $script:InstallDir ".agents\bin\obscura.exe"
            New-FakeObscuraExe -Path $managedPath -SupportsMcp $false

            $fakeBin = Join-Path $TestDrive "valid-path-obscura"
            New-FakeObscuraCommand -Directory $fakeBin -SupportsMcp $true | Out-Null
            $env:PATH = $fakeBin

            Check-ChromeDevTools | Should -Be ""
        }
        finally {
            $script:InstallDir = $oldInstallDir
            $env:PATH = $oldPath
        }
    }
}
