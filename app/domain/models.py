"""Typed domain models for the capacity simulation.

Units used throughout the project:
- effort and capacity: hours (the scheduler converts to whole minutes internally)
- dates: calendar days; a due date means "finished by the end of that day"
- priority: 1 (highest) to 5 (lowest)
- weekdays: 0 = Monday ... 6 = Sunday
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import date

MIN_PRIORITY = 1
MAX_PRIORITY = 5
WEEKDAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


@dataclass(frozen=True)
class DateRange:
    """Inclusive calendar date range."""

    start: date
    end: date

    def contains(self, day: date) -> bool:
        return self.start <= day <= self.end


@dataclass(frozen=True)
class CapacityBoost:
    """Extra scheduled hours per working day during a period (e.g. approved overtime)."""

    period: DateRange
    extra_hours_per_day: float


@dataclass
class Resource:
    id: str
    name: str
    role: str
    skills: tuple[str, ...]
    hours_per_day: float
    working_days: tuple[int, ...] = (0, 1, 2, 3, 4)
    # Share of scheduled hours that is productive project time (meetings, email
    # and context switching take the rest). Capacity is never calendar hours.
    focus_factor: float = 0.8
    unavailable: list[DateRange] = field(default_factory=list)
    capacity_boosts: list[CapacityBoost] = field(default_factory=list)


@dataclass
class Task:
    id: str
    description: str
    project: str
    effort_hours: float
    priority: int
    due_date: date
    required_skill: str
    dependencies: tuple[str, ...] = ()
    # When set, only this resource may do the task. Otherwise every resource
    # holding ``required_skill`` is eligible.
    assigned_resource: str | None = None
    release_date: date | None = None


@dataclass
class Workload:
    """A team, its tasks and the planning period they are simulated in."""

    name: str
    period_start: date
    period_end: date
    resources: list[Resource]
    tasks: list[Task]
    notice: str = ""

    def copy(self) -> Workload:
        """Independent deep copy, so scenarios never mutate the baseline."""
        return copy.deepcopy(self)

    def resource(self, resource_id: str) -> Resource:
        for resource in self.resources:
            if resource.id == resource_id:
                return resource
        raise KeyError(resource_id)

    def task(self, task_id: str) -> Task:
        for task in self.tasks:
            if task.id == task_id:
                return task
        raise KeyError(task_id)

    def eligible_resource_ids(self, task: Task) -> list[str]:
        """Resources allowed to work on ``task``, sorted by ID."""
        if task.assigned_resource is not None:
            return [task.assigned_resource]
        return sorted(r.id for r in self.resources if task.required_skill in r.skills)
