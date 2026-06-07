# Common Dependency Issues & Fixes

## Node.js / JavaScript

### Peer Dependency Conflicts

**Symptoms:**
```
npm ERR! peer dep missing: react@^17.0.0, required by some-package@1.0.0
npm ERR! peer dep missing: @types/react@^17.0.0
```

**Quick Fix:**
```bash
npm install --legacy-peer-deps
```

**Proper Fix:**
1. Check which package requires the peer dependency
2. Either upgrade/downgrade the conflicting package
3. Or install the missing peer dependency explicitly

```bash
npm ls <conflicting-package>
npm install <missing-peer>@<version>
```

### Module Not Found

**Symptoms:**
```
Error: Cannot find module 'some-package'
```

**Fixes:**
```bash
# 1. Reinstall
rm -rf node_modules package-lock.json
npm install

# 2. Check if it's a dev dependency used in production
npm install <package> --save

# 3. Check case sensitivity (especially on macOS/Windows)
ls node_modules | grep -i <package>
```

### Native Module Build Failures

**Symptoms:**
```
gyp ERR! stack Error: `make` failed with exit code: 2
node-pre-gyp ERR! build error
```

**Fixes:**
```bash
# 1. Ensure build tools installed
xcode-select --install  # macOS
# or
sudo apt-get install build-essential python3  # Linux

# 2. Rebuild native modules
npm rebuild

# 3. Use prebuilt binaries
npm install <package> --build-from-source=false
```

### Version Mismatch

**Symptoms:**
```
error <package>@2.0.0: The engine "node" is incompatible with this module.
```

**Fixes:**
```bash
# Check required version
cat .nvmrc  # or .node-version

# Switch Node version
nvm install <version>
nvm use <version>

# Or update package.json engines
# "engines": { "node": ">=18.0.0" }
```

### ESM vs CommonJS Issues

**Symptoms:**
```
Warning: To load an ES module, set "type": "module" in the package.json
SyntaxError: Cannot use import statement outside a module
```

**Fixes:**
```json
// package.json
{
  "type": "module"
}
```

Or use `.mjs` / `.cjs` extensions explicitly.

---

## Python

### Version Conflicts

**Symptoms:**
```
ERROR: pip's dependency resolver does not currently take into account all the packages that are installed.
ERROR: Cannot install package-a and package-b because these package versions have conflicting dependencies.
```

**Fixes:**
```bash
# 1. Use a fresh virtual environment
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Check for conflicts
pip check

# 3. Pin versions explicitly
pip freeze > requirements.txt
```

### Missing System Dependencies

**Symptoms:**
```
fatal error: 'libssl/ssl.h' file not found
error: command 'gcc' failed with exit status 1
```

**Fixes:**
```bash
# macOS
brew install openssl

# Ubuntu/Debian
sudo apt-get install libssl-dev python3-dev

# Then reinstall
pip install --no-cache-dir <package>
```

### Import Errors After Install

**Symptoms:**
```
ModuleNotFoundError: No module named 'package'
```

**Fixes:**
```bash
# 1. Verify correct Python/venv
which python
python -c "import sys; print(sys.path)"

# 2. Reinstall
pip uninstall <package>
pip install <package>

# 3. Check if editable install broken
pip install -e .
```

---

## Rust

### Multiple Versions of Same Crate

**Symptoms:**
```
error: multiple versions for dependency `serde`
```

**Fixes:**
```bash
# 1. Check duplicate versions
cargo tree --duplicates

# 2. Update to resolve
cargo update

# 3. Pin specific version in Cargo.toml
[dependencies]
serde = "=1.0.150"  # Exact version
```

### Link Errors

**Symptoms:**
```
error: linking with `cc` failed: exit code: 1
note: ld: library not found for -l<lib>
```

**Fixes:**
```bash
# macOS
brew install <lib>

# Linux
sudo apt-get install lib<lib>-dev

# Or use vendored feature if available
# Cargo.toml
# [dependencies]
# openssl = { version = "0.10", features = ["vendored"] }
```

---

## Go

### Module Version Mismatches

**Symptoms:**
```
go: module github.com/foo/bar: version "v1.0.0" invalid
```

**Fixes:**
```bash
# 1. Clean and re-download
go clean -modcache
go mod download

# 2. Update dependencies
go get -u ./...
go mod tidy

# 3. Verify
go mod verify
```

### Import Cycle

**Symptoms:**
```
import cycle not allowed
```

**Fix:** Requires code refactoring — create a shared package or use interfaces.

---

## .NET

### NuGet Version Conflicts

**Symptoms:**
```
Package 'Package.X' is incompatible with 'net6.0'
```

**Fixes:**
```bash
# 1. List outdated packages
dotnet list package --outdated

# 2. Update packages
dotnet add package <Package.Name>

# 3. Clean and restore
dotnet clean
rm -rf obj bin
dotnet restore
```

### Binding Redirects

**Symptoms:**
```
System.IO.FileLoadException: Could not load file or assembly
```

**Fixes:**
```xml
<!-- Add to app.config or web.config -->
<runtime>
  <assemblyBinding xmlns="urn:schemas-microsoft-com:asm.v1">
    <dependentAssembly>
      <assemblyIdentity name="SomeAssembly" publicKeyToken="..." />
      <bindingRedirect oldVersion="0.0.0.0-2.0.0.0" newVersion="2.0.0.0" />
    </dependentAssembly>
  </assemblyBinding>
</runtime>
```

---

## Environment-Specific Issues

### macOS

```bash
# If CLI tools missing
xcode-select --install

# If Homebrew packages not found
brew doctor
brew update && brew upgrade

# If OpenSSL issues
export LDFLAGS="-L$(brew --prefix openssl)/lib"
export CPPFLAGS="-I$(brew --prefix openssl)/include"
```

### Linux

```bash
# Common build dependencies
sudo apt-get update
sudo apt-get install -y build-essential python3-dev libffi-dev libssl-dev

# For Node.js native modules
sudo apt-get install -y nodejs-dev node-gyp
```

### Windows

```powershell
# Install build tools
npm install --global windows-build-tools

# For Python
# Use chocolatey or download from python.org
choco install python

# For Visual Studio Build Tools
# Download from visualstudio.microsoft.com
```

---

## Verification Commands

After applying fixes, always verify:

```bash
# Node.js
npm ci && npm run build && npm start -- --help  # Quick check

# Python
pip install -r requirements.txt && python -c "import <main_module>"

# Rust
cargo build && cargo run -- --help

# Go
go mod download && go build && ./<binary> --help

# .NET
dotnet restore && dotnet build && dotnet run -- --help
```
