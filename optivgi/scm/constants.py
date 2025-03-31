"""
Defines centralized constants used throughout the SCM package.

Consolidating constants here improves maintainability and clarity. It includes
parameters related to algorithm timing, simulation, energy conversion, and
default values for EV charging profiles.
"""
from datetime import timedelta


class AlgorithmConstants:
    """Constants related to the timing and structure of the SCM algorithm."""

    #: RESOLUTION: The time duration of a single step in the optimization algorithm.
    RESOLUTION = timedelta(minutes=1)

    #: RUNTIME: The total time horizon the optimization algorithm plans for.
    RUNTIME = timedelta(hours=8)

    #: TIMESTEPS: The total number of discrete time steps within the RUNTIME horizon.
    #: Calculated based on RUNTIME and RESOLUTION.
    TIMESTEPS = int(RUNTIME.total_seconds() / RESOLUTION.total_seconds())

    #: POWER_ENERGY_FACTOR: Conversion factor from power (kW or A) applied over
    #: one RESOLUTION period to energy (kWh or Ah).
    #: (RESOLUTION in hours) = RESOLUTION / 1 hour
    POWER_ENERGY_FACTOR = RESOLUTION.total_seconds() / timedelta(hours=1).total_seconds()


class EVConstants:
    """Constants related to Electric Vehicle (EV) properties and charging profiles."""

    #: CHARGING_PROFILE_ID: Default ID to use for generated charging profiles.
    #: Required by OCPP protocol in the charging profile.
    CHARGING_PROFILE_ID = 1

    #: CHARGING_PROFILE_PURPOSE: Default purpose field for charging profiles.
    #: Common values include 'TxProfile', 'ChargePointMaxProfile', 'TxDefaultProfile'.
    CHARGING_PROFILE_PURPOSE = 'TxProfile'

    #: CHARGING_PROFILE_STACK_LEVEL: Default stack level for generated profiles.
    #: Determines priority relative to other profiles. Lower numbers often have higher priority.
    CHARGING_PROFILE_STACK_LEVEL = 1

    #: CHARGING_PROFILE_KIND: Default kind of profile. 'Absolute' means the limits
    #: are absolute values, 'Relative' means percentage, 'Recurring' is time-based.
    CHARGING_PROFILE_KIND = 'Absolute'

    #: CHARGING_RATE_VOLTAGE: Default nominal voltage (in Volts) used for conversions
    #: between Watts (W) and Amperes (A) when the actual voltage is not provided.
    #: Common values are 230V (Europe single-phase), 240V (US split-phase), 120V (US single-phase).
    CHARGING_RATE_VOLTAGE = 240
