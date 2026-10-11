"""What-if scenarios: small, explicit modifications applied to a copy of the baseline."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

from app.domain.models import CapacityBoost, DateRange, Resource, Task, Workload
from app.domain.validation import WorkloadValidationError

TYPE_BASELINE = "baseline"
TYPE_ADD_WORK = "additional_work"
TYPE_UNAVAILABLE = "resource_unavailability"
TYPE_ADD_CAPACITY = "additional_capacity"
TYPE_DEADLINE = "deadline_change"
TYPE_PRIORITY = "priority_change"
TYPE_REASSIGN = "task_reassignment"


class Modification(Protocol):
    def apply(self, workload: Workload) -> None:
        """Mutate ``workload`` (always a scenario copy, never the baseline)."""


def _resource(workload: Workload, resource_id: str) -> Resource:
    try:
        return workload.resource(resource_id)
    except KeyError:
        raise WorkloadValidationError([f"Scenario refers to unknown resource {resource_id!r}."])


def _task(workload: Workload, task_id: str) -> Task:
    try:
        return workload.task(task_id)
    except KeyError:
        raise WorkloadValidationError([f"Scenario refers to unknown task {task_id!r}."])


@dataclass(frozen=True)
class AddTasks:
    tasks: tuple[Task, ...]

    def apply(self, workload: Workload) -> None:
        workload.tasks.extend(self.tasks)


@dataclass(frozen=True)
class MakeUnavailable:
    resource_id: str
    start: date
    end: date

    def apply(self, workload: Workload) -> None:
        _resource(workload, self.resource_id).unavailable.append(DateRange(self.start, self.end))


@dataclass(frozen=True)
class BoostCapacity:
    resource_id: str
    extra_hours_per_day: float
    start: date
    end: date

    def apply(self, workload: Workload) -> None:
        _resource(workload, self.resource_id).capacity_boosts.append(
            CapacityBoost(DateRange(self.start, self.end), self.extra_hours_per_day)
        )


@dataclass(frozen=True)
class ChangeDeadline:
    task_id: str
    due_date: date

    def apply(self, workload: Workload) -> None:
        _task(workload, self.task_id).due_date = self.due_date


@dataclass(frozen=True)
class ChangePriority:
    task_id: str
    priority: int

    def apply(self, workload: Workload) -> None:
        _task(workload, self.task_id).priority = self.priority


@dataclass(frozen=True)
class ReassignTask:
    task_id: str
    resource_id: str

    def apply(self, workload: Workload) -> None:
        _resource(workload, self.resource_id)
        _task(workload, self.task_id).assigned_resource = self.resource_id


@dataclass(frozen=True)
class Scenario:
    name: str
    scenario_type: str
    description: str = ""
    modifications: tuple[Modification, ...] = field(default_factory=tuple)


BASELINE = Scenario("Baseline", TYPE_BASELINE, "Current workload and capacity, unchanged.")


def apply_scenario(baseline: Workload, scenario: Scenario) -> Workload:
    """Return a modified deep copy of ``baseline``; the baseline itself is untouched.

    The result is validated by the engine like any other workload, so an
    invalid modification (unknown skill, bad date, ...) is reported, not run.
    """
    modified = baseline.copy()
    for modification in scenario.modifications:
        modification.apply(modified)
    return modified


def work_package(
    *,
    prefix: str,
    project: str,
    total_hours: float,
    task_count: int,
    required_skill: str,
    due_date: date,
    priority: int,
    release_date: date | None = None,
) -> tuple[Task, ...]:
    """Split extra work into equal tasks that follow one another (a simple chain)."""
    tasks: list[Task] = []
    for index in range(1, task_count + 1):
        task_id = f"{prefix}{index:02d}"
        tasks.append(
            Task(
                id=task_id,
                description=f"{project} - work item {index} of {task_count}",
                project=project,
                effort_hours=round(total_hours / task_count, 2),
                priority=priority,
                due_date=due_date,
                required_skill=required_skill,
                dependencies=(tasks[-1].id,) if tasks else (),
                release_date=release_date,
            )
        )
    return tuple(tasks)
