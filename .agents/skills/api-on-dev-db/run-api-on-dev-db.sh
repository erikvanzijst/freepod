#!/usr/bin/env bash
# Run the local API (api/app/main.py, port 8000) against the dev cluster's
# platform database, configured like the dev API. Dev only: the namespace is
# fixed, because the same kubectl context also reaches production.
set -euo pipefail

NS=caelus-dev
PORT="${DEV_DB_PORT:-15432}"
ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
STATIC="$ROOT/var/dev-static"

kc() { kubectl -n "$NS" "$@"; }
secret() { kc get secret "$1" -o "jsonpath={.data.$2}" | base64 -d; }

# 1. A port forward to dev's Postgres, unless one is already listening.
if ! pg_isready -q -h localhost -p "$PORT"; then
  echo "Forwarding $NS/caelus-postgres to localhost:$PORT"
  kc port-forward deploy/caelus-postgres "$PORT:5432" >/dev/null &
  FORWARD=$!
  trap 'kill $FORWARD 2>/dev/null' EXIT
  for _ in $(seq 30); do pg_isready -q -h localhost -p "$PORT" && break; sleep 0.5; done
  pg_isready -q -h localhost -p "$PORT" || { echo "Port forward did not come up" >&2; exit 1; }
fi

DB_USER=$(secret caelus-db username)
DB_PASS=$(secret caelus-db password)
DB_NAME=$(secret caelus-db database)

# 2. The schema must match this checkout's migrations, or the API breaks in odd places.
REMOTE_REV=$(PGPASSWORD="$DB_PASS" psql -h localhost -p "$PORT" -U "$DB_USER" -d "$DB_NAME" -Atc "select version_num from alembic_version")
LOCAL_HEAD=$(cd "$ROOT/api" && uv run alembic heads 2>/dev/null | awk '{print $1}')
if [ "$REMOTE_REV" != "$LOCAL_HEAD" ]; then
  echo "Dev database is at $REMOTE_REV but this checkout's head is $LOCAL_HEAD." >&2
  echo "Rebase onto what dev runs, or set ALLOW_SCHEMA_MISMATCH=1 to start anyway." >&2
  [ "${ALLOW_SCHEMA_MISMATCH:-}" = 1 ] || exit 1
fi

# 3. Icons and screenshots live on dev's static volume; take a snapshot once.
if [ ! -d "$STATIC/icons" ] || [ "${REFRESH_STATIC:-}" = 1 ]; then
  echo "Copying dev's static files to $STATIC"
  mkdir -p "$STATIC"
  kc exec deploy/caelus-api -c api -- tar cf - -C /var/static . | tar xf - -C "$STATIC"
fi

# 4. Dev's API configuration, then the few values that must point here instead.
#    Exported variables win over api/.env and api/.env.local.
eval "$(kc get configmap caelus-api-config -o json | python3 -c '
import json, shlex, sys
for key, value in json.load(sys.stdin)["data"].items():
    if key.startswith("CAELUS_"):
        print(f"export {key}={shlex.quote(value)}")
')"
export CAELUS_VAR_ENCRYPTION_KEYS="$(secret caelus-var-keys CAELUS_VAR_ENCRYPTION_KEYS)"
export CAELUS_DATABASE_URL="postgresql+psycopg://$DB_USER:$DB_PASS@localhost:$PORT/$DB_NAME"
export CAELUS_STATIC_PATH="$STATIC"
export CAELUS_BASE_URL="http://localhost:5173"
export CAELUS_BASE_URL_API="http://localhost:8000/api/"
export CAELUS_MOLLIE_REDIRECT_URL="http://localhost:5173"

echo "Starting the API on :8000 against $NS (revision $REMOTE_REV)"
cd "$ROOT/api"
uv run python3 app/main.py
