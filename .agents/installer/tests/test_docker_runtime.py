from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_docker_build_skips_runtime_service_startup():
    dockerfile = (ROOT / "Dockerfile").read_text()

    assert "RUN bash .agents/install.sh --yes --dir /root/.ostwin --no-start" in dockerfile


def test_docker_cmd_uses_runtime_entrypoint():
    dockerfile = (ROOT / "Dockerfile").read_text()

    assert 'CMD ["bash", ".agents/docker-entrypoint.sh"]' in dockerfile


def test_docker_frontend_uses_committed_pnpm_lockfile():
    dockerfile = (ROOT / "Dockerfile").read_text()

    assert "dashboard/fe/pnpm-lock.yaml" in dockerfile
    assert "pnpm install --frozen-lockfile" in dockerfile
    assert "pnpm run build" in dockerfile


def test_runtime_entrypoint_starts_and_supervises_services():
    entrypoint = (ROOT / ".agents" / "docker-entrypoint.sh").read_text()

    assert "opencode serve" in entrypoint
    assert "uvicorn dashboard.api:app" in entrypoint
    assert "wait -n" in entrypoint
