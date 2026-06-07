#Requires -Version 7.0
# Agent OS — Configuration Module
#
# Import:
#   Import-Module "$PSScriptRoot/Config.psm1"
#
# Provides: config loading, validation, schema enforcement, run-config copy-on-write

function Resolve-OstwinConfigPath {
    <#
    .SYNOPSIS
        Resolves the path to the Agent OS config.json file.
    .DESCRIPTION
        Canonical config-file resolution logic. Checks, in order:
          1. Explicit $ConfigPath parameter
          2. AGENT_OS_CONFIG environment variable
          3. OSTWIN_CONFIG_PATH environment variable
          4. OSTWIN_PROJECT_DIR + /.agents/config.json
          5. AGENTS_DIR environment variable + /config.json
          6. OSTWIN_HOME/.agents/config.json (or ~/.ostwin/.agents/config.json)
          7. Relative to this module's parent directory
        Throws if the resolved path does not exist.
        This function is the SINGLE SOURCE OF TRUTH for config path resolution.
        Utils.psm1:Read-OstwinConfig should delegate here in a future refactor.
    .PARAMETER ConfigPath
        Optional explicit path. If provided and non-empty, used as-is.
    .OUTPUTS
        [string] — The resolved, validated path to config.json.
    #>
    [CmdletBinding()]
    [OutputType([string])]
    param(
        [string]$ConfigPath = ''
    )

    if (-not $ConfigPath) {
        $homeDir = if ($env:USERPROFILE) { $env:USERPROFILE }
                   elseif ($env:HOME) { $env:HOME }
                   else { $HOME }
        $ostwinHome = if ($env:OSTWIN_HOME) { $env:OSTWIN_HOME } else { Join-Path $homeDir ".ostwin" }
        $globalConfig = Join-Path (Join-Path $ostwinHome ".agents") "config.json"

        $ConfigPath = if ($env:AGENT_OS_CONFIG) { $env:AGENT_OS_CONFIG }
                      elseif ($env:OSTWIN_CONFIG_PATH) { $env:OSTWIN_CONFIG_PATH }
                      elseif ($env:OSTWIN_PROJECT_DIR) { Join-Path (Join-Path $env:OSTWIN_PROJECT_DIR ".agents") "config.json" }
                      elseif ($env:AGENTS_DIR) { Join-Path $env:AGENTS_DIR "config.json" }
                      elseif (Test-Path $globalConfig) { $globalConfig }
                      else {
                          $agentsDir = (Resolve-Path (Join-Path $PSScriptRoot "..") -ErrorAction SilentlyContinue).Path
                          Join-Path $agentsDir "config.json"
                      }
    }

    if (-not (Test-Path $ConfigPath)) {
        throw "Config file not found: $ConfigPath"
    }

    return $ConfigPath
}

function Get-OstwinConfig {
    <#
    .SYNOPSIS
        Loads and returns the full Agent OS configuration as a PSCustomObject.
    .PARAMETER ConfigPath
        Optional path to config.json. Defaults to AGENT_OS_CONFIG env var or .agents/config.json.
    #>
    [CmdletBinding()]
    param(
        [string]$ConfigPath = ''
    )

    $ConfigPath = Resolve-OstwinConfigPath -ConfigPath $ConfigPath
    $config = Get-Content $ConfigPath -Raw | ConvertFrom-Json
    return $config
}

function Get-OstwinManagerRuntimeSettings {
    <#
    .SYNOPSIS
        Resolves manager loop runtime settings with safe defaults.
    .DESCRIPTION
        Canonical manager settings live under the manager section, with
        runtime.* used only as a secondary source for the same canonical key
        names. This helper supplies safe defaults so the manager loop never
        crashes on missing values.
    .PARAMETER Config
        The full config object (from Get-OstwinConfig).
    .OUTPUTS
        PSCustomObject with normalized manager runtime settings.
    #>
    [CmdletBinding()]
    [OutputType([PSCustomObject])]
    param(
        [Parameter(Mandatory)]
        [PSCustomObject]$Config
    )

    $manager = if ($null -ne $Config.manager) { $Config.manager } else { $null }
    $runtime = if ($null -ne $Config.runtime) { $Config.runtime } else { $null }

    $pollInterval = if ($null -ne $manager -and $null -ne $manager.poll_interval_seconds) {
        $manager.poll_interval_seconds
    }
    elseif ($null -ne $runtime -and $null -ne $runtime.poll_interval_seconds) {
        $runtime.poll_interval_seconds
    }
    else {
        5
    }

    $maxConcurrentRooms = if ($null -ne $manager -and $null -ne $manager.max_concurrent_rooms) {
        $manager.max_concurrent_rooms
    }
    elseif ($null -ne $runtime -and $null -ne $runtime.max_concurrent_rooms) {
        $runtime.max_concurrent_rooms
    }
    else {
        10
    }

    $maxEngineerRetries = if ($null -ne $manager -and $null -ne $manager.max_engineer_retries) {
        $manager.max_engineer_retries
    }
    else {
        3
    }

    $stateTimeoutSeconds = if ($null -ne $manager -and $null -ne $manager.state_timeout_seconds) {
        $manager.state_timeout_seconds
    }
    else {
        900
    }

    $autoApproveTools = if ($null -ne $manager -and $null -ne $manager.auto_approve_tools) {
        [bool]$manager.auto_approve_tools
    }
    elseif ($null -ne $runtime -and $null -ne $runtime.auto_approve_tools) {
        [bool]$runtime.auto_approve_tools
    }
    else {
        $false
    }

    $dynamicPipelines = if ($null -ne $manager -and $null -ne $manager.dynamic_pipelines) {
        [bool]$manager.dynamic_pipelines
    }
    elseif ($null -ne $runtime -and $null -ne $runtime.dynamic_pipelines) {
        [bool]$runtime.dynamic_pipelines
    }
    else {
        $true
    }

    return [PSCustomObject]@{
        poll_interval_seconds = [int]$pollInterval
        max_concurrent_rooms  = [int]$maxConcurrentRooms
        max_engineer_retries  = [int]$maxEngineerRetries
        state_timeout_seconds = [int]$stateTimeoutSeconds
        auto_approve_tools    = $autoApproveTools
        dynamic_pipelines     = $dynamicPipelines
    }
}

function Test-OstwinConfig {
    <#
    .SYNOPSIS
        Validates a config object against required fields and returns validation results.
    .PARAMETER Config
        The config object (from Get-OstwinConfig).
    .OUTPUTS
        PSCustomObject with IsValid (bool) and Errors (string[]) properties.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [PSCustomObject]$Config
    )

    $errors = [System.Collections.Generic.List[string]]::new()

    # Required top-level fields
    if (-not $Config.version) { $errors.Add("Missing required field: version") }
    if (-not $Config.manager) { $errors.Add("Missing required section: manager") }
    if (-not $Config.engineer) { $errors.Add("Missing required section: engineer") }
    if (-not $Config.qa) { $errors.Add("Missing required section: qa") }
    if (-not $Config.channel) { $errors.Add("Missing required section: channel") }

    # Manager section
    if ($Config.manager) {
        if ($null -eq $Config.manager.poll_interval_seconds) {
            $errors.Add("Missing: manager.poll_interval_seconds")
        }
        elseif ($Config.manager.poll_interval_seconds -lt 1) {
            $errors.Add("manager.poll_interval_seconds must be >= 1")
        }

        if ($null -eq $Config.manager.max_concurrent_rooms) {
            $errors.Add("Missing: manager.max_concurrent_rooms")
        }
        elseif ($Config.manager.max_concurrent_rooms -lt 1) {
            $errors.Add("manager.max_concurrent_rooms must be >= 1")
        }

        if ($null -eq $Config.manager.max_engineer_retries) {
            $errors.Add("Missing: manager.max_engineer_retries")
        }

        if ($null -eq $Config.manager.auto_expand_plan) {
            # Provide a default value if missing
            $Config.manager | Add-Member -MemberType NoteProperty -Name "auto_expand_plan" -Value $false -Force
        }
    }

    # Engineer section
    if ($Config.engineer) {
        if (-not $Config.engineer.cli) { $errors.Add("Missing: engineer.cli") }
        if (-not $Config.engineer.default_model) { $errors.Add("Missing: engineer.default_model") }
        if ($null -eq $Config.engineer.timeout_seconds) { $errors.Add("Missing: engineer.timeout_seconds") }
    }

    # QA section
    if ($Config.qa) {
        if (-not $Config.qa.cli) { $errors.Add("Missing: qa.cli") }
        if ($null -eq $Config.qa.timeout_seconds) { $errors.Add("Missing: qa.timeout_seconds") }
    }

    # Channel section
    if ($Config.channel) {
        if (-not $Config.channel.format) { $errors.Add("Missing: channel.format") }
    }

    return [PSCustomObject]@{
        IsValid = ($errors.Count -eq 0)
        Errors  = $errors.ToArray()
    }
}

function New-RunConfig {
    <#
    .SYNOPSIS
        Creates a copy-on-write run config from the base config.json, applying overrides.
    .PARAMETER ConfigPath
        Path to the base config.json.
    .PARAMETER OutputPath
        Path to write the run config.
    .PARAMETER Overrides
        Hashtable of dot-separated key paths to new values.
    .EXAMPLE
        New-RunConfig -ConfigPath ".agents/config.json" -OutputPath ".agents/config.run.json" `
                      -Overrides @{ "manager.max_concurrent_rooms" = 10 }
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$ConfigPath,

        [Parameter(Mandatory)]
        [string]$OutputPath,

        [hashtable]$Overrides = @{}
    )

    if (-not (Test-Path $ConfigPath)) {
        throw "Base config not found: $ConfigPath"
    }

    $config = Get-Content $ConfigPath -Raw | ConvertFrom-Json

    # Apply overrides
    foreach ($key in $Overrides.Keys) {
        $parts = $key.Split('.')
        $current = $config

        for ($i = 0; $i -lt $parts.Count - 1; $i++) {
            $current = $current.($parts[$i])
            if ($null -eq $current) {
                throw "Override key path invalid: '$key' — '$($parts[$i])' not found"
            }
        }

        $lastKey = $parts[-1]
        $current | Add-Member -MemberType NoteProperty -Name $lastKey -Value $Overrides[$key] -Force
    }

    $config | ConvertTo-Json -Depth 10 | Out-File -FilePath $OutputPath -Encoding utf8

    return $OutputPath
}

Export-ModuleMember -Function Resolve-OstwinConfigPath, Get-OstwinConfig, Get-OstwinManagerRuntimeSettings, Test-OstwinConfig, New-RunConfig
