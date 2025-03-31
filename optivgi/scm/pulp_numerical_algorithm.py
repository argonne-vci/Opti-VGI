"""
Provides an SCM algorithm implementation using the PuLP linear programming library.

This algorithm formulates the charging schedule optimization as a linear program
and uses a solver (like CBC, GLPK, CPLEX, etc.) interfaced through PuLP to find
an optimal solution based on the defined objective and constraints.
"""
import logging

from pulp import LpVariable, LpProblem, LpMaximize, PULP_CBC_CMD

from .algorithm import Algorithm
from .constants import AlgorithmConstants

class PulpNumericalAlgorithm(Algorithm):
    """
    SCM Algorithm using PuLP for Linear Programming Optimization.

    This algorithm aims to maximize the percentage of requested energy delivered
    across all EVs, while respecting individual EV power limits, arrival/departure
    times, and aggregate peak power constraints for the group. It also includes
    terms to encourage utilizing available peak power and minimizing power fluctuations.
    """

    def calculate(self) -> None:
        """
        Formulates and solves the charging optimization problem using PuLP.

        Steps:
        1. Create an LpProblem instance.
        2. Define decision variables:
           - `ev_vars`: Power allocated to each EV at each time step.
           - `ev_vars_diff`: Absolute difference in power between consecutive time steps for each EV.
           - `percentage`: Minimum percentage of energy charged across all EVs (to be maximized).
        3. Define the objective function: Maximize `percentage`, scaled, plus a term for
           peak power utilization, minus a penalty for power fluctuations (`ev_vars_diff`).
        4. Define constraints:
           - Power difference calculation (using absolute value formulation).
           - Energy charged for each EV must be >= `percentage` * requested energy.
           - Power limits (min/max) for each EV during its connected time.
           - Zero power before arrival and after departure for each EV.
           - Aggregate power demand constraint for each time step.
        5. Solve the linear programming problem using the configured solver (default CBC).
        6. Extract the results (optimal power values) from `ev_vars` and store them
           in the `ev.power` list for each EV object.
        7. Log summary information.
        """
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
