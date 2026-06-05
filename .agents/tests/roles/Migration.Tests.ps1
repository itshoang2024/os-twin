# EPIC-001 Skills Migration Tests

Describe "Registry Schema Migration" {
    BeforeAll {
        $script:agentsDir = (Resolve-Path (Join-Path (Resolve-Path "$PSScriptRoot/..").Path "..")).Path
        $script:rolesDir = Join-Path $script:agentsDir "roles"
        $script:registryFile = Join-Path $script:rolesDir "registry.json"
    }

    It "registry.json should exist" {
        Test-Path $script:registryFile | Should -Be $true
    }

    It "should contain legacy 'skills' string field for all available skills" {
        $registry = Get-Content $script:registryFile -Raw | ConvertFrom-Json
        $registry.skills.available | ForEach-Object {
            $_.skills | Should -Not -BeNullOrEmpty
            $_.skills | Should -BeOfType [string]
        }
    }
}

Describe "Role Definition Migration" {
    BeforeAll {
        $script:agentsDir = (Resolve-Path (Join-Path (Resolve-Path "$PSScriptRoot/..").Path "..")).Path
        $script:rolesDir = Join-Path $script:agentsDir "roles"
    }

    It "All roles should contain skill_refs property" {
        $roles = @("engineer", "qa", "architect")
        foreach ($roleName in $roles) {
            $roleFile = Join-Path $script:rolesDir $roleName "role.json"
            Write-Host "Checking '$roleFile'"
            $roleData = Get-Content $roleFile -Raw | ConvertFrom-Json
            # Check if property exists using PSObject
            $hasProp = $null -ne ($roleData.PSObject.Properties | Where-Object { $_.Name -eq "skill_refs" })
            if (-not $hasProp) {
                Write-Error "Role $roleName is missing skill_refs"
            }
            $hasProp | Should -Be $true
        }
    }

    It "Architect role should have specific skills" {
        $roleFile = Join-Path $script:rolesDir "architect" "role.json"
        $roleData = Get-Content $roleFile -Raw | ConvertFrom-Json
        $roleData.skill_refs | Should -Contain "create-architecture"
        $roleData.skill_refs | Should -Contain "create-lifecycle"
        $roleData.skill_refs | Should -Contain "create-role"
    }
}

Describe "SKILL.md Frontmatter Migration" {
    BeforeAll {
        $script:agentsDir = (Resolve-Path (Join-Path (Resolve-Path "$PSScriptRoot/..").Path "..")).Path
        $script:skillsDir = Join-Path $script:agentsDir "skills"
        $script:registryFile = Join-Path $script:agentsDir "roles" "registry.json"
    }

    It "All skills in registry should have structured frontmatter at specified paths" {
        $registry = Get-Content $script:registryFile -Raw | ConvertFrom-Json
        foreach ($skill in $registry.skills.available) {
            $skillName = $skill.name
            $skillPath = $skill.path
            $skillMd = Join-Path $script:agentsDir $skillPath
            Write-Host "Checking '$skillMd'"
            if (-not (Test-Path $skillMd)) {
                Write-Error "File not found: $skillMd (from registry path: $skillPath)"
                $false | Should -Be $true
            }
            $content = Get-Content $skillMd -Raw
            $content | Should -Match '(?s)^---\r?\n.*\r?\n---\r?\n'
        }
    }
}
