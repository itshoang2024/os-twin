<#
.SYNOPSIS
    Universal agent launcher — wraps opencode run for any role.

.DESCRIPTION
    Provides a common interface for launching opencode run with role-specific
    prompts, config, PID tracking, timeout, and output capture.
    Used by Start-Engineer.ps1, Start-QA.ps1, and future role runners.

    v0.3 — migrated from deepagents CLI to opencode run.

.PARAMETER RoomDir
    Path to the war-room directory.
.PARAMETER RoleName
    Role identifier (engineer, qa, architect, etc.). Passed as --agent.
.PARAMETER Prompt
    Full prompt text. Passed as a positional argument to opencode run.
.PARAMETER Model
    Model to use (provider/model format). Passed as --model / -m.
.PARAMETER TimeoutSeconds
    Max execution time. Default from config.
.PARAMETER AgentCmd
    Override CLI command (for testing with mocks). Default: opencode run.
.PARAMETER McpConfig
    Path to the MCP config JSON. Used to generate an opencode.json config
    in the artifacts dir. Pass empty string to disable MCP tool injection.
.PARAMETER Format
    Output format: 'default' (formatted) or 'json' (raw JSON events).
.PARAMETER Files
    File(s) to attach to the message. Each is passed as --file.
.PARAMETER SessionTitle
    Title for the session. Passed as --title.
.PARAMETER SessionId
    Session ID to continue. Passed as --session / -s.
.PARAMETER ContinueSession
    Continue the last session. Passed as --continue / -c.
.PARAMETER ForkSession
    Fork the session when continuing. Passed as --fork.
.PARAMETER ShareSession
    Share the session. Passed as --share.
.PARAMETER Command
    Command to run, use message for args. Passed as --command.
.PARAMETER AttachUrl
    Attach to a running opencode server. Passed as --attach.
.PARAMETER Port
    Port for the local server. Passed as --port.
.PARAMETER ExtraArgs
    Additional CLI arguments as string array.

.OUTPUTS
    PSCustomObject with ExitCode, Output, OutputFile, PidFile properties.

.EXAMPLE
    $result = ./Invoke-Agent.ps1 -RoomDir "./war-rooms/room-001" -RoleName "engineer" `
                                  -Prompt "Implement auth" -TimeoutSeconds 600
    if ($result.ExitCode -eq 0) { Write-Host "Success" }
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$RoomDir,

    [Parameter(Mandatory)]
    [string]$RoleName,

    [Parameter(Mandatory)]
    [string]$Prompt,

    [string]$Model = '',
    [int]$TimeoutSeconds = 600,
    [string]$AgentCmd = '',
    [string]$InstanceId = '',
    [string]$WorkingDir = '',
    [string]$McpConfig = '',
    [string]$Format = '',
    [string[]]$Files = @(),
    [string]$SessionTitle = '',
    [string]$SessionId = '',
    [switch]$ContinueSession,
    [switch]$ForkSession,
    [switch]$ShareSession,
    [string]$Command = '',
    [string]$AttachUrl = '',
    [int]$Port = 0,
    [string[]]$ExtraArgs = @()
)

# --- Resolve paths ---
$agentsDir = (Resolve-Path (Join-Path $PSScriptRoot ".." "..") -ErrorAction SilentlyContinue).Path

# Resolve OSTWIN_HOME: env var → ~/.ostwin
$_homeDir = if ($env:HOME) { $env:HOME } else { $env:USERPROFILE }
$OstwinHome = if ($env:OSTWIN_HOME) { $env:OSTWIN_HOME } else { Join-Path $_homeDir ".ostwin" }

# Ensure RoomDir is absolute for bash wrapper consistency (EPIC-002)
# Using GetUnresolvedProviderPathFromPSPath to handle non-existent paths (unlikely but safe)
$absRoomDir = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($RoomDir)

# --- Load config ---
$configPath = if ($env:AGENT_OS_CONFIG) { $env:AGENT_OS_CONFIG }
else { Join-Path $agentsDir "config.json" }

# --- Load plan-specific roles config from room's config.json → plan_id ---
$planRolesConfig = $null
$roomConfigFile = Join-Path $absRoomDir "config.json"
if (Test-Path $roomConfigFile) {
    try {
        $roomCfg = Get-Content $roomConfigFile -Raw | ConvertFrom-Json
        $roomPlanId = $roomCfg.plan_id
        if ($roomPlanId) {
            $planRolesFile = Join-Path $OstwinHome ".agents" "plans" "$roomPlanId.roles.json"
            if (Test-Path $planRolesFile) {
                $planRolesConfig = Get-Content $planRolesFile -Raw | ConvertFrom-Json
            }
        }
    }
    catch { }
}

# --- Plan roles resolution (highest priority after explicit -Model) ---
# Runs unconditionally — does NOT depend on .agents/config.json existing.
# Schema: { "<role>": { "default_model": "...", "timeout_seconds": N, "max_retries": N,
#                       "instances": { "<id>": { "default_model": "...", "timeout_seconds": N } } } }
$timeoutWasExplicit = $PSBoundParameters.ContainsKey('TimeoutSeconds')
$maxProcessRetries = 3  # default — overridden by plan roles / config / role.json below

if ($planRolesConfig -and $planRolesConfig.$RoleName) {
    $planRoleNode = $planRolesConfig.$RoleName

    if (-not $Model) {
        # Priority 1a: plan-roles instance override
        if ($InstanceId -and $planRoleNode.instances `
                -and $planRoleNode.instances.$InstanceId `
                -and $planRoleNode.instances.$InstanceId.default_model) {
            $Model = $planRoleNode.instances.$InstanceId.default_model
        }
        # Priority 1b: plan-roles role default
        elseif ($planRoleNode.default_model) {
            $Model = $planRoleNode.default_model
        }
    }

    if (-not $timeoutWasExplicit) {
        if ($InstanceId -and $planRoleNode.instances `
                -and $planRoleNode.instances.$InstanceId `
                -and $planRoleNode.instances.$InstanceId.timeout_seconds) {
            $TimeoutSeconds = [int]$planRoleNode.instances.$InstanceId.timeout_seconds
        }
        elseif ($planRoleNode.timeout_seconds) {
            $TimeoutSeconds = [int]$planRoleNode.timeout_seconds
        }
    }

    # max_retries from plan roles (highest priority)
    if ($planRoleNode.max_retries) {
        $maxProcessRetries = [int]$planRoleNode.max_retries
    }
}

# Safe defaults (overridden inside config block below)
$NoMcp = $false
$ProjectDir = ""

if (Test-Path $configPath) {
    $config = Get-Content $configPath -Raw | ConvertFrom-Json

    # --- Instance-aware config resolution ---
    $instanceConfig = $null
    if ($InstanceId -and $config.$RoleName.instances.$InstanceId) {
        $instanceConfig = $config.$RoleName.instances.$InstanceId
    }

    # Model fallback chain (plan roles already applied above):
    # instance → role config.json → role.json → hardcoded default
    if (-not $Model) {
        if ($instanceConfig -and $instanceConfig.default_model) {
            $Model = $instanceConfig.default_model
        }
        elseif ($config.$RoleName.default_model) {
            $Model = $config.$RoleName.default_model
        }
        else {
            # Try role.json as last config-based source
            $roleJsonPath = Join-Path $agentsDir "roles" $RoleName "role.json"
            if (Test-Path $roleJsonPath) {
                $roleJson = Get-Content $roleJsonPath -Raw | ConvertFrom-Json
                if ($roleJson.model) {
                    $Model = $roleJson.model
                }
            }
        }
    }

    # Normalize model: auto-prefix bare model names with their provider so opencode
    # can resolve them. Many dynamically-created role.json files store just
    # "gemini-3-flash-preview" without the "google-vertex/" prefix.
    if ($Model -and ($Model -notmatch '/')) {
        if ($Model -match '^gemini') {
            $Model = "google-vertex/$Model"
        }
        elseif ($Model -match '^claude') {
            $Model = "anthropic/$Model"
        }
        elseif ($Model -match '^gpt|^o1|^o3|^o4') {
            $Model = "openai/$Model"
        }
    }

    # Timeout fallback chain (plan roles already applied above): instance → role
    if (-not $timeoutWasExplicit) {
        if ($instanceConfig -and $instanceConfig.timeout_seconds) {
            $TimeoutSeconds = $instanceConfig.timeout_seconds
        }
        elseif ($config.$RoleName.timeout_seconds) {
            $TimeoutSeconds = $config.$RoleName.timeout_seconds
        }
    }

    # max_retries fallback chain: plan roles (already applied) → instance → role config.json
    if ($maxProcessRetries -eq 3) {
        if ($instanceConfig -and $instanceConfig.max_retries) {
            $maxProcessRetries = [int]$instanceConfig.max_retries
        }
        elseif ($config.$RoleName.max_retries) {
            $maxProcessRetries = [int]$config.$RoleName.max_retries
        }
    }

    # WorkingDir: parameter → instance config → room config.json
    if (-not $WorkingDir -and $instanceConfig) {
        if ($instanceConfig.PSObject.Properties['working_dir'] -and $instanceConfig.working_dir) {
            $WorkingDir = $instanceConfig.working_dir
        }
    }
    if (-not $WorkingDir -and $roomCfg -and $roomCfg.PSObject.Properties['working_dir'] -and $roomCfg.working_dir) {
        $WorkingDir = $roomCfg.working_dir
    }

    # no_mcp: instance → role → default false
    # MCP is enabled by default — pass --mcp-config from the project dir.
    # Set no_mcp: true in config.json for a role to disable MCP (e.g. unstable remote exec).
    $NoMcp = $false
    if ($instanceConfig -and $instanceConfig.PSObject.Properties['no_mcp']) {
        $NoMcp = [bool]$instanceConfig.no_mcp
    }
    elseif ($config.$RoleName -and $config.$RoleName.PSObject.Properties['no_mcp']) {
        $NoMcp = [bool]$config.$RoleName.no_mcp
    }

    # --- Resolve ProjectDir from RoomDir (parent of .war-rooms) ---
    # War-room paths follow: $PROJECT/.war-rooms/<plan>/<room>/
    # Walk up from RoomDir to find the directory containing .war-rooms
    $ProjectDir = ""
    $searchDir = $absRoomDir
    for ($i = 0; $i -lt 6; $i++) {
        $parentDir = Split-Path $searchDir -Parent
        if (-not $parentDir -or $parentDir -eq $searchDir) { break }
        if ((Split-Path $searchDir -Leaf) -eq ".war-rooms") {
            $ProjectDir = $parentDir
            break
        }
        $searchDir = $parentDir
    }
    # Fallback: env variable
    if (-not $ProjectDir -and $env:PROJECT_DIR) { $ProjectDir = $env:PROJECT_DIR }
    if (-not $ProjectDir -and $WorkingDir) { $ProjectDir = $WorkingDir }

    # --- Override ProjectDir with WorkingDir when scoped ---
    if ($WorkingDir) {
        $ProjectDir = $WorkingDir
    }

    # --- CLI resolution: (1) explicit -AgentCmd  →  (2) Role-specific env (e.g. ARCHITECT_CMD)  →  (3) OSTWIN_AGENT_CMD  →  (4) "opencode run" ---
    # No bin/agent binary lookup — the full flow is managed by the bash/powershell wrapper.
    if (-not $AgentCmd) {
        $roleEnvCmd = (Get-ChildItem Env: | Where-Object { $_.Name -eq "$($RoleName.ToUpper())_CMD" }).Value
        if ($roleEnvCmd) {
            $AgentCmd = $roleEnvCmd
        }
        elseif ($env:OSTWIN_AGENT_CMD) {
            $AgentCmd = $env:OSTWIN_AGENT_CMD
        }
    }
}

if (-not $AgentCmd) { $AgentCmd = "opencode run" }

# --- Role.json model + max_retries fallback (runs even when config.json is absent) ---
# If no model was resolved from -Model param, plan.roles.json, or config.json,
# try role.json as the last config-based source before the hardcoded default.
# Search order: HOME-based (authoritative) → project-local (legacy).
if (-not $Model -or $maxProcessRetries -eq 3) {
    $homeRoleJson = Join-Path $OstwinHome ".agents" "roles" $RoleName "role.json"
    $localRoleJson = Join-Path $agentsDir "roles" $RoleName "role.json"
    $roleJsonPath = if (Test-Path $homeRoleJson) { $homeRoleJson } elseif (Test-Path $localRoleJson) { $localRoleJson } else { $null }
    if ($roleJsonPath) {
        try {
            $roleJson = Get-Content $roleJsonPath -Raw | ConvertFrom-Json
            if (-not $Model -and $roleJson.model) {
                $Model = $roleJson.model
            }
            # max_retries from role.json (lowest config priority, above hardcoded default)
            if ($maxProcessRetries -eq 3 -and $roleJson.max_retries) {
                $maxProcessRetries = [int]$roleJson.max_retries
            }
        }
        catch { }
    }
}
if (-not $Model) { $Model = "google-vertex/zai-org/glm-5-maas" }

# --- Log resolved model/timeout/retries for debugging ---
# These are the values that will actually drive opencode run.
Write-Host "[Invoke-Agent] Resolved Role=$RoleName Instance=$InstanceId Model=$Model Timeout=${TimeoutSeconds}s MaxRetries=$maxProcessRetries"

# --- Prepare output directory ---
$artifactsDir = Join-Path $absRoomDir "artifacts"
$pidsDir = Join-Path $absRoomDir "pids"
New-Item -ItemType Directory -Path $artifactsDir -Force | Out-Null
New-Item -ItemType Directory -Path $pidsDir -Force | Out-Null

# --- Ensure ProjectDir is resolved (unconditional fallback) ---
# The config block above computes $ProjectDir only when config.json exists.
# Run the same walkup here so skill staging always uses the correct project dir,
# even for rooms without a config.json (e.g. test rooms, clean invocations).
if (-not $ProjectDir) {
    $searchDir2 = $absRoomDir
    for ($i = 0; $i -lt 6; $i++) {
        $parentDir2 = Split-Path $searchDir2 -Parent
        if (-not $parentDir2 -or $parentDir2 -eq $searchDir2) { break }
        if ((Split-Path $searchDir2 -Leaf) -eq ".war-rooms") {
            $ProjectDir = $parentDir2
            break
        }
        $searchDir2 = $parentDir2
    }
    if (-not $ProjectDir -and $env:PROJECT_DIR) { $ProjectDir = $env:PROJECT_DIR }
}

# --- Skill Staging: project-local .agents/skills/ (shared across rooms) ---
# Use the *project's* .agents/skills/, not the ostwin install tree ($agentsDir).
# This ensures skills appear at $project_dir/.agents/skills/ regardless of
# where Invoke-Agent.ps1 is installed (~/.ostwin or project-local dev copy).
$projectAgentsDir = if ($ProjectDir) { Join-Path $ProjectDir ".agents" } else { $agentsDir }
$isolatedSkillsDir = Join-Path $projectAgentsDir "skills"

# Ensure project-level skills dir exists
if (-not (Test-Path $isolatedSkillsDir)) {
    New-Item -ItemType Directory -Path $isolatedSkillsDir -Force | Out-Null
}

$rolePath = Join-Path $agentsDir "roles" $RoleName
$resolveSkillsScript = Join-Path $PSScriptRoot "Resolve-RoleSkills.ps1"

if (Test-Path $resolveSkillsScript) {
    try {
        $skills = & $resolveSkillsScript -RoleName $RoleName -RolePath $rolePath -RoomDir $absRoomDir -ErrorAction Stop
        foreach ($skill in $skills) {
            if ($skill.Path -and (Test-Path $skill.Path)) {
                # Copy the entire skill directory content to the isolated location
                $skillSrcDir = Split-Path $skill.Path -Parent
                $skillName = Split-Path $skillSrcDir -Leaf
                $destPath = Join-Path $isolatedSkillsDir $skillName

                # Ensure the destination skill directory exists and is clean
                if (Test-Path $destPath) {
                    Remove-Item -Path $destPath -Recurse -Force -ErrorAction SilentlyContinue
                }
                New-Item -ItemType Directory -Path $destPath -Force | Out-Null

                # Copy contents specifically to avoid nested directory issues
                Copy-Item -Path (Join-Path $skillSrcDir "*") -Destination $destPath -Recurse -Force -ErrorAction SilentlyContinue
            }
            else {
                Write-Warning "Skill source path not found for '$($skill.Name)': $($skill.Path)"
            }
        }
    }
    catch {
        Write-Warning "Failed to resolve or copy skills: $($_.Exception.Message)"
    }
}


$outputFile = Join-Path $artifactsDir "$RoleName-output.txt"
$pidFile = Join-Path $pidsDir "$RoleName.pid"

# --- PID is written by bin/agent via AGENT_OS_PID_FILE env var ---
# No premature PID write here. The agent process self-registers after startup.



# --- Execute with timeout and transient-error retry ---
# $maxProcessRetries was resolved above from plan roles → config.json → role.json → default 3
$exitCode = 0

$stdinNull = if ($IsLinux -or $IsMacOS) { "/dev/null" }
else { "NUL" }

# Write prompt to a file to avoid shell escaping issues
$promptFile = Join-Path $artifactsDir "prompt.txt"
$Prompt | Out-File -FilePath $promptFile -Encoding utf8 -NoNewline -Force
# Resolve to absolute path for -f flag
$promptFileAbsolute = (Resolve-Path $promptFile).Path

# --- Debug: write a human-readable copy of the compiled prompt ---
$debugPromptFile = Join-Path $artifactsDir "$RoleName-prompt-debug.md"
$Prompt | Out-File -FilePath $debugPromptFile -Encoding utf8 -Force

# Build non-prompt CLI args safely (opencode run flags)
# Prompt is passed as --file <path> to avoid ARG_MAX limits with large prompts.
# A short positional message is required by opencode run — the full prompt is in the file.
$extraCliArgs = @("...")
if ($Model) { $extraCliArgs += "--model"; $extraCliArgs += $Model }
if ($RoleName) { $extraCliArgs += "--agent"; $extraCliArgs += $RoleName }
if ($Format) { $extraCliArgs += "--format"; $extraCliArgs += $Format }
if ($SessionTitle) { $extraCliArgs += "--title"; $extraCliArgs += $SessionTitle }
if ($SessionId) { $extraCliArgs += "--session"; $extraCliArgs += $SessionId }

# --- Detect if this is a lifecycle retry ---
$isLifecycleRetry = $false
$retriesFile = Join-Path $absRoomDir "retries"
if (Test-Path $retriesFile) {
    try {
        $roomRetries = [int](Get-Content $retriesFile -Raw).Trim()
        if ($roomRetries -gt 0) { $isLifecycleRetry = $true }
    } catch {}
}

if ($ContinueSession -or $isLifecycleRetry) { $extraCliArgs += "--continue" }
if ($ForkSession) { $extraCliArgs += "--fork" }
if ($ShareSession) { $extraCliArgs += "--share" }
if ($Command) { $extraCliArgs += "--command"; $extraCliArgs += $Command }
if ($AttachUrl) { $extraCliArgs += "--attach"; $extraCliArgs += $AttachUrl }
if ($Port -gt 0) { $extraCliArgs += "--port"; $extraCliArgs += $Port.ToString() }
if ($ProjectDir) { $extraCliArgs += "--dir"; $extraCliArgs += $ProjectDir }
foreach ($f in $Files) { $extraCliArgs += "--file"; $extraCliArgs += $f }
# Attach prompt file — avoids inlining huge prompt text on the command line
$extraCliArgs += "--file"; $extraCliArgs += $promptFileAbsolute

# --- MCP config: use pre-compiled .opencode/opencode.json if available ---
# opencode run reads MCP config from .opencode/opencode.json (standard location).
# Invoke-Agent does NOT generate opencode.json — it must be pre-compiled by ostwin init/compile.
$tempMcpConfig = $null
if (-not $NoMcp -and $ProjectDir) {
    $precompiledOpencode = Join-Path $ProjectDir ".opencode" "opencode.json"
    if (Test-Path $precompiledOpencode) {
        $tempMcpConfig = $precompiledOpencode
    }
}

$extraCliArgs += $ExtraArgs
$extraCliArgs += "--dangerously-skip-permissions"

for ($processAttempt = 1; $processAttempt -le $maxProcessRetries; $processAttempt++) {
    $exitCode = 0
    $wrapperScript = $null  # Initialize before try block

    $attemptArgs = $extraCliArgs.Clone()
    if ($processAttempt -gt 1 -and $attemptArgs -notcontains "--continue") {
        $attemptArgs += "--continue"
    }

    $argsLine = ($attemptArgs | ForEach-Object {
            if ($_ -match '[\s"]') { "'$($_ -replace "'", "'\''")'" } else { $_ }
        }) -join ' '

    try {
        # Detect if running on Windows
        # NOTE: Cannot use $isWindows because PowerShell is case-insensitive and
        # $IsWindows is a read-only automatic variable. Using $runningOnWindows instead.
        $runningOnWindows = $PSVersionTable.PSVersion.Major -ge 6 -and $IsWindows
        $isUnix = $IsLinux -or $IsMacOS
        Write-Host "[Invoke-Agent] OS detection: runningOnWindows=$runningOnWindows, isUnix=$isUnix, PSVersion=$($PSVersionTable.PSVersion)"

        # Build paths with proper escaping for the target platform
        $safeOutput = $outputFile -replace "'", "'\''"
        $safePrompt = $promptFile -replace "'", "'\''"
        $safeCwd = if ($WorkingDir) { $WorkingDir -replace "'", "'\''" } else { "" }
        $safeRoomDir = $absRoomDir.Replace('\', '/').Replace("'", "'\''")
        $safeSkillsDir = $isolatedSkillsDir.Replace('\', '/').Replace("'", "'\''")
        $safeRole = $RoleName -replace "'", "'\''"

        $cwdLine = if ($safeCwd) { "cd '$safeCwd' 2>/dev/null || true" } else { "" }
        $safePidFile = $pidFile -replace "'", "'\''"
        $safeOstwinHome = $OstwinHome.Replace('\', '/').Replace("'", "'\''")
        $opencodeConfigLine = ""
        if ($tempMcpConfig) {
            $safeOpencodeConfig = $tempMcpConfig.Replace('\', '/').Replace("'", "'\''")
            $opencodeConfigLine = "export OPENCODE_CONFIG='$safeOpencodeConfig'"
        }

        # Ensure critical env vars for MCP server resolution are exported
        # These are required for {env:AGENT_DIR} and {env:OSTWIN_PYTHON} placeholders
        # Use platform-specific venv Python path
        $venvPythonUnix = Join-Path $OstwinHome ".venv" "bin" "python"
        $venvPythonWin = Join-Path $OstwinHome ".venv" "Scripts" "python.exe"
        $envExportLines = @"
export AGENT_DIR='$safeOstwinHome'
export OSTWIN_PYTHON='$venvPythonUnix'
"@

        # Log diagnostic info before exec
        Write-Host "[Invoke-Agent] Launching: CMD=$AgentCmd, PromptFile=$promptFile, ArgsLine=$argsLine"
        Write-Host "[Invoke-Agent] About to enter if (runningOnWindows=$runningOnWindows) branch..."

        if ($runningOnWindows) {
            Write-Host "[Invoke-Agent] Taking Windows branch..."
            # Windows: Use PowerShell wrapper instead of bash
            $winPidFile = $pidFile.Replace('/', '\')
            $winOutput = $outputFile.Replace('/', '\')
            $winPrompt = $promptFile.Replace('/', '\')
            $winSkillsDir = $isolatedSkillsDir.Replace('/', '\')
            $winOstwinHome = $OstwinHome.Replace('/', '\')
            $winOpencodeConfig = if ($tempMcpConfig) { $tempMcpConfig.Replace('/', '\') } else { "" }

            # Tokenize AgentCmd and args for PowerShell execution
            # $AgentCmd may be "opencode run", "'/path/to/agent'", or "/path/to/mock.ps1"
            $cmdParts = $AgentCmd.Trim("'").Trim('"').Split(' ', [StringSplitOptions]::RemoveEmptyEntries)
            $exe = $cmdParts[0]
            $cmdArgs = if ($cmdParts.Length -gt 1) { $cmdParts[1..($cmdParts.Length - 1)] } else { @() }

            # If the command is a .ps1 script (possibly wrapped in "pwsh -NoProfile -File script.ps1"),
            # extract the script path and run it directly via call operator in the wrapper.
            # This avoids nested pwsh invocations with broken argument passing.
            if ($exe -match '\.ps1$') {
                # exe is already the .ps1 file — cmdArgs are its parameters
                $allArgs = $cmdArgs + $extraCliArgs
            } elseif ($exe -eq 'pwsh' -or $exe -eq 'powershell') {
                # Look for -File flag and extract the script path
                $fileIdx = [Array]::FindIndex($cmdArgs, [Predicate[object]]{ param($a) $a -eq '-File' })
                if ($fileIdx -ge 0 -and ($fileIdx + 1) -lt $cmdArgs.Length) {
                    $exe = $cmdArgs[$fileIdx + 1].Trim('"').Trim("'")
                    # Drop -NoProfile, -File, and the script path from cmdArgs; keep the rest
                    $remaining = @()
                    for ($i = 0; $i -lt $cmdArgs.Length; $i++) {
                        if ($i -eq $fileIdx -or $i -eq ($fileIdx + 1)) { continue }
                        if ($cmdArgs[$i] -eq '-NoProfile' -or $cmdArgs[$i] -eq '-ExecutionPolicy' -or
                            ($i -gt 0 -and $cmdArgs[$i - 1] -eq '-ExecutionPolicy')) { continue }
                        $remaining += $cmdArgs[$i]
                    }
                    $allArgs = $remaining + $extraCliArgs
                } else {
                    $allArgs = $cmdArgs + $extraCliArgs
                }
            } else {
                $allArgs = $cmdArgs + $extraCliArgs
            }

            # Serialize args array into the wrapper script as a PowerShell array literal
            # Each arg must be properly escaped for PowerShell string handling
            $escapedArgs = $allArgs | ForEach-Object {
                $arg = $_
                # Escape single quotes by doubling them, then wrap in single quotes
                "'" + ($arg -replace "'", "''") + "'"
            }
            $argsArrayLiteral = "@(" + ($escapedArgs -join ',') + ")"

            $psWrapperScript = Join-Path $artifactsDir "run-agent.ps1"
            $psScriptContent = @"
`$env:AGENT_OS_ROOM_DIR = '$safeRoomDir'
`$env:AGENT_OS_ROLE = '$safeRole'
`$env:AGENT_OS_PARENT_PID = $PID
`$env:AGENT_OS_SKILLS_DIR = '$winSkillsDir'
`$env:AGENT_OS_PID_FILE = '$winPidFile'
`$env:OSTWIN_HOME = '$winOstwinHome'
`$env:AGENT_DIR = '$winOstwinHome'
`$env:OSTWIN_PYTHON = '$venvPythonWin'
if ('$winOpencodeConfig') { `$env:OPENCODE_CONFIG = '$winOpencodeConfig' }

# Source user-controlled pre-exec hook
`$envSh = Join-Path `$env:USERPROFILE '.ostwin' '.env.sh'
if (Test-Path `$envSh) { . `$envSh }

# Write PID
`$PID | Out-File -FilePath '$winPidFile' -Encoding ascii -NoNewline

# Log diagnostics
`$cmdArgs = $argsArrayLiteral
"[$wrapper] PID=`$PID, CMD=$exe, ARGS=`$(`$cmdArgs -join ' ')" | Out-File -FilePath '$winOutput' -Encoding utf8 -Append

# Execute using call operator with array
& '$exe' @cmdArgs 2>&1 | Out-File -FilePath '$winOutput' -Encoding utf8 -Append
"@
            $psScriptContent | Out-File -FilePath $psWrapperScript -Encoding utf8 -Force

            # Launch PowerShell wrapper
            $psi = [System.Diagnostics.ProcessStartInfo]::new()
            # Resolve absolute path for shell executable to avoid PATH issues
            $pwshPath = (Get-Command pwsh -ErrorAction SilentlyContinue).Source
            if ($pwshPath) {
                $psi.FileName = $pwshPath
            } else {
                $psPath = (Get-Command powershell -ErrorAction SilentlyContinue).Source
                if ($psPath) {
                    $psi.FileName = $psPath
                } else {
                    # Fallback to default paths
                    $psi.FileName = if ($runningOnWindows) { "powershell.exe" } else { "pwsh" }
                }
            }
            $psi.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$psWrapperScript`""
            $psi.UseShellExecute = $false
            $psi.RedirectStandardInput = $true
            $psi.CreateNoWindow = $true
            $proc = [System.Diagnostics.Process]::Start($psi)
            $proc.StandardInput.Close()

            $wrapperScript = $psWrapperScript
            Write-Host "[Invoke-Agent] Windows branch: wrapperScript=$wrapperScript"
        }
        else {
            Write-Host "[Invoke-Agent] Taking Unix/Mac branch..."
            # Unix: Use bash wrapper (existing logic)
            $wrapperScript = Join-Path $artifactsDir "run-agent.sh"
            Write-Host "[Invoke-Agent] Unix branch: wrapperScript=$wrapperScript"
            $scriptContent = @"
#!/bin/bash
export AGENT_OS_ROOM_DIR='$safeRoomDir'
export AGENT_OS_ROLE='$safeRole'
export AGENT_OS_PARENT_PID='$PID'
export AGENT_OS_SKILLS_DIR='$safeSkillsDir'
export AGENT_OS_PID_FILE='$safePidFile'
export OSTWIN_HOME='$safeOstwinHome'
$opencodeConfigLine
$envExportLines
# Static vars belong in `$safeOstwinHome`/.env; this file is for shell logic.
if [ -f "`$HOME/.ostwin/.env.sh" ]; then . "`$HOME/.ostwin/.env.sh"; fi
if [ -f '$safeOstwinHome/.env.sh' ]; then . '$safeOstwinHome/.env.sh'; fi
$cwdLine
# Write PID before exec — `$`$ survives exec, so this is the real agent PID.
# bin/agent also writes this (harmless overwrite); this fallback ensures
# non-bin/agent commands (opencode run, custom CLIs) still get tracked.
echo "`$$" > '$safePidFile'
# Log diagnostic info before exec
echo "[wrapper] PID=`$$, CMD=$AgentCmd, CWD=`$(pwd)" >> '$safeOutput'
echo "[wrapper] PROMPT_FILE='$safePrompt' (exists: `$(test -f '$safePrompt' && echo yes || echo no), size: `$(wc -c < '$safePrompt' 2>/dev/null || echo 0) bytes)" >> '$safeOutput'
echo "[wrapper] EXEC: $AgentCmd $argsLine" >> '$safeOutput'
exec $AgentCmd $argsLine >> '$safeOutput' 2>&1
# If exec fails, this line runs:
echo "[wrapper] EXEC FAILED: exit=`$?" >> '$safeOutput'
"@
            $scriptContent | Out-File -FilePath $wrapperScript -Encoding utf8 -NoNewline -Force
            chmod +x $wrapperScript 2>$null

            # --- Launch bash via System.Diagnostics.Process ---
            # Start-Process -NoNewWindow is unreliable inside Start-Job on macOS
            # (no console to attach to in headless runspace). Direct Process API works.
            $psi = [System.Diagnostics.ProcessStartInfo]::new()
            # Resolve absolute path for bash to avoid PATH issues in headless processes
            $bashPath = (Get-Command bash -ErrorAction SilentlyContinue).Source
            if ($bashPath) {
                $psi.FileName = $bashPath
            } else {
                # Fallback to standard default
                $psi.FileName = "/bin/bash"
            }
            $psi.Arguments = "`"$wrapperScript`""
            $psi.UseShellExecute = $false
            $psi.RedirectStandardInput = $true
            $psi.CreateNoWindow = $true
            $proc = [System.Diagnostics.Process]::Start($psi)
            $proc.StandardInput.Close()  # equivalent to /dev/null stdin
        }

        Write-Host "[Invoke-Agent] After if/else: wrapperScript='$wrapperScript'" -ForegroundColor Cyan
        Write-Warning "[Invoke-Agent] bash launched as PID $($proc.Id), HasExited=$($proc.HasExited), wrapper=$wrapperScript"

        # --- Wait for agent to self-register its PID (max 15s) ---
        # The wrapper writes $$ to the PID file before exec, and bin/agent
        # also writes it. We poll until we see a valid, alive PID.
        $pidConfirmTimeout = 15
        $pidConfirmStart = [int][double]::Parse((Get-Date -UFormat %s))
        $confirmedPid = $null
        while (([int][double]::Parse((Get-Date -UFormat %s)) - $pidConfirmStart) -lt $pidConfirmTimeout) {
            if ($proc.HasExited) {
                # Process already done — do one final PID file read before giving up.
                # The wrapper writes PID before exec, so the file may exist even if
                # the process exited quickly (fast completion or exec failure).
                if (Test-Path $pidFile) {
                    $pidContent = (Get-Content $pidFile -Raw -ErrorAction SilentlyContinue)
                    if ($pidContent -and ($pidContent.Trim() -match '^\d+$')) {
                        $confirmedPid = [int]$pidContent.Trim()
                    }
                }
                break
            }
            if (Test-Path $pidFile) {
                $pidContent = (Get-Content $pidFile -Raw -ErrorAction SilentlyContinue)
                if ($pidContent -and ($pidContent.Trim() -match '^\d+$')) {
                    $candidatePid = [int]$pidContent.Trim()
                    # Verify it's actually alive and not our own PowerShell PID
                    if ($candidatePid -ne $PID) {
                        try {
                            $p = Get-Process -Id $candidatePid -ErrorAction Stop
                            if ($p) { $confirmedPid = $candidatePid; break }
                        }
                        catch { }
                    }
                }
            }
            Start-Sleep -Milliseconds 500
        }

        if (-not $confirmedPid -and -not $proc.HasExited) {
            Write-Warning "[Invoke-Agent] PID confirmation timed out after ${pidConfirmTimeout}s for '$RoleName'. Falling back to proc.Id ($($proc.Id)). Agent may not be tracked correctly."
        }
        Write-Warning "[Invoke-Agent] PID confirmation result: confirmedPid=$confirmedPid procId=$($proc.Id) procHasExited=$($proc.HasExited)"

        $finished = $proc.WaitForExit($TimeoutSeconds * 1000)
        if (-not $proc.HasExited) {
            # Timeout — kill the confirmed agent PID if available, else fall back to proc.Id
            $killPid = if ($confirmedPid) { $confirmedPid } else { $proc.Id }
            Stop-Process -Id $killPid -Force -ErrorAction SilentlyContinue
            # Also kill proc.Id in case they differ (belt-and-suspenders)
            if ($confirmedPid -and $confirmedPid -ne $proc.Id) {
                Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
            }
            # Wait for process to fully exit so file handles are released
            # (Windows doesn't release locks immediately after Stop-Process)
            try { $proc.WaitForExit(3000) } catch {}
            $exitCode = 124
            try {
                "Agent timed out after ${TimeoutSeconds}s" | Out-File -FilePath $outputFile -Encoding utf8 -Append
            } catch {
                Write-Warning "[Invoke-Agent] Could not write timeout message to output file: $_"
            }
        }
        else {
            $exitCode = $proc.ExitCode
        }

        # --- Diagnostic: log output on failure ---
        if ($exitCode -ne 0 -and (Test-Path $outputFile)) {
            $firstLines = Get-Content $outputFile -TotalCount 5 -ErrorAction SilentlyContinue
            if ($firstLines) {
                Write-Warning "[Invoke-Agent] Agent exited with code $exitCode. First output lines: $($firstLines -join ' | ')"
            }
        }
    }
    catch {
        $exitCode = 1
        $errorMsg = $_.Exception.Message
        $errorType = $_.Exception.GetType().FullName
        $stackTrace = $_.ScriptStackTrace
        Write-Host "[Invoke-Agent] ERROR in try block (attempt $processAttempt): $errorType" -ForegroundColor Red
        Write-Host "[Invoke-Agent] Message: $errorMsg" -ForegroundColor Red
        Write-Host "[Invoke-Agent] StackTrace:`n$stackTrace" -ForegroundColor Red
        Write-Host "[Invoke-Agent] wrapperScript at catch: '$wrapperScript'" -ForegroundColor Yellow
        Write-Host "[Invoke-Agent] runningOnWindows: $runningOnWindows" -ForegroundColor Yellow
        Write-Host "[Invoke-Agent] artifactsDir: $artifactsDir" -ForegroundColor Yellow
        "$errorType : $errorMsg`nStackTrace:`n$stackTrace" | Out-File -FilePath $outputFile -Encoding utf8
    }

    # --- Retry on transient remote errors (ClosedResourceError, RemoteException) ---
    if ($exitCode -ne 0 -and $exitCode -ne 124 -and $processAttempt -lt $maxProcessRetries) {
        $agentOutput = if (Test-Path $outputFile) { Get-Content $outputFile -Raw -ErrorAction SilentlyContinue } else { "" }
        if ($agentOutput -match "ClosedResourceError|RemoteException.*ClosedResource|ReadError|WriteError") {
            $backoff = [math]::Pow(2, $processAttempt)
            Write-Host "[Invoke-Agent] Transient remote error on attempt $processAttempt/$maxProcessRetries, retrying in ${backoff}s..."
            Start-Sleep -Seconds $backoff
            continue
        }
    }
    break  # Success or non-transient error — stop retrying
}

# --- Read output ---
$output = if (Test-Path $outputFile) {
    Get-Content $outputFile -Raw -ErrorAction SilentlyContinue
}
else { "No output captured" }

# --- Clean up temp files (OPT-003: prevent accumulation on retries) ---
Remove-Item $wrapperScript -Force -ErrorAction SilentlyContinue
Remove-Item $promptFile -Force -ErrorAction SilentlyContinue
# Note: opencode.json is no longer generated by Invoke-Agent.
# Pre-compiled .opencode/opencode.json (from ostwin init/compile) is used directly.

# Note: PID file is NOT removed here. The caller (Start-Engineer/Start-QA)
# must clean it up after posting the channel message, to avoid race conditions
# with the manager's deadlock detection.

# --- Return result ---
[PSCustomObject]@{
    ExitCode   = $exitCode
    Output     = $output
    OutputFile = $outputFile
    PidFile    = $pidFile
    RoleName   = $RoleName
    TimedOut   = ($exitCode -eq 124)
}
