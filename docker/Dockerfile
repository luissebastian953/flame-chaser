# Curio dev container: dawnmaker (engine + daemon) and the Vue webview served
# by Vite, in one image. This is the browser-mode stack -- the Tauri window
# itself can't run in Docker (it needs the host's WebKit and a display).
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    REAVER_HOME=/data \
    COREPACK_ENABLE_DOWNLOAD_PROMPT=0 PNPM_HOME=/pnpm PATH=/pnpm:$PATH

# Node 22 (Vite 8 needs >= 22.12); Debian's own node is too old.
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates gnupg \
 && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
 && apt-get install -y --no-install-recommends nodejs \
 && apt-get purge -y gnupg && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Engine: editable install so a Python edit on the host is live in the
# container. Source is bind-mounted at the same path at run time.
COPY reaver/pyproject.toml reaver/README.md /app/reaver/
COPY reaver/coreflame /app/reaver/coreflame
COPY reaver/dawnmaker /app/reaver/dawnmaker
RUN pip install -e "/app/reaver[daemon,dev]"

# pnpm workspace: root tooling + deliverer/. node_modules dirs live in
# container-only volumes (see compose) so the host's macOS native binaries
# never leak in. corepack pins the pnpm version from package.json.
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml /app/
COPY deliverer/package.json /app/deliverer/
RUN corepack enable && corepack prepare --activate && pnpm install --frozen-lockfile

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 5173 8765
ENTRYPOINT ["/entrypoint.sh"]
