#!/usr/bin/env bats
# Tests for start-opencode-server.sh

setup() {
  INSTALLER_DIR="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
  source "$INSTALLER_DIR/lib.sh"
  source "$INSTALLER_DIR/start-opencode-server.sh"
}

@test "start-opencode-server.sh can be sourced without side effects" {
  [[ -n "$_START_OPENCODE_SERVER_SH_LOADED" ]]
}

@test "start_opencode_server function is defined" {
  declare -f start_opencode_server > /dev/null
}

@test "start_opencode_server uses the managed opencode_server workdir" {
  grep -Fq 'local project_dir="$server_dir"' "$INSTALLER_DIR/start-opencode-server.sh"
  ! grep -Fq 'SOURCE_DIR:-$server_dir' "$INSTALLER_DIR/start-opencode-server.sh"
}

@test "_is_opencode_serve_process matches serve process even with truncated comm" {
  ps() {
    case "$*" in
      "-p 123 -o comm=") echo "opencode" ;;
      "-p 123 -o args=") echo "opencode serve --hostname 127.0.0.1 --port 4096" ;;
    esac
  }

  _is_opencode_serve_process 123
  unset -f ps
}

@test "_is_opencode_serve_process rejects non-server opencode commands" {
  ps() {
    case "$*" in
      "-p 123 -o comm=") echo "opencode" ;;
      "-p 123 -o args=") echo "opencode auth login" ;;
    esac
  }

  ! _is_opencode_serve_process 123
  unset -f ps
}

@test "_load_opencode_service_env sources global and project env files" {
  INSTALL_DIR="$BATS_TEST_TMPDIR/install"
  local project_dir="$BATS_TEST_TMPDIR/project"
  mkdir -p "$INSTALL_DIR" "$project_dir/.agents"

  cat > "$INSTALL_DIR/.env" <<'EOF'
GLOBAL_ONLY=global
SHARED_VALUE=global
EOF
  cat > "$INSTALL_DIR/.env.sh" <<'EOF'
GLOBAL_HOOK=global-hook
EOF
  cat > "$project_dir/.env" <<'EOF'
PROJECT_ONLY=project
SHARED_VALUE=project
EOF
  cat > "$project_dir/.agents/.env" <<'EOF'
AGENTS_ONLY=agents
EOF

  _load_opencode_service_env "$project_dir"

  [[ "$GLOBAL_ONLY" == "global" ]]
  [[ "$GLOBAL_HOOK" == "global-hook" ]]
  [[ "$PROJECT_ONLY" == "project" ]]
  [[ "$AGENTS_ONLY" == "agents" ]]
  [[ "$SHARED_VALUE" == "project" ]]
}
