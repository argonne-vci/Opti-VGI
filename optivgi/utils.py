from datetime import datetime, timedelta

def round_down_datetime(dt: datetime, minute: int) -> datetime:
    """Round a timedelta to the nearest minute"""
    return dt - timedelta(minutes=dt.minute % minute, seconds=dt.second, microseconds=dt.microsecond)
