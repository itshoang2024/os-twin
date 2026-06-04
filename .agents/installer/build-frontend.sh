#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# build-frontend.sh — Unified frontend build function
#
# Provides: build_frontend(dir, label, required)
#
# Replaces the old build_nextjs() and build_dashboard_fe() with a single
# parameterized function that can build any frontend project.
#
# Requires: lib.sh, globals: SOURCE_DIR, SCRIPT_DIR
# ──────────────────────────────────────────────────────────────────────────────

# Guard against double-sourcing
[[ -n "${_BUILD_FRONTEND_SH_LOADED:-}" ]] && return 0
_BUILD_FRONTEND_SH_LOADED=1

# ─── build_frontend ─────────────────────────────────────────────────────────
# Usage: build_frontend <subdir> <label> [required]
#   subdir — relative path under the source repo (e.g. "dashboard/fe")
#   label  — human-readable label for log messages (e.g. "Dashboard FE")
#   required — true|required|--required to fail when the frontend cannot build

_frontend_ci_mode() {
  [[ "${CI:-}" == "1" || "${CI:-}" == "true" || "${CI:-}" == "TRUE" ]]
}

_select_frontend_pm() {
  local fe_dir="$1"

  # Installer builds intentionally support only bun and npm. Prefer the
  # package manager with a committed lockfile, then fall back to npm because
  # Node.js includes it by default and no extra bootstrap step is needed.
  if [[ ( -f "$fe_dir/bun.lockb" || -f "$fe_dir/bun.lock" ) ]] && command -v bun &>/dev/null; then
    echo "bun"
    return 0
  fi
  if [[ ( -f "$fe_dir/package-lock.json" || -f "$fe_dir/npm-shrinkwrap.json" ) ]] && command -v npm &>/dev/null; then
    echo "npm"
    return 0
  fi
  if command -v npm &>/dev/null; then
    echo "npm"
    return 0
  fi
  if command -v bun &>/dev/null; then
    echo "bun"
    return 0
  fi

  return 1
}

_install_frontend_deps() {
  local pm="$1"
  local output=""

  case "$pm" in
    bun)
      if [[ -f bun.lockb || -f bun.lock ]]; then
        if output="$(bun install --frozen-lockfile 2>&1)"; then
          [[ -n "$output" ]] && printf '%s\n' "$output"
          return 0
        fi

        if ! _frontend_ci_mode; then
          warn "bun lockfile is out of date; retrying without --frozen-lockfile"
          [[ -n "$output" ]] && printf '%s\n' "$output" >&2
          bun install
          return $?
        fi

        [[ -n "$output" ]] && printf '%s\n' "$output" >&2
        return 1
      fi

      bun install
      ;;
    npm)
      if [[ -f package-lock.json || -f npm-shrinkwrap.json ]]; then
        if output="$(npm ci 2>&1)"; then
          [[ -n "$output" ]] && printf '%s\n' "$output"
          return 0
        fi

        if ! _frontend_ci_mode; then
          warn "npm lockfile install failed; retrying with npm install"
          [[ -n "$output" ]] && printf '%s\n' "$output" >&2
          npm install
          return $?
        fi

        [[ -n "$output" ]] && printf '%s\n' "$output" >&2
        return 1
      fi

      npm install
      ;;
    *)
      warn "Unsupported JavaScript package manager: $pm"
      return 1
      ;;
  esac
}

build_frontend() {
  local subdir="$1"
  local label="${2:-$subdir}"
  local required="${3:-false}"

  # Locate the frontend directory relative to the source repo
  local fe_dir=""
  for candidate in \
    "${SOURCE_DIR}/${subdir}" \
    "${SCRIPT_DIR}/../${subdir}" \
    "${SCRIPT_DIR}/${subdir}"; do
    if [[ -d "$candidate" ]] && [[ -f "$candidate/package.json" ]]; then
      fe_dir="$(cd "$candidate" && pwd)"
      break
    fi
  done

  if [[ -z "$fe_dir" ]]; then
    warn "$label not found — skipping build"
    info "Expected at ${subdir}/package.json"
    [[ "$required" == "true" || "$required" == "required" || "$required" == "--required" ]] && return 1
    return
  fi

  # Pick the package manager that matches the committed lockfile.
  local pm=""
  pm="$(_select_frontend_pm "$fe_dir" || true)"

  if [[ -z "$pm" ]]; then
    warn "No package manager (bun/npm) found — skipping $label build"
    info "Install bun or npm to enable $label"
    [[ "$required" == "true" || "$required" == "required" || "$required" == "--required" ]] && return 1
    return
  fi

  local lock_dir="$fe_dir/.next-build.lock"
  local waited=0
  while ! mkdir "$lock_dir" 2>/dev/null; do
    local lock_pid=""
    [[ -f "$lock_dir/pid" ]] && lock_pid="$(cat "$lock_dir/pid" 2>/dev/null || true)"
    if [[ -n "$lock_pid" ]] && ! kill -0 "$lock_pid" 2>/dev/null; then
      rm -rf "$lock_dir"
      continue
    fi
    if (( waited == 0 )); then
      warn "$label build is already running; waiting for .next build lock"
    fi
    if (( waited >= 900 )); then
      warn "Timed out waiting for $label build lock at $lock_dir"
      [[ "$required" == "true" || "$required" == "required" || "$required" == "--required" ]] && return 1
      return 0
    fi
    sleep 2
    waited=$((waited + 2))
  done
  printf '%s\n' "$$" > "$lock_dir/pid" 2>/dev/null || true

  local status=0
  step "Building $label ($pm) at $fe_dir..."
  (
    set -e
    cd "$fe_dir" || exit
    step "Installing JavaScript dependencies with $pm..."
    _install_frontend_deps "$pm"
    "$pm" run build
  ) || status=$?
  rm -rf "$lock_dir"

  if [[ "$status" -eq 0 ]]; then
    ok "$label build complete"
  else
    warn "$label build failed"
    [[ "$required" == "true" || "$required" == "required" || "$required" == "--required" ]] && return 1
    return 0
  fi
}
