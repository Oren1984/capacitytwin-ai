"""Rules-based recommendations. Every sentence is built from engine output only."""

from __future__ import annotations

from dataclasses import dataclass

from app.analytics.comparison import Comparison
from app.analytics.metrics import (
    STATUS_HIGH,
    STATUS_NO_CAPACITY,
    STATUS_OVERLOADED,
)
from app.engine.scheduler import CAUSE_DEPENDENCY, CAUSE_RESOURCE_BUSY, CAUSE_RESOURCE_CALENDAR
from app.engine.simulation import SimulationResult

CRITICAL = "critical"
WARNING = "warning"
INFO = "info"
POSITIVE = "positive"

MAX_LATE_TASKS_LISTED = 6


@dataclass(frozen=True)
class Recommendation:
    severity: str
    text: str


def _days(count: int) -> str:
    return f"{count} business day{'' if count == 1 else 's'}"


def _name(result: SimulationResult, resource_id: str) -> str:
    return result.workload.resource(resource_id).name


def _late_task_reason(result: SimulationResult, task_id: str) -> str:
    entry = result.schedule[task_id]
    if entry.resource_id is None:
        return entry.unscheduled_reason or "It could not be scheduled."
    if entry.start_cause == CAUSE_DEPENDENCY and entry.blocker_task_id:
        return f"It could only start when prerequisite {entry.blocker_task_id} finished."
    who = _name(result, entry.resource_id)
    if entry.start_cause == CAUSE_RESOURCE_BUSY and entry.blocker_task_id:
        return f"It was ready on {entry.ready_date} but waited for {who}, who was working on {entry.blocker_task_id}."
    if entry.start_cause == CAUSE_RESOURCE_CALENDAR:
        return f"It was ready on {entry.ready_date} but {who} had no working time until {entry.start_date}."
    return f"Its effort does not fit before the due date at {who}'s daily capacity."


def recommend_for_result(result: SimulationResult) -> list[Recommendation]:
    """Findings about a single simulated plan."""
    metrics, workload = result.metrics, result.workload
    recs: list[Recommendation] = []

    if metrics.unscheduled_hours > 0:
        recs.append(
            Recommendation(
                CRITICAL,
                f"{metrics.unscheduled_hours:g} h of work ({metrics.unfinished_tasks} task(s)) does not fit "
                f"in the planning period ending {workload.period_end}. Reduce scope, extend the period or add "
                "eligible capacity.",
            )
        )

    for res in metrics.resources:
        if res.status == STATUS_NO_CAPACITY and res.demand_hours > 0:
            recs.append(
                Recommendation(
                    CRITICAL,
                    f"{res.name} has no available capacity in the period but {res.demand_hours:g} h of work "
                    "can only be done by them.",
                )
            )
        elif res.status == STATUS_OVERLOADED:
            if res.peak_deadline_load_pct is not None and res.peak_deadline_load_pct > 100:
                detail = (
                    f"work due by {res.peak_deadline_date} needs {res.peak_deadline_load_pct:g}% of the "
                    "capacity available up to that date"
                )
            else:
                detail = f"{res.demand_hours:g} h of demand against {res.capacity_hours:g} h of capacity"
            recs.append(Recommendation(WARNING, f"{res.name} is overloaded: {detail}."))
        elif res.status == STATUS_HIGH:
            recs.append(
                Recommendation(
                    INFO,
                    f"{res.name} is operating at high workload demand: {res.peak_deadline_load_pct:g}% of "
                    f"capacity is needed for work due by {res.peak_deadline_date}.",
                )
            )

    if metrics.bottleneck_resource_id:
        res = metrics.resource(metrics.bottleneck_resource_id)
        late_skills = sorted(
            {
                t.required_skill
                for t in workload.tasks
                if metrics.tasks[t.id].late and result.schedule[t.id].resource_id == res.resource_id
            }
        )
        text = (
            f"{res.name} is the main bottleneck: {res.late_tasks_caused} late task(s) trace back to "
            f"waiting for them, and tasks queued {_days(res.queue_wait_days)} in total for their time."
        )
        for skill in late_skills:
            others = [r.name for r in workload.resources if skill in r.skills and r.id != res.resource_id]
            if not others:
                text += (
                    f" No other resource has the '{skill}' skill, so spare capacity elsewhere "
                    "cannot relieve this."
                )
        recs.append(Recommendation(WARNING, text))

    late = [workload.task(tid) for tid in metrics.missed_deadlines]
    for task in late[:MAX_LATE_TASKS_LISTED]:
        tm = metrics.tasks[task.id]
        finish = result.schedule[task.id].finish_date
        if tm.lateness_is_lower_bound:
            outcome = f"is not finished in the period (at least {_days(tm.lateness_days)} late)"
        else:
            outcome = f"is projected {_days(tm.lateness_days)} late (due {task.due_date}, finishes {finish})"
        recs.append(
            Recommendation(
                WARNING,
                f"Task {task.id} ({task.description}) {outcome}. {_late_task_reason(result, task.id)}",
            )
        )
    if len(late) > MAX_LATE_TASKS_LISTED:
        recs.append(
            Recommendation(
                INFO,
                f"{len(late) - MAX_LATE_TASKS_LISTED} more late task(s) are listed in the schedule table.",
            )
        )

    if not workload.tasks:
        recs.append(Recommendation(INFO, "The workload has no tasks, so there is nothing to schedule."))
    elif not late and metrics.unscheduled_hours == 0:
        recs.append(
            Recommendation(
                POSITIVE,
                f"All {metrics.tasks_total} tasks are projected to finish by their due dates; "
                f"final completion {metrics.final_completion_date}.",
            )
        )
    return recs


def recommend_for_comparison(
    baseline: SimulationResult, scenario: SimulationResult, comparison: Comparison
) -> list[Recommendation]:
    """Findings about how a what-if scenario differs from the baseline."""
    recs: list[Recommendation] = []
    name = comparison.scenario_name
    missed, lateness = comparison.delta("missed"), comparison.delta("lateness")
    capacity, final = comparison.delta("capacity"), comparison.delta("final")

    if not comparison.has_effect:
        return [
            Recommendation(
                INFO,
                f"'{name}' has no effect: every metric and every projected completion date is identical "
                "to the baseline.",
            )
        ]

    improved = missed.delta < 0 or lateness.delta < 0
    worsened = missed.delta > 0 or lateness.delta > 0

    summary = (
        f"missed deadlines go from {missed.baseline:g} to {missed.scenario:g} and total lateness from "
        f"{_days(int(lateness.baseline))} to {_days(int(lateness.scenario))}"
    )
    if (improved and worsened) or (comparison.new_missed and comparison.resolved_missed):
        recs.append(
            Recommendation(
                WARNING,
                f"'{name}' is a trade-off, helping some commitments at the expense of others: {summary}.",
            )
        )
    elif improved:
        recs.append(Recommendation(POSITIVE, f"'{name}' improves delivery: {summary}."))
    elif worsened:
        recs.append(
            Recommendation(
                CRITICAL if comparison.new_missed else WARNING, f"'{name}' makes delivery worse: {summary}."
            )
        )
    else:
        recs.append(
            Recommendation(
                INFO,
                f"'{name}' does not change deadline outcomes: still {missed.scenario:g} missed "
                f"deadline(s) and {_days(int(lateness.scenario))} of total lateness.",
            )
        )

    if comparison.new_missed:
        recs.append(
            Recommendation(
                WARNING,
                f"It creates {len(comparison.new_missed)} new deadline violation(s): "
                f"{', '.join(comparison.new_missed)}.",
            )
        )
    if comparison.resolved_missed:
        recs.append(
            Recommendation(
                POSITIVE,
                f"It resolves {len(comparison.resolved_missed)} deadline violation(s): "
                f"{', '.join(comparison.resolved_missed)}.",
            )
        )

    if capacity.delta and capacity.delta > 0 and not improved:
        text = (
            f"Adding {capacity.delta:g} h of capacity does not improve any deadline: the added hours are "
            "not where the schedule is constrained."
        )
        if comparison.bottleneck_after:
            text += f" The bottleneck is still {_name(scenario, comparison.bottleneck_after)}."
        recs.append(Recommendation(INFO, text))

    if final.delta is not None and final.delta != 0:
        direction = "later" if final.delta > 0 else "earlier"
        recs.append(
            Recommendation(
                WARNING if final.delta > 0 else POSITIVE,
                f"Final completion moves {_days(abs(int(final.delta)))} {direction}: "
                f"{final.baseline} to {final.scenario}.",
            )
        )
    elif final.scenario is None and final.baseline is not None:
        recs.append(
            Recommendation(
                CRITICAL,
                f"The work no longer fits in the planning period: {scenario.metrics.unscheduled_hours:g} h "
                "remains unscheduled.",
            )
        )

    if comparison.bottleneck_before != comparison.bottleneck_after:
        before = _name(baseline, comparison.bottleneck_before) if comparison.bottleneck_before else "none"
        after = _name(scenario, comparison.bottleneck_after) if comparison.bottleneck_after else "none"
        recs.append(Recommendation(INFO, f"The main bottleneck changes from {before} to {after}."))

    return recs
