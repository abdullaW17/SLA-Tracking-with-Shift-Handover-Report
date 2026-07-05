"""
services/business_hours.py
----------------------------
Business-hours-aware SLA deadline calculation (Gap #3).

Provides ``add_business_minutes(start_dt, minutes, client)`` which returns
a deadline datetime that only counts working hours.

Default schedule: Monday-Friday 09:00-17:00 in the client's timezone.
The schedule is intentionally kept simple for the MVP — a per-client
``BusinessCalendar`` model can be added later to support holidays, custom
hours, etc.
"""

from datetime import datetime, timedelta, timezone, time
from zoneinfo import ZoneInfo

# Default working schedule (can be overridden per-client in a future version)
DEFAULT_WORK_START = time(9, 0)   # 09:00
DEFAULT_WORK_END = time(17, 0)    # 17:00
DEFAULT_WORK_DAYS = {0, 1, 2, 3, 4}  # Mon-Fri (datetime.weekday() values)
BUSINESS_MINUTES_PER_DAY = (
    (datetime.combine(datetime.today(), DEFAULT_WORK_END) -
     datetime.combine(datetime.today(), DEFAULT_WORK_START)).total_seconds() / 60
)


def _get_client_tz(client):
    """Resolve the client's timezone to a ZoneInfo object, defaulting to UTC."""
    tz_name = "UTC"
    if client and hasattr(client, "timezone") and client.timezone:
        tz_name = client.timezone
    try:
        return ZoneInfo(tz_name)
    except (KeyError, Exception):
        return ZoneInfo("UTC")


def add_business_minutes(start_dt, minutes, client=None):
    """
    Compute a deadline by adding ``minutes`` of business time to ``start_dt``.

    Only hours within the working window (default Mon-Fri 09:00-17:00 in the
    client's timezone) are counted.  Weekends and outside-hours periods are
    skipped.

    Args:
        start_dt: timezone-aware datetime (UTC internally)
        minutes: int — the number of business minutes to add
        client: optional Client model instance (provides timezone)

    Returns:
        timezone-aware datetime (UTC) representing the deadline
    """
    if minutes <= 0:
        return start_dt

    client_tz = _get_client_tz(client)

    # Convert start time to the client's local timezone for calendar math
    local_dt = start_dt.astimezone(client_tz)

    remaining = float(minutes)

    while remaining > 0:
        # If we're on a non-working day, skip to next working day start
        if local_dt.weekday() not in DEFAULT_WORK_DAYS:
            # Jump to next Monday (or next working day)
            days_ahead = 1
            next_dt = local_dt + timedelta(days=days_ahead)
            while next_dt.weekday() not in DEFAULT_WORK_DAYS:
                next_dt += timedelta(days=1)
            local_dt = next_dt.replace(
                hour=DEFAULT_WORK_START.hour,
                minute=DEFAULT_WORK_START.minute,
                second=0, microsecond=0,
            )
            continue

        local_time = local_dt.time()

        # Before business hours — fast-forward to start of day
        if local_time < DEFAULT_WORK_START:
            local_dt = local_dt.replace(
                hour=DEFAULT_WORK_START.hour,
                minute=DEFAULT_WORK_START.minute,
                second=0, microsecond=0,
            )
            continue

        # After business hours — skip to next working day
        if local_time >= DEFAULT_WORK_END:
            local_dt = local_dt + timedelta(days=1)
            local_dt = local_dt.replace(
                hour=DEFAULT_WORK_START.hour,
                minute=DEFAULT_WORK_START.minute,
                second=0, microsecond=0,
            )
            # May have landed on a weekend — loop will handle it
            continue

        # We're within working hours — consume as many minutes as possible today
        end_of_day = local_dt.replace(
            hour=DEFAULT_WORK_END.hour,
            minute=DEFAULT_WORK_END.minute,
            second=0, microsecond=0,
        )
        available_minutes = (end_of_day - local_dt).total_seconds() / 60

        if remaining <= available_minutes:
            local_dt = local_dt + timedelta(minutes=remaining)
            remaining = 0
        else:
            remaining -= available_minutes
            # Move to next working day
            local_dt = local_dt + timedelta(days=1)
            local_dt = local_dt.replace(
                hour=DEFAULT_WORK_START.hour,
                minute=DEFAULT_WORK_START.minute,
                second=0, microsecond=0,
            )

    # Convert back to UTC for storage
    return local_dt.astimezone(timezone.utc)
