"""
Defines the abstract base class for Smart Charging Management (SCM) algorithms.

All specific charging optimization algorithms within Opti-VGI should inherit
from the `Algorithm` class defined here and implement the `calculate` method.
"""
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

from .ev import EV, ChargingRateUnit
from .constants import AlgorithmConstants

class Algorithm(ABC):
    """
    Abstract Base Class for SCM Optimization Algorithms.

    Provides a common interface and initialization for different charging strategies.

    Attributes:
        evs (list[EV]): A list of electric vehicle objects to be scheduled.
        peak_power_demand (list[float]): A list representing the maximum allowed
            aggregate power for each time step over the planning horizon. The length
            must match `AlgorithmConstants.TIMESTEPS`.
        now (datetime): The reference start time for the scheduling calculation.
    """
    def __init__(self, evs: list[EV], peak_power_demand: list[float], now: datetime):
        """
        Initializes the Algorithm base class.

        Args:
            evs: A list of EV objects representing the vehicles to be scheduled.
            peak_power_demand: The maximum aggregate power allowed for each time step.
                               Must have length equal to `AlgorithmConstants.TIMESTEPS`.
            now: The starting datetime for the scheduling horizon.

        Raises:
            AssertionError: If the length of `peak_power_demand` does not match
                            `AlgorithmConstants.TIMESTEPS`.
        """
        self.evs = evs
        self.peak_power_demand = peak_power_demand
        self.now = now

        assert len(self.peak_power_demand) == AlgorithmConstants.TIMESTEPS, f'Peak power demand must be the same length as the number of timesteps ({AlgorithmConstants.TIMESTEPS})'

    @abstractmethod
    def calculate(self) -> None:
        """
        Executes the core logic of the charging algorithm.

        Implementations of this method should determine the power allocation for
        each EV over the planning horizon (filling the `ev.power` list for each EV
        in `self.evs`).
        """
        raise NotImplementedError

    def get_current_power(self, unit: Optional[ChargingRateUnit] = None) -> dict[EV, dict]:
        """
        Generates charging profiles containing only the power for the current time step.

        This is useful for systems that only need the immediate power setting rather
        than the full future plan. It calls `ev.current_charging_profile` for each EV.

        Args:
            unit: The desired charging rate unit (W or A) for the output profiles.
                  If None, the unit from the EV object is used.

        Returns:
            A dictionary where keys are EV objects and values are their charging
            profiles formatted for the current time step.
        """
        return {ev: ev.current_charging_profile(self.now, unit) for ev in self.evs}

    def get_charging_profiles(self, unit: Optional[ChargingRateUnit] = None) -> dict[EV, dict]:
        """
        Generates the full charging profiles for all EVs over the planning horizon.

        This method compiles the results of the `calculate` method into a format
        suitable for sending to the external system (e.g., via the Translation layer).
        It calls `ev.charging_profile` for each EV.

        Args:
            unit: The desired charging rate unit (W or A) for the output profiles.
                  If None, the unit from the EV object is used.

        Returns:
            A dictionary where keys are EV objects and values are their complete
            charging profiles over the planning horizon.
        """
        return {ev: ev.charging_profile(self.now, unit) for ev in self.evs}

    def get_total_energy_charged(self) -> dict[EV, float]:
        """
        Calculates the total energy scheduled to be delivered to each EV.

        Sums the energy delivered in each time step based on the calculated power profile.
        It calls `ev.energy_charged()` for each EV.

        Returns:
            A dictionary where keys are EV objects and values are the total calculated
            energy (in kWh or Ah, matching `ev.energy` unit) to be charged.
        """
        return {ev: ev.energy_charged() for ev in self.evs}
