Set-StrictMode -Version Latest

function ConvertTo-WorkspaceHashtable {
    param([Parameter(Mandatory)]$InputObject)

    if ($InputObject -is [hashtable]) { return $InputObject.Clone() }
    if ($InputObject -is [System.Collections.Specialized.OrderedDictionary]) {
        $result = [ordered]@{}
        foreach ($key in $InputObject.Keys) { $result[$key] = $InputObject[$key] }
        return $result
    }

    $copy = [ordered]@{}
    foreach ($prop in $InputObject.PSObject.Properties) {
        $copy[$prop.Name] = $prop.Value
    }
    return $copy
}

function Get-WorkspaceJson {
    param([Parameter(Mandatory)][string]$Path)

    if (-not (Test-Path $Path)) { return $null }
    return (Get-Content $Path -Raw | ConvertFrom-Json)
}

function Write-WorkspaceJson {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)]$Value
    )

    $parent = Split-Path $Path -Parent
    if ($parent -and -not (Test-Path $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }

    $tmp = "$Path.tmp.$PID"
    ($Value | ConvertTo-Json -Depth 30) | Out-File -FilePath $tmp -Encoding utf8
    Move-Item -Path $tmp -Destination $Path -Force
}

function Invoke-GitWorkspaceCommand {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Cwd,
        [Parameter(Mandatory)][string[]]$Arguments,
        [switch]$AllowFailure
    )

    $output = & git -C $Cwd @Arguments 2>&1
    $exitCode = $LASTEXITCODE
    $text = ($output | ForEach-Object { "$_" }) -join [Environment]::NewLine
    if ($exitCode -ne 0 -and -not $AllowFailure) {
        throw "git -C '$Cwd' $($Arguments -join ' ') failed with exit code ${exitCode}: $text"
    }

    return [pscustomobject]@{
        ExitCode = $exitCode
        Output   = $text
    }
}

function Test-WorkspaceRuntimePath {
    param([Parameter(Mandatory)][string]$Path)

    $normalized = ($Path -replace '\\', '/').TrimStart('/')
    if ($normalized -eq '.gitignore') { return $true }
    if ($normalized -eq '.DS_Store' -or $normalized.EndsWith('/.DS_Store', [System.StringComparison]::OrdinalIgnoreCase)) { return $true }
    foreach ($prefix in @(
        '.war-rooms/',
        '.worktree/',
        '.opencode/',
        '.agents/logs/',
        '.agents/plans/',
        '.agents/mcp/'
    )) {
        if ($normalized.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            return $true
        }
    }

    foreach ($runtimeSegment in @('/.war-rooms/', '/.worktree/', '/.opencode/', '/.agents/skills/', '/.agents/mcp/')) {
        if ($normalized.Contains($runtimeSegment, [System.StringComparison]::OrdinalIgnoreCase)) {
            return $true
        }
    }

    return $false
}

function Get-WorkspaceSafeSlug {
    param(
        [Parameter(Mandatory)][string]$Value,
        [int]$MaxLength = 80
    )

    $slug = $Value.ToLowerInvariant() -replace '[^a-z0-9._-]+', '-'
    $slug = $slug.Trim('-')
    if (-not $slug) { $slug = 'room' }
    if ($slug.Length -gt $MaxLength) { $slug = $slug.Substring(0, $MaxLength).Trim('-') }
    return $slug
}

function Get-RoomWorkspaceBranchName {
    param(
        [Parameter(Mandatory)][string]$PlanId,
        [Parameter(Mandatory)][string]$RoomId,
        [Parameter(Mandatory)][string]$TaskRef,
        [AllowEmptyString()][string]$Title = ''
    )

    $titleSlug = Get-WorkspaceSafeSlug -Value $Title -MaxLength 56
    $taskSlug = Get-WorkspaceSafeSlug -Value $TaskRef -MaxLength 24
    if ($titleSlug -eq 'room') { $titleSlug = $taskSlug }
    $roomSlug = Get-WorkspaceSafeSlug -Value $RoomId -MaxLength 24
    $planSlug = Get-WorkspaceSafeSlug -Value $PlanId -MaxLength 32
    return "ostwin/$planSlug/$roomSlug/$titleSlug-$taskSlug"
}

function Get-WorkspaceShortHash {
    param([Parameter(Mandatory)][string]$Value)

    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($Value)
        return [BitConverter]::ToString($sha.ComputeHash($bytes)).Replace('-', '').Substring(0, 12).ToLowerInvariant()
    } finally {
        $sha.Dispose()
    }
}

function Get-DefaultWorktreeRoot {
    param(
        [Parameter(Mandatory)][string]$SourceGitRoot,
        [Parameter(Mandatory)][string]$SourceWorkingDir,
        [Parameter(Mandatory)][string]$PlanId,
        [Parameter(Mandatory)][string]$RunId
    )

    return (Join-Path $SourceWorkingDir '.worktree')
}

function Test-WorkspacePathUnderRoot {
    param(
        [AllowEmptyString()][string]$Path,
        [AllowEmptyString()][string]$Root
    )

    if ([string]::IsNullOrWhiteSpace($Path) -or [string]::IsNullOrWhiteSpace($Root)) { return $false }
    $normalizedPath = ([System.IO.Path]::GetFullPath($Path) -replace '\\', '/').TrimEnd('/')
    $normalizedRoot = ([System.IO.Path]::GetFullPath($Root) -replace '\\', '/').TrimEnd('/')
    return $normalizedPath.Equals($normalizedRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
        $normalizedPath.StartsWith("$normalizedRoot/", [System.StringComparison]::OrdinalIgnoreCase)
}

function Test-RoomWorktreeDirectory {
    param([AllowEmptyString()][string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path $Path -PathType Container)) { return $false }
    return (Test-Path (Join-Path $Path '.git'))
}

function Test-StaleGeneratedRoomWorktreeDirectory {
    param([AllowEmptyString()][string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path $Path -PathType Container)) { return $false }
    if (Test-RoomWorktreeDirectory -Path $Path) { return $false }

    $items = @(Get-ChildItem -Path $Path -Force -ErrorAction SilentlyContinue)
    if ($items.Count -eq 0) { return $true }

    foreach ($item in $items) {
        $name = $item.Name
        if ($name -notin @('.worktree', '.agents', '.opencode', '.war-rooms', '.DS_Store')) {
            return $false
        }
    }
    return $true
}

function Get-WorkspaceStatusLines {
    param([Parameter(Mandatory)][string]$GitRoot)

    $status = Invoke-GitWorkspaceCommand -Cwd $GitRoot -Arguments @('status', '--porcelain=v1', '--untracked-files=all') -AllowFailure
    if ($status.ExitCode -ne 0) { return @("!! $($status.Output)") }
    if ([string]::IsNullOrWhiteSpace($status.Output)) { return @() }
    return @($status.Output -split "`r?`n" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
}

function Test-GitReady {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$WorkingDir,
        [switch]$AllowRuntimeState
    )

    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        return [pscustomobject]@{ Ready = $false; Reason = 'git_not_found'; Message = 'git executable was not found on PATH.'; WorkingDir = $WorkingDir }
    }
    if (-not (Test-Path $WorkingDir -PathType Container)) {
        return [pscustomobject]@{ Ready = $false; Reason = 'working_dir_missing'; Message = "working_dir does not exist: $WorkingDir"; WorkingDir = $WorkingDir }
    }

    $resolvedWorkingDir = (Resolve-Path $WorkingDir).Path
    $rootResult = Invoke-GitWorkspaceCommand -Cwd $resolvedWorkingDir -Arguments @('rev-parse', '--show-toplevel') -AllowFailure
    if ($rootResult.ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($rootResult.Output)) {
        return [pscustomobject]@{ Ready = $false; Reason = 'not_git_worktree'; Message = "working_dir is not inside a Git work tree: $resolvedWorkingDir"; WorkingDir = $resolvedWorkingDir }
    }

    $sourceGitRoot = $rootResult.Output.Trim()
    $headResult = Invoke-GitWorkspaceCommand -Cwd $sourceGitRoot -Arguments @('rev-parse', '--verify', 'HEAD') -AllowFailure
    if ($headResult.ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($headResult.Output)) {
        return [pscustomobject]@{ Ready = $false; Reason = 'head_missing'; Message = 'Git repository has no HEAD commit.'; WorkingDir = $resolvedWorkingDir; SourceGitRoot = $sourceGitRoot }
    }

    $inProgress = @()
    foreach ($statePath in @('MERGE_HEAD', 'CHERRY_PICK_HEAD', 'REVERT_HEAD')) {
        $gitPath = (Invoke-GitWorkspaceCommand -Cwd $sourceGitRoot -Arguments @('rev-parse', '--git-path', $statePath)).Output.Trim()
        if ($gitPath -and (Test-Path $gitPath)) { $inProgress += $statePath }
    }
    foreach ($statePath in @('rebase-merge', 'rebase-apply')) {
        $gitPath = (Invoke-GitWorkspaceCommand -Cwd $sourceGitRoot -Arguments @('rev-parse', '--git-path', $statePath)).Output.Trim()
        if ($gitPath -and (Test-Path $gitPath)) { $inProgress += $statePath }
    }
    if ($inProgress.Count -gt 0) {
        return [pscustomobject]@{ Ready = $false; Reason = 'git_operation_in_progress'; Message = "Git operation in progress: $($inProgress -join ', ')"; WorkingDir = $resolvedWorkingDir; SourceGitRoot = $sourceGitRoot }
    }

    $dirtyTracked = @()
    $dirtyUntracked = @()
    foreach ($line in (Get-WorkspaceStatusLines -GitRoot $sourceGitRoot)) {
        if ($line.StartsWith('!! ')) {
            return [pscustomobject]@{ Ready = $false; Reason = 'git_status_failed'; Message = $line; WorkingDir = $resolvedWorkingDir; SourceGitRoot = $sourceGitRoot }
        }
        if ($line.Length -lt 4) { continue }
        $path = $line.Substring(3).Trim('"')
        if ($line.StartsWith('?? ')) {
            if (-not ($AllowRuntimeState -and (Test-WorkspaceRuntimePath -Path $path))) {
                $dirtyUntracked += $path
            }
        } else {
            if (-not ($AllowRuntimeState -and (Test-WorkspaceRuntimePath -Path $path))) {
                $dirtyTracked += $path
            }
        }
    }
    if ($dirtyTracked.Count -gt 0) {
        return [pscustomobject]@{ Ready = $false; Reason = 'dirty_tracked_files'; Message = "Tracked files have uncommitted changes: $($dirtyTracked -join ', ')"; WorkingDir = $resolvedWorkingDir; SourceGitRoot = $sourceGitRoot; DirtyPaths = $dirtyTracked }
    }
    if ($dirtyUntracked.Count -gt 0) {
        return [pscustomobject]@{ Ready = $false; Reason = 'untracked_non_runtime_files'; Message = "Untracked non-runtime files are present: $($dirtyUntracked -join ', ')"; WorkingDir = $resolvedWorkingDir; SourceGitRoot = $sourceGitRoot; DirtyPaths = $dirtyUntracked }
    }

    $baseRef = $headResult.Output.Trim()
    $branch = (Invoke-GitWorkspaceCommand -Cwd $sourceGitRoot -Arguments @('rev-parse', '--abbrev-ref', 'HEAD')).Output.Trim()
    $prefix = (Invoke-GitWorkspaceCommand -Cwd $resolvedWorkingDir -Arguments @('rev-parse', '--show-prefix') -AllowFailure).Output.Trim()
    $relativeDir = if ($prefix) { $prefix.TrimEnd('/') } else { '.' }

    return [pscustomobject]@{
        Ready             = $true
        Reason            = 'ok'
        Message           = 'Git preflight passed.'
        WorkingDir        = $resolvedWorkingDir
        SourceGitRoot     = $sourceGitRoot
        SourceRelativeDir = $relativeDir
        BaseRef           = $baseRef
        BaseBranch        = $branch
    }
}

function Get-PlanWorkspaceManifestPath {
    param([Parameter(Mandatory)][string]$WarRoomsDir)
    return (Join-Path $WarRoomsDir 'workspace.json')
}

function Get-PlanWorkspaceManifest {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$WarRoomsDir)

    return (Get-WorkspaceJson -Path (Get-PlanWorkspaceManifestPath -WarRoomsDir $WarRoomsDir))
}

function Get-WorkspaceRoomsTable {
    param($Manifest)

    if (-not $Manifest -or -not ($Manifest.PSObject.Properties.Name -contains 'rooms') -or -not $Manifest.rooms) {
        return [ordered]@{}
    }
    return (ConvertTo-WorkspaceHashtable -InputObject $Manifest.rooms)
}

function Get-RoomWorkspaceRecord {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$WarRoomsDir,
        [Parameter(Mandatory)][string]$RoomId
    )

    $manifest = Get-PlanWorkspaceManifest -WarRoomsDir $WarRoomsDir
    if (-not $manifest) { return $null }
    $rooms = Get-WorkspaceRoomsTable -Manifest $manifest
    if (-not $rooms.Contains($RoomId)) { return $null }
    return [pscustomobject](ConvertTo-WorkspaceHashtable -InputObject $rooms[$RoomId])
}

function Set-RoomWorkspaceRecord {
    [CmdletBinding()]
    param(
        [string]$RoomId = '',
        [string]$TaskRef = '',
        [Parameter(Mandatory)][string]$WarRoomsDir,
        [Parameter(Mandatory)][string]$Status,
        [hashtable]$Fields = @{}
    )

    if ([string]::IsNullOrWhiteSpace($RoomId)) { throw 'RoomId is required to update workspace manifest room state.' }

    $manifestPath = Get-PlanWorkspaceManifestPath -WarRoomsDir $WarRoomsDir
    $manifest = Get-WorkspaceJson -Path $manifestPath
    if (-not $manifest) { return $null }

    $rooms = Get-WorkspaceRoomsTable -Manifest $manifest
    $record = if ($rooms.Contains($RoomId)) {
        ConvertTo-WorkspaceHashtable -InputObject $rooms[$RoomId]
    } else {
        [ordered]@{}
    }

    $record['room_id'] = $RoomId
    if ($TaskRef) { $record['task_ref'] = $TaskRef }
    $record['status'] = $Status
    $record['updated_at'] = (Get-Date).ToUniversalTime().ToString('o')
    foreach ($key in $Fields.Keys) { $record[$key] = $Fields[$key] }

    $rooms[$RoomId] = $record
    if ($manifest.PSObject.Properties.Name -contains 'rooms') {
        $manifest.rooms = $rooms
    } else {
        $manifest | Add-Member -NotePropertyName rooms -NotePropertyValue $rooms
    }
    if ($manifest.PSObject.Properties.Name -contains 'updated_at') {
        $manifest.updated_at = (Get-Date).ToUniversalTime().ToString('o')
    } else {
        $manifest | Add-Member -NotePropertyName updated_at -NotePropertyValue (Get-Date).ToUniversalTime().ToString('o')
    }
    Write-WorkspaceJson -Path $manifestPath -Value $manifest
    return [pscustomobject]$record
}

function Remove-RoomConfigWorkspaceState {
    param([Parameter(Mandatory)]$Config)

    if ($Config.PSObject.Properties.Name -contains 'workspace') {
        $Config.PSObject.Properties.Remove('workspace')
    }
    return $Config
}

function ConvertTo-WorkspaceCanonicalRoomStatus {
    param([AllowEmptyString()][string]$Status)

    switch ($Status) {
        'passed'       { return 'done' }
        'failed-final' { return 'failed' }
        'fixing'       { return 'optimize' }
        default        { return $Status }
    }
}

function Initialize-PlanIntegrationWorkspace {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$WarRoomsDir,
        [Parameter(Mandatory)][string]$PlanId,
        [Parameter(Mandatory)][string]$RunId,
        [Parameter(Mandatory)][string]$SourceWorkingDir,
        [ValidateSet('room-worktree','shared')][string]$WorkspaceIsolation = 'shared',
        [string]$WorktreeRoot = ''
    )

    if (-not (Test-Path $WarRoomsDir)) {
        New-Item -ItemType Directory -Path $WarRoomsDir -Force | Out-Null
    }

    if ($WorkspaceIsolation -eq 'shared') {
        $sourcePath = if (Test-Path $SourceWorkingDir -PathType Container) { (Resolve-Path $SourceWorkingDir).Path } else { $SourceWorkingDir }
        $manifest = [ordered]@{
            version            = 2
            isolation          = 'shared'
            plan_id            = $PlanId
            run_id             = $RunId
            source_working_dir = $sourcePath
            status             = 'not_applicable'
            rooms              = [ordered]@{}
            created_at         = (Get-Date).ToUniversalTime().ToString('o')
        }
        Write-WorkspaceJson -Path (Get-PlanWorkspaceManifestPath -WarRoomsDir $WarRoomsDir) -Value $manifest
        return [pscustomobject]$manifest
    }

    $ready = Test-GitReady -WorkingDir $SourceWorkingDir -AllowRuntimeState
    if (-not $ready.Ready) {
        throw $ready.Message
    }

    if ([string]::IsNullOrWhiteSpace($WorktreeRoot)) {
        $WorktreeRoot = Get-DefaultWorktreeRoot -SourceGitRoot $ready.SourceGitRoot -SourceWorkingDir $ready.WorkingDir -PlanId $PlanId -RunId $RunId
    }
    $WorktreeRoot = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($WorktreeRoot)

    New-Item -ItemType Directory -Path $WorktreeRoot -Force | Out-Null

    $manifest = [ordered]@{
        version                  = 2
        isolation                = 'room-worktree'
        plan_id                  = $PlanId
        run_id                   = $RunId
        source_git_root          = $ready.SourceGitRoot
        source_working_dir       = $ready.WorkingDir
        source_relative_dir      = $ready.SourceRelativeDir
        base_ref                 = $ready.BaseRef
        base_branch              = $ready.BaseBranch
        worktree_root            = $WorktreeRoot
        status                   = 'ready'
        rooms                    = [ordered]@{}
        created_at               = (Get-Date).ToUniversalTime().ToString('o')
    }

    Write-WorkspaceJson -Path (Get-PlanWorkspaceManifestPath -WarRoomsDir $WarRoomsDir) -Value $manifest
    return [pscustomobject]$manifest
}

function Find-WorkspaceRoomByTaskRef {
    param(
        [Parameter(Mandatory)][string]$WarRoomsDir,
        [Parameter(Mandatory)][string]$TaskRef
    )

    foreach ($room in (Get-ChildItem -Path $WarRoomsDir -Directory -Filter 'room-*' -ErrorAction SilentlyContinue | Sort-Object Name)) {
        $cfgPath = Join-Path $room.FullName 'config.json'
        if (-not (Test-Path $cfgPath)) { continue }
        try {
            $cfg = Get-Content $cfgPath -Raw | ConvertFrom-Json
            if ("$($cfg.task_ref)" -eq $TaskRef) { return $room.FullName }
        } catch { }
    }
    return $null
}

function Set-RoomWorkspaceStatus {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$RoomDir,
        [Parameter(Mandatory)][string]$Status,
        [hashtable]$Fields = @{}
    )

    $cfgPath = Join-Path $RoomDir 'config.json'
    if (-not (Test-Path $cfgPath)) { return $null }
    $cfg = Get-Content $cfgPath -Raw | ConvertFrom-Json
    $warRoomsDir = Split-Path $RoomDir -Parent
    $roomId = if ($cfg.room_id) { "$($cfg.room_id)" } else { Split-Path $RoomDir -Leaf }
    $taskRef = if ($cfg.task_ref) { "$($cfg.task_ref)" } else { '' }
    $record = Set-RoomWorkspaceRecord -WarRoomsDir $warRoomsDir -RoomId $roomId -TaskRef $taskRef -Status $Status -Fields $Fields
    $cfg = Remove-RoomConfigWorkspaceState -Config $cfg
    Write-WorkspaceJson -Path $cfgPath -Value $cfg
    return $record
}

function Get-WorkspaceDependencyState {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$RoomDir,
        [Parameter(Mandatory)][string]$WarRoomsDir
    )

    $manifest = Get-PlanWorkspaceManifest -WarRoomsDir $WarRoomsDir
    if (-not $manifest -or "$($manifest.isolation)" -eq 'shared') {
        return [pscustomobject]@{ Ready = $true; Reason = 'shared'; BlockedBy = @() }
    }

    $cfgPath = Join-Path $RoomDir 'config.json'
    if (-not (Test-Path $cfgPath)) {
        return [pscustomobject]@{ Ready = $false; Reason = 'missing_config'; BlockedBy = @($RoomDir) }
    }
    $cfg = Get-Content $cfgPath -Raw | ConvertFrom-Json
    $blocked = @()
    foreach ($dep in @($cfg.depends_on)) {
        if ([string]::IsNullOrWhiteSpace([string]$dep) -or "$dep" -eq 'PLAN-REVIEW') { continue }
        $depRoom = Find-WorkspaceRoomByTaskRef -WarRoomsDir $WarRoomsDir -TaskRef "$dep"
        if (-not $depRoom) {
            $blocked += "${dep}:missing-room"
            continue
        }
        $depCfgPath = Join-Path $depRoom 'config.json'
        $depStatusPath = Join-Path $depRoom 'status'
        $depStatus = if (Test-Path $depStatusPath) { (Get-Content $depStatusPath -Raw).Trim() } else { '' }
        $depCfg = Get-Content $depCfgPath -Raw | ConvertFrom-Json
        $depRoomId = if ($depCfg.room_id) { "$($depCfg.room_id)" } else { Split-Path $depRoom -Leaf }
        $workspaceRecord = Get-RoomWorkspaceRecord -WarRoomsDir $WarRoomsDir -RoomId $depRoomId
        $workspaceStatus = if ($workspaceRecord -and ($workspaceRecord.PSObject.Properties.Name -contains 'status')) { "$($workspaceRecord.status)" } else { '' }
        $depCanonical = ConvertTo-WorkspaceCanonicalRoomStatus -Status $depStatus
        if ($depCanonical -ne 'done') {
            $blocked += "${dep}:not-done"
        } elseif ($workspaceStatus -notin @('merged', 'not_applicable')) {
            $blocked += "${dep}:not-merged"
        }
    }

    return [pscustomobject]@{
        Ready     = ($blocked.Count -eq 0)
        Reason    = if ($blocked.Count -eq 0) { 'ready' } else { 'dependencies_not_merged' }
        BlockedBy = $blocked
    }
}

function Sync-AgentRuntimeOverlay {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$SourceGitRoot,
        [Parameter(Mandatory)][string]$RoomWorktreeRoot,
        [string]$AgentsDir = ''
    )

    foreach ($dirRel in @('.agents/plans', '.agents/mcp')) {
        $src = Join-Path $SourceGitRoot $dirRel
        if (Test-Path $src) {
            $dst = Join-Path $RoomWorktreeRoot $dirRel
            $parent = Split-Path $dst -Parent
            if ($parent -and -not (Test-Path $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
            Copy-Item -Path $src -Destination $parent -Recurse -Force
        }
    }

    $opencodeSrc = Join-Path $SourceGitRoot '.opencode/opencode.json'
    if (Test-Path $opencodeSrc) {
        $opencodeDstDir = Join-Path $RoomWorktreeRoot '.opencode'
        New-Item -ItemType Directory -Path $opencodeDstDir -Force | Out-Null
        Copy-Item -Path $opencodeSrc -Destination (Join-Path $opencodeDstDir 'opencode.json') -Force
    }

    if ($AgentsDir) {
        $mcpSrc = Join-Path $AgentsDir 'mcp'
        if (Test-Path $mcpSrc) {
            $mcpDst = Join-Path $RoomWorktreeRoot '.agents/mcp'
            $mcpParent = Split-Path $mcpDst -Parent
            if ($mcpParent -and -not (Test-Path $mcpParent)) { New-Item -ItemType Directory -Path $mcpParent -Force | Out-Null }
            Copy-Item -Path $mcpSrc -Destination $mcpParent -Recurse -Force
        }
    }
}

function Ensure-RoomWorktree {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$RoomDir,
        [Parameter(Mandatory)][string]$WarRoomsDir,
        [string]$AgentsDir = ''
    )

    $manifest = Get-PlanWorkspaceManifest -WarRoomsDir $WarRoomsDir
    if (-not $manifest -or "$($manifest.isolation)" -eq 'shared') {
        Set-RoomWorkspaceStatus -RoomDir $RoomDir -Status 'not_applicable' | Out-Null
        return [pscustomobject]@{ Ready = $true; Mode = 'shared'; WorkingDir = '' }
    }

    $cfgPath = Join-Path $RoomDir 'config.json'
    $cfg = Get-Content $cfgPath -Raw | ConvertFrom-Json
    $roomId = "$($cfg.room_id)"
    $taskRef = "$($cfg.task_ref)"
    $title = if ($cfg.assignment -and $cfg.assignment.title) { "$($cfg.assignment.title)" } else { $taskRef }

    if ($taskRef -eq 'PLAN-REVIEW') {
        Set-RoomWorkspaceStatus -RoomDir $RoomDir -Status 'not_applicable' | Out-Null
        $cfg = Remove-RoomConfigWorkspaceState -Config $cfg
        Write-WorkspaceJson -Path $cfgPath -Value $cfg
        return [pscustomobject]@{ Ready = $true; Mode = 'plan-review'; WorkingDir = "$($cfg.working_dir)" }
    }

    $roomWorktreeRoot = Join-Path "$($manifest.worktree_root)" $roomId

    $existingRecord = Get-RoomWorkspaceRecord -WarRoomsDir $WarRoomsDir -RoomId $roomId
    if ($existingRecord) {
        $existingStatus = if ($existingRecord.PSObject.Properties.Name -contains 'status') { "$($existingRecord.status)" } else { '' }
        $existingWorktreeDir = if ($existingRecord.PSObject.Properties.Name -contains 'worktree_dir') { "$($existingRecord.worktree_dir)" } else { '' }
        $existingDir = if ($existingRecord.PSObject.Properties.Name -contains 'working_dir') { "$($existingRecord.working_dir)" } else { '' }
        $existingWorktreeMatches = $existingWorktreeDir -and ([System.IO.Path]::GetFullPath($existingWorktreeDir) -eq [System.IO.Path]::GetFullPath($roomWorktreeRoot))
        if ($existingStatus -in @('ready', 'merged') -and $existingWorktreeMatches -and (Test-RoomWorktreeDirectory -Path $roomWorktreeRoot) -and $existingDir -and (Test-Path $existingDir -PathType Container)) {
            $cfg.working_dir = $existingDir
            $cfg = Remove-RoomConfigWorkspaceState -Config $cfg
            Write-WorkspaceJson -Path $cfgPath -Value $cfg
            return [pscustomobject]@{ Ready = $true; Mode = 'room-worktree'; WorkingDir = $existingDir; Reused = $true }
        }
    }

    $branch = Get-RoomWorkspaceBranchName -PlanId "$($manifest.plan_id)" -RoomId $roomId -TaskRef $taskRef -Title $title
    $baseRef = (Invoke-GitWorkspaceCommand -Cwd "$($manifest.source_git_root)" -Arguments @('rev-parse', 'HEAD')).Output.Trim()
    Set-RoomWorkspaceRecord -WarRoomsDir $WarRoomsDir -RoomId $roomId -TaskRef $taskRef -Status 'creating' -Fields @{
        branch       = $branch
        base_ref     = $baseRef
        worktree_dir = $roomWorktreeRoot
    } | Out-Null

    try {
        if (-not (Test-RoomWorktreeDirectory -Path $roomWorktreeRoot)) {
            if ((Test-Path $roomWorktreeRoot -PathType Container) -and ((Get-ChildItem -Path $roomWorktreeRoot -Force -ErrorAction SilentlyContinue | Measure-Object).Count -eq 0)) {
                Remove-Item -Path $roomWorktreeRoot -Force
            } elseif (Test-StaleGeneratedRoomWorktreeDirectory -Path $roomWorktreeRoot) {
                Remove-Item -Path $roomWorktreeRoot -Recurse -Force
            } elseif (Test-Path $roomWorktreeRoot -PathType Container) {
                throw "Room worktree path exists but is not a Git worktree and contains non-runtime files: $roomWorktreeRoot"
            }
            Invoke-GitWorkspaceCommand -Cwd "$($manifest.source_git_root)" -Arguments @('worktree', 'add', '-B', $branch, $roomWorktreeRoot, $baseRef) | Out-Null
        }
        Sync-AgentRuntimeOverlay -SourceGitRoot "$($manifest.source_git_root)" -RoomWorktreeRoot $roomWorktreeRoot -AgentsDir $AgentsDir
        $relativeDir = ''
        if ($manifest.PSObject.Properties.Name -contains 'source_git_root' -and $manifest.source_git_root -and $cfg.working_dir -and -not (Test-WorkspacePathUnderRoot -Path "$($cfg.working_dir)" -Root "$($manifest.worktree_root)")) {
            try {
                $candidateRelative = [System.IO.Path]::GetRelativePath("$($manifest.source_git_root)", "$($cfg.working_dir)") -replace '\\', '/'
                if ($candidateRelative -and $candidateRelative -ne '.') { $relativeDir = $candidateRelative }
            } catch { }
        }
        if (-not $relativeDir -and $manifest.PSObject.Properties.Name -contains 'source_relative_dir' -and "$($manifest.source_relative_dir)" -ne '.') {
            $relativeDir = "$($manifest.source_relative_dir)"
        }
        $roomWorkingDir = if ($relativeDir) { Join-Path $roomWorktreeRoot $relativeDir } else { $roomWorktreeRoot }
        if (-not (Test-Path $roomWorkingDir)) { New-Item -ItemType Directory -Path $roomWorkingDir -Force | Out-Null }

        $cfg.working_dir = $roomWorkingDir
        $cfg = Remove-RoomConfigWorkspaceState -Config $cfg
        Write-WorkspaceJson -Path $cfgPath -Value $cfg
        Set-RoomWorkspaceRecord -WarRoomsDir $WarRoomsDir -RoomId $roomId -TaskRef $taskRef -Status 'ready' -Fields @{
            mode                = 'git-worktree'
            branch              = $branch
            base_ref            = $baseRef
            worktree_dir        = $roomWorktreeRoot
            working_dir         = $roomWorkingDir
            source_relative_dir = if ($relativeDir) { $relativeDir } else { '.' }
            ready_at            = (Get-Date).ToUniversalTime().ToString('o')
        } | Out-Null
        return [pscustomobject]@{ Ready = $true; Mode = 'room-worktree'; WorkingDir = $roomWorkingDir; BaseRef = $baseRef; Branch = $branch }
    } catch {
        Set-RoomWorkspaceRecord -WarRoomsDir $WarRoomsDir -RoomId $roomId -TaskRef $taskRef -Status 'failed' -Fields @{ error = $_.Exception.Message } | Out-Null
        throw
    }
}

function Update-PlanWorkspaceIntegrationHead {
    param(
        [Parameter(Mandatory)][string]$WarRoomsDir,
        [Parameter(Mandatory)][string]$IntegrationHead
    )

    $manifestPath = Get-PlanWorkspaceManifestPath -WarRoomsDir $WarRoomsDir
    $manifest = Get-WorkspaceJson -Path $manifestPath
    if (-not $manifest) { return }
    if ($manifest.PSObject.Properties.Name -contains 'integration_head') {
        $manifest.integration_head = $IntegrationHead
    } else {
        $manifest | Add-Member -NotePropertyName integration_head -NotePropertyValue $IntegrationHead
    }
    if ($manifest.PSObject.Properties.Name -contains 'updated_at') {
        $manifest.updated_at = (Get-Date).ToUniversalTime().ToString('o')
    } else {
        $manifest | Add-Member -NotePropertyName updated_at -NotePropertyValue (Get-Date).ToUniversalTime().ToString('o')
    }
    Write-WorkspaceJson -Path $manifestPath -Value $manifest
}

function Complete-RoomWorkspaceMerge {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$RoomDir,
        [Parameter(Mandatory)][string]$WarRoomsDir
    )

    $manifest = Get-PlanWorkspaceManifest -WarRoomsDir $WarRoomsDir
    if (-not $manifest -or "$($manifest.isolation)" -eq 'shared') {
        Set-RoomWorkspaceStatus -RoomDir $RoomDir -Status 'not_applicable' | Out-Null
        return [pscustomobject]@{ Integrated = $true; Status = 'not_applicable' }
    }

    $cfgPath = Join-Path $RoomDir 'config.json'
    $cfg = Get-Content $cfgPath -Raw | ConvertFrom-Json
    $roomId = "$($cfg.room_id)"
    $taskRef = "$($cfg.task_ref)"

    if ($taskRef -eq 'PLAN-REVIEW') {
        Set-RoomWorkspaceStatus -RoomDir $RoomDir -Status 'not_applicable' | Out-Null
        $cfg = Remove-RoomConfigWorkspaceState -Config $cfg
        Write-WorkspaceJson -Path $cfgPath -Value $cfg
        return [pscustomobject]@{ Integrated = $true; Status = 'not_applicable' }
    }

    $workspaceRecord = Get-RoomWorkspaceRecord -WarRoomsDir $WarRoomsDir -RoomId $roomId
    if ($workspaceRecord -and ($workspaceRecord.PSObject.Properties.Name -contains 'status') -and "$($workspaceRecord.status)" -eq 'merged') {
        return [pscustomobject]@{ Integrated = $true; Status = 'merged'; Reused = $true }
    }
    if ($workspaceRecord -and ($workspaceRecord.PSObject.Properties.Name -contains 'status') -and "$($workspaceRecord.status)" -eq 'conflicted') {
        return [pscustomobject]@{ Integrated = $false; Status = 'conflicted' }
    }
    if (-not $workspaceRecord) {
        Set-RoomWorkspaceRecord -WarRoomsDir $WarRoomsDir -RoomId $roomId -TaskRef $taskRef -Status 'failed' -Fields @{ error = 'Workspace record missing from manifest.' } | Out-Null
        return [pscustomobject]@{ Integrated = $false; Status = 'workspace_missing' }
    }

    $workspace = ConvertTo-WorkspaceHashtable -InputObject $workspaceRecord
    $roomWorktree = "$($workspace['worktree_dir'])"
    $branch = "$($workspace['branch'])"
    if (-not (Test-Path $roomWorktree -PathType Container)) {
        Set-RoomWorkspaceRecord -WarRoomsDir $WarRoomsDir -RoomId $roomId -TaskRef $taskRef -Status 'failed' -Fields @{ error = "Room worktree missing: $roomWorktree" } | Out-Null
        return [pscustomobject]@{ Integrated = $false; Status = 'worktree_missing' }
    }

    $lockDir = Join-Path $WarRoomsDir '.workspace'
    New-Item -ItemType Directory -Path $lockDir -Force | Out-Null
    $lockPath = Join-Path $lockDir 'merge.lock'
    $lockStream = $null
    while (-not $lockStream) {
        try {
            $lockStream = [System.IO.File]::Open($lockPath, [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
        } catch {
            Start-Sleep -Milliseconds 200
        }
    }

    try {
        $sourceStatusLines = Get-WorkspaceStatusLines -GitRoot "$($manifest.source_git_root)"
        $dirtySourceTracked = @()
        foreach ($line in $sourceStatusLines) {
            if ($line.StartsWith('!! ')) { throw $line }
            if ($line.Length -lt 4 -or $line.StartsWith('?? ')) { continue }
            $path = $line.Substring(3).Trim('"')
            if (-not (Test-WorkspaceRuntimePath -Path $path)) { $dirtySourceTracked += $path }
        }
        if ($dirtySourceTracked.Count -gt 0) {
            Set-RoomWorkspaceRecord -WarRoomsDir $WarRoomsDir -RoomId $roomId -TaskRef $taskRef -Status 'failed' -Fields @{ error = "Source worktree has dirty tracked files: $($dirtySourceTracked -join ', ')" } | Out-Null
            return [pscustomobject]@{ Integrated = $false; Status = 'source_dirty'; DirtyPaths = $dirtySourceTracked }
        }

        $statusLines = Get-WorkspaceStatusLines -GitRoot $roomWorktree
        $hasCandidateChanges = $false
        foreach ($line in $statusLines) {
            if ($line.Length -lt 4) { continue }
            $path = $line.Substring(3).Trim('"')
            if (-not (Test-WorkspaceRuntimePath -Path $path)) { $hasCandidateChanges = $true; break }
        }

        $commitCreated = $false
        if ($hasCandidateChanges) {
            Invoke-GitWorkspaceCommand -Cwd $roomWorktree -Arguments @('add', '-A', '--', '.') | Out-Null
            foreach ($runtimePath in @('.war-rooms', '.opencode', '.agents/logs', '.agents/plans', '.agents/mcp')) {
                Invoke-GitWorkspaceCommand -Cwd $roomWorktree -Arguments @('reset', '-q', 'HEAD', '--', $runtimePath) -AllowFailure | Out-Null
            }
            $cached = Invoke-GitWorkspaceCommand -Cwd $roomWorktree -Arguments @('diff', '--cached', '--quiet') -AllowFailure
            if ($cached.ExitCode -ne 0) {
                $message = "ostwin: $taskRef $roomId"
                Invoke-GitWorkspaceCommand -Cwd $roomWorktree -Arguments @('-c', 'user.name=ostwin', '-c', 'user.email=ostwin@local', 'commit', '-m', $message) | Out-Null
                $commitCreated = $true
                $commitRef = (Invoke-GitWorkspaceCommand -Cwd $roomWorktree -Arguments @('rev-parse', 'HEAD')).Output.Trim()
                Set-RoomWorkspaceRecord -WarRoomsDir $WarRoomsDir -RoomId $roomId -TaskRef $taskRef -Status 'committed' -Fields @{
                    branch = $branch
                    commit = $commitRef
                } | Out-Null
            }
        }

        $roomHead = (Invoke-GitWorkspaceCommand -Cwd $roomWorktree -Arguments @('rev-parse', 'HEAD')).Output.Trim()
        $baseRef = if ($workspace.Contains('base_ref')) { "$($workspace['base_ref'])" } else { '' }
        if (-not $commitCreated -and $baseRef -and $roomHead -eq $baseRef) {
            Set-RoomWorkspaceRecord -WarRoomsDir $WarRoomsDir -RoomId $roomId -TaskRef $taskRef -Status 'merged' -Fields @{
                branch             = $branch
                merged_at          = (Get-Date).ToUniversalTime().ToString('o')
                no_changes         = $true
            } | Out-Null
            return [pscustomobject]@{ Integrated = $true; Status = 'merged'; NoChanges = $true }
        }

        Set-RoomWorkspaceRecord -WarRoomsDir $WarRoomsDir -RoomId $roomId -TaskRef $taskRef -Status 'merging' -Fields @{
            branch = $branch
        } | Out-Null

        $merge = Invoke-GitWorkspaceCommand -Cwd "$($manifest.source_git_root)" -Arguments @('-c', 'user.name=ostwin', '-c', 'user.email=ostwin@local', 'merge', '--no-ff', '--no-edit', $branch) -AllowFailure
        if ($merge.ExitCode -ne 0) {
            $conflicts = (Invoke-GitWorkspaceCommand -Cwd "$($manifest.source_git_root)" -Arguments @('diff', '--name-only', '--diff-filter=U') -AllowFailure).Output
            $conflictFiles = @($conflicts -split "`r?`n" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
            $conflictDetails = [ordered]@{
                room_id = $roomId
                task_ref = $taskRef
                branch = $branch
                conflict_files = $conflictFiles
                error = $merge.Output
                conflicted_at = (Get-Date).ToUniversalTime().ToString('o')
            }
            $artifactsDir = Join-Path $RoomDir 'artifacts'
            if (-not (Test-Path $artifactsDir)) { New-Item -ItemType Directory -Path $artifactsDir -Force | Out-Null }
            Write-WorkspaceJson -Path (Join-Path $artifactsDir 'workspace-merge-conflict.json') -Value $conflictDetails
            Invoke-GitWorkspaceCommand -Cwd "$($manifest.source_git_root)" -Arguments @('merge', '--abort') -AllowFailure | Out-Null
            Set-RoomWorkspaceRecord -WarRoomsDir $WarRoomsDir -RoomId $roomId -TaskRef $taskRef -Status 'conflicted' -Fields @{
                branch         = $branch
                conflict_files = $conflictFiles
                error          = $merge.Output
                artifact       = 'artifacts/workspace-merge-conflict.json'
            } | Out-Null
            return [pscustomobject]@{ Integrated = $false; Status = 'conflicted'; ConflictFiles = $conflictFiles; Artifact = 'artifacts/workspace-merge-conflict.json' }
        }

        $mergedHead = (Invoke-GitWorkspaceCommand -Cwd "$($manifest.source_git_root)" -Arguments @('rev-parse', 'HEAD')).Output.Trim()
        Update-PlanWorkspaceIntegrationHead -WarRoomsDir $WarRoomsDir -IntegrationHead $mergedHead
        Set-RoomWorkspaceRecord -WarRoomsDir $WarRoomsDir -RoomId $roomId -TaskRef $taskRef -Status 'merged' -Fields @{
            branch      = $branch
            merged_head = $mergedHead
            merged_at   = (Get-Date).ToUniversalTime().ToString('o')
        } | Out-Null
        $cfg = Remove-RoomConfigWorkspaceState -Config $cfg
        Write-WorkspaceJson -Path $cfgPath -Value $cfg
        return [pscustomobject]@{ Integrated = $true; Status = 'merged'; MergedHead = $mergedHead }
    } finally {
        if ($lockStream) { $lockStream.Dispose() }
    }
}

Export-ModuleMember -Function Test-GitReady, Initialize-PlanIntegrationWorkspace, Ensure-RoomWorktree, Sync-AgentRuntimeOverlay, Get-WorkspaceDependencyState, Get-PlanWorkspaceManifest, Get-RoomWorkspaceRecord, Set-RoomWorkspaceRecord, Set-RoomWorkspaceStatus, Complete-RoomWorkspaceMerge
