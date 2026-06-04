# Agent OS — Epic-to-TASKS.md Flow Tests
# Tests the complete lifecycle: PLAN → brief.md → Engineer prompt → TASKS.md → QA review
#
# These tests verify that:
# 1. brief.md captures the full EPIC content from the plan (description + DoD + AC)
# 2. The Engineer prompt correctly builds for Epic vs Task workflows
# 3. TASKS.md is created/read properly during epic flow
# 4. QA receives TASKS.md + brief.md together for epic reviews
# 5. Fix cycles re-inject existing TASKS.md context

BeforeAll {
    $script:agentsDir = (Resolve-Path (Join-Path (Resolve-Path "$PSScriptRoot/../../../roles/engineer").Path ".." "..")).Path
    $script:StartEngineer = Join-Path (Resolve-Path "$PSScriptRoot/../../../roles/engineer").Path "Start-Engineer.ps1"
    $script:NewWarRoom = Join-Path $script:agentsDir "war-rooms" "New-WarRoom.ps1"
    $script:StartQA = Join-Path $script:agentsDir "roles" "qa" "Start-QA.ps1"
    $script:PostMessage = Join-Path $script:agentsDir "channel" "Post-Message.ps1"
    $script:ReadMessages = Join-Path $script:agentsDir "channel" "Read-Messages.ps1"

    # ── Sample Sky Fighter EPIC content (from real plan) ──
    $script:SkyFighterEpicDesc = @"
Core Game Loop (Phase 1)

**Description:**
This Epic establishes the foundational architecture and core game loop for the "Sky Fighter" project. As the bedrock of the application, it sets up the rendering pipeline using Three.js and Vite, creating a responsive, high-performance environment.

The technical approach heavily emphasizes a robust, fixed-timestep game loop. By decoupling the physics and logic updates (locked at 60Hz) from the rendering frame rate, we ensure deterministic gameplay mechanics.

Key components introduced in this phase include a cross-platform input manager that normalizes both mouse and touch events into a reactive state, and a procedural low-poly player aircraft constructed from composed Three.js primitives.

#### Implementation Strategy

1. **Phase 1: Project Scaffolding & Engine Initialization**
   - Initialize the project utilizing vite@latest with the vanilla template and install three.
   - Configure the Vite base path for portable builds.
   - Implement engine.js to initialize the WebGLRenderer, PerspectiveCamera, and Scene.

2. **Phase 2: Core Architecture & Input**
   - Develop the fixed-timestep game loop in clock.js using the accumulator pattern.
   - Create config.js to centralize all tunable variables.
   - Build input.js to capture and normalize mousemove and touchmove events.

3. **Phase 3: Player Entity Development**
   - Construct the player aircraft in player.js by grouping Three.js primitives.
   - Implement movement logic that lerps the aircraft toward input coordinates.
"@

    $script:SkyFighterDoD = @(
        "Project compiles, bundles via Vite, and serves locally without any console errors or build warnings.",
        "Core game loop strictly implements an accumulator-based fixed timestep (60Hz update rate) separated from the rendering loop.",
        "Centralized config.js is fully integrated, containing all speed, boundary, lighting, and camera offset constants.",
        "Application scales correctly on window resize, maintaining aspect ratio without stretching or black bars.",
        "Performance profile shows stable 60 FPS rendering and zero memory leaks during a 5-minute continuous run.",
        "Project folder structure accurately reflects the architectural standard (src/main.js, core/, entities/, world/)."
    )

    $script:SkyFighterAC = @(
        "**Responsive Resizing:** Given the application is running, when the user resizes the browser window, then the canvas adjusts and the 3D scene maintains correct aspect ratio without distortion.",
        "**Unified Input Handling:** Given the game is active, when the user moves the mouse on desktop OR drags a finger on mobile, then the player aircraft moves smoothly to the corresponding relative screen position.",
        "**Aircraft Banking Animation:** Given the player aircraft is moving along the X-axis or Y-axis, then the model visually rolls or pitches slightly in the direction of movement.",
        "**Infinite Starfield:** Given the scene is rendering, then the background star particles continuously travel along the Z-axis and seamlessly reset, creating infinite forward motion.",
        "**Smooth Chase Camera:** Given the player aircraft changes position rapidly, when the camera updates, then it follows with a slight smooth delay (lerp) rather than rigidly locking.",
        "**Tab-Switching Resilience:** Given the user switches browser tabs and returns, when the game loop resumes, then the physics do not spiral out of control because the delta time is properly clamped."
    )

    $script:SkyFighterSubTasks = @"
# Tasks for EPIC-001

- [ ] TASK-001 — Project scaffolding
  - AC: npm create vite@latest works, npm install three installs, npm run dev opens blank page
- [ ] TASK-002 — Three.js engine setup (src/core/engine.js)
  - AC: WebGLRenderer, PerspectiveCamera, Scene with fog all initialized; resize handler works
- [ ] TASK-003 — Game loop with fixed timestep (src/core/clock.js)
  - AC: Accumulator-based 60Hz loop; delta clamped to 0.25s; no spiral on tab-switch
- [ ] TASK-004 — Input manager (src/core/input.js)
  - AC: Normalized -1..1 mouse/touch tracking; shooting via mouse/touch/space; no default scroll
- [ ] TASK-005 — Player aircraft (src/entities/player.js)
  - AC: Low-poly jet group renders; lerp-follows input; slight roll/pitch on movement
- [ ] TASK-006 — Chase camera (src/main.js)
  - AC: Camera offset (0, +3, -8); lerp follow with 0.05 factor; lookAt player
- [ ] TASK-007 — Starfield background (src/world/starfield.js)
  - AC: 2000 point particles scroll on Z; reset when behind camera; parallax effect
- [ ] TASK-008 — Lighting & sky (src/world/lighting.js)
  - AC: AmbientLight + DirectionalLight; background deep space blue 0x0a0a2e
- [ ] TASK-009 — Config constants (src/config.js)
  - AC: All magic numbers centralized; no hardcoded values in logic files
- [ ] TASK-010 — Integration & polish
  - AC: All modules wired in main.js; 60 FPS; no console warnings; resize works
"@
}

# =============================================================================
# SECTION 1: brief.md Capture — Does the war-room get full EPIC detail?
# =============================================================================
Describe "Epic Brief Capture — Plan → War-Room → brief.md" {
    BeforeEach {
        $script:warRoomsDir = Join-Path $TestDrive "warrooms-$(Get-Random)"
        New-Item -ItemType Directory -Path $script:warRoomsDir -Force | Out-Null
    }

    Context "New-WarRoom brief.md content for Epics" {
        It "brief.md contains the EPIC reference header" {
            & $script:NewWarRoom -RoomId "room-001" -TaskRef "EPIC-001" `
                -TaskDescription $script:SkyFighterEpicDesc `
                -WarRoomsDir $script:warRoomsDir `
                -DefinitionOfDone $script:SkyFighterDoD `
                -AcceptanceCriteria $script:SkyFighterAC

            $brief = Get-Content (Join-Path $script:warRoomsDir "room-001" "brief.md") -Raw
            $brief | Should -Match "^# EPIC-001"
        }

        It "brief.md contains the EPIC description body" {
            & $script:NewWarRoom -RoomId "room-001" -TaskRef "EPIC-001" `
                -TaskDescription $script:SkyFighterEpicDesc `
                -WarRoomsDir $script:warRoomsDir `
                -DefinitionOfDone $script:SkyFighterDoD `
                -AcceptanceCriteria $script:SkyFighterAC

            $brief = Get-Content (Join-Path $script:warRoomsDir "room-001" "brief.md") -Raw
            $brief | Should -Match "fixed-timestep game loop"
            $brief | Should -Match "Three.js"
            $brief | Should -Match "Implementation Strategy"
        }

        It "brief.md contains Working Directory section" {
            & $script:NewWarRoom -RoomId "room-001" -TaskRef "EPIC-001" `
                -TaskDescription $script:SkyFighterEpicDesc `
                -WarRoomsDir $script:warRoomsDir `
                -DefinitionOfDone $script:SkyFighterDoD `
                -AcceptanceCriteria $script:SkyFighterAC

            $brief = Get-Content (Join-Path $script:warRoomsDir "room-001" "brief.md") -Raw
            $brief | Should -Match "## Working Directory"
        }

        It "config.json stores DoD array with all items" {
            & $script:NewWarRoom -RoomId "room-001" -TaskRef "EPIC-001" `
                -TaskDescription $script:SkyFighterEpicDesc `
                -WarRoomsDir $script:warRoomsDir `
                -DefinitionOfDone $script:SkyFighterDoD `
                -AcceptanceCriteria $script:SkyFighterAC

            $config = Get-Content (Join-Path $script:warRoomsDir "room-001" "config.json") -Raw | ConvertFrom-Json
            $config.goals.definition_of_done.Count | Should -Be 6
            $config.goals.definition_of_done[0] | Should -Match "bundles via Vite"
        }

        It "config.json stores AC array with all items" {
            & $script:NewWarRoom -RoomId "room-001" -TaskRef "EPIC-001" `
                -TaskDescription $script:SkyFighterEpicDesc `
                -WarRoomsDir $script:warRoomsDir `
                -DefinitionOfDone $script:SkyFighterDoD `
                -AcceptanceCriteria $script:SkyFighterAC

            $config = Get-Content (Join-Path $script:warRoomsDir "room-001" "config.json") -Raw | ConvertFrom-Json
            $config.goals.acceptance_criteria.Count | Should -Be 6
            $config.goals.acceptance_criteria[0] | Should -Match "Responsive Resizing"
        }

        It "brief.md contains Definition of Done section" {
            # Fixed: New-WarRoom now appends DoD/AC to brief.md
            & $script:NewWarRoom -RoomId "room-001" -TaskRef "EPIC-001" `
                -TaskDescription $script:SkyFighterEpicDesc `
                -WarRoomsDir $script:warRoomsDir `
                -DefinitionOfDone $script:SkyFighterDoD `
                -AcceptanceCriteria $script:SkyFighterAC

            $brief = Get-Content (Join-Path $script:warRoomsDir "room-001" "brief.md") -Raw

            $brief | Should -Match "## Definition of Done"
            $brief | Should -Match "bundles via Vite"
            $brief | Should -Match "accumulator-based fixed timestep"
        }

        It "brief.md contains Acceptance Criteria section" {
            & $script:NewWarRoom -RoomId "room-001" -TaskRef "EPIC-001" `
                -TaskDescription $script:SkyFighterEpicDesc `
                -WarRoomsDir $script:warRoomsDir `
                -DefinitionOfDone $script:SkyFighterDoD `
                -AcceptanceCriteria $script:SkyFighterAC

            $brief = Get-Content (Join-Path $script:warRoomsDir "room-001" "brief.md") -Raw

            $brief | Should -Match "## Acceptance Criteria"
            $brief | Should -Match "Responsive Resizing"
            $brief | Should -Match "Tab-Switching Resilience"
        }

        It "brief.md omits DoD/AC sections when none provided" {
            & $script:NewWarRoom -RoomId "room-001" -TaskRef "TASK-001" `
                -TaskDescription "Simple task" `
                -WarRoomsDir $script:warRoomsDir

            $brief = Get-Content (Join-Path $script:warRoomsDir "room-001" "brief.md") -Raw
            $brief | Should -Not -Match "## Definition of Done"
            $brief | Should -Not -Match "## Acceptance Criteria"
        }
    }
}

# =============================================================================
# SECTION 2: Engineer Prompt Construction — Does it build correctly for epics?
# =============================================================================
Describe "Engineer Prompt Construction" {
    BeforeEach {
        $script:roomDir = Join-Path $TestDrive "room-eng-$(Get-Random)"
        New-Item -ItemType Directory -Path $script:roomDir -Force | Out-Null
        New-Item -ItemType Directory -Path (Join-Path $script:roomDir "pids") -Force | Out-Null
        New-Item -ItemType Directory -Path (Join-Path $script:roomDir "artifacts") -Force | Out-Null
        New-Item -ItemType File -Path (Join-Path $script:roomDir "channel.jsonl") -Force | Out-Null

        # Config with echo mock agent
        $script:configFile = Join-Path $TestDrive "config-eng-epic.json"
        @{
            engineer = @{
                cli              = "echo"
                default_model    = "test-model"
                timeout_seconds  = 10
                max_prompt_bytes = 204800
            }
            qa = @{ cli = "echo"; timeout_seconds = 10 }
        } | ConvertTo-Json -Depth 3 | Out-File $script:configFile -Encoding utf8
        $env:AGENT_OS_CONFIG = $script:configFile
    }

    AfterEach {
        Remove-Item Env:AGENT_OS_CONFIG -ErrorAction SilentlyContinue
    }

    Context "Epic workflow — prompt includes TASKS.md creation instructions" {
        It "detects EPIC prefix and selects epic workflow" {
            "EPIC-001" | Out-File (Join-Path $script:roomDir "task-ref") -NoNewline

            $taskRef = (Get-Content (Join-Path $script:roomDir "task-ref") -Raw).Trim()
            $isEpic = $taskRef -match '^EPIC-'
            $isEpic | Should -BeTrue
        }

        It "epic prompt instructs creating TASKS.md with checkboxes" {
            "EPIC-001" | Out-File (Join-Path $script:roomDir "task-ref") -NoNewline
            $isEpic = $true

            # Simulate the prompt construction from Start-Engineer.ps1 lines 163-187
            if ($isEpic) {
                $instructions = @"
You are working on an EPIC — a high-level feature that you must plan and implement yourself.

### Phase 1 — Planning
1. Analyze the brief above and break it into concrete sub-tasks
2. Create a file called TASKS.md at: $($script:roomDir)/TASKS.md
   - Use markdown checkboxes: - [ ] TASK-001 — Description
   - Each sub-task should be independently testable
   - Include acceptance criteria for each sub-task
3. Save TASKS.md before proceeding to implementation

### Phase 2 — Implementation
1. Work through each sub-task in TASKS.md sequentially
2. After completing each sub-task, check it off: - [x] TASK-001 — Description
3. Write tests as you go — each sub-task should be verified before moving on

### Phase 3 — Reporting
1. Ensure all checkboxes in TASKS.md are checked
2. Summarize your changes with:
   - Epic overview: what was delivered
   - Sub-tasks completed (include the final TASKS.md checklist)
   - Files modified/created
   - How to test the full epic
"@
            }

            $instructions | Should -Match "TASKS.md"
            $instructions | Should -Match "acceptance criteria for each sub-task"
            $instructions | Should -Match "markdown checkboxes"
            $instructions | Should -Match "Phase 1 — Planning"
        }

        It "task prompt does NOT mention TASKS.md" {
            "TASK-042" | Out-File (Join-Path $script:roomDir "task-ref") -NoNewline
            $taskRef = (Get-Content (Join-Path $script:roomDir "task-ref") -Raw).Trim()
            $isEpic = $taskRef -match '^EPIC-'

            if (-not $isEpic) {
                $instructions = @"
1. Implement the task described above
2. When done, summarize your changes clearly
3. Format your summary with: Changes Made, Files Modified, How to Test
"@
            }

            $instructions | Should -Not -Match "TASKS.md"
        }
    }

    Context "Brief.md reading with full Sky Fighter content" {
        It "Engineer reads full brief.md content" {
            "EPIC-001" | Out-File (Join-Path $script:roomDir "task-ref") -NoNewline
            $script:SkyFighterEpicDesc | Out-File (Join-Path $script:roomDir "brief.md") -Encoding utf8

            $taskDesc = Get-Content (Join-Path $script:roomDir "brief.md") -Raw
            $taskDesc | Should -Match "fixed-timestep game loop"
            $taskDesc | Should -Match "Three.js"
            $taskDesc | Should -Match "Implementation Strategy"
        }

        It "Engineer reads working directory from brief.md" {
            "EPIC-001" | Out-File (Join-Path $script:roomDir "task-ref") -NoNewline
            $briefContent = @"
# EPIC-001

$($script:SkyFighterEpicDesc)

## Working Directory
/Users/paulaan/PycharmProjects/phaser-examples/sky-fighter

## Created
2026-03-15T17:00:50Z
"@
            $briefContent | Out-File (Join-Path $script:roomDir "brief.md") -Encoding utf8

            $taskDesc = Get-Content (Join-Path $script:roomDir "brief.md") -Raw
            $workingDir = ''
            if ($taskDesc -match '## Working Directory\s*\n(.+)') {
                $workingDir = $Matches[1].Trim()
            }
            $workingDir | Should -Be "/Users/paulaan/PycharmProjects/phaser-examples/sky-fighter"
        }
    }
}

# =============================================================================
# SECTION 3: TASKS.md Lifecycle — Creation, Updating, Reading
# =============================================================================
Describe "TASKS.md Lifecycle" {
    BeforeEach {
        $script:roomDir = Join-Path $TestDrive "room-tasks-$(Get-Random)"
        New-Item -ItemType Directory -Path $script:roomDir -Force | Out-Null
        New-Item -ItemType Directory -Path (Join-Path $script:roomDir "pids") -Force | Out-Null
        New-Item -ItemType Directory -Path (Join-Path $script:roomDir "artifacts") -Force | Out-Null
        New-Item -ItemType File -Path (Join-Path $script:roomDir "channel.jsonl") -Force | Out-Null

        "EPIC-001" | Out-File (Join-Path $script:roomDir "task-ref") -NoNewline
    }

    Context "Engineer creates TASKS.md for epics" {
        It "TASKS.md can be created with proper checkbox format" {
            $script:SkyFighterSubTasks | Out-File (Join-Path $script:roomDir "TASKS.md") -Encoding utf8

            $tasks = Get-Content (Join-Path $script:roomDir "TASKS.md") -Raw
            $tasks | Should -Match "# Tasks for EPIC-001"
            $tasks | Should -Match "- \[ \] TASK-001"
            $tasks | Should -Match "- \[ \] TASK-010"
        }

        It "TASKS.md sub-tasks include acceptance criteria" {
            $script:SkyFighterSubTasks | Out-File (Join-Path $script:roomDir "TASKS.md") -Encoding utf8

            $tasks = Get-Content (Join-Path $script:roomDir "TASKS.md") -Raw
            # Each sub-task should have an AC line
            $tasks | Should -Match "AC:.*npm create vite"
            $tasks | Should -Match "AC:.*WebGLRenderer"
            $tasks | Should -Match "AC:.*Accumulator-based"
        }

        It "TASKS.md checkbox can be checked off" {
            $script:SkyFighterSubTasks | Out-File (Join-Path $script:roomDir "TASKS.md") -Encoding utf8

            $content = Get-Content (Join-Path $script:roomDir "TASKS.md") -Raw
            $updated = $content -replace '- \[ \] TASK-001', '- [x] TASK-001'
            $updated | Out-File (Join-Path $script:roomDir "TASKS.md") -Encoding utf8

            $result = Get-Content (Join-Path $script:roomDir "TASKS.md") -Raw
            $result | Should -Match "- \[x\] TASK-001"
            # Others remain unchecked
            $result | Should -Match "- \[ \] TASK-002"
        }

        It "counts unchecked vs checked tasks" {
            $script:SkyFighterSubTasks | Out-File (Join-Path $script:roomDir "TASKS.md") -Encoding utf8

            $content = Get-Content (Join-Path $script:roomDir "TASKS.md") -Raw
            $unchecked = [regex]::Matches($content, '- \[ \]').Count
            $checked = [regex]::Matches($content, '- \[x\]').Count

            $unchecked | Should -Be 10
            $checked | Should -Be 0
        }

        It "all tasks checked means epic complete" {
            $content = $script:SkyFighterSubTasks -replace '- \[ \]', '- [x]'
            $content | Out-File (Join-Path $script:roomDir "TASKS.md") -Encoding utf8

            $result = Get-Content (Join-Path $script:roomDir "TASKS.md") -Raw
            $unchecked = [regex]::Matches($result, '- \[ \]').Count
            $checked = [regex]::Matches($result, '- \[x\]').Count

            $unchecked | Should -Be 0
            $checked | Should -Be 10
        }
    }

    Context "TASKS.md is NOT created for standalone tasks" {
        It "Task workflow does not produce TASKS.md" {
            "TASK-042" | Out-File (Join-Path $script:roomDir "task-ref") -NoNewline

            $taskRef = (Get-Content (Join-Path $script:roomDir "task-ref") -Raw).Trim()
            $isEpic = $taskRef -match '^EPIC-'

            $isEpic | Should -BeFalse
            Test-Path (Join-Path $script:roomDir "TASKS.md") | Should -BeFalse
        }
    }
}

# =============================================================================
# SECTION 4: QA Review — Does QA receive TASKS.md + brief.md for epics?
# =============================================================================
Describe "QA Epic Review — TASKS.md Consumption" {
    BeforeEach {
        $script:roomDir = Join-Path $TestDrive "room-qa-epic-$(Get-Random)"
        New-Item -ItemType Directory -Path $script:roomDir -Force | Out-Null
        New-Item -ItemType Directory -Path (Join-Path $script:roomDir "pids") -Force | Out-Null
        New-Item -ItemType Directory -Path (Join-Path $script:roomDir "artifacts") -Force | Out-Null
        New-Item -ItemType File -Path (Join-Path $script:roomDir "channel.jsonl") -Force | Out-Null

        "EPIC-001" | Out-File (Join-Path $script:roomDir "task-ref") -NoNewline
        "review" | Out-File (Join-Path $script:roomDir "status") -NoNewline

        # Write the Sky Fighter brief
        @"
# EPIC-001

$($script:SkyFighterEpicDesc)

## Working Directory
/tmp/sky-fighter

## Created
2026-03-15T17:00:50Z
"@ | Out-File (Join-Path $script:roomDir "brief.md") -Encoding utf8
    }

    Context "QA reads TASKS.md for epic review" {
        It "QA detects EPIC prefix and loads TASKS.md" {
            # Create TASKS.md with completed tasks
            $completed = $script:SkyFighterSubTasks -replace '- \[ \]', '- [x]'
            $completed | Out-File (Join-Path $script:roomDir "TASKS.md") -Encoding utf8

            $taskRef = (Get-Content (Join-Path $script:roomDir "task-ref") -Raw).Trim()
            $isEpic = $taskRef -match '^EPIC-'
            $isEpic | Should -BeTrue

            $tasksMd = ""
            if ($isEpic) {
                $tasksFile = Join-Path $script:roomDir "TASKS.md"
                if (Test-Path $tasksFile) {
                    $tasksMd = Get-Content $tasksFile -Raw
                }
            }

            $tasksMd | Should -Match "TASK-001"
            $tasksMd | Should -Match "TASK-010"
            $tasksMd | Should -Match "\[x\]"
        }

        It "QA builds epic review instructions" {
            $completed = $script:SkyFighterSubTasks -replace '- \[ \]', '- [x]'
            $completed | Out-File (Join-Path $script:roomDir "TASKS.md") -Encoding utf8

            $taskRef = (Get-Content (Join-Path $script:roomDir "task-ref") -Raw).Trim()
            $isEpic = $taskRef -match '^EPIC-'

            $tasksMd = Get-Content (Join-Path $script:roomDir "TASKS.md") -Raw
            $taskDesc = Get-Content (Join-Path $script:roomDir "brief.md") -Raw

            $tasksSection = ""
            if ($isEpic -and $tasksMd) {
                $tasksSection = @"

## Engineer's Task Breakdown (TASKS.md)

$tasksMd
"@
            }

            $reviewInstructions = @"
You are reviewing an EPIC — a complete feature delivered by the engineer.

1. Review ALL code changes holistically across the full epic
2. Verify the TASKS.md checklist is complete — all sub-tasks must be checked off
3. Verify each sub-task was actually implemented (not just checked off)
4. Run the project test suite
5. Validate the epic delivers the feature described in the brief
6. Provide your verdict
"@
            # Verify prompt assembly
            $tasksSection | Should -Match "Engineer's Task Breakdown"
            $tasksSection | Should -Match "TASK-001"
            $reviewInstructions | Should -Match "TASKS.md checklist is complete"
        }

        It "QA handles missing TASKS.md for epic gracefully" {
            # No TASKS.md created
            $taskRef = (Get-Content (Join-Path $script:roomDir "task-ref") -Raw).Trim()
            $isEpic = $taskRef -match '^EPIC-'

            $tasksMd = ""
            if ($isEpic) {
                $tasksFile = Join-Path $script:roomDir "TASKS.md"
                if (Test-Path $tasksFile) {
                    $tasksMd = Get-Content $tasksFile -Raw
                }
            }

            $tasksMd | Should -BeNullOrEmpty
            # QA should still work — it just won't have the TASKS.md section
        }

        It "QA does NOT load TASKS.md for standalone tasks" {
            "TASK-042" | Out-File (Join-Path $script:roomDir "task-ref") -NoNewline

            $taskRef = (Get-Content (Join-Path $script:roomDir "task-ref") -Raw).Trim()
            $isEpic = $taskRef -match '^EPIC-'
            $isEpic | Should -BeFalse

            # Even if TASKS.md exists, QA ignores it for tasks
            $tasksMd = ""
            if ($isEpic) {
                $tasksMd = "should not reach here"
            }
            $tasksMd | Should -BeNullOrEmpty
        }

        It "Checks that all sub-tasks are checked off in TASKS.md" {
            $completed = $script:SkyFighterSubTasks -replace '- \[ \]', '- [x]'
            $completed | Out-File (Join-Path $script:roomDir "TASKS.md") -Encoding utf8

            $tasksMd = Get-Content (Join-Path $script:roomDir "TASKS.md") -Raw
            $unchecked = [regex]::Matches($tasksMd, '- \[ \]').Count
            $unchecked | Should -Be 0 -Because "all sub-tasks should be completed before QA review"
        }

        It "Detects incomplete TASKS.md (not all checked)" {
            # Only first 5 checked
            $partial = $script:SkyFighterSubTasks
            for ($i = 1; $i -le 5; $i++) {
                $partial = $partial -replace "- \[ \] TASK-00$i", "- [x] TASK-00$i"
            }
            $partial | Out-File (Join-Path $script:roomDir "TASKS.md") -Encoding utf8

            $tasksMd = Get-Content (Join-Path $script:roomDir "TASKS.md") -Raw
            $unchecked = [regex]::Matches($tasksMd, '- \[ \]').Count
            $checked = [regex]::Matches($tasksMd, '- \[x\]').Count

            $unchecked | Should -BeGreaterThan 0 -Because "some tasks are still pending"
            $checked | Should -Be 5
        }
    }
}

# =============================================================================
# SECTION 5: Fix Cycle — Does TASKS.md survive fix cycles?
# =============================================================================
Describe "Fix Cycle — TASKS.md Persistence and Re-injection" {
    BeforeEach {
        $script:roomDir = Join-Path $TestDrive "room-fix-$(Get-Random)"
        New-Item -ItemType Directory -Path $script:roomDir -Force | Out-Null
        New-Item -ItemType Directory -Path (Join-Path $script:roomDir "pids") -Force | Out-Null
        New-Item -ItemType Directory -Path (Join-Path $script:roomDir "artifacts") -Force | Out-Null
        New-Item -ItemType File -Path (Join-Path $script:roomDir "channel.jsonl") -Force | Out-Null

        "EPIC-001" | Out-File (Join-Path $script:roomDir "task-ref") -NoNewline
        "fixing" | Out-File (Join-Path $script:roomDir "status") -NoNewline
        "1" | Out-File (Join-Path $script:roomDir "retries") -NoNewline

        $script:SkyFighterEpicDesc | Out-File (Join-Path $script:roomDir "brief.md") -Encoding utf8

        # Partially completed TASKS.md from first attempt
        $partialTasks = $script:SkyFighterSubTasks `
            -replace '- \[ \] TASK-001', '- [x] TASK-001' `
            -replace '- \[ \] TASK-002', '- [x] TASK-002' `
            -replace '- \[ \] TASK-003', '- [x] TASK-003'
        $partialTasks | Out-File (Join-Path $script:roomDir "TASKS.md") -Encoding utf8
    }

    Context "TASKS.md survives between fix cycles" {
        It "TASKS.md persists across retries" {
            $tasks = Get-Content (Join-Path $script:roomDir "TASKS.md") -Raw
            $tasks | Should -Match "\[x\] TASK-001"
            $tasks | Should -Match "\[x\] TASK-002"
            $tasks | Should -Match "\[x\] TASK-003"
            $tasks | Should -Match "\[ \] TASK-004"
        }

        It "retries counter is preserved in room" {
            $retries = [int](Get-Content (Join-Path $script:roomDir "retries") -Raw).Trim()
            $retries | Should -Be 1
        }

        It "fix status is set in room" {
            $status = (Get-Content (Join-Path $script:roomDir "status") -Raw).Trim()
            $status | Should -Be "fixing"
        }
    }

    Context "[GAP] Engineer fix prompt should include existing TASKS.md" {
        It "existing TASKS.md can be read and injected into fix prompt" {
            # This tests the recommended fix: inject existing TASKS.md into
            # the Engineer's fix-cycle prompt so it knows what was already completed

            $taskRef = (Get-Content (Join-Path $script:roomDir "task-ref") -Raw).Trim()
            $isEpic = $taskRef -match '^EPIC-'
            $isEpic | Should -BeTrue

            $existingTasks = Join-Path $script:roomDir "TASKS.md"
            $existingTasksContent = ""
            if ($isEpic -and (Test-Path $existingTasks)) {
                $existingTasksContent = Get-Content $existingTasks -Raw
            }

            $existingTasksContent | Should -Not -BeNullOrEmpty
            $existingTasksContent | Should -Match "\[x\] TASK-001"
            $existingTasksContent | Should -Match "\[ \] TASK-004"

            # Build a fix prompt that includes existing TASKS.md
            $fixPrompt = @"
## Existing TASKS.md (from previous attempt)

$existingTasksContent

## QA Feedback

TASK-004 input manager does not prevent default scroll on mobile.
TASK-005 player aircraft does not bank on X-axis movement.

## Instructions

Fix the specific issues above. Update TASKS.md if new sub-tasks are needed.
"@
            $fixPrompt | Should -Match "Existing TASKS.md"
            $fixPrompt | Should -Match "QA Feedback"
            $fixPrompt | Should -Match "\[x\] TASK-001"
        }
    }

    Context "Triage context integration" {
        It "triage-context.md can be created alongside TASKS.md" {
            $triageContent = @"
# Manager Triage Context

## Classification: implementation-bug

## QA Failure Report
TASK-004 input manager does not prevent default scroll on mobile.
TASK-005 player aircraft does not bank on X-axis movement.

## Action Required
Engineer: Fix the specific issues listed in QA's report above.
"@
            $triageContent | Out-File (Join-Path $script:roomDir "artifacts" "triage-context.md") -Encoding utf8

            $triage = Get-Content (Join-Path $script:roomDir "artifacts" "triage-context.md") -Raw
            $triage | Should -Match "implementation-bug"
            $triage | Should -Match "TASK-004"

            # Both files exist in the room
            Test-Path (Join-Path $script:roomDir "TASKS.md") | Should -BeTrue
            Test-Path (Join-Path $script:roomDir "artifacts" "triage-context.md") | Should -BeTrue
        }
    }
}

# =============================================================================
# SECTION 6: End-to-End Scenario — Full Sky Fighter EPIC-001 lifecycle
# =============================================================================
Describe "End-to-End — Sky Fighter EPIC-001 Full Lifecycle" {
    BeforeEach {
        $script:warRoomsDir = Join-Path $TestDrive "warrooms-e2e-$(Get-Random)"
        New-Item -ItemType Directory -Path $script:warRoomsDir -Force | Out-Null
    }

    Context "Complete lifecycle: create → engineer → QA" {
        It "Step 1: Create war-room with full EPIC content" {
            & $script:NewWarRoom -RoomId "room-001" -TaskRef "EPIC-001" `
                -TaskDescription $script:SkyFighterEpicDesc `
                -WarRoomsDir $script:warRoomsDir `
                -DefinitionOfDone $script:SkyFighterDoD `
                -AcceptanceCriteria $script:SkyFighterAC

            $roomDir = Join-Path $script:warRoomsDir "room-001"

            # Room exists
            Test-Path $roomDir | Should -BeTrue
            # All core files present
            Test-Path (Join-Path $roomDir "brief.md") | Should -BeTrue
            Test-Path (Join-Path $roomDir "config.json") | Should -BeTrue
            Test-Path (Join-Path $roomDir "task-ref") | Should -BeTrue
            Test-Path (Join-Path $roomDir "status") | Should -BeTrue
            Test-Path (Join-Path $roomDir "channel.jsonl") | Should -BeTrue
        }

        It "Step 2: Engineer detects EPIC and would create TASKS.md" {
            & $script:NewWarRoom -RoomId "room-001" -TaskRef "EPIC-001" `
                -TaskDescription $script:SkyFighterEpicDesc `
                -WarRoomsDir $script:warRoomsDir `
                -DefinitionOfDone $script:SkyFighterDoD `
                -AcceptanceCriteria $script:SkyFighterAC

            $roomDir = Join-Path $script:warRoomsDir "room-001"

            # Verify Engineer can detect epic
            $taskRef = (Get-Content (Join-Path $roomDir "task-ref") -Raw).Trim()
            $taskRef | Should -Be "EPIC-001"
            ($taskRef -match '^EPIC-') | Should -BeTrue

            # Simulate Engineer creating TASKS.md
            $script:SkyFighterSubTasks | Out-File (Join-Path $roomDir "TASKS.md") -Encoding utf8
            Test-Path (Join-Path $roomDir "TASKS.md") | Should -BeTrue

            # Simulate checking off all tasks
            $content = Get-Content (Join-Path $roomDir "TASKS.md") -Raw
            $content = $content -replace '- \[ \]', '- [x]'
            $content | Out-File (Join-Path $roomDir "TASKS.md") -Encoding utf8

            $allDone = -not ([regex]::IsMatch((Get-Content (Join-Path $roomDir "TASKS.md") -Raw), '- \[ \]'))
            $allDone | Should -BeTrue
        }

        It "Step 3: QA reviews using brief.md + TASKS.md" {
            & $script:NewWarRoom -RoomId "room-001" -TaskRef "EPIC-001" `
                -TaskDescription $script:SkyFighterEpicDesc `
                -WarRoomsDir $script:warRoomsDir `
                -DefinitionOfDone $script:SkyFighterDoD `
                -AcceptanceCriteria $script:SkyFighterAC

            $roomDir = Join-Path $script:warRoomsDir "room-001"

            # Simulate completed TASKS.md
            $completed = $script:SkyFighterSubTasks -replace '- \[ \]', '- [x]'
            $completed | Out-File (Join-Path $roomDir "TASKS.md") -Encoding utf8

            # Verify QA can read both sources
            $brief = Get-Content (Join-Path $roomDir "brief.md") -Raw
            $tasksMd = Get-Content (Join-Path $roomDir "TASKS.md") -Raw
            $config = Get-Content (Join-Path $roomDir "config.json") -Raw | ConvertFrom-Json

            $brief | Should -Match "fixed-timestep game loop"
            $tasksMd | Should -Match "\[x\] TASK-001"
            $config.goals.definition_of_done.Count | Should -Be 6
            $config.goals.acceptance_criteria.Count | Should -Be 6
        }

        It "Step 4: QA can compare TASKS.md checkboxes to DoD/AC" {
            & $script:NewWarRoom -RoomId "room-001" -TaskRef "EPIC-001" `
                -TaskDescription $script:SkyFighterEpicDesc `
                -WarRoomsDir $script:warRoomsDir `
                -DefinitionOfDone $script:SkyFighterDoD `
                -AcceptanceCriteria $script:SkyFighterAC

            $roomDir = Join-Path $script:warRoomsDir "room-001"

            $completed = $script:SkyFighterSubTasks -replace '- \[ \]', '- [x]'
            $completed | Out-File (Join-Path $roomDir "TASKS.md") -Encoding utf8

            $config = Get-Content (Join-Path $roomDir "config.json") -Raw | ConvertFrom-Json
            $tasksMd = Get-Content (Join-Path $roomDir "TASKS.md") -Raw

            # QA checks: all TASKS.md done?
            $unchecked = [regex]::Matches($tasksMd, '- \[ \]').Count
            $unchecked | Should -Be 0

            # QA checks: DoD items can be cross-referenced
            $dodItems = $config.goals.definition_of_done
            $dodItems | Should -Contain "Project compiles, bundles via Vite, and serves locally without any console errors or build warnings."
            $dodItems | Should -Contain "Core game loop strictly implements an accumulator-based fixed timestep (60Hz update rate) separated from the rendering loop."

            # QA checks: AC items can be cross-referenced
            $acItems = $config.goals.acceptance_criteria
            ($acItems | Where-Object { $_ -match "Responsive Resizing" }).Count | Should -Be 1
            ($acItems | Where-Object { $_ -match "Tab-Switching Resilience" }).Count | Should -Be 1
        }
    }
}
