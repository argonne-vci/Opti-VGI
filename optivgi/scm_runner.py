"""
Core Smart Charging Management (SCM) runner logic.

This module orchestrates the process of fetching data via the Translation layer,
running the selected SCM algorithm, and sending the results back through the Translation layer.
"""
import os
import logging
from typing import Type
from datetime import datetime, UTC

from .translation import Translation
from .scm.algorithm import Algorithm
from .scm.constants import AlgorithmConstants
from .utils import round_down_datetime

def scm_runner(translation: Translation, algorithm_cls: Type[Algorithm]):
    """
    Executes one cycle of the Smart Charging Management logic for configured groups.

    This function performs the following steps for each station group defined
    in the `STATION_GROUPS` environment variable:
    1. Retrieves the list of EVs (`get_evs`) and peak power demand (`get_peak_power_demand`) from the provided `translation` object.
    2. Instantiates the specified `Algorithm` with the fetched data and current time.
    3. Runs the algorithm's `calculate` method to determine charging schedules.
    4. Retrieves the calculated charging profiles using `get_charging_profiles`.
    5. Sends the profiles back to the external system via `translation.send_power_to_evs`.

    The current time is rounded down to the nearest algorithm resolution interval.

    Args:
        translation: An instantiated object of a class inheriting from
                     `optivgi.translation.Translation`. Used for interacting with the
                     external system.
        algorithm_cls: The class type of the SCM algorithm to use (must inherit
                       from `optivgi.scm.algorithm.Algorithm`).
    """
    groups = filter(bool, map(str.strip, os.getenv('STATION_GROUPS', '').split(',')))

    now = round_down_datetime(datetime.now(UTC), int(AlgorithmConstants.RESOLUTION.total_seconds() / 60))

    logging.info('Running SCM for groups: %s at time: %s', os.getenv('STATION_GROUPS'), now)

    for group in groups:
        logging.info('Running SCM for group: %s', group)
        evs, voltage = translation.get_evs(group)
        peak_power_demand = translation.get_peak_power_demand(group, now, voltage)

        algorithm = algorithm_cls(evs, peak_power_demand, now)
        algorithm.calculate()

        powers = algorithm.get_charging_profiles()
        translation.send_power_to_evs(powers)
