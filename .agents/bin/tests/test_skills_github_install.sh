#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# test_skills_github_install.sh
#
# Unit + integration tests for  `ostwin skills install <github-url>`
#
# Usage:
#   bash .agents/bin/tests/test_skills_github_install.sh
#
# The tests use a LOCAL bare git repo so they never hit the network.
# ──────────────────────────────────────────────────────────────────────────────
set -uo pipefail
# Note: -e is intentionally omitted — assertions and integration
# commands return non-zero codes that would kill the harness.

# ─── Harness ──────────────────────────────────────────────────────────────────

PASS=0; FAIL=0; SKIP=0
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

_pass() { PASS=$((PASS + 1)); }
_fail() { FAIL=$((FAIL + 1)); echo -e "  ${RED}FAIL${NC}: $1"; }

assert_eq()  { if [[ "$1" == "$2" ]]; then _pass; else _fail "expected '$2', got '$1'  ($3)"; fi; }
assert_neq() { if [[ "$1" != "$2" ]]; then _pass; else _fail "did not expect '$2'  ($3)"; fi; }
assert_ok()  { if [[ $1 -eq 0 ]]; then _pass; else _fail "expected exit 0, got $1  ($2)"; fi; }
assert_fail(){ if [[ $1 -ne 0 ]]; then _pass; else _fail "expected non-zero exit, got 0  ($2)"; fi; }
assert_file(){ if [[ -f "$1" ]]; then _pass; else _fail "file not found: $1  ($2)"; fi; }
assert_dir() { if [[ -d "$1" ]]; then _pass; else _fail "dir not found: $1  ($2)"; fi; }
assert_contains() { if echo "$1" | grep -qF "$2"; then _pass; else _fail "output missing '$2'  ($3)"; fi; }
assert_not_contains() { if ! echo "$1" | grep -qF "$2"; then _pass; else _fail "output should not contain '$2'  ($3)"; fi; }
section() { echo -e "\n${YELLOW}── $1 ──${NC}"; }

# ─── Paths ────────────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
OSTWIN_CLI="$BIN_DIR/ostwin"

# ─── Fixture: local git repo with SKILL.md ────────────────────────────────────

FIXTURE_DIR="$(mktemp -d)"
trap 'rm -rf "$FIXTURE_DIR"' EXIT

# Repo A: has SKILL.md at root with name in frontmatter
REPO_A_WORK="$FIXTURE_DIR/repo-a-work"
REPO_A_BARE="$FIXTURE_DIR/repo-a.git"
mkdir -p "$REPO_A_WORK"
git -C "$REPO_A_WORK" init -q
cat > "$REPO_A_WORK/SKILL.md" <<'SKILLEOF'
---
name: test-skill-alpha
description: A test skill for unit testing
tags: [testing, unit]
---

# Test Skill Alpha

This is a test skill.
SKILLEOF
cat > "$REPO_A_WORK/helper.txt" <<'EOF'
extra file that should be copied
EOF
git -C "$REPO_A_WORK" add -A && git -C "$REPO_A_WORK" commit -q -m "init"
git clone -q --bare "$REPO_A_WORK" "$REPO_A_BARE"
REPO_A_COMMIT="$(git -C "$REPO_A_WORK" rev-parse HEAD)"

# Repo B: has SKILL.md in a subdirectory, no name frontmatter
REPO_B_WORK="$FIXTURE_DIR/repo-b-work"
REPO_B_BARE="$FIXTURE_DIR/my-cool-skill.git"
mkdir -p "$REPO_B_WORK/skills/cool"
git -C "$REPO_B_WORK" init -q
cat > "$REPO_B_WORK/skills/cool/SKILL.md" <<'SKILLEOF'
---
description: Nested skill without name field
---

# Cool Nested Skill
SKILLEOF
git -C "$REPO_B_WORK" add -A && git -C "$REPO_B_WORK" commit -q -m "init"
git clone -q --bare "$REPO_B_WORK" "$REPO_B_BARE"

# Repo C: no SKILL.md at all
REPO_C_WORK="$FIXTURE_DIR/repo-c-work"
REPO_C_BARE="$FIXTURE_DIR/empty-repo.git"
mkdir -p "$REPO_C_WORK"
git -C "$REPO_C_WORK" init -q
echo "no skill here" > "$REPO_C_WORK/README.md"
git -C "$REPO_C_WORK" add -A && git -C "$REPO_C_WORK" commit -q -m "init"
git clone -q --bare "$REPO_C_WORK" "$REPO_C_BARE"

# Repo D: multi-skill repo with source/skills/ (like impeccable)
# Also has duplicate skills under .cursor/skills/ which must be ignored.
REPO_D_WORK="$FIXTURE_DIR/repo-d-work"
REPO_D_BARE="$FIXTURE_DIR/multi-skills.git"
mkdir -p "$REPO_D_WORK/source/skills/alpha" \
         "$REPO_D_WORK/source/skills/beta" \
         "$REPO_D_WORK/.cursor/skills/alpha" \
         "$REPO_D_WORK/.cursor/skills/beta"
git -C "$REPO_D_WORK" init -q
for loc in "source" ".cursor"; do
  printf -- '---\nname: alpha-skill\ndescription: alpha\n---\n# Alpha\n' > "$REPO_D_WORK/$loc/skills/alpha/SKILL.md"
  printf -- '---\nname: beta-skill\ndescription: beta\n---\n# Beta\n'   > "$REPO_D_WORK/$loc/skills/beta/SKILL.md"
done
git -C "$REPO_D_WORK" add -A && git -C "$REPO_D_WORK" commit -q -m "init"
git clone -q --bare "$REPO_D_WORK" "$REPO_D_BARE"

# Repo E: skills with nested references (parent SKILL.md + child SKILL.md)
REPO_E_WORK="$FIXTURE_DIR/repo-e-work"
REPO_E_BARE="$FIXTURE_DIR/nested-refs.git"
mkdir -p "$REPO_E_WORK/skills/main-skill/references/sub-ref"
git -C "$REPO_E_WORK" init -q
printf -- '---\nname: main-skill\n---\n# Main\n' > "$REPO_E_WORK/skills/main-skill/SKILL.md"
printf -- '---\nname: sub-ref-DO-NOT-INSTALL\n---\n# Sub\n' > "$REPO_E_WORK/skills/main-skill/references/sub-ref/SKILL.md"
echo "ref data" > "$REPO_E_WORK/skills/main-skill/references/sub-ref/data.txt"
git -C "$REPO_E_WORK" add -A && git -C "$REPO_E_WORK" commit -q -m "init"
git clone -q --bare "$REPO_E_WORK" "$REPO_E_BARE"

# Repo F: SKILL.md with empty name field
REPO_F_WORK="$FIXTURE_DIR/repo-f-work"
REPO_F_BARE="$FIXTURE_DIR/empty-name.git"
mkdir -p "$REPO_F_WORK"
git -C "$REPO_F_WORK" init -q
printf -- '---\nname: \ndescription: has empty name\n---\n# Empty Name\n' > "$REPO_F_WORK/SKILL.md"
git -C "$REPO_F_WORK" add -A && git -C "$REPO_F_WORK" commit -q -m "init"
git clone -q --bare "$REPO_F_WORK" "$REPO_F_BARE"

# Repo G: two skills in different subdirectories — flat scan should find both
REPO_G_WORK="$FIXTURE_DIR/repo-g-work"
REPO_G_BARE="$FIXTURE_DIR/agents-pref.git"
mkdir -p "$REPO_G_WORK/toolset-a/skill-one" \
         "$REPO_G_WORK/toolset-b/nested/skill-two"
git -C "$REPO_G_WORK" init -q
printf -- '---\nname: skill-one\n---\n# Skill One\n' > "$REPO_G_WORK/toolset-a/skill-one/SKILL.md"
printf -- '---\nname: skill-two\n---\n# Skill Two\n' > "$REPO_G_WORK/toolset-b/nested/skill-two/SKILL.md"
git -C "$REPO_G_WORK" add -A && git -C "$REPO_G_WORK" commit -q -m "init"
git clone -q --bare "$REPO_G_WORK" "$REPO_G_BARE"

# Repo H: stale files from a previous install should be removed on re-install
# V1: has old-asset.txt
REPO_H1_WORK="$FIXTURE_DIR/repo-h1-work"
REPO_H1_BARE="$FIXTURE_DIR/stale-v1.git"
mkdir -p "$REPO_H1_WORK"
git -C "$REPO_H1_WORK" init -q
printf -- '---\nname: evolving-skill\n---\n# V1\n' > "$REPO_H1_WORK/SKILL.md"
echo "old-asset" > "$REPO_H1_WORK/old-asset.txt"
git -C "$REPO_H1_WORK" add -A && git -C "$REPO_H1_WORK" commit -q -m "v1"
git clone -q --bare "$REPO_H1_WORK" "$REPO_H1_BARE"
# V2: has new-asset.txt, no old-asset.txt
REPO_H2_WORK="$FIXTURE_DIR/repo-h2-work"
REPO_H2_BARE="$FIXTURE_DIR/stale-v2.git"
mkdir -p "$REPO_H2_WORK"
git -C "$REPO_H2_WORK" init -q
printf -- '---\nname: evolving-skill\n---\n# V2\n' > "$REPO_H2_WORK/SKILL.md"
echo "new-asset" > "$REPO_H2_WORK/new-asset.txt"
git -C "$REPO_H2_WORK" add -A && git -C "$REPO_H2_WORK" commit -q -m "v2"
git clone -q --bare "$REPO_H2_WORK" "$REPO_H2_BARE"

# Repo I: URL with trailing slash
REPO_I_BARE="$REPO_A_BARE"  # reuse repo-a

# Repo J: multi-skill with NO frontmatter names (should use dir names)
REPO_J_WORK="$FIXTURE_DIR/repo-j-work"
REPO_J_BARE="$FIXTURE_DIR/noname-multi.git"
mkdir -p "$REPO_J_WORK/skills/foo" "$REPO_J_WORK/skills/bar"
git -C "$REPO_J_WORK" init -q
printf -- '---\ndescription: no name\n---\n# Foo\n' > "$REPO_J_WORK/skills/foo/SKILL.md"
printf -- '---\ndescription: no name\n---\n# Bar\n' > "$REPO_J_WORK/skills/bar/SKILL.md"
git -C "$REPO_J_WORK" add -A && git -C "$REPO_J_WORK" commit -q -m "init"
git clone -q --bare "$REPO_J_WORK" "$REPO_J_BARE"

# ─── Sandboxed HOME for install targets ───────────────────────────────────────

FAKE_HOME="$FIXTURE_DIR/fakehome"
mkdir -p "$FAKE_HOME/.ostwin/.agents/skills/global"
mkdir -p "$FAKE_HOME/.ostwin/skills/global"
# Create a minimal sync-skills.sh stub so the install doesn't error
mkdir -p "$FAKE_HOME/.ostwin"
cat > "$FAKE_HOME/.ostwin/sync-skills.sh" <<'STUBEOF'
#!/usr/bin/env bash
# stub — do nothing
exit 0
STUBEOF
chmod +x "$FAKE_HOME/.ostwin/sync-skills.sh"

# GitHub install tests stay offline by rewriting https://github.com/local/*.git
# to the local bare repos created under $FIXTURE_DIR.
GIT_CONFIG_FILE="$FIXTURE_DIR/gitconfig"
git config --file "$GIT_CONFIG_FILE" url."file://$FIXTURE_DIR/".insteadOf "https://github.com/local/"

repo_url() {
  printf 'https://github.com/local/%s\n' "$(basename "$1")"
}

# Helper: run install with sandboxed HOME, unreachable dashboard,
#         and AGENTS_DIR pointing at the real bin directory's parent.
run_install() {
  HOME="$FAKE_HOME" \
  OSTWIN_HOME="$FAKE_HOME/.ostwin" \
  AGENTS_DIR="$BIN_DIR/.." \
  DASHBOARD_URL="http://localhost:1" \
  GIT_CONFIG_GLOBAL="$GIT_CONFIG_FILE" \
  pwsh -NoProfile -File "$OSTWIN_CLI" skills install "$@" 2>&1
}

# =============================================================================
#  1. URL PATTERN MATCHING (unit)
# =============================================================================
section "1. URL pattern matching"

match_gh() {
  local url="$1"
  if [[ "$url" =~ ^https?://github\.com/ ]] || [[ "$url" =~ ^git@github\.com: ]]; then
    echo "yes"
  else
    echo "no"
  fi
}

assert_eq "$(match_gh 'https://github.com/user/repo')"       "yes" "https without .git"
assert_eq "$(match_gh 'https://github.com/user/repo.git')"   "yes" "https with .git"
assert_eq "$(match_gh 'http://github.com/user/repo')"        "yes" "http (non-TLS)"
assert_eq "$(match_gh 'git@github.com:user/repo.git')"       "yes" "SSH format"
assert_eq "$(match_gh 'git@github.com:org/repo')"            "yes" "SSH without .git"
assert_eq "$(match_gh 'steipete/web-search')"                "no"  "ClawHub slug"
assert_eq "$(match_gh './local-dir')"                         "no"  "relative path"
assert_eq "$(match_gh '/absolute/path')"                     "no"  "absolute path"
assert_eq "$(match_gh 'https://gitlab.com/user/repo.git')"   "no"  "non-GitHub URL"
assert_eq "$(match_gh 'web-search')"                         "no"  "bare slug"

# =============================================================================
#  2. SKILL NAME DERIVATION FROM URL (unit)
# =============================================================================
section "2. Skill name from URL"

derive_name() { basename "$1" .git; }

assert_eq "$(derive_name 'https://github.com/user/taste-skill.git')"  "taste-skill"  "strip .git"
assert_eq "$(derive_name 'https://github.com/user/taste-skill')"      "taste-skill"  "no .git"
assert_eq "$(derive_name 'git@github.com:org/my-repo.git')"           "my-repo"      "SSH .git"
assert_eq "$(derive_name 'https://github.com/user/repo')"             "repo"         "simple repo name"

# =============================================================================
#  3. FRONTMATTER NAME EXTRACTION (unit)
# =============================================================================
section "3. Frontmatter name extraction (awk)"

extract_name() {
  awk '/^---$/{if(++c==2)exit} c==1 && /^name:/{sub(/^name:[ \t]*/,""); gsub(/^["'\''"]|["'\''"]$/,""); print; exit}' <<< "$1"
}

assert_eq "$(extract_name '---
name: my-skill
description: hello
---')" "my-skill" "simple name"

assert_eq "$(extract_name '---
name: "quoted-skill"
description: hello
---')" "quoted-skill" "double-quoted name"

assert_eq "$(extract_name "---
name: 'single-quoted'
description: hello
---")" "single-quoted" "single-quoted name"

assert_eq "$(extract_name '---
description: no name field
---')" "" "missing name field"

assert_eq "$(extract_name 'no frontmatter at all')" "" "no frontmatter"

assert_eq "$(extract_name '---
name: stitch-design-taste
description: Semantic Design System Skill
tags: [design, ui]
---

# body content
name: not-this-one')" "stitch-design-taste" "name outside frontmatter ignored"

# =============================================================================
#  4. FULL INSTALL — SKILL.MD AT REPO ROOT WITH NAME (integration)
# =============================================================================
section "4. Full install: SKILL.md at root with frontmatter name"

# Clean install targets
rm -rf "$FAKE_HOME/.ostwin/.agents/skills/global/"*
rm -rf "$FAKE_HOME/.ostwin/skills/global/"*

OUT_A="$(run_install "$(repo_url "$REPO_A_BARE")")"
RC_A=$?

assert_ok "$RC_A" "exit code 0 for valid repo"
assert_contains "$OUT_A" "Installing skill from GitHub:" "prints install header"
assert_contains "$OUT_A" "Cloning repository" "prints clone message"
assert_contains "$OUT_A" "test-skill-alpha" "uses frontmatter name"

# Verify destination 1
DEST_A1="$FAKE_HOME/.ostwin/.agents/skills/global/test-skill-alpha"
assert_dir  "$DEST_A1" "dest1 directory exists"
assert_file "$DEST_A1/SKILL.md" "dest1 has SKILL.md"
assert_file "$DEST_A1/helper.txt" "dest1 has extra file"
assert_file "$DEST_A1/origin.json" "dest1 has origin.json"

# Verify destination 2
DEST_A2="$FAKE_HOME/.ostwin/skills/global/test-skill-alpha"
assert_dir  "$DEST_A2" "dest2 directory exists"
assert_file "$DEST_A2/SKILL.md" "dest2 has SKILL.md"
assert_file "$DEST_A2/helper.txt" "dest2 has extra file"
assert_file "$DEST_A2/origin.json" "dest2 has origin.json"

# Verify origin.json content
ORIGIN_JSON="$(cat "$DEST_A1/origin.json")"
assert_contains "$ORIGIN_JSON" '"source": "github"' "origin source is github"
assert_contains "$ORIGIN_JSON" "$(repo_url "$REPO_A_BARE")" "origin has URL"
assert_contains "$ORIGIN_JSON" "$REPO_A_COMMIT" "origin has commit SHA"
assert_contains "$ORIGIN_JSON" '"installed_at":' "origin has timestamp"

# =============================================================================
#  5. FULL INSTALL — NESTED SKILL.MD, NO FRONTMATTER NAME (integration)
# =============================================================================
section "5. Full install: nested SKILL.md, no name in frontmatter"

rm -rf "$FAKE_HOME/.ostwin/.agents/skills/global/"*
rm -rf "$FAKE_HOME/.ostwin/skills/global/"*

OUT_B="$(run_install "$(repo_url "$REPO_B_BARE")")"
RC_B=$?

assert_ok "$RC_B" "exit code 0"
# No name in frontmatter → falls back to repo basename ("my-cool-skill")
assert_contains "$OUT_B" "my-cool-skill" "falls back to repo name"
DEST_B1="$FAKE_HOME/.ostwin/.agents/skills/global/my-cool-skill"
assert_dir  "$DEST_B1" "dest1 created from repo name"
assert_file "$DEST_B1/SKILL.md" "SKILL.md copied from nested location"

# =============================================================================
#  6. MISSING SKILL.MD — SHOULD FAIL (integration)
# =============================================================================
section "6. Error: repo without SKILL.md"

rm -rf "$FAKE_HOME/.ostwin/.agents/skills/global/"*
rm -rf "$FAKE_HOME/.ostwin/skills/global/"*

# Capture exit code without || true swallowing it
RC_C=0
OUT_C="$(run_install "$(repo_url "$REPO_C_BARE")" 2>&1)" || RC_C=$?

assert_fail "$RC_C" "non-zero exit for missing SKILL.md"
assert_contains "$OUT_C" "No SKILL.md found" "error message mentions SKILL.md"

# =============================================================================
#  7. INVALID URL — CLONE FAILURE (integration)
# =============================================================================
section "7. Error: invalid URL (clone fails)"

RC_D=0
OUT_D="$(run_install "https://github.com/local/not-found.git" 2>&1)" || RC_D=$?

assert_fail "$RC_D" "non-zero exit for bad URL"
assert_contains "$OUT_D" "clone" "mentions clone in output"

# =============================================================================
#  8. TEMP DIRECTORY CLEANUP (integration)
# =============================================================================
section "8. Temp directory cleanup"

# After a successful install, no /tmp/tmp.* leftover from our test
# (We can't directly check since mktemp names are random, but we verify
#  the trap cleared the directory by checking nothing new exists.)
BEFORE_COUNT="$(find /tmp -maxdepth 1 -name 'tmp.*' -type d 2>/dev/null | wc -l)"
run_install "$(repo_url "$REPO_A_BARE")" >/dev/null 2>&1 || true
AFTER_COUNT="$(find /tmp -maxdepth 1 -name 'tmp.*' -type d 2>/dev/null | wc -l)"
# The after count should be <= before count (our temp was cleaned up)
if [[ "$AFTER_COUNT" -le "$BEFORE_COUNT" ]]; then
  ((PASS++))
else
  ((FAIL++))
  echo -e "  ${RED}FAIL${NC}: temp dir may not have been cleaned up (before=$BEFORE_COUNT after=$AFTER_COUNT)"
fi

# =============================================================================
#  9. IDEMPOTENT RE-INSTALL (integration)
# =============================================================================
section "9. Idempotent re-install overwrites cleanly"

rm -rf "$FAKE_HOME/.ostwin/.agents/skills/global/"*
rm -rf "$FAKE_HOME/.ostwin/skills/global/"*

# Install twice
run_install "$(repo_url "$REPO_A_BARE")" >/dev/null 2>&1
FIRST_ORIGIN="$(cat "$FAKE_HOME/.ostwin/.agents/skills/global/test-skill-alpha/origin.json")"
sleep 1
run_install "$(repo_url "$REPO_A_BARE")" >/dev/null 2>&1
SECOND_ORIGIN="$(cat "$FAKE_HOME/.ostwin/.agents/skills/global/test-skill-alpha/origin.json")"

# Both should have the same commit but potentially different timestamps
assert_contains "$SECOND_ORIGIN" "$REPO_A_COMMIT" "re-install keeps correct commit"
assert_file "$FAKE_HOME/.ostwin/.agents/skills/global/test-skill-alpha/SKILL.md" "SKILL.md present after re-install"
assert_file "$FAKE_HOME/.ostwin/.agents/skills/global/test-skill-alpha/helper.txt" "extra file present after re-install"

# =============================================================================
# 10. HELP TEXT INCLUDES GITHUB USAGE (unit)
# =============================================================================
section "10. Help text"

HELP_OUT="$(HOME="$FAKE_HOME" OSTWIN_HOME="$FAKE_HOME/.ostwin" AGENTS_DIR="$BIN_DIR/.." pwsh -NoProfile -File "$OSTWIN_CLI" skills bogus 2>&1)" || true
assert_contains "$HELP_OUT" "github-url" "help mentions github-url"
assert_contains "$HELP_OUT" "https://github.com/user/skill-repo" "help has GitHub examples"

# =============================================================================
# 11. MULTI-SKILL REPO — ALL SKILL.MD FILES INSTALLED (integration)
#     With flat unlimited scan, all SKILL.md files anywhere in the repo are
#     found. The nesting-detection skips sub-skills inside a parent skill's
#     tree, but parallel copies (source/ vs .cursor/) are both installed.
# =============================================================================
section "11. Multi-skill: flat scan installs all top-level SKILL.md folders"

rm -rf "$FAKE_HOME/.ostwin/.agents/skills/global/"*
rm -rf "$FAKE_HOME/.ostwin/skills/global/"*

OUT_D="$(run_install "$(repo_url "$REPO_D_BARE")")"
RC_D=$?

assert_ok "$RC_D" "exit code 0"
assert_contains "$OUT_D" "alpha-skill" "installed alpha"
assert_contains "$OUT_D" "beta-skill"  "installed beta"
# Flat scan finds both source/ and .cursor/ copies (4 total, but same skill name
# overwrites — last-writer-wins for same skill name)
assert_file "$FAKE_HOME/.ostwin/.agents/skills/global/alpha-skill/SKILL.md" "alpha at dest1"
assert_file "$FAKE_HOME/.ostwin/.agents/skills/global/beta-skill/SKILL.md"  "beta at dest1"
assert_file "$FAKE_HOME/.ostwin/skills/global/alpha-skill/SKILL.md" "alpha at dest2"
assert_file "$FAKE_HOME/.ostwin/skills/global/beta-skill/SKILL.md"  "beta at dest2"

# =============================================================================
# 12. NESTED SKILL.MD INSIDE REFERENCES NOT INSTALLED SEPARATELY (integration)
# =============================================================================
section "12. Nested SKILL.md in references/ skipped"

rm -rf "$FAKE_HOME/.ostwin/.agents/skills/global/"*
rm -rf "$FAKE_HOME/.ostwin/skills/global/"*

OUT_E="$(run_install "$(repo_url "$REPO_E_BARE")")"
RC_E=$?

assert_ok "$RC_E" "exit code 0"
assert_contains "$OUT_E" "main-skill" "main skill installed"
assert_not_contains "$OUT_E" "sub-ref-DO-NOT-INSTALL" "nested ref skill NOT installed separately"
E_COUNT="$(echo "$OUT_E" | grep -c "Installed '")"
assert_eq "$E_COUNT" "1" "exactly 1 skill installed"
# But the nested files should still be present inside the parent skill tree
assert_file "$FAKE_HOME/.ostwin/.agents/skills/global/main-skill/references/sub-ref/SKILL.md" "nested SKILL.md preserved in parent tree"
assert_file "$FAKE_HOME/.ostwin/.agents/skills/global/main-skill/references/sub-ref/data.txt" "nested data preserved"

# =============================================================================
# 13. EMPTY NAME FIELD — FALLS BACK TO REPO NAME (integration)
# =============================================================================
section "13. Empty name: field falls back to repo name"

rm -rf "$FAKE_HOME/.ostwin/.agents/skills/global/"*
rm -rf "$FAKE_HOME/.ostwin/skills/global/"*

OUT_F="$(run_install "$(repo_url "$REPO_F_BARE")")"
RC_F=$?

assert_ok "$RC_F" "exit code 0"
# name is empty string → should fall back to repo name "empty-name"
assert_contains "$OUT_F" "empty-name" "falls back to repo name when name is empty"
assert_file "$FAKE_HOME/.ostwin/.agents/skills/global/empty-name/SKILL.md" "skill installed with repo name"

# =============================================================================
# 14. FLAT SCAN — ALL SKILL.MD FOUND REGARDLESS OF LOCATION (integration)
#     With flat scan, skills at different subdirectory levels are all found.
# =============================================================================
section "14. Flat scan: skills at different depths both installed"

rm -rf "$FAKE_HOME/.ostwin/.agents/skills/global/"*
rm -rf "$FAKE_HOME/.ostwin/skills/global/"*

OUT_G="$(run_install "$(repo_url "$REPO_G_BARE")")"
RC_G=$?

assert_ok "$RC_G" "exit code 0"
assert_contains "$OUT_G" "skill-one" "skill-one installed (depth 2)"
assert_contains "$OUT_G" "skill-two" "skill-two installed (depth 3)"
assert_file "$FAKE_HOME/.ostwin/.agents/skills/global/skill-one/SKILL.md" "skill-one at dest"
assert_file "$FAKE_HOME/.ostwin/.agents/skills/global/skill-two/SKILL.md" "skill-two at dest"

# =============================================================================
# 15. STALE FILES REMOVED ON RE-INSTALL (integration)
# =============================================================================
section "15. Stale files removed on re-install"

rm -rf "$FAKE_HOME/.ostwin/.agents/skills/global/"*
rm -rf "$FAKE_HOME/.ostwin/skills/global/"*

# Install V1 (has old-asset.txt, no new-asset.txt)
run_install "$(repo_url "$REPO_H1_BARE")" >/dev/null 2>&1
assert_file "$FAKE_HOME/.ostwin/.agents/skills/global/evolving-skill/old-asset.txt" "v1 has old-asset"

# Install V2 (has new-asset.txt, no old-asset.txt)
run_install "$(repo_url "$REPO_H2_BARE")" >/dev/null 2>&1
if [[ -f "$FAKE_HOME/.ostwin/.agents/skills/global/evolving-skill/old-asset.txt" ]]; then
  _fail "stale old-asset.txt NOT removed after re-install"
else
  _pass
fi
assert_file "$FAKE_HOME/.ostwin/.agents/skills/global/evolving-skill/new-asset.txt" "v2 has new-asset"

# =============================================================================
# 16. URL WITH TRAILING SLASH (unit)
# =============================================================================
section "16. URL edge cases"

# Trailing slash
assert_eq "$(match_gh 'https://github.com/user/repo/')"      "yes" "trailing slash"
# Trailing .git with slash
assert_eq "$(match_gh 'https://github.com/user/repo.git/')"  "yes" "trailing .git/"
# Extra path segments (tree/main)
assert_eq "$(match_gh 'https://github.com/user/repo/tree/main')" "yes" "tree/main path"

# basename derivation with trailing slash — bash basename strips trailing /
assert_eq "$(derive_name 'https://github.com/user/my-skill/')"      "my-skill"  "trailing slash stripped by basename"
assert_eq "$(derive_name 'https://github.com/user/my-skill.git/')"  "my-skill"  "trailing .git/ stripped by basename"

# =============================================================================
# 17. MULTI-SKILL, NO FRONTMATTER NAMES — USES DIR NAMES (integration)
# =============================================================================
section "17. Multi-skill without names uses directory names"

rm -rf "$FAKE_HOME/.ostwin/.agents/skills/global/"*
rm -rf "$FAKE_HOME/.ostwin/skills/global/"*

OUT_J="$(run_install "$(repo_url "$REPO_J_BARE")")"
RC_J=$?

assert_ok "$RC_J" "exit code 0"
# Should use directory names foo/bar since there's no frontmatter name and it's multi-skill
assert_contains "$OUT_J" "'foo'" "uses dir name 'foo'"
assert_contains "$OUT_J" "'bar'" "uses dir name 'bar'"
assert_file "$FAKE_HOME/.ostwin/.agents/skills/global/foo/SKILL.md" "foo installed"
assert_file "$FAKE_HOME/.ostwin/.agents/skills/global/bar/SKILL.md" "bar installed"

# =============================================================================
# 18. FRONTMATTER — ADDITIONAL EDGE CASES (unit)
# =============================================================================
section "18. Frontmatter edge cases"

# Empty value after name:
assert_eq "$(extract_name '---
name:
description: empty
---')" "" "name with no value"

# name: with only whitespace
assert_eq "$(extract_name '---
name:   
description: ws
---')" "" "name with only whitespace"

# name with colons in value
assert_eq "$(extract_name '---
name: my:special:skill
description: test
---')" "my:special:skill" "name containing colons"

# Multiple name: fields — first wins
assert_eq "$(extract_name '---
name: first-name
name: second-name
---')" "first-name" "first name: field wins"

# =============================================================================
# 19. DEEP FOLDER STRUCTURE — SKILL.MD AT ANY DEPTH (regression, integration)
#     Reproduces: ostwin skills install https://github.com/bmad-code-org/BMAD-METHOD.git
#     Strategy: scan the entire repo with no depth limit and install every
#     folder that contains a SKILL.md (regardless of nesting level).
# =============================================================================
section "19. Deep folder: SKILL.md at any depth — unlimited scan"

rm -rf "$FAKE_HOME/.ostwin/.agents/skills/global/"*
rm -rf "$FAKE_HOME/.ostwin/skills/global/"*

# Build a repo that mimics BMAD-METHOD mixed structure:
#   src/bmm-skills/1-analysis/bmad-analyst/SKILL.md  (depth 4)
#   src/bmm-skills/2-planning/bmad-pm/SKILL.md        (depth 4)
#   src/core-skills/bmad-elicitation/SKILL.md          (depth 3)
#   any-folder/deep-skill/SKILL.md                     (depth 2, generic)
REPO_BMAD_WORK="$FIXTURE_DIR/repo-bmad-work"
REPO_BMAD_BARE="$FIXTURE_DIR/bmad-deep.git"
mkdir -p "$REPO_BMAD_WORK/src/bmm-skills/1-analysis/bmad-analyst" \
         "$REPO_BMAD_WORK/src/bmm-skills/2-planning/bmad-pm" \
         "$REPO_BMAD_WORK/src/core-skills/bmad-elicitation" \
         "$REPO_BMAD_WORK/plugins/deep-skill"
git -C "$REPO_BMAD_WORK" init -q
printf -- '---\nname: bmad-analyst\ndescription: analyst\n---\n# Analyst\n' \
  > "$REPO_BMAD_WORK/src/bmm-skills/1-analysis/bmad-analyst/SKILL.md"
printf -- '---\nname: bmad-pm\ndescription: pm\n---\n# PM\n' \
  > "$REPO_BMAD_WORK/src/bmm-skills/2-planning/bmad-pm/SKILL.md"
printf -- '---\nname: bmad-elicitation\ndescription: elicitation\n---\n# Elicitation\n' \
  > "$REPO_BMAD_WORK/src/core-skills/bmad-elicitation/SKILL.md"
printf -- '---\nname: deep-skill\ndescription: generic deep\n---\n# Deep\n' \
  > "$REPO_BMAD_WORK/plugins/deep-skill/SKILL.md"
git -C "$REPO_BMAD_WORK" add -A && git -C "$REPO_BMAD_WORK" commit -q -m "bmad-like init"
git clone -q --bare "$REPO_BMAD_WORK" "$REPO_BMAD_BARE"

OUT_BMAD="$(run_install "$(repo_url "$REPO_BMAD_BARE")")"
RC_BMAD=$?

assert_ok   "$RC_BMAD" "19: exit code 0 for deep-folder repo"
assert_not_contains "$OUT_BMAD" "No SKILL.md found" "19: does NOT emit 'SKILL.md not found'"
assert_contains "$OUT_BMAD" "bmad-analyst"    "19: bmad-analyst installed (depth 4)"
assert_contains "$OUT_BMAD" "bmad-pm"         "19: bmad-pm installed (depth 4)"
assert_contains "$OUT_BMAD" "bmad-elicitation" "19: bmad-elicitation installed (depth 3)"
assert_contains "$OUT_BMAD" "deep-skill"       "19: deep-skill installed (depth 2, generic)"
BMAD_COUNT="$(echo "$OUT_BMAD" | grep -c "Installed '")"
assert_eq "$BMAD_COUNT" "4" "19: all 4 skills installed from flat unlimited scan"
assert_file "$FAKE_HOME/.ostwin/.agents/skills/global/bmad-analyst/SKILL.md"     "19: bmad-analyst at dest"
assert_file "$FAKE_HOME/.ostwin/.agents/skills/global/bmad-pm/SKILL.md"          "19: bmad-pm at dest"
assert_file "$FAKE_HOME/.ostwin/.agents/skills/global/bmad-elicitation/SKILL.md" "19: bmad-elicitation at dest"
assert_file "$FAKE_HOME/.ostwin/.agents/skills/global/deep-skill/SKILL.md"       "19: deep-skill at dest"

# =============================================================================
# SUMMARY
# =============================================================================
echo ""
echo "════════════════════════════════════════════"
TOTAL=$((PASS + FAIL))
if [[ $FAIL -eq 0 ]]; then
  echo -e "  ${GREEN}ALL $TOTAL TESTS PASSED${NC}"
else
  echo -e "  ${RED}$FAIL/$TOTAL TESTS FAILED${NC}"
fi
echo "  (pass=$PASS fail=$FAIL)"
echo "════════════════════════════════════════════"

exit "$FAIL"
