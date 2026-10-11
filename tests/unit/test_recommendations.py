"""Recommendations must be grounded: every number and ID they quote comes from the engine."""

import re

from app.analytics.comparison import compare
from app.analytics.recommendations import (
    CRITICAL,
    INFO,
    POSITIVE,
    recommend_for_comparison,
    recommend_for_result,
)
from app.scenarios import manager as sc
from tests.conftest import day, make_resource, make_task, make_workload, run


def texts(recs) -> str:
    return "\n".join(r.text for r in recs)


def test_baseline_findings_quote_engine_values(baseline):
    text = texts(recommend_for_result(baseline))
    maya = baseline.metrics.resource("R3")
    assert f"needs {maya.peak_deadline_load_pct:g}% of the capacity" in text
    assert f"{maya.late_tasks_caused} late task(s) trace back" in text
    for task_id in baseline.metrics.missed_deadlines:
        finish = baseline.schedule[task_id].finish_date
        assert f"Task {task_id} " in text and f"finishes {finish}" in text


def test_findings_never_mention_tasks_or_people_outside_the_workload(baseline):
    text = texts(recommend_for_result(baseline))
    known_tasks = {t.id for t in baseline.workload.tasks}
    assert set(re.findall(r"\bT\d\d\b", text)) <= known_tasks
    on_time = known_tasks - set(baseline.metrics.missed_deadlines)
    assert not any(f"Task {tid} " in text for tid in on_time)


def test_no_alternative_skill_is_only_claimed_when_true(baseline):
    assert "No other resource has the 'design' skill" in texts(recommend_for_result(baseline))
    with_second_designer = baseline.workload.copy()
    with_second_designer.resource("R4").skills += ("design",)
    result = run(with_second_designer)
    assert "No other resource has the 'design' skill" not in texts(recommend_for_result(result))


def test_healthy_plan_gets_a_positive_finding_only():
    recs = recommend_for_result(run(make_workload([make_resource()], [make_task("T1")])))
    assert [r.severity for r in recs] == [POSITIVE]
    assert "All 1 tasks" in recs[0].text


def test_unschedulable_work_is_flagged_as_critical():
    recs = recommend_for_result(run(make_workload([make_resource()], [make_task("T1", effort=100)])))
    assert recs[0].severity == CRITICAL and "20 h of work" in recs[0].text


def test_empty_workload_finding():
    recs = recommend_for_result(run(make_workload([make_resource()], [])))
    assert "no tasks" in texts(recs)


def compare_with(baseline, modification, name="what-if"):
    scenario = run(sc.apply_scenario(baseline.workload, sc.Scenario(name, "x", "", (modification,))), name)
    comparison = compare(baseline, scenario)
    return comparison, recommend_for_comparison(baseline, scenario, comparison)


def test_unhelpful_capacity_is_called_out_as_not_improving(baseline):
    comparison, recs = compare_with(baseline, sc.BoostCapacity("R1", 2, day(2), day(27)))
    text = texts(recs)
    assert "does not change deadline outcomes" in text
    assert (
        f"Adding {comparison.delta('capacity').delta:g} h of capacity does not improve any deadline" in text
    )
    assert "still Maya Stern" in text
    assert POSITIVE not in [r.severity for r in recs]


def test_helpful_capacity_is_reported_with_before_and_after_numbers(baseline):
    comparison, recs = compare_with(baseline, sc.BoostCapacity("R3", 2, day(2), day(27)))
    text = texts(recs)
    assert "missed deadlines go from 3 to 0" in text
    assert "5 business days to 0 business days" in text
    assert "resolves 3 deadline violation(s): T03, T11, T12" in text
    assert recs[0].severity == POSITIVE


def test_new_violations_are_listed_exactly(baseline):
    comparison, recs = compare_with(baseline, sc.MakeUnavailable("R2", day(18), day(20)))
    assert f"creates {len(comparison.new_missed)} new deadline violation(s): " + ", ".join(
        comparison.new_missed
    ) in texts(recs)
    assert recs[0].severity == CRITICAL


def test_no_effect_scenario_says_so(baseline):
    comparison, recs = compare_with(baseline, sc.ChangePriority("T11", 1))
    assert not comparison.has_effect
    assert [r.severity for r in recs] == [INFO] and "has no effect" in recs[0].text
