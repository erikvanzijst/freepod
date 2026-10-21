# App Studio: opencode's server and web UI over a persistent /workspace, with the
# toolchains and the `freepod` CLI an agent needs to build and ship apps.
#
# The CLI is installed from this repository's cli/, passed as a named build
# context: --build-context freepod-cli=cli (see ../README.md).
FROM node:24-bookworm

ARG OPENCODE_VERSION=2.1.2
ARG YQ_VERSION=v4.54.1
ARG YQ_SHA256=8e34fc298390875de416e6a4afcb8cabeceb25d9aa8506c1a2f9353cf702ea5f

# PGDG, for a client matching the tenant database's major version (18); a
# bookworm pg_dump (15) refuses newer servers. The server is for local
# development and is not started; `dev-postgres` starts it.
RUN install -d /usr/share/postgresql-common/pgdg \
 && curl -fsSLo /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc https://www.postgresql.org/media/keys/ACCC4CF8.asc \
 && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
      > /etc/apt/sources.list.d/pgdg.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends \
      python3 python3-venv python3-pip python-is-python3 \
      postgresql-18 postgresql-client-18 openssh-client \
      ripgrep fd-find jq less tini vim bash-completion psmisc \
 && rm -rf /var/lib/apt/lists/* \
 && printf '%s\n' '' \
      '# App Studio: tab completion (git, apt, ...) in the studio terminal.' \
      'if ! shopt -oq posix && [ -f /usr/share/bash-completion/bash_completion ]; then' \
      '  . /usr/share/bash-completion/bash_completion' \
      'fi' >> /etc/bash.bashrc
COPY vimrc.local /etc/vim/vimrc.local
ENV PATH=/usr/lib/postgresql/18/bin:$PATH

# mikefarah/yq; Debian's `yq` package is a different tool.
RUN curl -fsSLo /usr/local/bin/yq https://github.com/mikefarah/yq/releases/download/${YQ_VERSION}/yq_linux_amd64 \
 && echo "${YQ_SHA256}  /usr/local/bin/yq" | sha256sum -c - \
 && chmod +x /usr/local/bin/yq

COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /uvx /usr/local/bin/

# Local S3 on the same Garage version as Freepod's object storage, started by
# `dev-s3`.
COPY --from=dxflrs/garage:v2.3.0 /garage /usr/local/bin/garage
COPY garage.toml /etc/garage.toml
COPY bin/dev-s3 bin/dev-postgres bin/dev-app /usr/local/bin/
ENV UV_TOOL_DIR=/opt/uv/tools \
    UV_TOOL_BIN_DIR=/usr/local/bin

RUN npm install -g @opencode/cli@${OPENCODE_VERSION} \
 && npm cache clean --force

# Playwright's MCP server, for the agent to open and inspect the app in a
# headless browser; opencode starts it (`mcp` in opencode.json). The browser is
# the one this exact version expects, installed with its own command.
ARG PLAYWRIGHT_MCP_VERSION=0.0.83
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright
RUN npm install -g @playwright/mcp@${PLAYWRIGHT_MCP_VERSION} \
 && /usr/local/lib/node_modules/@playwright/mcp/node_modules/.bin/playwright install-deps chromium \
 && playwright-mcp install-browser chrome-for-testing \
 && rm -rf /var/lib/apt/lists/* \
 && npm cache clean --force

COPY --from=freepod-cli pyproject.toml README.md LICENSE /tmp/freepod-cli/
COPY --from=freepod-cli src /tmp/freepod-cli/src
RUN uv tool install /tmp/freepod-cli \
 && rm -rf /tmp/freepod-cli

# User configuration (opencode's, freepod's credentials and keys, git's) lives
# on the workspace volume. Settings the platform owns are opencode's managed
# config, which overrides the user's.
ENV XDG_CONFIG_HOME=/workspace/.config
COPY opencode.json /etc/opencode/opencode.json
COPY bin/appstudio-start bin/appstudio-new-app bin/appstudio-app bin/appstudio-reaper /usr/local/bin/
# The starter every app is copied from, and a reference app built on it; the
# agent's instructions point at both. Neither is copied into the project, so
# nothing appears in the preview before the user asks for an app.
COPY template /opt/appstudio/template
COPY examples /opt/appstudio/examples
# The agent's instructions, loaded through opencode.json's `instructions`.
COPY AGENTS.md /opt/appstudio/AGENTS.md

WORKDIR /workspace
ENTRYPOINT ["tini", "--"]
# Listens on $STUDIO_PORT, not $PORT: everything the agent runs would inherit
# it, and apps it builds for Freepod bind $PORT (8080 there).
CMD ["appstudio-start"]
