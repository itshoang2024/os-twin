# ──────────────────────────────────────────────────────────────────────────────
# Setup-Env.Tests.ps1 — Tests for installer/Setup-Env.ps1
# ──────────────────────────────────────────────────────────────────────────────

BeforeAll {
    . "$PSScriptRoot/TestHelper.ps1"
    Import-InstallerModule -Modules @("Lib.ps1", "Setup-Env.ps1")
    . $script:_ImportedModuleScript
}

Describe "Setup-Env" {
    BeforeEach {
        $testDir = Join-Path $TestDrive "test-env-$(Get-Random)"
        New-Item -ItemType Directory -Path $testDir -Force | Out-Null
        $script:InstallDir = $testDir
        $script:AutoYes = $true
        $script:OS = "windows"
    }

    It "Should create .env file" {
        Setup-Env
        $envFile = Join-Path $testDir ".env"
        Test-Path $envFile | Should -Be $true
    }

    It "Should contain OSTWIN_API_KEY" {
        Setup-Env
        $envFile = Join-Path $testDir ".env"
        $content = Get-Content $envFile -Raw
        $content | Should -Match 'OSTWIN_API_KEY=ostwin_'
    }

    It "Should contain memory backend settings" {
        Setup-Env
        $envFile = Join-Path $testDir ".env"
        $content = Get-Content $envFile -Raw
        $content | Should -Match 'MEMORY_LLM_BACKEND=huggingface'
        $content | Should -Match 'MEMORY_EMBEDDING_BACKEND=ollama'
        $content | Should -Match 'MEMORY_VECTOR_BACKEND=zvec'
    }

    It "Should contain provider key placeholders" {
        # Temporarily clear any real API keys from the environment
        # so Migrate-EnvKeys doesn't replace the placeholders.
        $savedGoogle = $env:GOOGLE_API_KEY
        $savedOpenAI = $env:OPENAI_API_KEY
        $savedAnthropic = $env:ANTHROPIC_API_KEY
        $env:GOOGLE_API_KEY = $null
        $env:OPENAI_API_KEY = $null
        $env:ANTHROPIC_API_KEY = $null
        try {
            Setup-Env
            $envFile = Join-Path $testDir ".env"
            $content = Get-Content $envFile -Raw
            $content | Should -Match '# GOOGLE_API_KEY='
            $content | Should -Match '# OPENAI_API_KEY='
            $content | Should -Match '# ANTHROPIC_API_KEY='
        }
        finally {
            $env:GOOGLE_API_KEY = $savedGoogle
            $env:OPENAI_API_KEY = $savedOpenAI
            $env:ANTHROPIC_API_KEY = $savedAnthropic
        }
    }

    It "Should not overwrite existing .env" {
        $envFile = Join-Path $testDir ".env"
        Set-Content -Path $envFile -Value "EXISTING=true"
        Setup-Env
        $content = Get-Content $envFile -Raw
        $content | Should -Match "EXISTING=true"
    }

    It "Should generate unique API keys" {
        $testDir1 = Join-Path $TestDrive "env1-$(Get-Random)"
        $testDir2 = Join-Path $TestDrive "env2-$(Get-Random)"
        New-Item -ItemType Directory -Path $testDir1 -Force | Out-Null
        New-Item -ItemType Directory -Path $testDir2 -Force | Out-Null

        $script:InstallDir = $testDir1
        Setup-Env
        $env1 = Get-Content (Join-Path $testDir1 ".env") -Raw
        $key1 = if ($env1 -match 'OSTWIN_API_KEY=(ostwin_\w+)') { $Matches[1] }

        # Re-import to get fresh function (reload module for unique key generation)
        Import-InstallerModule -Modules @("Setup-Env.ps1")
        . $script:_ImportedModuleScript

        $script:InstallDir = $testDir2
        Setup-Env
        $env2 = Get-Content (Join-Path $testDir2 ".env") -Raw
        $key2 = if ($env2 -match 'OSTWIN_API_KEY=(ostwin_\w+)') { $Matches[1] }

        $key1 | Should -Not -Be $key2
    }
}

Describe "Create-EnvPs1Hook" {
    BeforeEach {
        $testDir = Join-Path $TestDrive "test-hook-$(Get-Random)"
        New-Item -ItemType Directory -Path $testDir -Force | Out-Null
        $script:InstallDir = $testDir
    }

    It "Should create .env.ps1 file" {
        Create-EnvPs1Hook
        $envPs1 = Join-Path $testDir ".env.ps1"
        Test-Path $envPs1 | Should -Be $true
    }

    It "Should contain Vertex API key refresh logic" {
        Create-EnvPs1Hook
        $envPs1 = Join-Path $testDir ".env.ps1"
        $content = Get-Content $envPs1 -Raw
        $content | Should -Match 'VERTEX_API_KEY'
    }

    It "Should contain Gemini auto-promote logic" {
        Create-EnvPs1Hook
        $envPs1 = Join-Path $testDir ".env.ps1"
        $content = Get-Content $envPs1 -Raw
        $content | Should -Match 'MEMORY_LLM_BACKEND'
    }

    It "Should not overwrite existing .env.ps1" {
        $envPs1 = Join-Path $testDir ".env.ps1"
        Set-Content -Path $envPs1 -Value "# existing hook"
        Create-EnvPs1Hook
        $content = Get-Content $envPs1 -Raw
        $content | Should -Match "# existing hook"
    }
}

Describe "Migrate-EnvKeys" {
    BeforeEach {
        $testDir = Join-Path $TestDrive "test-migrate-$(Get-Random)"
        New-Item -ItemType Directory -Path $testDir -Force | Out-Null
        $script:InstallDir = $testDir
        $script:AutoYes = $true
        $script:OS = "windows"
    }

    It "Should migrate environment variables into .env" {
        $envFile = Join-Path $testDir ".env"
        Set-Content -Path $envFile -Value "# GOOGLE_API_KEY=your-key-here"

        # Set a test env var
        $env:GOOGLE_API_KEY = "test-key-123"
        try {
            Migrate-EnvKeys -EnvFile $envFile
            $content = Get-Content $envFile -Raw
            $content | Should -Match 'GOOGLE_API_KEY=test-key-123'
        }
        finally {
            Remove-Item Env:GOOGLE_API_KEY -ErrorAction SilentlyContinue
        }
    }
}
