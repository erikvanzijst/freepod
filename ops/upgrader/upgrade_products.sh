#!/usr/bin/env bash
# The local runner: the upgrade-product skill once per curated product, each in its own fresh
# pi session and clone, behind the service's guards.
#
#   upgrade_products.sh [slug ...]    # default: every product with a real upstream
#
# Env: MODEL, THINKING, UPGRADE_DRY_RUN (default 1), UPGRADE_OUT_DIR (a temp dir if unset),
# REPO_URL (what each product clones; default GitHub, or a local fixture for a scenario).
# Products run one after another: the inference server serves a single session at a time.
set -uo pipefail

here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../.." && pwd)
SKILL="$root/products/UPGRADING/SKILL.md"
SCHEMA="$root/products/UPGRADING/result.schema.json"
MODEL="${MODEL:-deprutser/qwen3.8-27b-q4}"
THINKING="${THINKING:-medium}"
REPO_URL="${REPO_URL:-https://github.com/erikvanzijst/freepod.git}"
export UPGRADE_DRY_RUN="${UPGRADE_DRY_RUN:-1}"
export UPGRADE_OUT_DIR="${UPGRADE_OUT_DIR:-$(mktemp -d)}"
mkdir -p "$UPGRADE_OUT_DIR"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

export UPGRADER_REAL_GH UPGRADER_REAL_GIT
UPGRADER_REAL_GH=$(command -v gh)
UPGRADER_REAL_GIT=$(command -v git)

slugs=("$@")
if [ ${#slugs[@]} -eq 0 ]; then
  git clone -q --depth 1 --branch master "$REPO_URL" "$work/catalog" || exit 1
  for f in "$work"/catalog/products/catalog/*.yaml; do
    grep -q '^upstream:' "$f" && ! grep -q 'OWNER/REPO' "$f" && slugs+=("$(basename "$f" .yaml)")
  done
fi

# One pi turn for $slug; extra arguments go before the message, the last argument.
run_pi() {
  local message="${*: -1}"
  (cd "$work/$slug" && PATH="$here/bin:$PATH" GH_REPO=erikvanzijst/freepod UPGRADE_PRODUCT="$slug" \
     PI_TELEMETRY=0 GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.hooksPath GIT_CONFIG_VALUE_0="$here/hooks" \
     pi --model "$MODEL" --thinking "$THINKING" --skill "$SKILL" --no-context-files \
        --name "upgrade-$slug" --session-dir "$UPGRADE_OUT_DIR/$slug.session" "${@:1:$#-1}" -p -- "$message" \
     </dev/null >>"$UPGRADE_OUT_DIR/$slug.stdout.txt" 2>&1) || echo "    pi exited non-zero; see $UPGRADE_OUT_DIR/$slug.stdout.txt"
}

check() {
  uv run --directory "$here" --no-sync python -m upgrader.result "$SCHEMA" \
    "$UPGRADE_OUT_DIR/$slug/result.json" "$slug" "$dry"
}

failed=0
for slug in "${slugs[@]}"; do
  echo "=== $slug ($(date -u +%H:%M:%S))"
  git clone -q --depth 1 --branch master "$REPO_URL" "$work/$slug/freepod" || { failed=1; continue; }
  : >"$UPGRADE_OUT_DIR/$slug.stdout.txt"
  run_pi "Run the upgrade-product skill for the $slug product only. The repository is already cloned at ./freepod: work in that clone and do not clone it again. Read the skill file in full before you start."
  dry=$([ "$UPGRADE_DRY_RUN" = 0 ] && echo 0 || echo 1)
  # Like the service: an unacceptable result gets one more turn in the same session.
  verdict=$(check); ok=$?
  echo "$verdict"
  transcript=$(find "$UPGRADE_OUT_DIR/$slug.session" -name '*.jsonl' 2>/dev/null | sort | head -n 1)
  if [ $ok -ne 0 ] && [ -n "$transcript" ]; then
    echo "    asking the session to fix its result"
    run_pi --session "$transcript" "$(uv run --directory "$here" --no-sync python -c \
      'import sys; from upgrader.pi import repair_prompt; print(repair_prompt(*sys.argv[1:]))' \
      "$slug" "${verdict#"$slug: failed: "}")"
    check || failed=1
  elif [ $ok -ne 0 ]; then
    failed=1
  fi
done

echo "Results and outputs: $UPGRADE_OUT_DIR"
exit $failed
