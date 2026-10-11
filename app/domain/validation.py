"""Workload validation. Collects every problem instead of stopping at the first."""

from __future__ import annotations

import math

from app.domain.models import MAX_PRIORITY, MIN_PRIORITY, DateRange, Workload

MAX_RESOURCES = 50
MAX_TASKS = 500
MAX_PERIOD_DAYS = 366
MAX_EFFORT_HOURS = 10_000
MAX_HOURS_PER_DAY = 24


class WorkloadValidationError(ValueError):
    """Raised when a workload cannot be simulated. ``issues`` lists every problem."""

    def __init__(self, issues: list[str]):
        self.issues = issues
        super().__init__("; ".join(issues))


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _check_range(label: str, period: DateRange, issues: list[str]) -> None:
    if period.end < period.start:
        issues.append(f"{label}: end date {period.end} is before start date {period.start}.")


def find_cycle(dependencies: dict[str, tuple[str, ...]]) -> list[str] | None:
    """Return one dependency cycle as a list of task IDs, or None if acyclic."""
    state: dict[str, int] = {}  # 1 = on current path, 2 = fully explored

    def visit(node: str, path: list[str]) -> list[str] | None:
        state[node] = 1
        path.append(node)
        for dep in sorted(dependencies.get(node, ())):
            if dep not in dependencies:
                continue
            if state.get(dep) == 1:
                return path[path.index(dep) :] + [dep]
            if dep not in state:
                cycle = visit(dep, path)
                if cycle:
                    return cycle
        path.pop()
        state[node] = 2
        return None

    for node in sorted(dependencies):
        if node not in state:
            cycle = visit(node, [])
            if cycle:
                return cycle
    return None


def validate_workload(workload: Workload) -> list[str]:
    """Return a list of human-readable problems; empty means the workload is valid."""
    issues: list[str] = []

    if workload.period_end < workload.period_start:
        issues.append("Planning period: end date is before start date.")
    elif (workload.period_end - workload.period_start).days + 1 > MAX_PERIOD_DAYS:
        issues.append(f"Planning period is longer than {MAX_PERIOD_DAYS} days.")
    if len(workload.resources) > MAX_RESOURCES:
        issues.append(f"Too many resources (limit {MAX_RESOURCES}).")
    if len(workload.tasks) > MAX_TASKS:
        issues.append(f"Too many tasks (limit {MAX_TASKS}).")

    resource_ids: set[str] = set()
    for res in workload.resources:
        label = f"Resource {res.id!r}"
        if not res.id.strip():
            issues.append("A resource has an empty ID.")
        if res.id in resource_ids:
            issues.append(f"{label}: duplicate resource ID.")
        resource_ids.add(res.id)
        if not _is_number(res.hours_per_day) or not 0 <= res.hours_per_day <= MAX_HOURS_PER_DAY:
            issues.append(f"{label}: hours per day must be between 0 and {MAX_HOURS_PER_DAY}.")
        if not _is_number(res.focus_factor) or not 0 < res.focus_factor <= 1:
            issues.append(f"{label}: focus factor must be greater than 0 and at most 1.")
        if any(not isinstance(d, int) or not 0 <= d <= 6 for d in res.working_days):
            issues.append(f"{label}: working days must be weekday numbers 0 (Mon) to 6 (Sun).")
        if len(set(res.working_days)) != len(res.working_days):
            issues.append(f"{label}: working days contain duplicates.")
        for period in res.unavailable:
            _check_range(f"{label} unavailability", period, issues)
        for boost in res.capacity_boosts:
            _check_range(f"{label} capacity boost", boost.period, issues)
            extra = boost.extra_hours_per_day
            if not _is_number(extra) or extra < 0:
                issues.append(f"{label}: extra hours per day must be zero or positive.")
            elif _is_number(res.hours_per_day) and res.hours_per_day + extra > MAX_HOURS_PER_DAY:
                issues.append(f"{label}: boosted hours exceed {MAX_HOURS_PER_DAY} hours per day.")

    task_ids: set[str] = set()
    for task in workload.tasks:
        if task.id in task_ids:
            issues.append(f"Task {task.id!r}: duplicate task ID.")
        task_ids.add(task.id)

    for task in workload.tasks:
        label = f"Task {task.id!r}"
        if not task.id.strip():
            issues.append("A task has an empty ID.")
        if not _is_number(task.effort_hours) or task.effort_hours <= 0:
            issues.append(f"{label}: effort must be a positive number of hours.")
        elif task.effort_hours > MAX_EFFORT_HOURS:
            issues.append(f"{label}: effort exceeds the {MAX_EFFORT_HOURS}-hour limit.")
        if (
            not isinstance(task.priority, int)
            or isinstance(task.priority, bool)
            or not MIN_PRIORITY <= task.priority <= MAX_PRIORITY
        ):
            issues.append(f"{label}: priority must be an integer {MIN_PRIORITY}-{MAX_PRIORITY}.")
        if task.due_date < workload.period_start:
            issues.append(f"{label}: due date {task.due_date} is before the planning period.")
        if task.release_date is not None and task.release_date > task.due_date:
            issues.append(f"{label}: release date is after its due date.")
        if len(set(task.dependencies)) != len(task.dependencies):
            issues.append(f"{label}: duplicate dependencies.")
        for dep in task.dependencies:
            if dep == task.id:
                issues.append(f"{label}: depends on itself.")
            elif dep not in task_ids:
                issues.append(f"{label}: depends on unknown task {dep!r}.")
        if task.assigned_resource is not None:
            if task.assigned_resource not in resource_ids:
                issues.append(f"{label}: assigned to unknown resource {task.assigned_resource!r}.")
            elif task.required_skill not in workload.resource(task.assigned_resource).skills:
                issues.append(
                    f"{label}: assigned resource {task.assigned_resource!r} "
                    f"lacks required skill {task.required_skill!r}."
                )
        elif not workload.eligible_resource_ids(task):
            issues.append(f"{label}: no resource has required skill {task.required_skill!r}.")

    cycle = find_cycle({t.id: t.dependencies for t in workload.tasks if t.id not in t.dependencies})
    if cycle:
        issues.append("Cyclic dependency: " + " -> ".join(cycle) + ".")

    return issues


def ensure_valid(workload: Workload) -> None:
    issues = validate_workload(workload)
    if issues:
        raise WorkloadValidationError(issues)
