# ──────────────────────────────────────────────────────────────────────────────
# Setup-Env.ps1 — .env file creation, API key prompting, .env.ps1 hook
#
# Provides: Setup-Env
#
# Requires: Lib.ps1, Detect-OS.ps1, globals: $script:InstallDir, $script:AutoYes
# ──────────────────────────────────────────────────────────────────────────────

if ($script:_SetupEnvPs1Loaded) { return }
$script:_SetupEnvPs1Loaded = $true

function Setup-Env {
    [CmdletBinding()]
    param()

    $envFile = Join-Path $script:InstallDir ".env"

    if (Test-Path $envFile) {
        Write-Ok ".env already exists at $envFile"
        return
    }

    Write-Step "Creating .env file at $envFile..."
    if (-not (Test-Path $script:InstallDir)) {
        New-Item -ItemType Directory -Path $script:InstallDir -Force | Out-Null
    }

    # Generate a secure API key for dashboard auth
    $randomBytes = New-Object byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($randomBytes)
    $generatedApiKey = "ostwin_" + [Convert]::ToBase64String($randomBytes).Replace("/", "").Replace("+", "").Replace("=", "").Substring(0, 32)

    $envContent = @"
# Ostwin — Environment Variables
# Edit this file and re-start the dashboard (ostwin stop && ostwin start)
# Lines starting with # are comments.

# ── AI Provider Keys (set at least one) ────────────────────────────────────
# GOOGLE_API_KEY=your-google-api-key-here
# OPENAI_API_KEY=your-openai-api-key-here
# ANTHROPIC_API_KEY=your-anthropic-api-key-here
# OPENROUTER_API_KEY=your-openrouter-api-key-here
# AZURE_OPENAI_API_KEY=your-azure-openai-api-key-here
# BASETEN_API_KEY=your-baseten-api-key-here
# AWS_ACCESS_KEY_ID=your-aws-access-key-id-here
# AWS_SECRET_ACCESS_KEY=your-aws-secret-access-key-here
GOOGLE_GENAI_USE_VERTEXAI=True
# ── Dashboard settings ──────────────────────────────────────────────────────
# DASHBOARD_PORT=3366
# DASHBOARD_HOST=0.0.0.0

# ── Dashboard Authentication ────────────────────────────────────────────────
# API key for CLI ↔ Dashboard communication. Auto-generated on first install.
OSTWIN_API_KEY=$generatedApiKey

# ── ngrok Tunnel (auto-starts when NGROK_AUTHTOKEN is set) ─────────────────
# NGROK_AUTHTOKEN=
# NGROK_DOMAIN=              # Optional: custom/static domain (paid ngrok plans)

# ── Agent OS settings ───────────────────────────────────────────────────────
# OSTWIN_LOG_LEVEL=INFO

# ── Agentic Memory Platform ────────────────────────────────────────────────
# Processing LLM — the model that analyses, summarises, and evolves memories.
# Backend: huggingface | gemini | openai | ollama | openrouter | sglang
MEMORY_LLM_BACKEND=huggingface
MEMORY_LLM_MODEL=LiquidAI/LFM2-1.2B-Extract

# Embedding — converts text into vectors for similarity search.
# Backend: ollama | gemini | google-vertex | openai-compatible
MEMORY_EMBEDDING_BACKEND=ollama
MEMORY_EMBEDDING_MODEL=leoipulsar/harrier-0.6b

# Vector store: zvec (recommended) | chroma
MEMORY_VECTOR_BACKEND=zvec

# Behaviour
MEMORY_CONTEXT_AWARE=true
MEMORY_AUTO_SYNC=true
MEMORY_AUTO_SYNC_INTERVAL=60

# ── Gemini override ────────────────────────────────────────────────────────
# To use Gemini for memory instead of local HuggingFace, uncomment below
# (requires GOOGLE_API_KEY to be set above):
# MEMORY_LLM_BACKEND=gemini
# MEMORY_LLM_MODEL=gemini-3-flash-preview
# MEMORY_EMBEDDING_BACKEND=gemini
# MEMORY_EMBEDDING_MODEL=gemini-embedding-001
"@

    Set-Content -Path $envFile -Value $envContent -Encoding UTF8

    Write-Ok ".env created — edit $envFile to add your API keys"

    # Create .env.ps1 hook for dynamic env logic
    Create-EnvPs1Hook

    # Migrate any existing environment variables
    Migrate-EnvKeys -EnvFile $envFile

    # Prompt for ngrok tunnel token (optional)
    if (-not $script:AutoYes -and -not $env:NGROK_AUTHTOKEN) {
        Write-Host ""
        Write-Host -NoNewline "    → Enter NGROK_AUTHTOKEN for dashboard port-forwarding (or press Enter to skip): " -ForegroundColor Cyan
        $ngrokToken = Read-Host
        if ($ngrokToken) {
            # Ensure ngrok is installed before saving the token
            Install-Ngrok

            $content = Get-Content $envFile -Raw
            $content = $content -replace '^# NGROK_AUTHTOKEN=.*', "NGROK_AUTHTOKEN=$ngrokToken"
            Set-Content -Path $envFile -Value $content -Encoding UTF8
            Write-Ok "Saved NGROK_AUTHTOKEN — tunnel will auto-start with dashboard"
        }
    }
}

# ─── Internal helpers ────────────────────────────────────────────────────────

function Create-EnvPs1Hook {
    [CmdletBinding()]
    param()

    $envPs1 = Join-Path $script:InstallDir ".env.ps1"
    if (-not (Test-Path $envPs1)) {
        $hookContent = @'
# Ostwin — dynamic environment hook (Windows)
# Sourced by generated agent wrappers before the agent execs.
# Use this for env vars that require shell logic (subshells, conditionals,
# token refresh, etc.). Static KEY=VALUE pairs belong in ~/.ostwin/.env.

# Refresh a Vertex AI access token from the active gcloud account.
if (Get-Command gcloud -ErrorAction SilentlyContinue) {
    $env:VERTEX_API_KEY = (& gcloud auth print-access-token 2>$null)
}

# Auto-promote memory backend to Gemini when a Google API key is available
# and the user hasn't explicitly overridden the LLM backend.
if ($env:GOOGLE_API_KEY -and ($env:MEMORY_LLM_BACKEND -eq 'huggingface' -or -not $env:MEMORY_LLM_BACKEND)) {
    $env:MEMORY_LLM_BACKEND = 'gemini'
    if (-not $env:MEMORY_LLM_MODEL) { $env:MEMORY_LLM_MODEL = 'gemini-3-flash-preview' }
    $env:MEMORY_EMBEDDING_BACKEND = 'gemini'
    if (-not $env:MEMORY_EMBEDDING_MODEL) { $env:MEMORY_EMBEDDING_MODEL = 'gemini-embedding-001' }
}
'@
        Set-Content -Path $envPs1 -Value $hookContent -Encoding UTF8
        Write-Ok ".env.ps1 created — add dynamic env hooks (e.g. token refresh) here"
    }
}

function Migrate-EnvKeys {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$EnvFile)

    $migrated = $false
    $content = Get-Content $EnvFile -Raw

    $keysToMigrate = @(
        'GOOGLE_API_KEY', 'OPENAI_API_KEY', 'ANTHROPIC_API_KEY',
        'OPENROUTER_API_KEY', 'AZURE_OPENAI_API_KEY', 'BASETEN_API_KEY',
        'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'NGROK_AUTHTOKEN'
    )

    foreach ($key in $keysToMigrate) {
        $envValue = [System.Environment]::GetEnvironmentVariable($key)
        if ($envValue) {
            $content = $content -replace "(?m)^# ${key}=.*$", "${key}=$envValue"
            Write-Ok "Migrated `$$key into .env"
            $migrated = $true
        }
    }

    if ($migrated) {
        Set-Content -Path $EnvFile -Value $content -Encoding UTF8
    }
    else {
        Write-Warn "No API keys found in current environment."
        if (-not $script:AutoYes) {
            Write-Host "    Which AI Provider would you like to configure now?" -ForegroundColor Cyan
            Write-Host "      1) Google (Gemini)     5) Azure OpenAI"
            Write-Host "      2) OpenAI              6) Baseten"
            Write-Host "      3) Anthropic           7) AWS Bedrock"
            Write-Host "      4) OpenRouter"
            Write-Host "      0) Skip for now"
            Write-Host -NoNewline "    ? Select an option [0-7]: " -ForegroundColor Yellow
            $choice = Read-Host

            $selectedKeys = @()
            switch ($choice) {
                "1" { $selectedKeys = @("GOOGLE_API_KEY") }
                "2" { $selectedKeys = @("OPENAI_API_KEY") }
                "3" { $selectedKeys = @("ANTHROPIC_API_KEY") }
                "4" { $selectedKeys = @("OPENROUTER_API_KEY") }
                "5" { $selectedKeys = @("AZURE_OPENAI_API_KEY") }
                "6" { $selectedKeys = @("BASETEN_API_KEY") }
                "7" { $selectedKeys = @("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY") }
                default { Write-Info "Skipped API key setup. Please edit $EnvFile later." }
            }

            foreach ($keyName in $selectedKeys) {
                Write-Host -NoNewline "    → Enter ${keyName}: " -ForegroundColor Cyan
                $userVal = Read-Host -AsSecureString
                $plainVal = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
                    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($userVal)
                )
                if ($plainVal) {
                    $content = $content -replace "(?m)^# ${keyName}=.*$", "${keyName}=$plainVal"
                    Set-Content -Path $EnvFile -Value $content -Encoding UTF8
                    Write-Ok "Saved $keyName into .env"
                }
            }
        }
        else {
            Write-Info "Non-interactive mode (-Yes). Edit $EnvFile later to add your API keys."
        }
    }
}
