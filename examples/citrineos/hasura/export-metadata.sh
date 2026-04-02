#!/usr/bin/env bash
# Export Hasura metadata from a running instance so it persists across restarts.
# Usage: ./hasura/export-metadata.sh [hasura_url]
#
# Run this AFTER you've tracked all tables/relationships in Hasura.
# The exported metadata is auto-applied on next container startup via
# the cli-migrations-v3 image's /hasura-metadata volume mount.

set -euo pipefail

HASURA_URL="${1:-http://localhost:${HASURA_PORT:-8090}}"

echo "Exporting metadata from ${HASURA_URL}..."

# Export full metadata as JSON
METADATA=$(curl -sf "${HASURA_URL}/v1/metadata" \
  -H 'Content-Type: application/json' \
  -d '{"type":"export_metadata","version":2,"args":{}}')

if [ -z "$METADATA" ]; then
  echo "ERROR: Could not export metadata. Is Hasura running?"
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
echo "$METADATA" > "${SCRIPT_DIR}/metadata/metadata.json"

echo "Metadata exported to hasura/metadata/metadata.json"
echo "This will be auto-applied on next 'docker compose up'."
