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

# ON_ERROR_STOP is essential on every call below. psql exits 0 even when
# a statement fails, so without it a failed schema rebuild would be
# invisible and the COPY would load into the old, still-populated tables
# and die on a duplicate key. That exact failure happened once.
PSQL="psql -d $DB -q -v ON_ERROR_STOP=1"

echo "Rebuilding schema in database '$DB'..."
$PSQL -f "$ROOT/sql/00_schema.sql"

echo "Loading users..."
$PSQL -c "\copy users FROM '$ROOT/data/raw/users.csv' WITH (FORMAT csv, HEADER true)"

echo "Loading events..."
$PSQL -c "\copy events FROM '$ROOT/data/raw/events.csv' WITH (FORMAT csv, HEADER true)"

psql -d "$DB" -c "SELECT
    (SELECT count(*) FROM users)  AS users,
    (SELECT count(*) FROM events) AS events;"

echo "Done."
