<#
.SYNOPSIS
    Parses ASCII lifecycle diagrams into lifecycle.json-compatible objects.

.DESCRIPTION
    Converts human-readable ASCII lifecycle text like:

        pending → engineer → qa ─┬─► passed → signoff
                     ▲           │
                     └─ engineer ◄┘ (on fail → fixing)

    into a structured lifecycle.json object that the manager loop can consume.

    The parser handles:
    - Main flow line: splits on arrow characters to get ordered stages
    - Fork pattern (─┬─►): detects the branch where done/pass goes forward, fail loops back
    - Review vs worker classification via name heuristics
    - Fail/fixing loop wiring from secondary lines
    - Terminal states: passed, signoff

.PARAMETER Text
    The raw ASCII lifecycle text (multi-line string).

.OUTPUTS
    PSObject matching the lifecycle.json schema:
    {
        "initial_state": "...",
        "states": {
            "<state>": { "type": "agent", "role": "<role>", "transitions": { ... } },
            ...
        }
    }

.EXAMPLE
    $text = @"
    pending → engineer → qa ─┬─► passed → signoff
                 ▲           │
                 └─ engineer ◄┘ (on fail → fixing)
    "@
    $lifecycle = ConvertFrom-AsciiLifecycle -Text $text
    $lifecycle | ConvertTo-Json -Depth 10
#>
function ConvertFrom-AsciiLifecycle {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory, Position = 0)]
        [string]$Text
    )

    $lines = $Text -split "`n" | ForEach-Object { $_.Trim() } | Where-Object { $_ }
    if ($lines.Count -eq 0) {
        Write-Warning "ConvertFrom-AsciiLifecycle: empty input"
        return $null
    }

    # ──────────────────────────────────────────────────────────────────────
    # STEP 1: Parse the main flow line (first line with → arrows)
    # ──────────────────────────────────────────────────────────────────────
    $mainLine = $lines[0]

    # Detect if there's a fork (─┬─► or ┬) — the stage before the fork is a reviewer
    # It decides done/pass (forward) or fail (loop back to fixing)
    $hasFork = $mainLine -match '[┬]'

    # Find which segment sits immediately before the fork character
    $forkSegmentName = ''
    if ($hasFork) {
        # Extract the text just before ┬: e.g. "analyst ─┬─►" → "analyst"
        if ($mainLine -match '([a-zA-Z0-9_-]+)\s*─*┬') {
            $forkSegmentName = $Matches[1].ToLower()
        }
    }

    # Normalize arrow characters into a standard delimiter
    # Handle: →  ─►  ─┬─►  ──►  ►
    $normalized = $mainLine -replace '─+┬─+►', ' → '   # Fork: ─┬─► → just split it
    $normalized = $normalized -replace '─+►', ' → '      # Plain: ─► or ──►
    $normalized = $normalized -replace '►', ' → '         # Bare ►

    # Split on → (with optional whitespace)
    $segments = ($normalized -split '\s*→\s*') |
        ForEach-Object { $_.Trim() } |
        Where-Object { $_ -and $_ -ne '─' -and $_ -ne '┬' }

    # Clean up any remaining box-drawing chars from segment names
    $segments = $segments | ForEach-Object {
        ($_ -replace '[─┬┘┐└┌│▲►◄╴╶┤├]', '').Trim()
    } | Where-Object { $_ }

    # ──────────────────────────────────────────────────────────────────────
    # STEP 2: Classify each segment
    # ──────────────────────────────────────────────────────────────────────
    # Remove meta-states from the processing list
    $terminalStates = @('pending', 'passed', 'signoff', 'fixing')
    $reviewHeuristic = '(review|qa|audit|check|validate|verify|test|reviewer)'

    $stages = [System.Collections.Generic.List[PSObject]]::new()
    $hasSignoff = $false

    foreach ($seg in $segments) {
        $segLower = $seg.ToLower()

        if ($segLower -eq 'pending') { continue }       # Entry point, not a real stage
        if ($segLower -eq 'signoff') { $hasSignoff = $true; continue }  # Terminal
        if ($segLower -eq 'passed')  { continue }       # Terminal target

        # Classify: review if it matches heuristic OR if it's the fork stage
        $isReview = ($segLower -match $reviewHeuristic) -or ($segLower -eq $forkSegmentName)
        $stages.Add([PSCustomObject]@{
            StateName = $segLower
            Role      = $segLower
            Type      = if ($isReview) { 'review' } else { 'worker' }
        })
    }

    if ($stages.Count -eq 0) {
        Write-Warning "ConvertFrom-AsciiLifecycle: no stages parsed from: $mainLine"
        return $null
    }

    # ──────────────────────────────────────────────────────────────────────
    # STEP 3: Detect the fail target from secondary lines
    # ──────────────────────────────────────────────────────────────────────
    # Look for patterns like:
    #   └─ engineer ◄┘ (on fail → fixing)
    #   └── ui-designer ◄───────────┘ (on fail → fixing)
    # The role name between └─ and ◄ is the fixing role (who does the rework)
    $fixingRole = $stages[0].Role  # Default: primary worker does the fixing
    $failTarget = $null

    for ($i = 1; $i -lt $lines.Count; $i++) {
        $line = $lines[$i]
        # Match: └─ <role> ◄  OR  └── <role> ◄
        if ($line -match '[└]─+\s*([a-zA-Z0-9_-]+)\s*[◄<]') {
            $fixingRole = $Matches[1].ToLower()
        }
        # Also look for explicit "on fail" annotation
        if ($line -match 'on\s+fail') {
            # The fail pattern confirms the fork loops back
            $failTarget = 'fixing'
        }
    }

    # If we detected a fork (┬) but no explicit fail annotation,
    # the fork itself implies: done/pass → forward, fail → back to fixing
    if ($hasFork -and -not $failTarget) {
        $failTarget = 'fixing'
    }

    # ──────────────────────────────────────────────────────────────────────
    # STEP 4: Build the lifecycle.json structure
    # ──────────────────────────────────────────────────────────────────────
    $states = [ordered]@{}

    for ($i = 0; $i -lt $stages.Count; $i++) {
        $stage = $stages[$i]
        $stateName = $stage.StateName

        # What does this stage transition to on success?
        if ($i -lt ($stages.Count - 1)) {
            $nextState = $stages[$i + 1].StateName
        } else {
            $nextState = 'passed'
        }

        $transitions = [ordered]@{}
        if ($stage.Type -eq 'review') {
            # Review stages: done goes forward, fail goes to manager-triage.
            # pass remains accepted for legacy generated lifecycles.
            $transitions['done'] = $nextState
            $transitions['pass'] = $nextState
            $transitions['fail'] = 'manager-triage'
            $transitions['escalate'] = 'manager-triage'
        } else {
            # Worker stages: done goes to next; pass remains legacy-compatible.
            $transitions['done'] = $nextState
            $transitions['pass'] = $nextState
        }

        $states[$stateName] = [ordered]@{
            type        = 'agent'
            role        = $stage.Role
            transitions = $transitions
        }
    }

    # --- Fixing state ---
    # Routes back to the first review stage (matching the fork pattern:
    # after fixing, the work goes back through review, not straight to passed)
    $firstReview = $stages | Where-Object { $_.Type -eq 'review' } | Select-Object -First 1
    $fixReturnTarget = if ($firstReview) { $firstReview.StateName } else { 'passed' }

    $states['fixing'] = [ordered]@{
        type        = 'agent'
        role        = $fixingRole
        transitions = [ordered]@{ done = $fixReturnTarget }
    }

    # --- Builtin states (always present) ---
    $states['manager-triage'] = [ordered]@{
        type        = 'builtin'
        role        = 'manager'
        transitions = [ordered]@{}
    }
    $states['plan-revision'] = [ordered]@{
        type        = 'builtin'
        role        = 'manager'
        transitions = [ordered]@{}
    }

    # ──────────────────────────────────────────────────────────────────────
    # STEP 5: Return the lifecycle object
    # ──────────────────────────────────────────────────────────────────────
    $initialState = $stages[0].StateName

    return [ordered]@{
        initial_state = $initialState
        states        = $states
    }
}
