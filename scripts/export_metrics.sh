#!/usr/bin/env bash
# Run each analytical query and write its result to data/tableau/ as CSV.
#
# These CSVs are what Tableau reads. PostgreSQL still does all the
# calculation — the CSVs are only a serving layer, because Tableau
# Public cannot connect to a database directly.
#
# Every file here is small and pre-aggregated. Tableau never touches the
# 61,000-row event table.
#
# Usage:  ./scripts/export_metrics.sh

set -euo pipefail

DB="${INSIGHTFLOW_DB:-insightflow}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/data/tableau"

mkdir -p "$OUT"

# Make sure the shared user-level view matches the current data.
psql -d "$DB" -q -v ON_ERROR_STOP=1 -f "$ROOT/sql/00_user_funnel_view.sql"

# Each query file ends in exactly one SELECT, so --csv gives one clean
# CSV per file.
for name in \
    01_kpi_summary \
    02_funnel \
    03_retention \
    04_segment_activation \
    05_segment_conversion \
    06_feature_adoption \
    07_monthly_trends \
    08_top_segments
do
    # ON_ERROR_STOP is essential: without it psql exits 0 even when a
    # query fails, so a broken query would silently write an empty CSV
    # and the dashboard would show nothing wrong.
    psql -d "$DB" -q -v ON_ERROR_STOP=1 --csv \
         -f "$ROOT/sql/${name}.sql" -o "$OUT/${name}.csv"
    rows=$(($(wc -l < "$OUT/${name}.csv") - 1))
    printf '%-24s %4s rows\n' "${name}.csv" "$rows"
done

echo "Exported to data/tableau/"
