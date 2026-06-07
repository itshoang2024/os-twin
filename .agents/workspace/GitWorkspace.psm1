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
    foreach ($prefix in @(
        '.war-rooms/',
        '.opencode/',
        '.agents/logs/',
        '.agents/plans/',
        '.agents/mcp/'
    )) {
        if ($normalized.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
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
        [Parameter(Mandatory)][string]$PlanId,
        [Parameter(Mandatory)][string]$RunId
    )

    $homeDir = if ($env:HOME) { $env:HOME } elseif ($env:USERPROFILE) { $env:USERPROFILE } else { [Environment]::GetFolderPath('UserProfile') }
    $ostwinHome = if ($env:OSTWIN_HOME) { $env:OSTWIN_HOME } else { Join-Path $homeDir '.ostwin' }
    $repoHash = Get-WorkspaceShortHash -Value $SourceGitRoot
    return (Join-Path (Join-Path (Join-Path (Join-Path $ostwinHome 'worktrees') $repoHash) (Get-WorkspaceSafeSlug -Value $PlanId)) (Get-WorkspaceSafeSlug -Value $RunId))
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
            $dirtyTracked += $path
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

function Write-WorkspaceEvent {
    param(
        [Parameter(Mandatory)][string]$EventType,
        [Parameter(Mandatory)][string]$PlanId,
        [Parameter(Mandatory)][string]$RunId,
        [Parameter(Mandatory)][string]$Summary,
        [hashtable]$Payload = @{},
        [string]$EventsPath = '',
        [string]$RoomId = '',
        [string]$EpicRef = '',
        [string]$Severity = 'info'
    )

    if (-not (Get-Command Write-OrchestrationEvent -ErrorAction SilentlyContinue)) { return $null }
    if ([string]::IsNullOrWhiteSpace($PlanId)) { return $null }
    if ([string]::IsNullOrWhiteSpace($RunId)) { return $null }

    $event = [ordered]@{
        event_type = $EventType
        plan_id    = $PlanId
        run_id     = $RunId
        severity   = $Severity
        summary    = $Summary
        payload    = [ordered]@{}
    }
    foreach ($key in $Payload.Keys) { $event.payload[$key] = $Payload[$key] }
    if ($RoomId) { $event['room_id'] = $RoomId }
    if ($EpicRef) { $event['epic_ref'] = $EpicRef }

    return (Write-OrchestrationEvent -EventsPath $EventsPath -Event $event)
}

function Initialize-PlanIntegrationWorkspace {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$WarRoomsDir,
        [Parameter(Mandatory)][string]$PlanId,
        [Parameter(Mandatory)][string]$RunId,
        [Parameter(Mandatory)][string]$SourceWorkingDir,
        [ValidateSet('room-worktree','shared')][string]$WorkspaceIsolation = 'room-worktree',
        [string]$WorktreeRoot = ''
    )

    if (-not (Test-Path $WarRoomsDir)) {
        New-Item -ItemType Directory -Path $WarRoomsDir -Force | Out-Null
    }

    if ($WorkspaceIsolation -eq 'shared') {
        $manifest = [ordered]@{
            version            = 1
            isolation          = 'shared'
            plan_id            = $PlanId
            run_id             = $RunId
            source_working_dir = (Resolve-Path $SourceWorkingDir).Path
            status             = 'not_applicable'
            created_at         = (Get-Date).ToUniversalTime().ToString('o')
        }
        Write-WorkspaceJson -Path (Get-PlanWorkspaceManifestPath -WarRoomsDir $WarRoomsDir) -Value $manifest
        return [pscustomobject]$manifest
    }

    $ready = Test-GitReady -WorkingDir $SourceWorkingDir -AllowRuntimeState
    if (-not $ready.Ready) {
        Write-WorkspaceEvent -EventType 'workspace.git.preflight.failed' -PlanId $PlanId -RunId $RunId -Summary "Git preflight failed for $PlanId." -Payload @{ reason = $ready.Reason; message = $ready.Message; working_dir = $SourceWorkingDir } -Severity 'error' | Out-Null
        throw $ready.Message
    }

    Write-WorkspaceEvent -EventType 'workspace.git.preflight.passed' -PlanId $PlanId -RunId $RunId -Summary "Git preflight passed for $PlanId." -Payload @{
        source_git_root    = $ready.SourceGitRoot
        source_working_dir = $ready.WorkingDir
        base_ref           = $ready.BaseRef
        base_branch        = $ready.BaseBranch
    } | Out-Null

    if ([string]::IsNullOrWhiteSpace($WorktreeRoot)) {
        $WorktreeRoot = Get-DefaultWorktreeRoot -SourceGitRoot $ready.SourceGitRoot -PlanId $PlanId -RunId $RunId
    }
    $WorktreeRoot = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($WorktreeRoot)
    $integrationWorktree = Join-Path $WorktreeRoot 'integration'
    $integrationBranch = "ostwin/$((Get-WorkspaceSafeSlug -Value $PlanId -MaxLength 48))/$((Get-WorkspaceSafeSlug -Value $RunId -MaxLength 48))/integration"

    New-Item -ItemType Directory -Path $WorktreeRoot -Force | Out-Null
    if (-not (Test-Path $integrationWorktree)) {
        Invoke-GitWorkspaceCommand -Cwd $ready.SourceGitRoot -Arguments @('worktree', 'add', '-B', $integrationBranch, $integrationWorktree, $ready.BaseRef) | Out-Null
    }
    $integrationHead = (Invoke-GitWorkspaceCommand -Cwd $integrationWorktree -Arguments @('rev-parse', 'HEAD')).Output.Trim()

    $manifest = [ordered]@{
        version                  = 1
        isolation                = 'room-worktree'
        plan_id                  = $PlanId
        run_id                   = $RunId
        source_git_root          = $ready.SourceGitRoot
        source_working_dir       = $ready.WorkingDir
        source_relative_dir      = $ready.SourceRelativeDir
        base_ref                 = $ready.BaseRef
        base_branch              = $ready.BaseBranch
        integration_branch       = $integrationBranch
        integration_worktree_dir = $integrationWorktree
        integration_head         = $integrationHead
        worktree_root            = $WorktreeRoot
        status                   = 'ready'
        created_at               = (Get-Date).ToUniversalTime().ToString('o')
    }

    Write-WorkspaceEvent -EventType 'workspace.integration.ready' -PlanId $PlanId -RunId $RunId -Summary "Integration workspace ready for $PlanId." -Payload @{
        integration_branch       = $integrationBranch
        integration_worktree_dir = $integrationWorktree
        integration_head         = $integrationHead
        worktree_root            = $WorktreeRoot
    } | Out-Null

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
    $workspace = if ($cfg.PSObject.Properties.Name -contains 'workspace' -and $cfg.workspace) {
        ConvertTo-WorkspaceHashtable -InputObject $cfg.workspace
    } else {
        [ordered]@{}
    }
    $workspace['status'] = $Status
    $workspace['updated_at'] = (Get-Date).ToUniversalTime().ToString('o')
    foreach ($key in $Fields.Keys) { $workspace[$key] = $Fields[$key] }

    if ($cfg.PSObject.Properties.Name -contains 'workspace') {
        $cfg.workspace = $workspace
    } else {
        $cfg | Add-Member -NotePropertyName workspace -NotePropertyValue $workspace
    }
    Write-WorkspaceJson -Path $cfgPath -Value $cfg
    return $cfg
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
        $workspaceStatus = if ($depCfg.PSObject.Properties.Name -contains 'workspace' -and $depCfg.workspace -and ($depCfg.workspace.PSObject.Properties.Name -contains 'status')) { "$($depCfg.workspace.status)" } else { '' }
        if ($depStatus -ne 'passed') {
            $blocked += "${dep}:not-passed"
        } elseif ($workspaceStatus -notin @('integrated', 'not_applicable')) {
            $blocked += "${dep}:not-integrated"
        }
    }

    return [pscustomobject]@{
        Ready     = ($blocked.Count -eq 0)
        Reason    = if ($blocked.Count -eq 0) { 'ready' } else { 'dependencies_not_integrated' }
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
    $eventsPath = if ($cfg.PSObject.Properties.Name -contains 'events_path') { "$($cfg.events_path)" } else { '' }

    if ($taskRef -eq 'PLAN-REVIEW') {
        Set-RoomWorkspaceStatus -RoomDir $RoomDir -Status 'not_applicable' | Out-Null
        return [pscustomobject]@{ Ready = $true; Mode = 'plan-review'; WorkingDir = "$($cfg.working_dir)" }
    }

    if ($cfg.PSObject.Properties.Name -contains 'workspace' -and $cfg.workspace) {
        $existingStatus = if ($cfg.workspace.PSObject.Properties.Name -contains 'status') { "$($cfg.workspace.status)" } else { '' }
        $existingDir = if ($cfg.workspace.PSObject.Properties.Name -contains 'working_dir') { "$($cfg.workspace.working_dir)" } else { '' }
        if ($existingStatus -in @('ready', 'integrated') -and $existingDir -and (Test-Path $existingDir -PathType Container)) {
            return [pscustomobject]@{ Ready = $true; Mode = 'room-worktree'; WorkingDir = $existingDir; Reused = $true }
        }
    }

    $roomSlug = Get-WorkspaceSafeSlug -Value "$taskRef-$roomId" -MaxLength 96
    $roomWorktreeRoot = Join-Path $manifest.worktree_root $roomSlug
    $branch = "ostwin/$((Get-WorkspaceSafeSlug -Value $manifest.plan_id -MaxLength 48))/$((Get-WorkspaceSafeSlug -Value $manifest.run_id -MaxLength 48))/$roomSlug"
    $baseRef = (Invoke-GitWorkspaceCommand -Cwd $manifest.integration_worktree_dir -Arguments @('rev-parse', 'HEAD')).Output.Trim()

    Write-WorkspaceEvent -EventType 'workspace.worktree.requested' -PlanId $manifest.plan_id -RunId $manifest.run_id -RoomId $roomId -EpicRef $taskRef -EventsPath $eventsPath -Summary "Worktree requested for $taskRef." -Payload @{
        room_id   = $roomId
        task_ref  = $taskRef
        branch    = $branch
        base_ref  = $baseRef
        worktree  = $roomWorktreeRoot
    } | Out-Null

    try {
        if (-not (Test-Path $roomWorktreeRoot)) {
            Invoke-GitWorkspaceCommand -Cwd $manifest.source_git_root -Arguments @('worktree', 'add', '-B', $branch, $roomWorktreeRoot, $baseRef) | Out-Null
        }
        Sync-AgentRuntimeOverlay -SourceGitRoot $manifest.source_git_root -RoomWorktreeRoot $roomWorktreeRoot -AgentsDir $AgentsDir
        $relativeDir = ''
        if ($cfg.PSObject.Properties.Name -contains 'workspace' -and $cfg.workspace -and ($cfg.workspace.PSObject.Properties.Name -contains 'source_relative_dir') -and "$($cfg.workspace.source_relative_dir)" -ne '.') {
            $relativeDir = "$($cfg.workspace.source_relative_dir)"
        } elseif ($manifest.PSObject.Properties.Name -contains 'source_relative_dir' -and "$($manifest.source_relative_dir)" -ne '.') {
            $relativeDir = "$($manifest.source_relative_dir)"
        }
        $roomWorkingDir = if ($relativeDir) { Join-Path $roomWorktreeRoot $relativeDir } else { $roomWorktreeRoot }
        if (-not (Test-Path $roomWorkingDir)) { New-Item -ItemType Directory -Path $roomWorkingDir -Force | Out-Null }

        $workspace = [ordered]@{
            mode          = 'git-worktree'
            status        = 'ready'
            branch        = $branch
            base_ref      = $baseRef
            worktree_dir  = $roomWorktreeRoot
            working_dir   = $roomWorkingDir
            requested_at  = (Get-Date).ToUniversalTime().ToString('o')
            ready_at      = (Get-Date).ToUniversalTime().ToString('o')
        }
        $cfg.working_dir = $roomWorkingDir
        if ($cfg.PSObject.Properties.Name -contains 'workspace') {
            $cfg.workspace = $workspace
        } else {
            $cfg | Add-Member -NotePropertyName workspace -NotePropertyValue $workspace
        }
        Write-WorkspaceEvent -EventType 'workspace.worktree.ready' -PlanId $manifest.plan_id -RunId $manifest.run_id -RoomId $roomId -EpicRef $taskRef -EventsPath $eventsPath -Summary "Worktree ready for $taskRef." -Payload @{
            room_id     = $roomId
            task_ref    = $taskRef
            branch      = $branch
            base_ref    = $baseRef
            worktree    = $roomWorktreeRoot
            working_dir = $roomWorkingDir
        } | Out-Null
        Write-WorkspaceJson -Path $cfgPath -Value $cfg
        return [pscustomobject]@{ Ready = $true; Mode = 'room-worktree'; WorkingDir = $roomWorkingDir; BaseRef = $baseRef; Branch = $branch }
    } catch {
        Write-WorkspaceEvent -EventType 'workspace.worktree.failed' -PlanId $manifest.plan_id -RunId $manifest.run_id -RoomId $roomId -EpicRef $taskRef -EventsPath $eventsPath -Summary "Worktree failed for $taskRef." -Severity 'error' -Payload @{
            room_id = $roomId
            task_ref = $taskRef
            error = $_.Exception.Message
        } | Out-Null
        Set-RoomWorkspaceStatus -RoomDir $RoomDir -Status 'failed' -Fields @{ error = $_.Exception.Message } | Out-Null
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
    $manifest.integration_head = $IntegrationHead
    $manifest.updated_at = (Get-Date).ToUniversalTime().ToString('o')
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
    $eventsPath = if ($cfg.PSObject.Properties.Name -contains 'events_path') { "$($cfg.events_path)" } else { '' }

    if ($taskRef -eq 'PLAN-REVIEW') {
        Set-RoomWorkspaceStatus -RoomDir $RoomDir -Status 'not_applicable' | Out-Null
        return [pscustomobject]@{ Integrated = $true; Status = 'not_applicable' }
    }

    if ($cfg.PSObject.Properties.Name -contains 'workspace' -and $cfg.workspace -and $cfg.workspace.PSObject.Properties.Name -contains 'status' -and "$($cfg.workspace.status)" -eq 'integrated') {
        return [pscustomobject]@{ Integrated = $true; Status = 'integrated'; Reused = $true }
    }
    if ($cfg.PSObject.Properties.Name -contains 'workspace' -and $cfg.workspace -and $cfg.workspace.PSObject.Properties.Name -contains 'status' -and "$($cfg.workspace.status)" -eq 'merge-conflicted') {
        return [pscustomobject]@{ Integrated = $false; Status = 'merge-conflicted' }
    }
    if (-not ($cfg.PSObject.Properties.Name -contains 'workspace') -or -not $cfg.workspace) {
        return [pscustomobject]@{ Integrated = $false; Status = 'workspace_missing' }
    }

    $workspace = ConvertTo-WorkspaceHashtable -InputObject $cfg.workspace
    $roomWorktree = "$($workspace['worktree_dir'])"
    $branch = "$($workspace['branch'])"
    if (-not (Test-Path $roomWorktree -PathType Container)) {
        Set-RoomWorkspaceStatus -RoomDir $RoomDir -Status 'failed' -Fields @{ error = "Room worktree missing: $roomWorktree" } | Out-Null
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
                Write-WorkspaceEvent -EventType 'workspace.room.committed' -PlanId $manifest.plan_id -RunId $manifest.run_id -RoomId $roomId -EpicRef $taskRef -EventsPath $eventsPath -Summary "Room $taskRef committed." -Payload @{
                    room_id = $roomId
                    task_ref = $taskRef
                    branch = $branch
                    commit = $commitRef
                } | Out-Null
            }
        }

        $roomHead = (Invoke-GitWorkspaceCommand -Cwd $roomWorktree -Arguments @('rev-parse', 'HEAD')).Output.Trim()
        $baseRef = if ($workspace.Contains('base_ref')) { "$($workspace['base_ref'])" } else { '' }
        if (-not $commitCreated -and $baseRef -and $roomHead -eq $baseRef) {
            Write-WorkspaceEvent -EventType 'workspace.merge.completed' -PlanId $manifest.plan_id -RunId $manifest.run_id -RoomId $roomId -EpicRef $taskRef -EventsPath $eventsPath -Summary "No workspace changes to merge for $taskRef." -Payload @{
                room_id = $roomId
                task_ref = $taskRef
                branch = $branch
                integration_branch = $manifest.integration_branch
                no_changes = $true
            } | Out-Null
            Set-RoomWorkspaceStatus -RoomDir $RoomDir -Status 'integrated' -Fields @{ integrated_at = (Get-Date).ToUniversalTime().ToString('o'); no_changes = $true } | Out-Null
            return [pscustomobject]@{ Integrated = $true; Status = 'integrated'; NoChanges = $true }
        }

        Write-WorkspaceEvent -EventType 'workspace.merge.requested' -PlanId $manifest.plan_id -RunId $manifest.run_id -RoomId $roomId -EpicRef $taskRef -EventsPath $eventsPath -Summary "Merge requested for $taskRef." -Payload @{
            room_id = $roomId
            task_ref = $taskRef
            branch = $branch
            integration_branch = $manifest.integration_branch
        } | Out-Null
        Write-WorkspaceEvent -EventType 'workspace.merge.started' -PlanId $manifest.plan_id -RunId $manifest.run_id -RoomId $roomId -EpicRef $taskRef -EventsPath $eventsPath -Summary "Merge started for $taskRef." -Payload @{
            room_id = $roomId
            task_ref = $taskRef
            branch = $branch
            integration_branch = $manifest.integration_branch
        } | Out-Null

        $merge = Invoke-GitWorkspaceCommand -Cwd $manifest.integration_worktree_dir -Arguments @('-c', 'user.name=ostwin', '-c', 'user.email=ostwin@local', 'merge', '--no-ff', '--no-edit', $branch) -AllowFailure
        if ($merge.ExitCode -ne 0) {
            $conflicts = (Invoke-GitWorkspaceCommand -Cwd $manifest.integration_worktree_dir -Arguments @('diff', '--name-only', '--diff-filter=U') -AllowFailure).Output
            $conflictFiles = @($conflicts -split "`r?`n" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
            Write-WorkspaceEvent -EventType 'workspace.merge.conflicted' -PlanId $manifest.plan_id -RunId $manifest.run_id -RoomId $roomId -EpicRef $taskRef -EventsPath $eventsPath -Severity 'error' -Summary "Merge conflicted for $taskRef." -Payload @{
                room_id = $roomId
                task_ref = $taskRef
                branch = $branch
                integration_branch = $manifest.integration_branch
                conflict_files = $conflictFiles
                error = $merge.Output
            } | Out-Null
            Set-RoomWorkspaceStatus -RoomDir $RoomDir -Status 'merge-conflicted' -Fields @{ conflict_files = $conflictFiles; error = $merge.Output } | Out-Null
            return [pscustomobject]@{ Integrated = $false; Status = 'merge-conflicted'; ConflictFiles = $conflictFiles }
        }

        $integrationHead = (Invoke-GitWorkspaceCommand -Cwd $manifest.integration_worktree_dir -Arguments @('rev-parse', 'HEAD')).Output.Trim()
        Write-WorkspaceEvent -EventType 'workspace.merge.completed' -PlanId $manifest.plan_id -RunId $manifest.run_id -RoomId $roomId -EpicRef $taskRef -EventsPath $eventsPath -Summary "Merge completed for $taskRef." -Payload @{
            room_id = $roomId
            task_ref = $taskRef
            branch = $branch
            integration_branch = $manifest.integration_branch
            integration_head = $integrationHead
        } | Out-Null
        Update-PlanWorkspaceIntegrationHead -WarRoomsDir $WarRoomsDir -IntegrationHead $integrationHead
        Set-RoomWorkspaceStatus -RoomDir $RoomDir -Status 'integrated' -Fields @{ integrated_at = (Get-Date).ToUniversalTime().ToString('o'); integration_head = $integrationHead } | Out-Null
        return [pscustomobject]@{ Integrated = $true; Status = 'integrated'; IntegrationHead = $integrationHead }
    } finally {
        if ($lockStream) { $lockStream.Dispose() }
    }
}

Export-ModuleMember -Function Test-GitReady, Initialize-PlanIntegrationWorkspace, Ensure-RoomWorktree, Sync-AgentRuntimeOverlay, Get-WorkspaceDependencyState, Get-PlanWorkspaceManifest, Set-RoomWorkspaceStatus, Complete-RoomWorkspaceMerge
