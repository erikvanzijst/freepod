#!/bin/bash
#
# Build and push production container images to ghcr.io
#
# Usage:
#   ./scripts/build-images.sh               # Builds both images with git SHA tag
#   ./scripts/build-images.sh v1.2.3        # Builds both images with custom tag
#   ./scripts/build-images.sh --api          # Build only API image (tag = git SHA)
#   ./scripts/build-images.sh --ui           # Build only UI image (tag = git SHA)
#   ./scripts/build-images.sh --keycloak     # Build only Keycloak image (Freepod theme)
#   ./scripts/build-images.sh --ssh-sidecar   # Build only the dev-profile SSH sidecar
#   ./scripts/build-images.sh --ssh-resolver  # Build only the SSH auth resolver
#   ./scripts/build-images.sh --builder       # Build only the tenant build image
#   ./scripts/build-images.sh v1.2.3 --api   # Build only API image with custom tag
#   ./scripts/build-images.sh v1.2.3 --ui    # Build only UI image with custom tag
#   ./scripts/build-images.sh --help         # Show this help message
#
# Note: the Keycloak image (deps) is not part of the default "both" build; it
# rarely changes and is built explicitly with --keycloak.
#
# The SSH sidecar is not part of "both" or "all" either, and for a stronger
# reason. The images above are platform Deployments on moving tags: they are
# re-pushed to :latest / :<branch> and picked up by ./scripts/rollout.sh
# restarting the pods. The sidecar runs in *tenant* pods, one per deployment,
# which rollout.sh knows nothing about; it reaches them through a chart version
# bump fanned out by the reconciler. So it takes an immutable version tag from
# products/_lib/ssh-sidecar-image/VERSION, is never re-pushed, and building it is a
# deliberate act after that file has been bumped -- which is also why folding it
# into --all would fail every build that did not bump it. CI publishes it with
# --skip-if-published instead, so a push lands exactly when VERSION names a
# version the registry does not already hold.
#
# The SSH auth resolver is on the same footing and for a related reason. It runs
# as a sidecar in the SSH edge's pod, on the authentication path of every SSH
# connection, and must not roll because the API rolled: it takes its version from
# ssh-auth/VERSION, is never re-pushed, and reaches the cluster only when
# Terraform names a new version.
#
# The tenant build image is the third of these. It is not a Deployment at all --
# the build worker names it in each build Job it creates -- so a moving tag would
# change what runs tenant code without anything having been rolled out. Version
# in products/custom/builder/VERSION, never re-pushed, reaching builds only when
# Terraform names a new version.

set -euo pipefail

REGISTRY=ghcr.io/$(gh repo view --json nameWithOwner -q .nameWithOwner)

# Function to display help
usage() {
  cat <<'EOF'
Usage: ./scripts/build-images.sh [TAG] [--api|--ui|--keycloak|--ssh-sidecar|--ssh-resolver|--builder|--all|--help]

If TAG is not provided, the current git SHA will be used.

Options:
  --api           Build only the API image.
  --ui            Build only the UI image.
  --keycloak      Build only the Keycloak image (Freepod theme baked in).
  --ssh-sidecar   Build only the dev-profile SSH sidecar. Ignores TAG: its
                  version comes from products/_lib/ssh-sidecar-image/VERSION and an
                  already-published version is refused rather than overwritten.
  --ssh-resolver  Build only the SSH auth resolver. Ignores TAG: its version
                  comes from ssh-auth/VERSION and an already-published version
                  is refused rather than overwritten.
  --builder       Build only the tenant build image. Ignores TAG: its version
                  comes from products/custom/builder/VERSION and an already-
                  published version is refused rather than overwritten.
  --skip-if-published
                  With --ssh-sidecar, --ssh-resolver or --builder, treat an
                  already-published version as nothing to do rather than an
                  error. This is what makes the publish safe to run on every
                  merge: it pushes exactly when VERSION is new. Run by hand
                  without it, so that a version you believed you had bumped
                  fails loudly.
  --all           Build all images on moving tags (API, UI, Keycloak).
  --help          Show this help message and exit.
EOF
}

# Parse arguments
TAG=""
TARGET="both"  # possible values: both, api, ui, keycloak, ssh-sidecar, ssh-resolver, builder, all
SKIP_IF_PUBLISHED=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --api)
      TARGET="api"
      shift
      ;;
    --ui)
      TARGET="ui"
      shift
      ;;
    --keycloak)
      TARGET="keycloak"
      shift
      ;;
    --ssh-sidecar)
      TARGET="ssh-sidecar"
      shift
      ;;
    --ssh-resolver)
      TARGET="ssh-resolver"
      shift
      ;;
    --builder)
      TARGET="builder"
      shift
      ;;
    --skip-if-published)
      SKIP_IF_PUBLISHED=true
      shift
      ;;
    --all)
      TARGET="all"
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      if [ -z "$TAG" ]; then
        TAG="$1"
        shift
      else
        echo "Unexpected argument: $1"
        exit 1
      fi
      ;;
  esac
done

# Only the immutably-tagged images can be already-published, so anywhere else
# this flag would silently do nothing -- which is how a publish everyone
# believes is conditional turns out never to have been.
if [[ "$SKIP_IF_PUBLISHED" == "true" && "$TARGET" != "ssh-sidecar" && "$TARGET" != "ssh-resolver" && "$TARGET" != "builder" ]]; then
  echo "--skip-if-published only applies to --ssh-sidecar, --ssh-resolver and --builder." >&2
  exit 1
fi

GIT_COMMIT=$(git rev-parse --short HEAD)

GIT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
BRANCH_TAG=$(echo "$GIT_BRANCH" | sed -E 's/[^A-Za-z0-9_.-]+/-/g; s/^[.-]+//')

if [ -z "$TAG" ]; then
  TAG="$GIT_COMMIT"
fi

echo "=============================================="
echo "Building Caelus Images"
echo "Registry: ${REGISTRY}"
echo "Tag: ${TAG}"
echo "Branch tag: ${BRANCH_TAG}"
echo "Target: ${TARGET}"
echo "=============================================="

if [[ "$TARGET" == "ssh-sidecar" ]]; then
  SIDECAR_CONTEXT=./products/_lib/ssh-sidecar-image
  SIDECAR_VERSION=$(tr -d '[:space:]' < "${SIDECAR_CONTEXT}/VERSION")
  SIDECAR_REF="${REGISTRY}/ssh-sidecar:${SIDECAR_VERSION}"

  # A published tag is never overwritten: a change to the image is a new
  # version, and the chart that names it is repointed. Enforced here rather
  # than left to a line in a README that someone has to remember.
  if docker manifest inspect "${SIDECAR_REF}" >/dev/null 2>&1; then
    if [[ "$SKIP_IF_PUBLISHED" == "true" ]]; then
      echo "${SIDECAR_REF} is already published. Nothing to do."
      exit 0
    fi
    echo "Refusing to overwrite ${SIDECAR_REF}, which is already published." >&2
    echo "Bump ${SIDECAR_CONTEXT}/VERSION and repoint the chart that references it." >&2
    exit 1
  fi

  echo ""
  echo "[1/1] Building and pushing SSH sidecar image ${SIDECAR_VERSION}..."
  # amd64 only: the cluster node is amd64 and multi-arch is an explicit
  # non-goal. The Dockerfile fails the build on any other architecture.
  docker buildx build \
    --push \
    --platform linux/amd64 \
    --tag "${SIDECAR_REF}" \
    "${SIDECAR_CONTEXT}"

  echo ""
  echo "=============================================="
  echo "Pushed ${SIDECAR_REF}"
  echo ""
  echo "This does not reach any deployment on its own. Point the chart that"
  echo "consumes it at this version and roll that out; ./scripts/rollout.sh"
  echo "restarts the platform's own Deployments and has no bearing here."
  echo "=============================================="
  exit 0
fi

if [[ "$TARGET" == "ssh-resolver" ]]; then
  RESOLVER_CONTEXT=./ssh-auth
  RESOLVER_VERSION=$(tr -d '[:space:]' < "${RESOLVER_CONTEXT}/VERSION")
  RESOLVER_REF="${REGISTRY}/ssh-resolver:${RESOLVER_VERSION}"

  # Never overwritten, for the same reason as the sidecar above and one more:
  # rolling back the SSH edge means pointing Terraform at the previous version,
  # which only works while that version is still the image it was.
  if docker manifest inspect "${RESOLVER_REF}" >/dev/null 2>&1; then
    if [[ "$SKIP_IF_PUBLISHED" == "true" ]]; then
      echo "${RESOLVER_REF} is already published. Nothing to do."
      exit 0
    fi
    echo "Refusing to overwrite ${RESOLVER_REF}, which is already published." >&2
    echo "Bump ssh-auth/VERSION and repoint tf/app/sshpiper." >&2
    exit 1
  fi

  echo ""
  echo "[1/1] Building and pushing SSH resolver image ${RESOLVER_VERSION}..."
  # Its own directory is the whole context: ssh-auth/ depends on nothing else
  # in the repository, which is the point of it being self-contained.
  docker buildx build \
    --push \
    --platform linux/amd64 \
    --tag "${RESOLVER_REF}" \
    "${RESOLVER_CONTEXT}"

  echo ""
  echo "=============================================="
  echo "Pushed ${RESOLVER_REF}"
  echo ""
  echo "This does not reach the SSH edge on its own. Point tf/app/sshpiper at"
  echo "this version and apply; ./scripts/rollout.sh does not touch it."
  echo "=============================================="
  exit 0
fi

if [[ "$TARGET" == "builder" ]]; then
  BUILDER_CONTEXT=./products/custom/builder
  BUILDER_VERSION=$(tr -d '[:space:]' < "${BUILDER_CONTEXT}/VERSION")
  BUILDER_REF="${REGISTRY}/builder:${BUILDER_VERSION}"

  # Never overwritten, for the same reason as the two above and one specific to
  # this image: a build Job names it by tag, so re-pushing would change what
  # executes tenant code under a version nobody bumped.
  if docker manifest inspect "${BUILDER_REF}" >/dev/null 2>&1; then
    if [[ "$SKIP_IF_PUBLISHED" == "true" ]]; then
      echo "${BUILDER_REF} is already published. Nothing to do."
      exit 0
    fi
    echo "Refusing to overwrite ${BUILDER_REF}, which is already published." >&2
    echo "Bump ${BUILDER_CONTEXT}/VERSION and repoint builder_image in tf/app." >&2
    exit 1
  fi

  echo ""
  echo "[1/1] Building and pushing the tenant build image ${BUILDER_VERSION}..."
  # amd64 only: the railpack binary the Dockerfile installs is x86_64, and the
  # Dockerfile fails the build on any other architecture rather than shipping an
  # image whose railpack cannot exec.
  docker buildx build \
    --push \
    --platform linux/amd64 \
    --tag "${BUILDER_REF}" \
    "${BUILDER_CONTEXT}"

  echo ""
  echo "=============================================="
  echo "Pushed ${BUILDER_REF}"
  echo ""
  echo "This does not reach any build on its own. Point builder_image in tf/app"
  echo "at this version and apply; ./scripts/rollout.sh does not touch it."
  echo "=============================================="
  exit 0
fi

if [[ "$TARGET" == "both" || "$TARGET" == "all" || "$TARGET" == "api" ]]; then
  echo ""
  echo "[1/$(if [[ "$TARGET" == "both" ]]; then echo "2"; elif [[ "$TARGET" == "all" ]]; then echo "3"; else echo "1"; fi)] Building and pushing API image..."
  docker buildx build \
    --push \
    --build-arg GIT_COMMIT="${GIT_COMMIT}" \
    --tag "${REGISTRY}/api:${TAG}" \
    --tag "${REGISTRY}/api:${BRANCH_TAG}" \
    --tag "${REGISTRY}/api:latest" \
    --file ./api/Dockerfile \
    .
fi

if [[ "$TARGET" == "keycloak" || "$TARGET" == "all" ]]; then
  echo ""
  echo "[$(if [[ "$TARGET" == "all" ]]; then echo "2/3"; else echo "1/1"; fi)] Building and pushing Keycloak image (Freepod theme baked in)..."
  docker buildx build \
    --push \
    --tag "${REGISTRY}/keycloak:${TAG}" \
    --tag "${REGISTRY}/keycloak:${BRANCH_TAG}" \
    --tag "${REGISTRY}/keycloak:latest" \
    ./tf/deps/keycloak
fi

if [[ "$TARGET" == "both" || "$TARGET" == "all" || "$TARGET" == "ui" ]]; then
  echo ""
  echo "[1/$(if [[ "$TARGET" == "both" ]]; then echo "2"; elif [[ "$TARGET" == "all" ]]; then echo "3"; else echo "1"; fi)] Building and pushing UI image..."
  docker buildx build \
    --push \
    --build-arg GIT_COMMIT="${GIT_COMMIT}" \
    --tag "${REGISTRY}/ui:${TAG}" \
    --tag "${REGISTRY}/ui:${BRANCH_TAG}" \
    --tag "${REGISTRY}/ui:latest" \
    ./ui
fi

echo ""
echo "=============================================="
echo "Build Complete!"
echo "=============================================="

echo "Images pushed:"
if [[ "$TARGET" == "both" || "$TARGET" == "all" || "$TARGET" == "api" ]]; then
  echo "  ${REGISTRY}/api:${TAG}"
  echo "  ${REGISTRY}/api:${BRANCH_TAG}"
  echo "  ${REGISTRY}/api:latest"
fi
if [[ "$TARGET" == "both" || "$TARGET" == "all" || "$TARGET" == "ui" ]]; then
  echo "  ${REGISTRY}/ui:${TAG}"
  echo "  ${REGISTRY}/ui:${BRANCH_TAG}"
  echo "  ${REGISTRY}/ui:latest"
fi
if [[ "$TARGET" == "keycloak" || "$TARGET" == "all" ]]; then
  echo "  ${REGISTRY}/keycloak:${TAG}"
  echo "  ${REGISTRY}/keycloak:${BRANCH_TAG}"
  echo "  ${REGISTRY}/keycloak:latest"
fi

echo ""


