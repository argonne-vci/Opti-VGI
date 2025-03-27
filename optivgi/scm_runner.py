import os
import logging
from typing import Type
from datetime import datetime, UTC

from .translation import Translation
from .scm.algorithm import Algorithm
from .scm.constants import AlgorithmConstants
from .utils import round_down_datetime

def scm_runner(translation: Translation, algorithm_cls: Type[Algorithm]):
    """Main OptiVGI function that uses the translation and algorithm to run the SCM logic"""
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
