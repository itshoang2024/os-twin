# ──────────────────────────────────────────────────────────────────────────────
# Setup-Autostart.ps1 — Register/unregister the Ostwin dashboard as a
#                        Windows auto-start service via Task Scheduler
#
# Provides: Setup-Autostart, Remove-Autostart
#
# Why Task Scheduler instead of HKCU\Run?
#   - Task Scheduler supports "Run whether user is logged on or not"
#   - Supports delayed start, retry on failure, and proper logging
#   - HKCU\Run opens a visible console window on every login
#
# Requires: Lib.ps1, globals: $script:InstallDir, $script:DashboardPort
# ──────────────────────────────────────────────────────────────────────────────

if ($script:_SetupAutostartPs1Loaded) { return }
$script:_SetupAutostartPs1Loaded = $true

$script:TaskName = "OstwinDashboard"

function Setup-Autostart {
    [CmdletBinding()]
    param(
        [switch]$SkipStart
    )

    # Only applies to Windows
    if (-not ($IsWindows -or (-not $IsLinux -and -not $IsMacOS))) {
        Write-Info "Auto-start registration skipped (not Windows)"
        return
    }

    Write-Step "Registering dashboard as Windows auto-start task..."

    $dashboardPs1 = Join-Path $script:InstallDir ".agents\dashboard.ps1"
    if (-not (Test-Path $dashboardPs1)) {
        Write-Warn "dashboard.ps1 not found — skipping auto-start registration"
        Write-Info "Re-run: .\install.ps1 -SourceDir C:\path\to\agent-os"
        return
    }

    $pwshExe = (Get-Command pwsh -ErrorAction SilentlyContinue).Source
    if (-not $pwshExe) {
        $pwshExe = (Get-Command powershell -ErrorAction SilentlyContinue).Source
    }
    if (-not $pwshExe) {
        Write-Warn "PowerShell not found — cannot register auto-start task"
        return
    }

    # Build the command arguments
    $argList = "-NoProfile -ExecutionPolicy Bypass -File `"$dashboardPs1`" -Background -Port $($script:DashboardPort) -ProjectDir `"$($script:InstallDir)`""

    # Remove any existing task first (clean re-registration)
    try {
        $existing = Get-ScheduledTask -TaskName $script:TaskName -ErrorAction SilentlyContinue
        if ($existing) {
            Unregister-ScheduledTask -TaskName $script:TaskName -Confirm:$false -ErrorAction SilentlyContinue
        }
    } catch {}

    try {
        # Create the action — run pwsh with the dashboard script
        $action = New-ScheduledTaskAction -Execute $pwshExe -Argument $argList

        # Trigger — at user logon, with a 10s delay so the desktop settles first
        $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
        # Delay start by 10 seconds to avoid race with desktop initialization
        $trigger.Delay = "PT10S"

        # Settings — run on battery, don't stop on battery change, allow start when available
        $settings = New-ScheduledTaskSettingsSet `
            -AllowStartIfOnBatteries `
            -DontStopIfGoingOnBatteries `
            -StartWhenAvailable `
            -MultipleInstances IgnoreNew `
            -ExecutionTimeLimit ([TimeSpan]::Zero)   # No time limit — dashboard runs forever

        # Register the task
        Register-ScheduledTask `
            -TaskName $script:TaskName `
            -Action $action `
            -Trigger $trigger `
            -Settings $settings `
            -Description "Ostwin Dashboard — Multi-Agent War-Room Orchestrator (auto-start at login)" `
            -Force | Out-Null

        Write-Ok "Registered auto-start task: $script:TaskName"
        Write-Info "Dashboard will start on next login (10s delay)"

        # Start immediately unless --no-start
        if (-not $SkipStart) {
            try {
                Start-ScheduledTask -TaskName $script:TaskName -ErrorAction Stop
                Write-Ok "Dashboard auto-start task triggered"
            } catch {
                Write-Warn "Could not trigger task immediately: $_"
                Write-Info "Dashboard will start on next login"
            }
        }
    }
    catch {
        Write-Warn "Failed to register auto-start task: $_"
        Write-Info "You can register manually via Task Scheduler or run: ostwin dashboard start"
    }
}

function Remove-Autostart {
    [CmdletBinding()]
    param()

    if (-not ($IsWindows -or (-not $IsLinux -and -not $IsMacOS))) {
        return
    }

    try {
        $existing = Get-ScheduledTask -TaskName $script:TaskName -ErrorAction SilentlyContinue
        if ($existing) {
            Unregister-ScheduledTask -TaskName $script:TaskName -Confirm:$false
            Write-Ok "Removed auto-start task: $script:TaskName"
        }
        else {
            Write-Info "Auto-start task not found — already removed"
        }
    }
    catch {
        Write-Warn "Failed to remove auto-start task: $_"
    }
}
