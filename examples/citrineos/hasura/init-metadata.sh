#!/usr/bin/env bash
# Auto-track all CitrineOS tables and foreign-key relationships in Hasura.
# Designed to run as an init container after Hasura starts.
set -euo pipefail

HASURA_URL="${HASURA_GRAPHQL_ENDPOINT:-http://graphql-engine:8080}"
MAX_WAIT=60
WAITED=0

echo "[hasura-init] Waiting for Hasura at ${HASURA_URL}..."
until curl -sf "${HASURA_URL}/healthz" > /dev/null 2>&1; do
  sleep 2
  WAITED=$((WAITED + 2))
  if [ "$WAITED" -ge "$MAX_WAIT" ]; then
    echo "[hasura-init] ERROR: Hasura not ready after ${MAX_WAIT}s"
    exit 1
  fi
done
echo "[hasura-init] Hasura is ready (waited ${WAITED}s)"

# Step 1: Get all public tables from Postgres via Hasura run_sql
echo "[hasura-init] Discovering tables..."
TABLES=$(curl -sf "${HASURA_URL}/v2/query" \
  -H 'Content-Type: application/json' \
  -d '{
    "type": "run_sql",
    "args": {
      "source": "default",
      "sql": "SELECT tablename FROM pg_tables WHERE schemaname = '\''public'\'' AND tablename != '\''spatial_ref_sys'\'' AND tablename != '\''SequelizeMeta'\'' ORDER BY tablename;"
    }
  }' | python3 -c "
import json, sys
data = json.load(sys.stdin)
for row in data['result'][1:]:
    print(row[0])
")

# Step 2: Track each table
TABLE_COUNT=0
for TABLE in $TABLES; do
  RESULT=$(curl -sf "${HASURA_URL}/v1/metadata" \
    -H 'Content-Type: application/json' \
    -d "{
      \"type\": \"pg_track_table\",
      \"args\": {
        \"source\": \"default\",
        \"table\": {\"schema\": \"public\", \"name\": \"${TABLE}\"}
      }
    }" 2>&1) || true
  TABLE_COUNT=$((TABLE_COUNT + 1))
done
echo "[hasura-init] Tracked ${TABLE_COUNT} tables"

# Step 3: Auto-detect and track foreign-key relationships
echo "[hasura-init] Discovering foreign-key relationships..."
FK_JSON=$(curl -sf "${HASURA_URL}/v2/query" \
  -H 'Content-Type: application/json' \
  -d '{
    "type": "run_sql",
    "args": {
      "source": "default",
      "sql": "SELECT tc.table_name AS from_table, kcu.column_name AS from_column, ccu.table_name AS to_table, ccu.column_name AS to_column, tc.constraint_name FROM information_schema.table_constraints tc JOIN information_schema.key_column_usage kcu ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema JOIN information_schema.constraint_column_usage ccu ON ccu.constraint_name = tc.constraint_name AND ccu.table_schema = tc.table_schema WHERE tc.constraint_type = '\''FOREIGN KEY'\'' AND tc.table_schema = '\''public'\'' ORDER BY tc.table_name;"
    }
  }')

# Parse FKs and create object relationships (many-to-one) and array relationships (one-to-many)
python3 -c "
import json, sys, urllib.request

hasura_url = '${HASURA_URL}'
data = json.loads('''${FK_JSON}''')
rows = data['result'][1:]  # skip header

created = 0
for row in rows:
    from_table, from_col, to_table, to_col, constraint = row

    # Object relationship: from_table -> to_table (many-to-one)
    obj_name = to_table.rstrip('s')  # simple singularize
    if to_table == from_table:
        obj_name = 'Parent' + to_table.rstrip('s')
    payload = json.dumps({
        'type': 'pg_create_object_relationship',
        'args': {
            'source': 'default',
            'table': {'schema': 'public', 'name': from_table},
            'name': obj_name,
            'using': {
                'foreign_key_constraint_on': from_col
            }
        }
    }).encode()
    req = urllib.request.Request(
        f'{hasura_url}/v1/metadata',
        data=payload,
        headers={'Content-Type': 'application/json'}
    )
    try:
        urllib.request.urlopen(req)
        created += 1
    except Exception:
        pass  # already exists

    # Array relationship: to_table -> from_table (one-to-many)
    arr_name = from_table
    payload = json.dumps({
        'type': 'pg_create_array_relationship',
        'args': {
            'source': 'default',
            'table': {'schema': 'public', 'name': to_table},
            'name': arr_name,
            'using': {
                'foreign_key_constraint_on': {
                    'table': {'schema': 'public', 'name': from_table},
                    'column': from_col
                }
            }
        }
    }).encode()
    req = urllib.request.Request(
        f'{hasura_url}/v1/metadata',
        data=payload,
        headers={'Content-Type': 'application/json'}
    )
    try:
        urllib.request.urlopen(req)
        created += 1
    except Exception:
        pass  # already exists

print(f'[hasura-init] Created {created} relationships')
"

echo "[hasura-init] Metadata initialization complete"
