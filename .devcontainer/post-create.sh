#!/usr/bin/env bash
set -euo pipefail

cd /workspace/src/api
uv sync

completion_dir="$HOME/.local/share/caelus"
completion_file="$completion_dir/completion.bash"
completion_source_line="source \"$completion_file\""

mkdir -p "$completion_dir"
uv run caelus --show-completion > "$completion_file"

grep -qxF "$completion_source_line" "$HOME/.bashrc" || \
  echo "$completion_source_line" >> "$HOME/.bashrc"

alias_line="alias claude='claude --dangerously-skip-permissions'"
grep -qxF "$alias_line" "$HOME/.bashrc" || \
  echo "$alias_line" >> "$HOME/.bashrc"

uv run alembic upgrade head

# The test database, which the suites share but neither owns. pytest creates it
# on demand (`test_database` in api/tests/conftest.py), but the Go suite in
# daemons/ssh-auth/ has no such hook and only reads, so a fresh container has to
# arrive with the database already migrated for `go test ./...` to work at all.
#
# Idempotent on purpose: var/pg_data outlives container rebuilds, so this
# re-runs against a database that is usually already there.
test_db="${CAELUS_TEST_DATABASE_URL##*/}"
admin_url="${CAELUS_TEST_DATABASE_URL/+psycopg/}"
admin_url="${admin_url%/*}/postgres"

if ! psql "$admin_url" -tAc "SELECT 1 FROM pg_database WHERE datname = '$test_db'" | grep -q 1; then
  psql "$admin_url" -c "CREATE DATABASE \"$test_db\""
fi
CAELUS_DATABASE_URL="$CAELUS_TEST_DATABASE_URL" uv run alembic upgrade head

cd /workspace/src/cli
uv sync
