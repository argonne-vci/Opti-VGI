import logging

from pulp import LpVariable, LpProblem, LpMaximize, PULP_CBC_CMD

from .algorithm import Algorithm
from .constants import AlgorithmConstants

class PulpNumericalAlgorithm(Algorithm):
    """Pulp Numerical SCM Algorithm"""

    def calculate(self) -> None:
        logging.info('Number of Connected EVs: %s', len(self.evs))

        # Create a linear programming problem
        model = LpProblem(name='charging_schedule', sense=LpMaximize)

        # Decision variables
        ev_vars = {
            (ev.ev_id, time): LpVariable(name=f'X_{ev.ev_id}_{time}', lowBound=0)
            for ev in self.evs
            for time in range(AlgorithmConstants.TIMESTEPS)
        }
        ev_vars_diff = {
            (ev.ev_id, time): LpVariable(name=f'X_diff_{ev.ev_id}_{time}', lowBound=0)
            for ev in self.evs
            for time in range(AlgorithmConstants.TIMESTEPS - 1)
        }
        percentage = LpVariable(name='percentage_charge', lowBound=0)

        ev_max_demand = sum(ev.max_power for ev in self.evs) if self.evs else float('inf')
        max_power_demand = [min(ev_max_demand, self.peak_power_demand[time]) for time in range(AlgorithmConstants.TIMESTEPS)]

        # Objective function - maximize the percentage of energy charged and peak power utilization and minimize the change in power
        model += percentage * 100 * AlgorithmConstants.TIMESTEPS * len(self.evs) + sum(
            sum(ev_vars[ev.ev_id, time] for ev in self.evs) / max_power_demand[time] # type: ignore
            for time in range(AlgorithmConstants.TIMESTEPS)
        ) - sum(sum(ev_vars_diff[ev.ev_id, time] for time in range(AlgorithmConstants.TIMESTEPS - 1)) for ev in self.evs) # type: ignore

        # Constraints
        for ev in self.evs:
            # Power Difference Constraints - absolute value
            for time in range(AlgorithmConstants.TIMESTEPS - 1):
                model += ev_vars_diff[ev.ev_id, time] >= ev_vars[ev.ev_id, time + 1] - ev_vars[ev.ev_id, time]
                model += ev_vars_diff[ev.ev_id, time] >= -ev_vars[ev.ev_id, time + 1] + ev_vars[ev.ev_id, time]

            # Percentage of energy charged >= maximised percentage
            model += (
                (sum(ev_vars[ev.ev_id, time] for time in range(AlgorithmConstants.TIMESTEPS)) * AlgorithmConstants.POWER_ENERGY_FACTOR) / ev.energy
            ) >= percentage

            # Calculate the index of the arrival and departure times
            arrival_index = ev.arrival_index(self.now)
            departure_index = ev.departure_index(self.now)

            # Power constraints after arrival before departure
            for time in range(arrival_index, departure_index):
                model += ev_vars[ev.ev_id, time] >= ev.min_power

                model += ev_vars[ev.ev_id, time] <= ev.max_power

            # No charging before arrival
            for time in range(arrival_index):
                model += ev_vars[ev.ev_id, time] == 0

            # No charging after departure
            for time in range(departure_index, AlgorithmConstants.TIMESTEPS):
                model += ev_vars[ev.ev_id, time] == 0

        # Peak power demand constraint
        for time in range(AlgorithmConstants.TIMESTEPS):
            model += sum(ev_vars[ev.ev_id, time] for ev in self.evs) <= self.peak_power_demand[time]


        # Solve the problem
        model.solve(PULP_CBC_CMD(msg=False))

        # Total percentage of requested energy charged
        total_percentage = model.objective.value()
        logging.info('Maximized Percentage of Charging: %s', total_percentage)

        for ev in self.evs:
            for time in range(AlgorithmConstants.TIMESTEPS):
                ev.power[time] = ev_vars[ev.ev_id, time].varValue # type: ignore

            logging.info('EV %s: Max Power: %s / %s, Energy Charged: %s / %s', ev.ev_id, max(ev.power), ev.max_power, ev.energy_charged(), ev.energy)
