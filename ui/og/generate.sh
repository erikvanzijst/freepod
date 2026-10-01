#!/usr/bin/env bash
#
# Rasterize the social preview cards (og/<name>.html) to the shipped PNG assets
# (public/<name>.png). Run after editing a template. With no arguments it
# renders every template; otherwise only the named ones:
#
#     og/generate.sh og-image-dev
#
# Requires a Chrome/Chromium binary. Renders at exactly 1200x630 with a scale
# factor of 1, which is the canonical Open Graph "summary_large_image" size.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Find a headless browser.
chrome=""
for candidate in google-chrome chromium chromium-browser google-chrome-stable; do
  if command -v "$candidate" >/dev/null 2>&1; then
    chrome="$candidate"
    break
  fi
done
if [[ -z "$chrome" ]]; then
  echo "error: no Chrome/Chromium binary found on PATH" >&2
  exit 1
fi

if [[ $# -gt 0 ]]; then
  names=("$@")
else
  names=()
  for template in "$here"/*.html; do
    names+=("$(basename "$template" .html)")
  done
fi

for name in "${names[@]}"; do
  out="${here}/../public/${name}.png"
  "$chrome" \
    --headless \
    --no-sandbox \
    --hide-scrollbars \
    --force-device-scale-factor=1 \
    --window-size=1200,630 \
    --default-background-color=00000000 \
    --screenshot="$out" \
    "file://${here}/${name}.html" >/dev/null 2>&1
  echo "wrote $out"
done
