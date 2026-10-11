"""Deterministic dependency-aware priority scheduler.

Policy (documented in docs/simulation-methodology.md):

1. Time advances day by day through the planning period; inside a day each
   resource has a window of productive minutes that starts at minute 0.
2. A task is *ready* once its release date has arrived and every prerequisite
   is finished. A task can start in the same day its last prerequisite ends.
3. Whenever resources are free, ready tasks are dispatched in the order
   (priority, due date, task ID) to the eligible free resource with the lowest ID.
4. A resource works on one task at a time. A started task stays with its
   resource until it is finished (no preemption, no hand-over); it simply
   pauses over days on which that resource has no capacity.
5. Work that does not fit in the planning period is reported, never dropped.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.domain.models import Task, Workload
from app.engine.capacity import daily_capacity_minutes, iter_days

Moment = tuple[date, int]  # (day, minute within that day's working window)

STATUS_COMPLETED = "completed"
STATUS_PARTIAL = "partial"
STATUS_UNSCHEDULED = "unscheduled"

# Why a task started when it did.
CAUSE_NONE = "none"  # started as soon as the period opened
CAUSE_RELEASE = "release"  # waited for its own release date
CAUSE_DEPENDENCY = "dependency"  # started the moment a prerequisite finished
CAUSE_RESOURCE_BUSY = "resource_busy"  # was ready, resource was on another task
CAUSE_RESOURCE_CALENDAR = "resource_calendar"  # was ready, resource was unavailable


@dataclass(frozen=True)
class Segment:
    """A contiguous block of work on one day."""

    day: date
    resource_id: str
    start_minute: int
    end_minute: int

    @property
    def minutes(self) -> int:
        return self.end_minute - self.start_minute


@dataclass
class TaskSchedule:
    task_id: str
    status: str = STATUS_UNSCHEDULED
    resource_id: str | None = None
    ready_date: date | None = None
    start_date: date | None = None
    finish_date: date | None = None
    scheduled_minutes: int = 0
    remaining_minutes: int = 0
    start_cause: str | None = None
    blocker_task_id: str | None = None
    unscheduled_reason: str | None = None
    segments: list[Segment] = field(default_factory=list)


def effort_minutes(task: Task) -> int:
    return max(1, round(task.effort_hours * 60))


def dispatch_key(task: Task) -> tuple[int, date, str]:
    """Deterministic ordering of competing ready tasks."""
    return (task.priority, task.due_date, task.id)


def build_schedule(workload: Workload) -> dict[str, TaskSchedule]:
    """Simulate the workload and return one ``TaskSchedule`` per task.

    The workload must already be valid (see ``app.domain.validation``).
    """
    tasks = sorted(workload.tasks, key=dispatch_key)
    eligible = {t.id: workload.eligible_resource_ids(t) for t in tasks}
    resource_ids = sorted(r.id for r in workload.resources)
    resources = {r.id: r for r in workload.resources}

    result = {t.id: TaskSchedule(task_id=t.id, remaining_minutes=effort_minutes(t)) for t in tasks}
    finished_at: dict[str, Moment] = {}
    in_progress: dict[str, str] = {}  # resource ID -> task ID
    last_work: dict[str, tuple[Moment, str]] = {}  # resource ID -> (end moment, task ID)
    period_open: Moment = (workload.period_start, 0)

    def ready_moment(task: Task) -> Moment | None:
        """When the task became ready, or None while a prerequisite is unfinished."""
        moment = period_open
        if task.release_date is not None:
            moment = max(moment, (task.release_date, 0))
        for dep in task.dependencies:
            if dep not in finished_at:
                return None
            moment = max(moment, finished_at[dep])
        return moment

    def start_cause(task: Task, rid: str, ready: Moment, now: Moment) -> tuple[str, str | None]:
        if now > ready:
            previous = last_work.get(rid)
            if previous and previous[0] > ready:
                return CAUSE_RESOURCE_BUSY, previous[1]
            res = resources[rid]
            if any(
                d.weekday() in res.working_days and any(p.contains(d) for p in res.unavailable)
                for d in iter_days(ready[0], now[0])
            ):
                return CAUSE_RESOURCE_CALENDAR, None
            # Otherwise the gap is only the resource's normal off-hours (night, weekend,
            # part-time day): the start is still attributed to what made the task ready.
        deps_done = [(finished_at[d], d) for d in task.dependencies]
        if deps_done and max(deps_done)[0] == ready:
            return CAUSE_DEPENDENCY, max(deps_done)[1]
        if task.release_date is not None and ready == (task.release_date, 0) != period_open:
            return CAUSE_RELEASE, None
        return CAUSE_NONE, None

    for day in iter_days(workload.period_start, workload.period_end):
        window = {rid: daily_capacity_minutes(resources[rid], day) for rid in resource_ids}
        active = [rid for rid in resource_ids if window[rid] > 0]
        clock = {rid: 0 for rid in active}

        def work(rid: str, day: date = day, clock: dict = clock, window: dict = window) -> None:
            """Advance the resource's in-progress task until it ends or the day does."""
            entry = result[in_progress[rid]]
            chunk = min(window[rid] - clock[rid], entry.remaining_minutes)
            entry.segments.append(Segment(day, rid, clock[rid], clock[rid] + chunk))
            entry.scheduled_minutes += chunk
            entry.remaining_minutes -= chunk
            clock[rid] += chunk
            last_work[rid] = ((day, clock[rid]), entry.task_id)
            if entry.remaining_minutes == 0:
                entry.status = STATUS_COMPLETED
                entry.finish_date = day
                finished_at[entry.task_id] = (day, clock[rid])
                del in_progress[rid]

        while True:
            open_ids = [rid for rid in active if clock[rid] < window[rid]]
            if not open_ids:
                break
            minute = min(clock[rid] for rid in open_ids)
            now: Moment = (day, minute)

            free: list[str] = []
            for rid in open_ids:
                if clock[rid] != minute:
                    continue
                if rid in in_progress:
                    work(rid)
                else:
                    free.append(rid)

            for task in tasks:
                if not free:
                    break
                entry = result[task.id]
                if entry.resource_id is not None:
                    continue
                ready = ready_moment(task)
                if ready is None or ready > now:
                    continue
                rid = next((r for r in free if r in eligible[task.id]), None)
                if rid is None:
                    continue
                entry.resource_id = rid
                entry.status = STATUS_PARTIAL
                entry.ready_date = ready[0]
                entry.start_date = day
                entry.start_cause, entry.blocker_task_id = start_cause(task, rid, ready, now)
                in_progress[rid] = task.id
                free.remove(rid)
                work(rid)

            # Nothing to do right now: wait for the next moment another resource
            # reaches (a possible task completion), or call it a day.
            for rid in free:
                later = [clock[other] for other in active if clock[other] > minute]
                clock[rid] = min([window[rid], *later])

    _explain_unfinished(workload, result, finished_at, eligible)
    return result


def _explain_unfinished(
    workload: Workload,
    result: dict[str, TaskSchedule],
    finished_at: dict[str, Moment],
    eligible: dict[str, list[str]],
) -> None:
    """Attach a plain-language reason to every task not completed in the period."""
    resources = {r.id: r for r in workload.resources}
    for task in workload.tasks:
        entry = result[task.id]
        if entry.status == STATUS_COMPLETED:
            continue
        if entry.status == STATUS_PARTIAL:
            entry.unscheduled_reason = "Started but not finished within the planning period."
            continue
        ready = None
        if all(dep in finished_at for dep in task.dependencies):
            ready = max(
                [finished_at[d][0] for d in task.dependencies] + [task.release_date or workload.period_start]
            )
            entry.ready_date = ready
        unfinished_deps = sorted(d for d in task.dependencies if d not in finished_at)
        has_capacity = any(
            daily_capacity_minutes(resources[rid], day) > 0
            for rid in eligible[task.id]
            for day in iter_days(workload.period_start, workload.period_end)
        )
        if not has_capacity:
            entry.unscheduled_reason = "No eligible resource has any capacity in the period."
        elif unfinished_deps:
            entry.unscheduled_reason = (
                "Blocked by unfinished prerequisite(s): " + ", ".join(unfinished_deps) + "."
            )
            entry.blocker_task_id = unfinished_deps[0]
        elif ready is not None and ready > workload.period_end:
            entry.unscheduled_reason = "Release date is after the planning period."
        else:
            entry.unscheduled_reason = "Eligible resources were fully booked until the period ended."
