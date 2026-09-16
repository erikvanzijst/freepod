FROM ghcr.io/astral-sh/uv:0.12.9 AS uv

FROM node:24.20.0-bookworm-slim

ARG GH_VERSION=2.100.0
ARG GH_SHA256=e4d4bb4498e8d007abe545b6568926793ace1b6447da598294a610018cb164be
ARG HELM_VERSION=4.1.1
ARG HELM_SHA256=5d4c7623283e6dfb1971957f4b755468ab64917066a8567dd50464af298f4031
ARG PI_VERSION=0.85.1
ARG PYTHON_VERSION=3.12.14

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates \
      curl=7.88.1-10+deb12u15 \
      git=1:2.39.5-0+deb12u3 \
      jq=1.6-2.1+deb12u2 \
      tini=0.19.0-1+b3 \
      htop \
      procps \
 && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL -o /tmp/gh.tar.gz "https://github.com/cli/cli/releases/download/v${GH_VERSION}/gh_${GH_VERSION}_linux_amd64.tar.gz" \
 && echo "${GH_SHA256}  /tmp/gh.tar.gz" | sha256sum -c - \
 && tar -xzf /tmp/gh.tar.gz -C /tmp \
 && install -m 0755 "/tmp/gh_${GH_VERSION}_linux_amd64/bin/gh" /usr/bin/gh \
 && curl -fsSL -o /tmp/helm.tar.gz "https://get.helm.sh/helm-v${HELM_VERSION}-linux-amd64.tar.gz" \
 && echo "${HELM_SHA256}  /tmp/helm.tar.gz" | sha256sum -c - \
 && tar -xzf /tmp/helm.tar.gz -C /tmp \
 && install -m 0755 /tmp/linux-amd64/helm /usr/local/bin/helm \
 && rm -rf /tmp/gh* /tmp/helm.tar.gz /tmp/linux-amd64

RUN npm install -g "@earendil-works/pi-coding-agent@${PI_VERSION}" && npm cache clean --force

COPY --from=uv /uv /uvx /usr/local/bin/
ENV UV_PYTHON_INSTALL_DIR=/opt/python \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN UV_PYTHON_DOWNLOADS=automatic uv python install "${PYTHON_VERSION}" \
 && uv sync --frozen --no-dev --no-install-project --python "${PYTHON_VERSION}"
COPY . .
RUN uv sync --frozen --no-dev --python "${PYTHON_VERSION}"

# product-upgrade-guardrails: every clone gets the push hook and the token helper. The bot's
# identity is added at run time, and git locks a config file by creating one beside it, so the
# system config lives in a directory the service user owns.
ENV GIT_CONFIG_SYSTEM=/etc/upgrader/gitconfig
RUN mkdir /etc/upgrader \
 && git config --system core.hooksPath /app/hooks \
 && git config --system credential.helper /app/bin/git-credential-upgrader \
 && chown -R node:node /etc/upgrader

USER node
ENV PATH=/app/.venv/bin:$PATH \
    UV_PYTHON_DOWNLOADS=automatic

# -s: in a pod whose containers share one process namespace, tini is not PID 1, so it registers as
# a subreaper to still collect what a terminated session leaves behind (D1).
ENTRYPOINT ["/usr/bin/tini", "-s", "--"]
CMD ["bash", "-c", "alembic upgrade head && exec uvicorn --factory upgrader.web:build --host 0.0.0.0 --port \"${PORT:-8080}\" --workers 1"]
