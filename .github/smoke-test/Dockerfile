FROM mcr.microsoft.com/powershell:7.4-ubuntu-22.04

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates python3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace
COPY .agents /workspace/.agents
COPY .github/smoke-test/worktree-two-epics.ps1 /workspace/.github/smoke-test/worktree-two-epics.ps1

CMD ["pwsh", "-NoProfile", "-File", ".github/smoke-test/worktree-two-epics.ps1"]
