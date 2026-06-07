#Requires -Version 7.0

Describe "health.ps1" {
    BeforeAll {
        $script:agentsDir = (Resolve-Path (Join-Path $PSScriptRoot "../../..")).Path
        $script:healthScript = Join-Path $script:agentsDir "health.ps1"
        $script:envNames = @(
            "AGENT_OS_CONFIG",
            "OSTWIN_CONFIG_PATH",
            "OSTWIN_PROJECT_DIR",
            "AGENTS_DIR",
            "OSTWIN_HOME",
            "WARROOMS_DIR"
        )

        function script:New-HealthTestRoom {
            param(
                [Parameter(Mandatory)][string]$RoomsDir,
                [Parameter(Mandatory)][string]$Status,
                [Parameter(Mandatory)][int]$ElapsedSeconds
            )

            $roomDir = Join-Path $RoomsDir "room-001"
            New-Item -ItemType Directory -Path $roomDir -Force | Out-Null
            $Status | Out-File -FilePath (Join-Path $roomDir "status") -Encoding utf8 -NoNewline
            (([DateTimeOffset]::UtcNow.ToUnixTimeSeconds()) - $ElapsedSeconds).ToString() |
                Out-File -FilePath (Join-Path $roomDir "state_changed_at") -Encoding utf8 -NoNewline

            @{
                version = 2
                initial_state = "developing"
                states = @{
                    developing = @{
                        type = "work"
                        role = "engineer"
                    }
                    passed = @{
                        type = "terminal"
                    }
                }
            } | ConvertTo-Json -Depth 8 | Out-File -FilePath (Join-Path $roomDir "lifecycle.json") -Encoding utf8

            return $roomDir
        }

        function script:Invoke-HealthJson {
            $json = (& $script:healthScript -JsonOutput) -join "`n"
            return $json | ConvertFrom-Json
        }
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

    It "uses global manager.state_timeout_seconds and counts V2 developing rooms as active" {
        $ostwinHome = Join-Path $TestDrive ".ostwin"
        $globalConfig = Join-Path (Join-Path $ostwinHome ".agents") "config.json"
        $roomsDir = Join-Path $TestDrive "war-rooms"
        New-Item -ItemType Directory -Path (Split-Path $globalConfig -Parent) -Force | Out-Null
        New-Item -ItemType Directory -Path $roomsDir -Force | Out-Null
        '{"manager":{"state_timeout_seconds":1800}}' | Out-File -FilePath $globalConfig -Encoding utf8 -NoNewline
        New-HealthTestRoom -RoomsDir $roomsDir -Status "developing" -ElapsedSeconds 1200 | Out-Null
        $env:OSTWIN_HOME = $ostwinHome
        $env:WARROOMS_DIR = $roomsDir

        $result = Invoke-HealthJson

        $result.config.state_timeout_seconds | Should -Be 1800
        $result.rooms.active | Should -Be 1
        $result.rooms.stuck | Should -Be 0
    }

    It "lets AGENT_OS_CONFIG override the global timeout" {
        $ostwinHome = Join-Path $TestDrive ".ostwin"
        $globalConfig = Join-Path (Join-Path $ostwinHome ".agents") "config.json"
        $explicitConfig = Join-Path $TestDrive "explicit-config.json"
        $roomsDir = Join-Path $TestDrive "war-rooms"
        New-Item -ItemType Directory -Path (Split-Path $globalConfig -Parent) -Force | Out-Null
        New-Item -ItemType Directory -Path $roomsDir -Force | Out-Null
        '{"manager":{"state_timeout_seconds":1800}}' | Out-File -FilePath $globalConfig -Encoding utf8 -NoNewline
        '{"manager":{"state_timeout_seconds":600}}' | Out-File -FilePath $explicitConfig -Encoding utf8 -NoNewline
        New-HealthTestRoom -RoomsDir $roomsDir -Status "developing" -ElapsedSeconds 1200 | Out-Null
        $env:OSTWIN_HOME = $ostwinHome
        $env:AGENT_OS_CONFIG = $explicitConfig
        $env:WARROOMS_DIR = $roomsDir

        $result = Invoke-HealthJson

        $result.config.state_timeout_seconds | Should -Be 600
        $result.rooms.active | Should -Be 1
        $result.rooms.stuck | Should -Be 1
    }
}
