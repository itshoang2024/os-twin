# Agent OS — Update-Progress Pester Tests

BeforeAll {
    $script:UpdateProgress = Join-Path (Resolve-Path "$PSScriptRoot/../../plan").Path "Update-Progress.ps1"
    $script:agentsDir = (Resolve-Path (Join-Path (Resolve-Path "$PSScriptRoot/../../plan").Path "..")).Path
    $script:NewWarRoom = Join-Path $script:agentsDir "war-rooms" "New-WarRoom.ps1"
    $script:BuildDag = Join-Path (Resolve-Path "$PSScriptRoot/../../plan").Path "Build-DependencyGraph.ps1"
}

Describe "Update-Progress" {
    BeforeEach {
        $script:warRoomsDir = Join-Path $TestDrive "warrooms-$(Get-Random)"
        New-Item -ItemType Directory -Path $script:warRoomsDir -Force | Out-Null
    }

    Context "Empty war-rooms" {
        It "creates progress.json with total=0" {
            & $script:UpdateProgress -WarRoomsDir $script:warRoomsDir *>&1 | Out-Null

            $progressFile = Join-Path $script:warRoomsDir "progress.json"
            Test-Path $progressFile | Should -Be $true

            $data = Get-Content $progressFile -Raw | ConvertFrom-Json
            $data.total | Should -Be 0
            $data.pct_complete | Should -Be 0
        }

        It "creates PROGRESS.md" {
            & $script:UpdateProgress -WarRoomsDir $script:warRoomsDir *>&1 | Out-Null

            $mdFile = Join-Path $script:warRoomsDir "PROGRESS.md"
            Test-Path $mdFile | Should -Be $true
        }
    }

    Context "Mixed statuses" {
        BeforeEach {
            # Create 4 rooms with various statuses
            & $script:NewWarRoom -RoomId "room-001" -TaskRef "TASK-001" `
                                 -TaskDescription "T1" -WarRoomsDir $script:warRoomsDir
            & $script:NewWarRoom -RoomId "room-002" -TaskRef "TASK-002" `
                                 -TaskDescription "T2" -WarRoomsDir $script:warRoomsDir
            & $script:NewWarRoom -RoomId "room-003" -TaskRef "TASK-003" `
                                 -TaskDescription "T3" -WarRoomsDir $script:warRoomsDir
            & $script:NewWarRoom -RoomId "room-004" -TaskRef "TASK-004" `
                                 -TaskDescription "T4" -WarRoomsDir $script:warRoomsDir

            "done" | Out-File -FilePath (Join-Path $script:warRoomsDir "room-001" "status") -NoNewline
            "failed" | Out-File -FilePath (Join-Path $script:warRoomsDir "room-002" "status") -NoNewline
            "blocked" | Out-File -FilePath (Join-Path $script:warRoomsDir "room-003" "status") -NoNewline
            # room-004 stays pending
        }

        It "counts statuses correctly" {
            & $script:UpdateProgress -WarRoomsDir $script:warRoomsDir *>&1 | Out-Null

            $data = Get-Content (Join-Path $script:warRoomsDir "progress.json") -Raw | ConvertFrom-Json
            $data.total | Should -Be 4
            $data.done | Should -Be 1
            $data.passed | Should -Be 1
            $data.failed | Should -Be 1
            $data.blocked | Should -Be 1
            $data.pending | Should -Be 1
            $data.pct_complete | Should -Be 25
        }

        It "PROGRESS.md contains blocked room" {
            & $script:UpdateProgress -WarRoomsDir $script:warRoomsDir *>&1 | Out-Null

            $md = Get-Content (Join-Path $script:warRoomsDir "PROGRESS.md") -Raw
            $md | Should -Match "TASK-003"
            $md | Should -Match "blocked"
        }

        It "PROGRESS.md contains failed room" {
            & $script:UpdateProgress -WarRoomsDir $script:warRoomsDir *>&1 | Out-Null

            $md = Get-Content (Join-Path $script:warRoomsDir "PROGRESS.md") -Raw
            $md | Should -Match "TASK-002"
            $md | Should -Match "failed"
        }
    }

    Context "Critical path progress" {
        It "reads DAG.json for critical path when present" {
            & $script:NewWarRoom -RoomId "room-001" -TaskRef "TASK-001" `
                                 -TaskDescription "T1" -WarRoomsDir $script:warRoomsDir
            & $script:NewWarRoom -RoomId "room-002" -TaskRef "TASK-002" `
                                 -TaskDescription "T2" -WarRoomsDir $script:warRoomsDir `
                                 -DependsOn @("TASK-001")

            "done" | Out-File -FilePath (Join-Path $script:warRoomsDir "room-001" "status") -NoNewline

            # Build DAG
            & $script:BuildDag -WarRoomsDir $script:warRoomsDir | Out-Null

            & $script:UpdateProgress -WarRoomsDir $script:warRoomsDir *>&1 | Out-Null

            $data = Get-Content (Join-Path $script:warRoomsDir "progress.json") -Raw | ConvertFrom-Json
            $data.critical_path | Should -Be "1/2"
        }
    }

    Context "All done" {
        It "shows 100% complete" {
            & $script:NewWarRoom -RoomId "room-001" -TaskRef "TASK-001" `
                                 -TaskDescription "T1" -WarRoomsDir $script:warRoomsDir
            "done" | Out-File -FilePath (Join-Path $script:warRoomsDir "room-001" "status") -NoNewline

            & $script:UpdateProgress -WarRoomsDir $script:warRoomsDir *>&1 | Out-Null

            $data = Get-Content (Join-Path $script:warRoomsDir "progress.json") -Raw | ConvertFrom-Json
            $data.done | Should -Be 1
            $data.pct_complete | Should -Be 100
        }
    }
}
