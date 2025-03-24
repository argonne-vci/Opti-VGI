from datetime import timedelta


class AlgorithmConstants:
    """Constants for the SCM algorithm"""
    RESOLUTION = timedelta(minutes=1)

    RUNTIME = timedelta(hours=8)

    TIMESTEPS = int(RUNTIME.total_seconds() / RESOLUTION.total_seconds())

    POWER_ENERGY_FACTOR = RESOLUTION.total_seconds() / timedelta(hours=1).total_seconds()


class EVConstants:
    """Constants for the EV"""
    CHARGING_PROFILE_ID = 1
    CHARGING_PROFILE_PURPOSE = 'TxProfile'
    CHARGING_PROFILE_STACK_LEVEL = 1
    CHARGING_PROFILE_KIND = 'Absolute'

    CHARGING_RATE_VOLTAGE = 240
