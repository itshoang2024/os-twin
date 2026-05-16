<#
.SYNOPSIS
    Analyzes a task description and returns recommended role, capabilities, and pipeline.
 
.PARAMETER TaskDescription
    The full task/epic description text.
.PARAMETER AgentsDir
    Path to the .agents directory.
.PARAMETER UseLLM
    If true, uses an LLM call for analysis. Otherwise uses fast keyword heuristics.
 
.OUTPUTS
    PSCustomObject: SuggestedRole, RequiredCapabilities, SuggestedPipeline, Confidence
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$TaskDescription,
 
    [string]$AgentsDir = '',
 
    [switch]$UseLLM
)
 
if (-not $AgentsDir) {
    $AgentsDir = (Resolve-Path (Join-Path $PSScriptRoot ".." "..")).Path
}
 
$result = [PSCustomObject]@{
    SuggestedRole        = 'engineer'
    RequiredCapabilities = @()
    SuggestedPipeline    = @()
    Confidence           = 0.5
}
 
$desc = $TaskDescription.ToLower()
 
# --- Keyword-to-Capability mapping ---
$capabilityKeywords = @{
    'security' = @(
        'security', 'owasp', 'cve', 'vulnerability', 'xss', 'csrf', 'injection',
        'authentication', 'authorization', 'auth', 'jwt', 'oauth', 'encrypt', 'encryption',
        'secrets', 'penetration', 'pentest', 'firewall', 'ssl', 'tls', 'cors'
    )
    'database' = @(
        'database', 'schema', 'migration', 'sql', 'query', 'index', 'postgres', 'postgresql',
        'mysql', 'sqlite', 'mongodb', 'redis', 'orm', 'alembic', 'prisma',
        'deadlock', 'transaction', 'table', 'foreign key', 'normalization'
    )
    'infrastructure' = @(
        'docker', 'kubernetes', 'k8s', 'ci/cd', 'ci-cd', 'pipeline', 'deploy',
        'terraform', 'ansible', 'nginx', 'load balancer', 'scaling', 'monitoring',
        'grafana', 'prometheus', 'aws', 'gcp', 'azure', 'helm', 'container'
    )
    'architecture' = @(
        'architecture', 'system design', 'microservice', 'monolith', 'api design',
        'interface', 'contract', 'event-driven', 'message queue', 'grpc', 'graphql',
        'domain model', 'bounded context', 'cqrs', 'event sourcing'
    )
    'accessibility' = @(
        'accessibility', 'a11y', 'wcag', 'screen reader', 'aria', 'keyboard navigation',
        'color contrast', 'alt text', 'semantic html', 'focus management'
    )
    'frontend' = @(
        'react', 'vue', 'angular', 'svelte', 'css', 'tailwind', 'responsive',
        'component', 'ui', 'ux', 'dashboard', 'layout', 'animation', 'dom'
    )
    'backend' = @(
        'api', 'rest', 'endpoint', 'fastapi', 'express', 'django', 'flask',
        'middleware', 'route', 'controller', 'service layer', 'websocket'
    )
    'testing' = @(
        'test', 'cypress', 'jest', 'pytest', 'e2e', 'integration test', 'unit test',
        'coverage', 'tdd', 'bdd', 'playwright', 'selenium', 'mock', 'fixture'
    )
}
 
# --- Score each capability ---
$detectedCapabilities = @()
$capHits = @{}
$maxScore = 0

foreach ($cap in $capabilityKeywords.Keys) {
    $keywords = $capabilityKeywords[$cap]
    $hits = 0
    foreach ($kw in $keywords) {
        $matches = [regex]::Matches($desc, "\b$([regex]::Escape($kw))\b")
        $hits += $matches.Count
    }
    if ($hits -ge 1) {
        $detectedCapabilities += $cap
        $capHits[$cap] = $hits
        if ($hits -gt $maxScore) { $maxScore = $hits }
    }
}

$result.RequiredCapabilities = $detectedCapabilities

# --- Determine confidence ---
if ($detectedCapabilities.Count -gt 0) {
    $result.Confidence = [Math]::Min(0.9, 0.5 + ($detectedCapabilities.Count * 0.1))
}

# --- Suggest primary role based on dominant capability ---
$roleMapping = @{
    'security'       = 'security-engineer'
    'database'       = 'database-architect'
    'infrastructure' = 'devops-engineer'
    'architecture'   = 'architect'
    'accessibility'  = 'accessibility-specialist'
    'frontend'       = 'engineer:fe'
    'backend'        = 'engineer:be'
    'testing'        = 'test-engineer'
}

if ($detectedCapabilities.Count -gt 0) {
    # Pick the role for the most-matched capability
    $primaryCap = $detectedCapabilities | Sort-Object { $capHits[$_] } -Descending | Select-Object -First 1
    if ($roleMapping.ContainsKey($primaryCap)) {
        $result.SuggestedRole = $roleMapping[$primaryCap]
    }
}
 
# --- Suggest pipeline ---
$pipelineStages = @($result.SuggestedRole)
foreach ($cap in $detectedCapabilities) {
    if ($cap -in @('security', 'database', 'architecture', 'infrastructure', 'accessibility')) {
        $reviewRole = $roleMapping[$cap]
        if ($reviewRole -ne $result.SuggestedRole) {
            $pipelineStages += $reviewRole
        }
    }
}
$result.SuggestedPipeline = $pipelineStages
 
Write-Output $result
