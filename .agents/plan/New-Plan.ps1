#Requires -Version 7.0

<#
.SYNOPSIS
    Creates a new development plan with AI-assisted ideation.
.DESCRIPTION
    Provides interactive or non-interactive plan creation. Supports AI ideation
    to generate epics and tasks from project goals, with feedback loops for
    refinement. Outputs a structured plan file.

    Replaces: plan.sh (create mode)

.PARAMETER ProjectDir
    Project root directory.
.PARAMETER Goal
    High-level project goal for AI ideation.
.PARAMETER PlanFile
    Path to write the plan. Default: <ProjectDir>/plan-<timestamp>.md
.PARAMETER InitFile
    Optional path to an initial markdown file to use as the plan content.
    When provided, the file content becomes the plan's first version.
    If -Goal is not specified, the title is extracted from the markdown
    header (# Plan: ...) or from the filename.
.PARAMETER NonInteractive
    Skip interactive prompts and use defaults.

.EXAMPLE
    ./New-Plan.ps1 -ProjectDir "/project" -Goal "Implement user auth with JWT" -NonInteractive
.EXAMPLE
    ./New-Plan.ps1 -ProjectDir "/project" -InitFile "./my-plan-draft.md"
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$ProjectDir,

    [string]$Goal = '',

    [string]$PlanFile = '',

    [string]$InitFile = '',

    [switch]$NonInteractive
)

# --- Resolve paths ---
$agentsDir = Join-Path $ProjectDir ".agents"
if (-not (Test-Path $agentsDir)) { $agentsDir = $PSScriptRoot | Split-Path }

# --- Generate plan file name ---
if (-not $PlanFile) {
    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $PlanFile = Join-Path $ProjectDir "plan-$timestamp.md"
}

# --- Read initial file if provided ---
$initContent = ''
if ($InitFile) {
    if (-not (Test-Path $InitFile)) {
        throw "File not found: $InitFile"
    }
    $initContent = Get-Content -Path $InitFile -Raw

    # Extract title from markdown header if -Goal not given
    if (-not $Goal) {
        $titleMatch = [regex]::Match($initContent, '^#\s+(?:Plan:\s*)?(.+)', [System.Text.RegularExpressions.RegexOptions]::Multiline)
        if ($titleMatch.Success) {
            $Goal = $titleMatch.Groups[1].Value.Trim()
        } else {
            # Fall back to filename stem
            $Goal = [System.IO.Path]::GetFileNameWithoutExtension($InitFile)
        }
    }
}

# --- Interactive goal prompt ---
if (-not $Goal -and -not $InitFile -and -not $NonInteractive) {
    Write-Host ""
    Write-Host "=== Ostwin Plan Creator ===" -ForegroundColor Cyan
    Write-Host ""
    $Goal = Read-Host "What is the goal of this plan?"
}

if (-not $Goal) {
    throw "No goal provided. Use -Goal parameter, -InitFile, or interactive mode."
}

# --- Generate plan file name ---
if (-not $PlanFile) {
    # Create a friendly slug from the goal
    $slug = $Goal -replace '[^a-zA-Z0-9]+', '-' -replace '^-|-$', ''
    $slug = $slug.ToLower()
    if ($slug.Length -gt 40) { $slug = $slug.Substring(0, 40) -replace '-$', '' }
    if (-not $slug) { $slug = "plan-$(Get-Date -Format 'yyyyMMdd-HHmmss')" }
    
    $plansDir = Join-Path $ProjectDir "plans"
    if (-not (Test-Path $plansDir)) { New-Item -ItemType Directory -Path $plansDir -Force | Out-Null }
    $defaultPlanFile = Join-Path $plansDir "$slug.md"
    
    if (-not $NonInteractive) {
        $relativePath = $defaultPlanFile.Replace($ProjectDir + [System.IO.Path]::DirectorySeparatorChar, "")
        $promptMsg = "Where would you like to save this plan? [default: $relativePath]"
        $userInput = Read-Host $promptMsg
        
        if ($userInput) {
            # If user entered an absolute path, use it. Otherwise, combine with ProjectDir.
            if ([System.IO.Path]::IsPathRooted($userInput)) {
                $PlanFile = $userInput
            } else {
                $PlanFile = Join-Path $ProjectDir $userInput
            }
        } else {
            $PlanFile = $defaultPlanFile
        }
    } else {
        $PlanFile = $defaultPlanFile
    }
}

# --- Ensure custom plan directory exists if they changed it ---
$customPlanDir = Split-Path $PlanFile
if (-not (Test-Path $customPlanDir)) {
    [void](New-Item -ItemType Directory -Path $customPlanDir -Force)
}

# --- Build plan structure ---
if ($initContent) {
    # Use the provided initial file content
    $planContent = $initContent
} else {
    # Generate a sample plan
    $planContent = @"
# Plan: $Goal

> Created: $(Get-Date -Format 'yyyy-MM-ddTHH:mm:ssZ' -AsUTC)
> Status: draft
> Project: $ProjectDir

---

## Goal

$Goal

## Agent Roles

<!-- SUGGESTED ROLES — common starting points, not a limit -->
<!-- You are encouraged to invent the ideal specialist for each epic -->

| Role | Description | Skills |
|------|-------------|--------|
| engineer | General full-stack engineer | python, javascript, powershell |
| engineer:fe | Frontend specialist | javascript, typescript, css, html |
| engineer:be | Backend specialist | python, sql, docker, powershell |
| qa | Code review & test validation | testing, security-audit |
| architect | System design & tech decisions | architecture, documentation |

### Defining Custom Roles

You are NOT limited to the roles above. For each epic, define the best-fit agent
for the job. The more specific the role, the better the agent performs.

Per-epic format:
```
Role: <role-name>            (preset name OR any custom role you invent)
Objective: <mission>         (what this agent must achieve — be specific)
Skills: <capabilities>       (comma-separated, guides the agent's focus)
Working_dir: <path>            (scope the agent to a specific subdirectory)
```

Think: **"What kind of expert would I hire specifically for this epic?"**

## Epics

### EPIC-001 — $Goal

Role: engineer
Objective: Implement the core functionality with clean, tested code
Skills: python, javascript, testing
Working_dir: src/

#### Definition of Done
- [ ] Core functionality implemented
- [ ] Unit tests passing with >= 80% coverage
- [ ] Code reviewed and documented

#### Acceptance Criteria
- [ ] All specified features are working
- [ ] No critical or high-severity bugs
- [ ] Performance meets requirements

#### Tasks
- [ ] TASK-001 — Design and plan implementation
- [ ] TASK-002 — Implement core functionality
- [ ] TASK-003 — Write unit tests
- [ ] TASK-004 — Documentation and cleanup

depends_on: []

---

## Notes

_This plan was generated by Ostwin. Review and refine before starting._
_Each epic MUST have a "Role:" line. Use a preset or invent a custom role._
_Add "Objective:" and "Skills:" to give the agent a clear mission._
_Use "Working_dir:" to scope the agent to a specific subdirectory._
"@
}

# --- Write plan ---
$planContent | Out-File -FilePath $PlanFile -Encoding utf8

# --- Push plan to dashboard API ---
$dashboardUrl = if ($env:DASHBOARD_URL) { $env:DASHBOARD_URL } else { "http://localhost:3366" }
$registeredPlanId = ""
$metadataPlanId = [guid]::NewGuid().ToString().Replace("-", "").Substring(0, 12)

# Load API auth headers
$utilsModule = Join-Path $agentsDir "lib" "Utils.psm1"
if (Test-Path $utilsModule) { Import-Module $utilsModule -Force }
$apiHeaders = if (Get-Command Get-OstwinApiHeaders -ErrorAction SilentlyContinue) { Get-OstwinApiHeaders } else { @{} }

try {
    # Check if dashboard is reachable
    $null = Invoke-RestMethod -Uri "$dashboardUrl/api/status" -Headers $apiHeaders -TimeoutSec 3 -ErrorAction Stop

    # POST to create the plan via API
    $createBody = @{
        path        = $ProjectDir
        title       = $Goal
        working_dir = $ProjectDir
    }
    # Only include content when user provided an initial file;
    # otherwise let the API generate its own default.
    if ($initContent) {
        $createBody['content'] = $initContent
    }
    $createBodyJson = $createBody | ConvertTo-Json -Depth 5

    $response = Invoke-RestMethod -Uri "$dashboardUrl/api/plans/create" `
        -Method Post -ContentType 'application/json' -Body $createBodyJson -Headers $apiHeaders -ErrorAction Stop

    if ($response.plan_id) {
        $registeredPlanId = $response.plan_id
        $metadataPlanId = $registeredPlanId
        Write-Host ""
        Write-Host "[PLAN] Registered with API: plan_id = $registeredPlanId" -ForegroundColor Cyan
    }
}
catch {
    Write-Host ""
    Write-Host "[PLAN] ⚠  Dashboard not reachable at $dashboardUrl" -ForegroundColor Yellow
    Write-Host "[PLAN]   Start it with: ostwin dashboard" -ForegroundColor Yellow
}

# --- Update file with embedded config ---
$configBlock = @"

<!-- CONFIG
{
  "plan_id": "$metadataPlanId",
  "goals": {
    "definition_of_done": [
      "Core functionality implemented",
      "Unit tests passing with >= 80% coverage",
      "Code reviewed and documented"
    ],
    "acceptance_criteria": [
      "All specified features are working",
      "No critical or high-severity bugs",
      "Performance meets requirements"
    ]
  }
}
-->
"@
Add-Content -Path $PlanFile -Value $configBlock

Write-Host ""
Write-Host "[PLAN] Created: $PlanFile" -ForegroundColor Green
Write-Host "[PLAN] Goal: $Goal"
if ($InitFile) {
    Write-Host "[PLAN] Source: $InitFile" -ForegroundColor DarkGray
}
if ($registeredPlanId) {
    Write-Host "[PLAN] Plan ID: $registeredPlanId" -ForegroundColor Cyan
}
Write-Host "[PLAN] Epics: 1"
Write-Host "[PLAN] Tasks: 4"

Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Review and edit the plan"
if ($registeredPlanId) {
    Write-Host "  2. Run: ostwin run $registeredPlanId"
} else {
    Write-Host "  2. Run: ./.agents/plan/Start-Plan.ps1 -PlanFile '$PlanFile'"
}

# --- Return plan info ---
if ($registeredPlanId) {
    Write-Output $registeredPlanId
} else {
    Write-Output $PlanFile
}
