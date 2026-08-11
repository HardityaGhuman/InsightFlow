#!/usr/bin/env bash
# Load the generated CSVs into PostgreSQL.
#
# Rebuilds the schema from scratch and copies both files in. Uses \copy
# (client side) rather than COPY so no server-side file permissions are
# needed.
#
# Usage:  ./scripts/load_data.sh

set -euo pipefail

DB="${INSIGHTFLOW_DB:-insightflow}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "Rebuilding schema in database '$DB'..."
psql -d "$DB" -q -f "$ROOT/sql/00_schema.sql"

echo "Loading users..."
psql -d "$DB" -q -c "\copy users FROM '$ROOT/data/raw/users.csv' WITH (FORMAT csv, HEADER true)"

echo "Loading events..."
psql -d "$DB" -q -c "\copy events FROM '$ROOT/data/raw/events.csv' WITH (FORMAT csv, HEADER true)"

psql -d "$DB" -c "SELECT
    (SELECT count(*) FROM users)  AS users,
    (SELECT count(*) FROM events) AS events;"

echo "Done."
