#!/usr/bin/env python3
# pylint: disable=invalid-name
"""Auto-track all CitrineOS tables and foreign-key relationships in Hasura.

Designed to run as an init container after Hasura starts.
Uses only stdlib — no pip dependencies needed.
Uses Hasura bulk API to minimize round-trips.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request

HASURA_URL = os.environ.get("HASURA_GRAPHQL_ENDPOINT", "http://graphql-engine:8080")
MAX_WAIT = 90


def hasura_request(path, payload):
    """Make a JSON POST to Hasura and return parsed response."""
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{HASURA_URL}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def wait_for_hasura():
    """Wait for Hasura to be healthy."""
    print(f"[hasura-init] Waiting for Hasura at {HASURA_URL}...")
    waited = 0
    while waited < MAX_WAIT:
        try:
            req = urllib.request.Request(f"{HASURA_URL}/healthz")
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    print(f"[hasura-init] Hasura is ready (waited {waited}s)")
                    return
        except Exception:  # pylint: disable=broad-exception-caught
            pass
        time.sleep(2)
        waited += 2

    print(f"[hasura-init] ERROR: Hasura not ready after {MAX_WAIT}s")
    sys.exit(1)


def get_tables():
    """Get all public tables from Postgres via Hasura run_sql."""
    result = hasura_request("/v2/query", {
        "type": "run_sql",
        "args": {
            "source": "default",
            "sql": (
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname = 'public' "
                "AND tablename != 'spatial_ref_sys' "
                "AND tablename != 'SequelizeMeta' "
                "ORDER BY tablename;"
            ),
        },
    })
    return [row[0] for row in result["result"][1:]]


def track_tables(tables):
    """Track all tables in a single bulk request."""
    args = [
        {
            "type": "pg_track_table",
            "args": {
                "source": "default",
                "table": {"schema": "public", "name": table},
            },
        }
        for table in tables
    ]
    try:
        hasura_request("/v1/metadata", {"type": "bulk", "args": args})
        print(f"[hasura-init] Tracked {len(tables)} tables (bulk)")
    except urllib.error.HTTPError:
        # Some already tracked — fall back to individual
        count = 0
        for req_args in args:
            try:
                hasura_request("/v1/metadata", req_args)
                count += 1
            except urllib.error.HTTPError:
                pass
        print(f"[hasura-init] Tracked {count} new tables ({len(tables)} total)")


def get_foreign_keys():
    """Get all foreign key relationships from Postgres."""
    result = hasura_request("/v2/query", {
        "type": "run_sql",
        "args": {
            "source": "default",
            "sql": (
                "SELECT tc.table_name, kcu.column_name, "
                "ccu.table_name, ccu.column_name, tc.constraint_name "
                "FROM information_schema.table_constraints tc "
                "JOIN information_schema.key_column_usage kcu "
                "  ON tc.constraint_name = kcu.constraint_name "
                "  AND tc.table_schema = kcu.table_schema "
                "JOIN information_schema.constraint_column_usage ccu "
                "  ON ccu.constraint_name = tc.constraint_name "
                "  AND ccu.table_schema = tc.table_schema "
                "WHERE tc.constraint_type = 'FOREIGN KEY' "
                "AND tc.table_schema = 'public' "
                "ORDER BY tc.table_name;"
            ),
        },
    })
    return result["result"][1:]


def build_relationship_args(fk_rows):
    """Build all relationship metadata args from foreign keys."""
    args = []
    seen_obj = set()
    seen_arr = set()

    for row in fk_rows:
        from_table, from_col, to_table, _to_col, _constraint = row

        # Object relationship: from_table -> to_table (many-to-one)
        obj_name = to_table.rstrip("s")
        if to_table == from_table:
            obj_name = "Parent" + obj_name
        obj_key = (from_table, obj_name)
        if obj_key in seen_obj:
            obj_name = obj_name + "By" + from_col.replace("Id", "").replace("id", "")
        seen_obj.add((from_table, obj_name))

        args.append({
            "type": "pg_create_object_relationship",
            "args": {
                "source": "default",
                "table": {"schema": "public", "name": from_table},
                "name": obj_name,
                "using": {"foreign_key_constraint_on": from_col},
            },
        })

        # Array relationship: to_table -> from_table (one-to-many)
        arr_name = from_table
        arr_key = (to_table, arr_name)
        if arr_key in seen_arr:
            arr_name = from_table + "By" + from_col.replace("Id", "").replace("id", "")
        seen_arr.add((to_table, arr_name))

        args.append({
            "type": "pg_create_array_relationship",
            "args": {
                "source": "default",
                "table": {"schema": "public", "name": to_table},
                "name": arr_name,
                "using": {
                    "foreign_key_constraint_on": {
                        "table": {"schema": "public", "name": from_table},
                        "column": from_col,
                    }
                },
            },
        })

    return args


def create_relationships(fk_rows):
    """Create all relationships, trying bulk first then individual fallback."""
    args = build_relationship_args(fk_rows)
    if not args:
        print("[hasura-init] No relationships to create")
        return

    try:
        hasura_request("/v1/metadata", {"type": "bulk", "args": args})
        print(f"[hasura-init] Created {len(args)} relationships (bulk)")
    except urllib.error.HTTPError:
        # Some already exist — fall back to individual
        created = 0
        for req_args in args:
            try:
                hasura_request("/v1/metadata", req_args)
                created += 1
            except urllib.error.HTTPError:
                pass
        print(f"[hasura-init] Created {created} relationships ({len(args)} attempted)")


def seed_id_tags():
    """Seed authorization idTags so the simulator's StartTransaction is accepted."""
    tags = os.environ.get("SEED_ID_TAGS", "OPTIVGI-AUTO").split(",")
    for tag in tags:
        tag = tag.strip()
        if not tag:
            continue
        try:
            hasura_request("/v2/query", {
                "type": "run_sql",
                "args": {
                    "source": "default",
                    "sql": (
                        f"INSERT INTO \"Authorizations\" "
                        f"(\"idToken\", \"idTokenType\", \"status\", "
                        f"\"concurrentTransaction\", "
                        f"\"realTimeAuth\", \"tenantId\", \"createdAt\", \"updatedAt\") "
                        f"VALUES ('{tag}', 'ISO14443', 'Accepted', "
                        f"true, 'Never', 1, NOW(), NOW()) "
                        f"ON CONFLICT (\"idToken\", \"idTokenType\") "
                        f"DO UPDATE SET \"concurrentTransaction\" = true;"
                    ),
                },
            })
            print(f"[hasura-init] Seeded idTag: {tag}")
        except urllib.error.HTTPError as e:
            print(f"[hasura-init] idTag {tag} seed failed: {e}")


def seed_evses():
    """Seed EVSE records for OCPP 1.6 stations so the operator UI works.

    OCPP 1.6 only has connectors, but the CitrineOS operator UI expects
    EVSE records to display charger activity. For 1.6, each connector
    is treated as its own EVSE.
    """
    station_ids = os.environ.get(
        "STATION_IDS",
        "OPTIVGI-STATION-01,OPTIVGI-STATION-02,OPTIVGI-STATION-03,"
        "OPTIVGI-STATION-04,OPTIVGI-STATION-05,OPTIVGI-STATION-06",
    ).split(",")
    connectors = int(os.environ.get("CONNECTORS_PER_STATION", "2"))

    for station in station_ids:
        station = station.strip()
        if not station:
            continue
        for conn_id in range(1, connectors + 1):
            try:
                hasura_request("/v2/query", {
                    "type": "run_sql",
                    "args": {
                        "source": "default",
                        "sql": (
                            f"INSERT INTO \"Evses\" "
                            f"(\"stationId\", \"evseId\", \"evseTypeId\", "
                            f"\"tenantId\", \"createdAt\", \"updatedAt\") "
                            f"VALUES ('{station}', '{conn_id}', {conn_id}, "
                            f"1, NOW(), NOW()) "
                            f"ON CONFLICT DO NOTHING;"
                        ),
                    },
                })
            except urllib.error.HTTPError:
                pass
    print(f"[hasura-init] Seeded EVSEs for {len(station_ids)} stations")


def main():
    """Discover and track all CitrineOS tables, relationships, and seed EVSEs."""
    wait_for_hasura()

    print("[hasura-init] Discovering tables...")
    tables = get_tables()
    print(f"[hasura-init] Found {len(tables)} tables")
    track_tables(tables)

    print("[hasura-init] Discovering foreign-key relationships...")
    fk_rows = get_foreign_keys()
    print(f"[hasura-init] Found {len(fk_rows)} foreign keys")
    create_relationships(fk_rows)

    print("[hasura-init] Seeding idTags...")
    seed_id_tags()

    print("[hasura-init] Seeding EVSEs for operator UI...")
    seed_evses()

    print("[hasura-init] Metadata initialization complete")


if __name__ == "__main__":
    main()
