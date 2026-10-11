import pytest

from app.domain.models import CapacityBoost, DateRange
from app.domain.validation import WorkloadValidationError, find_cycle, validate_workload
from tests.conftest import day, make_resource, make_task, make_workload, run


def issues_for(tasks, resources=None, **kwargs) -> str:
    return " | ".join(validate_workload(make_workload(resources or [make_resource()], tasks, **kwargs)))


def test_valid_workload_has_no_issues():
    assert validate_workload(make_workload([make_resource()], [make_task("T1")])) == []


@pytest.mark.parametrize("effort", [-1, 0, float("nan"), float("inf"), "8"])
def test_rejects_non_positive_or_non_numeric_effort(effort):
    assert "effort must be a positive number" in issues_for([make_task("T1", effort=effort)])


def test_rejects_excessively_large_effort():
    assert "exceeds the 10000-hour limit" in issues_for([make_task("T1", effort=10_001)])


def test_rejects_unknown_assigned_resource():
    assert "unknown resource 'ZZ'" in issues_for([make_task("T1", assigned_resource="ZZ")])


def test_rejects_task_nobody_is_skilled_for():
    assert "no resource has required skill 'legal'" in issues_for([make_task("T1", skill="legal")])


def test_rejects_assignment_to_resource_without_the_skill():
    assert "lacks required skill" in issues_for([make_task("T1", skill="design", assigned_resource="A")])


def test_rejects_unknown_dependency():
    assert "depends on unknown task 'T9'" in issues_for([make_task("T1", deps=["T9"])])


def test_rejects_self_dependency():
    assert "depends on itself" in issues_for([make_task("T1", deps=["T1"])])


def test_rejects_cyclic_dependencies_and_names_the_cycle():
    tasks = [make_task("T1", deps=["T3"]), make_task("T2", deps=["T1"]), make_task("T3", deps=["T2"])]
    assert "Cyclic dependency: T1 -> T3 -> T2 -> T1" in issues_for(tasks)


def test_find_cycle_returns_none_for_a_dag():
    assert find_cycle({"a": (), "b": ("a",), "c": ("a", "b")}) is None


def test_rejects_duplicate_ids():
    text = issues_for([make_task("T1"), make_task("T1")], [make_resource("A"), make_resource("A")])
    assert "duplicate task ID" in text and "duplicate resource ID" in text


def test_rejects_impossible_dates():
    assert "end date is before start date" in issues_for([], start=day(13), end=day(2))
    assert "before the planning period" in issues_for([make_task("T1", due=day(1))])
    assert "release date is after its due date" in issues_for(
        [make_task("T1", due=day(5), release_date=day(6))]
    )
    res = make_resource(unavailable=[DateRange(day(5), day(4))])
    assert "end date 2026-11-04 is before start date" in issues_for([], [res])


@pytest.mark.parametrize("priority", [0, 6, 2.5, True])
def test_rejects_invalid_priority(priority):
    assert "priority must be an integer 1-5" in issues_for([make_task("T1", priority=priority)])


def test_rejects_invalid_resource_settings():
    text = issues_for(
        [],
        [
            make_resource("A", hours=-1),
            make_resource("B", focus=0),
            make_resource("C", working_days=(7,)),
            make_resource("D", hours=20, capacity_boosts=[CapacityBoost(DateRange(day(2), day(3)), 8)]),
        ],
    )
    assert "hours per day must be between 0 and 24" in text
    assert "focus factor" in text
    assert "weekday numbers" in text
    assert "boosted hours exceed 24" in text


def test_engine_refuses_invalid_workload_with_all_issues():
    workload = make_workload([make_resource()], [make_task("T1", effort=-2, deps=["T1"])])
    with pytest.raises(WorkloadValidationError) as error:
        run(workload)
    assert len(error.value.issues) == 2
