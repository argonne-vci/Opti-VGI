"""
Defines the Electric Vehicle (EV) data structure and related enums.

This module includes the `EV` dataclass, which stores all relevant information
about a vehicle for scheduling purposes, and the `ChargingRateUnit` enum used
to specify power units.
"""
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
from typing import Optional, Self

from .constants import EVConstants, AlgorithmConstants



class ChargingRateUnit(Enum):
    """
    Enum for charging rate units (Power or Current).
    All values represented in the algorithm and EV are in kW (not W) or A.
    This class can be used to convert this value to W or A
    for sending to the EVSE.
    """
    W = 'W'
    A = 'A'

    def convert(self, value: float, unit: Self, voltage: Optional[float] = None) -> float:
        """
        Converts a power or current value from one unit to another.

        Requires voltage for W <-> A conversion. Uses `EVConstants.CHARGING_RATE_VOLTAGE`
        as a default if voltage is not provided or is zero.

        Args:
            value: The numerical value to convert.
            from_unit: The unit of the input `value` (ChargingRateUnit.W or ChargingRateUnit.A).
            voltage: The nominal voltage (in Volts) to use for conversion. If None or zero,
                     `EVConstants.CHARGING_RATE_VOLTAGE` is used.

        Returns:
            The converted value in the target unit (`self`).

        Raises:
            ValueError: If voltage is required for conversion but is not provided or is zero/negative.
        """
        match unit:
            case ChargingRateUnit.W:
                power_w = value * 1000
            case ChargingRateUnit.A:
                power_w = value * voltage if voltage else EVConstants.CHARGING_RATE_VOLTAGE

        if self == ChargingRateUnit.A:
            return power_w / voltage if voltage else EVConstants.CHARGING_RATE_VOLTAGE

        return power_w

@dataclass
class EV:
    """
    Represents an Electric Vehicle and its charging requirements/constraints.

    This dataclass holds both static information (ID, power limits, energy needs)
    and dynamic state (calculated power schedule).
    """
    #: ev_id: Unique identifier for the EV. This is used to track and manage
    #: the EV's charging session and is essential for scheduling and reporting.
    #: It should be unique across all EVs in the system.
    ev_id: int

    #: active: Indicates whether the EV is currently connected and actively
    #: participating in the charging session (True), or if it's a future
    #: reservation/planned arrival (False). This is important for scheduling
    #: and resource allocation.
    active: bool

    #: station_id: Identifier of the charging station the EV is connected to or
    #: assigned to. This is used for managing the charging session and
    #: sending the charging profile to the correct station.
    station_id: int

    #: connector_id: Identifier of the specific connector/outlet on the station.
    connector_id: int

    #: min_power: Minimum charging power (in kW or A, matching `unit`) required by
    #: the EV when charging. Can be 0 if supported by the EVSE.
    min_power: float # kW / A

    #: max_power: Maximum charging power (in kW or A, matching `unit`) the EV or
    #: station connector can handle. This is the upper limit for the charging
    #: profile and should not be exceeded.
    max_power: float # kW / A

    #: arrival_time: The datetime when the EV arrives or is expected to arrive.
    arrival_time: datetime
    #: departure_time: The datetime when the EV needs to be fully charged or will depart.
    departure_time: datetime

    #: energy: The amount of energy (in kWh or Ah, matching `unit`) required by the EV before departure.
    energy: float # kWh / Ah

    #: unit: The physical unit (`ChargingRateUnit.W` or `ChargingRateUnit.A`) for
    #: `min_power`, `max_power`, and the calculated `power` list. Determines
    #: if `energy` is in kWh (for W) or Ah (for A). Defaults to Watts (W).
    unit: ChargingRateUnit = ChargingRateUnit.W

    #: voltage: The nominal voltage (in Volts) at the connector. Used for W/A
    #: conversions if needed. Defaults to `EVConstants.CHARGING_RATE_VOLTAGE`.
    voltage: float = EVConstants.CHARGING_RATE_VOLTAGE

    #: power: A list storing the calculated charging power (in the unit specified by
    #: `self.unit`) allocated to this EV for each time step defined by
    #: `AlgorithmConstants.TIMESTEPS`. Initialized to zeros. This list is
    #: populated by the SCM `Algorithm.calculate()` method. (repr=False to
    #: avoid overly long default string representation).
    #: The length of this list is equal to `AlgorithmConstants.TIMESTEPS`.
    power: list[float] = field(default_factory=lambda: [0.] * AlgorithmConstants.TIMESTEPS, repr=False)

    def __eq__(self, other):
        """Checks equality based on ev_id."""
        if not isinstance(other, EV):
            return NotImplemented
        return self.ev_id == other.ev_id

    def __hash__(self):
        """Computes hash based on ev_id."""
        return hash(self.ev_id)

    def departure_index(self, now: datetime) -> int:
        """
        Calculates the index of the time step corresponding to the EV's departure time.

        The index is relative to the planning horizon starting at `now`.
        The result is clamped between 0 and `AlgorithmConstants.TIMESTEPS - 1`.

        Args:
            now: The reference start time of the planning horizon.

        Returns:
            The integer index for the departure time step. Returns 0 if departure is
            before or at `now`.
        """
        departure_index = int((self.departure_time - now).total_seconds() / AlgorithmConstants.RESOLUTION.total_seconds())
        return max(0, min(departure_index, AlgorithmConstants.TIMESTEPS - 1))

    def arrival_index(self, now: datetime) -> int:
        """
        Calculates the index of the time step corresponding to the EV's arrival time.

        The index is relative to the planning horizon starting at `now`.
        The result is clamped between 0 and `AlgorithmConstants.TIMESTEPS - 1`.

        Args:
            now: The reference start time of the planning horizon.

        Returns:
            The integer index for the arrival time step. Returns 0 if arrival is
            before or at `now`.
        """
        arrival_index = int((self.arrival_time - now).total_seconds() / AlgorithmConstants.RESOLUTION.total_seconds())
        return max(0, min(arrival_index, AlgorithmConstants.TIMESTEPS - 1))

    def energy_charged(self) -> float:
        """
        Calculates the total energy scheduled to be delivered based on the `power` list.

        Sums the power allocated in each time step and converts it to energy using
        `AlgorithmConstants.POWER_ENERGY_FACTOR`.

        Returns:
            The total calculated energy in kWh (if `unit` is W) or Ah (if `unit` is A).
        """
        return sum(self.power) * AlgorithmConstants.POWER_ENERGY_FACTOR

    def current_charging_profile(self, now: datetime, unit: Optional[ChargingRateUnit] = None) -> dict:
        """
        Generates a charging profile dictionary containing only the power for the current time step.

        This is suitable for systems requiring immediate power commands, conforming to
        a structure similar to OCPP's SetChargingProfileRequest.

        Args:
            now: The current time, used to set the profile's start schedule time.
            unit: The desired output unit (`ChargingRateUnit.W` or `ChargingRateUnit.A`)
                  for the 'limit' value in the profile. If None, `self.unit` is used.

        Returns:
            A dictionary representing the charging profile for the current time step.
            Returns an empty dictionary if the EV is not active or has no power scheduled now.
        """
        if unit is None:
            unit = self.unit
        return {
            "chargingProfileId": EVConstants.CHARGING_PROFILE_ID,
            "stackLevel": EVConstants.CHARGING_PROFILE_STACK_LEVEL,
            "chargingProfilePurpose": EVConstants.CHARGING_PROFILE_PURPOSE,
            "chargingProfileKind": EVConstants.CHARGING_PROFILE_KIND,
            "chargingSchedule": {
                "startSchedule": now.strftime('%Y-%m-%dT%H:%M:%SZ'),
                "chargingRateUnit": unit.value,
                "chargingSchedulePeriod":[{
                    "startPeriod": 0,
                    "limit": unit.convert(self.power[0], self.unit, self.voltage),
                    "numberPhases": 1
                }]
            }
        }

    def charging_profile(self, now: datetime, unit: Optional[ChargingRateUnit] = None) -> dict:
        """
        Generates the full charging profile dictionary over the entire planning horizon.

        This compiles the calculated `self.power` list into a structure suitable for
        protocols like OCPP, including compression to reduce the number of periods
        where the power limit remains constant.

        Args:
            now: The current time, used to set the profile's start schedule time.
            unit: The desired output unit (`ChargingRateUnit.W` or `ChargingRateUnit.A`)
                  for the 'limit' values in the profile periods. If None, `self.unit` is used.

        Returns:
            A dictionary representing the complete charging profile.
            Returns an empty dictionary if the EV has no power scheduled.
        """
        if unit is None:
            unit = self.unit

        charging_schedule_period = [
            {
                "startPeriod": i * AlgorithmConstants.RESOLUTION.total_seconds(),
                "limit": unit.convert(power, self.unit, self.voltage),
                "numberPhases": 1
            }
            for i, power in enumerate(self.power)
        ]

        charging_schedule_period_compressed = [charging_schedule_period[0]]
        for period in charging_schedule_period[1:]:
            if period['limit'] != charging_schedule_period_compressed[-1]['limit']:
                charging_schedule_period_compressed.append(period)

        return {
            "chargingProfileId": EVConstants.CHARGING_PROFILE_ID,
            "stackLevel": EVConstants.CHARGING_PROFILE_STACK_LEVEL,
            "chargingProfilePurpose": EVConstants.CHARGING_PROFILE_PURPOSE,
            "chargingProfileKind": EVConstants.CHARGING_PROFILE_KIND,
            "chargingSchedule": {
                "startSchedule": now.strftime('%Y-%m-%dT%H:%M:%SZ'),
                "chargingRateUnit": unit.value,
                "chargingSchedulePeriod": charging_schedule_period_compressed
            }
        }
