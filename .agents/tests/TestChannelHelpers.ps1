function Write-TestChannelMessage {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$RoomDir,
        [Parameter(Mandatory)][string]$From,
        [Parameter(Mandatory)][string]$To,
        [Parameter(Mandatory)][string]$Type,
        [Parameter(Mandatory)][string]$Ref,
        [AllowEmptyString()][string]$Body = ''
    )

    if (-not (Test-Path $RoomDir)) {
        New-Item -ItemType Directory -Path $RoomDir -Force | Out-Null
    }

    $channelFile = Join-Path $RoomDir "channel.jsonl"
    $msgId = "$From-$Type-$([guid]::NewGuid().ToString('N'))"
    $msg = [ordered]@{
        v    = 1
        id   = $msgId
        ts   = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
        from = $From
        to   = $To
        type = $Type
        ref  = $Ref
        body = $Body
    }

    ($msg | ConvertTo-Json -Compress -Depth 8) |
        Out-File -FilePath $channelFile -Encoding utf8 -Append

    return $msgId
}

function New-TestChannelWriter {
    return {
        param(
            [string]$RoomDir,
            [string]$From,
            [string]$To,
            [string]$Type,
            [string]$Ref,
            [AllowEmptyString()][string]$Body = ''
        )
        Write-TestChannelMessage -RoomDir $RoomDir -From $From -To $To -Type $Type -Ref $Ref -Body $Body
    }
}
