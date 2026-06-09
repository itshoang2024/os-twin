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

    It 'allows generated runtime state under the ostwin run working directory' {
        $repo = New-TestRepo -Name 'nested-runtime-only'
        $sourceDir = Join-Path $repo 'app'
        New-Item -ItemType Directory -Path $sourceDir -Force | Out-Null
        'app' | Out-File -FilePath (Join-Path $sourceDir 'app.txt') -Encoding utf8
        Invoke-TestGit -Cwd $repo -Args @('add', 'app/app.txt') | Out-Null
        Invoke-TestGit -Cwd $repo -Args @('commit', '-m', 'add app') | Out-Null
        $runtimeDir = Join-Path $sourceDir '.worktree/room-001'
        New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
        '{}' | Out-File -FilePath (Join-Path $runtimeDir 'config.json') -Encoding utf8

        $result = Test-GitReady -WorkingDir $sourceDir -AllowRuntimeState

        $result.Ready | Should -BeTrue
        $result.BaseRef | Should -Not -BeNullOrEmpty
    }
}

Describe 'GitWorkspace lazy room worktrees' {
    It 'creates a room worktree under source .worktree and keeps room state in .war-rooms' {
        $repo = New-TestRepo -Name 'lazy-base'
        $warRoomsDir = Join-Path $TestDrive 'war-rooms-lazy'

        $manifest = Initialize-PlanIntegrationWorkspace -WarRoomsDir $warRoomsDir -PlanId 'plan-test' -RunId 'run-test' -SourceWorkingDir $repo -WorkspaceIsolation room-worktree
        $sourceHead = (Invoke-TestGit -Cwd $repo -Args @('rev-parse', 'HEAD') | Select-Object -First 1).Trim()

        $roomDir = Join-Path $warRoomsDir 'room-001'
        New-Item -ItemType Directory -Path $roomDir -Force | Out-Null
        @{
            room_id = 'room-001'
            task_ref = 'EPIC-001'
            plan_id = 'plan-test'
            run_id = 'run-test'
            working_dir = $repo
            depends_on = @()
            assignment = @{ title = 'Build checkout API' }
        } | ConvertTo-Json -Depth 8 | Out-File (Join-Path $roomDir 'config.json') -Encoding utf8
        '{}' | Out-File (Join-Path $roomDir 'lifecycle.json') -Encoding utf8

        $result = Ensure-RoomWorktree -RoomDir $roomDir -WarRoomsDir $warRoomsDir
        $config = Get-Content (Join-Path $roomDir 'config.json') -Raw | ConvertFrom-Json
        $record = Get-RoomWorkspaceRecord -WarRoomsDir $warRoomsDir -RoomId 'room-001'

        $result.Ready | Should -BeTrue
        $manifest.worktree_root | Should -Be (Join-Path $repo '.worktree')
        $config.PSObject.Properties.Name | Should -Not -Contain 'workspace'
        $config.working_dir | Should -Be (Join-Path (Join-Path $repo '.worktree') 'room-001')
        $record.status | Should -Be 'ready'
        $record.base_ref | Should -Be $sourceHead
        $record.worktree_dir | Should -Be (Join-Path (Join-Path $repo '.worktree') 'room-001')
        Test-Path (Join-Path $roomDir 'lifecycle.json') | Should -BeTrue
    }

    It 'places the managed worktree root under the ostwin run working directory' {
        $repo = New-TestRepo -Name 'run-subdir-root'
        $sourceDir = Join-Path $repo 'app'
        New-Item -ItemType Directory -Path $sourceDir -Force | Out-Null
        'app' | Out-File -FilePath (Join-Path $sourceDir 'app.txt') -Encoding utf8
        Invoke-TestGit -Cwd $repo -Args @('add', 'app/app.txt') | Out-Null
        Invoke-TestGit -Cwd $repo -Args @('commit', '-m', 'add app') | Out-Null
        $warRoomsDir = Join-Path $TestDrive 'war-rooms-run-subdir'

        $manifest = Initialize-PlanIntegrationWorkspace -WarRoomsDir $warRoomsDir -PlanId 'plan-test' -RunId 'run-test' -SourceWorkingDir $sourceDir -WorkspaceIsolation room-worktree

        $manifest.worktree_root | Should -Be (Join-Path $sourceDir '.worktree')
        $manifest.source_git_root | Should -Be $repo
        $manifest.source_working_dir | Should -Be $sourceDir
        $manifest.source_relative_dir | Should -Be 'app'
    }

    It 'provisions the room worktree when a ready record points at a missing worktree' {
        $repo = New-TestRepo -Name 'stale-ready-record'
        $warRoomsDir = Join-Path $TestDrive 'war-rooms-stale-ready'
        Initialize-PlanIntegrationWorkspace -WarRoomsDir $warRoomsDir -PlanId 'plan-test' -RunId 'run-test' -SourceWorkingDir $repo -WorkspaceIsolation room-worktree | Out-Null

        $roomDir = Join-Path $warRoomsDir 'room-001'
        New-Item -ItemType Directory -Path $roomDir -Force | Out-Null
        @{
            room_id = 'room-001'
            task_ref = 'EPIC-001'
            plan_id = 'plan-test'
            run_id = 'run-test'
            working_dir = $repo
            depends_on = @()
            assignment = @{ title = 'Provision stale worktree' }
        } | ConvertTo-Json -Depth 8 | Out-File (Join-Path $roomDir 'config.json') -Encoding utf8
        $expectedWorktree = Join-Path (Join-Path $repo '.worktree') 'room-001'
        Set-RoomWorkspaceRecord -WarRoomsDir $warRoomsDir -RoomId 'room-001' -TaskRef 'EPIC-001' -Status 'ready' -Fields @{
            worktree_dir = $expectedWorktree
            working_dir = $expectedWorktree
        } | Out-Null

        $result = Ensure-RoomWorktree -RoomDir $roomDir -WarRoomsDir $warRoomsDir

        $result.Ready | Should -BeTrue
        $result.Reused | Should -BeNullOrEmpty
        $result.WorkingDir | Should -Be $expectedWorktree
        Test-Path (Join-Path $expectedWorktree '.git') | Should -BeTrue
    }

    It 'does not derive nested worktree paths from a persisted room working_dir' {
        $repo = New-TestRepo -Name 'nested-working-dir'
        $warRoomsDir = Join-Path $TestDrive 'war-rooms-nested-working-dir'
        Initialize-PlanIntegrationWorkspace -WarRoomsDir $warRoomsDir -PlanId 'plan-test' -RunId 'run-test' -SourceWorkingDir $repo -WorkspaceIsolation room-worktree | Out-Null

        $roomDir = Join-Path $warRoomsDir 'room-001'
        New-Item -ItemType Directory -Path $roomDir -Force | Out-Null
        $roomWorktree = Join-Path (Join-Path $repo '.worktree') 'room-001'
        $nestedWorkingDir = Join-Path $roomWorktree '.worktree/room-001'
        @{
            room_id = 'room-001'
            task_ref = 'EPIC-001'
            plan_id = 'plan-test'
            run_id = 'run-test'
            working_dir = $nestedWorkingDir
            depends_on = @()
            assignment = @{ title = 'Avoid nested worktree path' }
        } | ConvertTo-Json -Depth 8 | Out-File (Join-Path $roomDir 'config.json') -Encoding utf8

        $result = Ensure-RoomWorktree -RoomDir $roomDir -WarRoomsDir $warRoomsDir
        $config = Get-Content (Join-Path $roomDir 'config.json') -Raw | ConvertFrom-Json
        $record = Get-RoomWorkspaceRecord -WarRoomsDir $warRoomsDir -RoomId 'room-001'

        $result.WorkingDir | Should -Be $roomWorktree
        $config.working_dir | Should -Be $roomWorktree
        $record.working_dir | Should -Be $roomWorktree
        Test-Path (Join-Path $roomWorktree '.git') | Should -BeTrue
    }

    It 'does not unblock dependencies that are done but not merged' {
        $repo = New-TestRepo -Name 'dep-state'
        $warRoomsDir = Join-Path $TestDrive 'war-rooms-deps'
        Initialize-PlanIntegrationWorkspace -WarRoomsDir $warRoomsDir -PlanId 'plan-test' -RunId 'run-test' -SourceWorkingDir $repo -WorkspaceIsolation room-worktree | Out-Null

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
        Initialize-PlanIntegrationWorkspace -WarRoomsDir $warRoomsDir -PlanId 'plan-test' -RunId 'run-test' -SourceWorkingDir $repo -WorkspaceIsolation room-worktree | Out-Null

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

    It 'merges two epic room worktrees back while preserving .war-rooms artifacts' {
        $repo = New-TestRepo -Name 'two-epics'
        $warRoomsDir = Join-Path $repo '.war-rooms'
        Initialize-PlanIntegrationWorkspace -WarRoomsDir $warRoomsDir -PlanId 'plan-test' -RunId 'run-test' -SourceWorkingDir $repo -WorkspaceIsolation room-worktree | Out-Null

        foreach ($roomSpec in @(
            @{ RoomId = 'room-001'; TaskRef = 'EPIC-001'; Title = 'Create Alpha Feature'; File = 'alpha.txt'; Content = 'alpha' },
            @{ RoomId = 'room-002'; TaskRef = 'EPIC-002'; Title = 'Create Beta Feature'; File = 'beta.txt'; Content = 'beta' }
        )) {
            $roomDir = Join-Path $warRoomsDir $roomSpec.RoomId
            New-Item -ItemType Directory -Path (Join-Path $roomDir 'artifacts') -Force | Out-Null
            New-Item -ItemType Directory -Path (Join-Path $roomDir 'contexts') -Force | Out-Null
            @{ room_id = $roomSpec.RoomId; task_ref = $roomSpec.TaskRef; plan_id = 'plan-test'; run_id = 'run-test'; working_dir = $repo; depends_on = @(); assignment = @{ title = $roomSpec.Title } } |
                ConvertTo-Json -Depth 8 | Out-File (Join-Path $roomDir 'config.json') -Encoding utf8
            '{}' | Out-File (Join-Path $roomDir 'lifecycle.json') -Encoding utf8
            'pending' | Out-File (Join-Path $roomDir 'status') -Encoding utf8 -NoNewline

            $ready = Ensure-RoomWorktree -RoomDir $roomDir -WarRoomsDir $warRoomsDir
            $ready.WorkingDir | Should -Be (Join-Path (Join-Path $repo '.worktree') $roomSpec.RoomId)
            $roomSpec.Content | Out-File -FilePath (Join-Path $ready.WorkingDir $roomSpec.File) -Encoding utf8
            "agent wrapper" | Out-File -FilePath (Join-Path $roomDir 'artifacts/run-agent.sh') -Encoding utf8

            $merge = Complete-RoomWorkspaceMerge -RoomDir $roomDir -WarRoomsDir $warRoomsDir
            $merge.Integrated | Should -BeTrue
            Test-Path (Join-Path $repo $roomSpec.File) | Should -BeTrue
            Test-Path (Join-Path $roomDir 'lifecycle.json') | Should -BeTrue
            Test-Path (Join-Path $roomDir 'artifacts/run-agent.sh') | Should -BeTrue
        }

        Test-Path (Join-Path $repo '.worktree/room-001/.git') | Should -BeTrue
        Test-Path (Join-Path $repo '.worktree/room-002/.git') | Should -BeTrue
        $record1 = Get-RoomWorkspaceRecord -WarRoomsDir $warRoomsDir -RoomId 'room-001'
        $record2 = Get-RoomWorkspaceRecord -WarRoomsDir $warRoomsDir -RoomId 'room-002'
        $record1.status | Should -Be 'merged'
        $record2.status | Should -Be 'merged'
    }

    It 'records merge conflicts in the manifest and room artifact' {
        $repo = New-TestRepo -Name 'merge-conflict'
        $warRoomsDir = Join-Path $TestDrive 'war-rooms-conflict'
        Initialize-PlanIntegrationWorkspace -WarRoomsDir $warRoomsDir -PlanId 'plan-test' -RunId 'run-test' -SourceWorkingDir $repo -WorkspaceIsolation room-worktree | Out-Null

        $roomDir = Join-Path $warRoomsDir 'room-001'
        New-Item -ItemType Directory -Path $roomDir -Force | Out-Null
        @{
            room_id = 'room-001'
            task_ref = 'EPIC-001'
            plan_id = 'plan-test'
            run_id = 'run-test'
            working_dir = $repo
            depends_on = @()
            assignment = @{ title = 'Conflicting README update' }
        } | ConvertTo-Json -Depth 8 | Out-File (Join-Path $roomDir 'config.json') -Encoding utf8

        $ready = Ensure-RoomWorktree -RoomDir $roomDir -WarRoomsDir $warRoomsDir
        'room change' | Out-File -FilePath (Join-Path $ready.WorkingDir 'README.md') -Encoding utf8

        'source change' | Out-File -FilePath (Join-Path $repo 'README.md') -Encoding utf8
        Invoke-TestGit -Cwd $repo -Args @('add', 'README.md') | Out-Null
        Invoke-TestGit -Cwd $repo -Args @('commit', '-m', 'source diverged') | Out-Null

        $merge = Complete-RoomWorkspaceMerge -RoomDir $roomDir -WarRoomsDir $warRoomsDir
        $record = Get-RoomWorkspaceRecord -WarRoomsDir $warRoomsDir -RoomId 'room-001'

        $merge.Integrated | Should -BeFalse
        $merge.Status | Should -Be 'conflicted'
        $record.status | Should -Be 'conflicted'
        $record.conflict_files | Should -Contain 'README.md'
        Test-Path (Join-Path $roomDir 'artifacts/workspace-merge-conflict.json') | Should -BeTrue
    }
}
