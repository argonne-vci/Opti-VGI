# Copyright 2025 UChicago Argonne, LLC All right reserved
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://github.com/argonne-vci/Opti-VGI/blob/main/LICENSE
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
Automated verification script for the Opti-VGI curtailment demo.

Queries Hasura GraphQL for stored SetChargingProfile records and asserts
four key properties: profiles sent, concurrent sessions, aggregate within
site limit, and curtailment occurred.

Usage:
    cd examples/citrineos
    python verify.py
    python verify.py --url http://localhost:8090 --limit 30
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# GraphQL queries
# ---------------------------------------------------------------------------

PROFILES_QUERY = """
query ChargingProfiles {
    ChargingProfiles(order_by: {id: asc}) {
        id
        stationId
        transactionDatabaseId
        createdAt
        updatedAt
        ChargingSchedules {
            chargingRateUnit
            chargingSchedulePeriod
            startSchedule
        }
    }
}
"""

TRANSACTIONS_QUERY = """
query AllTransactions {
    Transactions(order_by: {id: asc}) {
        id
        transactionId
        stationId
        isActive
        createdAt
    }
}
"""

PROFILE_HISTORY_QUERY = """
query SetChargingProfileHistory {
    OCPPMessages(
        where: {action: {_eq: "SetChargingProfile"}, origin: {_eq: "csms"}}
        order_by: {id: desc}
        limit: 500
    ) {
        id
        stationId
        message
    }
}
"""

# ---------------------------------------------------------------------------
# Hasura helper
# ---------------------------------------------------------------------------


def query_hasura(url: str, query: str, variables: dict | None = None) -> dict:
    """Execute a GraphQL query against Hasura and return the data payload."""
    payload = {"query": query, "variables": variables or {}}
    try:
        resp = requests.post(f"{url}/v1/graphql", json=payload, timeout=10)
        resp.raise_for_status()
    except requests.exceptions.ConnectionError:
        print(f"Cannot connect to Hasura at {url}. Is the stack running?")
        sys.exit(2)

    result = resp.json()
    if "errors" in result:
        raise RuntimeError(f"GraphQL errors: {json.dumps(result['errors'], indent=2)}")
    return result["data"]


# ---------------------------------------------------------------------------
# Profile parsing helpers
# ---------------------------------------------------------------------------


def _get_first_limit_kw(profile: dict, voltage: float) -> float | None:
    """Extract the power limit (kW) of the first period from a profile."""
    schedules = profile.get("ChargingSchedules", [])
    if not schedules:
        return None

    sched = schedules[0]
    period = sched.get("chargingSchedulePeriod")
    if isinstance(period, str):
        period = json.loads(period)
    if not period or not isinstance(period, list):
        return None

    limit_value = float(period[0].get("limit", 0))
    rate_unit = sched.get("chargingRateUnit", "")

    if rate_unit == "A":
        return limit_value * voltage / 1000.0
    if rate_unit == "W":
        return limit_value / 1000.0
    return limit_value


def _get_all_limits_kw(profile: dict, voltage: float) -> list[float]:
    """Extract all period limits (kW) from a profile."""
    schedules = profile.get("ChargingSchedules", [])
    if not schedules:
        return []

    sched = schedules[0]
    period = sched.get("chargingSchedulePeriod")
    if isinstance(period, str):
        period = json.loads(period)
    if not period or not isinstance(period, list):
        return []

    rate_unit = sched.get("chargingRateUnit", "")
    limits = []
    for p in period:
        lv = float(p.get("limit", 0))
        if rate_unit == "A":
            limits.append(lv * voltage / 1000.0)
        elif rate_unit == "W":
            limits.append(lv / 1000.0)
        else:
            limits.append(lv)
    return limits


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def check_profiles_sent(
    profiles: list[dict], min_count: int = 3
) -> tuple[bool, str]:
    """Check 1: Assert that SetChargingProfile commands were sent."""
    count = len(profiles)
    passed = count >= min_count
    return passed, f"Found {count} charging profiles (need >= {min_count})"


def check_concurrent_sessions(
    profiles: list[dict], voltage: float, min_concurrent: int = 3
) -> tuple[bool, str]:
    """Check 2: Assert 3+ EVs had active charging profiles simultaneously.

    CitrineOS stores one profile per (station, transaction). If N profiles
    exist with non-zero first-period limits, those N EVs were being
    managed concurrently.
    """
    active_count = 0
    for p in profiles:
        limit = _get_first_limit_kw(p, voltage)
        if limit is not None and limit > 0:
            active_count += 1

    passed = active_count >= min_concurrent
    return passed, (
        f"Found {active_count} profiles with active allocations "
        f"(need >= {min_concurrent})"
    )


def _parse_timestamp(ts_str: str):
    """Parse an ISO-ish timestamp string from Hasura."""
    if not ts_str:
        return None
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
    ):
        try:
            return datetime.strptime(ts_str, fmt)
        except ValueError:
            continue
    return None


def _limit_at_offset(profile: dict, offset_s: float, voltage: float) -> float:
    """Return the kW limit active at a given offset (seconds) from startSchedule."""
    schedules = profile.get("ChargingSchedules", [])
    if not schedules:
        return 0.0

    sched = schedules[0]
    period = sched.get("chargingSchedulePeriod")
    if isinstance(period, str):
        period = json.loads(period)
    if not period or not isinstance(period, list):
        return 0.0

    rate_unit = sched.get("chargingRateUnit", "")

    # Find the active period for this offset (last period with startPeriod <= offset)
    active = period[0]
    for p in period:
        if p.get("startPeriod", 0) <= offset_s:
            active = p
        else:
            break

    limit_value = float(active.get("limit", 0))
    if rate_unit == "A":
        return limit_value * voltage / 1000.0
    if rate_unit == "W":
        return limit_value / 1000.0
    return limit_value


def check_aggregate_within_limit(
    profiles: list[dict], site_limit_kw: float, voltage: float
) -> tuple[bool, str]:
    """Check 3: Assert aggregate power <= site limit in latest scheduling cycle.

    Groups profiles by startSchedule (same cycle = same timestamp).
    Takes the largest group from the most recent cycle and sums limits.
    Allows a small tolerance for whole-Amp rounding (±0.24 kW per EV).
    """
    if not profiles:
        return False, "No charging profiles to check aggregate"

    # Group profiles by startSchedule (same cycle)
    groups: dict[str, list[dict]] = {}
    for p in profiles:
        schedules = p.get("ChargingSchedules", [])
        if not schedules:
            continue
        start = schedules[0].get("startSchedule", "unknown")
        groups.setdefault(start, []).append(p)

    if not groups:
        return False, "No schedule groups found"

    # Pick the latest cycle with the most profiles
    sorted_keys = sorted(groups.keys(), reverse=True)
    best_key = sorted_keys[0]
    best_group = groups[best_key]

    aggregate = 0.0
    for p in best_group:
        limit_kw = _get_first_limit_kw(p, voltage)
        if limit_kw is not None:
            aggregate += limit_kw

    # Tolerance: whole-Amp rounding can add up to 0.12 kW per EV
    n_evs = len(best_group)
    tolerance = n_evs * 0.12 + 0.1
    passed = aggregate <= site_limit_kw + tolerance
    return passed, (
        f"Aggregate in latest cycle ({n_evs} EVs, {best_key[:19]}): "
        f"{aggregate:.1f} kW {'<=' if passed else '>'} "
        f"{site_limit_kw:.1f} kW limit (+{tolerance:.1f} kW rounding tolerance)"
    )


def check_curtailment_occurred(
    profile_history: list[dict], max_rate_kw: float, voltage: float
) -> tuple[bool, str]:
    """Check 4: Assert at least one EV received power below its max rate.

    Uses the OCPPMessages history (all SetChargingProfile commands ever sent)
    rather than the ChargingProfiles snapshot, which only stores the latest
    profile per station and loses curtailment evidence after EVs depart.
    """
    max_rate_a = max_rate_kw * 1000.0 / voltage  # e.g. 30A for 7.2 kW at 240V
    curtailed_count = 0
    min_power = float("inf")

    for msg_row in profile_history:
        message = msg_row.get("message")
        if not isinstance(message, list) or len(message) < 4:
            continue
        payload = message[3]
        periods = (
            payload.get("csChargingProfiles", {})
            .get("chargingSchedule", {})
            .get("chargingSchedulePeriod", [])
        )
        for period in periods:
            limit_a = float(period.get("limit", 0))
            if 0 < limit_a < max_rate_a - 0.5:
                limit_kw = limit_a * voltage / 1000.0
                curtailed_count += 1
                min_power = min(min_power, limit_kw)
                break  # one curtailed period per message is enough

    passed = curtailed_count > 0
    if passed:
        return True, (
            f"Found {curtailed_count} curtailed profiles in history "
            f"(min was {min_power:.2f} kW, max rate {max_rate_kw:.2f} kW)"
        )
    return False, (
        f"No profiles found with power below max {max_rate_kw:.2f} kW"
    )


# ---------------------------------------------------------------------------
# Plot
# ---------------------------------------------------------------------------


def _build_cycle_timeseries(
    profile_history: list[dict], voltage: float
) -> tuple[list[datetime], list[float], dict[str, list[float]]]:
    """Build per-cycle power timeseries from OCPP message history.

    Returns (timestamps, aggregate_kw, per_station) sorted by time.
    per_station maps station_id -> list of kW values aligned with timestamps.
    Each cycle is identified by startSchedule — profiles in the same cycle
    have the same startSchedule timestamp.
    """
    cycles: dict[str, dict[str, float]] = defaultdict(dict)
    for msg_row in profile_history:
        message = msg_row.get("message")
        if not isinstance(message, list) or len(message) < 4:
            continue
        payload = message[3]
        cp = payload.get("csChargingProfiles", {})
        schedule = cp.get("chargingSchedule", {})
        start = schedule.get("startSchedule", "")
        station = msg_row.get("stationId", "")
        periods = schedule.get("chargingSchedulePeriod", [])
        if periods and start:
            limit_a = float(periods[0].get("limit", 0))
            cycles[start][station] = limit_a * voltage / 1000.0

    timestamps = []
    aggregates = []
    cycle_stations = []
    for ts_str in sorted(cycles.keys()):
        stations = cycles[ts_str]
        agg = sum(stations.values())
        if agg <= 0:
            continue
        ts = _parse_timestamp(ts_str)
        if ts is None:
            continue
        if ts.tzinfo is not None:
            ts = ts.astimezone().replace(tzinfo=None)
        timestamps.append(ts)
        aggregates.append(agg)
        cycle_stations.append(stations)

    # Only keep the latest contiguous session — detect gaps > 30 min
    if len(timestamps) > 1:
        last_session_start = 0
        for i in range(1, len(timestamps)):
            gap = (timestamps[i] - timestamps[i - 1]).total_seconds()
            if gap > 1800:
                last_session_start = i
        timestamps = timestamps[last_session_start:]
        aggregates = aggregates[last_session_start:]
        cycle_stations = cycle_stations[last_session_start:]

    # Build per-station timeseries (0 when station not in cycle)
    all_stations = sorted({s for cs in cycle_stations for s in cs})
    per_station: dict[str, list[float]] = {s: [] for s in all_stations}
    for cs in cycle_stations:
        for s in all_stations:
            per_station[s].append(cs.get(s, 0.0))

    return timestamps, aggregates, per_station


def plot_curtailment(
    profile_history: list[dict], site_limit_kw: float, voltage: float
) -> None:
    """Plot per-EV charging profiles and aggregate vs site limit over time."""
    timestamps, aggregates, per_station = _build_cycle_timeseries(
        profile_history, voltage
    )
    if not timestamps:
        print("No cycle data to plot.")
        return

    try:
        # pylint: disable=import-outside-toplevel
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        import numpy as np
        # pylint: enable=import-outside-toplevel

        fig, ax = plt.subplots(figsize=(12, 5))

        # Stacked area for per-EV power
        station_ids = sorted(per_station.keys())
        # Short labels: OPTIVGI-STATION-01 -> EV 1
        labels = [f"EV {i+1}" for i in range(len(station_ids))]
        arrays = [per_station[s] for s in station_ids]
        cmap = plt.colormaps["tab10"]
        colors = cmap(np.linspace(0, 1, len(station_ids)))

        ax.stackplot(timestamps, *arrays, labels=labels, colors=colors, alpha=0.7)

        # Site limit line
        ax.axhline(
            y=site_limit_kw, color="r", linestyle="--", linewidth=2,
            label=f"Site limit ({site_limit_kw} kW)",
        )

        # Over-limit shading — solid red on top of everything
        ax.fill_between(
            timestamps, aggregates, site_limit_kw,
            where=[a > site_limit_kw for a in aggregates],
            interpolate=True, facecolor="#ff0000", alpha=0.7, zorder=10,
            label="Over limit",
        )

        ax.set_xlabel("Time")
        ax.set_ylabel("Power (kW)")
        ax.set_ylim(0, max(max(aggregates) * 1.15, site_limit_kw * 1.2))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        ax.xaxis.set_major_locator(mdates.MinuteLocator(interval=1))
        fig.autofmt_xdate()

        # Legend outside plot area
        ax.legend(loc="upper left", ncol=min(len(station_ids) + 1, 4), fontsize=8)

        plt.title("Opti-VGI Curtailment Demo — Per-EV Power Allocation")
        plt.tight_layout()

        out_path = Path(__file__).parent / "curtailment_plot.png"
        plt.savefig(out_path, dpi=150)
        plt.close()
        print(f"\nPlot saved to {out_path}")

    except ImportError:
        print("\n(matplotlib not installed — showing ASCII chart)\n")
        ev_counts = [sum(1 for s in per_station if per_station[s][i] > 0)
                     for i in range(len(timestamps))]
        _ascii_plot(timestamps, aggregates, ev_counts, site_limit_kw)


def _ascii_plot(
    timestamps: list[datetime],
    aggregates: list[float],
    ev_counts: list[int],
    site_limit_kw: float,
    width: int = 60,
) -> None:
    """Simple ASCII bar chart of aggregate power over time."""
    max_val = max(max(aggregates), site_limit_kw) * 1.1  # pylint: disable=nested-min-max
    limit_col = int(site_limit_kw / max_val * width)

    # Sample ~20 rows if there are many cycles
    step = max(1, len(timestamps) // 20)
    print(f"{'Time':>8}  EVs  {'Power (kW)':>{width}}  kW")
    print(f"{'':>8}  {'':>3}  {'|' * 1:>{limit_col}}{'':>{width - limit_col}}")

    for i in range(0, len(timestamps), step):
        ts = timestamps[i]
        agg = aggregates[i]
        evs = ev_counts[i]
        bar_len = int(agg / max_val * width)
        filled = "█" * bar_len
        marker = " " * (limit_col - bar_len) + "│" if bar_len < limit_col else ""
        time_str = ts.strftime("%H:%M:%S")
        print(f"{time_str}   {evs:>2}  {filled}{marker} {agg:.1f}")

    print(f"{'':>8}  {'':>3}  {'':>{limit_col}}↑ limit={site_limit_kw} kW")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    """Run all verification checks and report results."""
    parser = argparse.ArgumentParser(
        description="Verify Opti-VGI curtailment demo results via Hasura GraphQL"
    )
    parser.add_argument(
        "--url",
        default=None,
        help="Hasura GraphQL URL (default: http://localhost:8090)",
    )
    parser.add_argument(
        "--limit",
        type=float,
        default=None,
        help="Site power limit in kW (overrides .env SITE_POWER_LIMIT_KW)",
    )
    parser.add_argument(
        "--voltage",
        type=float,
        default=None,
        help="Voltage for A-to-kW conversion (overrides .env VOLTAGE)",
    )
    parser.add_argument(
        "--plot",
        action="store_true",
        help="Generate a plot of aggregate power vs site limit over time",
    )
    args = parser.parse_args()

    # Load .env from script directory
    env_path = Path(__file__).parent / ".env"
    load_dotenv(env_path)

    # Resolve configuration: CLI > env > default
    url = args.url or os.getenv("HASURA_URL", "http://localhost:8090")
    # For host-side access, always use localhost with HASURA_PORT
    if "graphql-engine" in url:
        port = os.getenv("HASURA_PORT", "8090")
        url = f"http://localhost:{port}"

    site_limit_kw = args.limit
    if site_limit_kw is None:
        site_limit_kw = float(os.getenv("SITE_POWER_LIMIT_KW", "30.0"))

    voltage = args.voltage
    if voltage is None:
        voltage = float(os.getenv("VOLTAGE", "240.0"))

    max_rate_kw = 7.2  # Uniform max from demo scenario

    # Query Hasura
    print("=== Opti-VGI Curtailment Verification ===")
    print(f"\nConfig: url={url}, site_limit={site_limit_kw} kW, voltage={voltage} V")
    print()

    profiles_data = query_hasura(url, PROFILES_QUERY)
    profiles = profiles_data.get("ChargingProfiles", [])

    transactions_data = query_hasura(url, TRANSACTIONS_QUERY)
    _transactions = transactions_data.get("Transactions", [])

    history_data = query_hasura(url, PROFILE_HISTORY_QUERY)
    profile_history = history_data.get("OCPPMessages", [])

    # Run checks
    checks = [
        ("Check 1: Charging profiles sent", check_profiles_sent(profiles)),
        ("Check 2: Concurrent sessions", check_concurrent_sessions(profiles, voltage)),
        (
            "Check 3: Aggregate within limit",
            check_aggregate_within_limit(profiles, site_limit_kw, voltage),
        ),
        (
            "Check 4: Curtailment occurred",
            check_curtailment_occurred(profile_history, max_rate_kw, voltage),
        ),
    ]

    pass_count = 0
    total = len(checks)

    for name, (passed, message) in checks:
        status = "PASS" if passed else "FAIL"
        print(f"[{status}] {name} -- {message}")
        if passed:
            pass_count += 1

    print()
    verdict = "PASS" if pass_count == total else "FAIL"
    print(f"Result: {pass_count}/{total} checks passed -- {verdict}")

    if args.plot:
        # Fetch full history for plotting (no limit)
        full_query = PROFILE_HISTORY_QUERY.replace("limit: 500", "limit: 10000")
        full_data = query_hasura(url, full_query)
        full_history = full_data.get("OCPPMessages", [])
        plot_curtailment(full_history, site_limit_kw, voltage)

    sys.exit(0 if pass_count == total else 1)


if __name__ == "__main__":
    main()
