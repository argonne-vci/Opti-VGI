from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

from .ev import EV, ChargingRateUnit
from .constants import AlgorithmConstants

class Algorithm(ABC):
    """Abstract class for SCM Algorithms"""
    def __init__(self, evs: list[EV], peak_power_demand: list[float], now: datetime):
        self.evs = evs
        self.peak_power_demand = peak_power_demand
        self.now = now

        assert len(self.peak_power_demand) == AlgorithmConstants.TIMESTEPS, f'Peak power demand must be the same length as the number of timesteps ({AlgorithmConstants.TIMESTEPS})'

    @abstractmethod
    def calculate(self) -> None:
        """Run the algorithm to calculate the power for each EV"""

    def get_current_power(self, unit: Optional[ChargingRateUnit] = None) -> dict[EV, dict]:
        """Helper function to get the current time charging profiles for each EV"""
        return {ev: ev.current_charging_profile(self.now, unit) for ev in self.evs}

    def get_charging_profiles(self, unit: Optional[ChargingRateUnit] = None) -> dict[EV, dict]:
        """Helper function to get the full charging profiles for each EV"""
        return {ev: ev.charging_profile(self.now, unit) for ev in self.evs}

    def get_total_energy_charged(self) -> dict[EV, float]:
        """Helper function to get the total energy charged for each EV"""
        return {ev: ev.energy_charged() for ev in self.evs}
