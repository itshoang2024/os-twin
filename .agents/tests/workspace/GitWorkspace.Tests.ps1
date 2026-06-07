BeforeAll {
    $script:WorkspaceModule = Join-Path (Resolve-Path "$PSScriptRoot/../../workspace").Path 'GitWorkspace.psm1'
    Import-Module $script:WorkspaceModule -Force
    $script:PriorEventWsDisabled = $env:OSTWIN_EVENT_WS_DISABLED
    $env:OSTWIN_EVENT_WS_DISABLED = '1'

    function script:Invoke-TestGit {
        param(
            [Parameter(Mandatory)][string]$Cwd,
            [Parameter(Mandatory)][string[]]$Args
        )
        $output = & git -C $Cwd @Args 2>&1
        if ($LASTEXITCODE -ne 0) {
            throw "git -C '$Cwd' $($Args -join ' ') failed: $($output -join "`n")"
        }
        return $output
    }

    function script:New-TestRepo {
        param([Parameter(Mandatory)][string]$Name)

        $repo = Join-Path $TestDrive $Name
        New-Item -ItemType Directory -Path $repo -Force | Out-Null
        Invoke-TestGit -Cwd $repo -Args @('init') | Out-Null
        Invoke-TestGit -Cwd $repo -Args @('config', 'user.name', 'Test User') | Out-Null
        Invoke-TestGit -Cwd $repo -Args @('config', 'user.email', 'test@example.local') | Out-Null
        'base' | Out-File -FilePath (Join-Path $repo 'README.md') -Encoding utf8
        Invoke-TestGit -Cwd $repo -Args @('add', 'README.md') | Out-Null
        Invoke-TestGit -Cwd $repo -Args @('commit', '-m', 'base') | Out-Null
        return $repo
    }
}

AfterAll {
    $env:OSTWIN_EVENT_WS_DISABLED = $script:PriorEventWsDisabled
}

Describe 'GitWorkspace preflight' {
    It 'fails outside a Git work tree' {
        $dir = Join-Path $TestDrive 'not-git'
        New-Item -ItemType Directory -Path $dir -Force | Out-Null

        $result = Test-GitReady -WorkingDir $dir -AllowRuntimeState

        $result.Ready | Should -BeFalse
        $result.Reason | Should -Be 'not_git_worktree'
    }

    It 'fails when tracked files are dirty' {
        $repo = New-TestRepo -Name 'dirty-tracked'
        'changed' | Out-File -FilePath (Join-Path $repo 'README.md') -Encoding utf8

        $result = Test-GitReady -WorkingDir $repo -AllowRuntimeState

        $result.Ready | Should -BeFalse
        $result.Reason | Should -Be 'dirty_tracked_files'
    }

    It 'allows generated untracked Ostwin runtime state' {
        $repo = New-TestRepo -Name 'runtime-only'
        $runtimeDir = Join-Path $repo '.agents/plans'
        New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
        '{}' | Out-File -FilePath (Join-Path $runtimeDir 'plan.meta.json') -Encoding utf8

        $result = Test-GitReady -WorkingDir $repo -AllowRuntimeState

        $result.Ready | Should -BeTrue
        $result.BaseRef | Should -Not -BeNullOrEmpty
    }
}

Describe 'GitWorkspace lazy room worktrees' {
    It 'creates a room worktree from the current integration head' {
        $repo = New-TestRepo -Name 'lazy-base'
        $warRoomsDir = Join-Path $TestDrive 'war-rooms-lazy'
        $worktreeRoot = Join-Path $TestDrive 'worktrees-lazy'

        $manifest = Initialize-PlanIntegrationWorkspace -WarRoomsDir $warRoomsDir -PlanId 'plan-test' -RunId 'run-test' -SourceWorkingDir $repo -WorkspaceIsolation room-worktree -WorktreeRoot $worktreeRoot
        'integration change' | Out-File -FilePath (Join-Path $manifest.integration_worktree_dir 'integration.txt') -Encoding utf8
        Invoke-TestGit -Cwd $manifest.integration_worktree_dir -Args @('add', 'integration.txt') | Out-Null
        Invoke-TestGit -Cwd $manifest.integration_worktree_dir -Args @('commit', '-m', 'integration change') | Out-Null
        $integrationHead = (Invoke-TestGit -Cwd $manifest.integration_worktree_dir -Args @('rev-parse', 'HEAD') | Select-Object -First 1).Trim()

        $roomDir = Join-Path $warRoomsDir 'room-001'
        New-Item -ItemType Directory -Path $roomDir -Force | Out-Null
        @{
            room_id = 'room-001'
            task_ref = 'EPIC-001'
            plan_id = 'plan-test'
            run_id = 'run-test'
            working_dir = $repo
            depends_on = @()
        } | ConvertTo-Json -Depth 8 | Out-File (Join-Path $roomDir 'config.json') -Encoding utf8

        $result = Ensure-RoomWorktree -RoomDir $roomDir -WarRoomsDir $warRoomsDir
        $config = Get-Content (Join-Path $roomDir 'config.json') -Raw | ConvertFrom-Json
        $record = Get-RoomWorkspaceRecord -WarRoomsDir $warRoomsDir -RoomId 'room-001'

        $result.Ready | Should -BeTrue
        $config.PSObject.Properties.Name | Should -Not -Contain 'workspace'
        $record.status | Should -Be 'ready'
        $record.base_ref | Should -Be $integrationHead
        Test-Path (Join-Path $record.worktree_dir 'integration.txt') | Should -BeTrue
    }

    It 'does not unblock dependencies that are done but not merged' {
        $repo = New-TestRepo -Name 'dep-state'
        $warRoomsDir = Join-Path $TestDrive 'war-rooms-deps'
        Initialize-PlanIntegrationWorkspace -WarRoomsDir $warRoomsDir -PlanId 'plan-test' -RunId 'run-test' -SourceWorkingDir $repo -WorkspaceIsolation room-worktree -WorktreeRoot (Join-Path $TestDrive 'worktrees-deps') | Out-Null

        $depRoom = Join-Path $warRoomsDir 'room-001'
        $nextRoom = Join-Path $warRoomsDir 'room-002'
        New-Item -ItemType Directory -Path $depRoom, $nextRoom -Force | Out-Null
        'done' | Out-File (Join-Path $depRoom 'status') -Encoding utf8 -NoNewline
        @{
            room_id = 'room-001'
            task_ref = 'EPIC-001'
        } | ConvertTo-Json -Depth 6 | Out-File (Join-Path $depRoom 'config.json') -Encoding utf8
        Set-RoomWorkspaceRecord -WarRoomsDir $warRoomsDir -RoomId 'room-001' -TaskRef 'EPIC-001' -Status 'ready' | Out-Null
        @{
            room_id = 'room-002'
            task_ref = 'EPIC-002'
            depends_on = @('EPIC-001')
        } | ConvertTo-Json -Depth 6 | Out-File (Join-Path $nextRoom 'config.json') -Encoding utf8

        $state = Get-WorkspaceDependencyState -RoomDir $nextRoom -WarRoomsDir $warRoomsDir

        $state.Ready | Should -BeFalse
        $state.BlockedBy | Should -Contain 'EPIC-001:not-merged'
    }

    It 'unblocks dependencies when predecessor is done and manifest is merged' {
        $repo = New-TestRepo -Name 'dep-state-merged'
        $warRoomsDir = Join-Path $TestDrive 'war-rooms-deps-merged'
        Initialize-PlanIntegrationWorkspace -WarRoomsDir $warRoomsDir -PlanId 'plan-test' -RunId 'run-test' -SourceWorkingDir $repo -WorkspaceIsolation room-worktree -WorktreeRoot (Join-Path $TestDrive 'worktrees-deps-merged') | Out-Null

        $depRoom = Join-Path $warRoomsDir 'room-001'
        $nextRoom = Join-Path $warRoomsDir 'room-002'
        New-Item -ItemType Directory -Path $depRoom, $nextRoom -Force | Out-Null
        'done' | Out-File (Join-Path $depRoom 'status') -Encoding utf8 -NoNewline
        @{ room_id = 'room-001'; task_ref = 'EPIC-001' } | ConvertTo-Json -Depth 6 | Out-File (Join-Path $depRoom 'config.json') -Encoding utf8
        Set-RoomWorkspaceRecord -WarRoomsDir $warRoomsDir -RoomId 'room-001' -TaskRef 'EPIC-001' -Status 'merged' | Out-Null
        @{ room_id = 'room-002'; task_ref = 'EPIC-002'; depends_on = @('EPIC-001') } | ConvertTo-Json -Depth 6 | Out-File (Join-Path $nextRoom 'config.json') -Encoding utf8

        $state = Get-WorkspaceDependencyState -RoomDir $nextRoom -WarRoomsDir $warRoomsDir

        $state.Ready | Should -BeTrue
    }

    It 'records merge conflicts in the manifest and room artifact' {
        $repo = New-TestRepo -Name 'merge-conflict'
        $warRoomsDir = Join-Path $TestDrive 'war-rooms-conflict'
        $manifest = Initialize-PlanIntegrationWorkspace -WarRoomsDir $warRoomsDir -PlanId 'plan-test' -RunId 'run-test' -SourceWorkingDir $repo -WorkspaceIsolation room-worktree -WorktreeRoot (Join-Path $TestDrive 'worktrees-conflict')

        $roomDir = Join-Path $warRoomsDir 'room-001'
        New-Item -ItemType Directory -Path $roomDir -Force | Out-Null
        @{
            room_id = 'room-001'
            task_ref = 'EPIC-001'
            plan_id = 'plan-test'
            run_id = 'run-test'
            working_dir = $repo
            depends_on = @()
        } | ConvertTo-Json -Depth 8 | Out-File (Join-Path $roomDir 'config.json') -Encoding utf8

        $ready = Ensure-RoomWorktree -RoomDir $roomDir -WarRoomsDir $warRoomsDir
        'room change' | Out-File -FilePath (Join-Path $ready.WorkingDir 'README.md') -Encoding utf8

        'integration change' | Out-File -FilePath (Join-Path $manifest.integration_worktree_dir 'README.md') -Encoding utf8
        Invoke-TestGit -Cwd $manifest.integration_worktree_dir -Args @('add', 'README.md') | Out-Null
        Invoke-TestGit -Cwd $manifest.integration_worktree_dir -Args @('commit', '-m', 'integration diverged') | Out-Null

        $merge = Complete-RoomWorkspaceMerge -RoomDir $roomDir -WarRoomsDir $warRoomsDir
        $record = Get-RoomWorkspaceRecord -WarRoomsDir $warRoomsDir -RoomId 'room-001'

        $merge.Integrated | Should -BeFalse
        $merge.Status | Should -Be 'conflicted'
        $record.status | Should -Be 'conflicted'
        $record.conflict_files | Should -Contain 'README.md'
        Test-Path (Join-Path $roomDir 'artifacts/workspace-merge-conflict.json') | Should -BeTrue
    }
}
