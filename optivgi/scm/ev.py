from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
from typing import Optional, Self

from .constants import EVConstants, AlgorithmConstants



class ChargingRateUnit(Enum):
    '''Enum for Charging Rate Unit'''
    W = 'W'
    A = 'A'

    def convert(self, value: float, unit: Self, voltage: Optional[float] = None) -> float:
        '''Convert the power in kW/A to the correct unit'''
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
    """Class for Storing EV attributes"""
    ev_id: int
    active: bool
    station_id: int
    connector_id: int
    min_power: float # kW / A
    max_power: float # kW / A

    arrival_time: datetime
    departure_time: datetime
    energy: float # kWh / Ah

    unit: ChargingRateUnit = ChargingRateUnit.W
    voltage: float = EVConstants.CHARGING_RATE_VOLTAGE

    power: list[float] = field(default_factory=lambda: [0.] * AlgorithmConstants.TIMESTEPS, repr=False)

    def __eq__(self, other):
        if not isinstance(other, EV):
            return NotImplemented
        return self.ev_id == other.ev_id

    def __hash__(self):
        return hash(self.ev_id)

    def departure_index(self, now: datetime) -> int:
        """Get the index of the departure time based on the current time"""
        departure_index = int((self.departure_time - now).total_seconds() / AlgorithmConstants.RESOLUTION.total_seconds())
        return max(0, min(departure_index, AlgorithmConstants.TIMESTEPS - 1))

    def arrival_index(self, now: datetime) -> int:
        """Get the index of the arrival time based on the current time"""
        arrival_index = int((self.arrival_time - now).total_seconds() / AlgorithmConstants.RESOLUTION.total_seconds())
        return max(0, min(arrival_index, AlgorithmConstants.TIMESTEPS - 1))

    def energy_charged(self) -> float:
        """Get the total energy charged by the EV"""
        return sum(self.power) * AlgorithmConstants.POWER_ENERGY_FACTOR

    def current_charging_profile(self, now: datetime, unit: Optional[ChargingRateUnit] = None) -> dict:
        """Get the current time charging profile for the EV"""
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
        """Get the full charging profile for the EV"""
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
