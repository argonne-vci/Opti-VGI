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
    """
    @abstractmethod
    def get_peak_power_demand(self, group_name: str, now: datetime, voltage: Optional[float] = None) -> list[float]:
        """Get the peak power demand of a group"""

    @abstractmethod
    def get_evs(self, group_name: str) -> tuple[list[EV], Optional[float]]:
        """Get all EVs in a group and optional voltage if available"""

    @abstractmethod
    def send_power_to_evs(self, powers: dict[EV, dict], unit: Optional[ChargingRateUnit] = None):
        """Send power to EVs"""
