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
        "ERROR" { return "error" }
        "REJECT" { return "fail" }
        default { return "" }
    }
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

    foreach ($line in [System.IO.File]::ReadLines($channelFile)) {
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

    ($msg | ConvertTo-Json -Compress -Depth 8) |
        Out-File -FilePath $channelFile -Encoding utf8 -Append

    return [pscustomobject]$msg
}

Export-ModuleMember -Function Get-AgentVerdict, Convert-VerdictToLifecycleSignal, Get-PreferredLifecycleSuccessSignal, Test-FreshLifecycleSignal, Write-LifecycleSignal
