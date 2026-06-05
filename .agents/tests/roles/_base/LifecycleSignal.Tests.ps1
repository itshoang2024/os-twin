# Agent OS - LifecycleSignal.psm1 tests

BeforeAll {
    $script:modulePath = Join-Path (Resolve-Path "$PSScriptRoot/../../../roles/_base").Path "LifecycleSignal.psm1"
    Import-Module $script:modulePath -Force
}

Describe "LifecycleSignal protocol compatibility" {
    BeforeEach {
        $script:roomDir = Join-Path $TestDrive "room-lifecycle-signal-$(Get-Random)"
        New-Item -ItemType Directory -Path $script:roomDir -Force | Out-Null
        "review" | Out-File (Join-Path $script:roomDir "status") -Encoding utf8 -NoNewline
    }

    It "prefers done when lifecycle accepts both done and pass" {
        @{
            version = 2
            states = @{
                review = @{
                    role = "qa"
                    type = "review"
                    signals = [ordered]@{
                        done = @{ target = "passed" }
                        pass = @{ target = "passed" }
                        fail = @{ target = "optimize" }
                    }
                }
            }
        } | ConvertTo-Json -Depth 8 | Out-File (Join-Path $script:roomDir "lifecycle.json") -Encoding utf8

        Get-PreferredLifecycleSuccessSignal -RoomDir $script:roomDir | Should -Be "done"
        Convert-VerdictToLifecycleSignal -Verdict "DONE" -DefaultSuccessSignal (Get-PreferredLifecycleSuccessSignal -RoomDir $script:roomDir) | Should -Be "done"
        Convert-VerdictToLifecycleSignal -Verdict "PASS" -DefaultSuccessSignal (Get-PreferredLifecycleSuccessSignal -RoomDir $script:roomDir) | Should -Be "done"
    }

    It "falls back to pass when a legacy lifecycle only accepts pass" {
        @{
            version = 2
            states = @{
                review = @{
                    role = "qa"
                    type = "review"
                    signals = [ordered]@{
                        pass = @{ target = "passed" }
                        fail = @{ target = "optimize" }
                    }
                }
            }
        } | ConvertTo-Json -Depth 8 | Out-File (Join-Path $script:roomDir "lifecycle.json") -Encoding utf8

        $successSignal = Get-PreferredLifecycleSuccessSignal -RoomDir $script:roomDir
        $successSignal | Should -Be "pass"
        Convert-VerdictToLifecycleSignal -Verdict "DONE" -DefaultSuccessSignal $successSignal | Should -Be "pass"
        Convert-VerdictToLifecycleSignal -Verdict "PASS" -DefaultSuccessSignal $successSignal | Should -Be "pass"
    }

    It "extracts the final verdict from output and keeps legacy PASS parseable" {
        $output = "Earlier noise`nVERDICT: FAIL`n`nFinal decision:`nVERDICT: DONE"
        Get-AgentVerdict -Output $output | Should -Be "DONE"
        Get-AgentVerdict -Output "VERDICT: PASS" | Should -Be "PASS"
    }

    It "detects fresh lifecycle signals and ignores stale ones" {
        $oldEpoch = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - 60
        $futureEpoch = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() + 60
        "review" | Out-File (Join-Path $script:roomDir "status") -Encoding utf8 -NoNewline

        Write-LifecycleSignal -RoomDir $script:roomDir -FromRole "qa" -Type "done" -Ref "TASK-1" -Body "VERDICT: DONE" | Out-Null
        $oldEpoch.ToString() | Out-File (Join-Path $script:roomDir "state_changed_at") -Encoding utf8 -NoNewline
        Test-FreshLifecycleSignal -RoomDir $script:roomDir -FromRole "qa" -Type "done" -Ref "TASK-1" | Should -BeTrue

        $futureEpoch.ToString() | Out-File (Join-Path $script:roomDir "state_changed_at") -Encoding utf8 -NoNewline
        Test-FreshLifecycleSignal -RoomDir $script:roomDir -FromRole "qa" -Type "done" -Ref "TASK-1" | Should -BeFalse
    }
}
