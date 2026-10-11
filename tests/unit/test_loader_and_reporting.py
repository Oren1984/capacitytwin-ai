import csv
import io
import json

import pytest

from app.analytics.recommendations import recommend_for_result
from app.domain.validation import WorkloadValidationError
from app.services.loader import (
    DEFAULT_DATASET,
    MAX_FILE_BYTES,
    parse_workload_file,
    workload_from_dict,
    workload_to_dict,
)
from app.services.reporting import report_json, sanitize_cell, schedule_csv, schedule_rows, timeline_rows
from tests.conftest import make_resource, make_task, make_workload, run


def default_dict() -> dict:
    return json.loads(DEFAULT_DATASET.read_text(encoding="utf-8"))


def issues(raw) -> str:
    with pytest.raises(WorkloadValidationError) as error:
        workload_from_dict(raw)
    return " | ".join(error.value.issues)


def test_default_dataset_loads_and_is_labelled_synthetic(default_workload):
    assert len(default_workload.resources) == 4 and len(default_workload.tasks) == 18
    assert (
        default_workload.notice == "Synthetic demonstration data - not real employee or client information."
    )


def test_round_trip_preserves_the_workload(default_workload):
    assert workload_from_dict(workload_to_dict(default_workload)) == default_workload


@pytest.mark.parametrize("name", ["plan.csv", "plan.xlsx", "plan.pkl", "plan.json.exe", "plan"])
def test_unsupported_file_formats_are_rejected(name):
    with pytest.raises(WorkloadValidationError, match="Unsupported file format"):
        parse_workload_file(name, b"{}")


def test_oversized_file_is_rejected():
    with pytest.raises(WorkloadValidationError, match="larger than"):
        parse_workload_file("plan.json", b" " * (MAX_FILE_BYTES + 1))


@pytest.mark.parametrize(
    "content", [b"not json", b"\xff\xfe\x00", b"[" * 100_000], ids=["text", "bad-utf8", "deep-nesting"]
)
def test_malformed_content_is_rejected_without_crashing(content):
    with pytest.raises(WorkloadValidationError, match="not valid UTF-8 JSON"):
        parse_workload_file("plan.json", content)


@pytest.mark.parametrize("raw", [[], "text", 5, None])
def test_non_object_top_level_is_rejected(raw):
    assert "expected an object" in issues(raw)


def test_missing_and_unknown_fields_are_reported():
    raw = default_dict()
    del raw["tasks"][0]["effort_hours"]
    raw["tasks"][1]["__class__"] = "os.system"
    raw["resources"][0]["salary"] = 1
    text = issues(raw)
    assert "tasks[0]: missing field(s) effort_hours" in text
    assert "tasks[1]: unknown field(s) __class__" in text
    assert "resources[0]: unknown field(s) salary" in text


def test_wrong_types_and_bad_dates_are_reported():
    raw = default_dict()
    raw["tasks"][0]["effort_hours"] = "8"
    raw["tasks"][0]["due_date"] = "03/11/2026"
    raw["tasks"][1]["priority"] = 1.5
    raw["resources"][0]["skills"] = "backend"
    raw["period_end"] = 20261204
    text = issues(raw)
    assert "tasks[0].effort_hours: expected a number" in text
    assert "tasks[0].due_date: expected a date formatted YYYY-MM-DD" in text
    assert "tasks[1].priority: expected a whole number" in text
    assert "resources[0].skills: expected a list" in text
    assert "period_end: expected a date" in text


def test_semantic_problems_in_a_file_are_reported():
    raw = default_dict()
    raw["tasks"][0]["dependencies"] = ["T09"]  # T01 -> T09 -> ... -> T01
    raw["tasks"][1]["effort_hours"] = -4
    text = issues(raw)
    assert "Cyclic dependency" in text and "effort must be a positive number" in text


@pytest.mark.parametrize("payload", ["=1+1", "+cmd", "-2+3", "@SUM(A1)", "\tx", "\rx"])
def test_formula_like_cells_are_neutralised(payload):
    assert sanitize_cell(payload) == "'" + payload


def test_ordinary_cells_are_untouched():
    assert sanitize_cell("Portal design") == "Portal design"
    assert sanitize_cell(-3.5) == -3.5


def test_csv_export_escapes_formula_injection_from_task_descriptions():
    task = make_task("T1")
    task.description = '=HYPERLINK("http://evil.example","x")'
    result = run(make_workload([make_resource()], [task]))
    rows = list(csv.DictReader(io.StringIO(schedule_csv(result))))
    assert rows[0]["Description"].startswith("'=HYPERLINK")


def test_csv_export_matches_the_schedule(baseline):
    rows = list(csv.DictReader(io.StringIO(schedule_csv(baseline))))
    assert len(rows) == 18
    by_task = {row["Task"]: row for row in rows}
    assert by_task["T03"]["Finish"] == baseline.schedule["T03"].finish_date.isoformat()
    assert by_task["T03"]["Late (business days)"] == "2"


def test_csv_export_of_an_empty_workload_is_empty():
    assert schedule_csv(run(make_workload([make_resource()], []))) == ""


def test_json_report_is_valid_json_and_carries_the_engine_numbers(baseline):
    report = json.loads(report_json(baseline, recommend_for_result(baseline)))
    assert report["baseline"]["capacity_hours"] == baseline.metrics.capacity_hours
    assert report["baseline"]["missed_deadlines"] == ["T03", "T11", "T12"]
    assert report["baseline"]["run_id"] == baseline.run_id
    assert "not a prediction" in report["disclaimer"]
    assert "Synthetic demonstration data" in report["data_notice"]
    assert len(report["baseline"]["schedule"]) == 18


def test_timeline_bars_cover_exactly_the_worked_days(baseline):
    rows = [r for r in timeline_rows(baseline) if r["Task"] == "T02"]
    # Maya works Mon-Thu: T02 runs Tue 3 - Thu 5 Nov, pauses, and ends Mon 9 Nov.
    assert [(r["Start"].day, r["End"].day) for r in rows] == [(3, 6), (9, 10)]
    worked = sum(len({s.day for s in e.segments}) for e in baseline.schedule.values())
    assert sum((r["End"] - r["Start"]).days for r in timeline_rows(baseline)) == worked


def test_schedule_rows_include_unscheduled_work():
    result = run(make_workload([make_resource(hours=0)], [make_task("T1")]))
    row = schedule_rows(result)[0]
    assert row["Status"] == "unscheduled" and "capacity" in row["Note"]
