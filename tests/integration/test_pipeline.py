"""Dataset -> validation -> engine -> metrics -> comparison -> explanation -> export.

Expected figures for the synthetic dataset are pinned so any change to the
scheduling policy or the data shows up as a failing test.
"""

import json
import logging

import pytest

from app.ai.mock_provider import CAVEAT, MockExplanationProvider
from app.ai.provider import build_evidence, get_provider
from app.analytics.comparison import compare
from app.analytics.recommendations import recommend_for_comparison, recommend_for_result
from app.domain.validation import WorkloadValidationError
from app.scenarios import manager as sc
from app.services.loader import parse_workload_file, workload_to_dict
from app.services.reporting import report_json
from tests.conftest import day, run

PERIOD = (day(2), day(4, month=12))


def scenario_run(baseline, kind, name, *modifications):
    result = run(sc.apply_scenario(baseline.workload, sc.Scenario(name, kind, "", modifications)), name)
    return result, compare(baseline, result)


def test_baseline_of_the_synthetic_dataset(baseline):
    m = baseline.metrics
    # 3 full-time people: 25 days * 6.4 h; designer: 19 days * 4.8 h.
    assert m.capacity_hours == 3 * 160 + 91.2 == 571.2
    assert m.workload_hours == sum(t.effort_hours for t in baseline.workload.tasks) == 242
    assert m.utilization_pct == 42.4 and m.demand_ratio_pct == 42.4
    assert m.missed_deadlines == ("T03", "T11", "T12")
    assert m.total_lateness_days == 5 and not m.lateness_is_lower_bound
    assert m.final_completion_date == day(27)
    assert m.unscheduled_hours == 0
    assert m.bottleneck_resource_id == "R3"
    maya = m.resource("R3")
    assert (maya.capacity_hours, maya.demand_hours, maya.status) == (91.2, 54.0, "overloaded")
    assert maya.peak_deadline_load_pct == 106.5 and maya.peak_deadline_date == day(17)
    assert [r.status for r in m.resources if r.resource_id != "R3"] == ["ok", "ok", "ok"]


def test_scenario_b_additional_work_creates_new_violations(baseline):
    package = sc.work_package(
        prefix="X",
        project="Additional work",
        total_hours=40,
        task_count=2,
        required_skill="backend",
        due_date=day(20),
        priority=2,
    )
    result, comparison = scenario_run(baseline, sc.TYPE_ADD_WORK, "Add 40 h", sc.AddTasks(package))
    assert result.metrics.workload_hours == 282
    assert result.metrics.utilization_pct == 49.4
    assert comparison.new_missed == ("T15", "T17", "X02")
    assert comparison.delta("missed").delta == 3
    assert comparison.delta("lateness").delta == 6
    assert result.metrics.final_completion_date == day(1, month=12)
    assert comparison.bottleneck_after == "R1"


def test_scenario_c_unavailability_ripples_through_dependencies(baseline):
    result, comparison = scenario_run(
        baseline, sc.TYPE_UNAVAILABLE, "Eli away", sc.MakeUnavailable("R2", day(18), day(20))
    )
    assert comparison.delta("capacity").delta == -19.2  # 3 days * 6.4 h
    assert comparison.new_missed == ("T05", "T07", "T08", "T09", "T14", "T16")
    assert result.metrics.total_lateness_days == 17
    # Work that is not Eli's slips too, because it depends on his.
    assert {c.task_id for c in comparison.task_changes} >= {"T07", "T08", "T09"}


def test_scenario_d_capacity_for_the_wrong_person_does_not_help(baseline):
    result, comparison = scenario_run(
        baseline, sc.TYPE_ADD_CAPACITY, "Dana +2 h/day", sc.BoostCapacity("R1", 2, *PERIOD)
    )
    assert comparison.delta("capacity").delta == 40.0  # 25 days * 2 h * 0.8
    assert comparison.delta("missed").delta == 0 and comparison.delta("lateness").delta == 0
    assert result.metrics.missed_deadlines == baseline.metrics.missed_deadlines
    assert result.metrics.bottleneck_resource_id == "R3"


def test_scenario_d_capacity_for_the_bottleneck_resolves_all_violations(baseline):
    result, comparison = scenario_run(
        baseline, sc.TYPE_ADD_CAPACITY, "Maya +2 h/day", sc.BoostCapacity("R3", 2, *PERIOD)
    )
    assert comparison.delta("capacity").delta == 30.4  # 19 days * 2 h * 0.8
    assert result.metrics.missed_deadlines == ()
    assert comparison.resolved_missed == ("T03", "T11", "T12")
    assert result.metrics.final_completion_date == day(25)
    assert comparison.delta("final").delta == -2


def test_scenario_e_priority_change_is_a_trade_off(baseline):
    result, comparison = scenario_run(baseline, sc.TYPE_PRIORITY, "T03 first", sc.ChangePriority("T03", 1))
    assert comparison.resolved_missed == ("T03",)
    assert comparison.new_missed == ("T14", "T18")
    assert result.metrics.total_lateness_days == 8
    assert result.metrics.final_completion_date == day(30)


def test_scenario_e_deadline_change(baseline):
    result, comparison = scenario_run(
        baseline, sc.TYPE_DEADLINE, "T03 earlier", sc.ChangeDeadline("T03", day(12))
    )
    assert result.metrics.missed_deadlines == ("T03", "T11", "T12", "T14", "T18")
    assert result.metrics.total_lateness_days == 10


def test_scenarios_do_not_leak_into_the_baseline(baseline, default_workload):
    before = json.dumps(workload_to_dict(baseline.workload))
    for modification in (
        sc.MakeUnavailable("R3", day(4), day(5)),
        sc.BoostCapacity("R3", 2, *PERIOD),
        sc.ChangePriority("T12", 1),
    ):
        scenario_run(baseline, "x", "x", modification)
    assert json.dumps(workload_to_dict(baseline.workload)) == before
    assert run(default_workload).metrics == baseline.metrics


def test_results_are_reproducible_run_to_run(default_workload):
    first, second = run(default_workload), run(default_workload.copy())
    assert first.run_id == second.run_id
    assert first.schedule == second.schedule and first.metrics == second.metrics


def test_exported_dataset_can_be_reloaded_with_identical_results(baseline):
    exported = json.dumps(workload_to_dict(baseline.workload)).encode()
    assert run(parse_workload_file("export.json", exported)).metrics == baseline.metrics


def test_mock_explanation_is_deterministic_and_evidence_based(baseline):
    result, comparison = scenario_run(
        baseline, sc.TYPE_ADD_CAPACITY, "Maya +2 h/day", sc.BoostCapacity("R3", 2, *PERIOD)
    )
    provider = get_provider()
    assert isinstance(provider, MockExplanationProvider)
    first = provider.explain(build_evidence(baseline, result, comparison))
    assert first == provider.explain(build_evidence(baseline, result, comparison))
    assert first.mode == "mock" and "no AI model" in first.label
    assert "571.2 h of productive capacity for 242 h" in first.text
    assert "3 task(s) miss their deadline (T03, T11, T12), 5 business day(s) late" in first.text
    assert "No task misses its deadline." in first.text
    assert "missed deadlines go from 3 to 0" in first.text
    assert first.text.endswith(CAVEAT)


def test_unknown_ai_mode_falls_back_to_mock_and_logs(monkeypatch, caplog):
    monkeypatch.setenv("CAPACITYTWIN_AI_MODE", "some-llm")
    logging.getLogger("capacitytwin").propagate = True
    with caplog.at_level(logging.WARNING, logger="capacitytwin.ai"):
        provider = get_provider()
    assert isinstance(provider, MockExplanationProvider)
    assert "falling back to mock" in caplog.text


def test_full_report_export_contains_baseline_scenario_and_comparison(baseline):
    result, comparison = scenario_run(
        baseline, sc.TYPE_UNAVAILABLE, "Eli away", sc.MakeUnavailable("R2", day(18), day(20))
    )
    findings = recommend_for_result(baseline) + recommend_for_comparison(baseline, result, comparison)
    report = json.loads(report_json(baseline, findings, result, comparison))
    assert report["scenario"]["missed_deadlines"] == list(result.metrics.missed_deadlines)
    assert report["comparison"]["new_missed_deadlines"] == list(comparison.new_missed)
    deltas = {d["key"]: d for d in report["comparison"]["deltas"]}
    assert deltas["lateness"]["delta"] == 12 and deltas["lateness"]["verdict"] == "worse"
    assert len(report["recommendations"]) == len(findings)


def test_simulation_logs_run_id_scenario_and_duration(default_workload, caplog):
    logging.getLogger("capacitytwin").propagate = True
    with caplog.at_level(logging.INFO, logger="capacitytwin.simulation"):
        result = run(default_workload, "Baseline")
    assert f"run_id={result.run_id}" in caplog.text
    assert "scenario='Baseline'" in caplog.text and "duration_ms=" in caplog.text


def test_validation_failure_is_logged_and_raised(default_workload, caplog):
    logging.getLogger("capacitytwin").propagate = True
    default_workload.task("T01").effort_hours = -1
    with caplog.at_level(logging.WARNING, logger="capacitytwin.simulation"):
        with pytest.raises(WorkloadValidationError):
            run(default_workload)
    assert "validation failed" in caplog.text
