"""Metrics derived from a schedule. All definitions are in docs/simulation-methodology.md.

Two ratios are kept strictly apart:
- demand ratio   = estimated workload hours / available capacity hours (may exceed 100 %)
- utilization    = hours actually scheduled / available capacity hours (never exceeds 100 %)
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date

from app.domain.models import Workload
from app.engine.capacity import business_days_after, capacity_minutes
from app.engine.scheduler import (
    CAUSE_DEPENDENCY,
    CAUSE_RESOURCE_BUSY,
    CAUSE_RESOURCE_CALENDAR,
    STATUS_COMPLETED,
    TaskSchedule,
    effort_minutes,
)

HIGH_LOAD_PCT = 85.0
STATUS_OVERLOADED = "overloaded"
STATUS_HIGH = "high"
STATUS_OK = "ok"
STATUS_NO_CAPACITY = "no capacity"


def pct(part: float, whole: float) -> float | None:
    """Percentage, or None when the denominator is zero (shown as 'n/a')."""
    return round(part / whole * 100, 1) if whole > 0 else None


@dataclass(frozen=True)
class ChainLink:
    """One step back along the chain of events that fixed a task's start."""

    task_id: str
    cause: str
    resource_id: str | None
    blocker_task_id: str | None


@dataclass(frozen=True)
class TaskMetrics:
    task_id: str
    completed: bool
    late: bool
    # Business days after the due date. For unfinished tasks this is a lower bound.
    lateness_days: int
    lateness_is_lower_bound: bool
    wait_days: int
    delay_chain: tuple[ChainLink, ...]


@dataclass(frozen=True)
class ResourceMetrics:
    resource_id: str
    name: str
    capacity_hours: float
    demand_hours: float
    scheduled_hours: float
    demand_ratio_pct: float | None
    utilization_pct: float | None
    # Highest "work due by date D / capacity up to D" over this resource's deadlines.
    peak_deadline_load_pct: float | None
    peak_deadline_date: date | None
    queue_wait_days: int
    late_tasks_caused: int
    status: str


@dataclass(frozen=True)
class Metrics:
    capacity_hours: float
    workload_hours: float
    scheduled_hours: float
    unscheduled_hours: float
    demand_ratio_pct: float | None
    utilization_pct: float | None
    tasks_total: int
    tasks_completed: int
    missed_deadlines: tuple[str, ...]
    total_lateness_days: int
    lateness_is_lower_bound: bool
    final_completion_date: date | None  # None when work remains after the period
    bottleneck_resource_id: str | None
    blocking_task_id: str | None
    resources: tuple[ResourceMetrics, ...]
    tasks: dict[str, TaskMetrics]

    @property
    def unfinished_tasks(self) -> int:
        return self.tasks_total - self.tasks_completed

    def resource(self, resource_id: str) -> ResourceMetrics:
        return next(r for r in self.resources if r.resource_id == resource_id)


def _delay_chain(task_id: str, schedule: dict[str, TaskSchedule]) -> tuple[ChainLink, ...]:
    chain: list[ChainLink] = []
    seen: set[str] = set()
    current: str | None = task_id
    while current is not None and current not in seen:
        seen.add(current)
        entry = schedule[current]
        cause = entry.start_cause or "not_started"
        chain.append(ChainLink(current, cause, entry.resource_id, entry.blocker_task_id))
        current = entry.blocker_task_id
    return tuple(chain)


def compute_metrics(workload: Workload, schedule: dict[str, TaskSchedule]) -> Metrics:
    start, end = workload.period_start, workload.period_end

    task_metrics: dict[str, TaskMetrics] = {}
    for task in workload.tasks:
        entry = schedule[task.id]
        completed = entry.status == STATUS_COMPLETED
        if completed:
            lateness = business_days_after(task.due_date, entry.finish_date)
            late, lower_bound = lateness > 0, False
        elif task.due_date <= end:
            # Cannot finish before the first business day after the period.
            lateness = business_days_after(task.due_date, end) + 1
            late, lower_bound = True, True
        else:
            lateness, late, lower_bound = 0, False, False
        waited = (
            entry.start_cause in (CAUSE_RESOURCE_BUSY, CAUSE_RESOURCE_CALENDAR)
            and entry.ready_date is not None
        )
        task_metrics[task.id] = TaskMetrics(
            task_id=task.id,
            completed=completed,
            late=late,
            lateness_days=lateness,
            lateness_is_lower_bound=lower_bound,
            wait_days=business_days_after(entry.ready_date, entry.start_date) if waited else 0,
            delay_chain=_delay_chain(task.id, schedule) if late else (),
        )

    # Attribute each late task to the resources it (or its chain) had to queue for.
    late_by_resource: Counter[str] = Counter()
    blocking_tasks: Counter[str] = Counter()
    for tm in task_metrics.values():
        waited_on = {
            link.resource_id
            for link in tm.delay_chain
            if link.cause in (CAUSE_RESOURCE_BUSY, CAUSE_RESOURCE_CALENDAR) and link.resource_id
        }
        late_by_resource.update(waited_on)
        # Only tasks that are themselves late can be blamed for a downstream delay.
        blocking_tasks.update(link.task_id for link in tm.delay_chain[1:] if task_metrics[link.task_id].late)

    resource_metrics: list[ResourceMetrics] = []
    for res in sorted(workload.resources, key=lambda r: r.id):
        cap_min = capacity_minutes(res, start, end)
        own_tasks = [
            t
            for t in workload.tasks
            if schedule[t.id].resource_id == res.id
            or (schedule[t.id].resource_id is None and workload.eligible_resource_ids(t) == [res.id])
        ]
        demand_min = sum(effort_minutes(t) for t in own_tasks)
        scheduled_min = sum(
            seg.minutes for e in schedule.values() for seg in e.segments if seg.resource_id == res.id
        )

        peak_pct: float | None = None
        peak_date: date | None = None
        zero_capacity_deadline = False
        for due in sorted({t.due_date for t in own_tasks}):
            due_demand = sum(effort_minutes(t) for t in own_tasks if t.due_date <= due)
            due_capacity = capacity_minutes(res, start, min(due, end))
            if due_capacity == 0:
                zero_capacity_deadline = True
                continue
            load = round(due_demand / due_capacity * 100, 1)
            if peak_pct is None or load > peak_pct:
                peak_pct, peak_date = load, due

        if cap_min == 0:
            status = STATUS_NO_CAPACITY
        elif demand_min > cap_min or zero_capacity_deadline or (peak_pct or 0) > 100:
            status = STATUS_OVERLOADED
        elif (peak_pct or 0) >= HIGH_LOAD_PCT:
            status = STATUS_HIGH
        else:
            status = STATUS_OK

        resource_metrics.append(
            ResourceMetrics(
                resource_id=res.id,
                name=res.name,
                capacity_hours=round(cap_min / 60, 1),
                demand_hours=round(demand_min / 60, 1),
                scheduled_hours=round(scheduled_min / 60, 1),
                demand_ratio_pct=pct(demand_min, cap_min),
                utilization_pct=pct(scheduled_min, cap_min),
                peak_deadline_load_pct=peak_pct,
                peak_deadline_date=peak_date,
                queue_wait_days=sum(
                    task_metrics[t.id].wait_days
                    for t in workload.tasks
                    if schedule[t.id].resource_id == res.id
                ),
                late_tasks_caused=late_by_resource[res.id],
                status=status,
            )
        )

    # Bottleneck: the resource behind the most late tasks; ties go to the longest queue.
    bottleneck = None
    if late_by_resource:
        bottleneck = min(
            (r for r in resource_metrics if r.late_tasks_caused > 0),
            key=lambda r: (-r.late_tasks_caused, -r.queue_wait_days, r.resource_id),
        ).resource_id
    blocking_task = None
    if blocking_tasks:
        blocking_task = min(blocking_tasks, key=lambda tid: (-blocking_tasks[tid], tid))

    capacity_min = sum(capacity_minutes(r, start, end) for r in workload.resources)
    workload_min = sum(effort_minutes(t) for t in workload.tasks)
    scheduled_min = sum(e.scheduled_minutes for e in schedule.values())
    completed = [e for e in schedule.values() if e.status == STATUS_COMPLETED]
    all_done = len(completed) == len(workload.tasks)
    late = [tm for tm in task_metrics.values() if tm.late]

    return Metrics(
        capacity_hours=round(capacity_min / 60, 1),
        workload_hours=round(workload_min / 60, 1),
        scheduled_hours=round(scheduled_min / 60, 1),
        unscheduled_hours=round((workload_min - scheduled_min) / 60, 1),
        demand_ratio_pct=pct(workload_min, capacity_min),
        utilization_pct=pct(scheduled_min, capacity_min),
        tasks_total=len(workload.tasks),
        tasks_completed=len(completed),
        missed_deadlines=tuple(sorted(tm.task_id for tm in late)),
        total_lateness_days=sum(tm.lateness_days for tm in late),
        lateness_is_lower_bound=any(tm.lateness_is_lower_bound for tm in late),
        final_completion_date=(max((e.finish_date for e in completed), default=None) if all_done else None),
        bottleneck_resource_id=bottleneck,
        blocking_task_id=blocking_task,
        resources=tuple(resource_metrics),
        tasks=task_metrics,
    )


def first_dependency_blocker(tm: TaskMetrics) -> str | None:
    """The prerequisite that directly fixed this task's start, if any."""
    if tm.delay_chain and tm.delay_chain[0].cause in (CAUSE_DEPENDENCY, "not_started"):
        return tm.delay_chain[0].blocker_task_id
    return None
