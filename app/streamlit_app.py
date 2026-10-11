"""CapacityTwin AI - Streamlit dashboard.

Presentation only: every number shown comes from ``app.engine`` / ``app.analytics``.
Run with:  streamlit run app/streamlit_app.py
"""

from __future__ import annotations

import logging
import sys
from datetime import date, timedelta
from pathlib import Path

# Streamlit puts this file's folder on sys.path; the ``app`` package lives one level up.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import altair as alt  # noqa: E402
import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from app.ai.provider import build_evidence, get_provider  # noqa: E402
from app.analytics.comparison import Comparison, compare  # noqa: E402
from app.analytics.metrics import (  # noqa: E402
    STATUS_HIGH,
    STATUS_NO_CAPACITY,
    STATUS_OK,
    STATUS_OVERLOADED,
)
from app.analytics.recommendations import (  # noqa: E402
    CRITICAL,
    INFO,
    POSITIVE,
    WARNING,
    Recommendation,
    recommend_for_comparison,
    recommend_for_result,
)
from app.config import configure_logging  # noqa: E402
from app.domain.models import MAX_PRIORITY, MIN_PRIORITY, WEEKDAY_NAMES, Workload  # noqa: E402
from app.domain.validation import WorkloadValidationError  # noqa: E402
from app.engine.simulation import SimulationEngine, SimulationResult  # noqa: E402
from app.scenarios import manager as sc  # noqa: E402
from app.services.loader import load_default_workload, parse_workload_file  # noqa: E402
from app.services.reporting import (  # noqa: E402
    DISCLAIMER,
    report_json,
    schedule_csv,
    schedule_rows,
    timeline_rows,
)

logger = logging.getLogger("capacitytwin.ui")
engine = SimulationEngine()

# Validated categorical pair (blue, orange) and reserved status colours.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
STATUS_COLORS = {
    STATUS_OK: "#2a78d6",
    STATUS_HIGH: "#fab219",
    STATUS_OVERLOADED: "#d03b3b",
    STATUS_NO_CAPACITY: "#898781",
}
STATUS_LABELS = {
    STATUS_OK: "OK",
    STATUS_HIGH: "High load",
    STATUS_OVERLOADED: "Overloaded",
    STATUS_NO_CAPACITY: "No capacity",
}
CAUSE_LABELS = {
    "none": "Start of planning period",
    "release": "Its own release date",
    "dependency": "A prerequisite finishing",
    "resource_busy": "Resource busy on another task",
    "resource_calendar": "Resource had no working time",
    "not_started": "Not started",
}
SCENARIO_LABELS = {
    sc.TYPE_ADD_WORK: "B - Additional work",
    sc.TYPE_UNAVAILABLE: "C - Resource unavailability",
    sc.TYPE_ADD_CAPACITY: "D - Additional capacity",
    sc.TYPE_DEADLINE: "E - Deadline change",
    sc.TYPE_PRIORITY: "E - Priority change",
    sc.TYPE_REASSIGN: "F - Task reassignment",
}
SEVERITY_ICONS = {CRITICAL: "🛑", WARNING: "⚠️", INFO: "ℹ️", POSITIVE: "✅"}


# --------------------------------------------------------------------------- state


def set_workload(workload: Workload) -> None:
    """Install a new baseline workload and discard any scenario built on the old one."""
    st.session_state.workload = workload
    st.session_state.baseline = engine.run(workload, "Baseline")
    st.session_state.scenario = None
    st.session_state.comparison = None


def show_issues(title: str, error: WorkloadValidationError) -> None:
    st.error(title + "\n\n" + "\n".join(f"- {issue}" for issue in error.issues[:15]))
    if len(error.issues) > 15:
        st.caption(f"... and {len(error.issues) - 15} more issue(s).")


def fmt_pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:g}%"


def fmt_date(value: date | None) -> str:
    return value.strftime("%a %d %b %Y") if value else "Beyond period"


# --------------------------------------------------------------------------- sections


def sidebar() -> None:
    with st.sidebar:
        st.header("Dataset")
        workload: Workload = st.session_state.workload
        st.write(f"**{workload.name}**")
        st.caption(
            f"{workload.period_start:%d %b %Y} to {workload.period_end:%d %b %Y} · "
            f"{len(workload.resources)} resources · {len(workload.tasks)} tasks"
        )
        if st.button("Restore default dataset", help="Reload the built-in synthetic demo workload."):
            set_workload(load_default_workload())
            st.session_state.uploader_key = st.session_state.get("uploader_key", 0) + 1
            st.rerun()

        uploaded = st.file_uploader(
            "Load a workload file (.json)",
            type=["json"],
            key=f"upload-{st.session_state.get('uploader_key', 0)}",
            help="Same structure as data/synthetic/default_workload.json. Maximum 1 MB.",
        )
        if uploaded is not None and st.session_state.get("loaded_file") != uploaded.file_id:
            try:
                set_workload(parse_workload_file(uploaded.name, uploaded.getvalue()))
                st.session_state.loaded_file = uploaded.file_id
                st.rerun()
            except WorkloadValidationError as error:
                logger.warning("upload rejected issues=%d", len(error.issues))
                show_issues("The file was not loaded:", error)

        st.divider()
        st.caption(
            f"Explanations: **{get_provider().mode} mode** (deterministic templates, no AI service is called)."
        )
        st.caption("Local demonstration tool. Not designed for public internet exposure.")


def overview(result: SimulationResult, baseline: SimulationResult) -> None:
    m, b = result.metrics, baseline.metrics
    is_scenario = result is not baseline

    def delta(now: float | None, before: float | None, unit: str) -> str | None:
        if not is_scenario or now is None or before is None:
            return None
        return f"{now - before:+g} {unit}"

    cols = st.columns(5)
    cols[0].metric(
        "Available capacity",
        f"{m.capacity_hours:g} h",
        delta(m.capacity_hours, b.capacity_hours, "h"),
        delta_color="off",
        help="Productive hours of all resources in the planning period: working days x hours per day x "
        "focus factor, minus unavailability.",
    )
    cols[1].metric(
        "Estimated workload",
        f"{m.workload_hours:g} h",
        delta(m.workload_hours, b.workload_hours, "h"),
        delta_color="off",
        help="Sum of the effort estimates of all tasks.",
    )
    cols[2].metric(
        "Capacity utilization",
        fmt_pct(m.utilization_pct),
        delta(m.utilization_pct, b.utilization_pct, "pts"),
        delta_color="off",
        help="Hours actually scheduled / available capacity. Never above 100%. "
        f"Workload demand ratio (workload / capacity): {fmt_pct(m.demand_ratio_pct)}.",
    )
    late_label = f"{len(m.missed_deadlines)} of {m.tasks_total}"
    cols[3].metric(
        "At-risk deadlines",
        late_label,
        delta(len(m.missed_deadlines), len(b.missed_deadlines), "tasks"),
        delta_color="inverse",
        help="Tasks projected to finish after their due date. Total lateness: "
        f"{'at least ' if m.lateness_is_lower_bound else ''}{m.total_lateness_days} business day(s).",
    )
    final_delta = None
    if is_scenario and m.final_completion_date and b.final_completion_date:
        shift = (m.final_completion_date - b.final_completion_date).days
        final_delta = f"{shift:+d} calendar days" if shift else None
    cols[4].metric(
        "Projected completion",
        m.final_completion_date.strftime("%d %b %Y") if m.final_completion_date else "Beyond period",
        final_delta,
        delta_color="inverse",
        help="Day the last task finishes. 'Beyond period' means some work does not fit in the planning period.",
    )
    if m.unscheduled_hours > 0:
        st.warning(
            f"{m.unscheduled_hours:g} h of work ({m.unfinished_tasks} task(s)) cannot be scheduled within the "
            "planning period. It is listed in the schedule table, not dropped."
        )


def resource_section(result: SimulationResult) -> None:
    resources = result.metrics.resources
    if not resources:
        st.info("This workload has no resources.")
        return

    def label(r) -> str:
        return f"{r.name} ({STATUS_LABELS[r.status]})" if r.status != STATUS_OK else r.name

    order = [label(r) for r in resources]
    left, right = st.columns(2)

    with left:
        st.markdown("**Capacity versus workload (hours in the planning period)**")
        long = pd.DataFrame(
            [
                {"Resource": label(r), "Measure": measure, "Hours": hours}
                for r in resources
                for measure, hours in (
                    ("Available capacity", r.capacity_hours),
                    ("Workload demand", r.demand_hours),
                )
            ]
        )
        base = alt.Chart(long).encode(
            y=alt.Y("Resource:N", sort=order, title=None, axis=alt.Axis(labelLimit=220)),
            yOffset=alt.YOffset("Measure:N", sort=["Available capacity", "Workload demand"]),
            x=alt.X("Hours:Q", title="Hours"),
            tooltip=["Resource", "Measure", alt.Tooltip("Hours:Q", format=".1f")],
        )
        bars = base.mark_bar(cornerRadiusEnd=4).encode(
            color=alt.Color(
                "Measure:N",
                scale=alt.Scale(domain=["Available capacity", "Workload demand"], range=SERIES[:2]),
                legend=alt.Legend(orient="top", title=None),
            )
        )
        values = base.mark_text(align="left", dx=4).encode(text=alt.Text("Hours:Q", format=".0f"))
        st.altair_chart((bars + values).properties(height=56 * len(resources) + 40), width="stretch")

    with right:
        st.markdown("**Peak deadline load (% of capacity needed by the tightest deadline)**")
        peak = pd.DataFrame(
            [
                {
                    "Resource": label(r),
                    "Peak load (%)": r.peak_deadline_load_pct or 0.0,
                    "Tightest deadline": r.peak_deadline_date.isoformat() if r.peak_deadline_date else "-",
                    "Status": STATUS_LABELS[r.status],
                }
                for r in resources
            ]
        )
        base = alt.Chart(peak).encode(
            y=alt.Y("Resource:N", sort=order, title=None, axis=alt.Axis(labelLimit=220)),
            x=alt.X(
                "Peak load (%):Q",
                title="Percent of capacity",
                scale=alt.Scale(domain=[0, max(120.0, float(peak["Peak load (%)"].max()) * 1.15)]),
            ),
            tooltip=["Resource", "Peak load (%)", "Tightest deadline", "Status"],
        )
        bars = base.mark_bar(cornerRadiusEnd=4, size=22).encode(
            color=alt.Color(
                "Status:N",
                scale=alt.Scale(
                    domain=[STATUS_LABELS[s] for s in STATUS_COLORS], range=list(STATUS_COLORS.values())
                ),
                legend=alt.Legend(orient="top", title=None),
            )
        )
        values = base.mark_text(align="left", dx=4).encode(text=alt.Text("Peak load (%):Q", format=".0f"))
        limit = (
            alt.Chart(pd.DataFrame({"x": [100]}))
            .mark_rule(strokeDash=[4, 4], color="#52514e")
            .encode(x="x:Q", tooltip=alt.value("100% = all capacity up to the deadline"))
        )
        st.altair_chart((bars + limit + values).properties(height=56 * len(resources) + 40), width="stretch")

    st.caption(
        "Peak deadline load: for each deadline of a resource, the work due by that date divided by the "
        "capacity available up to that date; the highest value is shown. Above 100% the deadlines cannot all "
        "be met even before dependencies are considered."
    )
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Resource": r.name,
                    "Status": STATUS_LABELS[r.status],
                    "Capacity (h)": r.capacity_hours,
                    "Workload demand (h)": r.demand_hours,
                    "Scheduled (h)": r.scheduled_hours,
                    "Utilization": fmt_pct(r.utilization_pct),
                    "Demand ratio": fmt_pct(r.demand_ratio_pct),
                    "Peak deadline load": fmt_pct(r.peak_deadline_load_pct),
                    "Tasks waited (business days)": r.queue_wait_days,
                    "Late tasks traced here": r.late_tasks_caused,
                }
                for r in resources
            ]
        ),
        hide_index=True,
        width="stretch",
    )


def chain_text(result: SimulationResult, task_id: str) -> str:
    """Readable cause chain, e.g. 'T05 <- prerequisite T03 <- Maya busy on T11'."""
    parts = [task_id]
    for link in result.metrics.tasks[task_id].delay_chain:
        if not link.blocker_task_id:
            break
        if link.cause == "resource_busy":
            who = result.workload.resource(link.resource_id).name
            parts.append(f"{who} busy on {link.blocker_task_id}")
        else:
            parts.append(f"prerequisite {link.blocker_task_id}")
    return "  ←  ".join(parts)


def schedule_section(result: SimulationResult) -> None:
    rows = timeline_rows(result)
    if not result.workload.tasks:
        st.info("This workload has no tasks, so there is no schedule to show.")
        return
    if rows:
        df = pd.DataFrame(rows)
        for column in ("First start", "Finish", "Due"):
            df[column + " date"] = [d.isoformat() if d else "not finished" for d in df[column]]
        for column in ("Start", "End", "Due"):
            df[column] = pd.to_datetime(df[column])
        df["Due marker"] = df["Due"] + pd.Timedelta(days=1)  # end of the due day
        df["Label"] = df["Task"] + "  " + df["Description"] + df["Late"].map({True: "  ⚠ late", False: ""})
        df["Deadline"] = df["Late"].map({True: "Missed", False: "Met"})
        order = df.sort_values(["First start", "Task"])["Label"].drop_duplicates().tolist()
        projects = sorted(df["Project"].unique())
        # Show the whole planning period (or further, if a due date lies beyond it).
        period = (
            pd.Timestamp(result.workload.period_start),
            max(pd.Timestamp(result.workload.period_end), df["Due"].max()) + pd.Timedelta(days=1),
        )
        tooltip = [
            "Task",
            "Description",
            "Project",
            "Resource",
            alt.Tooltip("First start date", title="Start"),
            alt.Tooltip("Finish date", title="Finish"),
            alt.Tooltip("Due date", title="Due"),
            "Late (business days)",
        ]
        y = alt.Y("Label:N", sort=order, title=None, axis=alt.Axis(labelLimit=330))
        bars = (
            alt.Chart(df)
            .mark_bar(cornerRadius=4, height=14)
            .encode(
                y=y,
                x=alt.X(
                    "Start:T",
                    title=None,
                    axis=alt.Axis(format="%d %b"),
                    scale=alt.Scale(domain=[period[0].isoformat(), period[1].isoformat()]),
                ),
                x2="End:T",
                color=alt.Color(
                    "Project:N",
                    scale=alt.Scale(domain=projects, range=SERIES[: len(projects)]),
                    legend=alt.Legend(orient="top", title=None),
                ),
                tooltip=tooltip,
            )
        )
        due = (
            alt.Chart(df.drop_duplicates("Task"))
            .mark_tick(thickness=3, size=20)
            .encode(
                y=y,
                x="Due marker:T",
                color=alt.Color(
                    "Deadline:N",
                    scale=alt.Scale(domain=["Met", "Missed"], range=["#52514e", "#d03b3b"]),
                    legend=alt.Legend(orient="top", title="Deadline (end of due day)"),
                ),
                tooltip=tooltip,
            )
        )
        chart = (bars + due).resolve_scale(color="independent").properties(height=26 * len(order) + 30)
        st.altair_chart(chart, width="stretch")
        st.caption(
            "Bars are the days each task is actually worked on in the simulation (gaps are non-working days "
            "or waiting). The vertical tick marks the end of the due day."
        )

    unfinished = [e for e in result.schedule.values() if e.status != "completed"]
    if unfinished:
        st.warning(
            "Not finished within the planning period:\n\n"
            + "\n".join(f"- **{e.task_id}**: {e.unscheduled_reason}" for e in unfinished)
        )

    late = result.metrics.missed_deadlines
    if late:
        st.markdown("**Why the late tasks are late**")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Task": tid,
                        "Late (business days)": (
                            f"{'≥ ' if result.metrics.tasks[tid].lateness_is_lower_bound else ''}"
                            f"{result.metrics.tasks[tid].lateness_days}"
                        ),
                        "Start was fixed by": CAUSE_LABELS[result.schedule[tid].start_cause or "not_started"],
                        "Chain of causes": chain_text(result, tid),
                    }
                    for tid in late
                ]
            ),
            hide_index=True,
            width="stretch",
        )

    with st.expander("Full schedule table"):
        st.dataframe(pd.DataFrame(schedule_rows(result)), hide_index=True, width="stretch")


def scenario_form(workload: Workload) -> sc.Scenario | None:
    """Scenario controls. Returns the scenario to run, or None while it is incomplete."""
    kind = st.selectbox(
        "Scenario", list(SCENARIO_LABELS), format_func=SCENARIO_LABELS.get, key="scenario-kind"
    )
    resources = {r.id: f"{r.name} - {r.role}" for r in workload.resources}
    tasks = {t.id: f"{t.id} - {t.description}" for t in workload.tasks}
    start, end = workload.period_start, workload.period_end
    span = (end - start).days

    def offset(days: int) -> date:
        return start + timedelta(days=min(days, span))

    def pick(options: dict, label: str, preferred: str, key: str) -> str | None:
        if not options:
            st.info("The workload has nothing to choose from for this scenario.")
            return None
        ids = list(options)
        index = ids.index(preferred) if preferred in ids else 0
        return st.selectbox(label, ids, index=index, format_func=options.get, key=key)

    if kind == sc.TYPE_ADD_WORK:
        skills = sorted({s for r in workload.resources for s in r.skills})
        if not skills:
            st.info("No resource has any skill, so additional work cannot be assigned.")
            return None
        c1, c2, c3 = st.columns(3)
        hours = c1.number_input("Additional work (hours)", 1.0, 2000.0, 40.0, step=4.0)
        count = c2.number_input("Split into tasks", 1, 20, 2, help="Tasks follow one another in a chain.")
        skill = c3.selectbox(
            "Required skill", skills, index=skills.index("backend") if "backend" in skills else 0
        )
        c4, c5 = st.columns(2)
        due = c4.date_input("Due date", offset(18), min_value=start)
        priority = c5.number_input("Priority (1 = highest)", MIN_PRIORITY, MAX_PRIORITY, 2)
        package = sc.work_package(
            prefix="X",
            project="Additional work",
            total_hours=float(hours),
            task_count=int(count),
            required_skill=skill,
            due_date=due,
            priority=int(priority),
        )
        return sc.Scenario(
            f"Add {hours:g} h of {skill} work",
            kind,
            f"{count} new task(s), due {due}, priority {priority}.",
            (sc.AddTasks(package),),
        )

    if kind == sc.TYPE_UNAVAILABLE:
        rid = pick(resources, "Resource", "R2", "unavailable-resource")
        c1, c2 = st.columns(2)
        first = c1.date_input("First day away", offset(16), min_value=start, max_value=end)
        last = c2.date_input("Last day away", offset(18), min_value=start, max_value=end)
        if rid is None:
            return None
        name = workload.resource(rid).name
        return sc.Scenario(
            f"{name} unavailable {first:%d %b} to {last:%d %b}",
            kind,
            "",
            (sc.MakeUnavailable(rid, first, last),),
        )

    if kind == sc.TYPE_ADD_CAPACITY:
        rid = pick(resources, "Resource", "R1", "capacity-resource")
        c1, c2, c3 = st.columns(3)
        extra = c1.number_input(
            "Extra hours per working day",
            0.5,
            12.0,
            2.0,
            step=0.5,
            help="Scheduled hours; the resource's focus factor still applies.",
        )
        first = c2.date_input("From", start, min_value=start, max_value=end)
        last = c3.date_input("To", end, min_value=start, max_value=end)
        if rid is None:
            return None
        name = workload.resource(rid).name
        return sc.Scenario(
            f"{name} +{extra:g} h/day", kind, "", (sc.BoostCapacity(rid, float(extra), first, last),)
        )

    if kind == sc.TYPE_DEADLINE:
        tid = pick(tasks, "Task", "T03", "deadline-task")
        if tid is None:
            return None
        current = workload.task(tid).due_date
        due = st.date_input(
            f"New due date (currently {current})", max(start, current - timedelta(days=5)), min_value=start
        )
        return sc.Scenario(f"{tid} due {due:%d %b}", kind, "", (sc.ChangeDeadline(tid, due),))

    if kind == sc.TYPE_PRIORITY:
        tid = pick(tasks, "Task", "T03", "priority-task")
        if tid is None:
            return None
        current = workload.task(tid).priority
        priority = st.number_input(
            f"New priority (1 = highest; currently {current})", MIN_PRIORITY, MAX_PRIORITY, MIN_PRIORITY
        )
        return sc.Scenario(f"{tid} priority {priority}", kind, "", (sc.ChangePriority(tid, int(priority)),))

    tid = pick(tasks, "Task", "T08", "reassign-task")
    if tid is None:
        return None
    task = workload.task(tid)
    eligible = {r.id: resources[r.id] for r in workload.resources if task.required_skill in r.skills}
    st.caption(f"Only resources with the '{task.required_skill}' skill can take this task.")
    rid = pick(eligible, "Assign to", "", f"reassign-resource-{tid}")
    if rid is None:
        return None
    return sc.Scenario(
        f"{tid} assigned to {workload.resource(rid).name}", kind, "", (sc.ReassignTask(tid, rid),)
    )


def whatif_section(baseline: SimulationResult) -> None:
    st.markdown(
        "Pick a change, press **Run simulation**, and compare it with the baseline. The scenario runs on a "
        "copy of the workload through the same engine; the baseline is never modified."
    )
    scenario = scenario_form(baseline.workload)
    if st.button("Run simulation", type="primary", disabled=scenario is None):
        try:
            modified = sc.apply_scenario(baseline.workload, scenario)
            result = engine.run(modified, scenario.name)
            st.session_state.scenario = result
            st.session_state.comparison = compare(baseline, result)
            logger.info("scenario type=%s run_id=%s", scenario.scenario_type, result.run_id)
            st.rerun()
        except WorkloadValidationError as error:
            show_issues("This scenario cannot be simulated:", error)
        except Exception:
            logger.exception("scenario failed type=%s", scenario.scenario_type)
            st.error("The simulation failed unexpectedly. Details are in the application log.")

    result: SimulationResult | None = st.session_state.scenario
    comparison: Comparison | None = st.session_state.comparison
    if result is None or comparison is None:
        st.info("No scenario has been run yet. The baseline is shown in the other tabs.")
        return

    st.divider()
    st.subheader(f"Before / after: Baseline vs '{result.scenario_name}'")
    if not comparison.has_effect:
        st.info("This change has no effect: every metric and completion date equals the baseline.")

    def show(value) -> str:
        if value is None:
            return "Beyond period"
        return value.isoformat() if isinstance(value, date) else f"{value:g}"

    def change(d) -> str:
        if d.delta is None:
            return "-" if d.baseline == d.scenario else "changed"
        return "0" if d.delta == 0 else f"{d.delta:+g} {'pts' if d.unit == '%' else d.unit}"

    verdict_text = {"better": "✅ better", "worse": "🛑 worse", "same": "= same", "changed": "changed"}
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Metric": f"{d.label} ({d.unit})" if d.key != "final" else d.label,
                    "Baseline": show(d.baseline),
                    "Scenario": show(d.scenario),
                    "Change": change(d),
                    "Verdict": verdict_text[d.verdict],
                }
                for d in comparison.deltas
            ]
        ),
        hide_index=True,
        width="stretch",
    )
    names = {r.id: r.name for r in result.workload.resources}
    st.markdown(
        f"**Bottleneck:** {names.get(comparison.bottleneck_before, 'none')} → "
        f"{names.get(comparison.bottleneck_after, 'none')}"
    )

    left, right = st.columns(2)
    with left:
        st.markdown("**Scheduling impact (tasks whose outcome changes)**")
        if comparison.task_changes:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Task": c.task_id,
                            "Finish before": show(c.baseline_finish),
                            "Finish after": show(c.scenario_finish),
                            "Shift (business days)": "-" if c.shift_days is None else f"{c.shift_days:+d}",
                            "Deadline": (
                                "newly missed"
                                if c.scenario_late and not c.baseline_late
                                else "now met"
                                if c.baseline_late and not c.scenario_late
                                else "still missed"
                                if c.scenario_late
                                else "met"
                            ),
                        }
                        for c in comparison.task_changes
                    ]
                ),
                hide_index=True,
                width="stretch",
            )
        else:
            st.caption("No existing task finishes on a different day.")
        if comparison.added_tasks:
            st.caption("Tasks added by the scenario: " + ", ".join(comparison.added_tasks))
    with right:
        st.markdown("**Resources**")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Resource": c.name,
                        "Capacity (h)": f"{c.baseline_capacity_hours:g} → {c.scenario_capacity_hours:g}",
                        "Utilization": f"{fmt_pct(c.baseline_utilization_pct)} → {fmt_pct(c.scenario_utilization_pct)}",
                        "Status": f"{STATUS_LABELS[c.baseline_status]} → {STATUS_LABELS[c.scenario_status]}",
                    }
                    for c in comparison.resource_changes
                ]
            ),
            hide_index=True,
            width="stretch",
        )

    st.markdown("**What this means**")
    show_recommendations(recommend_for_comparison(baseline, result, comparison))


def show_recommendations(recommendations: list[Recommendation]) -> None:
    if not recommendations:
        st.caption("Nothing to report.")
    for rec in recommendations:
        st.markdown(f"{SEVERITY_ICONS[rec.severity]} {rec.text}")


def recommendations_section(baseline: SimulationResult) -> list[Recommendation]:
    scenario: SimulationResult | None = st.session_state.scenario
    comparison: Comparison | None = st.session_state.comparison
    findings = recommend_for_result(baseline)

    st.markdown("**Baseline plan**")
    show_recommendations(findings)
    if scenario is not None and comparison is not None:
        st.markdown(f"**Scenario '{scenario.scenario_name}' compared with the baseline**")
        scenario_findings = recommend_for_comparison(baseline, scenario, comparison)
        show_recommendations(scenario_findings)
        findings = findings + scenario_findings

    st.divider()
    st.markdown("**Plain-language summary**")
    try:
        explanation = get_provider().explain(build_evidence(baseline, scenario, comparison))
        st.caption(explanation.label)
        st.write(explanation.text)
    except Exception:
        logger.exception("explanation provider failed")
        st.warning("The explanation could not be generated. The figures above are unaffected.")

    st.warning(
        "**Assumptions to keep in mind.** " + DISCLAIMER + " Effort estimates are taken as given, each "
        "person works on one task at a time, started tasks are not interrupted or handed over, and only the "
        "listed skills decide who can do what. Do not use this tool for performance, disciplinary or "
        "employment decisions."
    )
    return findings


def data_section(baseline: SimulationResult, findings: list[Recommendation]) -> None:
    workload = baseline.workload
    scenario: SimulationResult | None = st.session_state.scenario
    comparison: Comparison | None = st.session_state.comparison

    st.markdown("**Resources**")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "ID": r.id,
                    "Name": r.name,
                    "Role": r.role,
                    "Skills": ", ".join(r.skills),
                    "Hours/day": r.hours_per_day,
                    "Working days": " ".join(WEEKDAY_NAMES[d] for d in r.working_days),
                    "Focus factor": r.focus_factor,
                    "Unavailable": "; ".join(f"{p.start} to {p.end}" for p in r.unavailable),
                }
                for r in workload.resources
            ]
        ),
        hide_index=True,
        width="stretch",
    )
    st.markdown("**Tasks**")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "ID": t.id,
                    "Description": t.description,
                    "Project": t.project,
                    "Effort (h)": t.effort_hours,
                    "Priority": t.priority,
                    "Due": t.due_date.isoformat(),
                    "Skill": t.required_skill,
                    "Depends on": ", ".join(t.dependencies),
                    "Assigned to": t.assigned_resource or "any eligible",
                }
                for t in workload.tasks
            ]
        ),
        hide_index=True,
        width="stretch",
    )

    st.markdown("**Export**")
    shown = scenario or baseline
    c1, c2 = st.columns(2)
    c1.download_button(
        f"Schedule as CSV ({shown.scenario_name})",
        schedule_csv(shown),
        file_name="capacitytwin_schedule.csv",
        mime="text/csv",
    )
    c2.download_button(
        "Full report as JSON",
        report_json(baseline, findings, scenario, comparison),
        file_name="capacitytwin_report.json",
        mime="application/json",
    )

    st.markdown("**Simulation runs**")
    runs = [baseline] + ([scenario] if scenario else [])
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Plan": r.scenario_name,
                    "Run ID": r.run_id,
                    "Status": "completed",
                    "Engine time (ms)": r.duration_ms,
                }
                for r in runs
            ]
        ),
        hide_index=True,
        width="stretch",
    )
    st.caption("The run ID is a hash of the simulated input: the same input always gives the same ID.")


# --------------------------------------------------------------------------- page


def main() -> None:
    st.set_page_config(page_title="CapacityTwin AI", page_icon="📊", layout="wide")
    configure_logging()

    if "baseline" not in st.session_state:
        try:
            set_workload(st.session_state.get("workload") or load_default_workload())
        except (WorkloadValidationError, OSError) as error:
            logger.exception("initial workload could not be loaded")
            st.error(f"The workload could not be loaded: {error}")
            st.stop()

    sidebar()
    baseline: SimulationResult = st.session_state.baseline
    scenario: SimulationResult | None = st.session_state.scenario

    # Everything above the tabs lives in one container so that showing or hiding the
    # plan selector never shifts the tabs (which would reset the selected tab).
    with st.container():
        st.title("CapacityTwin AI")
        st.caption(
            "A lightweight what-if simulator for team capacity: can the work be done on time, who is "
            "overloaded, and what changes if plans change?"
        )
        if baseline.workload.notice:
            st.info(baseline.workload.notice)

        shown = baseline
        if scenario is not None:
            choice = st.radio(
                "Plan shown in the overview, resource and schedule views",
                ["Baseline", f"Scenario: {scenario.scenario_name}"],
                horizontal=True,
            )
            if choice != "Baseline":
                shown = scenario

        st.subheader(
            "Workload overview" + ("" if shown is baseline else " (change vs baseline shown below values)")
        )
        overview(shown, baseline)

    tabs = st.tabs(
        ["Resource capacity", "Work schedule", "What-if simulator", "Recommendations", "Data and export"]
    )
    with tabs[0]:
        resource_section(shown)
    with tabs[1]:
        schedule_section(shown)
    with tabs[2]:
        whatif_section(baseline)
    with tabs[3]:
        findings = recommendations_section(baseline)
    with tabs[4]:
        data_section(baseline, findings)


main()
