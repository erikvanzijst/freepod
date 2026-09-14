#!/bin/bash
#
# Mirror the Railpack base images, and the Dockerfile frontend, into an
# environment's tenant registry.
#
# Every build pulls these before it runs a line of the tenant's own code, and
# the pod's BuildKit state is an emptyDir, so nothing about that pull is ever
# reused. Measured on a 62s build: ~9s transferring the 225 MB builder base
# from ghcr.io and ~10s extracting it. Serving it from the in-cluster registry
# instead reclaims the transfer and takes ghcr.io off the critical path of
# every build.
#
# The builder image configures its ephemeral buildkitd to treat the registry as
# a mirror for ghcr.io (see `buildkitd_config` in
# products/custom/builder/build.py). BuildKit asks a mirror for the *same*
# repository path, which is why these land at `railwayapp/...` rather than
# under a prefix of our own.
#
# Running this is repeatable. A mirror that lacks a Railpack image is not an
# error — BuildKit falls through to ghcr.io — but the Dockerfile frontend has
# no such fallback, so a new registry needs this before its first Dockerfile
# build.
#
# The registry is reachable only from inside the cluster and authorizes every
# write, so nothing here talks to it from this machine: the token comes from
# `caelus registry-token` in the environment's build worker, which holds the
# signing key, and `crane` runs in a throwaway pod with that token as its only
# credential (authenticated-tenant-registry D19).
#
# Usage:
#   ./scripts/mirror-railpack-images.sh dev
#   ./scripts/mirror-railpack-images.sh prod
#   ./scripts/mirror-railpack-images.sh --help

set -euo pipefail

# These three are part of the version-matched set described in
# products/custom/builder/README.md, and must move with `RAILPACK_VERSION` in
# that directory's Dockerfile.
#
# FRONTEND_DIGEST duplicates `FRONTEND_IMAGE` in build.py; a test in
# api/tests/test_builder_script.py fails if the two ever disagree.
#
# MISE_TAG is chosen by Railpack itself rather than by us, so it is not
# recorded anywhere else in this repo. To find the current one, run a build and
# read the images out of its log:
#
#   kubectl logs -n caelus-builds <build pod> | grep -o 'docker-image://[^ ]*' | sort -u
RAILPACK_VERSION=0.36.4
FRONTEND_DIGEST=sha256:282e3d0e542c9299c9fc4f938c9a5c45f0666d954264deaea59d13281121a91a
MISE_TAG=mise-2026.8.4

# The Dockerfile frontend, for builds that use the project's own Dockerfile.
# Not part of the Railpack set and on its own cadence, but mirrored by the same
# script because it is the same job: an image every build needs before it runs
# any tenant code.
#
# DOCKERFILE_FRONTEND_DIGEST duplicates `DOCKERFILE_FRONTEND_DIGEST` in
# build.py; the same test that guards FRONTEND_DIGEST fails if they disagree.
DOCKERFILE_FRONTEND_TAG=1
DOCKERFILE_FRONTEND_DIGEST=sha256:ecfaec9ed6d810b56388c508f4121597bfbba70d41a6dfeee4d8cad5f295fc32

# `crane copy` retains the source digest, which the frontend requires: build.py
# names it by digest, so a re-serialized manifest would be a different image
# and the mirror would simply never be hit. Copying the *tag* rather than the
# digest gets both — the digest resolves, and the manifest stays tagged, out of
# reach of a `registry garbage-collect --delete-untagged` pass.
#
# The debug variant, because we need a shell
CRANE_IMAGE=gcr.io/go-containerregistry/crane/debug:v0.22.1

usage() {
  cat <<'EOF'
Usage: ./scripts/mirror-railpack-images.sh dev|prod

Copies the Railpack frontend, builder and runtime images from ghcr.io, and the
Dockerfile frontend from Docker Hub, into that environment's tenant registry,
preserving digests.

Requires kubectl pointed at the cluster.
EOF
}

case "${1:-}" in
  dev)  NAMESPACE=caelus-dev REGISTRY=cr.dev.freepod.eu ;;
  prod) NAMESPACE=caelus REGISTRY=cr.freepod.eu ;;
  --help | -h)
    usage
    exit 0
    ;;
  *)
    usage >&2
    exit 1
    ;;
esac

IMAGES=(
  "railwayapp/railpack-frontend:v${RAILPACK_VERSION}"
  "railwayapp/railpack-builder:${MISE_TAG}"
  "railwayapp/railpack-runtime:${MISE_TAG}"
)

echo "Minting a mirror token in ${NAMESPACE}"
token=$(kubectl -n "$NAMESPACE" exec deploy/caelus-build-worker -c build-worker -- \
  caelus registry-token --ttl-seconds 900 \
  --push railwayapp/railpack-frontend \
  --push railwayapp/railpack-builder \
  --push railwayapp/railpack-runtime \
  --push docker/dockerfile)

echo "Mirroring Railpack v${RAILPACK_VERSION} base images into ${REGISTRY}"

# Fed through stdin so the token never appears in the pod spec.
output=$(kubectl -n "$NAMESPACE" run "mirror-railpack-$$" --rm -i --restart=Never --quiet \
  --image="$CRANE_IMAGE" --command -- /busybox/sh -s <<EOF | tee /dev/stderr
set -eu
export PATH=/ko-app:/busybox:\$PATH DOCKER_CONFIG=/tmp/.docker
mkdir -p \$DOCKER_CONFIG
printf '{"auths":{"%s":{"registrytoken":"%s"}}}' '${REGISTRY}' '${token}' > \$DOCKER_CONFIG/config.json

for image in ${IMAGES[*]}; do
  echo "  ghcr.io/\$image  ->  ${REGISTRY}/\$image"
  crane copy "ghcr.io/\$image" "${REGISTRY}/\$image"
done

echo "  docker/dockerfile:${DOCKERFILE_FRONTEND_TAG}  ->  ${REGISTRY}/docker/dockerfile"
crane copy "docker/dockerfile:${DOCKERFILE_FRONTEND_TAG}" "${REGISTRY}/docker/dockerfile:${DOCKERFILE_FRONTEND_TAG}"

echo MIRROR_OK
EOF
)

if ! grep -qx MIRROR_OK <<<"$output"; then
  echo "ERROR: mirroring into ${REGISTRY} did not complete" >&2
  exit 1
fi
echo "Done. $(( ${#IMAGES[@]} + 1 )) images mirrored into ${REGISTRY}."
