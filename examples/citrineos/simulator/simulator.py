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

"""OCPP 1.6J charge point simulator for CitrineOS integration testing.

Spawns multiple async charge point connections that connect to CitrineOS,
send BootNotification, and idle in wait-for-trigger mode. Responds to
RemoteStartTransaction, RemoteStopTransaction, and SetChargingProfile
commands from the CSMS.

When a SCENARIO_FILE is configured, automatically schedules charging sessions
with physics-based battery simulation (CC-CV charging curve, profile compliance).
"""

import asyncio
import json
import logging
import os
import signal
import sys
from dataclasses import dataclass
from datetime import datetime, timezone

import websockets
from ocpp.routing import on
from ocpp.v16 import ChargePoint as cp
from ocpp.v16 import call, call_result
from ocpp.v16.enums import (
    ChargePointErrorCode,
    ChargePointStatus,
    RegistrationStatus,
    RemoteStartStopStatus,
)

logger = logging.getLogger("simulator")


def _ocpp_timestamp() -> str:
    """Return current UTC timestamp in OCPP 1.6 format (ISO 8601 with Z suffix)."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Battery model
# ---------------------------------------------------------------------------

@dataclass
class EVBattery:
    """Physics-based EV battery model with CC-CV charging curve."""

    capacity_kwh: float = 60.0
    soc: float = 0.20
    target_soc: float = 1.0
    max_charge_rate_kw: float = 7.2
    voltage: float = 240.0

    def taper_rate_kw(self) -> float:
        """CC-CV curve: full power below 80% SoC, linear taper 80%->100%."""
        if self.soc <= 0.8:
            return self.max_charge_rate_kw
        return self.max_charge_rate_kw * (1.0 - self.soc) / 0.2

    def effective_power_kw(self, profile_limit_kw: float | None = None) -> float:
        """Compute actual charge power respecting profile limit and taper."""
        rate = min(self.max_charge_rate_kw, self.taper_rate_kw())
        if profile_limit_kw is not None:
            rate = min(rate, profile_limit_kw)
        return max(rate, 0.0)

    def step(self, power_kw: float, dt_seconds: float) -> float:
        """Advance SoC by charging at power_kw for dt_seconds. Returns actual Wh delivered."""
        if self.soc >= self.target_soc or power_kw <= 0:
            return 0.0
        dt_hours = dt_seconds / 3600.0
        old_soc = self.soc
        delta_soc = (power_kw * dt_hours) / self.capacity_kwh
        self.soc = min(old_soc + delta_soc, self.target_soc)
        actual_wh = (self.soc - old_soc) * self.capacity_kwh * 1000.0
        return actual_wh

    def is_target_reached(self) -> bool:
        """Return True if SOC has reached the target within tolerance."""
        return self.soc >= self.target_soc - 0.001

    @property
    def current_amperes(self) -> float:
        """Approximate current draw at nominal voltage."""
        return (self.effective_power_kw() * 1000.0) / self.voltage if self.voltage > 0 else 0.0

    @property
    def soc_percent(self) -> float:
        """Return current state of charge as a percentage."""
        return round(self.soc * 100.0, 1)


# ---------------------------------------------------------------------------
# Session scheduling
# ---------------------------------------------------------------------------

@dataclass
class SessionConfig:
    """Configuration for an auto-scheduled charging session."""

    station_id: str
    connector_id: int = 1
    arrive_offset_s: float = 0.0
    depart_offset_s: float = 3600.0
    capacity_kwh: float = 60.0
    arrival_soc: float = 0.20
    target_soc: float = 1.0
    max_charge_rate_kw: float = 7.2
    id_tag: str = "OPTIVGI-AUTO"
    auto_start: bool = True


def load_scenario(scenario_file: str | None = None) -> dict[str, list[SessionConfig]]:
    """Load scenario from JSON file. Returns {station_id: [SessionConfig, ...]}."""
    path = scenario_file or os.environ.get("SCENARIO_FILE", "")
    if not path:
        return {}

    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        logger.warning("[Simulator] Could not load scenario %s: %s", path, exc)
        return {}

    sessions: dict[str, list[SessionConfig]] = {}
    for entry in data.get("sessions", []):
        cfg = SessionConfig(
            station_id=entry["station_id"],
            connector_id=entry.get("connector_id", 1),
            arrive_offset_s=entry.get("arrive_offset_s", 0),
            depart_offset_s=entry.get("depart_offset_s", 3600),
            capacity_kwh=entry.get("capacity_kwh", 60.0),
            arrival_soc=entry.get("arrival_soc", 0.20),
            target_soc=entry.get("target_soc", 1.0),
            max_charge_rate_kw=entry.get("max_charge_rate_kw", 7.2),
            id_tag=entry.get("id_tag", "OPTIVGI-AUTO"),
            auto_start=entry.get("auto_start", True),
        )
        sessions.setdefault(cfg.station_id, []).append(cfg)

    logger.info(
        "[Simulator] Loaded scenario with %d sessions for %d stations",
        sum(len(v) for v in sessions.values()),
        len(sessions),
    )
    return sessions


# ---------------------------------------------------------------------------
# Charging profile resolution
# ---------------------------------------------------------------------------

def resolve_profile_limit_kw(profile: dict, voltage: float, elapsed_s: float) -> float | None:
    """Resolve the active power limit from a stored OCPP charging profile."""
    schedule = profile.get("chargingSchedule") or profile.get("charging_schedule")
    if not schedule:
        return None

    rate_unit = schedule.get("chargingRateUnit") or schedule.get("charging_rate_unit", "W")
    periods = (
        schedule.get("chargingSchedulePeriod")
        or schedule.get("charging_schedule_period")
        or []
    )
    if not periods:
        return None

    # Find the active period based on elapsed time
    active_period = periods[0]
    for period in periods:
        start = period.get("startPeriod") or period.get("start_period", 0)
        if start <= elapsed_s:
            active_period = period
        else:
            break

    limit = active_period.get("limit", 0)
    if rate_unit in ("A", "a"):
        return limit * voltage / 1000.0
    return limit / 1000.0


# ---------------------------------------------------------------------------
# Simulator
# ---------------------------------------------------------------------------

class ChargingSimulator(cp):
    """OCPP 1.6J charge point simulator with physics-based battery model.

    Connects to CitrineOS, sends BootNotification, and idles sending
    Heartbeat messages. Responds to RemoteStartTransaction,
    RemoteStopTransaction, and SetChargingProfile. When auto-sessions
    are configured, schedules arrivals/departures with realistic SoC
    progression.
    """

    def __init__(self, station_id, ws, num_connectors=2, meter_interval=10):
        super().__init__(station_id, ws)
        self.num_connectors = num_connectors
        self.meter_interval = meter_interval
        self._active_transactions = {}  # connector_id -> transaction_id
        self._meter_tasks = {}  # connector_id -> asyncio.Task
        self._meter_values = {}  # connector_id -> cumulative Wh
        self._batteries = {}  # connector_id -> EVBattery
        self._profile_limits = {}  # connector_id -> dict (raw profile)
        self._profile_start_times = {}  # connector_id -> datetime
        self._departure_tasks = {}  # connector_id -> asyncio.Task
        self._shutdown = asyncio.Event()

    async def send_boot_notification(self):
        """Send BootNotification and report connector status if accepted."""
        request = call.BootNotification(
            charge_point_model="Opti-VGI-Sim",
            charge_point_vendor="Opti-VGI",
        )
        response = await self.call(request)
        if response.status == RegistrationStatus.accepted:
            logger.info("[Simulator] %s: connected and accepted", self.id)
            for conn_id in range(1, self.num_connectors + 1):
                await self._send_status(conn_id, ChargePointStatus.available)
        else:
            logger.warning(
                "[Simulator] %s: BootNotification status=%s",
                self.id,
                response.status,
            )
        return response

    async def _send_status(self, connector_id, status):
        """Send StatusNotification for a connector."""
        request = call.StatusNotification(
            connector_id=connector_id,
            error_code=ChargePointErrorCode.no_error,
            status=status,
            timestamp=_ocpp_timestamp(),
        )
        await self.call(request)

    async def heartbeat_loop(self):
        """Send Heartbeat every 60 seconds until shutdown."""
        while not self._shutdown.is_set():
            try:
                await asyncio.wait_for(self._shutdown.wait(), timeout=60)
                break
            except asyncio.TimeoutError:
                await self.call(call.Heartbeat())

    # ------- OCPP handlers -------

    @on("RemoteStartTransaction")
    async def on_remote_start(self, connector_id, id_tag, **_kwargs):
        """Handle RemoteStartTransaction from CSMS."""
        logger.info(
            "[Simulator] %s: RemoteStart connector=%d id_tag=%s",
            self.id,
            connector_id,
            id_tag,
        )
        asyncio.create_task(self._start_charging(connector_id, id_tag))
        return call_result.RemoteStartTransaction(
            status=RemoteStartStopStatus.accepted
        )

    @on("RemoteStopTransaction")
    async def on_remote_stop(self, transaction_id, **_kwargs):
        """Handle RemoteStopTransaction from CSMS."""
        logger.info(
            "[Simulator] %s: RemoteStop transaction=%d", self.id, transaction_id
        )
        asyncio.create_task(self._stop_charging_by_transaction(transaction_id, reason="Remote"))
        return call_result.RemoteStopTransaction(
            status=RemoteStartStopStatus.accepted
        )

    @on("SetChargingProfile")
    async def on_set_charging_profile(self, connector_id, cs_charging_profiles, **_kwargs):
        """Handle SetChargingProfile from CSMS (used by Opti-VGI)."""
        self._profile_limits[connector_id] = cs_charging_profiles
        self._profile_start_times[connector_id] = datetime.now(timezone.utc)

        # Only log curtailment changes, not every repeated profile
        battery = self._batteries.get(connector_id)
        voltage = battery.voltage if battery else 240.0
        limit_kw = resolve_profile_limit_kw(cs_charging_profiles, voltage, 0.0)
        if battery is not None and limit_kw is not None:
            current_rate = battery.effective_power_kw()
            if limit_kw < current_rate:
                logger.info(
                    "[Simulator] %s: connector=%d curtailed %.2f kW -> %.2f kW",
                    self.id,
                    connector_id,
                    current_rate,
                    limit_kw,
                )
            else:
                logger.debug(
                    "[Simulator] %s: connector=%d profile limit=%.2f kW (current rate=%.2f kW)",
                    self.id,
                    connector_id,
                    limit_kw,
                    current_rate,
                )

        return call_result.SetChargingProfile(status="Accepted")

    # ------- Charging session management -------

    async def _start_charging(self, connector_id, id_tag, battery=None):
        """Begin a charging session on a connector."""
        if battery is None:
            battery = EVBattery()

        self._batteries[connector_id] = battery

        await self._send_status(connector_id, ChargePointStatus.preparing)
        await asyncio.sleep(1)  # Brief preparing state
        await self._send_status(connector_id, ChargePointStatus.charging)

        meter_start = 0
        response = await self.call(
            call.StartTransaction(
                connector_id=connector_id,
                id_tag=id_tag,
                meter_start=meter_start,
                timestamp=_ocpp_timestamp(),
            )
        )

        auth_status = response.id_tag_info.get("status", "") if isinstance(response.id_tag_info, dict) else getattr(response.id_tag_info, "status", "")
        if auth_status != "Accepted":
            logger.error(
                "[Simulator] %s: StartTransaction REJECTED on connector=%d "
                "(status=%s, transactionId=%d) — aborting session",
                self.id,
                connector_id,
                auth_status,
                response.transaction_id,
            )
            await self._send_status(connector_id, ChargePointStatus.available)
            self._batteries.pop(connector_id, None)
            return

        transaction_id = response.transaction_id
        self._active_transactions[connector_id] = transaction_id
        self._meter_values[connector_id] = meter_start

        logger.info(
            "[Simulator] %s: Started transaction=%d on connector=%d "
            "(SoC=%.1f%%, capacity=%.1f kWh, max_rate=%.1f kW)",
            self.id,
            transaction_id,
            connector_id,
            battery.soc_percent,
            battery.capacity_kwh,
            battery.max_charge_rate_kw,
        )

        task = asyncio.create_task(
            self._meter_values_loop(connector_id, transaction_id)
        )
        self._meter_tasks[connector_id] = task

    async def _stop_charging(self, connector_id, reason="Local"):
        """Stop a charging session on a connector."""
        # Pop transaction — also signals the meter loop to exit naturally
        # on its next iteration (it checks `connector_id in _active_transactions`).
        transaction_id = self._active_transactions.pop(connector_id, None)
        if transaction_id is None:
            return

        # Wait for meter loop to finish its current cycle gracefully
        # before sending anything else on the websocket.
        if connector_id in self._meter_tasks:
            task = self._meter_tasks.pop(connector_id)
            try:
                await asyncio.wait_for(task, timeout=self.meter_interval + 5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # Cancel departure watchdog
        if connector_id in self._departure_tasks:
            self._departure_tasks.pop(connector_id).cancel()

        meter_stop = self._meter_values.pop(connector_id, 0)
        battery = self._batteries.pop(connector_id, None)
        self._profile_limits.pop(connector_id, None)
        self._profile_start_times.pop(connector_id, None)

        await self._send_status(connector_id, ChargePointStatus.finishing)
        await self.call(
            call.StopTransaction(
                meter_stop=meter_stop,
                timestamp=_ocpp_timestamp(),
                transaction_id=transaction_id,
                reason=reason,
            )
        )
        await self._send_status(connector_id, ChargePointStatus.available)

        soc_str = f" SoC={battery.soc_percent}%" if battery else ""
        logger.info(
            "[Simulator] %s: Stopped transaction=%d reason=%s meter_stop=%d Wh%s",
            self.id,
            transaction_id,
            reason,
            meter_stop,
            soc_str,
        )

    async def _stop_charging_by_transaction(self, transaction_id, reason="Remote"):
        """Stop a charging session by transaction ID."""
        connector_id = None
        for cid, tid in self._active_transactions.items():
            if tid == transaction_id:
                connector_id = cid
                break

        if connector_id is None:
            logger.warning(
                "[Simulator] %s: transaction=%d not found", self.id, transaction_id
            )
            return

        await self._stop_charging(connector_id, reason=reason)

    # ------- MeterValues with physics -------

    async def _meter_values_loop(self, connector_id, transaction_id):
        """Send physics-based MeterValues at configured interval."""
        try:
            while connector_id in self._active_transactions:
                await asyncio.sleep(self.meter_interval)
                if connector_id not in self._active_transactions:
                    break

                battery = self._batteries.get(connector_id)
                if battery is None:
                    break

                # Resolve profile limit
                profile_limit_kw = None
                profile = self._profile_limits.get(connector_id)
                if profile:
                    start_time = self._profile_start_times.get(connector_id)
                    elapsed_s = 0.0
                    if start_time:
                        elapsed_s = (datetime.now(timezone.utc) - start_time).total_seconds()
                    profile_limit_kw = resolve_profile_limit_kw(
                        profile, battery.voltage, elapsed_s
                    )

                # Physics step
                power_kw = battery.effective_power_kw(profile_limit_kw)
                energy_wh = battery.step(power_kw, self.meter_interval)
                self._meter_values[connector_id] += round(energy_wh)
                cumulative_wh = self._meter_values[connector_id]

                power_w = round(power_kw * 1000.0, 1)
                current_a = round(power_kw * 1000.0 / battery.voltage, 2) if battery.voltage > 0 else 0
                voltage_v = round(battery.voltage, 1)
                soc_pct = battery.soc_percent

                await self.call(
                    call.MeterValues(
                        connector_id=connector_id,
                        transaction_id=transaction_id,
                        meter_value=[
                            {
                                "timestamp": _ocpp_timestamp(),
                                "sampledValue": [
                                    {
                                        "value": str(cumulative_wh),
                                        "context": "Sample.Periodic",
                                        "measurand": "Energy.Active.Import.Register",
                                        "unit": "Wh",
                                    },
                                    {
                                        "value": str(power_w),
                                        "context": "Sample.Periodic",
                                        "measurand": "Power.Active.Import",
                                        "unit": "W",
                                    },
                                    {
                                        "value": str(current_a),
                                        "context": "Sample.Periodic",
                                        "measurand": "Current.Import",
                                        "unit": "A",
                                    },
                                    {
                                        "value": str(voltage_v),
                                        "context": "Sample.Periodic",
                                        "measurand": "Voltage",
                                        "unit": "V",
                                    },
                                    {
                                        "value": str(soc_pct),
                                        "context": "Sample.Periodic",
                                        "measurand": "SoC",
                                        "unit": "Percent",
                                    },
                                ],
                            }
                        ],
                    )
                )

                # Auto-stop if target SoC reached
                if battery.is_target_reached():
                    logger.info(
                        "[Simulator] %s: connector=%d target SoC reached (%.1f%%)",
                        self.id,
                        connector_id,
                        soc_pct,
                    )
                    asyncio.create_task(
                        self._stop_charging(connector_id, reason="EVDisconnected")
                    )
                    break

        except asyncio.CancelledError:
            pass

    # ------- Auto-session scheduling -------

    async def schedule_sessions(self, session_configs: list[SessionConfig]):
        """Schedule auto-sessions from scenario configuration."""
        for cfg in session_configs:
            if not cfg.auto_start:
                continue
            asyncio.create_task(self._run_scheduled_session(cfg))

    async def _run_scheduled_session(self, cfg: SessionConfig):
        """Wait for arrival offset, start charging, schedule departure."""
        if cfg.arrive_offset_s > 0:
            logger.info(
                "[Simulator] %s: session on connector=%d arrives in %.0fs",
                self.id,
                cfg.connector_id,
                cfg.arrive_offset_s,
            )
            await asyncio.sleep(cfg.arrive_offset_s)

        battery = EVBattery(
            capacity_kwh=cfg.capacity_kwh,
            soc=cfg.arrival_soc,
            target_soc=cfg.target_soc,
            max_charge_rate_kw=cfg.max_charge_rate_kw,
        )

        await self._start_charging(cfg.connector_id, cfg.id_tag, battery=battery)

        # Schedule departure watchdog
        remaining = cfg.depart_offset_s - cfg.arrive_offset_s
        if remaining > 0:
            task = asyncio.create_task(
                self._departure_watchdog(cfg.connector_id, remaining)
            )
            self._departure_tasks[cfg.connector_id] = task

    async def _departure_watchdog(self, connector_id, duration_s):
        """Auto-stop the session after the departure time elapses."""
        try:
            await asyncio.sleep(duration_s)
            if connector_id in self._active_transactions:
                logger.info(
                    "[Simulator] %s: connector=%d departure time reached",
                    self.id,
                    connector_id,
                )
                # Remove ourselves from _departure_tasks BEFORE calling
                # _stop_charging, which would otherwise cancel this task
                # (itself) and abort the stop via CancelledError.
                self._departure_tasks.pop(connector_id, None)
                await self._stop_charging(connector_id, reason="EVDisconnected")
        except asyncio.CancelledError:
            pass

    def stop(self):
        """Signal shutdown."""
        self._shutdown.set()
        for task in self._meter_tasks.values():
            task.cancel()
        for task in self._departure_tasks.values():
            task.cancel()


# ---------------------------------------------------------------------------
# Station runner
# ---------------------------------------------------------------------------

async def run_station(ws_url, station_id, num_connectors, meter_interval,
                      session_configs=None):
    """Run a single charge point with exponential backoff retry."""
    delay = 1
    max_delay = 30

    while True:
        try:
            url = f"{ws_url}/{station_id}"
            logger.info("[Simulator] %s: Connecting to %s", station_id, url)
            async with websockets.connect(
                url, subprotocols=["ocpp1.6"]
            ) as ws:
                sim = ChargingSimulator(
                    station_id, ws, num_connectors, meter_interval
                )
                # Reset backoff on successful connection
                delay = 1

                coros = [
                    sim.start(),
                    sim.send_boot_notification(),
                    sim.heartbeat_loop(),
                ]

                if session_configs:
                    coros.append(sim.schedule_sessions(session_configs))

                await asyncio.gather(*coros)
        except (
            websockets.exceptions.ConnectionClosed,
            websockets.exceptions.InvalidStatusCode,
            ConnectionRefusedError,
            OSError,
        ) as exc:
            logger.warning(
                "[Simulator] %s: Connection failed (%s), retrying in %ds",
                station_id,
                exc,
                delay,
            )
            await asyncio.sleep(delay)
            delay = min(delay * 2, max_delay)
        except asyncio.CancelledError:
            logger.info("[Simulator] %s: Shutting down", station_id)
            break


# ---------------------------------------------------------------------------
# Startup cleanup
# ---------------------------------------------------------------------------

def _cleanup_stale_transactions():
    """Delete orphan transactions from previous simulator runs.

    Connects directly to the CitrineOS Postgres database and removes all
    MeterValues, Transactions, StartTransactions, and StopTransactions so
    that new StartTransaction requests don't get rejected with ConcurrentTx.
    """
    db_host = os.environ.get("DB_HOST", "ocpp-db")
    db_port = os.environ.get("DB_PORT", "5432")
    db_name = os.environ.get("DB_NAME", "citrine")
    db_user = os.environ.get("DB_USER", "citrine")
    db_pass = os.environ.get("DB_PASS", "citrine")

    try:
        import psycopg2  # pylint: disable=import-outside-toplevel
        conn = psycopg2.connect(
            host=db_host, port=db_port, dbname=db_name,
            user=db_user, password=db_pass,
        )
        conn.autocommit = True
        cur = conn.cursor()

        # TRUNCATE resets auto-increment sequences so CitrineOS assigns
        # unique transaction IDs.  CASCADE handles foreign-key deps.
        cur.execute(
            'TRUNCATE "MeterValues", "StopTransactions", '
            '"StartTransactions", "Transactions", '
            '"ChargingProfiles", "ChargingSchedules", '
            '"OCPPMessages" RESTART IDENTITY CASCADE'
        )
        logger.info("[Simulator] Truncated transaction tables (sequences reset)")

        cur.close()
        conn.close()
        logger.info("[Simulator] Stale transaction cleanup complete")
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.warning("[Simulator] Could not clean stale transactions: %s", exc)


def _link_connectors_to_evses():
    """Link Connector rows to their corresponding EVSE rows in the DB.

    OCPP 1.6 StatusNotification creates Connectors without an evseId FK.
    The operator UI reads charger activity through the Evses->Connectors
    relationship, so this link is required for the dashboard to work.
    """
    db_host = os.environ.get("DB_HOST", "ocpp-db")
    db_port = os.environ.get("DB_PORT", "5432")
    db_name = os.environ.get("DB_NAME", "citrine")
    db_user = os.environ.get("DB_USER", "citrine")
    db_pass = os.environ.get("DB_PASS", "citrine")

    try:
        import psycopg2  # pylint: disable=import-outside-toplevel
        conn = psycopg2.connect(
            host=db_host, port=db_port, dbname=db_name,
            user=db_user, password=db_pass,
        )
        conn.autocommit = True
        cur = conn.cursor()

        cur.execute(
            'UPDATE "Connectors" c '
            'SET "evseId" = e."id" '
            'FROM "Evses" e '
            'WHERE e."stationId" = c."stationId" '
            'AND e."evseId"::int = c."connectorId" '
            'AND c."evseId" IS NULL'
        )
        if cur.rowcount > 0:
            logger.info(
                "[Simulator] Linked %d connectors to EVSEs", cur.rowcount
            )

        # Also patch StatusNotifications so the operator UI can match
        # them to EVSEs (it joins on statusNotification.evseId == evse.evseTypeId).
        cur.execute(
            'UPDATE "StatusNotifications" sn '
            'SET "evseId" = e."evseId"::int '
            'FROM "Evses" e '
            'WHERE e."stationId" = sn."stationId" '
            'AND e."evseId"::int = sn."connectorId" '
            'AND sn."evseId" IS NULL'
        )
        if cur.rowcount > 0:
            logger.info(
                "[Simulator] Patched %d StatusNotifications with evseId",
                cur.rowcount,
            )

        # OCPP 1.6 StartTransaction doesn't set chargingState (2.0.1 field).
        # The operator UI shows "N/A" when it's null — set it for active txns.
        cur.execute(
            'UPDATE "Transactions" '
            'SET "chargingState" = \'Charging\' '
            'WHERE "isActive" = true AND "chargingState" IS NULL'
        )
        if cur.rowcount > 0:
            logger.info(
                "[Simulator] Set chargingState on %d active transactions",
                cur.rowcount,
            )

        cur.close()
        conn.close()
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.warning("[Simulator] Could not link connectors to EVSEs: %s", exc)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main():
    """Entry point: spawn one async task per station ID."""
    _cleanup_stale_transactions()

    ws_url = os.environ.get("CITRINEOS_WS_URL", "ws://citrineos:8092")
    station_ids_str = os.environ.get(
        "STATION_IDS",
        "OPTIVGI-STATION-01,OPTIVGI-STATION-02,OPTIVGI-STATION-03,"
        "OPTIVGI-STATION-04,OPTIVGI-STATION-05,OPTIVGI-STATION-06",
    )
    station_ids = [s.strip() for s in station_ids_str.split(",") if s.strip()]
    num_connectors = int(os.environ.get("CONNECTORS_PER_STATION", "2"))
    meter_interval = int(os.environ.get("METER_VALUES_INTERVAL", "10"))

    # Load scenario for auto-sessions
    scenario = load_scenario()

    logger.info(
        "[Simulator] Starting %d stations: %s", len(station_ids), station_ids
    )
    logger.info(
        "[Simulator] WebSocket URL: %s, Connectors: %d, MeterValues interval: %ds",
        ws_url,
        num_connectors,
        meter_interval,
    )
    if scenario:
        logger.info("[Simulator] Auto-session mode: %d stations with scenarios",
                     len(scenario))
    else:
        logger.info("[Simulator] Wait-for-trigger mode (no scenario file)")

    tasks = [
        asyncio.create_task(
            run_station(
                ws_url, sid, num_connectors, meter_interval,
                session_configs=scenario.get(sid),
            )
        )
        for sid in station_ids
    ]

    # After stations connect and send StatusNotification, link the
    # resulting Connector rows to their EVSE rows so the operator
    # dashboard can display charger activity correctly.
    async def _delayed_link():
        await asyncio.sleep(30)  # wait for all stations to boot
        _link_connectors_to_evses()

    asyncio.create_task(_delayed_link())

    # Graceful shutdown on SIGINT/SIGTERM
    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()

    def _signal_handler():
        logger.info("[Simulator] Received shutdown signal")
        shutdown_event.set()
        for t in tasks:
            t.cancel()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    try:
        await asyncio.gather(*tasks, return_exceptions=True)
    except asyncio.CancelledError:
        pass

    logger.info("[Simulator] All stations stopped")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
    )
    # Suppress raw OCPP send/receive message logging from ocpp library
    logging.getLogger("ocpp").setLevel(logging.WARNING)
    asyncio.run(main())
