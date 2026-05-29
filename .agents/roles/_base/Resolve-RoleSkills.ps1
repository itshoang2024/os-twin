<#
.SYNOPSIS
    Resolves a set of skills for a specific role via plan-roles config + task-aware discovery.

.DESCRIPTION
    Phase 1 — CONFIG-DRIVEN skill_refs (what the role always needs):
      1. Plan-roles config:  ~/.ostwin/.agents/plans/{plan_id}.roles.json → $role.skill_refs
      2. Repo/local role.json: explicit RolePath → .agents/roles/{RoleName} → contributes/roles/{RoleName}
      3. Installed role.json: ~/.ostwin/.agents/roles/{RoleName} → ~/.ostwin/roles/{RoleName}
      First non-empty wins (no merging across sources).

    Phase 2a — LOCAL TASK-AWARE DISCOVERY (find skills by matching TASKS.md content):
      Reads brief.md + TASKS.md from RoomDir, extracts keywords from task text,
      then scans ALL local SKILL.md frontmatter (name, description, tags) for matches.
      Merges up to 5 additional skill refs not already in Phase 1.
      Runs whenever RoomDir exists and task content is meaningful — no API needed.

    Phase 2b — REMOTE TASK-AWARE API SEARCH (discover extra skills via dashboard):
      Reads brief.md + TASKS.md from RoomDir, searches the Dashboard API,
      and merges up to 5 additional skill refs not already in Phase 1 + 2a.
      Runs only when ApiKey is available and task content is meaningful.

    Phase 3 — LOCAL RESOLUTION (stage each ref to disk):
      1. Registry lookup: from ~/.ostwin/roles/registry.json
      2. Local skills: hierarchical search in skills/ tree
      3. Backend fetch: downloaded from dashboard API when not found locally

    Unresolvable refs are skipped gracefully (best-effort).
    Deduplication is performed based on skill directory name (identifier).

.PARAMETER RoleName
    Name of the role (e.g., engineer, architect). Supports instance suffix (engineer:fe).
.PARAMETER RolePath
    Path to the role directory (unused — kept for backward compat).
.PARAMETER RoomDir
    Optional. War-room directory path — used to read plan_id from config.json,
    and brief.md + TASKS.md for task-aware API search.
.PARAMETER PlanId
    Optional. Explicit plan ID override. When omitted, read from room config.json.
.PARAMETER SkillsBaseDir
    Optional. Override for the base skills directory (defaults to ../../skills).
.PARAMETER DashboardUrl
    Optional. Dashboard API base URL (default: http://localhost:3366).
.PARAMETER ApiKey
    Optional. API key for dashboard authentication (default: $env:OSTWIN_API_KEY).

.OUTPUTS
    [PSCustomObject[]] Collection of objects with Name, Path (to SKILL.md), and Tier.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$RoleName,

    [Parameter(Mandatory = $true)]
    [string]$RolePath,

    [string]$RoomDir = '',

    [string]$PlanId = '',

    [string]$SkillsBaseDir = '',

    [string]$DashboardUrl = '',

    [string]$ApiKey = ''
)

# --- Initialize base paths ---
if (-not $SkillsBaseDir) {
    # Default to .agents/skills relative to this script's location
    $SkillsBaseDir = Resolve-Path (Join-Path $PSScriptRoot ".." ".." "skills")
}

if (-not (Test-Path $SkillsBaseDir)) {
    Write-Warning "Skills base directory not found: $SkillsBaseDir"
    return @()
}

# --- Initialize dashboard settings ---
if (-not $DashboardUrl) {
    $DashboardUrl = if ($env:DASHBOARD_URL) { $env:DASHBOARD_URL } else { "http://localhost:3366" }
}
if (-not $ApiKey) {
    $ApiKey = $env:OSTWIN_API_KEY
}

$resolvedSkills = @{} # Using hashtable for deduplication by Name

# Platform gate: returns $true if the skill's SKILL.md declares a platform list that
# includes the current OS, or if no platform field is present (cross-platform).
function Test-SkillPlatform {
    param([string]$SkillMdPath)
    if (-not (Test-Path $SkillMdPath)) { return $true }
    $content = Get-Content $SkillMdPath -Raw -ErrorAction SilentlyContinue
    if (-not $content) { return $true }
    if ($content -match '(?m)^platform:\s*\[([^\]]+)\]') {
        $platforms = $Matches[1] -split ',' | ForEach-Object { $_.Trim().Trim('"').Trim("'") }
        $currentOS = if ($IsWindows) { 'windows' } elseif ($IsMacOS) { 'macos' } else { 'linux' }
        return ($platforms -contains $currentOS)
    }
    return $true   # No platform field = cross-platform
}

# Enabled gate: returns $false if the skill's SKILL.md explicitly declares enabled: false
function Test-SkillEnabled {
    param([string]$SkillMdPath)
    if (-not (Test-Path $SkillMdPath)) { return $true }
    $content = Get-Content $SkillMdPath -Raw -ErrorAction SilentlyContinue
    if (-not $content) { return $true }
    # Match enabled: false or enabled: 0 (case-insensitive)
    if ($content -match '(?m)^enabled:\s*(false|0)') {
        return $false
    }
    return $true
}

# --- Resolve OSTWIN_HOME ---
$_homeDir = if ($env:HOME) { $env:HOME } else { $env:USERPROFILE }
$ostwinHome = if ($env:OSTWIN_HOME) { $env:OSTWIN_HOME } else { Join-Path $_homeDir ".ostwin" }

# --- Strip instance suffix (engineer:fe → engineer) ---
$baseRole = $RoleName -replace ':.*$', ''

# =======================================================================
# PHASE 1: CONFIG-DRIVEN SKILL REFS
# =======================================================================
$allRefs = @()

# Source 1: Plan-roles config (~/.ostwin/.agents/plans/{plan_id}.roles.json → $role.skill_refs)
if ($allRefs.Count -eq 0) {
    # Resolve plan_id: explicit parameter > room config.json
    $effectivePlanId = $PlanId
    if (-not $effectivePlanId -and $RoomDir -and (Test-Path $RoomDir)) {
        $roomConfigFile = Join-Path $RoomDir "config.json"
        if (Test-Path $roomConfigFile) {
            try {
                $roomCfg = Get-Content $roomConfigFile -Raw | ConvertFrom-Json -ErrorAction SilentlyContinue
                if ($roomCfg.plan_id) {
                    $effectivePlanId = $roomCfg.plan_id
                }
            } catch { }
        }
    }

    if ($effectivePlanId) {
        $planRolesFile = Join-Path $ostwinHome ".agents" "plans" "$effectivePlanId.roles.json"
        if (Test-Path $planRolesFile) {
            try {
                $planRolesData = Get-Content $planRolesFile -Raw | ConvertFrom-Json
                if ($planRolesData.$baseRole -and $planRolesData.$baseRole.skill_refs -and $planRolesData.$baseRole.skill_refs.Count -gt 0) {
                    $allRefs = @($planRolesData.$baseRole.skill_refs)
                    Write-Verbose "Skill refs from plan-roles ($effectivePlanId): $($allRefs -join ', ')"
                }
            } catch { }
        }
    }
}

# Source 2: Repo/local role.json (explicit RolePath → .agents/roles → contributes/roles)
if ($allRefs.Count -eq 0) {
    $localRoleCandidates = @()
    if ($RolePath) {
        $localRoleCandidates += Join-Path $RolePath "role.json"
    }
    $localRoleCandidates += Join-Path $PSScriptRoot ".." $baseRole "role.json"

    if ($RoomDir -and (Test-Path $RoomDir)) {
        $searchDir = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($RoomDir)
        for ($i = 0; $i -lt 6; $i++) {
            $parentDir = Split-Path $searchDir -Parent
            if (-not $parentDir -or $parentDir -eq $searchDir) { break }
            if ((Split-Path $searchDir -Leaf) -eq ".war-rooms") {
                $projectRoot = $parentDir
                $localRoleCandidates += Join-Path $projectRoot "contributes" "roles" $baseRole "role.json"
                break
            }
            $searchDir = $parentDir
        }
    }

    foreach ($localRoleJson in ($localRoleCandidates | Select-Object -Unique)) {
        if (Test-Path $localRoleJson) {
            try {
                $localRoleData = Get-Content $localRoleJson -Raw | ConvertFrom-Json
                if ($localRoleData.skill_refs -and $localRoleData.skill_refs.Count -gt 0) {
                    $allRefs = @($localRoleData.skill_refs)
                    Write-Verbose "Skill refs from local role.json: $($allRefs -join ', ')"
                    break
                }
            } catch { }
        }
    }
}

# Source 3: Installed role.json (~/.ostwin/.agents/roles/{RoleName} → ~/.ostwin/roles/{RoleName})
if ($allRefs.Count -eq 0) {
    $homeRoleCandidates = @(
        (Join-Path $ostwinHome ".agents" "roles" $baseRole "role.json"),
        (Join-Path $ostwinHome "roles" $baseRole "role.json")
    )
    foreach ($homeRoleJson in $homeRoleCandidates) {
        if (Test-Path $homeRoleJson) {
            try {
                $homeRoleData = Get-Content $homeRoleJson -Raw | ConvertFrom-Json
                if ($homeRoleData.skill_refs -and $homeRoleData.skill_refs.Count -gt 0) {
                    $allRefs = @($homeRoleData.skill_refs)
                    Write-Verbose "Skill refs from installed role.json: $($allRefs -join ', ')"
                    break
                }
            } catch { }
        }
    }
}

# =======================================================================
# PHASE 2a: LOCAL TASK-AWARE DISCOVERY (keyword matching against SKILL.md frontmatter)
# =======================================================================
$taskContext = ""
if ($RoomDir -and (Test-Path $RoomDir)) {
    $briefFile = Join-Path $RoomDir "brief.md"
    $tasksFile = Join-Path $RoomDir "TASKS.md"

    if (Test-Path $briefFile) {
        $taskContext += (Get-Content $briefFile -Raw -ErrorAction SilentlyContinue)
    }
    if (Test-Path $tasksFile) {
        $taskContext += "`n" + (Get-Content $tasksFile -Raw -ErrorAction SilentlyContinue)
    }
}

if ($taskContext.Length -gt 50) {
    $existingNames = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($r in $allRefs) { $existingNames.Add($r) | Out-Null }

    $stopWords = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    @(
        'the','a','an','and','or','but','in','on','at','to','for','of','with','by',
        'from','is','it','that','this','was','are','be','has','had','have','will',
        'would','could','should','may','can','do','does','did','not','no','if',
        'then','than','so','as','up','out','into','over','after','before','between',
        'about','through','during','without','within','along','across','behind',
        'below','above','under','each','every','all','both','few','more','most',
        'other','some','such','only','own','same','also','just','very','even',
        'still','already','yet','ever','never','always','often','here','there',
        'when','where','which','who','whom','how','what','why','while','until',
        'since','because','although','though','unless','whether','however',
        'therefore','thus','hence','moreover','furthermore','nevertheless',
        'need','needs','needed','use','uses','used','using','make','makes',
        'made','making','get','gets','got','getting','set','sets','setting',
        'put','puts','putting','add','adds','added','adding','run','runs',
        'running','create','creates','created','creating','ensure','ensures',
        'ensuring','include','includes','including','provide','provides',
        'provided','providing','implement','implements','implemented',
        'implementing','update','updates','updated','updating','check',
        'checks','checked','checking','write','writes','writing','written',
        'read','reads','reading','written','following','follow','follows',
        'followed','must','shall','etc','via','per','like','new','old','one',
        'two','first','second','next','last','based','work','working','worked',
        'want','wanted','allow','allows','allowed','allowing','require',
        'requires','required','requiring','support','supports','supported',
        'supporting','handle','handles','handled','handling','build','builds',
        'built','building','test','tests','tested','testing','code','file',
        'files','data','value','values','function','functions','method',
        'methods','object','objects','class','classes','type','types','item',
        'items','task','tasks','step','steps','part','parts','section',
        'sections','case','cases','way','ways','thing','things','point',
        'points','end','ends','system','systems','process','processes',
        'feature','features','component','components','element','elements',
        'page','pages','screen','screens','app','application','applications',
        'project','projects','product','products','service','services',
        'user','users','name','names','list','lists','field','fields',
        'config','configuration','error','errors','result','results',
        'output','outputs','input','inputs','content','contents'
    ) | ForEach-Object { $stopWords.Add($_) | Out-Null }

    $taskLower = $taskContext.ToLowerInvariant()
    $taskWords = @($taskLower -split '[^a-z0-9\-]+' | Where-Object {
        $_.Length -gt 2 -and -not $stopWords.Contains($_)
    } | Select-Object -Unique)

    $taskWordSet = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($w in $taskWords) { $taskWordSet.Add($w) | Out-Null }

    $localSearchPaths = @(
        @{ Base = $SkillsBaseDir; ExcludeDirs = @("global", "roles") }
        @{ Base = (Join-Path $SkillsBaseDir "global"); ExcludeDirs = @() }
    )
    $rolesDir = Join-Path $SkillsBaseDir "roles"
    if (Test-Path $rolesDir) {
        Get-ChildItem -Path $rolesDir -Directory -ErrorAction SilentlyContinue | ForEach-Object {
            $localSearchPaths += @{ Base = $_.FullName; ExcludeDirs = @() }
        }
    }

    $skillScores = @{}

    foreach ($searchDef in $localSearchPaths) {
        if (-not (Test-Path $searchDef.Base)) { continue }
        Get-ChildItem -Path $searchDef.Base -Filter "SKILL.md" -Recurse -Depth 1 -ErrorAction SilentlyContinue | ForEach-Object {
            $skillMd = $_.FullName
            $skillDirName = $_.Directory.Name

            if ($searchDef.ExcludeDirs -contains $skillDirName) { return }

            if ($existingNames.Contains($skillDirName)) { return }
            if ($skillScores.ContainsKey($skillDirName)) { return }

            if (-not (Test-SkillPlatform -SkillMdPath $skillMd)) { return }
            if (-not (Test-SkillEnabled -SkillMdPath $skillMd)) { return }

            $content = Get-Content $skillMd -Raw -ErrorAction SilentlyContinue
            if (-not $content) { return }

            $nameMatch = ""
            $descMatch = ""
            $tagsMatch = ""
            if ($content -match '(?m)^name:\s*(.+)$') { $nameMatch = $Matches[1].Trim().Trim('"').Trim("'") }
            if ($content -match '(?m)^description:\s*(.+)$') { $descMatch = $Matches[1].Trim().Trim('"').Trim("'") }
            if ($content -match '(?m)^tags:\s*\[([^\]]+)\]') { $tagsMatch = $Matches[1] }

            $matchText = @($skillDirName, $nameMatch, $descMatch, $tagsMatch) -join " "
            $matchLower = $matchText.ToLowerInvariant()
            $matchWords = $matchLower -split '[^a-z0-9\-]+' | Where-Object { $_.Length -gt 2 }

            $score = 0
            foreach ($mw in $matchWords) {
                if ($taskWordSet.Contains($mw)) { $score++ }
            }

            if ($skillDirName -match '-' -and $taskLower.Contains($skillDirName)) { $score += 10 }

            $taskNgrams = @()
            for ($i = 0; $i -lt $taskWords.Count - 1; $i++) {
                $taskNgrams += "$($taskWords[$i])-$($taskWords[$i+1])"
            }
            foreach ($ng in $taskNgrams) {
                if ($skillDirName -eq $ng -or $nameMatch -eq $ng) { $score += 10 }
                if ($matchLower.Contains($ng)) { $score += 3 }
            }

            if ($score -gt 0) {
                $skillScores[$skillDirName] = [PSCustomObject]@{
                    Name  = $skillDirName
                    Path  = $skillMd
                    Score = $score
                }
            }
        }
    }

    $ranked = @($skillScores.Values | Sort-Object -Property Score -Descending)
    $phase2aAdded = 0
    foreach ($entry in $ranked) {
        if ($phase2aAdded -ge 5) { break }
        if (-not $existingNames.Contains($entry.Name)) {
            $allRefs += $entry.Name
            $existingNames.Add($entry.Name) | Out-Null
            $phase2aAdded++
            Write-Verbose "Phase 2a local task-discovered skill: $($entry.Name) (score: $($entry.Score))"
        }
    }
}

# =======================================================================
# PHASE 2b: REMOTE TASK-AWARE API SEARCH (additive — supplements Phase 1 + 2a)
# =======================================================================
if ($RoomDir -and (Test-Path $RoomDir) -and $ApiKey -and $taskContext.Length -gt 50) {
    try {
        $query = $taskContext.Substring(0, [Math]::Min($taskContext.Length, 500))
        $headers = @{ "X-API-Key" = $ApiKey }
        $searchUrl = "$DashboardUrl/api/skills/search?q=$([uri]::EscapeDataString($query))&role=$([uri]::EscapeDataString($baseRole))"
        $searchResults = @(Invoke-RestMethod -Uri $searchUrl -Headers $headers -Method Get -TimeoutSec 10 -ErrorAction Stop)

        if ($searchResults.Count -gt 0 -and $null -ne $searchResults[0]) {
            $existingNames = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
            foreach ($r in $allRefs) { $existingNames.Add($r) | Out-Null }

            $addedCount = 0
            foreach ($result in $searchResults) {
                if ($addedCount -ge 5) { break }
                if ($result.name -and -not $existingNames.Contains($result.name)) {
                    $allRefs += $result.name
                    $existingNames.Add($result.name) | Out-Null
                    $addedCount++
                    Write-Verbose "Phase 2b API-discovered skill: $($result.name)"
                }
            }
        }
    }
    catch {
        Write-Verbose "Task-aware API skill search failed (non-fatal): $_"
    }
}

# =======================================================================
# PHASE 2.5: LEGAL GUARDRAIL EXPANSION
# Ensures legal-common is present whenever legal-* skills are resolved,
# and adds source-document-intake when a legal workflow and source-doc
# signals both appear in the task context.
# =======================================================================
$hasLegalSkill = @($allRefs | Where-Object { $_ -match '^legal-' -and $_ -ine 'legal-common' }).Count -gt 0
if ($hasLegalSkill -or ($taskContext -imatch '\blegal\b')) {
    $guardSet = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($r in $allRefs) { $guardSet.Add($r) | Out-Null }

    if ($hasLegalSkill -and -not $guardSet.Contains('legal-common')) {
        $allRefs += 'legal-common'
        $guardSet.Add('legal-common') | Out-Null
        Write-Verbose "Phase 2.5: added legal-common (legal workflow guardrail)"
    }

    $sourceDocPattern = 'pdf|docx|pptx|xlsx|uploaded|attached|contract|exhibit|filing|policy|evidence|clause'
    if (($taskContext -imatch $sourceDocPattern) -and -not $guardSet.Contains('source-document-intake')) {
        $allRefs += 'source-document-intake'
        Write-Verbose "Phase 2.5: added source-document-intake (legal + source-doc signal)"
    }
}

# =======================================================================
# PHASE 3: LOCAL RESOLUTION (stage each ref to disk)
# =======================================================================

# Deduplicate
$allRefs = @($allRefs | Select-Object -Unique)
Write-Verbose "Skill refs to resolve ($($allRefs.Count)): $($allRefs -join ', ')"

if ($allRefs.Count -eq 0) {
    return @()
}

# Registry always from HOME ~/.ostwin/roles/registry.json
$registryFile = Join-Path $ostwinHome "roles" "registry.json"
$registry = if (Test-Path $registryFile) { Get-Content $registryFile -Raw | ConvertFrom-Json } else { $null }

foreach ($ref in $allRefs) {
    # Strategy 1: Registry lookup
    $skillFromRegistry = if ($registry) { $registry.skills.available | Where-Object { $_.name -eq $ref } } else { $null }
    $registryPath = $null

    if ($skillFromRegistry) {
        $registryPath = Join-Path (Split-Path $registryFile -Parent) ".." $skillFromRegistry.path
        if (Test-Path $registryPath) {
            if (-not (Test-SkillPlatform -SkillMdPath $registryPath)) {
                Write-Verbose "Skipping platform-incompatible skill '$ref' (registry)"
                continue
            }
            if (-not (Test-SkillEnabled -SkillMdPath $registryPath)) {
                Write-Verbose "Skipping disabled skill '$ref' (registry)"
                continue
            }
            $resolvedSkills[$ref] = [PSCustomObject]@{
                Name = $ref
                Path = $registryPath
                Tier = "Explicit"
            }
            continue
        }
    }

    # Check if already resolved (duplicate)
    if ($resolvedSkills.ContainsKey($ref)) { continue }

    # Strategy 2: Local hierarchical search
    # Search order (own-role wins over flat to avoid surprises):
    #   1. skills/roles/<RoleName>/<ref>/SKILL.md   (own role — highest priority)
    #   2. skills/<ref>/SKILL.md                    (flat)
    #   3. skills/global/<ref>/SKILL.md             (global)
    #   4. skills/roles/*/<ref>/SKILL.md            (any role)
    $localPath = $null
    $ownRolePath = Join-Path $SkillsBaseDir "roles" $baseRole $ref "SKILL.md"
    $searchPaths = @(
        $ownRolePath
        (Join-Path $SkillsBaseDir $ref "SKILL.md")
    )
    $searchPaths += (Join-Path $SkillsBaseDir "global" $ref "SKILL.md")
    $rolesSkillDir = Join-Path $SkillsBaseDir "roles"
    if (Test-Path $rolesSkillDir) {
        Get-ChildItem -Path $rolesSkillDir -Directory -ErrorAction SilentlyContinue | ForEach-Object {
            if ($_.Name -ne $baseRole) {
                $searchPaths += Join-Path $_.FullName $ref "SKILL.md"
            }
        }
    }

    foreach ($candidate in $searchPaths) {
        if (Test-Path $candidate) {
            $localPath = $candidate
            break
        }
    }

    if ($localPath) {
        if (-not (Test-SkillPlatform -SkillMdPath $localPath)) {
            Write-Verbose "Skipping platform-incompatible skill '$ref'"
            continue
        }
        if (-not (Test-SkillEnabled -SkillMdPath $localPath)) {
            Write-Verbose "Skipping disabled skill '$ref'"
            continue
        }
        $resolvedSkills[$ref] = [PSCustomObject]@{
            Name = $ref
            Path = $localPath
            Tier = "Explicit"
        }
    }
    else {
        # Strategy 3: Backend fetch — download skill content from dashboard API
        $fetched = $false
        if ($ApiKey) {
            try {
                $headers = @{ "X-API-Key" = $ApiKey }
                $searchUrl = "$DashboardUrl/api/skills/search?q=$([uri]::EscapeDataString($ref))&role=$([uri]::EscapeDataString($baseRole))"
                $response = @(Invoke-RestMethod -Uri $searchUrl -Headers $headers -Method Get -TimeoutSec 10 -ErrorAction Stop)

                $matchedSkill = $null
                if ($response.Count -gt 0 -and $null -ne $response[0]) {
                    $matchedSkill = $response | Where-Object { $_.name -eq $ref } | Select-Object -First 1
                    if (-not $matchedSkill) { $matchedSkill = $response[0] }
                }

                if ($matchedSkill -and $matchedSkill.relative_path -and $matchedSkill.content -and (Test-SkillPlatform -SkillMdPath (Join-Path $SkillsBaseDir ($matchedSkill.relative_path -replace '^skills/', '') "SKILL.md"))) {
                    $relPath = $matchedSkill.relative_path
                    $subPath = $relPath -replace '^skills/', ''
                    $localSkillDir = Join-Path $SkillsBaseDir $subPath
                    $localSkillMd = Join-Path $localSkillDir "SKILL.md"

                    if (-not (Test-Path $localSkillDir)) {
                        New-Item -ItemType Directory -Path $localSkillDir -Force | Out-Null
                    }

                    $frontmatter = @"
---
name: $($matchedSkill.name)
description: $($matchedSkill.description)
---
"@
                    $fullContent = "$frontmatter`n`n$($matchedSkill.content)"
                    $fullContent | Out-File -FilePath $localSkillMd -Encoding utf8 -Force

                    $resolvedSkills[$ref] = [PSCustomObject]@{
                        Name = $matchedSkill.name
                        Path = $localSkillMd
                        Tier = "Backend"
                    }
                    Write-Verbose "Fetched skill '$ref' from backend -> $localSkillMd"
                    $fetched = $true
                }
            }
            catch {
                Write-Verbose "Backend skill fetch failed for '$ref': $_"
            }
        }

        if (-not $fetched) {
            # Unresolvable — skip gracefully
            Write-Verbose "Skill '$ref' not resolvable locally or via backend — skipping"
        }
    }
}

return $resolvedSkills.Values | Sort-Object Tier, Name
