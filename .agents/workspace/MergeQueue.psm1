Set-StrictMode -Version Latest

$gitWorkspaceModule = Join-Path $PSScriptRoot 'GitWorkspace.psm1'
if (Test-Path $gitWorkspaceModule) {
    Import-Module (Resolve-Path $gitWorkspaceModule).Path -Force
}

function Invoke-RoomWorkspaceMerge {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$RoomDir,
        [Parameter(Mandatory)][string]$WarRoomsDir
    )

    return (Complete-RoomWorkspaceMerge -RoomDir $RoomDir -WarRoomsDir $WarRoomsDir)
}

Export-ModuleMember -Function Invoke-RoomWorkspaceMerge
