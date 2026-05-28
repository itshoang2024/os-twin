#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# verify.sh — Component status display
#
# Provides: verify_components, print_completion_banner
#
# Requires: lib.sh, check-deps.sh (check_python, check_pwsh, check_uv,
#           check_opencode, check_agent_browser), globals: INSTALL_DIR, VENV_DIR, DASHBOARD_ONLY,
#           BASH_VER, PYTHON_VERSION, PWSH_VERSION, DASHBOARD_PORT,
#           START_CHANNEL, TUNNEL_URL
# ──────────────────────────────────────────────────────────────────────────────

# Guard against double-sourcing
[[ -n "${_VERIFY_SH_LOADED:-}" ]] && return 0
_VERIFY_SH_LOADED=1

verify_components() {
  echo ""
  if ${DASHBOARD_ONLY:-false}; then
    echo -e "  ${BOLD}Dashboard-Only Component Status:${NC}"
    local py_cmd
    py_cmd=$(check_python)
    if [[ -n "$py_cmd" ]]; then
      echo -e "    python:           ${GREEN}✅ $PYTHON_VERSION${NC}"
    else
      echo -e "    python:           ${RED}❌ not found${NC}"
    fi
    if [[ -d "$VENV_DIR" ]]; then
      echo -e "    venv:             ${GREEN}✅ $VENV_DIR${NC}"
    else
      echo -e "    venv:             ${RED}❌ not created${NC}"
    fi
    if [[ -f "$INSTALL_DIR/dashboard/api.py" ]]; then
      echo -e "    dashboard api:    ${GREEN}✅ installed${NC}"
    else
      echo -e "    dashboard api:    ${RED}❌ not found${NC}"
    fi
  else
    echo -e "  ${BOLD}Component Status:${NC}"
    echo -e "    bash:             ${GREEN}✅ ${BASH_VER:-$(bash --version | head -1 | grep -oE '[0-9]+\.[0-9]+' | head -1)}${NC}"

    local py_cmd
    py_cmd=$(check_python)
    if [[ -n "$py_cmd" ]]; then
      echo -e "    python:           ${GREEN}✅ $PYTHON_VERSION${NC}"
    else
      echo -e "    python:           ${RED}❌ not found${NC}"
    fi

    if check_pwsh; then
      echo -e "    powershell:       ${GREEN}✅ $PWSH_VERSION${NC}"
    else
      echo -e "    powershell:       ${YELLOW}⚠️  not installed${NC}"
    fi

    if check_uv; then
      echo -e "    uv:               ${GREEN}✅ $(uv --version 2>&1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)${NC}"
    else
      echo -e "    uv:               ${YELLOW}⚠️  not installed${NC}"
    fi

    if check_opencode; then
      echo -e "    opencode:         ${GREEN}✅ $(opencode --version 2>&1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || echo 'installed')${NC}"
    else
      echo -e "    opencode:         ${YELLOW}⚠️  not in PATH${NC}"
    fi

    if check_agent_browser; then
      echo -e "    agent-browser:    ${GREEN}✅ $(agent-browser --version 2>&1 | head -1 || echo 'installed')${NC}"
    else
      echo -e "    agent-browser:    ${YELLOW}⚠️  not installed${NC}"
    fi

    local obscura_path
    obscura_path=$(check_obscura 2>/dev/null || true)
    if [[ -n "$obscura_path" ]]; then
      echo -e "    obscura:          ${GREEN}✅ $obscura_path${NC}"
    else
      echo -e "    obscura:          ${YELLOW}⚠️  not installed${NC}"
    fi

    if [[ -d "$VENV_DIR" ]]; then
      echo -e "    venv:             ${GREEN}✅ $VENV_DIR${NC}"
    else
      echo -e "    venv:             ${RED}❌ not created${NC}"
    fi
  fi
}

print_completion_banner() {
  local shell_name
  shell_name=$(basename "${SHELL:-/bin/bash}")
  local shell_rc="$HOME/.${shell_name}rc"

  echo ""
  echo -e "  ${GREEN}${BOLD}Installation complete! ✅${NC}"
  echo ""
  echo -e "  ${BOLD}Next steps:${NC}"
  echo ""
  echo -e "    ${CYAN}1.${NC} Reload your shell:        ${DIM}source $shell_rc${NC}"
  echo -e "    ${CYAN}2.${NC} Verify installation:       ${DIM}ostwin health${NC}"
  echo -e "    ${CYAN}3.${NC} Set your API key:          ${DIM}nano ${INSTALL_DIR}/.env${NC}"
  echo -e "    ${CYAN}4.${NC} Initialize a project:      ${DIM}ostwin init ~/my-project${NC}"
  echo -e "    ${CYAN}5.${NC} Run your first plan:       ${DIM}ostwin run plans/my-plan.md${NC}"
  echo ""
  echo -e "  ${DIM}Note: API keys in ~/.ostwin/.env are auto-sourced in new terminals.${NC}"
  echo ""
  echo -e "  ${BOLD}Dashboard:${NC}"
  if [[ -n "${TUNNEL_URL:-}" ]]; then
    echo -e "    ${DIM}Local:  http://localhost:${DASHBOARD_PORT}${NC}"
    echo -e "    ${DIM}Public: ${TUNNEL_URL}${NC}"
  else
    echo -e "    ${DIM}Dashboard running at http://localhost:${DASHBOARD_PORT}${NC}"
  fi
  echo -e "    ${DIM}Stop with: ostwin stop${NC}"
  if ${START_CHANNEL:-false}; then
    echo -e ""
    echo -e "  ${BOLD}Channels (Telegram + Discord + Slack):${NC}"
    echo -e "    ${DIM}Running in background — log: $INSTALL_DIR/logs/channel.log${NC}"
    echo -e "    ${DIM}Stop with: ostwin channel stop${NC}"
  fi
  echo ""

  # Display OSTWIN_API_KEY for frontend authentication
  local api_key="${OSTWIN_API_KEY:-}"
  if [[ -z "$api_key" ]]; then
    # Try reading from .env
    api_key=$(grep -E '^OSTWIN_API_KEY=' "${INSTALL_DIR}/.env" 2>/dev/null | cut -d'=' -f2-)
  fi
  if [[ -n "$api_key" ]]; then
    echo -e "  ${BOLD}🔑 Dashboard Authentication Key:${NC}"
    echo ""
    echo -e "    ${YELLOW}${BOLD}${api_key}${NC}"
    echo ""
    echo -e "    ${DIM}Use this key to authenticate with the dashboard frontend.${NC}"
    echo -e "    ${DIM}The frontend will prompt you to enter this key on first visit.${NC}"
    echo -e "    ${DIM}Stored in: ${INSTALL_DIR}/.env${NC}"
    echo ""
  fi
}
