# Agent OS — Wait-ForMessage Pester Tests

BeforeAll {
    . (Join-Path (Resolve-Path "$PSScriptRoot/..").Path "TestChannelHelpers.ps1")
    $script:PostMessage = New-TestChannelWriter
    $script:WaitForMessage = Join-Path (Resolve-Path "$PSScriptRoot/../../channel").Path "Wait-ForMessage.ps1"
}

Describe "Wait-ForMessage" {
    BeforeEach {
        $script:roomDir = Join-Path $TestDrive "room-$(Get-Random)"
        New-Item -ItemType Directory -Path $script:roomDir -Force | Out-Null
    }

    Context "Immediate match" {
        It "returns immediately when matching message already exists" {
            # Post a 'done' message first
            & $script:PostMessage -RoomDir $script:roomDir -From "engineer" -To "manager" `
                                  -Type "done" -Ref "TASK-001" -Body "Completed"

            $result = & $script:WaitForMessage -RoomDir $script:roomDir -WaitType "done" `
                                               -PollIntervalSeconds 1
            $msg = $result | ConvertFrom-Json
            $msg.type | Should -Be "done"
            $msg.body | Should -Be "Completed"
        }

        It "returns the matching message with from filter" {
            & $script:PostMessage -RoomDir $script:roomDir -From "qa" -To "manager" `
                                  -Type "pass" -Ref "TASK-001" -Body "All good"

            $result = & $script:WaitForMessage -RoomDir $script:roomDir -WaitType "pass" `
                                               -FilterFrom "qa" -PollIntervalSeconds 1
            $msg = $result | ConvertFrom-Json
            $msg.from | Should -Be "qa"
            $msg.type | Should -Be "pass"
        }

        It "returns the matching message with ref filter" {
            & $script:PostMessage -RoomDir $script:roomDir -From "engineer" -To "manager" `
                                  -Type "done" -Ref "EPIC-001" -Body "Epic done"

            $result = & $script:WaitForMessage -RoomDir $script:roomDir -WaitType "done" `
                                               -FilterRef "EPIC-001" -PollIntervalSeconds 1
            $msg = $result | ConvertFrom-Json
            $msg.ref | Should -Be "EPIC-001"
        }
    }

    Context "Timeout" {
        It "exits with error after timeout when no matching message" {
            $ErrorActionPreference = 'Continue'
            # Post a non-matching message
            & $script:PostMessage -RoomDir $script:roomDir -From "manager" -To "engineer" `
                                  -Type "task" -Ref "TASK-001" -Body "Do something"

            # Wait for 'done' with very short timeout — should fail
            $result = & $script:WaitForMessage -RoomDir $script:roomDir -WaitType "done" `
                                               -TimeoutSeconds 2 -PollIntervalSeconds 1 2>&1

            # Should have exited with error
            $LASTEXITCODE | Should -Not -Be 0
        }
    }

    Context "Async message arrival" {
        It "waits and returns when message arrives after startup" {
            # Start the wait in a background job
            $job = Start-Job -ScriptBlock {
                param($script, $room)
                & $script -RoomDir $room -WaitType "done" -PollIntervalSeconds 1 -TimeoutSeconds 10
            } -ArgumentList $script:WaitForMessage, $script:roomDir

            # Post the message after a short delay
            Start-Sleep -Seconds 2
            & $script:PostMessage -RoomDir $script:roomDir -From "engineer" -To "manager" `
                                  -Type "done" -Ref "TASK-001" -Body "Finished async"

            # Wait for job completion
            $job | Wait-Job -Timeout 15 | Out-Null
            $output = $job | Receive-Job
            $job | Remove-Job -Force

            $msg = $output | ConvertFrom-Json
            $msg.type | Should -Be "done"
            $msg.body | Should -Be "Finished async"
        }
    }

    Context "No channel file" {
        It "waits without error when channel.jsonl doesn't exist yet, then returns when it appears" {
            $job = Start-Job -ScriptBlock {
                param($script, $room)
                & $script -RoomDir $room -WaitType "task" -PollIntervalSeconds 1 -TimeoutSeconds 10
            } -ArgumentList $script:WaitForMessage, $script:roomDir

            Start-Sleep -Seconds 2
            & $script:PostMessage -RoomDir $script:roomDir -From "manager" -To "engineer" `
                                  -Type "task" -Ref "TASK-001" -Body "New task"

            $job | Wait-Job -Timeout 15 | Out-Null
            $output = $job | Receive-Job
            $job | Remove-Job -Force

            $msg = $output | ConvertFrom-Json
            $msg.type | Should -Be "task"
        }
    }
}
