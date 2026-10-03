FROM bitnami/kubectl AS kubectl
FROM alpine:3.22 AS helm
# Keep in sync with .devcontainer/Dockerfile. Official release, pinned and checksummed:
# d3fk/helm only publishes `latest`, and helm v4.2.2 drops trailing newlines
# from post-rendered block scalars.
ARG HELM_VERSION=v4.3.0
ARG HELM_SHA256=86584a54def73570558f66f5111cc53dfed56689637ae32c1201205d494f54fb
RUN wget -qO /tmp/helm.tgz "https://get.helm.sh/helm-${HELM_VERSION}-linux-amd64.tar.gz" && \
    echo "${HELM_SHA256}  /tmp/helm.tgz" | sha256sum -c - && \
    tar -xzf /tmp/helm.tgz -C /tmp && mv /tmp/linux-amd64/helm /helm

FROM python:3.13-slim
COPY --from=kubectl /opt/bitnami/kubectl/bin/kubectl /usr/local/bin/kubectl
COPY --from=helm /helm /usr/local/bin/helm

RUN apt-get update -y && \
    apt-get install -y --no-install-recommends postgresql-client procps

RUN pip install uv

RUN mkdir /app
WORKDIR /app

COPY api/ .
RUN uv sync --no-dev --frozen
RUN uv pip install . --no-deps

COPY products/catalog/ /app/products/catalog/
ENV CAELUS_CATALOG_DIR=/app/products/catalog

EXPOSE 8000

ARG GIT_COMMIT=unknown
ENV GIT_COMMIT=${GIT_COMMIT}
ENV PATH="/app/.venv/bin:$PATH"
ENV HELM_PLUGINS=/app/helm-plugins

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
