#!/bin/bash
#
# Package and push product Helm charts to ghcr.io
#
# Usage:
#   ./scripts/publish-charts.sh custom                      # Publish one chart
#   ./scripts/publish-charts.sh immich nextcloud            # Publish several
#   ./scripts/publish-charts.sh --all                       # Publish every product chart
#   ./scripts/publish-charts.sh --all --skip-if-published   # What CI runs on merge
#   ./scripts/publish-charts.sh --help
#
# The contract is the one build-images.sh applies to its immutably-tagged
# images: the tag is the chart's own Chart.yaml version, a published version is
# never overwritten, and --skip-if-published makes an already-published version
# a no-op so CI can run this on every merge. products/_lib/ssh-sidecar-chart is
# not a product chart and is never published; it is vendored into each package
# by `helm dependency build`.

set -euo pipefail

cd "$(dirname "$0")/.."

CHARTS=()
for chart_yaml in products/*/chart/Chart.yaml; do
  CHARTS+=("$(basename "$(dirname "$(dirname "$chart_yaml")")")")
done

usage() {
  cat <<EOF
Usage: ./scripts/publish-charts.sh [CHART...|--all] [--skip-if-published] [--help]

Packages each named chart from products/<CHART>/chart and pushes it to
oci://ghcr.io/<owner>/freepod/charts, tagged with the version in its Chart.yaml.

Charts:
$(printf '  %s\n' "${CHARTS[@]}")

Options:
  --all                Publish every chart listed above.
  --skip-if-published  Treat an already-published version as nothing to do
                       rather than an error. This is what makes the publish safe
                       to run on every merge: it pushes exactly when a chart's
                       version is new. Run by hand without it, so that a version
                       you believed you had bumped fails loudly.
  --help               Show this help message and exit.
EOF
}

SELECTED=()
ALL=false
SKIP_IF_PUBLISHED=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --all)
      ALL=true
      shift
      ;;
    --skip-if-published)
      SKIP_IF_PUBLISHED=true
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    -*)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
    *)
      if [[ ! -f "products/$1/chart/Chart.yaml" ]]; then
        echo "Unknown chart: $1 (see --help for the list)" >&2
        exit 1
      fi
      SELECTED+=("$1")
      shift
      ;;
  esac
done

if [[ "$ALL" == "true" && ${#SELECTED[@]} -gt 0 ]]; then
  echo "Name charts or pass --all, not both." >&2
  exit 1
fi
if [[ "$ALL" == "true" ]]; then
  SELECTED=("${CHARTS[@]}")
fi
if [[ ${#SELECTED[@]} -eq 0 ]]; then
  usage >&2
  exit 1
fi

REGISTRY=oci://ghcr.io/$(gh repo view --json nameWithOwner -q .nameWithOwner)/charts

# Top-level keys only: `dependencies:` sorts first and carries its own `version:`.
chart_field() {
  helm show chart "products/$1/chart" | awk -v key="$2:" 'index($0, key) == 1 { print $2; exit }'
}

# Only "not found" means unpublished. Reading an auth or network failure as
# absence would send the publish on to push over a version that exists.
is_published() {
  local output
  if output=$(helm show chart "$1" --version "$2" 2>&1); then
    return 0
  fi
  if grep -q ': not found' <<<"$output"; then
    return 1
  fi
  echo "Could not determine whether $1:$2 is published:" >&2
  echo "$output" >&2
  exit 1
}

echo "=============================================="
echo "Publishing product charts"
echo "Registry: ${REGISTRY}"
echo "=============================================="

# Every check runs before any push, so a refusal leaves nothing half-published.
TO_PUBLISH=()
REFUSED=()
for chart in "${SELECTED[@]}"; do
  name=$(chart_field "$chart" name)
  version=$(chart_field "$chart" version)
  if is_published "${REGISTRY}/${name}" "$version"; then
    if [[ "$SKIP_IF_PUBLISHED" == "true" ]]; then
      echo "${REGISTRY}/${name}:${version} is already published. Nothing to do."
    else
      REFUSED+=("${REGISTRY}/${name}:${version}")
    fi
  else
    TO_PUBLISH+=("$chart")
  fi
done

if [[ ${#REFUSED[@]} -gt 0 ]]; then
  for ref in "${REFUSED[@]}"; do
    echo "Refusing to overwrite ${ref}, which is already published." >&2
  done
  echo "Bump version in the chart's Chart.yaml and repoint the templates that reference it." >&2
  exit 1
fi

if [[ ${#TO_PUBLISH[@]} -eq 0 ]]; then
  exit 0
fi

WORKDIR=$(mktemp -d)
trap 'rm -rf "$WORKDIR"' EXIT

PUBLISHED=()
for chart in "${TO_PUBLISH[@]}"; do
  dir="products/${chart}/chart"
  name=$(chart_field "$chart" name)
  version=$(chart_field "$chart" version)

  echo ""
  echo "Packaging and pushing ${name} ${version}..."
  # `build` rather than `update`, so the tracked Chart.lock decides what is
  # vendored and is not rewritten.
  if helm show chart "$dir" | grep -q '^dependencies:'; then
    helm dependency build "$dir"
  fi
  helm package "$dir" --destination "$WORKDIR"
  helm push "${WORKDIR}/${name}-${version}.tgz" "$REGISTRY"
  PUBLISHED+=("${REGISTRY}/${name}:${version}")
done

echo ""
echo "=============================================="
echo "Pushed:"
printf '  %s\n' "${PUBLISHED[@]}"
echo ""
echo "A new package on ghcr.io is private until its visibility is set to public,"
echo "and nothing can install it until then. This does not reach any deployment"
echo "on its own: point the product's template at the new version."
echo "=============================================="
