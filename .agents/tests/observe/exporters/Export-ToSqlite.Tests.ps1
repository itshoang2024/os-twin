# Agent OS — Export-ToSqlite Pester Tests

BeforeAll {
    $script:ExportSqlite = Join-Path (Resolve-Path "$PSScriptRoot/../../../observe/exporters").Path "Export-ToSqlite.ps1"
    $script:agentsDir = (Resolve-Path (Join-Path (Resolve-Path "$PSScriptRoot/../../../observe/exporters").Path ".." "..")).Path
    $script:NewWarRoom = Join-Path $script:agentsDir "war-rooms" "New-WarRoom.ps1"
    . (Join-Path $script:agentsDir "tests" "TestChannelHelpers.ps1")
    $script:PostMessage = New-TestChannelWriter

    # Check if python3 is available
    $script:hasPython = $false
    try {
        $null = & python3 --version 2>&1
        $script:hasPython = ($LASTEXITCODE -eq 0)
    }
    catch { }
}

Describe "Export-ToSqlite" {
    BeforeEach {
        $script:logDir = Join-Path $TestDrive "logs-$(Get-Random)"
        $script:warRoomsDir = Join-Path $TestDrive "wr-sql-$(Get-Random)"
        $script:dbFile = Join-Path $TestDrive "test-$(Get-Random).db"
        New-Item -ItemType Directory -Path $script:logDir -Force | Out-Null
        New-Item -ItemType Directory -Path $script:warRoomsDir -Force | Out-Null
    }

    Context "Basic export" -Skip:(-not $script:hasPython) {
        It "creates the SQLite database file" {
            # Create some trace data
            @(
                '{"ts":"2026-01-01T00:00:00Z","level":"INFO","message":"test event","trace_id":"abc123","span_id":"s1"}'
                '{"ts":"2026-01-01T00:00:01Z","level":"WARN","message":"warning","trace_id":"abc123","span_id":"s2"}'
            ) | Out-File (Join-Path $script:logDir "trace.jsonl") -Encoding utf8

            $result = & $script:ExportSqlite -LogDir $script:logDir `
                        -WarRoomsDir $script:warRoomsDir -OutputDb $script:dbFile

            Test-Path $script:dbFile | Should -BeTrue
            $result.imported.events | Should -Be 2
        }

        It "imports war-room channels" {
            & $script:NewWarRoom -RoomId "room-001" -TaskRef "TASK-001" `
                -TaskDescription "Test" -WarRoomsDir $script:warRoomsDir

            $roomDir = Join-Path $script:warRoomsDir "room-001"
            & $script:PostMessage -RoomDir $roomDir -From "engineer" -To "manager" `
                -Type "done" -Ref "TASK-001" -Body "Done!"

            $result = & $script:ExportSqlite -LogDir $script:logDir `
                        -WarRoomsDir $script:warRoomsDir -OutputDb $script:dbFile

            $result.imported.messages | Should -BeGreaterThan 0
            $result.imported.rooms | Should -Be 1
        }

        It "imports room config and status" {
            & $script:NewWarRoom -RoomId "room-002" -TaskRef "EPIC-001" `
                -TaskDescription "Big feature" -WarRoomsDir $script:warRoomsDir `
                -DefinitionOfDone @("Goal A", "Goal B")

            $result = & $script:ExportSqlite -LogDir $script:logDir `
                        -WarRoomsDir $script:warRoomsDir -OutputDb $script:dbFile

            $result.imported.rooms | Should -Be 1
        }

        It "lists expected tables" {
            # Create minimal data
            "" | Out-File (Join-Path $script:logDir "trace.jsonl") -Encoding utf8

            $result = & $script:ExportSqlite -LogDir $script:logDir `
                        -WarRoomsDir $script:warRoomsDir -OutputDb $script:dbFile

            $result.tables | Should -Contain "events"
            $result.tables | Should -Contain "spans"
            $result.tables | Should -Contain "messages"
            $result.tables | Should -Contain "rooms"
        }
    }

    Context "Append mode" -Skip:(-not $script:hasPython) {
        It "appends to existing database" {
            # First export
            '{"ts":"2026-01-01T00:00:00Z","level":"INFO","message":"first"}' |
                Out-File (Join-Path $script:logDir "trace.jsonl") -Encoding utf8

            & $script:ExportSqlite -LogDir $script:logDir `
                -WarRoomsDir $script:warRoomsDir -OutputDb $script:dbFile

            # Second export (append)
            '{"ts":"2026-01-01T00:00:01Z","level":"INFO","message":"second"}' |
                Out-File -Append (Join-Path $script:logDir "trace.jsonl") -Encoding utf8

            $result = & $script:ExportSqlite -LogDir $script:logDir `
                        -WarRoomsDir $script:warRoomsDir -OutputDb $script:dbFile -Append

            $result.imported.events | Should -Be 2
        }
    }

    Context "Empty data" -Skip:(-not $script:hasPython) {
        It "handles empty log directory gracefully" {
            $result = & $script:ExportSqlite -LogDir $script:logDir `
                        -WarRoomsDir $script:warRoomsDir -OutputDb $script:dbFile

            Test-Path $script:dbFile | Should -BeTrue
            $result.imported.events | Should -Be 0
        }
    }

    Context "Trace reports" -Skip:(-not $script:hasPython) {
        It "imports spans from trace report files" {
            @{
                trace_id = "tr-001"
                name     = "test-trace"
                spans    = @(
                    @{
                        span_id        = "sp-001"
                        parent_span_id = ""
                        name           = "engineer-run"
                        status         = "ok"
                        duration_ms    = 500
                        attributes     = @{ role = "engineer" }
                        event_count    = 3
                    }
                )
            } | ConvertTo-Json -Depth 5 |
                Out-File (Join-Path $script:logDir "trace-tr-001.json") -Encoding utf8

            $result = & $script:ExportSqlite -LogDir $script:logDir `
                        -WarRoomsDir $script:warRoomsDir -OutputDb $script:dbFile

            $result.imported.spans | Should -Be 1
        }
    }
}
