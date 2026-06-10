Set-StrictMode -Version Latest

$gitWorkspaceModule = Join-Path $PSScriptRoot 'GitWorkspace.psm1'
if (Test-Path $gitWorkspaceModule) {
    Import-Module (Resolve-Path $gitWorkspaceModule).Path -Force -DisableNameChecking
}

function Invoke-RoomWorkspaceMerge {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$RoomDir,
        [Parameter(Mandatory)][string]$WarRoomsDir
    )

    return (Complete-RoomWorkspaceMerge -RoomDir $RoomDir -WarRoomsDir $WarRoomsDir)
}

function Invoke-PlanWorkspaceMergeAll {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$WarRoomsDir,
        [switch]$Force
    )

    return (Complete-PlanWorkspaceMerge -WarRoomsDir $WarRoomsDir -Force:$Force)
}

Export-ModuleMember -Function Invoke-RoomWorkspaceMerge, Invoke-PlanWorkspaceMergeAll
