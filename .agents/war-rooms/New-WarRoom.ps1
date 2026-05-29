<#
.SYNOPSIS
    Creates a new war-room with config.json goal contract.

.DESCRIPTION
    Sets up a war-room directory structure with channel, status tracking, PID management,
    and a config.json containing assignment details and goal definitions.

    Replaces: war-rooms/create.sh
    Enhanced: adds config.json with goals (definition_of_done, acceptance_criteria)

.PARAMETER RoomId
    Unique room identifier (e.g. room-001).
.PARAMETER TaskRef
    Task or Epic reference (e.g. TASK-001, EPIC-001).
.PARAMETER TaskDescription
    Full task/epic description.
.PARAMETER WorkingDir
    Scoped working directory for this room's agents (absolute path).
.PARAMETER DefinitionOfDone
    Array of goal strings for the definition of done.
.PARAMETER AcceptanceCriteria
    Array of acceptance criteria strings.
.PARAMETER PlanId
    Optional plan identifier this room belongs to.
.PARAMETER WarRoomsDir
    Base directory for war-rooms. Default: WARROOMS_DIR env var or script directory.
.PARAMETER MaxRetries
    Maximum retries for this room. Default: 3.
.PARAMETER TimeoutSeconds
    Timeout per state in seconds. Default: 900.

.EXAMPLE
    ./New-WarRoom.ps1 -RoomId "room-001" -TaskRef "EPIC-001" `
                      -TaskDescription "Implement user auth" -WorkingDir "/project/src/api" `
                      -DefinitionOfDone @("JWT working", "Tests pass") `
                      -AcceptanceCriteria @("POST /login returns 200")
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$RoomId,

    [Parameter(Mandatory)]
    [string]$TaskRef,

    [Parameter(Mandatory)]
    [string]$TaskDescription,

    [string]$WorkingDir = '.',

    [string[]]$DefinitionOfDone = @(),

    [string[]]$AcceptanceCriteria = @(),

    [string]$PlanId = '',

    [string[]]$DependsOn = @(),

    [string]$WarRoomsDir = '',

    [string]$AssignedRole = 'engineer',

    [string[]]$CandidateRoles = @(),

    [int]$MaxRetries = 3,

    [int]$TimeoutSeconds = 900,
 
    [string]$Pipeline = '',
 
    [string[]]$RequiredCapabilities = @(),

    [string]$Lifecycle = '',

    [PSCustomObject[]]$Assets = @()
)

# --- Resolve war-rooms directory ---
if (-not $WarRoomsDir) {
    $WarRoomsDir = if ($env:WARROOMS_DIR) { $env:WARROOMS_DIR }
                   else { $PSScriptRoot }
}

$roomDir = Join-Path $WarRoomsDir $RoomId

# --- Prevent overwriting existing room ---
if (Test-Path $roomDir) {
    throw "War-room '$RoomId' already exists at $roomDir"
}

# --- Create room directory structure ---
New-Item -ItemType Directory -Path $roomDir -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $roomDir "pids") -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $roomDir "artifacts") -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $roomDir "contexts") -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $roomDir "assets") -Force | Out-Null

# --- Inject Assets ---
$assetManifest = ""
if ($Assets -and $Assets.Count -gt 0) {
    $assetManifest = "## Available Assets`n`n"
    foreach ($asset in $Assets) {
        $sourcePath = $asset.Path
        $targetFilename = $asset.Filename
        $targetPath = Join-Path $roomDir "assets" $targetFilename
        
        if (Test-Path $sourcePath) {
            # Copy asset (read-only in the room)
            Copy-Item -Path $sourcePath -Destination $targetPath -Force
            $assetManifest += "- ``assets/$targetFilename`` — $($asset.Description) (Type: $($asset.AssetType))`n"
        } else {
            Write-Warning "Asset file not found: $sourcePath"
            $assetManifest += "- [WARNING: MISSING ON DISK] ``assets/$targetFilename`` — $($asset.Description)`n"
        }
    }
    $assetManifest += "`n"
}

# --- Initialize channel ---
# NOTE: All subsequent writes to channel.jsonl MUST go through Write-ChannelLine
# (from Utils.psm1) which uses Invoke-WithFileLock to prevent concurrent-append corruption.
New-Item -ItemType File -Path (Join-Path $roomDir "channel.jsonl") -Force | Out-Null

# --- Detect Epic vs Task ---
$assignmentType = if ($TaskRef -match '^EPIC-') { 'epic' } else { 'task' }

# --- Write config.json (Goal Contract) ---
$ts = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')

$config = [ordered]@{
    room_id    = $RoomId
    task_ref   = $TaskRef
    plan_id    = $PlanId
    depends_on = @($DependsOn)
    created_at = $ts
    working_dir = if ([System.IO.Path]::IsPathRooted($WorkingDir)) { $WorkingDir }
                  else { (Resolve-Path $WorkingDir -ErrorAction SilentlyContinue).Path }

    assignment = [ordered]@{
        title           = ($TaskDescription -split "`n")[0].Trim()
        description     = $TaskDescription
        assigned_role   = $AssignedRole
        candidate_roles = if ($CandidateRoles.Count -gt 0) { $CandidateRoles } else { @($AssignedRole) }
        type            = $assignmentType
    }

    goals = [ordered]@{
        definition_of_done  = $DefinitionOfDone
        acceptance_criteria = $AcceptanceCriteria
        quality_requirements = [ordered]@{
            test_coverage_min = 80
            lint_clean        = $true
            security_scan_pass = $true
        }
    }

    constraints = [ordered]@{
        max_retries       = $MaxRetries
        timeout_seconds   = $TimeoutSeconds
        budget_tokens_max = 500000
    }

    status = [ordered]@{
        current           = "pending"
        retries           = 0
        started_at        = $null
        last_state_change = $ts
    }
}

$config | ConvertTo-Json -Depth 10 | Out-File -FilePath (Join-Path $roomDir "config.json") -Encoding utf8

# --- Write per-role config file ({role}_{id}.json) ---
$agentsDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$configPath = Join-Path $agentsDir "config.json"
$globalConfig = $null
if (Test-Path $configPath) {
    $globalConfig = Get-Content $configPath -Raw | ConvertFrom-Json
}

# --- Load plan-specific roles config (~/.ostwin/.agents/plans/{plan_id}.roles.json) ---
$planRolesConfig = $null
if ($PlanId) {
    $_home = if ($env:HOME) { $env:HOME } else { $env:USERPROFILE }
    $planRolesFile = Join-Path $_home ".ostwin" ".agents" "plans" "$PlanId.roles.json"
    if (Test-Path $planRolesFile) {
        $planRolesConfig = Get-Content $planRolesFile -Raw | ConvertFrom-Json
    }
}

# Parse base role name (strip instance suffix like "engineer:fe" → "engineer")
$baseRole = $AssignedRole -replace ':.*$', ''
$instanceSuffix = if ($AssignedRole -match ':(.+)$') { $Matches[1] } else { '' }

# Resolve model for this role: plan roles.json → instance → global config → role.json → default
$roleModel = "google-vertex/gemini-3-flash-preview"
$roleTimeout = $TimeoutSeconds
$roleSkillRefs = @()

# Priority 1: plan-specific roles.json
if ($planRolesConfig -and $planRolesConfig.$baseRole) {
    $planRoleConfig = $planRolesConfig.$baseRole
    if ($planRoleConfig.default_model) {
        $roleModel = $planRoleConfig.default_model
    }
    if ($planRoleConfig.timeout_seconds) {
        $roleTimeout = $planRoleConfig.timeout_seconds
    }
    if ($planRoleConfig.skill_refs) {
        $roleSkillRefs = @($planRoleConfig.skill_refs)
    }
}
# Priority 1b: fallback to role.json skill_refs when plan roles.json is missing/empty
# Search order favors repo core roles over installed/home copies.
if ($roleSkillRefs.Count -eq 0) {
    $homeDir = if ($env:HOME) { $env:HOME } else { $env:USERPROFILE }
    $firstWorkingDir = if ($WorkingDir -and $WorkingDir -ne '.') { $WorkingDir } else { $null }
    $roleJsonCandidates = @(
        (Join-Path $agentsDir "roles" $baseRole "role.json"),
        (Join-Path $homeDir ".ostwin" ".agents" "roles" $baseRole "role.json"),
        (Join-Path $homeDir ".ostwin" "roles" $baseRole "role.json")
    )
    if ($firstWorkingDir) {
        $roleJsonCandidates += (Join-Path $firstWorkingDir "contributes" "roles" $baseRole "role.json")
    }
    foreach ($roleJsonPath in ($roleJsonCandidates | Select-Object -Unique)) {
        if (Test-Path $roleJsonPath) {
            try {
                $roleData = Get-Content $roleJsonPath -Raw | ConvertFrom-Json
                if ($roleData.skill_refs) {
                    $roleSkillRefs = @($roleData.skill_refs)
                    break
                }
            }
            catch {
                Write-Verbose "Failed to read skill_refs from role.json for '$baseRole': $_"
            }
        }
    }
}

# Priority 2: global config.json (only fill in what plan config didn't set)
if ($roleModel -eq "google-vertex/gemini-3-flash-preview" -and $globalConfig) {
    if ($instanceSuffix -and $globalConfig.$baseRole.instances.$instanceSuffix.default_model) {
        $roleModel = $globalConfig.$baseRole.instances.$instanceSuffix.default_model
    }
    elseif ($globalConfig.$baseRole.default_model) {
        $roleModel = $globalConfig.$baseRole.default_model
    }
}

# Priority 3: role.json fallback
if ($roleModel -eq "google-vertex/gemini-3-flash-preview") {
    $roleJsonPath = Join-Path $agentsDir "roles" $baseRole "role.json"
    if (Test-Path $roleJsonPath) {
        $roleJson = Get-Content $roleJsonPath -Raw | ConvertFrom-Json
        if ($roleJson.model) { $roleModel = $roleJson.model }
    }
}

# Determine instance ID (sequential counter for this role in this room)
$existingRoleConfigs = Get-ChildItem -Path $roomDir -Filter "${baseRole}_*.json" -ErrorAction SilentlyContinue
$instanceNum = ($existingRoleConfigs | Measure-Object).Count + 1
$instanceId = $instanceNum.ToString("000")

$roleConfig = [ordered]@{
    role          = $baseRole
    instance_id   = $instanceId
    instance_type = $instanceSuffix
    display_name  = if ($instanceSuffix) { "$baseRole`:$instanceSuffix #$instanceId" } else { "$baseRole #$instanceId" }
    model         = $roleModel
    timeout_seconds = $roleTimeout
    assigned_at   = $ts
    status        = "pending"
    config_override = [ordered]@{}
}
if ($roleSkillRefs.Count -gt 0) {
    $roleConfig['skill_refs'] = $roleSkillRefs
}

$roleConfigFile = Join-Path $roomDir "${baseRole}_${instanceId}.json"
$roleConfig | ConvertTo-Json -Depth 5 | Out-File -FilePath $roleConfigFile -Encoding utf8

# --- Extract Tasks block from TaskDescription (handles ##/###/#### Tasks headings) ---
$briefDescription = $TaskDescription
$extractedTasksBlock = ""
$taskLineCount = 0
$descCharsBefore = $TaskDescription.Length

Write-Verbose "[$RoomId / $TaskRef] Scanning TaskDescription ($descCharsBefore chars) for Tasks block..."

if ($TaskDescription -match '(?sm)(^#{2,4} Tasks\s*\n.*?)(?=^#{2,4} |\z)') {
    $extractedTasksBlock = $Matches[1].Trim()
    $taskLineCount = ($extractedTasksBlock -split '\n' | Where-Object { $_ -match '^\s*-\s+\[' }).Count
    # Remove the Tasks block from the description used in brief.md
    $briefDescription = ($TaskDescription -replace '(?sm)(^#{2,4} Tasks\s*\n.*?)(?=^#{2,4} |\z)', '').Trim()
    $descCharsAfter = $briefDescription.Length
    Write-Host "  [EXTRACT] $TaskRef → Tasks block found: $taskLineCount checklist item(s), $($descCharsBefore - $descCharsAfter) chars removed from brief" -ForegroundColor Cyan
    Write-Verbose "[$RoomId / $TaskRef] brief.md body: $descCharsAfter chars | TASKS.md block: $($extractedTasksBlock.Length) chars"
} else {
    Write-Host "  [EXTRACT] $TaskRef → No Tasks block found (##/###/####) — brief.md will contain full description" -ForegroundColor DarkYellow
    Write-Verbose "[$RoomId / $TaskRef] brief.md body: $descCharsBefore chars (unchanged)"
}

# --- Write assignment brief (includes DoD + AC, EXCLUDES Tasks block) ---
$dodSection = ""
if ($DefinitionOfDone -and $DefinitionOfDone.Count -gt 0) {
    $dodLines = ($DefinitionOfDone | ForEach-Object { "- [ ] $_" }) -join "`n"
    $dodSection = @"

## Definition of Done

$dodLines
"@
}

$acSection = ""
if ($AcceptanceCriteria -and $AcceptanceCriteria.Count -gt 0) {
    $acLines = ($AcceptanceCriteria | ForEach-Object { "- [ ] $_" }) -join "`n"
    $acSection = @"

## Acceptance Criteria

$acLines
"@
}

$briefContent = @"
# $TaskRef

$briefDescription
$dodSection
$acSection

$assetManifest
## Working Directory
$($config.working_dir)

## Created
$ts
"@
$briefPath = Join-Path $roomDir "brief.md"
$briefContent | Out-File -FilePath $briefPath -Encoding utf8
$briefBytes = (Get-Item $briefPath).Length
Write-Verbose "[$RoomId / $TaskRef] brief.md written: $briefBytes bytes | DoD: $($DefinitionOfDone.Count) item(s) | AC: $($AcceptanceCriteria.Count) item(s)"

# --- Create TASKS.md for Epics (from extracted block or fallback skeleton) ---
$tasksMode = 'none'
if ($assignmentType -eq 'epic') {
    if ($extractedTasksBlock) {
        # Use the actual ### Tasks block from the plan
        $tasksMode = 'extracted'
        $tasksContent = @"
# Tasks for $TaskRef

$assetManifest
$extractedTasksBlock
"@
    } else {
        # Fallback: no ### Tasks block found — create a minimal skeleton
        $tasksMode = 'skeleton'
        $tasksContent = @"
# Tasks for $TaskRef

$assetManifest
- [ ] TASK-001 — Planning and context gathering
- [ ] TASK-002 — Core implementation
"@
    }
    $tasksPath = Join-Path $roomDir "TASKS.md"
    $tasksContent | Out-File -FilePath $tasksPath -Encoding utf8
    $tasksBytes = (Get-Item $tasksPath).Length
    Write-Verbose "[$RoomId / $TaskRef] TASKS.md written ($tasksMode): $tasksBytes bytes"
}

# --- Generate per-room lifecycle (if Pipeline or Capabilities provided) ---
if ($Pipeline -or ($RequiredCapabilities -and $RequiredCapabilities.Count -gt 0)) {
    $resolvePipeline = Join-Path (Resolve-Path (Join-Path $PSScriptRoot "..")).Path "lifecycle" "Resolve-Pipeline.ps1"
    if (Test-Path $resolvePipeline) {
        $pipelineArgs = @{
            AssignedRole = $AssignedRole
            AgentsDir    = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
        }
        if ($Pipeline) { $pipelineArgs['PipelineString'] = $Pipeline }
        if ($RequiredCapabilities -and $RequiredCapabilities.Count -gt 0) {
            $pipelineArgs['RequiredCapabilities'] = $RequiredCapabilities
        }
        $pipelineArgs['OutputPath'] = Join-Path $roomDir "lifecycle.json"
        & $resolvePipeline @pipelineArgs
    }
}

# --- FALLBACK: Generate default lifecycle from CandidateRoles ---
# AssignedRole is the authoritative primary worker for the developing stage.
# Review stages are derived from CandidateRoles minus the AssignedRole.
# Only roles present in candidate_roles appear in the lifecycle.
$lifecyclePath = Join-Path $roomDir "lifecycle.json"
if (-not (Test-Path $lifecyclePath)) {
    $effectiveCandidates = @(if ($CandidateRoles.Count -gt 0) { $CandidateRoles } else { @($AssignedRole) })
    $resolvePipeline = Join-Path (Resolve-Path (Join-Path $PSScriptRoot "..")).Path "lifecycle" "Resolve-Pipeline.ps1"
    if (Test-Path $resolvePipeline) {
        # Use Resolve-Pipeline to generate v2 lifecycle from candidate roles
        & $resolvePipeline `
            -CandidateRoles $effectiveCandidates `
            -AssignedRole $AssignedRole `
            -MaxRetries $MaxRetries `
            -OutputPath $lifecyclePath
    } else {
        # Inline v2 fallback — minimal developing → review → passed
        $primaryRole = $AssignedRole
        $v2Lifecycle = [ordered]@{
            version       = 2
            initial_state = 'developing'
            max_retries   = $MaxRetries
            states        = [ordered]@{
                developing = [ordered]@{
                    role    = $primaryRole
                    type    = 'work'
                    signals = [ordered]@{
                        done  = [ordered]@{ target = 'review' }
                        error = [ordered]@{ target = 'failed'; actions = @('increment_retries') }
                    }
                }
                optimize = [ordered]@{
                    role    = $primaryRole
                    type    = 'work'
                    signals = [ordered]@{
                        done  = [ordered]@{ target = 'review' }
                        error = [ordered]@{ target = 'failed'; actions = @('increment_retries') }
                    }
                }
                review = [ordered]@{
                    role    = 'qa'
                    type    = 'review'
                    signals = [ordered]@{
                        pass     = [ordered]@{ target = 'passed' }
                        fail     = [ordered]@{ target = 'developing'; actions = @('increment_retries', 'post_fix') }
                        escalate = [ordered]@{ target = 'triage' }
                    }
                }
                triage = [ordered]@{
                    role    = 'manager'
                    type    = 'triage'
                    signals = [ordered]@{
                        fix      = [ordered]@{ target = 'developing'; actions = @('increment_retries') }
                        redesign = [ordered]@{ target = 'developing'; actions = @('increment_retries', 'revise_brief') }
                        reject   = [ordered]@{ target = 'failed-final' }
                    }
                }
                failed = [ordered]@{
                    role            = 'manager'
                    type            = 'decision'
                    auto_transition = $true
                    signals         = [ordered]@{
                        retry   = [ordered]@{ target = 'developing'; guard = 'retries < max_retries' }
                        exhaust = [ordered]@{ target = 'failed-final'; guard = 'retries >= max_retries' }
                    }
                }
                passed        = [ordered]@{ type = 'terminal' }
                'failed-final' = [ordered]@{ type = 'terminal' }
            }
        }
        $v2Lifecycle | ConvertTo-Json -Depth 10 | Out-File -FilePath $lifecyclePath -Encoding utf8 -Force
    }
}

# --- Store lifecycle notation (documentation only, not consumed at runtime) ---
if ($Lifecycle) {
    $Lifecycle | Out-File -FilePath (Join-Path $roomDir "lifecycle.md") -Encoding utf8
}

# --- Initialize status ---
"pending" | Out-File -FilePath (Join-Path $roomDir "status") -Encoding utf8 -NoNewline

# --- Initialize retry counter and done epoch ---
"0" | Out-File -FilePath (Join-Path $roomDir "retries") -Encoding utf8 -NoNewline
"0" | Out-File -FilePath (Join-Path $roomDir "done_epoch") -Encoding utf8 -NoNewline

# --- Store task ref for quick lookup ---
$TaskRef | Out-File -FilePath (Join-Path $roomDir "task-ref") -Encoding utf8 -NoNewline

# --- Post initial task message to channel ---
$PostMessage = Join-Path $PSScriptRoot ".." "channel" "Post-Message.ps1"
if (Test-Path $PostMessage) {
    & $PostMessage -RoomDir $roomDir -From "manager" -To $baseRole `
                   -Type "task" -Ref $TaskRef -Body $TaskDescription
}

# --- Output ---
Write-Output ""
Write-Output "[CREATED] War-room '$RoomId' for $TaskRef"
Write-Output "  Path:      $roomDir"
Write-Output "  Status:    pending"
Write-Output "  Role:      $AssignedRole → ${baseRole}_${instanceId}.json (model: $roleModel)"
Write-Output "  Goals:     $($DefinitionOfDone.Count) definition(s) of done, $($AcceptanceCriteria.Count) acceptance criteria"
Write-Output ""
Write-Output "  ┌─ File Extraction Log ─────────────────────────────────────────"
Write-Output "  │  brief.md     → $([math]::Round($briefBytes/1KB, 1)) KB  (DoD: $($DefinitionOfDone.Count), AC: $($AcceptanceCriteria.Count), Tasks: excluded)"
if ($assignmentType -eq 'epic') {
    $tasksLabel = if ($tasksMode -eq 'extracted') {
        "$taskLineCount task(s) extracted from plan"
    } else {
        "skeleton fallback (no ### Tasks block in description)"
    }
    Write-Output "  │  TASKS.md    → $([math]::Round($tasksBytes/1KB, 1)) KB  ($tasksLabel)"
} else {
    Write-Output "  │  TASKS.md    → not created (type: $assignmentType)"
}
Write-Output "  └───────────────────────────────────────────────────────────────"

