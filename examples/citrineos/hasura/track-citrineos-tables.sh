#!/usr/bin/env bash
# Track all CitrineOS tables in Hasura and export the metadata.
# Run this once after a fresh stack start to bootstrap Hasura.
#
# Usage: ./hasura/track-citrineos-tables.sh [hasura_url]

set -euo pipefail

HASURA_URL="${1:-http://localhost:${HASURA_PORT:-8090}}"

echo "Discovering CitrineOS tables via Hasura at ${HASURA_URL}..."

# Get all tables in the public schema
TABLES=$(curl -sf "${HASURA_URL}/v2/query" \
  -H 'Content-Type: application/json' \
  -d '{
    "type": "run_sql",
    "args": {
      "source": "default",
      "sql": "SELECT tablename FROM pg_tables WHERE schemaname = '\''public'\'' ORDER BY tablename;"
    }
  }' | python3 -c "
import json, sys
data = json.load(sys.stdin)
# Skip header row
for row in data['result'][1:]:
    print(row[0])
")

if [ -z "$TABLES" ]; then
  echo "ERROR: No tables found. Is CitrineOS database migrated?"
  exit 1
fi

TABLE_COUNT=0
for TABLE in $TABLES; do
  echo "  Tracking: ${TABLE}"
  # Track table (ignore errors for already-tracked tables)
  curl -sf "${HASURA_URL}/v1/metadata" \
    -H 'Content-Type: application/json' \
    -d "{
      \"type\": \"pg_track_table\",
      \"args\": {
        \"source\": \"default\",
        \"table\": {
          \"schema\": \"public\",
          \"name\": \"${TABLE}\"
        }
      }
    }" > /dev/null 2>&1 || true
  TABLE_COUNT=$((TABLE_COUNT + 1))
done

echo "Tracked ${TABLE_COUNT} tables."

# Now export metadata so it persists
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
bash "${SCRIPT_DIR}/export-metadata.sh" "$HASURA_URL"
