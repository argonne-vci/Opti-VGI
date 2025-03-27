import os
import logging
from typing import Optional
from datetime import datetime

from optivgi.translation import Translation
from optivgi.scm.ev import EV, ChargingRateUnit
from optivgi.scm.constants import AlgorithmConstants, EVConstants

import requests

class TranslationAPI(Translation):
    """
    Example Translation Layer that communicates with a remote server using HTTP requests.
    """

    def __init__(self):
        port = os.getenv("API_PORT")
        assert port, "API_PORT environment variable must be set"
        assert port.isdigit(), "API_PORT must be a valid port number"
        self.base_url = f"http://localhost:{port}"

    def __enter__(self):
        """Perform any entry setup needed in the translation layer."""
        logging.info('Entering Example Translation Layer')
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit the runtime context and perform any cleanup."""
        logging.info('Exiting EVrest Translation Layer')
        # self.cleanup.__exit__(exc_type, exc_val, exc_tb)

    def get_peak_power_demand(self, group_name: str, now: datetime, voltage: Optional[float] = None) -> list[float]:
        """
        Example implementation that fetches peak power demand data from a remote server using 'requests'.
        The server might return something like:
        { "2025-03-23T06:00:00.000000+00:00": 10, "2025-03-23T10:00:00.000000+00:00": 20, ... }
        """
        try:
            # Here, we call GET /peak_power_demand?group_name=<>&timestamp=<>?voltage=<>
            params = {
                "group_name": group_name,
                "timestamp": now.isoformat(),
                "voltage": voltage
            }
            resp = requests.get(f"{self.base_url}/peak_power_demand", params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            times = sorted(map(datetime.fromisoformat, data.keys()), reverse=True)
            assert times[-1] <= now, "Data is missing for the current time"

            peak_power_demand = []
            for _ in range(AlgorithmConstants.TIMESTEPS):
                if len(times) > 1 and times[-2] <= now:
                    times.pop()
                peak_power_demand.append(data[times[-1].isoformat()])
            return peak_power_demand
        except Exception as e:
            logging.error("Error fetching peak power demand: %s", repr(e))
            # Return an empty list or raise
            return []


    def get_evs(self, group_name: str) -> tuple[list[EV], Optional[float]]:
        """
        Example implementation that fetches a list of EVs from a remote server.
        The server might return something like:
            {
              "evs": [
                {
                  "ev_id": 1,
                  "station_id": 1,
                  "connector_id": 1,
                  "min_power": 2.5,
                  "max_power": 7.2,
                  "arrival_time": "2025-03-23T06:00:00.000000+00:00",
                  "departure_time": "2025-03-23T10:00:00.000000+00:00",
                  "energy_needed": 20.0
                },
                ...
              ],
              "voltage": 240.0   # If your server also returns a recommended voltage, for example
            }
        """
        evs: list[EV] = []
        voltage = None
        try:
            # Get Active EVs
            resp = requests.get(f"{self.base_url}/evs", params={ "group_name": group_name }, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            voltage = data.get("voltage")  # optional
            for ev_info in data.get("evs", []):
                # Build the EV object from the data
                ev_obj = EV(
                    ev_id=ev_info["ev_id"],
                    active=True,  # Indicate if the EV is currently charging
                    station_id=ev_info["station_id"],
                    connector_id=ev_info["connector_id"],
                    min_power=ev_info["min_power"],
                    max_power=ev_info["max_power"],
                    arrival_time=datetime.fromisoformat(ev_info.get("arrival_time")),
                    departure_time=datetime.fromisoformat(ev_info.get("departure_time")),
                    energy=ev_info["energy_needed"],
                    unit=ChargingRateUnit.W,  # or A, if your data says so
                    voltage=voltage if voltage else EVConstants.CHARGING_RATE_VOLTAGE
                )
                evs.append(ev_obj)

            # Get Future EVs
            resp = requests.get(f"{self.base_url}/future_evs", params={ "group_name": group_name }, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            assert data.get("voltage") == voltage, "Voltage mismatch between active and future EVs"
            for ev_info in data.get("future_evs", []):
                # Build the EV object from the data
                ev_obj = EV(
                    ev_id=ev_info["ev_id"],
                    active=False,  # Future EVs are not active
                    station_id=ev_info["station_id"],
                    connector_id=ev_info["connector_id"],
                    min_power=ev_info["min_power"],
                    max_power=ev_info["max_power"],
                    arrival_time=datetime.fromisoformat(ev_info.get("arrival_time")),
                    departure_time=datetime.fromisoformat(ev_info.get("departure_time")),
                    energy=ev_info["energy_needed"],
                    unit=ChargingRateUnit.W,  # or A, if your data says so
                    voltage=voltage if voltage else EVConstants.CHARGING_RATE_VOLTAGE
                )
                evs.append(ev_obj)

        except Exception as e:
            logging.error("Error while fetching EVs: %s", repr(e))

        logging.info("Fetched %d EVs for group %s", len(evs), group_name)
        return (evs, voltage)


    def send_power_to_evs(self, powers: dict[EV, dict], unit: Optional[ChargingRateUnit] = None):
        """
        Example implementation that POSTs power profiles to a remote server.
        Typically, `powers` is a dict: { EV_object: charging_profile_dict, ... }.

        We'll transform it into a JSON-friendly dict, e.g.:
            {
              "1": {...charging profile data...},
              "2": {...charging profile data...}
            }

        Then POST it to /powers or your chosen endpoint.
        """
        try:
            payload = {}
            for ev, profile in powers.items():
                # Convert EV-based key to string ID
                payload[str(ev.ev_id)] = profile

            # You might also include the 'unit' or other info in the payload
            body = {
                "powers": payload,
                "unit": unit.value if unit else None
            }

            resp = requests.post(f"{self.base_url}/powers", json=body, timeout=10)
            resp.raise_for_status()
            logging.info("Successfully sent power allocation to EVs.")
        except Exception as e:
            logging.error("Error sending power to EVs: %s", repr(e))
