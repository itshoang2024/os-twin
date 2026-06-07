$global:TestRoot = $PSScriptRoot
$global:AgentsDir = (Resolve-Path (Join-Path $global:TestRoot "..\..\..\")).Path
$global:ManagerDir = Join-Path $global:AgentsDir "roles\manager"

Describe "Manager PID Lifecycle Ownership" {
    BeforeAll {
        $managerScriptFile = Join-Path $global:ManagerDir "Start-ManagerLoop.ps1"
        $lines = Get-Content $managerScriptFile
        $loopIdx = -1
        for ($i = 0; $i -lt $lines.Count; $i++) {
            if ($lines[$i] -match '^# === MAIN LOOP ===') {
                $loopIdx = $i
                break
            }
        }
        $headerRaw = $lines[0..($loopIdx - 1)] -join "`n"
        $headerRaw = $headerRaw -replace '\$PSScriptRoot', "'$global:ManagerDir'"
        $headerRaw = $headerRaw -replace '\$PID \| Out-File -FilePath \$managerPidFile', '# Bypassed pid'
        Invoke-Expression $headerRaw
    }
    
    Context "Write-RoomStatus" {
        It "should clean up .pid and .spawned_at files from the pids directory on state transition" {
            # Setup: Create a fake war room
            $tempDir = Join-Path $global:TestRoot "temp_room_status"
            if (Test-Path $tempDir) { Remove-Item $tempDir -Recurse -Force }
            New-Item -ItemType Directory -Path $tempDir | Out-Null
            
            $pidsDir = Join-Path $tempDir "pids"
            New-Item -ItemType Directory -Path $pidsDir | Out-Null
            
            $fakePidFile = Join-Path $pidsDir "architect.pid"
            $fakeLockFile = Join-Path $pidsDir "architect.spawned_at"
            "99999" | Out-File -FilePath $fakePidFile -Encoding utf8
            "1234567890" | Out-File -FilePath $fakeLockFile -Encoding utf8
            
            # Ensure they exist before action
            Test-Path $fakePidFile | Should -Be $true
            Test-Path $fakeLockFile | Should -Be $true
            
            # Act: Call Write-RoomStatus
            Write-RoomStatus -RoomDir $tempDir -NewStatus "passed"
            
            # Assert: The manager must have cleaned up the process tracking files
            Test-Path $fakePidFile | Should -Be $false
            Test-Path $fakeLockFile | Should -Be $false
            
            # Verify status was actually written
            $statusContent = Get-Content (Join-Path $tempDir "status") -Raw
            $statusContent.Trim() | Should -Be "done"
            
            # Cleanup
            Remove-Item $tempDir -Recurse -Force
        }
    }
    
    Context "Stop-RoomProcesses" {
        It "should clean up .pid and .spawned_at files when processes are forcefully stopped" {
            # Setup: Create a fake war room
            $tempDir = Join-Path $global:TestRoot "temp_room_stop"
            if (Test-Path $tempDir) { Remove-Item $tempDir -Recurse -Force }
            New-Item -ItemType Directory -Path $tempDir | Out-Null
            
            $pidsDir = Join-Path $tempDir "pids"
            New-Item -ItemType Directory -Path $pidsDir | Out-Null
            
            # Provide a wildly out-of-bounds PID so Stop-Process silently catches the attempt
            $fakePidFile = Join-Path $pidsDir "qa.pid"
            $fakeLockFile = Join-Path $pidsDir "qa.spawned_at"
            "999999" | Out-File -FilePath $fakePidFile -Encoding utf8
            "1234567890" | Out-File -FilePath $fakeLockFile -Encoding utf8
            
            # Ensure they exist before action
            Test-Path $fakePidFile | Should -Be $true
            Test-Path $fakeLockFile | Should -Be $true
            
            # Act: Call Stop-RoomProcesses
            Stop-RoomProcesses -RoomDir $tempDir
            
            # Assert: The manager must have cleaned up both the PID and the spawn lock
            Test-Path $fakePidFile | Should -Be $false
            Test-Path $fakeLockFile | Should -Be $false
            
            # Cleanup
            Remove-Item $tempDir -Recurse -Force
        }
    }
}
