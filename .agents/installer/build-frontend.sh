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

  if [[ -f "$fe_dir/pnpm-lock.yaml" ]] && command -v pnpm &>/dev/null; then
    echo "pnpm"
    return 0
  fi
  if [[ -f "$fe_dir/package-lock.json" || -f "$fe_dir/npm-shrinkwrap.json" ]] && command -v npm &>/dev/null; then
    echo "npm"
    return 0
  fi
  if [[ -f "$fe_dir/yarn.lock" ]] && command -v yarn &>/dev/null; then
    echo "yarn"
    return 0
  fi
  if [[ -f "$fe_dir/bun.lockb" || -f "$fe_dir/bun.lock" ]] && command -v bun &>/dev/null; then
    echo "bun"
    return 0
  fi

  for tool in pnpm npm yarn bun; do
    if command -v "$tool" &>/dev/null; then
      echo "$tool"
      return 0
    fi
  done

  return 1
}

_install_frontend_deps() {
  local pm="$1"
  local output=""

  case "$pm" in
    pnpm)
      if output="$(pnpm install --frozen-lockfile 2>&1)"; then
        [[ -n "$output" ]] && printf '%s\n' "$output"
        return 0
      fi

      if [[ "$output" == *"ERR_PNPM_OUTDATED_LOCKFILE"* ]] && ! _frontend_ci_mode; then
        warn "pnpm lockfile is out of date; retrying with --no-frozen-lockfile"
        pnpm install --no-frozen-lockfile
        return $?
      fi

      [[ -n "$output" ]] && printf '%s\n' "$output" >&2
      return 1
      ;;
    npm)
      if [[ -f package-lock.json || -f npm-shrinkwrap.json ]]; then
        npm ci
      else
        npm install
      fi
      ;;
    yarn)
      yarn install --frozen-lockfile
      ;;
    bun)
      bun install --frozen-lockfile
      ;;
    *)
      "$pm" install
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
    warn "No package manager (bun/pnpm/npm/yarn) found — skipping $label build"
    info "Install Node.js and a package manager to enable $label"
    [[ "$required" == "true" || "$required" == "required" || "$required" == "--required" ]] && return 1
    return
  fi

  step "Building $label ($pm) at $fe_dir..."
  if (
    set -e
    cd "$fe_dir" || exit
    step "Installing npm dependencies..."
    _install_frontend_deps "$pm"
    "$pm" run build
  ); then
    ok "$label build complete"
  else
    warn "$label build failed"
    [[ "$required" == "true" || "$required" == "required" || "$required" == "--required" ]] && return 1
    return 0
  fi
}
