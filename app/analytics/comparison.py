"""Before/after comparison of two simulation results produced by the same engine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.engine.capacity import business_days_after
from app.engine.simulation import SimulationResult


def signed_business_days(before: date, after: date) -> int:
    """Business days from ``before`` to ``after``; negative when ``after`` is earlier."""
    if after >= before:
        return business_days_after(before, after)
    return -business_days_after(after, before)


@dataclass(frozen=True)
class MetricDelta:
    key: str
    label: str
    unit: str
    baseline: float | date | None
    scenario: float | date | None
    delta: float | None  # scenario minus baseline; None when not computable
    lower_is_better: bool | None  # None: neither direction is inherently good

    @property
    def verdict(self) -> str:
        if self.delta is None:
            return "same" if self.baseline == self.scenario else "changed"
        if self.delta == 0:
            return "same"
        if self.lower_is_better is None:
            return "changed"
        return "better" if (self.delta < 0) == self.lower_is_better else "worse"


@dataclass(frozen=True)
class TaskChange:
    task_id: str
    description: str
    baseline_finish: date | None
    scenario_finish: date | None
    shift_days: int | None  # business days; positive = finishes later
    baseline_late: bool
    scenario_late: bool


@dataclass(frozen=True)
class ResourceChange:
    resource_id: str
    name: str
    baseline_capacity_hours: float
    scenario_capacity_hours: float
    baseline_utilization_pct: float | None
    scenario_utilization_pct: float | None
    baseline_status: str
    scenario_status: str


@dataclass(frozen=True)
class Comparison:
    baseline_name: str
    scenario_name: str
    deltas: tuple[MetricDelta, ...]
    task_changes: tuple[TaskChange, ...]  # only tasks whose outcome differs
    resource_changes: tuple[ResourceChange, ...]
    new_missed: tuple[str, ...]
    resolved_missed: tuple[str, ...]
    added_tasks: tuple[str, ...]
    bottleneck_before: str | None
    bottleneck_after: str | None

    def delta(self, key: str) -> MetricDelta:
        return next(d for d in self.deltas if d.key == key)

    @property
    def has_effect(self) -> bool:
        """True when the scenario changes any metric or any task outcome."""
        return bool(self.task_changes or self.added_tasks) or any(d.verdict != "same" for d in self.deltas)


def _number(key, label, unit, before, after, lower_is_better) -> MetricDelta:
    delta = None if before is None or after is None else round(after - before, 1)
    return MetricDelta(key, label, unit, before, after, delta, lower_is_better)


def compare(baseline: SimulationResult, scenario: SimulationResult) -> Comparison:
    b, s = baseline.metrics, scenario.metrics

    finish_delta = None
    if b.final_completion_date and s.final_completion_date:
        finish_delta = signed_business_days(b.final_completion_date, s.final_completion_date)

    deltas = (
        _number("capacity", "Available capacity", "h", b.capacity_hours, s.capacity_hours, None),
        _number("workload", "Estimated workload", "h", b.workload_hours, s.workload_hours, None),
        _number("demand", "Workload demand ratio", "%", b.demand_ratio_pct, s.demand_ratio_pct, None),
        _number("utilization", "Capacity utilization", "%", b.utilization_pct, s.utilization_pct, None),
        _number(
            "missed", "Missed deadlines", "tasks", len(b.missed_deadlines), len(s.missed_deadlines), True
        ),
        _number(
            "lateness",
            "Total lateness",
            "business days",
            b.total_lateness_days,
            s.total_lateness_days,
            True,
        ),
        _number("unfinished", "Unfinished tasks", "tasks", b.unfinished_tasks, s.unfinished_tasks, True),
        _number("unscheduled", "Unscheduled work", "h", b.unscheduled_hours, s.unscheduled_hours, True),
        MetricDelta(
            "final",
            "Final completion date",
            "business days",
            b.final_completion_date,
            s.final_completion_date,
            finish_delta,
            True,
        ),
    )

    baseline_ids = {t.id for t in baseline.workload.tasks}
    task_changes: list[TaskChange] = []
    for task in scenario.workload.tasks:
        if task.id not in baseline_ids:
            continue
        before, after = baseline.schedule[task.id], scenario.schedule[task.id]
        late_before, late_after = b.tasks[task.id].late, s.tasks[task.id].late
        if before.finish_date == after.finish_date and late_before == late_after:
            continue
        shift = None
        if before.finish_date and after.finish_date:
            shift = signed_business_days(before.finish_date, after.finish_date)
        task_changes.append(
            TaskChange(
                task.id,
                task.description,
                before.finish_date,
                after.finish_date,
                shift,
                late_before,
                late_after,
            )
        )

    scenario_resources = {r.resource_id: r for r in s.resources}
    resource_changes = tuple(
        ResourceChange(
            r.resource_id,
            r.name,
            r.capacity_hours,
            scenario_resources[r.resource_id].capacity_hours,
            r.utilization_pct,
            scenario_resources[r.resource_id].utilization_pct,
            r.status,
            scenario_resources[r.resource_id].status,
        )
        for r in b.resources
        if r.resource_id in scenario_resources
    )

    missed_before, missed_after = set(b.missed_deadlines), set(s.missed_deadlines)
    return Comparison(
        baseline_name=baseline.scenario_name,
        scenario_name=scenario.scenario_name,
        deltas=deltas,
        task_changes=tuple(task_changes),
        resource_changes=resource_changes,
        new_missed=tuple(sorted(missed_after - missed_before)),
        resolved_missed=tuple(sorted(missed_before - missed_after)),
        added_tasks=tuple(sorted(t.id for t in scenario.workload.tasks if t.id not in baseline_ids)),
        bottleneck_before=b.bottleneck_resource_id,
        bottleneck_after=s.bottleneck_resource_id,
    )
