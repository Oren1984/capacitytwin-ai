import pytest

from app.analytics.comparison import compare
from app.domain.validation import WorkloadValidationError
from app.scenarios import manager as sc
from app.services.loader import workload_to_dict
from tests.conftest import day, make_resource, make_task, make_workload, run


def scenario(*modifications, kind=sc.TYPE_ADD_WORK) -> sc.Scenario:
    return sc.Scenario("test scenario", kind, "", tuple(modifications))


def small_workload():
    resources = [make_resource("A"), make_resource("B", skills=("qa",))]
    tasks = [make_task("T1", effort=16, due=day(4)), make_task("T2", effort=8, deps=["T1"], due=day(5))]
    return make_workload(resources, tasks)


def test_applying_a_scenario_never_mutates_the_baseline(default_workload):
    before = workload_to_dict(default_workload)
    modified = sc.apply_scenario(
        default_workload,
        scenario(
            sc.AddTasks(
                sc.work_package(
                    prefix="X",
                    project="Extra",
                    total_hours=40,
                    task_count=2,
                    required_skill="backend",
                    due_date=day(20),
                    priority=2,
                )
            ),
            sc.MakeUnavailable("R2", day(18), day(20)),
            sc.BoostCapacity("R3", 2, day(2), day(27)),
            sc.ChangeDeadline("T03", day(12)),
            sc.ChangePriority("T05", 1),
        ),
    )
    assert workload_to_dict(default_workload) == before
    assert workload_to_dict(modified) != before
    assert modified.resource("R2") is not default_workload.resource("R2")


def test_additional_work_adds_chained_tasks_and_workload():
    package = sc.work_package(
        prefix="X",
        project="Extra",
        total_hours=30,
        task_count=3,
        required_skill="dev",
        due_date=day(13),
        priority=2,
    )
    assert [t.id for t in package] == ["X01", "X02", "X03"]
    assert [t.dependencies for t in package] == [(), ("X01",), ("X02",)]
    base = run(small_workload())
    result = run(sc.apply_scenario(base.workload, scenario(sc.AddTasks(package))))
    assert result.metrics.workload_hours == base.metrics.workload_hours + 30


def test_unavailability_delays_work_and_reduces_capacity():
    base = run(small_workload())
    result = run(sc.apply_scenario(base.workload, scenario(sc.MakeUnavailable("A", day(3), day(4)))))
    assert result.metrics.capacity_hours == base.metrics.capacity_hours - 16
    assert result.schedule["T1"].finish_date == day(5)  # was 3 Nov
    assert result.metrics.missed_deadlines == ("T1", "T2")


def test_additional_capacity_on_the_constrained_resource_helps():
    workload = make_workload([make_resource()], [make_task("T1", effort=20, due=day(3))])
    base = run(workload)
    result = run(sc.apply_scenario(workload, scenario(sc.BoostCapacity("A", 2, day(2), day(13)))))
    assert base.metrics.missed_deadlines == ("T1",)
    assert result.metrics.missed_deadlines == ()
    assert result.metrics.capacity_hours == 100.0


def test_additional_capacity_on_an_ineligible_resource_changes_nothing_but_capacity():
    workload = make_workload(
        [make_resource("A"), make_resource("B", skills=("qa",))], [make_task("T1", effort=20, due=day(3))]
    )
    base = run(workload)
    result = run(sc.apply_scenario(workload, scenario(sc.BoostCapacity("B", 4, day(2), day(13)))))
    comparison = compare(base, result)
    assert comparison.delta("capacity").delta == 40.0
    assert comparison.delta("missed").delta == 0 and comparison.delta("lateness").delta == 0
    assert comparison.task_changes == ()


def test_deadline_change_reorders_equal_priority_work():
    tasks = [make_task("T1", due=day(10)), make_task("T2", due=day(12))]
    workload = make_workload([make_resource()], tasks)
    result = run(sc.apply_scenario(workload, scenario(sc.ChangeDeadline("T2", day(3)))))
    assert result.schedule["T2"].start_date == day(2)
    assert result.schedule["T1"].start_date == day(3)


def test_priority_change_reorders_work():
    tasks = [make_task("T1", priority=2), make_task("T2", priority=3)]
    workload = make_workload([make_resource()], tasks)
    result = run(sc.apply_scenario(workload, scenario(sc.ChangePriority("T2", 1))))
    assert result.schedule["T2"].start_date == day(2)


def test_reassignment_moves_work_to_another_eligible_resource():
    workload = make_workload(
        [make_resource("A"), make_resource("B")],
        [
            make_task("T1", assigned_resource="A", priority=1),
            make_task("T2", assigned_resource="A", due=day(2)),
        ],
    )
    base = run(workload)
    result = run(sc.apply_scenario(workload, scenario(sc.ReassignTask("T2", "B"))))
    assert base.metrics.missed_deadlines == ("T2",)
    assert result.schedule["T2"].resource_id == "B"
    assert result.metrics.missed_deadlines == ()


def test_reassignment_to_an_unskilled_resource_is_rejected():
    workload = small_workload()
    with pytest.raises(WorkloadValidationError, match="lacks required skill"):
        run(sc.apply_scenario(workload, scenario(sc.ReassignTask("T1", "B"))))


@pytest.mark.parametrize(
    "modification",
    [
        sc.MakeUnavailable("NOPE", day(3), day(4)),
        sc.BoostCapacity("NOPE", 2, day(3), day(4)),
        sc.ChangeDeadline("NOPE", day(5)),
        sc.ChangePriority("NOPE", 1),
        sc.ReassignTask("T1", "NOPE"),
    ],
)
def test_scenarios_referring_to_unknown_ids_are_rejected(modification):
    with pytest.raises(WorkloadValidationError, match="unknown"):
        sc.apply_scenario(small_workload(), scenario(modification))


@pytest.mark.parametrize(
    "modification",
    [
        sc.MakeUnavailable("A", day(6), day(3)),
        sc.BoostCapacity("A", 30, day(3), day(4)),
        sc.ChangeDeadline("T1", day(1, month=10)),
        sc.ChangePriority("T1", 9),
        sc.AddTasks((make_task("T1"),)),
        sc.AddTasks((make_task("X1", skill="legal"),)),
    ],
)
def test_invalid_scenario_values_are_rejected_by_the_engine(modification):
    with pytest.raises(WorkloadValidationError):
        run(sc.apply_scenario(small_workload(), scenario(modification)))


def test_scenario_with_no_effect_is_detected():
    base = run(small_workload())
    same = run(sc.apply_scenario(base.workload, scenario(sc.ChangePriority("T1", 3))), "No-op")
    comparison = compare(base, same)
    assert not comparison.has_effect
    assert same.run_id == base.run_id  # identical input -> identical run ID
