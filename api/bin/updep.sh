#!/usr/bin/env bash
# Moves deployments onto their product's current template, as the admin UI's
# Upgrade button does. Run it inside the API pod: the build worker has no vars
# keyring, so deployments with vars would fail there.
#
#   kubectl exec -i -n caelus-dev -c api deploy/caelus-api -- sh -c 'cat > /tmp/upgrade-deployments.sh' < var/upgrade-deployments.sh
#   kubectl exec -it -n caelus-dev -c api deploy/caelus-api -- bash /tmp/upgrade-deployments.sh upgrade -i
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: upgrade-deployments.sh list    [-p SLUG] [-u EMAIL|ID]
       upgrade-deployments.sh upgrade [-p SLUG] [-u EMAIL|ID] [-i]

  list      list deployments whose template is behind their product's current one
  upgrade   move those deployments onto their product's current template

  -p, --product SLUG   only this product (repeatable, or comma-separated);
                       a product without a slug is matched by its id
  -u, --user EMAIL|ID  only this user's deployments (repeatable, or comma-separated)
  -i, --interactive    upgrade only: ask before each deployment:
                       [y]es, [n]o, [a]ll remaining, [q]uit
  -h, --help           show this help

Only ready and error deployments can be updated; rerun to pick up skipped ones.
Acts as $CAELUS_USER_EMAIL, which must be an admin.
EOF
}

command="" products=() users=() interactive=false
split() { local IFS=,; read -ra parts <<<"$1"; printf '%s\n' "${parts[@]}"; }
need() { [[ $# -ge 2 && -n $2 ]] || { echo "error: $1 needs a value" >&2; exit 2; }; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    -p|--product) need "$@"; mapfile -t -O "${#products[@]}" products < <(split "$2"); shift 2 ;;
    --product=*)  mapfile -t -O "${#products[@]}" products < <(split "${1#*=}"); shift ;;
    -u|--user)    need "$@"; mapfile -t -O "${#users[@]}" users < <(split "$2"); shift 2 ;;
    --user=*)     mapfile -t -O "${#users[@]}" users < <(split "${1#*=}"); shift ;;
    -i|--interactive) interactive=true; shift ;;
    -h|--help)    usage; exit 0 ;;
    list|upgrade) [[ -z $command ]] || { echo "error: more than one command" >&2; exit 2; }
                  command=$1; shift ;;
    *) echo "error: unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -z $command ]]; then
  usage >&2; exit 2
fi
if $interactive && [[ $command != upgrade ]]; then
  echo "error: --interactive only applies to upgrade" >&2; exit 2
fi

export CAELUS_USER_EMAIL=${CAELUS_USER_EMAIL:-erik.van.zijst@gmail.com}
if $interactive && ! { : </dev/tty; } 2>/dev/null; then
  echo "error: --interactive needs a terminal (kubectl exec -it)" >&2; exit 2
fi

json_list() { if [[ $# -eq 0 ]]; then echo '[]'; else printf '%s\n' "$@" | jq -R . | jq -cs .; fi; }

mapfile -t rows < <(
  caelus list-deployments --all | yq -r \
    --argjson products "$(json_list ${products[@]+"${products[@]}"})" \
    --argjson users "$(json_list ${users[@]+"${users[@]}"})" '
    .[] | (.desired_template.product) as $prod
    | select($prod.template_id != null and .desired_template.id != $prod.template_id)
    | ($prod.slug // ($prod.id | tostring)) as $key
    | (.user.email // "" | ascii_downcase) as $email
    | (.user_id | tostring) as $uid
    | select(($products | length) == 0 or any($products[]; . == $key))
    | select(($users | length) == 0
             or any($users[] | ascii_downcase; . == $email or . == $uid))
    | [.user_id, .id, .desired_template.id, $prod.template_id, .status,
       ($prod.slug // $prod.name), (.user.email // "-"), (.hostname // "-")] | @tsv'
)

if [[ ${#rows[@]} -eq 0 ]]; then
  echo "No outdated deployments."
  exit 0
fi

echo "${#rows[@]} deployment(s) behind their product's template:"
for row in "${rows[@]}"; do
  IFS=$'\t' read -r _ id from to status slug email host <<<"$row"
  printf '  %-10s %-28s %-30s #%s -> #%s  %-8s %s\n' "$slug" "$email" "$host" "$from" "$to" "$status" "$id"
done
[[ $command == list ]] && exit 0
echo

ok=0 skipped=0 failed=0 ask=$interactive
for row in "${rows[@]}"; do
  IFS=$'\t' read -r uid id from to status slug email host <<<"$row"
  label="$slug $host ($email)"
  case "$status" in
    ready|error) ;;
    *) echo "SKIP $label: $status"; skipped=$((skipped + 1)); continue ;;
  esac
  if $ask; then
    while true; do
      read -r -p "Upgrade $label #$from -> #$to? [y/n/a/q] " answer </dev/tty
      case "${answer,,}" in
        y|yes) break ;;
        a|all) ask=false; break ;;
        n|no)  echo "SKIP $label: declined"; skipped=$((skipped + 1)); continue 2 ;;
        q|quit) echo "Stopped."; break 2 ;;
      esac
    done
  fi
  if out=$(caelus update-deployment --user-id "$uid" --deployment-id "$id" \
             --desired-template-id "$to" </dev/null 2>&1); then
    echo "OK   $label #$from -> #$to"; ok=$((ok + 1))
  else
    echo "FAIL $label: $(tail -n1 <<<"$out")"; failed=$((failed + 1))
  fi
done

echo
echo "$ok upgraded, $skipped skipped, $failed failed."
echo "Follow progress with: caelus list-deployments --all; caelus jobs --failed"
[[ $failed -eq 0 ]]
