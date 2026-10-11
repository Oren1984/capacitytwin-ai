"""Tabular views and safe exports of simulation results."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import asdict
from datetime import timedelta

from app.analytics.comparison import Comparison
from app.analytics.recommendations import Recommendation
from app.engine.simulation import SimulationResult

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")

DISCLAIMER = (
    "Estimates from a simplified deterministic model with explicit assumptions. "
    "Decision support only; not a prediction."
)


def sanitize_cell(value: object) -> object:
    """Neutralise spreadsheet formula injection in exported text cells."""
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def schedule_rows(result: SimulationResult) -> list[dict]:
    """One row per task, ordered by start date then ID."""
    rows = []
    for task in result.workload.tasks:
        entry = result.schedule[task.id]
        tm = result.metrics.tasks[task.id]
        resource = result.workload.resource(entry.resource_id).name if entry.resource_id else ""
        rows.append(
            {
                "Task": task.id,
                "Description": task.description,
                "Project": task.project,
                "Resource": resource,
                "Effort (h)": task.effort_hours,
                "Priority": task.priority,
                "Depends on": ", ".join(task.dependencies),
                "Start": entry.start_date.isoformat() if entry.start_date else "",
                "Finish": entry.finish_date.isoformat() if entry.finish_date else "",
                "Due": task.due_date.isoformat(),
                "Status": entry.status,
                "Late (business days)": tm.lateness_days,
                "Lateness is lower bound": tm.lateness_is_lower_bound,
                "Waited for resource (business days)": tm.wait_days,
                "Start driven by": entry.start_cause or "",
                "Blocked by task": entry.blocker_task_id or "",
                "Note": entry.unscheduled_reason or "",
            }
        )
    rows.sort(key=lambda r: (r["Start"] or "9999", r["Task"]))
    return rows


def schedule_csv(result: SimulationResult) -> str:
    rows = schedule_rows(result)
    buffer = io.StringIO()
    if rows:
        writer = csv.DictWriter(buffer, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: sanitize_cell(value) for key, value in row.items()})
    return buffer.getvalue()


def _metrics_dict(result: SimulationResult) -> dict:
    m = result.metrics
    return {
        "scenario": result.scenario_name,
        "run_id": result.run_id,
        "capacity_hours": m.capacity_hours,
        "workload_hours": m.workload_hours,
        "scheduled_hours": m.scheduled_hours,
        "unscheduled_hours": m.unscheduled_hours,
        "demand_ratio_pct": m.demand_ratio_pct,
        "utilization_pct": m.utilization_pct,
        "tasks_total": m.tasks_total,
        "tasks_completed": m.tasks_completed,
        "missed_deadlines": list(m.missed_deadlines),
        "total_lateness_business_days": m.total_lateness_days,
        "lateness_is_lower_bound": m.lateness_is_lower_bound,
        "final_completion_date": m.final_completion_date,
        "bottleneck_resource_id": m.bottleneck_resource_id,
        "blocking_task_id": m.blocking_task_id,
        "resources": [asdict(r) for r in m.resources],
        "schedule": schedule_rows(result),
    }


def report_json(
    baseline: SimulationResult,
    recommendations: list[Recommendation],
    scenario: SimulationResult | None = None,
    comparison: Comparison | None = None,
) -> str:
    """Full machine-readable report. Dates are ISO strings; no objects are pickled."""
    report: dict = {
        "disclaimer": DISCLAIMER,
        "data_notice": baseline.workload.notice,
        "baseline": _metrics_dict(baseline),
        "recommendations": [asdict(r) for r in recommendations],
    }
    if scenario is not None and comparison is not None:
        report["scenario"] = _metrics_dict(scenario)
        report["comparison"] = {
            "deltas": [asdict(d) | {"verdict": d.verdict} for d in comparison.deltas],
            "task_changes": [asdict(c) for c in comparison.task_changes],
            "new_missed_deadlines": list(comparison.new_missed),
            "resolved_missed_deadlines": list(comparison.resolved_missed),
            "added_tasks": list(comparison.added_tasks),
            "has_effect": comparison.has_effect,
        }
    return json.dumps(report, indent=2, default=str)


def timeline_rows(result: SimulationResult) -> list[dict]:
    """Gantt bars: one row per run of consecutive calendar days a task was worked on.

    ``End`` is exclusive (the morning after the last worked day) so bars have width.
    """
    rows = []
    for task in result.workload.tasks:
        entry = result.schedule[task.id]
        tm = result.metrics.tasks[task.id]
        days = sorted({segment.day for segment in entry.segments})
        runs: list[list] = []
        for day in days:
            if runs and day - runs[-1][1] == timedelta(days=1):
                runs[-1][1] = day
            else:
                runs.append([day, day])
        for run_start, run_end in runs:
            rows.append(
                {
                    "Task": task.id,
                    "Description": task.description,
                    "Project": task.project,
                    "Resource": result.workload.resource(entry.resource_id).name,
                    "Start": run_start,
                    "End": run_end + timedelta(days=1),
                    "First start": entry.start_date,
                    "Finish": entry.finish_date,
                    "Due": task.due_date,
                    "Late": tm.late,
                    "Late (business days)": tm.lateness_days,
                    "Status": entry.status,
                }
            )
    return rows
