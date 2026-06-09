Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$root = Resolve-Path (Join-Path $PSScriptRoot '..' '..')
$ostwin = Join-Path $root '.agents/bin/ostwin'
if (-not (Test-Path $ostwin)) { throw "ostwin CLI not found at $ostwin" }

$repo = Join-Path $PWD 'sample-repo'
if (Test-Path $repo) { Remove-Item -Recurse -Force $repo }
New-Item -ItemType Directory -Path $repo -Force | Out-Null

git -C $repo init | Out-Null
git -C $repo config user.name 'Smoke Test' | Out-Null
git -C $repo config user.email 'smoke@example.local' | Out-Null
'base' | Out-File -FilePath (Join-Path $repo 'README.md') -Encoding utf8
git -C $repo add README.md | Out-Null
git -C $repo commit -m base | Out-Null

# `ostwin run` preflights the target project before Start-Plan initializes rooms.
$opencodeDir = Join-Path $repo '.opencode'
New-Item -ItemType Directory -Path $opencodeDir -Force | Out-Null
'{"$schema":"https://opencode.ai/config.json"}' | Out-File -FilePath (Join-Path $opencodeDir 'opencode.json') -Encoding utf8

# Seed a project-local Ostwin runtime so `ostwin run` exercises the modified
# scripts inside the sample repo instead of falling back to a globally installed
# ~/.ostwin copy. Keep the runtime ignored/untracked so init/sync mutations do
# not make the source repository dirty before room worktrees merge.
$projectAgents = Join-Path $repo '.agents'
New-Item -ItemType Directory -Path $projectAgents -Force | Out-Null
foreach ($rel in @('bin', 'channel', 'events', 'lib', 'lifecycle', 'mcp', 'plan', 'release', 'skills', 'war-rooms', 'workspace')) {
    Copy-Item -Path (Join-Path $root ".agents/$rel") -Destination $projectAgents -Recurse -Force
}
foreach ($fileRel in @('init.ps1', 'sync.ps1', 'sync-skills.ps1')) {
    $srcFile = Join-Path $root ".agents/$fileRel"
    if (Test-Path $srcFile) { Copy-Item -Path $srcFile -Destination (Join-Path $projectAgents $fileRel) -Force }
}
foreach ($role in @('_base', 'architect', 'engineer', 'manager', 'qa')) {
    $roleDst = Join-Path $projectAgents "roles/$role"
    New-Item -ItemType Directory -Path (Split-Path $roleDst -Parent) -Force | Out-Null
    Copy-Item -Path (Join-Path $root ".agents/roles/$role") -Destination (Split-Path $roleDst -Parent) -Recurse -Force
}
Copy-Item -Path (Join-Path $root '.agents/config.json') -Destination (Join-Path $projectAgents 'config.json') -Force
".agents/`n.opencode/`n.war-rooms/`n.worktree/`n.memory`n" | Out-File -FilePath (Join-Path $repo '.gitignore') -Encoding utf8
git -C $repo add .gitignore | Out-Null
git -C $repo commit -m 'ignore ostwin runtime' | Out-Null

$planId = 'a11ce001'
$plansDir = Join-Path $projectAgents 'plans'
New-Item -ItemType Directory -Path $plansDir -Force | Out-Null
$planFile = Join-Path $plansDir "$planId.md"
@"
# Plan: Worktree Smoke Test
working_dir: $repo

## EPIC-001 — Write hello page
Roles: engineer, qa
#### Definition of Done
- [ ] First epic writes hello.html

## EPIC-002 — Write world page
Roles: engineer, qa
#### Definition of Done
- [ ] Second epic writes world.html
"@ | Out-File -FilePath $planFile -Encoding utf8
@{ working_dir = $repo; title = 'Worktree Smoke Test' } | ConvertTo-Json -Depth 4 | Out-File -FilePath (Join-Path $plansDir "$planId.meta.json") -Encoding utf8

$mockAgent = Join-Path $PWD 'mock-agent.ps1'
@'
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$role = $env:AGENT_OS_ROLE
$roomDir = $env:AGENT_OS_ROOM_DIR
$roomId = Split-Path $roomDir -Leaf
$cwd = (Get-Location).Path

if ($role -eq 'engineer') {
    if ($roomId -eq 'room-001') {
        '<!doctype html><html><body>Hello</body></html>' | Out-File -FilePath (Join-Path $cwd 'hello.html') -Encoding utf8
    } elseif ($roomId -eq 'room-002') {
        '<!doctype html><html><body>World</body></html>' | Out-File -FilePath (Join-Path $cwd 'world.html') -Encoding utf8
    }
    @"
# Tasks

- [x] TASK-001 — Write sample data from $roomId
"@ | Out-File -FilePath (Join-Path $roomDir 'TASKS.md') -Encoding utf8
    "cwd=$cwd" | Out-File -FilePath (Join-Path $roomDir 'artifacts/engineer-cwd.txt') -Encoding utf8
    Write-Output 'VERDICT: DONE'
    exit 0
}

if ($role -eq 'qa') {
    "cwd=$cwd" | Out-File -FilePath (Join-Path $roomDir 'artifacts/qa-cwd.txt') -Encoding utf8
    Write-Output 'VERDICT: PASS'
    exit 0
}

Write-Output 'VERDICT: DONE'
exit 0
'@ | Out-File -FilePath $mockAgent -Encoding utf8

$env:OSTWIN_AGENT_CMD = "pwsh -NoProfile -File '$mockAgent'"
$env:ENGINEER_CMD = $env:OSTWIN_AGENT_CMD
$env:QA_CMD = $env:OSTWIN_AGENT_CMD
$env:ARCHITECT_CMD = $env:OSTWIN_AGENT_CMD
$env:OSTWIN_WORKSPACE_ISOLATION = 'room-worktree'
$env:AGENT_OS_LOG_LEVEL = 'ERROR'
try {
    Push-Location $repo
    & pwsh -NoProfile -File $ostwin run $planId --workspace-isolation room-worktree --non-interactive
    if ($LASTEXITCODE -ne 0) { throw "ostwin run exited with $LASTEXITCODE" }
} finally {
    Pop-Location -ErrorAction SilentlyContinue
    Remove-Item Env:OSTWIN_AGENT_CMD -ErrorAction SilentlyContinue
    Remove-Item Env:ENGINEER_CMD -ErrorAction SilentlyContinue
    Remove-Item Env:QA_CMD -ErrorAction SilentlyContinue
    Remove-Item Env:ARCHITECT_CMD -ErrorAction SilentlyContinue
    Remove-Item Env:OSTWIN_WORKSPACE_ISOLATION -ErrorAction SilentlyContinue
}

$warRoomsDir = Join-Path $repo '.war-rooms'
foreach ($expected in @(
    (Join-Path $repo 'hello.html'),
    (Join-Path $repo 'world.html'),
    (Join-Path $repo '.worktree/room-001/.git'),
    (Join-Path $repo '.worktree/room-002/.git'),
    (Join-Path $warRoomsDir 'DAG.json'),
    (Join-Path $warRoomsDir 'PROGRESS.md'),
    (Join-Path $warRoomsDir 'progress.json'),
    (Join-Path $warRoomsDir 'room-000/architect_001.json'),
    (Join-Path $warRoomsDir 'room-000/artifacts'),
    (Join-Path $warRoomsDir 'room-000/assets'),
    (Join-Path $warRoomsDir 'room-000/audit.log'),
    (Join-Path $warRoomsDir 'room-000/brief.md'),
    (Join-Path $warRoomsDir 'room-000/channel.jsonl'),
    (Join-Path $warRoomsDir 'room-000/config.json'),
    (Join-Path $warRoomsDir 'room-000/contexts'),
    (Join-Path $warRoomsDir 'room-000/lifecycle.json'),
    (Join-Path $warRoomsDir 'room-000/pids'),
    (Join-Path $warRoomsDir 'room-000/retries'),
    (Join-Path $warRoomsDir 'room-000/state_changed_at'),
    (Join-Path $warRoomsDir 'room-000/status'),
    (Join-Path $warRoomsDir 'room-000/task-ref'),
    (Join-Path $warRoomsDir 'room-001/lifecycle.json'),
    (Join-Path $warRoomsDir 'room-001/TASKS.md'),
    (Join-Path $warRoomsDir 'room-001/artifacts/run-agent.sh'),
    (Join-Path $warRoomsDir 'room-001/artifacts/engineer-cwd.txt'),
    (Join-Path $warRoomsDir 'room-002/lifecycle.json'),
    (Join-Path $warRoomsDir 'room-002/TASKS.md'),
    (Join-Path $warRoomsDir 'room-002/artifacts/run-agent.sh'),
    (Join-Path $warRoomsDir 'room-002/artifacts/engineer-cwd.txt')
)) {
    if (-not (Test-Path $expected)) { throw "missing expected path: $expected" }
}

foreach ($roomId in @('room-001', 'room-002')) {
    $cwdText = Get-Content (Join-Path $warRoomsDir "$roomId/artifacts/engineer-cwd.txt") -Raw
    $expectedCwd = [regex]::Escape((Join-Path (Join-Path $repo '.worktree') $roomId))
    if ($cwdText -notmatch $expectedCwd) { throw "engineer for $roomId did not run in .worktree: $cwdText" }
    $status = (Get-Content (Join-Path $warRoomsDir "$roomId/status") -Raw).Trim()
    if ($status -ne 'done') { throw "expected $roomId status done, got $status" }
}

foreach ($roomId in @('room-001', 'room-002')) {
    foreach ($required in @(
        'artifacts', 'assets', 'audit.log', 'brief.md', 'channel.jsonl', 'config.json',
        'contexts/engineer.md', 'contexts/qa.md', 'done_epoch', 'engineer_001.json',
        'lifecycle.json', 'pids', 'qa_001.json', 'retries', 'state_changed_at', 'status', 'task-ref', 'TASKS.md'
    )) {
        $path = Join-Path (Join-Path $warRoomsDir $roomId) $required
        if (-not (Test-Path $path)) { throw "missing $roomId structure path: $required" }
    }
}

$treeFile = Join-Path $PWD 'war-room-tree.txt'
Get-ChildItem -Path $warRoomsDir -Recurse -Force |
    Sort-Object FullName |
    ForEach-Object { $_.FullName.Substring($warRoomsDir.Length + 1) } |
    Out-File -FilePath $treeFile -Encoding utf8
Write-Host "War-room tree written to $treeFile"

Write-Host 'ostwin-run worktree-two-epics hello-world smoke ok'
