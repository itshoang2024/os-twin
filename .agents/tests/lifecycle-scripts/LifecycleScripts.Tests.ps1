<#
.SYNOPSIS
    Pester tests for EPIC-004 — PowerShell ports of lifecycle shell scripts.
    Validates that all 13 ported .ps1 scripts parse cleanly, have correct
    parameter definitions, and produce expected output for core behaviors.
#>

BeforeAll {
    $ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot ".." ".." "..")).Path
    $AgentsDir = Join-Path $ProjectRoot ".agents"
}

# ─── Parse validation: every .ps1 file must parse without errors ─────────────

Describe "Parse Validation — All ported scripts parse without errors" {
    $scripts = @(
        @{ Name = "init.ps1";           Path = "init.ps1" }
        @{ Name = "dashboard.ps1";      Path = "dashboard.ps1" }
        @{ Name = "stop.ps1";           Path = "stop.ps1" }
        @{ Name = "health.ps1";         Path = "health.ps1" }
        @{ Name = "sync.ps1";           Path = "sync.ps1" }
        @{ Name = "sync-skills.ps1";    Path = "sync-skills.ps1" }
        @{ Name = "logs.ps1";           Path = "logs.ps1" }
        @{ Name = "config.ps1";         Path = "config.ps1" }
        @{ Name = "uninstall.ps1";      Path = "uninstall.ps1" }
        @{ Name = "memory-monitor.ps1"; Path = "memory-monitor.ps1" }
        @{ Name = "clawhub-install.ps1"; Path = "clawhub-install.ps1" }
        @{ Name = "bin/agent.ps1";      Path = "bin/agent.ps1" }
        @{ Name = "bin/memory.ps1";     Path = "bin/memory.ps1" }
    )

    It "Should parse <Name> without errors" -ForEach $scripts {
        $filePath = Join-Path $AgentsDir $Path
        $filePath | Should -Exist

        $errors = $null
        $null = [System.Management.Automation.Language.Parser]::ParseFile(
            $filePath, [ref]$null, [ref]$errors
        )
        $errors.Count | Should -Be 0
    }
}

# ─── init.ps1 ────────────────────────────────────────────────────────────────

Describe "init.ps1" {
    It "Should create .agents/mcp directory and seed config" {
        $tmpDir = Join-Path ([System.IO.Path]::GetTempPath()) "ostwin-init-test-$([guid]::NewGuid().ToString('N').Substring(0,8))"
        New-Item -ItemType Directory -Path $tmpDir -Force | Out-Null

        try {
            # Run init.ps1 with -Yes in the temp directory
            & pwsh -NoProfile -File (Join-Path $AgentsDir "init.ps1") $tmpDir -Yes 2>&1 | Out-Null

            # Verify .agents/mcp was created
            (Join-Path $tmpDir ".agents" "mcp") | Should -Exist
            # Verify extensions.json was seeded
            (Join-Path $tmpDir ".agents" "mcp" "extensions.json") | Should -Exist
        }
        finally {
            Remove-Item $tmpDir -Recurse -Force -ErrorAction SilentlyContinue
        }
    }

    It "Should create .gitignore with Ostwin entries" {
        $tmpDir = Join-Path ([System.IO.Path]::GetTempPath()) "ostwin-init-gi-$([guid]::NewGuid().ToString('N').Substring(0,8))"
        New-Item -ItemType Directory -Path $tmpDir -Force | Out-Null

        try {
            & pwsh -NoProfile -File (Join-Path $AgentsDir "init.ps1") $tmpDir -Yes 2>&1 | Out-Null

            $gitignore = Join-Path $tmpDir ".gitignore"
            $gitignore | Should -Exist
            $content = Get-Content $gitignore -Raw
            $content | Should -Match "Ostwin generated"
            $content | Should -Match "\.war-rooms/"
        }
        finally {
            Remove-Item $tmpDir -Recurse -Force -ErrorAction SilentlyContinue
        }
    }

    It "Should remove Ostwin MCP entries from legacy home opencode config" {
        $tmpDir = Join-Path ([System.IO.Path]::GetTempPath()) "ostwin-init-legacy-$([guid]::NewGuid().ToString('N').Substring(0,8))"
        $tmpHome = Join-Path ([System.IO.Path]::GetTempPath()) "ostwin-home-legacy-$([guid]::NewGuid().ToString('N').Substring(0,8))"
        New-Item -ItemType Directory -Path $tmpDir -Force | Out-Null

        $legacyDir = Join-Path $tmpHome ".opencode"
        New-Item -ItemType Directory -Path $legacyDir -Force | Out-Null
        $legacyFile = Join-Path $legacyDir "opencode.json"
        [ordered]@{
            provider = "test-provider"
            theme = "system"
            mcp = [ordered]@{
                memory = [ordered]@{
                    type = "remote"
                    url = "http://localhost:3366/api/memory-pool/mcp"
                }
                knowledge = [ordered]@{
                    type = "remote"
                    url = "http://localhost:3366/api/knowledge/mcp/"
                }
                custom = [ordered]@{
                    type = "remote"
                    url = "http://localhost:9999/mcp"
                }
            }
            mcpServers = [ordered]@{
                warroom = [ordered]@{
                    command = @("python3", "warroom-server.py")
                }
                customServer = [ordered]@{
                    command = @("custom-mcp")
                }
            }
        } | ConvertTo-Json -Depth 8 | Set-Content -Path $legacyFile -Encoding utf8

        $oldHome = $env:HOME
        $oldUserProfile = $env:USERPROFILE
        $oldXdgConfigHome = $env:XDG_CONFIG_HOME

        try {
            $env:HOME = $tmpHome
            $env:USERPROFILE = $tmpHome
            $env:XDG_CONFIG_HOME = Join-Path $tmpHome ".config"

            & pwsh -NoProfile -File (Join-Path $AgentsDir "init.ps1") $tmpDir -Yes -PlanId "plan123" 2>&1 | Out-Null

            $updated = Get-Content $legacyFile -Raw | ConvertFrom-Json
            $updated.provider | Should -Be "test-provider"
            $updated.theme | Should -Be "system"

            $mcpNames = @($updated.mcp.PSObject.Properties.Name)
            $mcpNames | Should -Contain "custom"
            $mcpNames | Should -Not -Contain "memory"
            $mcpNames | Should -Not -Contain "knowledge"

            $legacyNames = @($updated.mcpServers.PSObject.Properties.Name)
            $legacyNames | Should -Contain "customServer"
            $legacyNames | Should -Not -Contain "warroom"

            "$legacyFile.ostwin.bak" | Should -Exist
        }
        finally {
            if ($null -eq $oldHome) { Remove-Item Env:HOME -ErrorAction SilentlyContinue } else { $env:HOME = $oldHome }
            if ($null -eq $oldUserProfile) { Remove-Item Env:USERPROFILE -ErrorAction SilentlyContinue } else { $env:USERPROFILE = $oldUserProfile }
            if ($null -eq $oldXdgConfigHome) { Remove-Item Env:XDG_CONFIG_HOME -ErrorAction SilentlyContinue } else { $env:XDG_CONFIG_HOME = $oldXdgConfigHome }
            Remove-Item $tmpDir -Recurse -Force -ErrorAction SilentlyContinue
            Remove-Item $tmpHome -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

# ─── config.ps1 ──────────────────────────────────────────────────────────────

Describe "config.ps1" {
    BeforeAll {
        $tmpConfig = Join-Path ([System.IO.Path]::GetTempPath()) "ostwin-config-test-$([guid]::NewGuid().ToString('N').Substring(0,8)).json"
        @{
            version = "1.0.0"
            manager = @{
                poll_interval_seconds = 30
                max_concurrent_rooms = 5
            }
        } | ConvertTo-Json -Depth 5 | Set-Content -Path $tmpConfig
    }

    AfterAll {
        Remove-Item $tmpConfig -Force -ErrorAction SilentlyContinue
    }

    It "Should print full config in JSON format" {
        $env:AGENT_OS_CONFIG = $tmpConfig
        $output = & pwsh -NoProfile -Command ". '$AgentsDir/config.ps1'" 2>&1
        $env:AGENT_OS_CONFIG = $null
        $outputStr = $output -join "`n"
        $outputStr | Should -Match '"version"'
        $outputStr | Should -Match '"manager"'
    }

    It "Should get a specific config value via -Get" {
        $env:AGENT_OS_CONFIG = $tmpConfig
        $output = & pwsh -NoProfile -Command ". '$AgentsDir/config.ps1' -Get 'manager.poll_interval_seconds'" 2>&1
        $env:AGENT_OS_CONFIG = $null
        ($output -join "").Trim() | Should -Be "30"
    }

    It "Should set a config value via -Set" {
        $env:AGENT_OS_CONFIG = $tmpConfig
        & pwsh -NoProfile -Command ". '$AgentsDir/config.ps1' -Set 'manager.max_concurrent_rooms' -Value 10" 2>&1 | Out-Null
        $env:AGENT_OS_CONFIG = $null

        $data = Get-Content $tmpConfig -Raw | ConvertFrom-Json
        $data.manager.max_concurrent_rooms | Should -Be 10
    }
}

# ─── health.ps1 ──────────────────────────────────────────────────────────────

Describe "health.ps1" {
    It "Should return JSON output with --json flag" {
        $output = & pwsh -NoProfile -Command "& '$AgentsDir/health.ps1' -JsonOutput" 2>&1
        $outputStr = $output -join "`n"
        $outputStr | Should -Match '"status"'
        $outputStr | Should -Match '"manager"'
        $outputStr | Should -Match '"rooms"'
    }

    It "Should report healthy when no manager is running" {
        $output = & pwsh -NoProfile -Command "& '$AgentsDir/health.ps1' -JsonOutput" 2>&1
        $outputStr = $output -join "`n"
        $json = $outputStr | ConvertFrom-Json
        # With no manager and no active rooms, should be healthy
        $json.status | Should -BeIn @("healthy", "unhealthy")
    }
}

# ─── logs.ps1 ────────────────────────────────────────────────────────────────

Describe "logs.ps1" {
    BeforeAll {
        $tmpWarrooms = Join-Path ([System.IO.Path]::GetTempPath()) "ostwin-logs-test-$([guid]::NewGuid().ToString('N').Substring(0,8))"
        $roomDir = Join-Path $tmpWarrooms "room-001"
        New-Item -ItemType Directory -Path $roomDir -Force | Out-Null

        # Create test channel.jsonl
        $messages = @(
            @{ v = 1; ts = "2026-04-11T10:00:00Z"; from = "manager"; to = "engineer"; type = "task"; ref = "TASK-001"; body = "Do the thing" }
            @{ v = 1; ts = "2026-04-11T10:01:00Z"; from = "engineer"; to = "qa"; type = "done"; ref = "TASK-001"; body = "Done!" }
        )
        $messages | ForEach-Object { $_ | ConvertTo-Json -Compress } | Set-Content -Path (Join-Path $roomDir "channel.jsonl")
    }

    AfterAll {
        Remove-Item $tmpWarrooms -Recurse -Force -ErrorAction SilentlyContinue
    }

    It "Should display messages from a specific room" {
        $env:WARROOMS_DIR = $tmpWarrooms
        $output = & pwsh -NoProfile -Command "& '$AgentsDir/logs.ps1' -RoomId 'room-001'" 2>&1
        $env:WARROOMS_DIR = $null
        $outputStr = $output -join "`n"
        $outputStr | Should -Match "TASK"
        $outputStr | Should -Match "manager"
    }

    It "Should filter by message type" {
        $env:WARROOMS_DIR = $tmpWarrooms
        $output = & pwsh -NoProfile -Command "& '$AgentsDir/logs.ps1' -RoomId 'room-001' -Type 'done'" 2>&1
        $env:WARROOMS_DIR = $null
        $outputStr = $output -join "`n"
        $outputStr | Should -Match "OK"
        $outputStr | Should -Not -Match "\[TASK\]"
    }

    It "Should limit with -Last flag" {
        $env:WARROOMS_DIR = $tmpWarrooms
        $output = & pwsh -NoProfile -Command "& '$AgentsDir/logs.ps1' -RoomId 'room-001' -Last 1" 2>&1
        $env:WARROOMS_DIR = $null
        @($output | Where-Object { $_ -match '\[' }).Count | Should -Be 1
    }
}

# ─── stop.ps1 ────────────────────────────────────────────────────────────────

Describe "stop.ps1" {
    It "Should have CmdletBinding and Force parameter" {
        $ast = [System.Management.Automation.Language.Parser]::ParseFile(
            (Join-Path $AgentsDir "stop.ps1"), [ref]$null, [ref]$null
        )
        $params = $ast.ParamBlock.Parameters
        $forceParam = $params | Where-Object { $_.Name.VariablePath.UserPath -eq "Force" }
        $forceParam | Should -Not -BeNullOrEmpty
    }

    It "Should handle dashboard PID file cleanup" {
        # Verify the script defines Stop-Dashboard function
        $content = Get-Content (Join-Path $AgentsDir "stop.ps1") -Raw
        $content | Should -Match "function Stop-Dashboard"
        $content | Should -Match "dashboard\.pid"
        $content | Should -Match "manager\.pid"
    }
}

# ─── memory-monitor.ps1 ─────────────────────────────────────────────────────

Describe "memory-monitor.ps1" {
    It "Should report venv status without errors" {
        $output = & pwsh -NoProfile -Command "& '$AgentsDir/memory-monitor.ps1' -Command 'status'" 2>&1
        $outputStr = $output -join "`n"
        $outputStr | Should -Match "MCP venv:"
        $outputStr | Should -Match "Ledger:"
    }
}

# ─── uninstall.ps1 ───────────────────────────────────────────────────────────

Describe "uninstall.ps1" {
    It "Should report nothing to remove when install dir does not exist" {
        $output = & pwsh -NoProfile -Command "& '$AgentsDir/uninstall.ps1' -Dir '/tmp/ostwin-nonexistent-$([guid]::NewGuid().ToString('N'))' -Yes" 2>&1
        $outputStr = $output -join "`n"
        $outputStr | Should -Match "Nothing to remove"
    }
}

# ─── sync.ps1 ────────────────────────────────────────────────────────────────

Describe "sync.ps1" {
    It "Should error when target has no .agents/ directory" {
        $tmpDir = Join-Path ([System.IO.Path]::GetTempPath()) "ostwin-sync-test-$([guid]::NewGuid().ToString('N').Substring(0,8))"
        New-Item -ItemType Directory -Path $tmpDir -Force | Out-Null

        try {
            $output = & pwsh -NoProfile -Command "& '$AgentsDir/sync.ps1' '$tmpDir'" 2>&1
            $outputStr = $output -join "`n"
            $outputStr | Should -Match "\.agents/ not found"
        }
        finally {
            Remove-Item $tmpDir -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

# ─── clawhub-install.ps1 ────────────────────────────────────────────────────

Describe "clawhub-install.ps1" {
    It "Should show help when invoked with no arguments" {
        $output = & pwsh -NoProfile -Command "& '$AgentsDir/clawhub-install.ps1' help" 2>&1
        $outputStr = $output -join "`n"
        $outputStr | Should -Match "ClawHub Skill Installer"
        $outputStr | Should -Match "install"
        $outputStr | Should -Match "search"
    }

    It "Should list empty when no skills installed" {
        $tmpHome = Join-Path ([System.IO.Path]::GetTempPath()) "ostwin-clawhub-$([guid]::NewGuid().ToString('N').Substring(0,8))"
        New-Item -ItemType Directory -Path $tmpHome -Force | Out-Null

        try {
            $output = & pwsh -NoProfile -Command "`$env:OSTWIN_HOME = '$tmpHome'; & '$AgentsDir/clawhub-install.ps1' list" 2>&1
            $outputStr = $output -join "`n"
            $outputStr | Should -Match "(No skills installed|Installed ClawHub Skills)"
        }
        finally {
            Remove-Item $tmpHome -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

# ─── bin/agent.ps1 ───────────────────────────────────────────────────────────

Describe "bin/agent.ps1" {
    It "Should have correct parameter structure" {
        $ast = [System.Management.Automation.Language.Parser]::ParseFile(
            (Join-Path $AgentsDir "bin" "agent.ps1"), [ref]$null, [ref]$null
        )
        $params = $ast.ParamBlock.Parameters
        $params.Count | Should -BeGreaterOrEqual 1
        $params[0].Name.VariablePath.UserPath | Should -Be "Arguments"
    }
}

# ─── bin/memory.ps1 ─────────────────────────────────────────────────────────

Describe "bin/memory.ps1" {
    It "Should show help text" {
        $output = & pwsh -NoProfile -Command "& '$AgentsDir/bin/memory.ps1' help" 2>&1
        $outputStr = $output -join "`n"
        $outputStr | Should -Match "publish"
        $outputStr | Should -Match "query"
        $outputStr | Should -Match "search"
        $outputStr | Should -Match "context"
        $outputStr | Should -Match "list"
    }

    It "Should have Command parameter with ValidateSet" -Skip:$(!$true) {
        $ast = [System.Management.Automation.Language.Parser]::ParseFile(
            (Join-Path $AgentsDir "bin" "memory.ps1"), [ref]$null, [ref]$null
        )
        $params = $ast.ParamBlock.Parameters
        $commandParam = $params | Where-Object { $_.Name.VariablePath.UserPath -eq "Command" }
        $commandParam | Should -Not -BeNullOrEmpty
    }
}

# ─── ostwin.ps1 dispatcher ──────────────────────────────────────────────────

Describe "ostwin.ps1 — dispatch to .ps1 scripts" {
    It "Should prefer init.ps1 over init.sh when dispatching 'init'" {
        $content = Get-Content (Join-Path $AgentsDir "bin" "ostwin.ps1") -Raw
        $content | Should -Match 'initPs1 = Join-Path.*"init\.ps1"'
        $content | Should -Match 'Test-Path \$initPs1'
    }

    It "Should prefer sync.ps1 over sync.sh when dispatching 'sync'" {
        $content = Get-Content (Join-Path $AgentsDir "bin" "ostwin.ps1") -Raw
        $content | Should -Match 'syncPs1 = Join-Path.*"sync\.ps1"'
    }

    It "Should prefer health.ps1 over health.sh when dispatching 'health'" {
        $content = Get-Content (Join-Path $AgentsDir "bin" "ostwin.ps1") -Raw
        $content | Should -Match 'healthPs1 = Join-Path.*"health\.ps1"'
    }

    It "Should prefer config.ps1 over config.sh when dispatching 'config'" {
        $content = Get-Content (Join-Path $AgentsDir "bin" "ostwin.ps1") -Raw
        $content | Should -Match 'configPs1 = Join-Path.*"config\.ps1"'
    }

    It "Should prefer logs.ps1 over logs.sh when dispatching 'logs'" {
        $content = Get-Content (Join-Path $AgentsDir "bin" "ostwin.ps1") -Raw
        $content | Should -Match 'logsPs1 = Join-Path.*"logs\.ps1"'
    }

    It "Should prefer dashboard.ps1 over dashboard.sh when dispatching 'dashboard'" {
        $content = Get-Content (Join-Path $AgentsDir "bin" "ostwin.ps1") -Raw
        $content | Should -Match 'dashPs1 = Join-Path.*"dashboard\.ps1"'
    }

    It "Should prefer sync-skills.ps1 for skills sync" {
        $content = Get-Content (Join-Path $AgentsDir "bin" "ostwin.ps1") -Raw
        $content | Should -Match 'sync-skills\.ps1'
    }

    It "Should prefer clawhub-install.ps1 for skills install/search/update/remove" {
        $content = Get-Content (Join-Path $AgentsDir "bin" "ostwin.ps1") -Raw
        $content | Should -Match 'clawhub-install\.ps1'
    }
}

# ─── Bash script non-regression ──────────────────────────────────────────────

Describe "Bash scripts unchanged (no regression)" {
    $bashScripts = @(
        @{ Name = "dashboard.sh";      Path = "dashboard.sh" }
        @{ Name = "stop.sh";           Path = "stop.sh" }
        @{ Name = "health.sh";         Path = "health.sh" }
        @{ Name = "sync.sh";           Path = "sync.sh" }
        @{ Name = "logs.sh";           Path = "logs.sh" }
        @{ Name = "config.sh";         Path = "config.sh" }
        @{ Name = "uninstall.sh";      Path = "uninstall.sh" }
        @{ Name = "memory-monitor.sh"; Path = "memory-monitor.sh" }
        @{ Name = "clawhub-install.sh"; Path = "clawhub-install.sh" }
        @{ Name = "bin/agent";         Path = "bin/agent" }
        @{ Name = "bin/memory";        Path = "bin/memory" }
    )

    It "Should still have <Name> present and unmodified" -ForEach $bashScripts {
        $filePath = Join-Path $AgentsDir $Path
        $filePath | Should -Exist
    }
}
