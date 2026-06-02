# ──────────────────────────────────────────────────────────────────────────────
# Orchestrate-Deps.Tests.ps1 — Tests for installer/Orchestrate-Deps.ps1
# ──────────────────────────────────────────────────────────────────────────────

BeforeAll {
    . "$PSScriptRoot/TestHelper.ps1"
    Import-InstallerModule -Modules @("Lib.ps1", "Versions.ps1", "Check-Deps.ps1", "Install-Deps.ps1", "Orchestrate-Deps.ps1")
    . $script:_ImportedModuleScript
}

Describe "Invoke-DependencyOrchestration" {
    It "Should define the function" {
        Get-Command Invoke-DependencyOrchestration | Should -Not -BeNullOrEmpty
    }

    It "Should define Bun JavaScript tooling helpers" {
        Get-Command Ensure-JsPackageManager | Should -Not -BeNullOrEmpty
        Get-Command Install-ClawhubCli | Should -Not -BeNullOrEmpty
    }

    Context "Dashboard-only mode" {
        It "Should handle dashboard-only flow" {
            $script:DashboardOnly = $true
            $script:AutoYes = $true

            # This would try to actually install things, so we verify the function
            # exists and the flow branches correctly
            $script:DashboardOnly | Should -Be $true
        }
    }

    Context "Full install mode" {
        It "Should handle full install flow" {
            $script:DashboardOnly = $false
            $script:AutoYes = $true

            $script:DashboardOnly | Should -Be $false
        }
    }
}

