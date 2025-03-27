# pylint: disable=missing-function-docstring
import math
import logging
from dataclasses import dataclass, field

from .algorithm import Algorithm
from .constants import AlgorithmConstants
from .ev import EV


# Debug Flag
DEBUG = False

# Configuration
FAIRNESS_FACTOR = 1.
SHIFT_FRONT = True
ALLOC_REMAINING_EXTRA = True


class GoAlgorithm(Algorithm):
    """SCM Algorithm created for use with the GO EV Scheduler"""

    @dataclass
    class EVPower:
        """Class for allocating EV power"""
        ev: EV
        energy_left: float = field(init=False)

        def __post_init__(self):
            self.energy_left = self.ev.energy

        def power(self, time: int, max_available=float('inf'), ignore_energy=False):
            return max(
                self.ev.min_power - self.ev.power[time],
                min(self.ev.max_power - self.ev.power[time],
                    self.energy_left / AlgorithmConstants.POWER_ENERGY_FACTOR if not ignore_energy else float('inf'),
                    max_available))

        def accept_power(self, time: int, power: float, ignore_energy=False):
            try:
                assert power <= self.power(time, ignore_energy=ignore_energy)
            except AssertionError as e:
                logging.error('Assertion Error: %s', e.args[0] if e.args else repr(e))
                logging.error('EV: %s', self.ev)
                logging.error('Time: %s', time)
                logging.error('Power: %s', power)
                logging.error('Energy Left: %s', self.energy_left)
                logging.error('Power at Time: %s', self.ev.power[time])
            if DEBUG:
                logging.info('%s accepted %s at %s', self.ev.ev_id, power, time)
            self.energy_left -= power * AlgorithmConstants.POWER_ENERGY_FACTOR
            self.ev.power[time] += power

        def shift_power(self, time_from: int, time_to: int, power: float):
            if time_from == time_to:
                return
            try:
                assert power <= self.ev.power[time_from]
                assert power <= self.ev.max_power - self.ev.power[time_to]
            except AssertionError as e:
                logging.error('Assertion Error: %s', e.args[0] if e.args else repr(e))
                logging.error('EV: %s', self.ev)
                logging.error('Time From: %s', time_from)
                logging.error('Time To: %s', time_to)
                logging.error('Power: %s', power)
                logging.error('Energy Left: %s', self.energy_left)
                logging.error('Power at Time From: %s', self.ev.power[time_from])
                logging.error('Power at Time To: %s', self.ev.power[time_to])
            if DEBUG:
                logging.info('%s shifted {p} from %s to %s', self.ev.ev_id, time_from, time_to)
            self.ev.power[time_from] -= power
            self.ev.power[time_to] += power

    def calculate(self) -> None:
        evs = {ev.ev_id: self.EVPower(ev=ev) for ev in self.evs}

        evs_present: list[set[int]] = [set() for _ in range(AlgorithmConstants.TIMESTEPS)]
        for ev_id, ev in evs.items():
            for time_index in range(ev.ev.arrival_index(self.now), ev.ev.departure_index(self.now)):
                evs_present[time_index].add(ev_id)

        available_peak_power = self.peak_power_demand.copy()
        for time in range(AlgorithmConstants.TIMESTEPS - 1, -1, -1):
            # Allocate Minimum Power first
            for ev_id in evs_present[time]:
                ev = evs[ev_id]
                ev.accept_power(time, ev.ev.min_power)
                available_peak_power[time] -= ev.ev.min_power

            while available_peak_power[time] > 0:
                evs_to_allocate = [(ev_id, evs[ev_id].power(time))
                                   for ev_id in evs_present[time]
                                   if evs[ev_id].power(time) != 0]
                if not evs_to_allocate:
                    break

                total_power_required = sum(p**FAIRNESS_FACTOR for _, p in evs_to_allocate)
                power_allocation = [(ev_id, power**FAIRNESS_FACTOR / total_power_required * available_peak_power[time])
                                    for ev_id, power in evs_to_allocate]
                if sum(allocated_power for _, allocated_power in power_allocation) == 0:
                    break

                if DEBUG:
                    logging.info('Splitting %s -> %s into %s', time, available_peak_power[time], power_allocation)
                for ev_id, allocated_power in power_allocation:
                    ev = evs[ev_id]
                    power = ev.power(time, allocated_power)
                    ev.accept_power(time, power)
                    available_peak_power[time] -= power

        if SHIFT_FRONT:
            for time_from in range(AlgorithmConstants.TIMESTEPS - 1, -1, -1):
                for ev_id, ev in evs.items():
                    time_to = time_from - 1
                    while time_to >= 0 and ev.ev.power[time_from] > ev.ev.min_power and ev_id in evs_present[time_to] and available_peak_power[time_to] > 0:
                        power = min(available_peak_power[time_to], ev.ev.power[time_from] - ev.ev.min_power, ev.ev.max_power - ev.ev.power[time_to])
                        ev.shift_power(time_from, time_to, power)
                        available_peak_power[time_to] -= power
                        available_peak_power[time_from] += power
                        time_to -= 1

        if ALLOC_REMAINING_EXTRA:
            for time in range(AlgorithmConstants.TIMESTEPS):
                available_extra_power = available_peak_power[time]

                evs_to_allocate = [(ev_id, evs[ev_id].power(time, available_extra_power, True))
                                   for ev_id in evs_present[time]
                                   if evs[ev_id].power(time, available_extra_power, True) != 0]

                total_power_required = sum(p**FAIRNESS_FACTOR for _, p in evs_to_allocate)
                power_allocation = [(ev_id, power**FAIRNESS_FACTOR / total_power_required * available_extra_power)
                                    for ev_id, power in evs_to_allocate]
                if sum(allocated_power for _, allocated_power in power_allocation) == 0:
                    continue

                for ev_id, allocation in power_allocation:
                    ev = evs[ev_id]
                    power = ev.power(time, allocation, True)
                    ev.accept_power(time, power, True)
                    available_peak_power[time] -= power

        try:
            for ev in evs.values():
                assert all(y == 0. or y <= ev.ev.max_power or math.isclose(y, ev.ev.max_power) for y in ev.ev.power), 'EV Max Power'
                assert all(y == 0. or y >= ev.ev.min_power for y in ev.ev.power), 'EV Min Power'
            for i in range(AlgorithmConstants.TIMESTEPS):
                assert available_peak_power[i] >= -1, f'{available_peak_power[i]} not greater than or equal to zero'
                y_pm_i = sum(ev.ev.power[i] for ev in evs.values())
                assert self.peak_power_demand[i] >= y_pm_i or math.isclose(self.peak_power_demand[i], y_pm_i), 'Total Power'
        except AssertionError as e:
            logging.error('Assertion Error: %s', e.args[0] if e.args else repr(e))
            logging.error('EVs: %s', self.evs)
            logging.error('peak_power_demand: %s', self.peak_power_demand)
            logging.error('available_peak_power: %s', available_peak_power)
