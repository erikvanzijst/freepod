#!/bin/bash
#
# Sweep every database on the tenant PostgreSQL cluster for the index and
# constraint damage that the 18.7 release notes say to repair, and optionally
# rebuild the affected indexes. Run it after the tenant cluster is on 18.7.
# The query, and what each finding means, is in tenant-db-index-sweep.sql.
#
# Runs psql as the superuser inside the tenant postgres pod through kubectl
# exec, so it needs exec rights in the environment's namespace.
#
# Usage:
#   ./scripts/tenant-db-index-sweep.sh dev               # list findings only
#   ./scripts/tenant-db-index-sweep.sh prod --reindex    # list and rebuild

set -euo pipefail

usage() {
  cat <<'EOF'
Usage: ./scripts/tenant-db-index-sweep.sh <env> [--reindex]

Lists, in every database on the tenant cluster, the indexes and constraints the
PostgreSQL 18.7 update says to check: GIN indexes, pg_trgm GiST indexes, B-tree
indexes on unlengthed bpchar, and NOT NULL NO INHERIT constraints on partitioned
tables.

Arguments:
  dev     caelus-dev namespace
  prod    caelus namespace

Options:
  --reindex   Also rebuild the listed indexes with REINDEX INDEX CONCURRENTLY.
              Refused unless the server is 18.7 or later. Constraints are only
              ever reported.
  --help      Show this help message and exit
EOF
}

ENV=""
REINDEX=off

while [[ $# -gt 0 ]]; do
  case "$1" in
    dev|prod) ENV="$1"; shift ;;
    --reindex) REINDEX=on; shift ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Error: unknown argument '$1'." >&2; usage >&2; exit 1 ;;
  esac
done

if [[ -z "$ENV" ]]; then
  usage >&2
  exit 1
fi

case "$ENV" in
  dev)  NAMESPACE="caelus-dev" ;;
  prod) NAMESPACE="caelus" ;;
esac

SQL_FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/tenant-db-index-sweep.sql"
TARGET="deploy/caelus-tenant-postgres"

# The client's own options outrank per-database and per-role settings: belt and
# braces so a suspended database (default_transaction_read_only) or a tenant's
# statement_timeout cannot get in the way of a long rebuild.
PG_OPTS="-c default_transaction_read_only=off -c statement_timeout=0 -c lock_timeout=0"

pg() {
  kubectl -n "$NAMESPACE" exec -i "$TARGET" -c postgres -- \
    env PGOPTIONS="$PG_OPTS" psql -U postgres -X -q "$@"
}

echo "Tenant cluster in ${NAMESPACE}: $(pg -d postgres -Atc 'SELECT version()')"

if [[ "$REINDEX" == "on" && "$ENV" == "prod" ]]; then
  read -r -p "Rebuild flagged indexes in every tenant database in ${NAMESPACE}? [y/N] " answer
  [[ "$answer" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 1; }
fi

mapfile -t DATABASES < <(pg -d postgres -Atc \
  "SELECT datname FROM pg_database WHERE datallowconn AND NOT datistemplate ORDER BY datname")

failed=()
for db in "${DATABASES[@]}"; do
  echo
  echo "== ${db}"
  if ! pg -d "$db" -v reindex="$REINDEX" -f - < "$SQL_FILE"; then
    failed+=("$db")
  fi
done

echo
echo "Swept ${#DATABASES[@]} database(s)."
if [[ ${#failed[@]} -gt 0 ]]; then
  echo "Failed in: ${failed[*]}" >&2
  exit 1
fi
