function Get-AgentVerdict {
    [CmdletBinding()]
    param([AllowEmptyString()][AllowNull()][string]$Output)

    if ([string]::IsNullOrWhiteSpace($Output)) { return "" }

    $lines = $Output -split "`r?`n"
    for ($i = $lines.Count - 1; $i -ge 0; $i--) {
        if ($lines[$i] -match '^\s*\*{0,2}\s*VERDICT:?\s*(DONE|PASS|FAIL|ESCALATE|BLOCKED|ERROR|REJECT)\b') {
            return $Matches[1].ToUpperInvariant()
        }
    }

    $matches = [regex]::Matches($Output, 'VERDICT:?\s*(DONE|PASS|FAIL|ESCALATE|BLOCKED|ERROR|REJECT)\b', 'IgnoreCase')
    if ($matches.Count -gt 0) {
        return $matches[$matches.Count - 1].Groups[1].Value.ToUpperInvariant()
    }

    return ""
}

function Convert-VerdictToLifecycleSignal {
    [CmdletBinding()]
    param(
        [AllowEmptyString()][AllowNull()][string]$Verdict,
        [string]$DefaultSuccessSignal = "done"
    )

    if ([string]::IsNullOrWhiteSpace($Verdict)) { return "" }

    switch ($Verdict.ToUpperInvariant()) {
        "DONE" { return $DefaultSuccessSignal }
        "PASS" { return $DefaultSuccessSignal }
        "FAIL" { return "fail" }
        "ESCALATE" { return "escalate" }
        "BLOCKED" { return "escalate" }
        "ERROR" { return "" }
        "REJECT" { return "fail" }
        default { return "" }
    }
}

function Set-LifecycleRoleStatus {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$RoomDir,
        [Parameter(Mandatory)][string]$RoleName,
        [Parameter(Mandatory)][ValidateSet("pending", "active", "completed", "failed")][string]$Status,
        [AllowEmptyString()][string]$ConfigFile = ""
    )

    $targetFile = $ConfigFile
    if (-not $targetFile) {
        $baseRole = $RoleName -replace ':.*$', ''
        $roleConfigs = Get-ChildItem -Path $RoomDir -Filter "${baseRole}_*.json" -ErrorAction SilentlyContinue |
            Sort-Object Name -Descending
        if ($roleConfigs) { $targetFile = $roleConfigs[0].FullName }
    }
    if (-not $targetFile -or -not (Test-Path $targetFile)) { return $null }

    $cfg = Get-Content $targetFile -Raw | ConvertFrom-Json
    $epoch = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    $iso = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    $cfg.status = $Status
    $cfg | Add-Member -NotePropertyName "status_updated_epoch" -NotePropertyValue $epoch -Force
    $cfg | Add-Member -NotePropertyName "status_updated_at" -NotePropertyValue $iso -Force
    $cfg | ConvertTo-Json -Depth 5 | Out-File -FilePath $targetFile -Encoding utf8
    return $targetFile
}

function Get-PreferredLifecycleSuccessSignal {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$RoomDir,
        [AllowEmptyString()][string]$StateName = "",
        [string]$DefaultSignal = "done"
    )

    $preferredSignals = [System.Collections.Generic.List[string]]::new()
    foreach ($candidate in @($DefaultSignal, "done", "pass")) {
        if ($candidate -and -not $preferredSignals.Contains($candidate)) {
            $preferredSignals.Add($candidate)
        }
    }

    if (-not $StateName) {
        $statusFile = Join-Path $RoomDir "status"
        if (Test-Path $statusFile) {
            try { $StateName = (Get-Content $statusFile -Raw).Trim() } catch { $StateName = "" }
        }
    }

    $lifecycleFile = Join-Path $RoomDir "lifecycle.json"
    if ($StateName -and (Test-Path $lifecycleFile)) {
        try {
            $lifecycle = Get-Content $lifecycleFile -Raw | ConvertFrom-Json
            $stateDef = if ($lifecycle -and $lifecycle.states -and $lifecycle.states.$StateName) {
                $lifecycle.states.$StateName
            } else { $null }

            $signalNames = @()
            if ($stateDef -and $stateDef.signals) {
                $signalNames = @($stateDef.signals.PSObject.Properties.Name)
            } elseif ($stateDef -and $stateDef.transitions) {
                $signalNames = @($stateDef.transitions.PSObject.Properties.Name)
            }

            foreach ($candidate in $preferredSignals) {
                if ($signalNames -contains $candidate) { return $candidate }
            }
        }
        catch { }
    }

    return $DefaultSignal
}

function Convert-ChannelTimestampToEpoch {
    [CmdletBinding()]
    param($Timestamp)

    if (-not $Timestamp) { return 0 }
    if ($Timestamp -is [datetime]) {
        return [long]([DateTimeOffset]::new($Timestamp.ToUniversalTime()).ToUnixTimeSeconds())
    }
    if ("$Timestamp" -match '^\d+$') { return [long]"$Timestamp" }

    try {
        return [long]([DateTimeOffset]::new([datetime]::Parse("$Timestamp").ToUniversalTime()).ToUnixTimeSeconds())
    }
    catch { return 0 }
}

function Test-FreshLifecycleSignal {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$RoomDir,
        [Parameter(Mandatory)][string]$FromRole,
        [Parameter(Mandatory)][string]$Type,
        [Parameter(Mandatory)][string]$Ref
    )

    $channelFile = Join-Path $RoomDir "channel.jsonl"
    if (-not (Test-Path $channelFile)) { return $false }

    $changedAt = 0
    $changedFile = Join-Path $RoomDir "state_changed_at"
    if (Test-Path $changedFile) {
        try { $changedAt = [long](Get-Content $changedFile -Raw).Trim() } catch { $changedAt = 0 }
    }

    foreach ($line in [System.IO.File]::ReadAllLines($channelFile)) {
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        try { $msg = $line | ConvertFrom-Json } catch { continue }

        $senderBase = "$($msg.from)" -replace ':.*$', ''
        if ($senderBase -ne $FromRole) { continue }
        if ($msg.type -ne $Type) { continue }
        if ($Ref -and $msg.ref -ne $Ref) { continue }

        $msgTs = Convert-ChannelTimestampToEpoch -Timestamp $msg.ts
        if ($msgTs -ge $changedAt) { return $true }
    }

    return $false
}

function Write-LifecycleSignalEvent {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$RoomDir,
        [Parameter(Mandatory)]$Message,
        [Parameter(Mandatory)][string]$FromRole,
        [Parameter(Mandatory)][string]$Type,
        [Parameter(Mandatory)][string]$Ref,
        [string]$ToRole = 'manager'
    )

    $configPath = Join-Path $RoomDir 'config.json'
    if (-not (Test-Path $configPath)) { return $null }

    try {
        $cfg = Get-Content $configPath -Raw | ConvertFrom-Json
        if (-not ($cfg.PSObject.Properties.Name -contains 'plan_id') -or [string]::IsNullOrWhiteSpace([string]$cfg.plan_id)) { return $null }

        $agentsDir = (Resolve-Path (Join-Path $PSScriptRoot '..' '..')).Path
        $eventsModule = Join-Path $agentsDir 'events' 'OrchestrationEvents.psm1'
        if (-not (Get-Command Write-OrchestrationEvent -ErrorAction SilentlyContinue) -and (Test-Path $eventsModule)) {
            Import-Module (Resolve-Path $eventsModule).Path -Force
        }
        if (-not (Get-Command Write-OrchestrationEvent -ErrorAction SilentlyContinue)) { return $null }

        $runId = if ($cfg.PSObject.Properties.Name -contains 'run_id' -and $cfg.run_id) { "$($cfg.run_id)" } elseif ($env:OSTWIN_RUN_ID) { $env:OSTWIN_RUN_ID } else { 'run_legacy' }
        $eventsPath = if ($cfg.PSObject.Properties.Name -contains 'events_path' -and $cfg.events_path) { "$($cfg.events_path)" } else { '' }
        $status = if (Test-Path (Join-Path $RoomDir 'status')) { (Get-Content (Join-Path $RoomDir 'status') -Raw).Trim() } else { '' }
        $event = [ordered]@{
            event_type = 'lifecycle.signal.posted'
            plan_id    = "$($cfg.plan_id)"
            run_id     = $runId
            room_id    = if ($cfg.PSObject.Properties.Name -contains 'room_id') { "$($cfg.room_id)" } else { Split-Path $RoomDir -Leaf }
            epic_ref   = if ($cfg.PSObject.Properties.Name -contains 'task_ref') { "$($cfg.task_ref)" } else { $Ref }
            role       = ($FromRole -replace ':.*$', '')
            state      = $status
            summary    = "Lifecycle signal '$Type' posted for $Ref."
            payload    = [ordered]@{
                message_id = $Message['id']
                from       = $FromRole
                to         = $ToRole
                type       = $Type
                ref        = $Ref
            }
        }
        return (Write-OrchestrationEvent -EventsPath $eventsPath -Event $event)
    } catch {
        throw "Failed to emit lifecycle signal event before channel append: $($_.Exception.Message)"
    }
}

function Write-LifecycleSignal {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$RoomDir,
        [Parameter(Mandatory)][string]$FromRole,
        [Parameter(Mandatory)][string]$Type,
        [Parameter(Mandatory)][string]$Ref,
        [string]$ToRole = "manager",
        [AllowEmptyString()][string]$Body = "",
        [switch]$SkipIfFresh
    )

    if ($SkipIfFresh -and (Test-FreshLifecycleSignal -RoomDir $RoomDir -FromRole $FromRole -Type $Type -Ref $Ref)) {
        return $null
    }

    if (-not (Test-Path $RoomDir)) {
        New-Item -ItemType Directory -Path $RoomDir -Force | Out-Null
    }

    $channelFile = Join-Path $RoomDir "channel.jsonl"
    $msg = [ordered]@{
        v    = 1
        id   = "$FromRole-$Type-$([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds())-$PID"
        ts   = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
        from = $FromRole
        to   = $ToRole
        type = $Type
        ref  = $Ref
        body = $Body
    }

    $event = Write-LifecycleSignalEvent -RoomDir $RoomDir -Message $msg -FromRole $FromRole -Type $Type -Ref $Ref -ToRole $ToRole
    if ($event -and ($event.PSObject.Properties.Name -contains 'event_id')) {
        $msg['event_id'] = $event.event_id
    }

    $line = ($msg | ConvertTo-Json -Compress -Depth 8) + [Environment]::NewLine
    [System.IO.File]::AppendAllText($channelFile, $line, [System.Text.Encoding]::UTF8)

    return [pscustomobject]$msg
}

Export-ModuleMember -Function Get-AgentVerdict, Convert-VerdictToLifecycleSignal, Get-PreferredLifecycleSuccessSignal, Set-LifecycleRoleStatus, Test-FreshLifecycleSignal, Write-LifecycleSignal
