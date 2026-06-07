#Requires -Version 7.0

Describe "Config resolution" {
    BeforeAll {
        $script:agentsDir = (Resolve-Path (Join-Path $PSScriptRoot "../../..")).Path
        $script:configModule = Join-Path $script:agentsDir "lib" "Config.psm1"
        Import-Module $script:configModule -Force
        $script:envNames = @(
            "AGENT_OS_CONFIG",
            "OSTWIN_CONFIG_PATH",
            "OSTWIN_PROJECT_DIR",
            "AGENTS_DIR",
            "OSTWIN_HOME"
        )
    }

    BeforeEach {
        $script:savedEnv = @{}
        foreach ($name in $script:envNames) {
            $script:savedEnv[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
            Remove-Item "Env:$name" -ErrorAction SilentlyContinue
        }
    }

    AfterEach {
        foreach ($name in $script:envNames) {
            if ($null -eq $script:savedEnv[$name]) {
                Remove-Item "Env:$name" -ErrorAction SilentlyContinue
            }
            else {
                [Environment]::SetEnvironmentVariable($name, $script:savedEnv[$name], "Process")
            }
        }
    }

    It "uses the global Ostwin config before project-local fallback" {
        $ostwinHome = Join-Path $TestDrive ".ostwin"
        $globalConfig = Join-Path (Join-Path $ostwinHome ".agents") "config.json"
        New-Item -ItemType Directory -Path (Split-Path $globalConfig -Parent) -Force | Out-Null
        '{"manager":{"state_timeout_seconds":1800}}' | Out-File -FilePath $globalConfig -Encoding utf8 -NoNewline
        $env:OSTWIN_HOME = $ostwinHome

        Resolve-OstwinConfigPath | Should -Be $globalConfig
    }

    It "honors AGENT_OS_CONFIG over the global Ostwin config" {
        $ostwinHome = Join-Path $TestDrive ".ostwin"
        $globalConfig = Join-Path (Join-Path $ostwinHome ".agents") "config.json"
        $explicitConfig = Join-Path $TestDrive "explicit-config.json"
        New-Item -ItemType Directory -Path (Split-Path $globalConfig -Parent) -Force | Out-Null
        '{"manager":{"state_timeout_seconds":1800}}' | Out-File -FilePath $globalConfig -Encoding utf8 -NoNewline
        '{"manager":{"state_timeout_seconds":600}}' | Out-File -FilePath $explicitConfig -Encoding utf8 -NoNewline
        $env:OSTWIN_HOME = $ostwinHome
        $env:AGENT_OS_CONFIG = $explicitConfig

        Resolve-OstwinConfigPath | Should -Be $explicitConfig
    }

    It "honors OSTWIN_CONFIG_PATH for dashboard-compatible overrides" {
        $explicitConfig = Join-Path $TestDrive "ostwin-config-path.json"
        '{"manager":{"state_timeout_seconds":2400}}' | Out-File -FilePath $explicitConfig -Encoding utf8 -NoNewline
        $env:OSTWIN_CONFIG_PATH = $explicitConfig

        Resolve-OstwinConfigPath | Should -Be $explicitConfig
    }

    It "honors OSTWIN_PROJECT_DIR for project-scoped config" {
        $projectDir = Join-Path $TestDrive "project"
        $projectConfig = Join-Path (Join-Path $projectDir ".agents") "config.json"
        New-Item -ItemType Directory -Path (Split-Path $projectConfig -Parent) -Force | Out-Null
        '{"manager":{"state_timeout_seconds":1200}}' | Out-File -FilePath $projectConfig -Encoding utf8 -NoNewline
        $env:OSTWIN_PROJECT_DIR = $projectDir

        Resolve-OstwinConfigPath | Should -Be $projectConfig
    }
}
