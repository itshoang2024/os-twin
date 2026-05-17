#!/usr/bin/env bats
# Tests for build-frontend.sh

setup() {
  INSTALLER_DIR="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
  source "$INSTALLER_DIR/lib.sh"
  source "$INSTALLER_DIR/build-frontend.sh"
}

@test "build-frontend.sh can be sourced without side effects" {
  [[ -n "$_BUILD_FRONTEND_SH_LOADED" ]]
}

@test "build_frontend function is defined (unified)" {
  declare -f build_frontend > /dev/null
}

@test "build_frontend accepts subdir and label args" {
  # Should gracefully handle a nonexistent dir
  SOURCE_DIR="/nonexistent"
  SCRIPT_DIR="/nonexistent"
  run build_frontend "nonexistent/dir" "Test Build"
  [[ "$output" == *"Test Build not found"* ]]
}

@test "build_frontend fails when required frontend is missing" {
  SOURCE_DIR="/nonexistent"
  SCRIPT_DIR="/nonexistent"
  run build_frontend "nonexistent/dir" "Required Build" true
  [ "$status" -ne 0 ]
  [[ "$output" == *"Required Build not found"* ]]
}

@test "build_frontend prefers package manager matching pnpm lockfile" {
  local root="$BATS_TEST_TMPDIR/frontend-pm"
  local fe_dir="$root/source/dashboard/fe"
  local bin_dir="$root/bin"
  export CALL_LOG="$root/calls.log"

  mkdir -p "$fe_dir" "$bin_dir"
  printf '{"scripts":{"build":"next build"}}\n' > "$fe_dir/package.json"
  touch "$fe_dir/pnpm-lock.yaml"

  for tool in bun pnpm npm yarn; do
    cat > "$bin_dir/$tool" <<'EOF'
#!/usr/bin/env bash
echo "$(basename "$0") $*" >> "$CALL_LOG"
exit 0
EOF
    chmod +x "$bin_dir/$tool"
  done

  export SOURCE_DIR="$root/source"
  export SCRIPT_DIR="$root/source/.agents"
  export PATH="$bin_dir:$PATH"

  run build_frontend "dashboard/fe" "Dashboard FE" true
  [ "$status" -eq 0 ]

  local calls
  calls="$(cat "$CALL_LOG")"
  [[ "$calls" == *"pnpm install --frozen-lockfile"* ]]
  [[ "$calls" == *"pnpm run build"* ]]
  [[ "$calls" != *"bun "* ]]
}

@test "build_frontend returns nonzero when required build fails" {
  local root="$BATS_TEST_TMPDIR/frontend-fail"
  local fe_dir="$root/source/dashboard/fe"
  local bin_dir="$root/bin"

  mkdir -p "$fe_dir" "$bin_dir"
  printf '{"scripts":{"build":"next build"}}\n' > "$fe_dir/package.json"
  touch "$fe_dir/pnpm-lock.yaml"

  cat > "$bin_dir/pnpm" <<'EOF'
#!/usr/bin/env bash
if [[ "$1" == "run" && "$2" == "build" ]]; then
  exit 7
fi
exit 0
EOF
  chmod +x "$bin_dir/pnpm"

  export SOURCE_DIR="$root/source"
  export SCRIPT_DIR="$root/source/.agents"
  export PATH="$bin_dir:$PATH"

  run build_frontend "dashboard/fe" "Dashboard FE" true
  [ "$status" -ne 0 ]
  [[ "$output" == *"Dashboard FE build failed"* ]]
}

@test "build_frontend keeps optional build failures non-fatal" {
  local root="$BATS_TEST_TMPDIR/frontend-optional-fail"
  local fe_dir="$root/source/dashboard/fe"
  local bin_dir="$root/bin"

  mkdir -p "$fe_dir" "$bin_dir"
  printf '{"scripts":{"build":"next build"}}\n' > "$fe_dir/package.json"
  touch "$fe_dir/pnpm-lock.yaml"

  cat > "$bin_dir/pnpm" <<'EOF'
#!/usr/bin/env bash
if [[ "$1" == "run" && "$2" == "build" ]]; then
  exit 7
fi
exit 0
EOF
  chmod +x "$bin_dir/pnpm"

  export SOURCE_DIR="$root/source"
  export SCRIPT_DIR="$root/source/.agents"
  export PATH="$bin_dir:$PATH"

  run build_frontend "dashboard/fe" "Dashboard FE"
  [ "$status" -eq 0 ]
  [[ "$output" == *"Dashboard FE build failed"* ]]
}

@test "old build_nextjs and build_dashboard_fe are NOT defined" {
  # Ensure the old functions don't exist
  ! declare -f build_nextjs > /dev/null 2>&1
  ! declare -f build_dashboard_fe > /dev/null 2>&1
}
