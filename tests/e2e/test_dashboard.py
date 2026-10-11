"""End-to-end dashboard workflows, driven headlessly with Streamlit's AppTest."""

import json
from datetime import date

import pytest
from streamlit.testing.v1 import AppTest

from app.services.loader import DEFAULT_DATASET, parse_workload_file

APP = "app/streamlit_app.py"


@pytest.fixture
def app() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    return at


def metrics(at: AppTest) -> dict[str, str]:
    return {m.label: m.value for m in at.metric}


def button(at: AppTest, label: str):
    return next(b for b in at.button if b.label == label)


def page_text(at: AppTest) -> str:
    return "\n".join(str(e.value) for e in [*at.markdown, *at.info, *at.warning, *at.caption])


def comparison_table(at: AppTest):
    return next(d.value for d in at.dataframe if "Verdict" in d.value.columns).set_index("Metric")


def run_scenario(at: AppTest, kind: str, **selections) -> AppTest:
    at.selectbox(key="scenario-kind").select(kind).run()
    for key, value in selections.items():
        at.selectbox(key=key).select(value).run()
    button(at, "Run simulation").click().run()
    assert not at.exception and not at.error
    return at


def test_dashboard_opens_with_the_synthetic_baseline(app):
    assert metrics(app) == {
        "Available capacity": "571.2 h",
        "Estimated workload": "242 h",
        "Capacity utilization": "42.4%",
        "At-risk deadlines": "3 of 18",
        "Projected completion": "27 Nov 2026",
    }
    text = page_text(app)
    assert "Synthetic demonstration data - not real employee or client information." in text
    assert "Maya Stern is the main bottleneck" in text
    assert "No scenario has been run yet" in text
    assert "mock mode" in text and "not a prediction" in text


def test_full_workflow_baseline_to_before_after_comparison(app):
    # 1. Overtime for the developer: more capacity, no better outcome.
    run_scenario(app, "additional_capacity")
    table = comparison_table(app)
    assert table.loc["Available capacity (h)", "Change"] == "+40 h"
    assert table.loc["Missed deadlines (tasks)", ["Baseline", "Scenario", "Verdict"]].tolist() == [
        "3",
        "3",
        "= same",
    ]
    assert "does not improve any deadline" in page_text(app)

    # 2. The same hours for the bottleneck designer: all deadlines met.
    run_scenario(app, "additional_capacity", **{"capacity-resource": "R3"})
    table = comparison_table(app)
    assert table.loc["Missed deadlines (tasks)", ["Baseline", "Scenario"]].tolist() == ["3", "0"]
    assert table.loc["Total lateness (business days)", "Change"] == "-5 business days"
    assert table.loc["Final completion date", ["Baseline", "Scenario"]].tolist() == [
        "2026-11-27",
        "2026-11-25",
    ]
    assert "resolves 3 deadline violation(s): T03, T11, T12" in page_text(app)

    # 3. The overview can switch to the scenario and shows the change against the baseline.
    app.radio[0].set_value("Scenario: Maya Stern +2 h/day").run()
    assert metrics(app)["At-risk deadlines"] == "0 of 18"
    assert metrics(app)["Projected completion"] == "25 Nov 2026"
    assert next(m for m in app.metric if m.label == "At-risk deadlines").delta == "-3 tasks"


@pytest.mark.parametrize(
    ("kind", "missed_after", "phrase"),
    [
        ("additional_work", "6", "creates 3 new deadline violation(s): T15, T17, X02"),
        ("resource_unavailability", "9", "makes delivery worse"),
        ("priority_change", "4", "is a trade-off"),
        ("deadline_change", "5", "makes delivery worse"),
        ("task_reassignment", "3", "has no effect"),
    ],
)
def test_each_scenario_type_runs_through_the_ui(app, kind, missed_after, phrase):
    run_scenario(app, kind)
    assert comparison_table(app).loc["Missed deadlines (tasks)", "Scenario"] == missed_after
    assert phrase in page_text(app)


def test_invalid_scenario_shows_a_controlled_error(app):
    app.selectbox(key="scenario-kind").select("resource_unavailability").run()
    app.date_input[1].set_value(date(2026, 11, 3)).run()  # last day away before the first
    button(app, "Run simulation").click().run()
    assert not app.exception
    assert "This scenario cannot be simulated" in app.error[0].value
    assert "is before start date" in app.error[0].value


def test_restore_default_dataset_clears_the_scenario(app):
    run_scenario(app, "additional_capacity")
    assert app.radio
    button(app, "Restore default dataset").click().run()
    assert not app.radio
    assert metrics(app)["At-risk deadlines"] == "3 of 18"
    assert "No scenario has been run yet" in page_text(app)


def test_dashboard_handles_empty_and_unschedulable_workloads():
    raw = json.loads(DEFAULT_DATASET.read_text(encoding="utf-8"))

    empty = dict(raw, tasks=[])
    at = AppTest.from_file(APP, default_timeout=30)
    at.session_state["workload"] = parse_workload_file("w.json", json.dumps(empty).encode())
    at.run()
    assert not at.exception
    assert metrics(at)["At-risk deadlines"] == "0 of 0"
    assert "no tasks" in page_text(at)

    for resource in raw["resources"]:
        resource["hours_per_day"] = 0
    at = AppTest.from_file(APP, default_timeout=30)
    at.session_state["workload"] = parse_workload_file("w.json", json.dumps(raw).encode())
    at.run()
    assert not at.exception
    assert metrics(at)["Capacity utilization"] == "n/a"
    assert metrics(at)["Projected completion"] == "Beyond period"
    assert "242 h of work (18 task(s)) cannot be scheduled" in page_text(at)
