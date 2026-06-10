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
    if ($normalized -eq '.memory' -or
        $normalized.StartsWith('.memory/', [System.StringComparison]::OrdinalIgnoreCase) -or
        $normalized.EndsWith('/.memory', [System.StringComparison]::OrdinalIgnoreCase) -or
        $normalized.Contains('/.memory/', [System.StringComparison]::OrdinalIgnoreCase)) { return $true }
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

    foreach ($runtimeSegment in @('/.war-rooms/', '/.worktree/', '/.opencode/', '/.agents/logs/', '/.agents/plans/', '/.agents/mcp/')) {
        if ($normalized.Contains($runtimeSegment, [System.StringComparison]::OrdinalIgnoreCase)) {
            return $true
        }
    }

    return $false
}

function Test-WorkspaceUntrackedRuntimePath {
    param([Parameter(Mandatory)][string]$Path)

    if (Test-WorkspaceRuntimePath -Path $Path) { return $true }

    # Project-local skills are staged into room worktrees at runtime. Ignore
    # untracked staged skills, but do not hide tracked skill edits/deletes.
    $normalized = ($Path -replace '\\', '/').TrimStart('/')
    return $normalized.StartsWith('.agents/skills/', [System.StringComparison]::OrdinalIgnoreCase) -or
        $normalized.Contains('/.agents/skills/', [System.StringComparison]::OrdinalIgnoreCase)
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

    # Plan-scoped so two plans running against the same project never collide
    # on room-NNN worktree paths.
    $planSlug = Get-WorkspaceSafeSlug -Value $PlanId -MaxLength 48
    return (Join-Path (Join-Path $SourceWorkingDir '.worktree') $planSlug)
}

# Single source of truth for untracked runtime paths that must never enter room commits.
# Written into each room worktree's git info/exclude so git itself enforces the
# policy for generated status noise and add -A alike. Tracked files remain
# visible to git even when they match info/exclude.
$script:WorkspaceRuntimeExcludeEntries = @(
    '.war-rooms/',
    '.worktree/',
    '.opencode/',
    '.DS_Store',
    '.memory',
    '**/.agents/skills/',
    '**/.agents/logs/',
    '**/.agents/plans/',
    '**/.agents/mcp/'
)

function Set-WorktreeRuntimeExcludes {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$WorktreeDir)

    $excludePath = (Invoke-GitWorkspaceCommand -Cwd $WorktreeDir -Arguments @('rev-parse', '--git-path', 'info/exclude') -AllowFailure).Output.Trim()
    if (-not $excludePath) { return }
    if (-not [System.IO.Path]::IsPathRooted($excludePath)) {
        $excludePath = Join-Path $WorktreeDir $excludePath
    }
    $parent = Split-Path $excludePath -Parent
    if ($parent -and -not (Test-Path $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    $lines = [System.Collections.Generic.List[string]]::new()
    if (Test-Path $excludePath) {
        foreach ($l in @(Get-Content $excludePath -ErrorAction SilentlyContinue)) { $lines.Add("$l") }
    }
    foreach ($entry in $script:WorkspaceRuntimeExcludeEntries) {
        if (-not $lines.Contains($entry)) { $lines.Add($entry) }
    }
    ($lines -join "`n") | Out-File -FilePath $excludePath -Encoding utf8
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
            if (-not ($AllowRuntimeState -and (Test-WorkspaceUntrackedRuntimePath -Path $path))) {
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

    # Untracked files do NOT block: room worktrees fork from HEAD (untracked
    # files never enter them), and the merge-back is guarded by git itself,
    # which refuses to overwrite untracked paths. Report them so callers can
    # warn that this work is invisible to agents until committed.
    $baseRef = $headResult.Output.Trim()
    $branch = (Invoke-GitWorkspaceCommand -Cwd $sourceGitRoot -Arguments @('rev-parse', '--abbrev-ref', 'HEAD')).Output.Trim()
    $prefix = (Invoke-GitWorkspaceCommand -Cwd $resolvedWorkingDir -Arguments @('rev-parse', '--show-prefix') -AllowFailure).Output.Trim()
    $relativeDir = if ($prefix) { $prefix.TrimEnd('/') } else { '.' }

    $message = if ($dirtyUntracked.Count -gt 0) {
        "Git preflight passed. Untracked files are not visible to room worktrees until committed: $($dirtyUntracked -join ', ')"
    } else {
        'Git preflight passed.'
    }

    return [pscustomobject]@{
        Ready             = $true
        Reason            = 'ok'
        Message           = $message
        WorkingDir        = $resolvedWorkingDir
        SourceGitRoot     = $sourceGitRoot
        SourceRelativeDir = $relativeDir
        BaseRef           = $baseRef
        BaseBranch        = $branch
        UntrackedPaths    = @($dirtyUntracked)
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

function Remove-PlanWorkspaceWorktrees {
    [CmdletBinding()]
    param([Parameter(Mandatory)]$Manifest)

    $gitRoot = if ($Manifest.PSObject.Properties.Name -contains 'source_git_root') { "$($Manifest.source_git_root)" } else { '' }
    if (-not $gitRoot -or -not (Test-Path $gitRoot -PathType Container)) { return }

    $rooms = Get-WorkspaceRoomsTable -Manifest $Manifest
    foreach ($roomId in @($rooms.Keys)) {
        $record = ConvertTo-WorkspaceHashtable -InputObject $rooms[$roomId]
        $dir = if ($record.Contains('worktree_dir')) { "$($record['worktree_dir'])" } else { '' }
        if ($dir -and (Test-RoomWorktreeDirectory -Path $dir)) {
            Invoke-GitWorkspaceCommand -Cwd $gitRoot -Arguments @('worktree', 'remove', '--force', $dir) -AllowFailure | Out-Null
            if (Test-Path $dir) {
                Remove-Item -Path $dir -Recurse -Force -ErrorAction SilentlyContinue
            }
        }
    }
    Invoke-GitWorkspaceCommand -Cwd $gitRoot -Arguments @('worktree', 'prune') -AllowFailure | Out-Null
}

function Initialize-PlanIntegrationWorkspace {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$WarRoomsDir,
        [Parameter(Mandatory)][string]$PlanId,
        [Parameter(Mandatory)][string]$RunId,
        [Parameter(Mandatory)][string]$SourceWorkingDir,
        [ValidateSet('room-worktree','shared')][string]$WorkspaceIsolation = 'shared',
        [string]$WorktreeRoot = '',
        [switch]$Resume
    )

    if (-not (Test-Path $WarRoomsDir)) {
        New-Item -ItemType Directory -Path $WarRoomsDir -Force | Out-Null
    }

    $existingManifest = Get-PlanWorkspaceManifest -WarRoomsDir $WarRoomsDir

    # Resume must never wipe room records, integration head, or live worktrees.
    if ($Resume -and $existingManifest `
            -and "$($existingManifest.plan_id)" -eq $PlanId `
            -and "$($existingManifest.isolation)" -eq $WorkspaceIsolation) {
        return $existingManifest
    }

    # Fresh init: tear down worktrees registered by the previous manifest so a
    # new run can never silently reuse a stale checkout.
    if ($existingManifest -and "$($existingManifest.isolation)" -eq 'room-worktree') {
        Remove-PlanWorkspaceWorktrees -Manifest $existingManifest
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

    # Keep the source repo's git status clean of ostwin runtime artifacts
    # (.agents/skills, .opencode, .memory, .war-rooms, .worktree, ...) without
    # touching the user's .gitignore — info/exclude is local-only.
    Set-WorktreeRuntimeExcludes -WorktreeDir $ready.SourceGitRoot

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
        integration_head         = $ready.BaseRef
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

    # Fork base: the plan integration head — never the moving source HEAD.
    # This makes parallel room forks deterministic regardless of spawn order.
    $integrationHead = ''
    if ($manifest.PSObject.Properties.Name -contains 'integration_head' -and $manifest.integration_head) {
        $integrationHead = "$($manifest.integration_head)"
    } elseif ($manifest.PSObject.Properties.Name -contains 'base_ref' -and $manifest.base_ref) {
        $integrationHead = "$($manifest.base_ref)"
    }

    $existingRecord = Get-RoomWorkspaceRecord -WarRoomsDir $WarRoomsDir -RoomId $roomId
    if ($existingRecord) {
        $existingStatus = if ($existingRecord.PSObject.Properties.Name -contains 'status') { "$($existingRecord.status)" } else { '' }
        $existingWorktreeDir = if ($existingRecord.PSObject.Properties.Name -contains 'worktree_dir') { "$($existingRecord.worktree_dir)" } else { '' }
        $existingDir = if ($existingRecord.PSObject.Properties.Name -contains 'working_dir') { "$($existingRecord.working_dir)" } else { '' }
        $existingBranch = if ($existingRecord.PSObject.Properties.Name -contains 'branch') { "$($existingRecord.branch)" } else { '' }
        $existingWorktreeMatches = $existingWorktreeDir -and ([System.IO.Path]::GetFullPath($existingWorktreeDir) -eq [System.IO.Path]::GetFullPath($roomWorktreeRoot))

        # Reuse only when the checkout still matches the record (same branch).
        # 'merged' is deliberately NOT reusable: post-merge rework must re-fork
        # from the new integration head or it would never be integrated again.
        $branchMatches = $false
        if ($existingWorktreeMatches -and $existingBranch -and (Test-RoomWorktreeDirectory -Path $roomWorktreeRoot)) {
            $headBranch = (Invoke-GitWorkspaceCommand -Cwd $roomWorktreeRoot -Arguments @('rev-parse', '--abbrev-ref', 'HEAD') -AllowFailure).Output.Trim()
            $branchMatches = ($headBranch -eq $existingBranch)
        }
        if ($existingStatus -in @('ready', 'committed') -and $branchMatches -and $existingDir -and (Test-Path $existingDir -PathType Container)) {
            $cfg.working_dir = $existingDir
            $cfg = Remove-RoomConfigWorkspaceState -Config $cfg
            Write-WorkspaceJson -Path $cfgPath -Value $cfg
            return [pscustomobject]@{ Ready = $true; Mode = 'room-worktree'; WorkingDir = $existingDir; Reused = $true }
        }
    }

    $branch = Get-RoomWorkspaceBranchName -PlanId "$($manifest.plan_id)" -RoomId $roomId -TaskRef $taskRef -Title $title
    $baseRef = $integrationHead
    if (-not $baseRef) {
        $baseRef = (Invoke-GitWorkspaceCommand -Cwd "$($manifest.source_git_root)" -Arguments @('rev-parse', 'HEAD')).Output.Trim()
    }
    Set-RoomWorkspaceRecord -WarRoomsDir $WarRoomsDir -RoomId $roomId -TaskRef $taskRef -Status 'creating' -Fields @{
        branch       = $branch
        base_ref     = $baseRef
        worktree_dir = $roomWorktreeRoot
    } | Out-Null

    try {
        if (Test-RoomWorktreeDirectory -Path $roomWorktreeRoot) {
            # Existing checkout failed the reuse validation (record missing,
            # branch mismatch, or merged room re-fork) — re-anchor it.
            Invoke-GitWorkspaceCommand -Cwd "$($manifest.source_git_root)" -Arguments @('worktree', 'remove', '--force', $roomWorktreeRoot) -AllowFailure | Out-Null
            Invoke-GitWorkspaceCommand -Cwd "$($manifest.source_git_root)" -Arguments @('worktree', 'prune') -AllowFailure | Out-Null
            if (Test-Path $roomWorktreeRoot) {
                Remove-Item -Path $roomWorktreeRoot -Recurse -Force -ErrorAction SilentlyContinue
            }
        }
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
        Set-WorktreeRuntimeExcludes -WorktreeDir $roomWorktreeRoot

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

function Complete-RoomWorkspaceCommit {
    <#
    .SYNOPSIS
        Commits a finished room's work onto its own branch. The manager then
        calls Complete-PlanWorkspaceMerge -Force so completed dependency rounds
        move into the source branch before downstream rooms start.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$RoomDir,
        [Parameter(Mandatory)][string]$WarRoomsDir
    )

    $manifest = Get-PlanWorkspaceManifest -WarRoomsDir $WarRoomsDir
    if (-not $manifest -or "$($manifest.isolation)" -eq 'shared') {
        Set-RoomWorkspaceStatus -RoomDir $RoomDir -Status 'not_applicable' | Out-Null
        return [pscustomobject]@{ Committed = $true; Status = 'not_applicable' }
    }

    $cfgPath = Join-Path $RoomDir 'config.json'
    $cfg = Get-Content $cfgPath -Raw | ConvertFrom-Json
    $roomId = "$($cfg.room_id)"
    $taskRef = "$($cfg.task_ref)"

    if ($taskRef -eq 'PLAN-REVIEW') {
        Set-RoomWorkspaceStatus -RoomDir $RoomDir -Status 'not_applicable' | Out-Null
        return [pscustomobject]@{ Committed = $true; Status = 'not_applicable' }
    }

    $workspaceRecord = Get-RoomWorkspaceRecord -WarRoomsDir $WarRoomsDir -RoomId $roomId
    if (-not $workspaceRecord) {
        Set-RoomWorkspaceRecord -WarRoomsDir $WarRoomsDir -RoomId $roomId -TaskRef $taskRef -Status 'failed' -Fields @{ error = 'Workspace record missing from manifest.' } | Out-Null
        return [pscustomobject]@{ Committed = $false; Status = 'workspace_missing' }
    }

    $workspace = ConvertTo-WorkspaceHashtable -InputObject $workspaceRecord
    $existingStatus = if ($workspace.Contains('status')) { "$($workspace['status'])" } else { '' }
    if ($existingStatus -eq 'merged') {
        $existingCommit = if ($workspace.Contains('commit')) { "$($workspace['commit'])" } elseif ($workspace.Contains('merged_head')) { "$($workspace['merged_head'])" } else { '' }
        return [pscustomobject]@{
            Committed         = $true
            Status            = 'merged'
            CommitRef         = $existingCommit
            AlreadyIntegrated = $true
        }
    }

    $roomWorktree = "$($workspace['worktree_dir'])"
    $branch = "$($workspace['branch'])"
    if (-not (Test-Path $roomWorktree -PathType Container)) {
        Set-RoomWorkspaceRecord -WarRoomsDir $WarRoomsDir -RoomId $roomId -TaskRef $taskRef -Status 'failed' -Fields @{ error = "Room worktree missing: $roomWorktree" } | Out-Null
        return [pscustomobject]@{ Committed = $false; Status = 'worktree_missing' }
    }

    # Guard for worktrees created before runtime excludes existed.
    Set-WorktreeRuntimeExcludes -WorktreeDir $roomWorktree

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
        foreach ($runtimePath in @('.war-rooms', '.worktree', '.opencode', '.agents/logs', '.agents/plans', '.agents/mcp')) {
            Invoke-GitWorkspaceCommand -Cwd $roomWorktree -Arguments @('reset', '-q', 'HEAD', '--', $runtimePath) -AllowFailure | Out-Null
        }
        $cached = Invoke-GitWorkspaceCommand -Cwd $roomWorktree -Arguments @('diff', '--cached', '--quiet') -AllowFailure
        if ($cached.ExitCode -ne 0) {
            $message = "ostwin: $taskRef $roomId"
            Invoke-GitWorkspaceCommand -Cwd $roomWorktree -Arguments @('-c', 'user.name=ostwin', '-c', 'user.email=ostwin@local', 'commit', '-m', $message) | Out-Null
            $commitCreated = $true
        }
    }

    $commitRef = (Invoke-GitWorkspaceCommand -Cwd $roomWorktree -Arguments @('rev-parse', 'HEAD')).Output.Trim()
    $baseRef = if ($workspace.Contains('base_ref')) { "$($workspace['base_ref'])" } else { '' }
    $noChanges = (-not $commitCreated) -and $baseRef -and ($commitRef -eq $baseRef)

    Set-RoomWorkspaceRecord -WarRoomsDir $WarRoomsDir -RoomId $roomId -TaskRef $taskRef -Status 'committed' -Fields @{
        branch       = $branch
        commit       = $commitRef
        no_changes   = [bool]$noChanges
        committed_at = (Get-Date).ToUniversalTime().ToString('o')
    } | Out-Null

    return [pscustomobject]@{
        Committed = $true
        Status    = 'committed'
        CommitRef = $commitRef
        Branch    = $branch
        NoChanges = [bool]$noChanges
    }
}

function Complete-PlanWorkspaceMerge {
    <#
    .SYNOPSIS
        Merges all committed room branches into the source branch, in
        dependency order. Refuses to run while rooms are still uncommitted
        unless -Force is given (manual partial integration).
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$WarRoomsDir,
        [switch]$Force
    )

    $manifest = Get-PlanWorkspaceManifest -WarRoomsDir $WarRoomsDir
    if (-not $manifest -or "$($manifest.isolation)" -eq 'shared') {
        return [pscustomobject]@{ Integrated = $true; Status = 'not_applicable'; Merged = @(); Pending = @(); Conflicted = '' }
    }

    $rooms = Get-WorkspaceRoomsTable -Manifest $manifest
    $records = @{}
    $queue = @()
    $pending = @()
    foreach ($roomId in @($rooms.Keys)) {
        $record = ConvertTo-WorkspaceHashtable -InputObject $rooms[$roomId]
        $records[$roomId] = $record
        $status = if ($record.Contains('status')) { "$($record['status'])" } else { '' }
        switch ($status) {
            'merged'         { }
            'not_applicable' { }
            'committed'      { $queue += $roomId }
            default          { $pending += "$roomId" }
        }
    }

    if ($pending.Count -gt 0 -and -not $Force) {
        return [pscustomobject]@{ Integrated = $false; Status = 'not_ready'; Merged = @(); Pending = $pending; Conflicted = '' }
    }
    if ($queue.Count -eq 0) {
        $integrated = ($pending.Count -eq 0)
        return [pscustomobject]@{
            Integrated = $integrated
            Status     = if ($integrated) { 'merged' } else { 'partial' }
            Merged     = @()
            Pending    = $pending
            Conflicted = ''
        }
    }

    # Order queued rooms so dependencies merge before their dependents.
    $refToRoom = @{}
    $depsByRoom = @{}
    foreach ($roomId in $queue) {
        $taskRef = if ($records[$roomId].Contains('task_ref')) { "$($records[$roomId]['task_ref'])" } else { '' }
        if ($taskRef) { $refToRoom[$taskRef] = $roomId }
        $deps = @()
        $cfgPath = Join-Path (Join-Path $WarRoomsDir $roomId) 'config.json'
        if (Test-Path $cfgPath) {
            try {
                $cfg = Get-Content $cfgPath -Raw | ConvertFrom-Json
                if ($cfg.PSObject.Properties.Name -contains 'depends_on' -and $cfg.depends_on) {
                    $deps = @($cfg.depends_on | ForEach-Object { "$_" })
                }
            } catch { }
        }
        $depsByRoom[$roomId] = $deps
    }
    $ordered = [System.Collections.Generic.List[string]]::new()
    $remaining = [System.Collections.Generic.List[string]]::new()
    foreach ($r in ($queue | Sort-Object)) { $remaining.Add($r) }
    while ($remaining.Count -gt 0) {
        $progress = $false
        foreach ($roomId in @($remaining)) {
            $blocked = $false
            foreach ($dep in $depsByRoom[$roomId]) {
                if ($refToRoom.ContainsKey($dep) -and $remaining.Contains($refToRoom[$dep]) -and -not $ordered.Contains($refToRoom[$dep])) {
                    $blocked = $true; break
                }
            }
            if (-not $blocked) {
                $ordered.Add($roomId)
                $null = $remaining.Remove($roomId)
                $progress = $true
            }
        }
        if (-not $progress) {
            foreach ($r in @($remaining)) { $ordered.Add($r) }
            break
        }
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
            return [pscustomobject]@{ Integrated = $false; Status = 'source_dirty'; Merged = @(); Pending = $pending; Conflicted = ''; DirtyPaths = $dirtySourceTracked }
        }

        $merged = @()
        foreach ($roomId in $ordered) {
            $record = $records[$roomId]
            $taskRef = if ($record.Contains('task_ref')) { "$($record['task_ref'])" } else { '' }
            $branch = if ($record.Contains('branch')) { "$($record['branch'])" } else { '' }
            $noChanges = $record.Contains('no_changes') -and [bool]$record['no_changes']
            $roomDir = Join-Path $WarRoomsDir $roomId

            if ($noChanges -or -not $branch) {
                Set-RoomWorkspaceRecord -WarRoomsDir $WarRoomsDir -RoomId $roomId -TaskRef $taskRef -Status 'merged' -Fields @{
                    merged_at  = (Get-Date).ToUniversalTime().ToString('o')
                    no_changes = $true
                } | Out-Null
                $merged += $roomId
                continue
            }

            Set-RoomWorkspaceRecord -WarRoomsDir $WarRoomsDir -RoomId $roomId -TaskRef $taskRef -Status 'merging' -Fields @{ branch = $branch } | Out-Null
            $merge = Invoke-GitWorkspaceCommand -Cwd "$($manifest.source_git_root)" -Arguments @('-c', 'user.name=ostwin', '-c', 'user.email=ostwin@local', 'merge', '--no-ff', '--no-edit', $branch) -AllowFailure
            if ($merge.ExitCode -ne 0) {
                # Distinguish "branch adds a path that exists untracked in the
                # source" (git refuses up-front, nothing to abort) from a real
                # content conflict. The user's untracked file is never touched.
                $mergeFailStatus = if ($merge.Output -match 'untracked working tree files would be overwritten') { 'untracked_collision' } else { 'conflicted' }
                $conflicts = (Invoke-GitWorkspaceCommand -Cwd "$($manifest.source_git_root)" -Arguments @('diff', '--name-only', '--diff-filter=U') -AllowFailure).Output
                $conflictFiles = @($conflicts -split "`r?`n" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
                $conflictDetails = [ordered]@{
                    room_id        = $roomId
                    task_ref       = $taskRef
                    branch         = $branch
                    status         = $mergeFailStatus
                    conflict_files = $conflictFiles
                    error          = $merge.Output
                    conflicted_at  = (Get-Date).ToUniversalTime().ToString('o')
                }
                $artifactsDir = Join-Path $roomDir 'artifacts'
                if (-not (Test-Path $artifactsDir)) { New-Item -ItemType Directory -Path $artifactsDir -Force | Out-Null }
                Write-WorkspaceJson -Path (Join-Path $artifactsDir 'workspace-merge-conflict.json') -Value $conflictDetails
                Invoke-GitWorkspaceCommand -Cwd "$($manifest.source_git_root)" -Arguments @('merge', '--abort') -AllowFailure | Out-Null
                Set-RoomWorkspaceRecord -WarRoomsDir $WarRoomsDir -RoomId $roomId -TaskRef $taskRef -Status $mergeFailStatus -Fields @{
                    branch         = $branch
                    conflict_files = $conflictFiles
                    error          = $merge.Output
                    artifact       = 'artifacts/workspace-merge-conflict.json'
                } | Out-Null
                return [pscustomobject]@{ Integrated = $false; Status = $mergeFailStatus; Merged = $merged; Pending = $pending; Conflicted = $roomId; ConflictFiles = $conflictFiles }
            }

            $mergedHead = (Invoke-GitWorkspaceCommand -Cwd "$($manifest.source_git_root)" -Arguments @('rev-parse', 'HEAD')).Output.Trim()
            Update-PlanWorkspaceIntegrationHead -WarRoomsDir $WarRoomsDir -IntegrationHead $mergedHead
            Set-RoomWorkspaceRecord -WarRoomsDir $WarRoomsDir -RoomId $roomId -TaskRef $taskRef -Status 'merged' -Fields @{
                branch      = $branch
                merged_head = $mergedHead
                merged_at   = (Get-Date).ToUniversalTime().ToString('o')
            } | Out-Null
            $merged += $roomId
        }

        $finalManifest = Get-PlanWorkspaceManifest -WarRoomsDir $WarRoomsDir
        $integrationHead = if ($finalManifest -and ($finalManifest.PSObject.Properties.Name -contains 'integration_head')) { "$($finalManifest.integration_head)" } else { '' }
        $integrated = ($pending.Count -eq 0)
        return [pscustomobject]@{
            Integrated      = $integrated
            Status          = if ($integrated) { 'merged' } else { 'partial' }
            Merged          = $merged
            Pending         = $pending
            Conflicted      = ''
            IntegrationHead = $integrationHead
        }
    } finally {
        if ($lockStream) { $lockStream.Dispose() }
    }
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
            foreach ($runtimePath in @('.war-rooms', '.worktree', '.opencode', '.agents/logs', '.agents/plans', '.agents/mcp')) {
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

Export-ModuleMember -Function Test-GitReady, Initialize-PlanIntegrationWorkspace, Ensure-RoomWorktree, Sync-AgentRuntimeOverlay, Get-WorkspaceDependencyState, Get-PlanWorkspaceManifest, Get-RoomWorkspaceRecord, Set-RoomWorkspaceRecord, Set-RoomWorkspaceStatus, Complete-RoomWorkspaceMerge, Complete-RoomWorkspaceCommit, Complete-PlanWorkspaceMerge, Set-WorktreeRuntimeExcludes
