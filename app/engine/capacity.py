"""Capacity and working-calendar calculations.

Productive capacity of a resource on a day, in hours:

    0                                              if the day is not one of its working
                                                   weekdays, or it is unavailable
    (hours_per_day + active boosts) * focus_factor otherwise
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, timedelta

from app.domain.models import Resource

# Lateness is reported in business days of this team-wide calendar.
BUSINESS_DAYS = (0, 1, 2, 3, 4)


def iter_days(start: date, end: date) -> Iterator[date]:
    """Every calendar day from ``start`` to ``end`` inclusive."""
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def daily_capacity_minutes(resource: Resource, day: date) -> int:
    """Productive minutes ``resource`` can work on ``day``."""
    if day.weekday() not in resource.working_days:
        return 0
    if any(period.contains(day) for period in resource.unavailable):
        return 0
    hours = resource.hours_per_day + sum(
        b.extra_hours_per_day for b in resource.capacity_boosts if b.period.contains(day)
    )
    return round(hours * resource.focus_factor * 60)


def capacity_minutes(resource: Resource, start: date, end: date) -> int:
    """Total productive minutes of ``resource`` from ``start`` to ``end`` inclusive."""
    return sum(daily_capacity_minutes(resource, day) for day in iter_days(start, end))


def business_days_after(start: date, end: date) -> int:
    """Number of business days later than ``start`` up to and including ``end``."""
    if end <= start:
        return 0
    return sum(1 for day in iter_days(start + timedelta(days=1), end) if day.weekday() in BUSINESS_DAYS)
