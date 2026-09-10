#!/bin/bash
#
# Mirror the Railpack base images into the internal registry.
#
# Every build pulls these before it runs a line of the tenant's own code, and
# the pod's BuildKit state is an emptyDir, so nothing about that pull is ever
# reused. Measured on a 62s build: ~9s transferring the 225 MB builder base
# from ghcr.io and ~10s extracting it. Serving it from the LAN registry instead
# reclaims the transfer (110 MB/s measured, against ~25 MB/s from ghcr) and
# takes ghcr.io off the critical path of every build.
#
# The builder image configures its ephemeral buildkitd to treat the internal
# registry as a mirror for ghcr.io (see `buildkitd_config` in
# products/custom/builder/build.py). BuildKit asks a mirror for the *same*
# repository path, which is why these land at `railwayapp/...` rather than
# under a prefix of our own.
#
# Running this is optional and repeatable. A mirror that lacks an image is not
# an error — BuildKit falls through to ghcr.io — so builds keep working before
# this has ever run, and keep working at the old speed after a Railpack bump
# whose new base images have not been mirrored yet.
#
# Usage:
#   ./scripts/mirror-railpack-images.sh              # mirror into registry.home
#   ./scripts/mirror-railpack-images.sh my.registry  # mirror somewhere else
#   ./scripts/mirror-railpack-images.sh --help

set -euo pipefail

DEFAULT_REGISTRY=registry.home

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
CRANE_IMAGE=gcr.io/go-containerregistry/crane:latest

usage() {
  cat <<'EOF'
Usage: ./scripts/mirror-railpack-images.sh [REGISTRY]

Copies the Railpack frontend, builder and runtime images from ghcr.io into
REGISTRY (default: registry.home), preserving digests.

Requires docker, and network reach to both ghcr.io and the target registry.
EOF
}

case "${1:-}" in
  --help | -h)
    usage
    exit 0
    ;;
esac

REGISTRY="${1:-$DEFAULT_REGISTRY}"

IMAGES=(
  "railwayapp/railpack-frontend:v${RAILPACK_VERSION}"
  "railwayapp/railpack-builder:${MISE_TAG}"
  "railwayapp/railpack-runtime:${MISE_TAG}"
)

crane() {
  # --insecure: the internal registry presents a certificate for a name it is
  # not addressed by, the same reason build.py passes `registry.insecure=true`.
  docker run --rm "$CRANE_IMAGE" --insecure "$@"
}

echo "Mirroring Railpack v${RAILPACK_VERSION} base images into ${REGISTRY}"

for image in "${IMAGES[@]}"; do
  echo "  ghcr.io/${image}  ->  ${REGISTRY}/${image}"
  crane copy "ghcr.io/${image}" "${REGISTRY}/${image}"
done

# The frontend is the one image build.py names by digest, so a mirror serving
# anything else there is not slow, it is invisible: BuildKit would ask for a
# digest the mirror does not have and fall through to ghcr.io on every build.
# Check it rather than assume it.
echo "Verifying the mirrored frontend digest"
mirrored=$(crane digest "${REGISTRY}/railwayapp/railpack-frontend:v${RAILPACK_VERSION}")
if [ "$mirrored" != "$FRONTEND_DIGEST" ]; then
  echo "ERROR: mirrored frontend is ${mirrored}, expected ${FRONTEND_DIGEST}" >&2
  echo "       builds will silently keep pulling the frontend from ghcr.io." >&2
  exit 1
fi

echo "  docker/dockerfile:${DOCKERFILE_FRONTEND_TAG}  ->  ${REGISTRY}/docker/dockerfile"
crane copy "docker/dockerfile:${DOCKERFILE_FRONTEND_TAG}" "${REGISTRY}/docker/dockerfile:${DOCKERFILE_FRONTEND_TAG}"

# This one has no upstream to fall through to: build.py addresses it at this
# registry by digest, so a mismatch is a broken Dockerfile build rather than a
# slow one.
echo "Verifying the mirrored Dockerfile frontend digest"
mirrored=$(crane digest "${REGISTRY}/docker/dockerfile:${DOCKERFILE_FRONTEND_TAG}")
if [ "$mirrored" != "$DOCKERFILE_FRONTEND_DIGEST" ]; then
  echo "ERROR: mirrored Dockerfile frontend is ${mirrored}, expected ${DOCKERFILE_FRONTEND_DIGEST}" >&2
  echo "       every Dockerfile build will fail to resolve its frontend." >&2
  exit 1
fi

echo "Done. $(( ${#IMAGES[@]} + 1 )) images mirrored; both frontend digests match build.py."
