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
CitrineOS Translation Layer implementation.

Bridges Opti-VGI's SCM algorithm with CitrineOS by querying Hasura GraphQL
for active transactions, meter values, and connector status. Builds EV
dataclass instances for the optimization algorithm.
"""
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

from optivgi.translation import Translation
from optivgi.scm.ev import EV, ChargingRateUnit
from optivgi.scm.constants import AlgorithmConstants

from .graphql_queries import ACTIVE_TRANSACTIONS_QUERY, CONNECTOR_STATUS_QUERY

logger = logging.getLogger(__name__)


class CitrineOSTranslation(Translation):
    """Translation Layer that reads EV data from CitrineOS via Hasura GraphQL.

    Queries active transactions, filters by connector charging status and
    MeterValues current, calculates remaining energy, and builds EV dataclass
    instances for the SCM algorithm.
    """

    def __init__(self):
        """Initialize CitrineOSTranslation from environment variables.

        Loads service URLs, voltage, site power limit, station IDs, and
        per-connector configuration (CONN_01_* through CONN_99_*).
        """
        self.citrineos_url = os.getenv("CITRINEOS_API_URL", "http://citrineos:8080")
        self.hasura_url = os.getenv("HASURA_URL", "http://graphql-engine:8080")
        self.voltage = float(os.getenv("VOLTAGE", "240"))
        self.site_power_limit = float(os.getenv("SITE_POWER_LIMIT_KW", "50"))

        # Parse station IDs list
        station_ids_str = os.getenv("STATION_IDS", "")
        self.station_ids = [s.strip() for s in station_ids_str.split(",") if s.strip()]

        # Build per-connector config by scanning CONN_XX_* env vars
        self.connector_configs = {}
        self._build_connector_configs()

        # Maps ev_id -> transaction metadata for send_power_to_evs
        self.transaction_map = {}

        logger.info(
            "CitrineOSTranslation initialized: hasura=%s, voltage=%.0f, "
            "site_power_limit=%.1f kW, connectors=%d",
            self.hasura_url, self.voltage, self.site_power_limit,
            len(self.connector_configs),
        )

    def _build_connector_configs(self):
        """Scan environment for CONN_XX_* variables and build connector configs.

        Each connector N maps to station_ids[N-1] with connector_id=1
        (one active connector per EVSE in OCPP 1.6J).
        """
        # Find all connector numbers defined in env
        conn_pattern = re.compile(r"^CONN_(\d+)_ENERGY_NEEDED_KWH$")
        for key in os.environ:
            match = conn_pattern.match(key)
            if not match:
                continue

            num = match.group(1)  # e.g., "01", "02"
            idx = int(num) - 1    # 0-based index into station_ids

            if idx >= len(self.station_ids):
                logger.warning(
                    "CONN_%s configured but no station at index %d (only %d stations)",
                    num, idx, len(self.station_ids),
                )
                continue

            station_id = self.station_ids[idx]
            connector_id = 1  # Each station has 1 active connector

            self.connector_configs[(station_id, connector_id)] = {
                "connector_num": num,
                "station_id": station_id,
                "connector_id": connector_id,
                "station_index": idx,
                "energy_needed_kwh": float(os.getenv(f"CONN_{num}_ENERGY_NEEDED_KWH", "30")),
                "max_power_kw": float(os.getenv(f"CONN_{num}_MAX_POWER_KW", "7.2")),
                "min_power_kw": float(os.getenv(f"CONN_{num}_MIN_POWER_KW", "1.4")),
                "arrival_time": os.getenv(f"CONN_{num}_ARRIVAL_TIME", "06:00"),
                "departure_time": os.getenv(f"CONN_{num}_DEPARTURE_TIME", "14:00"),
            }

        logger.info("Loaded %d connector configs", len(self.connector_configs))

    def __enter__(self):
        """Enter the runtime context for the CitrineOS translation layer."""
        logger.info("Entering CitrineOS Translation Layer")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit the runtime context and perform cleanup."""
        logger.info("Exiting CitrineOS Translation Layer")

    def _graphql_query(self, query: str, variables: dict = None) -> dict:
        """Execute a GraphQL query against the Hasura endpoint.

        Args:
            query: The GraphQL query string.
            variables: Optional variables dict for parameterized queries.

        Returns:
            The 'data' portion of the GraphQL response.

        Raises:
            RuntimeError: If the response contains GraphQL errors.
            requests.HTTPError: If the HTTP request fails.
        """
        payload = {"query": query, "variables": variables or {}}
        resp = requests.post(
            f"{self.hasura_url}/v1/graphql",
            json=payload,
            timeout=10,
        )
        resp.raise_for_status()
        result = resp.json()

        if "errors" in result:
            raise RuntimeError(f"GraphQL errors: {result['errors']}")

        return result["data"]

    def _is_connector_charging(self, station_id: str, connector_id: int) -> bool:
        """Check if the latest StatusNotification for a connector indicates Charging.

        Args:
            station_id: The OCPP station identifier string.
            connector_id: The connector number on the station.

        Returns:
            True if the latest status is 'Charging', False otherwise.
        """
        try:
            data = self._graphql_query(
                CONNECTOR_STATUS_QUERY,
                {"stationId": station_id, "connectorId": connector_id},
            )
            notifications = data.get("StatusNotifications", [])
            if not notifications:
                logger.debug(
                    "No StatusNotification for station=%s connector=%d",
                    station_id, connector_id,
                )
                return False
            return notifications[0].get("connectorStatus") == "Charging"
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error(
                "Error checking connector status for station=%s connector=%d: %s",
                station_id, connector_id, repr(e),
            )
            return False

    def _resolve_time(self, time_str: str, now: datetime) -> datetime:
        """Resolve an HH:MM time string to an absolute datetime using today's date.

        Args:
            time_str: Time in HH:MM format (e.g., '06:00', '14:30').
            now: Reference datetime for determining the date.

        Returns:
            A timezone-aware datetime combining today's date with the given time.
        """
        hour, minute = map(int, time_str.split(":"))
        return now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    def _build_ev(
        self, txn: dict, connector_config: dict, connector_key: tuple
    ) -> Optional[EV]:
        """Build an EV dataclass instance from a transaction and connector config.

        Filters out EVs that are not actively charging (requires both
        MeterValues current > 0 AND StatusNotification status == Charging).

        Args:
            txn: Transaction dict from the Hasura GraphQL response.
            connector_config: Per-connector configuration dict.
            connector_key: Tuple of (station_id, connector_id).

        Returns:
            An EV instance if the connector is actively charging, None otherwise.
        """
        now = datetime.now(timezone.utc)
        station_id = txn["stationId"]
        connector_id = connector_key[1]  # OCPP connector number from caller

        # Extract latest MeterValues
        meter_values = txn.get("MeterValues", [])
        cumulative_wh = 0.0

        if meter_values:
            sampled_value = meter_values[0].get("sampledValue", [])
            # sampledValue may be stored as JSON string or list
            if isinstance(sampled_value, str):
                try:
                    sampled_value = json.loads(sampled_value)
                except (json.JSONDecodeError, TypeError):
                    sampled_value = []

            for sv in sampled_value:
                measurand = sv.get("measurand", "")
                value = float(sv.get("value", 0))
                if measurand == "Energy.Active.Import.Register":
                    cumulative_wh = value
                elif measurand == "Current.Import":
                    _ = value  # parsed but not yet used

        # Filter: connector must have Charging status
        if not self._is_connector_charging(station_id, connector_id):
            logger.debug(
                "Skipping txn %s: connector status is not Charging",
                txn.get("transactionId"),
            )
            return None

        # Calculate remaining energy
        configured_energy_kwh = connector_config["energy_needed_kwh"]
        remaining_energy = max(0.0, configured_energy_kwh - (cumulative_wh / 1000.0))

        # Use transaction start time as arrival (works at any time of day).
        # Fall back to configured time if startTime is missing.
        start_time_str = txn.get("startTime")
        if start_time_str:
            arrival_time = datetime.fromisoformat(
                start_time_str.replace("Z", "+00:00")
            )
        else:
            arrival_time = self._resolve_time(connector_config["arrival_time"], now)

        # Set departure far enough ahead to cover the full planning horizon
        departure_time = max(
            self._resolve_time(connector_config["departure_time"], now),
            now + timedelta(hours=8),
        )

        ev_id = txn["id"]  # DB primary key (integer)
        station_index = connector_config["station_index"]

        # Store transaction metadata for send_power_to_evs
        self.transaction_map[ev_id] = {
            "transactionId": txn["transactionId"],
            "stationId": station_id,
        }

        return EV(
            ev_id=ev_id,
            active=True,
            station_id=station_index,
            connector_id=connector_id,
            min_power=connector_config["min_power_kw"],
            max_power=connector_config["max_power_kw"],
            arrival_time=arrival_time,
            departure_time=departure_time,
            energy=remaining_energy,
            unit=ChargingRateUnit.W,
            voltage=self.voltage,
        )

    def get_evs(self, group_name: str) -> tuple[list[EV], Optional[float]]:
        """Fetch active EVs from CitrineOS via Hasura GraphQL.

        Queries active transactions, matches them to configured connectors,
        filters by charging status and current, and builds EV instances.

        Args:
            group_name: The station group identifier (accepted for interface
                compliance; all connectors are treated as one group).

        Returns:
            A tuple of (list of EV instances, voltage).
        """
        evs = []
        try:
            data = self._graphql_query(ACTIVE_TRANSACTIONS_QUERY)
            transactions = data.get("Transactions", [])
            logger.debug(
                "Found %d active transactions for group '%s'",
                len(transactions), group_name,
            )

            for txn in transactions:
                # Resolve OCPP connector number from the Connector relationship
                # (Transaction.connectorId is a FK to Connectors.id, not the OCPP number)
                connector = txn.get("Connector") or {}
                ocpp_connector_id = connector.get("connectorId", 1)
                key = (txn["stationId"], ocpp_connector_id)
                config = self.connector_configs.get(key)
                if config is None:
                    logger.debug(
                        "No connector config for station=%s connector=%d, skipping",
                        txn["stationId"], ocpp_connector_id,
                    )
                    continue

                ev = self._build_ev(txn, config, key)
                if ev is not None:
                    evs.append(ev)

        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("Error fetching EVs: %s", repr(e))

        logger.debug("Fetched %d EVs for group %s", len(evs), group_name)
        return (evs, self.voltage)

    def get_peak_power_demand(
        self, group_name: str, _now: datetime, _voltage: Optional[float] = None
    ) -> list[float]:
        """Return the site power limit as a flat list for all timesteps.

        Args:
            group_name: The station group identifier.
            _now: The current timestamp (unused, accepted for interface compliance).
            _voltage: Optional voltage (unused).

        Returns:
            A list of SITE_POWER_LIMIT_KW repeated for AlgorithmConstants.TIMESTEPS.
        """
        logger.debug(
            "Site power limit for group '%s': %.1f kW",
            group_name, self.site_power_limit,
        )
        return [self.site_power_limit] * AlgorithmConstants.TIMESTEPS

    def send_power_to_evs(
        self, powers: dict[EV, dict], _unit: Optional[ChargingRateUnit] = None
    ):
        """Send SetChargingProfile to each EV via CitrineOS REST API.

        Iterates over the computed power allocations, builds OCPP 1.6
        SetChargingProfile payloads with TxProfile purpose in Amperes,
        and POSTs them to the CitrineOS REST API.

        Args:
            powers: Dict mapping EV instances to their charging profile dicts.
            _unit: Optional charging rate unit for the profiles.
        """
        logger.debug("send_power_to_evs called with %d profiles", len(powers))

        for ev, _profile in powers.items():
            try:
                txn_data = self.transaction_map.get(ev.ev_id)
                if txn_data is None:
                    logger.warning(
                        "EV %d not in transaction_map (may have disconnected), skipping",
                        ev.ev_id,
                    )
                    continue

                station_id_str = txn_data["stationId"]
                transaction_id = txn_data["transactionId"]

                # Generate current-period-only profile in Amperes.
                # SCM recalculates every cycle, so only the immediate
                # allocation matters — avoids stale multi-period schedules.
                profile_data = ev.current_charging_profile(
                    datetime.now(timezone.utc), unit=ChargingRateUnit.A
                )
                profile_data["transactionId"] = int(transaction_id)

                # Round period limits to whole Amps to avoid ajv multipleOf:0.1
                # floating-point precision failures (5.8 * 10 % 1 != 0 in JS).
                # 1A = 0.24 kW resolution at 240V — sufficient for Level 2.
                schedule = profile_data.get("chargingSchedule", {})
                for period in schedule.get("chargingSchedulePeriod", []):
                    period["limit"] = round(period["limit"])
                    period["startPeriod"] = int(period["startPeriod"])

                payload = {
                    "connectorId": ev.connector_id,
                    "csChargingProfiles": profile_data,
                }

                url = f"{self.citrineos_url}/ocpp/1.6/smartcharging/setChargingProfile"
                resp = requests.post(
                    url,
                    json=payload,
                    params={"identifier": station_id_str, "tenantId": "1"},
                    timeout=10,
                )
                if resp.status_code >= 400:
                    logger.error(
                        "SetChargingProfile rejected for EV %d (station=%s): HTTP %d body=%s",
                        ev.ev_id, station_id_str, resp.status_code, resp.text[:300],
                    )
                resp.raise_for_status()
                logger.debug(
                    "SetChargingProfile sent for EV %d (station=%s): HTTP %d",
                    ev.ev_id, station_id_str, resp.status_code,
                )

            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.error(
                    "Failed to send SetChargingProfile for EV %d: %s",
                    ev.ev_id, repr(e),
                )
