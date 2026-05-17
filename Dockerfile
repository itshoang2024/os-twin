# Use a pinned stable image (Bookworm) to avoid "Testing" distribution (Trixie) policy changes
FROM python:3.11-slim-bookworm

# Force the installer to use /root/.ostwin instead of assuming $HOME
ENV OSTWIN_HOME=/root/.ostwin
ENV PATH="/root/.local/bin:/root/.cargo/bin:/root/.ostwin/.venv/bin:/root/.ostwin/.agents/bin:$PATH"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV OPENCODE_BASE_URL=http://127.0.0.1:4096
ENV LARK_WEBHOOK_URL ""

# Set the working directory
WORKDIR /app

# 1. Install System Dependencies
# Includes nodejs 20.x and PowerShell 7.4.x
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    curl \
    git \
    rsync \
    wget \
    ca-certificates \
    build-essential \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get update \
    && apt-get install -y nodejs \
    # Install PowerShell directly from Microsoft (Stable)
    && wget -q -O /tmp/powershell.deb https://github.com/PowerShell/PowerShell/releases/download/v7.4.2/powershell_7.4.2-1.deb_amd64.deb \
    && apt-get install -y --no-install-recommends /tmp/powershell.deb \
    && rm -f /tmp/powershell.deb \
    && rm -rf /var/lib/apt/lists/*

# 2. Install OpenCode CLI
RUN curl -fsSL https://opencode.ai/install | bash

# 3. Setup OSTwin Home & Virtual Environment
RUN mkdir -p /root/.ostwin \
    && python -m venv /root/.ostwin/.venv

# 4. Cache Heavy Python Dependencies (Torch CPU)
# Explicitly installing CPU version saves 1.5GB of image size and download time
RUN /root/.ostwin/.venv/bin/pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# 5. Install Python dependencies via uv sync against pyproject.toml + uv.lock.
# This replaces the previous requirements.txt approach, which was removed when
# the dashboard moved to uv-managed locked installs.
RUN /root/.ostwin/.venv/bin/pip install --no-cache-dir uv
COPY dashboard/pyproject.toml dashboard/uv.lock /app/dashboard/
RUN TMPDIR=/tmp UV_PROJECT_ENVIRONMENT=/root/.ostwin/.venv \
    /root/.ostwin/.venv/bin/uv sync \
        --project /app/dashboard \
        --no-install-project --frozen --all-extras \
        --extra-index-url https://download.pytorch.org/whl/cpu \
        --index-strategy unsafe-best-match \
        --prerelease=allow

# 6. Cache Node Dependencies (Frontend)
RUN npm install -g pnpm@10.26.0
COPY dashboard/fe/package.json dashboard/fe/pnpm-lock.yaml /app/dashboard/fe/
RUN cd /app/dashboard/fe && pnpm install --frozen-lockfile

# 7. Build Frontend
COPY dashboard/fe /app/dashboard/fe
RUN cd /app/dashboard/fe && pnpm run build

# 8. Copy remaining source
COPY . /app

# 9. Run Installer (Full install to enable agent orchestration)
# Build-time installs files/deps/config only. Runtime services are supervised
# by .agents/docker-entrypoint.sh so OpenCode is alive in the final container.
RUN bash .agents/install.sh --yes --dir /root/.ostwin --no-start

# Expose the default port (Cloud Run will override this via $PORT)
EXPOSE 3366

# Start OpenCode and the dashboard together at container runtime.
# Respect the PORT environment variable injected by Cloud Run.
CMD ["bash", ".agents/docker-entrypoint.sh"]
