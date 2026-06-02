<#
.SYNOPSIS
    Maximizes planning detail in a PLAN.md using AI refinement.

.DESCRIPTION
    Parses a plan markdown file, identifies epics, and uses an AI architect
    to expand each epic into a detailed plan with clear Definition of Done,
    Acceptance Criteria, and dependency analysis.

.PARAMETER PlanFile
    Path to the raw plan markdown file.
.PARAMETER OutFile
    Path to write the refined plan. Defaults to <original>.refined.md next to the source file.
.PARAMETER DryRun
    Show what would be refined without calling the AI or writing the file.
.PARAMETER AgentCmd
    Optional path to a custom agent runner script. Used in tests to inject a mock AI.
    When not set, the real Invoke-Agent.ps1 with the 'architect' role is used.

.EXAMPLE
    ./Expand-Plan.ps1 -PlanFile "./plans/plan-001.md"
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$PlanFile,

    [string]$OutFile = '',

    [switch]$DryRun,

    [string]$AgentCmd = '',

    # Optional feedback from rejection to apply to refinement.
    [string]$Feedback = '',

    # Optional room directory for AI context. Default uses a temp room.
    [string]$RoomDir = '',

    # Dashboard plan ID to sync after expansion.
    # Defaults to the filename stem of $OutFile (e.g. 'c0d5ec36aa48' from 'c0d5ec36aa48.md').
    [string]$PlanId = ''
)

# --- Resolve paths ---
$scriptDir = $PSScriptRoot
$agentsDir = (Resolve-Path (Join-Path $scriptDir "..")).Path
$invokeAgent = Join-Path $agentsDir "roles" "_base" "Invoke-Agent.ps1"
$logModule = Join-Path $agentsDir "lib" "Log.psm1"
$utilsModule = Join-Path $agentsDir "lib" "Utils.psm1"

if (Test-Path $logModule) { Import-Module $logModule -Force }
if (Test-Path $utilsModule) { Import-Module $utilsModule -Force }

# --- Validate plan file ---
if (-not (Test-Path $PlanFile)) {
    throw "Plan file not found: $PlanFile"
}

$planContent = Get-Content $PlanFile -Raw
$planBase = [IO.Path]::GetFileNameWithoutExtension($PlanFile)
$planDir = Split-Path $PlanFile
if (-not $OutFile) {
    $OutFile = $PlanFile  # In-place update by default
}

# Accept - (single hyphen) as separator; also accept —, – for legacy
$epicPattern = '(?m)^#{2,3}\s+(EPIC-\d+)\s*[-—–?]\s*(.+)$'

$epicMatches = [regex]::Matches($planContent, $epicPattern)
if ($epicMatches.Count -eq 0) {
    Write-Host "No epics found to refine in $PlanFile"
    # exit 0 is intentional here — this is a top-level script entry point and
    # "no epics" is a successful (non-error) completion, not a failure.
    exit 0
}

Write-Host ""
Write-Host "=== Ostwin Plan Expander ===" -ForegroundColor Cyan
Write-Host "  Plan: $PlanFile"
Write-Host "  Epics to refine: $($epicMatches.Count)"
Write-Host ""

# --- Refinement loop ---
$refinedEpics = @{}

# Create a temporary room for expansion if not provided
$ownsTempRoom = $false
$expansionRoom = if ($RoomDir) { $RoomDir } else {
    $warRoomsDir = if ($env:WARROOMS_DIR) { $env:WARROOMS_DIR }
                   else { Join-Path (Split-Path $agentsDir) ".war-rooms" }
    $er = Join-Path $warRoomsDir "room-expansion"
    if (-not (Test-Path $er)) {
        New-Item -ItemType Directory -Path $er -Force | Out-Null
    }
    $ownsTempRoom = $true
    $er
}

foreach ($em in $epicMatches) {
    $epicRef = $em.Groups[1].Value
    $epicTitle = $em.Groups[2].Value.Trim()

    # Detect heading level (## or ###)
    $headingPrefix = if ($em.Value -match '^(#{2,3})') { $Matches[1] } else { '##' }

    # Find epic section
    $epicStart = $em.Index
    $nextMatch = $epicMatches | Where-Object { $_.Index -gt $epicStart } | Select-Object -First 1
    $epicEnd = if ($nextMatch) { $nextMatch.Index } else { $planContent.Length }
    $epicSection = $planContent.Substring($epicStart, $epicEnd - $epicStart)

    # --- Check if already well-specified ---
    # If feedback is provided, we must refine even if already well-specified.
    if (-not $Feedback -and -not (Test-Underspecified -Content $epicSection)) {
        Write-Host "  ${epicRef} is already well-specified. Skipping."
        continue
    }

    if ($DryRun) {
        Write-Host "  [DryRun] Would expand ${epicRef}: ${epicTitle}"
        continue
    }

    Write-Host "  Expanding ${epicRef}: ${epicTitle}..." -NoNewline

    $feedbackHeader = if ($Feedback) { "## Feedback to Address`n$Feedback`n" } else { "" }

    $prompt = @"
You are a Senior Software Architect. Your task is to REFINE and EXPAND a high-level Epic into a detailed implementation plan.

$feedbackHeader
## Original Epic
$epicSection

## Instructions
Maximize the detail in this plan. Your output MUST be a single markdown block representing the expansion of this Epic, following the Ostwin template:

1. **Description**: Expand the 1-2 line description into 3-5 paragraphs. Cover technical approach, key components, and potential risks. If feedback is provided above, ensure it is fully addressed in the refined content.
2. **Implementation Strategy**: Provide a sequential breakdown of the phases required to build this Epic. This should serve as the "detail plan for the team".
3. **Definition of Done (DoD)**: List at least 5 crystal-clear, verifiable conditions (e.g., "Unit test coverage >= 80%", "Lint clean", "Documentation updated").
4. **Acceptance Criteria (AC)**: List at least 5 testable scenarios (e.g., "User can login with valid JWT", "System rejects expired tokens with 401").
5. **Dependencies**: Identify if this TRULY depends on other EPICs from the plan. Only list an EPIC as a dependency if this epic genuinely cannot start until that other epic is finished (e.g. it consumes APIs or schemas defined there). Do NOT assume every epic depends on the one before it — parallel work is preferred when possible. Format as: depends_on: [EPIC-NNN] or depends_on: [] if none.
6. **Working Directory**: Analyze which subdirectory of the project this epic will primarily work in. Add a `Working_dir:` directive with a single relative path scoping the agent to only the relevant part of the codebase. Example: `Working_dir: dashboard/` or `Working_dir: bot/src/`. Only ONE path is allowed per epic. If the epic spans the entire project, omit this directive.

## Format Requirement
Return ONLY the refined markdown starting with '$headingPrefix $epicRef - $epicTitle'. Use a single hyphen '-' as the separator. Do not include any other text, chatter, or preamble.

### EXAMPLE OUTPUT
$headingPrefix EPIC-001 - Build Auth Module

[Detailed Description here...]

#### Definition of Done
- [ ] Core logic implemented
- [ ] ... (4 more)

#### Acceptance Criteria
- [ ] Scenario 1
- [ ] ... (4 more)

depends_on: []
"@

    $result = if ($AgentCmd) {
        $output = & $AgentCmd $prompt | Out-String
        $code = if ($?) { 0 } else { 1 }
        [PSCustomObject]@{ ExitCode = $code; Output = $output }
    } else {
        try {
            & $invokeAgent -RoomDir $expansionRoom -RoleName "architect" `
                             -Prompt $prompt -TimeoutSeconds 300 -ErrorAction Stop
        } catch {
            Write-Warning "Agent invocation failed for ${epicRef}: $($_.Exception.Message)"
            [PSCustomObject]@{ ExitCode = 1; Output = $_.Exception.Message }
        }
    }

    if ($result.ExitCode -eq 0) {
        $expanded = $result.Output.Trim()

        # Preserve per-epic metadata lines (Role/Roles, Objective, Working_dir,
        # Capabilities, Pipeline) that the AI may have dropped during expansion.
        $metaLines = @()
        foreach ($metaPattern in @(
            '(?m)^Roles?:\s*.+$',
            '(?m)^Objective:\s*.+$',
            '(?m)^Working_dir:\s*.+$',
            '(?m)^Capabilities:\s*.+$',
            '(?m)^Pipeline:\s*.+$'
        )) {
            $metaMatch = [regex]::Match($epicSection, $metaPattern)
            if ($metaMatch.Success) {
                $metaVal = $metaMatch.Value
                # Only inject if the expanded output doesn't already contain it
                if ($expanded -notmatch [regex]::Escape($metaVal)) {
                    $metaLines += $metaVal
                }
            }
        }
        if ($metaLines.Count -gt 0) {
            # Insert metadata right after the ## header line
            $headerEnd = [regex]::Match($expanded, '(?m)^#{2,3}\s+.+$')
            if ($headerEnd.Success) {
                $insertAt = $headerEnd.Index + $headerEnd.Length
                $metaBlock = "`n" + ($metaLines -join "`n")
                $expanded = $expanded.Insert($insertAt, $metaBlock)
            }
        }

        $refinedEpics[$epicRef] = $expanded
        Write-Host " [DONE]" -ForegroundColor Green
    } else {
        Write-Host " [FAILED]" -ForegroundColor Red
        Write-Warning "Refinement failed for ${epicRef}: $($result.Output)"
        $refinedEpics[$epicRef] = $epicSection # Fallback to original
    }
}

if ($DryRun) {
    Write-Host ""
    Write-Host "[DRY RUN] Complete. No changes made." -ForegroundColor Yellow
    exit 0
}

# --- Assemble refined plan ---
$newPlanContent = $planContent

foreach ($ref in $refinedEpics.Keys) {
    # Find the original epic section again to replace it
    $targetMatch = [regex]::Match($newPlanContent, "(?m)^#{2,3}\s+${ref}\s*[-—–]\s*.+$")
    if ($targetMatch.Success) {
        $start = $targetMatch.Index
        # Find end of section: next ## or ### EPIC- header or horizontal rule
        $afterRef = $newPlanContent.Substring($start + $targetMatch.Length)
        $nextSectionMatch = [regex]::Match($afterRef, "(?m)^(#{2,3}\s+EPIC-|---)")
        $end = if ($nextSectionMatch.Success) { $start + $targetMatch.Length + $nextSectionMatch.Index } else { $newPlanContent.Length }
        
        $newPlanContent = $newPlanContent.Remove($start, $end - $start).Insert($start, $refinedEpics[$ref] + "`n")
    }
}

# Normalize epic header separators: replace —, – with single -
$newPlanContent = $newPlanContent -replace '(?m)^(#{2,3}\s+EPIC-\d+)\s*[—–]\s*', '$1 - '
$newPlanContent | Out-File -FilePath $OutFile -Encoding utf8

Write-Host ""
Write-Host "[PLAN] Plan updated in-place: $OutFile" -ForegroundColor Green
Write-Host ""

# --- Sync expanded content to dashboard API ---
if (-not $DryRun) {
    $resolvedPlanId = if ($PlanId) { $PlanId } else { [IO.Path]::GetFileNameWithoutExtension($OutFile) }
    $dashboardUrl = if ($env:DASHBOARD_URL) { $env:DASHBOARD_URL } else { 'http://localhost:3366' }
    $apiHeaders = if (Get-Command Get-OstwinApiHeaders -ErrorAction SilentlyContinue) { Get-OstwinApiHeaders } else { @{} }
    try {
        $saveBody = @{ content = $newPlanContent; change_source = 'expansion' } | ConvertTo-Json -Depth 5
        Invoke-RestMethod -Uri "$dashboardUrl/api/plans/$resolvedPlanId/save" `
            -Method Post -ContentType 'application/json' -Body $saveBody -Headers $apiHeaders -ErrorAction Stop | Out-Null
        Write-Host "[PLAN] Synced to dashboard: $dashboardUrl/plans/$resolvedPlanId" -ForegroundColor Cyan
    }
    catch {
        Write-Host "[PLAN] ⚠ Dashboard not reachable — plan updated locally only." -ForegroundColor Yellow
    }
}

# --- Dependency analysis is handled separately by Review-Dependencies.ps1 ---
# Review-Dependencies.ps1 runs AFTER war-rooms are created (so it has access to
# actual brief.md files) and prompts the user for approval before applying changes.
# It is called by Start-Plan.ps1 after New-PlanWarRooms.

# Clean up temporary room (only if we created it — never delete an externally provided RoomDir)
if ($ownsTempRoom) {
    Remove-Item $expansionRoom -Recurse -Force -ErrorAction SilentlyContinue
}
