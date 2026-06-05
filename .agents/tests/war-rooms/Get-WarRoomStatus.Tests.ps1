# Agent OS — Get-WarRoomStatus Pester Tests

BeforeAll {
    $script:NewWarRoom = Join-Path (Resolve-Path "$PSScriptRoot/../../war-rooms").Path "New-WarRoom.ps1"
    $script:GetStatus = Join-Path (Resolve-Path "$PSScriptRoot/../../war-rooms").Path "Get-WarRoomStatus.ps1"
    $script:agentsDir = Split-Path (Resolve-Path "$PSScriptRoot/../../war-rooms").Path
    . (Join-Path $script:agentsDir "tests" "TestChannelHelpers.ps1")
    $script:PostMessage = New-TestChannelWriter
}

Describe "Get-WarRoomStatus" {
    BeforeEach {
        $script:warRoomsDir = Join-Path $TestDrive "warrooms-$(Get-Random)"
        New-Item -ItemType Directory -Path $script:warRoomsDir -Force | Out-Null
    }

    Context "No rooms" {
        It "returns empty summary when no rooms exist" {
            $result = & $script:GetStatus -WarRoomsDir $script:warRoomsDir -JsonOutput
            $data = $result | ConvertFrom-Json
            $data.summary.total | Should -Be 0
        }
    }

    Context "With rooms" {
        BeforeEach {
            # Create test rooms
            & $script:NewWarRoom -RoomId "room-001" -TaskRef "TASK-001" `
                                 -TaskDescription "First task" -WarRoomsDir $script:warRoomsDir `
                                 -DefinitionOfDone @("Tests pass", "Linted")
            & $script:NewWarRoom -RoomId "room-002" -TaskRef "EPIC-001" `
                                 -TaskDescription "Big feature" -WarRoomsDir $script:warRoomsDir
        }

        It "counts total rooms" {
            $result = & $script:GetStatus -WarRoomsDir $script:warRoomsDir -JsonOutput
            $data = $result | ConvertFrom-Json
            $data.summary.total | Should -Be 2
        }

        It "shows pending rooms" {
            $result = & $script:GetStatus -WarRoomsDir $script:warRoomsDir -JsonOutput
            $data = $result | ConvertFrom-Json
            $data.summary.pending | Should -Be 2
        }

        It "includes room details" {
            $result = & $script:GetStatus -WarRoomsDir $script:warRoomsDir -JsonOutput
            $data = $result | ConvertFrom-Json
            $room1 = $data.rooms | Where-Object { $_.room_id -eq "room-001" }
            $room1.task_ref | Should -Be "TASK-001"
            $room1.status | Should -Be "pending"
            $room1.retries | Should -Be 0
        }

        It "tracks goal counts from config.json" {
            $result = & $script:GetStatus -WarRoomsDir $script:warRoomsDir -JsonOutput
            $data = $result | ConvertFrom-Json
            $room1 = $data.rooms | Where-Object { $_.room_id -eq "room-001" }
            $room1.goals | Should -Be "0/2"
        }

        It "counts messages" {
            # Post an additional message
            $roomDir = Join-Path $script:warRoomsDir "room-001"
            & $script:PostMessage -RoomDir $roomDir -From "engineer" -To "manager" `
                                  -Type "done" -Ref "TASK-001" -Body "Done"

            $result = & $script:GetStatus -WarRoomsDir $script:warRoomsDir -JsonOutput
            $data = $result | ConvertFrom-Json
            $room1 = $data.rooms | Where-Object { $_.room_id -eq "room-001" }
            $room1.messages | Should -Be 1
        }
    }

    Context "Status transitions" {
        BeforeEach {
            & $script:NewWarRoom -RoomId "room-010" -TaskRef "TASK-010" `
                                 -TaskDescription "Status test" -WarRoomsDir $script:warRoomsDir
        }

        It "reflects developing status" {
            $roomDir = Join-Path $script:warRoomsDir "room-010"
            "developing" | Out-File -FilePath (Join-Path $roomDir "status") -NoNewline

            $result = & $script:GetStatus -WarRoomsDir $script:warRoomsDir -JsonOutput
            $data = $result | ConvertFrom-Json
            $data.summary.developing | Should -Be 1
            $data.summary.pending | Should -Be 0
        }

        It "reflects passed status" {
            $roomDir = Join-Path $script:warRoomsDir "room-010"
            "passed" | Out-File -FilePath (Join-Path $roomDir "status") -NoNewline

            $result = & $script:GetStatus -WarRoomsDir $script:warRoomsDir -JsonOutput
            $data = $result | ConvertFrom-Json
            $data.summary.passed | Should -Be 1
        }

        It "reflects failed-final status" {
            $roomDir = Join-Path $script:warRoomsDir "room-010"
            "failed-final" | Out-File -FilePath (Join-Path $roomDir "status") -NoNewline

            $result = & $script:GetStatus -WarRoomsDir $script:warRoomsDir -JsonOutput
            $data = $result | ConvertFrom-Json
            $data.summary.failed | Should -Be 1
        }
    }

    Context "Goal verification" {
        It "shows goal completion when goal-verification.json exists" {
            & $script:NewWarRoom -RoomId "room-020" -TaskRef "TASK-020" `
                                 -TaskDescription "Goal test" -WarRoomsDir $script:warRoomsDir `
                                 -DefinitionOfDone @("Goal A", "Goal B", "Goal C")

            # Write a goal verification report
            $roomDir = Join-Path $script:warRoomsDir "room-020"
            @{
                goals = @(
                    @{ goal = "Goal A"; status = "met"; evidence = "done" }
                    @{ goal = "Goal B"; status = "met"; evidence = "done" }
                    @{ goal = "Goal C"; status = "not_met"; evidence = "missing" }
                )
            } | ConvertTo-Json -Depth 5 | Out-File (Join-Path $roomDir "goal-verification.json") -Encoding utf8

            $result = & $script:GetStatus -WarRoomsDir $script:warRoomsDir -JsonOutput
            $data = $result | ConvertFrom-Json
            $room = $data.rooms | Where-Object { $_.room_id -eq "room-020" }
            $room.goals | Should -Be "2/3"
        }
    }

    Context "ProjectDir option" {
        It "resolves war-rooms from project/.war-rooms" {
            $projectDir = Join-Path $TestDrive "project-$(Get-Random)"
            $wrDir = Join-Path $projectDir ".war-rooms"
            New-Item -ItemType Directory -Path $wrDir -Force | Out-Null

            & $script:NewWarRoom -RoomId "room-100" -TaskRef "TASK-100" `
                                 -TaskDescription "Project test" -WarRoomsDir $wrDir

            $result = & $script:GetStatus -ProjectDir $projectDir -JsonOutput
            $data = $result | ConvertFrom-Json
            $data.summary.total | Should -Be 1
        }
    }
}
