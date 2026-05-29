#!/usr/bin/env bats
# Tests for search-engine.sh

setup() {
  REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../../.." && pwd)"
  SEARCH_SCRIPT="$REPO_ROOT/.agents/search-engine.sh"
  TMP_OSTWIN_HOME="$(mktemp -d)"
}

teardown() {
  rm -rf "$TMP_OSTWIN_HOME"
}

@test "search-engine.sh shows help" {
  run bash "$SEARCH_SCRIPT" --help
  [ "$status" -eq 0 ]
  [[ "$output" == *"ostwin search-engine"* ]]
  [[ "$output" == *"install"* ]]
}

@test "configure writes SearXNG settings under OSTWIN_HOME" {
  run env OSTWIN_HOME="$TMP_OSTWIN_HOME" bash "$SEARCH_SCRIPT" configure --port 9999 --bind 127.0.0.1
  [ "$status" -eq 0 ]

  settings="$TMP_OSTWIN_HOME/search-engine/etc/settings.yml"
  [ -f "$settings" ]

  content="$(cat "$settings")"
  [[ "$content" == *"use_default_settings: true"* ]]
  [[ "$content" == *"port: 9999"* ]]
  [[ "$content" == *"bind_address: \"127.0.0.1\""* ]]
  [[ "$content" == *"- json"* ]]
  [[ "$content" == *"name: bing"* ]]
  [[ "$content" == *"name: google"* ]]
  [[ "$content" == *"disabled: false"* ]]
}

@test "configure copies and patches SearXNG template when source exists" {
  template_dir="$TMP_OSTWIN_HOME/search-engine/searxng-src/utils/templates/etc/searxng"
  mkdir -p "$template_dir"
  printf '%s\n' \
    'use_default_settings: true' \
    'server:' \
    '  secret_key: "ultrasecretkey"' \
    '  port: 6633' \
    '  bind_address: "127.0.0.1"' \
    'search:' \
    '  formats:' \
    '    - html' \
    'engines:' \
    '  - name: bing' \
    '    disabled: true' \
    > "$template_dir/settings.yml"

  run env OSTWIN_HOME="$TMP_OSTWIN_HOME" bash "$SEARCH_SCRIPT" configure --port 9997 --bind 127.0.0.1
  [ "$status" -eq 0 ]

  settings="$TMP_OSTWIN_HOME/search-engine/etc/settings.yml"
  [ -f "$settings" ]
  content="$(cat "$settings")"
  [[ "$content" == *"port: 9997"* ]]
  [[ "$content" != *"ultrasecretkey"* ]]
  [[ "$content" == *"- json"* ]]
  [[ "$content" == *"name: google"* ]]
  [[ "$content" == *"disabled: false"* ]]
}

@test "configure rejects invalid port" {
  run env OSTWIN_HOME="$TMP_OSTWIN_HOME" bash "$SEARCH_SCRIPT" configure --port nope
  [ "$status" -ne 0 ]
  [[ "$output" == *"Invalid port"* ]]
}

@test "status reports live PID that is not serving expected URL" {
  mkdir -p "$TMP_OSTWIN_HOME/search-engine" "$TMP_OSTWIN_HOME/bin"
  sleep 30 &
  live_pid="$!"
  printf '%s\n' "$live_pid" > "$TMP_OSTWIN_HOME/search-engine/searxng.pid"
  cat > "$TMP_OSTWIN_HOME/bin/curl" <<'EOF'
#!/usr/bin/env bash
exit 7
EOF
  chmod +x "$TMP_OSTWIN_HOME/bin/curl"

  run env OSTWIN_HOME="$TMP_OSTWIN_HOME" PATH="$TMP_OSTWIN_HOME/bin:$PATH" bash "$SEARCH_SCRIPT" status

  kill "$live_pid" 2>/dev/null || true
  [ "$status" -eq 0 ]
  [[ "$output" == *"process exists"* ]]
  [[ "$output" == *"not responding on http://127.0.0.1:6633"* ]]
}
