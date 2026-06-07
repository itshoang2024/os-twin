# Agent OS - Start-DynamicRole Pester Tests

BeforeAll {
    $script:StartDynamicRole = Join-Path (Resolve-Path "$PSScriptRoot/../../../roles/_base").Path "Start-DynamicRole.ps1"
    $script:agentsDir = (Resolve-Path (Join-Path (Resolve-Path "$PSScriptRoot/../../../roles/_base").Path ".." "..")).Path
}

Describe "Start-DynamicRole" {
    BeforeEach {
        $script:roomDir = Join-Path $TestDrive "room-dynamic-$(Get-Random)"
        New-Item -ItemType Directory -Path $script:roomDir -Force | Out-Null
        New-Item -ItemType Directory -Path (Join-Path $script:roomDir "pids") -Force | Out-Null
        New-Item -ItemType Directory -Path (Join-Path $script:roomDir "artifacts") -Force | Out-Null
        New-Item -ItemType File -Path (Join-Path $script:roomDir "channel.jsonl") -Force | Out-Null

        "TASK-001" | Out-File (Join-Path $script:roomDir "task-ref") -Encoding utf8 -NoNewline
        "developing" | Out-File (Join-Path $script:roomDir "status") -Encoding utf8 -NoNewline
        @"
# TASK-001

Implement dynamic role behavior.

## Working Directory
$TestDrive
"@ | Out-File (Join-Path $script:roomDir "brief.md") -Encoding utf8

        @{
            assignment = @{
                assigned_role = "custom-role"
            }
            working_dir = $TestDrive
        } | ConvertTo-Json -Depth 5 | Out-File (Join-Path $script:roomDir "config.json") -Encoding utf8

        @{
            role        = "custom-role"
            instance_id = "001"
            status      = "pending"
        } | ConvertTo-Json -Depth 5 | Out-File (Join-Path $script:roomDir "custom-role_001.json") -Encoding utf8

        $script:readMessages = Join-Path $TestDrive "read-empty.ps1"
        @'
[CmdletBinding()]
param(
    [string]$RoomDir,
    $FilterType,
    [int]$Last,
    [switch]$AsObject
)
@()
'@ | Out-File $script:readMessages -Encoding ascii

        $script:roleDef = Join-Path $TestDrive "role-def.ps1"
        @'
[CmdletBinding()]
param([string]$RolePath, [string]$RoleName)
[pscustomobject]@{
    Model = "test-model"
    Timeout = 10
    InstanceType = "worker"
}
'@ | Out-File $script:roleDef -Encoding ascii

        $script:buildPrompt = Join-Path $TestDrive "build-prompt.ps1"
        @'
[CmdletBinding()]
param([string]$RoomDir, [string]$RolePath, [string]$RoleName)
"dynamic prompt"
'@ | Out-File $script:buildPrompt -Encoding ascii
    }

    It "marks role config failed without posting channel error when agent exits non-zero" {
        $invokeAgent = Join-Path $TestDrive "invoke-failed.ps1"
        @'
[CmdletBinding()]
param(
    [string]$RoomDir,
    [string]$RoleName,
    [string]$Prompt,
    [int]$TimeoutSeconds,
    [string]$WorkingDir
)
[pscustomobject]@{
    ExitCode = 7
    Output = "dynamic failed"
    OutputFile = $null
    PidFile = $null
    TimedOut = $false
}
'@ | Out-File $invokeAgent -Encoding ascii

        & pwsh -NoProfile -File $script:StartDynamicRole `
            -RoomDir $script:roomDir `
            -RoleName "custom-role" `
            -AgentsDir $script:agentsDir `
            -OverrideInvokeAgent $invokeAgent `
            -OverrideReadMessages $script:readMessages `
            -OverrideGetRoleDef $script:roleDef `
            -OverrideBuildSystemPrompt $script:buildPrompt `
            -TimeoutSeconds 10 2>&1 | Out-Null
        $LASTEXITCODE | Should -Be 7

        $roleConfig = Get-Content (Join-Path $script:roomDir "custom-role_001.json") -Raw | ConvertFrom-Json
        $roleConfig.status | Should -Be "failed"
        $roleConfig.status_updated_epoch | Should -Not -BeNullOrEmpty

        $channelRaw = Get-Content (Join-Path $script:roomDir "channel.jsonl") -Raw
        $channelRaw | Should -Not -Match '"(msg_type|type)"\s*:\s*"error"'
    }

    It "injects the latest manager channel message into the next agent prompt" {
        $managerDecision = [pscustomobject]@{
            id   = 'msg-manager-1'
            ts   = '2026-06-07T18:40:00Z'
            from = 'manager'
            to   = 'qa'
            type = 'done'
            body = 'Manager decision: escalation resolved. Resume review with this clarification.'
        } | ConvertTo-Json -Compress
        $olderEngineer = [pscustomobject]@{
            id   = 'msg-engineer-1'
            ts   = '2026-06-07T18:39:00Z'
            from = 'engineer'
            to   = 'qa'
            type = 'done'
            body = 'Engineer done message.'
        } | ConvertTo-Json -Compress
        @($olderEngineer, $managerDecision) | Set-Content -Path (Join-Path $script:roomDir 'channel.jsonl') -Encoding utf8

        $promptCapture = Join-Path $TestDrive 'captured-prompt.txt'
        $invokeAgent = Join-Path $TestDrive "invoke-capture-prompt.ps1"
        @"
[CmdletBinding()]
param(
    [string]`$RoomDir,
    [string]`$RoleName,
    [string]`$Prompt,
    [int]`$TimeoutSeconds,
    [string]`$WorkingDir
)
`$Prompt | Out-File -FilePath '$promptCapture' -Encoding utf8 -Force
[pscustomobject]@{
    ExitCode = 0
    Output = 'ok'
    OutputFile = `$null
    PidFile = `$null
    TimedOut = `$false
}
"@ | Out-File $invokeAgent -Encoding ascii

        & pwsh -NoProfile -File $script:StartDynamicRole `
            -RoomDir $script:roomDir `
            -RoleName "custom-role" `
            -AgentsDir $script:agentsDir `
            -OverrideInvokeAgent $invokeAgent `
            -OverrideReadMessages $script:readMessages `
            -OverrideGetRoleDef $script:roleDef `
            -OverrideBuildSystemPrompt $script:buildPrompt `
            -TimeoutSeconds 10 2>&1 | Out-Null
        $LASTEXITCODE | Should -Be 0

        $capturedPrompt = Get-Content $promptCapture -Raw
        $capturedPrompt | Should -Match '## Latest Manager Handoff'
        $capturedPrompt | Should -Match 'Type: done'
        $capturedPrompt | Should -Match 'To: qa'
        $capturedPrompt | Should -Match 'Manager decision: escalation resolved'
    }
}
