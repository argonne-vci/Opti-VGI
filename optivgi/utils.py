# Copyright 2025 UChicago Argonne, LLC All right reserved
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://github.com/argonne-vci/Opti-VGI/blob/main/LICENSE
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
Utility functions for the Opti-VGI package.

This module contains helper functions used across different parts of the application,
such as date and time manipulation.
"""
from datetime import datetime, timedelta

def round_down_datetime(dt: datetime, minute: int) -> datetime:
    """
    Rounds a datetime object down to the nearest specified minute interval.

    For example, rounding 2023-10-27 15:37:45 down with a `minute` interval of 15
    would result in 2023-10-27 15:30:00. Rounding down with an interval of 1
    results in rounding down to the start of the current minute.

    Args:
        dt: The datetime object to round down.
        minute: The minute interval to round down to (e.g., 1, 5, 15, 60).

    Returns:
        The datetime object rounded down to the specified minute interval.

    Raises:
        ValueError: If `minute` is not a positive integer.
    """
    return dt - timedelta(minutes=dt.minute % minute, seconds=dt.second, microseconds=dt.microsecond)
