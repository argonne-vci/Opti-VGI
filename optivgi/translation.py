"""
Provides the abstract base class for the Translation Layer.

The Translation Layer acts as an interface between the Opti-VGI core logic
and an external Charge Station Management System (CSMS) or data source.
Implementations of this class handle the specifics of communication (e.g., API calls,
database queries) to fetch EV data, power constraints, and send back charging schedules.
"""
from abc import abstractmethod
from contextlib import AbstractContextManager
from datetime import datetime
from typing import Optional

from .scm.ev import EV, ChargingRateUnit

class Translation(AbstractContextManager):
    """
    Translation Layer Abstract Class
    This class is used to define the interface for the translation layer.
    The translation layer is used to interact with the external EV Management System (CSMS).
    The abstract methods defined in this class must be implemented by the concrete translation layer.
    Implementations must support the context manager protocol for setup and teardown (e.g., opening/closing connections)
    """

    # Provide basic context manager implementations
    def __enter__(self):
        """Enters the runtime context for the translation layer.

        Implementations can override this to perform setup actions like
        establishing connections.

        Returns:
            self
        """
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exits the runtime context, performing any necessary cleanup.

        Implementations can override this to perform teardown actions like
        closing connections. Parameters relate to any exception that occurred
        within the `with` block.
        """
        # Default implementation does nothing

    @abstractmethod
    def get_peak_power_demand(self, group_name: str, now: datetime, voltage: Optional[float] = None) -> list[float]:
        """
        Fetches the anticipated peak power demand constraints for a specific station group.

        Args:
            group_name: The identifier for the group of charging stations.
            now: The current timestamp, used as the reference start time for the
                 power demand forecast. The forecast should cover the duration
                 defined by `AlgorithmConstants.TIMESTEPS`.
            voltage: An optional nominal voltage for the group. This may be needed
                     if the source provides demand in Amperes (A) and the algorithm
                     requires Kilowatts (kW), or vice-versa.

        Returns:
            A list of floats representing the maximum allowed aggregate power
            consumption (in kW, unless the EV objects consistently use Amps)
            for the group for each time step defined by `AlgorithmConstants.TIMESTEPS`,
            starting from the interval containing `now`. The length of the list
            must equal `AlgorithmConstants.TIMESTEPS`.
        """
        raise NotImplementedError

    @abstractmethod
    def get_evs(self, group_name: str) -> tuple[list[EV], Optional[float]]:
        """
        Retrieves information about all relevant EVs (currently connected/active
        and planned future arrivals) for a specified group.

        Args:
            group_name: The identifier for the group of charging stations.

        Returns:
            A tuple containing:
                - list[EV]: A list of `EV` objects associated with the group. This should
                  include EVs currently plugged in and expected future arrivals within
                  the planning horizon.
                - Optional[float]: The nominal voltage (V) for the group, if it's
                  consistently defined or available from the source. This helps in
                  potential W/A conversions within the algorithm or translation layer.
                  Returns `None` if voltage is unknown or varies significantly.
        """
        raise NotImplementedError

    @abstractmethod
    def send_power_to_evs(self, powers: dict[EV, dict], unit: Optional[ChargingRateUnit] = None):
        """
        Sends the calculated charging profiles or power levels to the external system
        for execution on the respective EVs.

        Args:
            powers: A dictionary where keys are `EV` objects and values are their
                    calculated charging profiles. The format of the profile dictionary
                    (the value) typically aligns with standards like OCPP's
                    SetChargingProfileRequest or a similar structure expected by the
                    target system. The `EV.charging_profile()` method provides a
                    default structure.
            unit: The desired unit (`ChargingRateUnit.W` or `ChargingRateUnit.A`) for the
                  power/limit values within the charging profiles being sent. If `None`,
                  the implementation should ideally use the unit specified within the
                  `EV` objects themselves or a default expected by the target system.
                  The implementation might need to perform conversions if this differs
                  from the units used in the `powers` dictionary values.
        """
        raise NotImplementedError
