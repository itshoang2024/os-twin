# ──────────────────────────────────────────────────────────────────────────────
# Start-Channels.ps1 — Channel connector install + launch (Telegram, Discord, Slack)
#
# Provides: Install-Channels, Start-Channels
#
# Requires: Lib.ps1, Check-Deps.ps1 (Check-Node, Check-Bun),
#           globals: $script:InstallDir, $script:SourceDir, $script:ScriptDir
# ──────────────────────────────────────────────────────────────────────────────

if ($script:_StartChannelsPs1Loaded) { return }
$script:_StartChannelsPs1Loaded = $true

function Test-ChannelCiMode {
    [CmdletBinding()]
    param()

    $env:CI -in @("1", "true", "TRUE")
}

function Invoke-ChannelBunInstall {
    [CmdletBinding()]
    param()

    if ((Test-Path "bun.lockb") -or (Test-Path "bun.lock")) {
        $installOutput = & bun install --frozen-lockfile 2>&1
        if ($LASTEXITCODE -eq 0) {
            return $true
        }
        if (-not (Test-ChannelCiMode)) {
            Write-Warn "Bun lockfile install failed; retrying without --frozen-lockfile"
            $installOutput | ForEach-Object { Write-Host $_ }
            & bun install 2>&1 | Out-Null
            return ($LASTEXITCODE -eq 0)
        }
        $installOutput | ForEach-Object { Write-Host $_ }
        return $false
    }

    & bun install 2>&1 | Out-Null
    return ($LASTEXITCODE -eq 0)
}

function Get-LocalTsxPath {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)][string]$Directory
    )

    foreach ($name in @("tsx.cmd", "tsx.exe", "tsx")) {
        $candidate = Join-Path $Directory (Join-Path "node_modules\.bin" $name)
        if (Test-Path $candidate) { return $candidate }
    }
    return ""
}

function Install-Channels {
    [CmdletBinding()]
    param()

    # Locate the channel connector directory
    $script:ChanDir = ""
    $candidates = @(
        (Join-Path $script:SourceDir "bot"),
        (Join-Path (Split-Path $script:ScriptDir -Parent) "bot")
    )

    foreach ($c in $candidates) {
        if ($c -and (Test-Path $c) -and (Test-Path (Join-Path $c "package.json"))) {
            $script:ChanDir = (Resolve-Path $c).Path
            break
        }
    }

    if (-not $script:ChanDir) {
        Write-Warn "Channel connector dir (bot/) not found — skipping"
        Write-Info "Expected at bot\package.json relative to the repo root"
        return
    }

    if (-not (Check-Node)) {
        Write-Warn "Node.js not found — cannot install channel connectors"
        Write-Info "Install Node.js and re-run"
        return
    }

    if (-not (Check-Bun)) {
        Write-Warn "Bun not found — cannot install channel connectors"
        Write-Info "Install Bun and re-run"
        return
    }

    Write-Step "Installing channel dependencies in $($script:ChanDir) with Bun..."
    $originalDir = Get-Location
    try {
        Set-Location $script:ChanDir
        if (-not (Invoke-ChannelBunInstall)) {
            Write-Warn "Channel dependency install failed"
            return
        }
        Write-Ok "Channel dependencies installed"
    }
    catch {
        Write-Warn "Channel dependency install failed: $_"
    }
    finally {
        Set-Location $originalDir
    }

    # tsx should come from bot/package.json devDependencies after install.
    $tsxPath = Get-LocalTsxPath -Directory $script:ChanDir
    if (-not $tsxPath) {
        Write-Warn "tsx not found after Bun install"
    }
    else {
        Write-Ok "tsx available"
    }

    Write-Ok "Channel connector dir: $($script:ChanDir)"
}

function Start-Channels {
    [CmdletBinding()]
    param()

    if (-not $script:ChanDir) { return }

    $bunCommand = Get-Command bun -ErrorAction SilentlyContinue
    if (-not $bunCommand) {
        Write-Warn "Bun not found — cannot start channels"
        return
    }

    # Load .env
    $envFile = Join-Path $script:InstallDir ".env"
    if (Test-Path $envFile) {
        Get-Content $envFile | ForEach-Object {
            if ($_ -match '^\s*([^#][^=]+)=(.*)$') {
                [System.Environment]::SetEnvironmentVariable($Matches[1].Trim(), $Matches[2].Trim(), "Process")
            }
        }
    }

    # Load project root .env
    $projectRootEnv = Join-Path (Split-Path $script:ChanDir -Parent) ".env"
    if (Test-Path $projectRootEnv) {
        Get-Content $projectRootEnv | ForEach-Object {
            if ($_ -match '^\s*([^#][^=]+)=(.*)$') {
                [System.Environment]::SetEnvironmentVariable($Matches[1].Trim(), $Matches[2].Trim(), "Process")
            }
        }
    }

    # Stop previous channel process — check both legacy and current PID file locations
    $chanPidFile = Join-Path $script:InstallDir "channels.pid"
    foreach ($legacyPid in @($chanPidFile, (Join-Path $script:InstallDir ".agents\channel.pid"))) {
        if (Test-Path $legacyPid) {
            $oldPid = Get-Content $legacyPid -ErrorAction SilentlyContinue
            if ($oldPid) {
                try {
                    $proc = Get-Process -Id $oldPid -ErrorAction SilentlyContinue
                    if ($proc) {
                        Write-Step "Stopping previous channel process (PID $oldPid)..."
                        & taskkill /F /T /PID $oldPid 2>$null | Out-Null
                        Start-Sleep -Seconds 1
                    }
                } catch { }
            }
            Remove-Item $legacyPid -Force -ErrorAction SilentlyContinue
        }
    }

    # Register Discord slash commands if configured
    if ($env:DISCORD_TOKEN -and $env:DISCORD_CLIENT_ID) {
        Write-Step "Registering Discord slash commands..."
        $originalDir = Get-Location
        try {
            Set-Location $script:ChanDir
            & $bunCommand.Source run deploy 2>$null
            Write-Ok "Discord commands registered"
        }
        catch {
            Write-Warn "Discord command registration failed (non-critical)"
        }
        finally {
            Set-Location $originalDir
        }
    }

    $logsDir = Join-Path $script:InstallDir "logs"
    if (-not (Test-Path $logsDir)) {
        New-Item -ItemType Directory -Path $logsDir -Force | Out-Null
    }

    Write-Step "Starting channels from $($script:ChanDir)..."
    $chanLogFile = Join-Path $logsDir "channel.log"
    $chanErrorLog = Join-Path $logsDir "channel-error.log"

    # Run through Bun so bot/channel lifecycle never depends on npm/pnpm wrappers.
    $batFile = Join-Path $logsDir "_start-channel.cmd"
    $batContent = "@echo off`r`ncd /d `"$($script:ChanDir)`"`r`n`"$($bunCommand.Source)`" run start >`"$chanLogFile`" 2>`"$chanErrorLog`""

    # Write with UTF-8 without BOM (handles non-ASCII paths correctly)
    [System.IO.File]::WriteAllText($batFile, $batContent, [System.Text.UTF8Encoding]::new($false))

    $chanWrapper = Start-Process -FilePath "cmd.exe" `
        -ArgumentList "/c", "`"$batFile`"" `
        -WindowStyle Hidden -PassThru

    # Resolve the real runtime PID by walking the process tree from the cmd.exe wrapper.
    Start-Sleep -Seconds 3
    $wrapperPid = $chanWrapper.Id
    $chanPid = $wrapperPid  # fallback: use wrapper if tree walk fails

    try {
        # Walk cmd.exe → bun.exe → node/tsx if spawned; match the first runtime process.
        $frontier = @($wrapperPid)
        $foundPid = $null
        while ($frontier.Count -gt 0 -and -not $foundPid) {
            $nextFrontier = @()
            foreach ($parentId in $frontier) {
                $children = @(Get-CimInstance Win32_Process -Filter "ParentProcessId = $parentId" -ErrorAction SilentlyContinue)
                foreach ($child in $children) {
                    $nextFrontier += $child.ProcessId
                    $exeName = $child.Name
                    if ($exeName -match '^(bun|node|tsx)(\.exe)?$') {
                        $foundPid = $child.ProcessId
                        break
                    }
                }
                if ($foundPid) { break }
            }
            $frontier = $nextFrontier
        }
        if ($foundPid) { $chanPid = $foundPid }
    } catch {}

    Set-Content -Path $chanPidFile -Value $chanPid -NoNewline
    Write-Ok "Channels started (PID $chanPid) — log: $chanLogFile"

    if ($env:TELEGRAM_BOT_TOKEN) { Write-Ok "Telegram: enabled" } else { Write-Info "Telegram: disabled (set TELEGRAM_BOT_TOKEN)" }
    if ($env:DISCORD_TOKEN) { Write-Ok "Discord: enabled" } else { Write-Info "Discord: disabled (set DISCORD_TOKEN)" }
    if ($env:SLACK_BOT_TOKEN) { Write-Ok "Slack: enabled" } else { Write-Info "Slack: disabled (set SLACK_BOT_TOKEN)" }
}
