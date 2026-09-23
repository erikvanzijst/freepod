#!/bin/bash
#
# Perform a rolling restart of Caelus deployments to pick up new container
# images. Deployments set imagePullPolicy: Always, so a restart pulls the
# newest image behind the deployment's tag (dev :latest, prod :master) and
# rolls out new pods with zero downtime.
#
# Usage:
#   ./scripts/rollout.sh dev      # Rollout to caelus-dev namespace
#   ./scripts/rollout.sh prod     # Rollout to caelus namespace (with confirmation)
#   ./scripts/rollout.sh --help   # Show help

set -euo pipefail

DEPLOYMENTS=("caelus-api" "caelus-ui" "caelus-worker" "caelus-build-worker" "caelus-db-worker" "caelus-usage-worker")

usage() {
  cat <<'EOF'
Usage: ./scripts/rollout.sh <env> [OPTIONS]

Perform a rolling restart of all Caelus deployments to pick up newly pushed
container images. Deployments use RollingUpdate strategy with zero downtime.

Arguments:
  dev     Deploy to caelus-dev namespace
  prod    Deploy to caelus namespace (requires confirmation)

Options:
  -y, --yes   Skip confirmation prompt (for CI/scripting)
  --help      Show this help message and exit

Typical workflow:
  ./scripts/build-images.sh     # Build and push new :latest images
  ./scripts/rollout.sh dev      # Roll out to dev
  ./scripts/rollout.sh prod     # Roll out to prod
EOF
}

ENV=""
SKIP_CONFIRM=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    dev|prod)
      if [[ -n "$ENV" ]]; then
        echo "Error: environment already set to '${ENV}'."
        exit 1
      fi
      ENV="$1"
      shift
      ;;
    -y|--yes)
      SKIP_CONFIRM=true
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Error: unknown argument '$1'."
      echo "Run './scripts/rollout.sh --help' for usage."
      exit 1
      ;;
  esac
done

if [[ -z "$ENV" ]]; then
  usage
  exit 1
fi

case "$ENV" in
  dev)  NAMESPACE="caelus-dev" ;;
  prod) NAMESPACE="caelus" ;;
esac

# Confirm before deploying to prod
if [[ "$ENV" == "prod" && "$SKIP_CONFIRM" == false ]]; then
  echo "You are about to roll out to PRODUCTION (namespace: ${NAMESPACE})."
  read -r -p "Continue? [y/N] " response
  if [[ ! "$response" =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 0
  fi
fi

echo "=============================================="
echo "Rolling out Caelus deployments"
echo "Environment: ${ENV}"
echo "Namespace:   ${NAMESPACE}"
echo "=============================================="

for deploy in "${DEPLOYMENTS[@]}"; do
  echo ""
  echo "Restarting ${deploy}..."
  kubectl rollout restart deployment/"${deploy}" -n "${NAMESPACE}"
done

echo ""
echo "Waiting for rollouts to complete..."

for deploy in "${DEPLOYMENTS[@]}"; do
  echo "  ${deploy}..."
  kubectl rollout status deployment/"${deploy}" -n "${NAMESPACE}" --timeout=120s
done

echo ""
echo "=============================================="
echo "Rollout complete!"
echo "=============================================="
