from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_docker_build_skips_runtime_service_startup():
    dockerfile = (ROOT / "Dockerfile").read_text()

    assert "RUN bash .agents/install.sh --yes --dir /root/.ostwin --no-start" in dockerfile


def test_docker_cmd_uses_runtime_entrypoint():
    dockerfile = (ROOT / "Dockerfile").read_text()

    assert 'CMD ["bash", ".agents/docker-entrypoint.sh"]' in dockerfile


def test_docker_frontend_uses_committed_bun_lockfile():
    dockerfile = (ROOT / "Dockerfile").read_text()

    assert "/root/.bun/bin" in dockerfile
    assert "curl -fsSL https://bun.com/install | bash" in dockerfile
    assert "dashboard/fe/bun.lock" in dockerfile
    assert "bun install --frozen-lockfile" in dockerfile
    assert "bun run build" in dockerfile
    assert "pnpm install" not in dockerfile


def test_runtime_entrypoint_starts_and_supervises_services():
    entrypoint = (ROOT / ".agents" / "docker-entrypoint.sh").read_text()

    assert "opencode serve" in entrypoint
    assert "OPENCODE_DISABLE_CLAUDE_CODE=1" in entrypoint
    assert "uvicorn dashboard.api:app" in entrypoint
    assert "wait -n" in entrypoint


def test_runtime_entrypoint_loads_project_env_before_services():
    entrypoint = (ROOT / ".agents" / "docker-entrypoint.sh").read_text()

    assert 'load_env_defaults "$INSTALL_DIR/.env"' in entrypoint
    assert 'load_env_defaults "$APP_DIR/.env"' in entrypoint
    assert 'load_env_defaults "$APP_DIR/.agents/.env"' in entrypoint
    assert 'source_env_hook "$INSTALL_DIR/.env.sh"' in entrypoint
    assert 'PROJECT_DIR="${OSTWIN_PROJECT_DIR:-$APP_DIR}"' in entrypoint
    assert 'cd "$PROJECT_DIR"' in entrypoint
