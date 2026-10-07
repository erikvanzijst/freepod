# Builder image for the `custom` product's build subsystem.
#
# One of these runs per build, as a Kubernetes Job in that environment's builds
# namespace (`caelus-builds` in prod, `caelus-builds-dev` in dev), and it
# executes **tenant-supplied code**: a project's dependency
# install hooks and build commands run inside it. It therefore holds no
# database, Kubernetes, or long-lived registry credential — only a presigned,
# expiring URL for the one artifact it is meant to build. It reports its result
# through the pod's termination message rather than by writing anywhere.
#
# Rootless BuildKit runs *inside this pod*, not as a shared daemon. Rootless
# BuildKit under Kubernetes requires `--oci-worker-no-process-sandbox`, whose
# documented consequence is that build containers can kill and potentially
# trace processes in the daemon's namespace. With a per-build daemon the only
# processes in reach belong to that tenant's own build — same flag, completely
# different blast radius.
#
# Build and publish: see README.md in this directory.
FROM moby/buildkit:v0.33.1-rootless

# Version-matched pair. The build plan `railpack prepare` emits is a contract
# between this binary and the frontend image pinned in build.py: the two must
# move together or a plan will be handed to a frontend that cannot read it.
# `ghcr.io/railwayapp/railpack-frontend:v0.36.4` resolves to the digest pinned
# there.
ARG RAILPACK_VERSION=0.36.4
ARG RAILPACK_SHA256=ed75f99fdd3ce10ea7a60128b4ac28788ad33bb93f339fada70d60ddcbf604e8

USER root

RUN set -eu; \
    # The cluster node is amd64 and multi-arch builds are an explicit non-goal.
    # Fail here rather than shipping an image whose railpack binary cannot exec:
    # `FROM moby/buildkit` is multi-arch, so building this on an arm64 machine
    # without `--platform linux/amd64` would otherwise produce exactly that.
    if [ "$(uname -m)" != "x86_64" ]; then \
        echo "ERROR: this image is amd64-only; rebuild with --platform linux/amd64" >&2; \
        exit 1; \
    fi; \
    # python3 is here for one reason: extracting an untrusted archive. Busybox
    # tar can neither reject traversal reliably nor bound expansion, and
    # Python's tarfile "data" filter is purpose-built for exactly this.
    #
    # This is a busybox image without bash, so pull it in explicitly.
    apk add --no-cache python3 bash; \
    wget -qO /tmp/railpack.tar.gz \
        "https://github.com/railwayapp/railpack/releases/download/v${RAILPACK_VERSION}/railpack-v${RAILPACK_VERSION}-x86_64-unknown-linux-musl.tar.gz"; \
    echo "${RAILPACK_SHA256}  /tmp/railpack.tar.gz" | sha256sum -c -; \
    tar -xzf /tmp/railpack.tar.gz -C /usr/local/bin railpack; \
    rm -f /tmp/railpack.tar.gz; \
    chmod 0755 /usr/local/bin/railpack; \
    railpack --version; \
    # The Job mounts an emptyDir over this; create it so the image also runs
    # standalone for a smoke test.
    mkdir -p /home/user/work; \
    chown 1000:1000 /home/user/work

COPY --chmod=0755 build.py /usr/local/bin/build.py

USER 1000:1000

# Rootless BuildKit under Kubernetes cannot use the process sandbox; without
# this the daemon fails to start. `buildctl-daemonless.sh` forwards
# BUILDKITD_FLAGS to the ephemeral daemon it spawns.
ENV BUILDKITD_FLAGS="--oci-worker-no-process-sandbox"

# The build's output is stored verbatim and replayed to users, so what this
# container emits must be plain readable text. `--progress=plain` on buildctl
# (in build.py) is what actually earns that; these two are belt-and-braces,
# since railpack and buildctl already suppress styling on a non-TTY.
#
# They do NOT reach the tenant's build steps: BuildKit executes those in
# containers of its own, with the environment coming from the build plan, not
# from this process. Tenant build output can therefore contain anything —
# verified: dpkg inside a real build emits bare CR progress redraws. That is
# stored faithfully rather than sanitized, which is part of why the log column
# is bytes.
ENV NO_COLOR=1 \
    TERM=dumb \
    PYTHONUNBUFFERED=1

WORKDIR /home/user/work

# Overrides the base image's `rootlesskit buildkitd` entrypoint: this container
# is a one-shot build, not a daemon. build.py spawns its own ephemeral daemon
# via buildctl-daemonless.sh and exits when the build is done.
ENTRYPOINT ["/usr/local/bin/build.py"]
