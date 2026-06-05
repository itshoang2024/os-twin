# Agent OS — Read-Messages Pester Tests

BeforeAll {
    . (Join-Path (Resolve-Path "$PSScriptRoot/..").Path "TestChannelHelpers.ps1")
    $script:PostMessage = New-TestChannelWriter
    $script:ReadMessages = Join-Path (Resolve-Path "$PSScriptRoot/../../channel").Path "Read-Messages.ps1"

    # --- Helper: post test messages to a room ---
    function Add-TestMessages {
        param([string]$RoomDir)
        & $script:PostMessage -RoomDir $RoomDir -From "manager" -To "engineer" -Type "task" -Ref "TASK-001" -Body "Implement auth"
        Start-Sleep -Milliseconds 5
        & $script:PostMessage -RoomDir $RoomDir -From "engineer" -To "manager" -Type "done" -Ref "TASK-001" -Body "Auth implemented"
        Start-Sleep -Milliseconds 5
        & $script:PostMessage -RoomDir $RoomDir -From "manager" -To "qa" -Type "review" -Ref "TASK-001" -Body "Please review auth"
        Start-Sleep -Milliseconds 5
        & $script:PostMessage -RoomDir $RoomDir -From "qa" -To "manager" -Type "pass" -Ref "TASK-001" -Body "Looks good"
        Start-Sleep -Milliseconds 5
        & $script:PostMessage -RoomDir $RoomDir -From "manager" -To "engineer" -Type "task" -Ref "TASK-002" -Body "Implement dashboard"
    }
}

Describe "Read-Messages" {
    BeforeEach {
        $script:roomDir = Join-Path $TestDrive "room-$(Get-Random)"
        New-Item -ItemType Directory -Path $script:roomDir -Force | Out-Null
    }

    Context "Empty / Missing channel" {
        It "returns empty JSON array when channel file doesn't exist" {
            $result = & $script:ReadMessages -RoomDir $script:roomDir
            $result | Should -Be '[]'
        }

        It "returns empty PSObject array with -AsObject when channel doesn't exist" {
            $result = & $script:ReadMessages -RoomDir $script:roomDir -AsObject
            $result | Should -BeNullOrEmpty
        }
    }

    Context "Unfiltered reads" {
        BeforeEach {
            Add-TestMessages -RoomDir $script:roomDir
        }

        It "returns all messages as JSON" {
            $result = & $script:ReadMessages -RoomDir $script:roomDir
            $msgs = $result | ConvertFrom-Json
            $msgs.Count | Should -Be 5
        }

        It "returns all messages as objects with -AsObject" {
            $msgs = & $script:ReadMessages -RoomDir $script:roomDir -AsObject
            $msgs.Count | Should -Be 5
        }
    }

    Context "Filter by type" {
        BeforeEach {
            Add-TestMessages -RoomDir $script:roomDir
        }

        It "filters by type 'task'" {
            $msgs = & $script:ReadMessages -RoomDir $script:roomDir -FilterType "task" -AsObject
            $msgs.Count | Should -Be 2
            $msgs | ForEach-Object { $_.type | Should -Be "task" }
        }

        It "filters by type 'done'" {
            $msgs = & $script:ReadMessages -RoomDir $script:roomDir -FilterType "done" -AsObject
            $msgs.Count | Should -Be 1
            $msgs[0].body | Should -Be "Auth implemented"
        }

        It "filters by type 'pass'" {
            $msgs = & $script:ReadMessages -RoomDir $script:roomDir -FilterType "pass" -AsObject
            $msgs.Count | Should -Be 1
        }
    }

    Context "Filter by from" {
        BeforeEach {
            Add-TestMessages -RoomDir $script:roomDir
        }

        It "filters messages from 'manager'" {
            $msgs = & $script:ReadMessages -RoomDir $script:roomDir -FilterFrom "manager" -AsObject
            $msgs.Count | Should -Be 3
            $msgs | ForEach-Object { $_.from | Should -Be "manager" }
        }

        It "filters messages from 'qa'" {
            $msgs = & $script:ReadMessages -RoomDir $script:roomDir -FilterFrom "qa" -AsObject
            $msgs.Count | Should -Be 1
            $msgs[0].type | Should -Be "pass"
        }
    }

    Context "Filter by ref" {
        BeforeEach {
            Add-TestMessages -RoomDir $script:roomDir
        }

        It "filters by TASK-001" {
            $msgs = & $script:ReadMessages -RoomDir $script:roomDir -FilterRef "TASK-001" -AsObject
            $msgs.Count | Should -Be 4
        }

        It "filters by TASK-002" {
            $msgs = & $script:ReadMessages -RoomDir $script:roomDir -FilterRef "TASK-002" -AsObject
            $msgs.Count | Should -Be 1
            $msgs[0].body | Should -Be "Implement dashboard"
        }
    }

    Context "Combined filters" {
        BeforeEach {
            Add-TestMessages -RoomDir $script:roomDir
        }

        It "filters by from=qa and type=pass" {
            $msgs = & $script:ReadMessages -RoomDir $script:roomDir -FilterFrom "qa" -FilterType "pass" -AsObject
            $msgs.Count | Should -Be 1
            $msgs[0].body | Should -Be "Looks good"
        }

        It "returns empty when no messages match combined filter" {
            $msgs = & $script:ReadMessages -RoomDir $script:roomDir -FilterFrom "qa" -FilterType "task" -AsObject
            $msgs | Should -BeNullOrEmpty
        }
    }

    Context "Last N" {
        BeforeEach {
            Add-TestMessages -RoomDir $script:roomDir
        }

        It "returns only the last 1 message" {
            $msgs = & $script:ReadMessages -RoomDir $script:roomDir -Last 1 -AsObject
            $msgs.Count | Should -Be 1
            $msgs[0].ref | Should -Be "TASK-002"
        }

        It "returns last 2 messages" {
            $msgs = & $script:ReadMessages -RoomDir $script:roomDir -Last 2 -AsObject
            $msgs.Count | Should -Be 2
        }

        It "returns all messages when Last exceeds total" {
            $msgs = & $script:ReadMessages -RoomDir $script:roomDir -Last 100 -AsObject
            $msgs.Count | Should -Be 5
        }

        It "combines Last with type filter" {
            $msgs = & $script:ReadMessages -RoomDir $script:roomDir -FilterType "task" -Last 1 -AsObject
            $msgs.Count | Should -Be 1
            $msgs[0].ref | Should -Be "TASK-002"
        }
    }

    Context "After message ID" {
        BeforeEach {
            Add-TestMessages -RoomDir $script:roomDir
        }

        It "returns messages after a specific message ID" {
            # Get the first message ID
            $all = & $script:ReadMessages -RoomDir $script:roomDir -AsObject
            $afterId = $all[0].id

            $msgs = & $script:ReadMessages -RoomDir $script:roomDir -After $afterId -AsObject
            $msgs.Count | Should -Be 4  # All except the first
        }

        It "returns empty when After ID is the last message" {
            $all = & $script:ReadMessages -RoomDir $script:roomDir -AsObject
            $lastId = $all[-1].id

            $msgs = & $script:ReadMessages -RoomDir $script:roomDir -After $lastId -AsObject
            $msgs | Should -BeNullOrEmpty
        }
    }

    Context "Corrupt JSON handling" {
        It "skips corrupt lines and returns valid messages" {
            $channelFile = Join-Path $script:roomDir "channel.jsonl"
            # Write a mix of valid and corrupt lines
            $validMsg = @{ v = 1; id = "test-1"; ts = "2026-01-01T00:00:00Z"; from = "manager"; to = "engineer"; type = "task"; ref = "TASK-001"; body = "valid" } | ConvertTo-Json -Compress
            @(
                $validMsg
                "this is not valid json {"
                ""
                $validMsg.Replace("test-1", "test-2")
            ) | Out-File $channelFile -Encoding utf8

            $msgs = & $script:ReadMessages -RoomDir $script:roomDir -AsObject 3>&1
            # Should get 2 valid messages (warnings go to warning stream)
            ($msgs | Where-Object { $_ -is [PSObject] -and $_.id }).Count | Should -Be 2
        }
    }

    Context "JSON output format" {
        It "returns valid JSON array for single message" {
            & $script:PostMessage -RoomDir $script:roomDir -From "manager" -To "engineer" -Type "task" -Ref "TASK-001" -Body "Single"
            $result = & $script:ReadMessages -RoomDir $script:roomDir
            $result | Should -Match '^\['    # Must start with [
            $result | Should -Match '\]$'    # Must end with ]
            $parsed = $result | ConvertFrom-Json
            $parsed.Count | Should -Be 1
        }

        It "returns valid JSON array for multiple messages" {
            & $script:PostMessage -RoomDir $script:roomDir -From "manager" -To "engineer" -Type "task" -Ref "TASK-001" -Body "First"
            & $script:PostMessage -RoomDir $script:roomDir -From "engineer" -To "manager" -Type "done" -Ref "TASK-001" -Body "Second"
            $result = & $script:ReadMessages -RoomDir $script:roomDir
            $parsed = $result | ConvertFrom-Json
            $parsed.Count | Should -Be 2
        }
    }
}
