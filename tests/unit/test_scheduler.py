"""Scheduler behaviour on tiny workloads whose correct schedule can be worked out by hand."""

from app.domain.models import DateRange
from app.engine.capacity import daily_capacity_minutes
from app.engine.scheduler import (
    CAUSE_DEPENDENCY,
    CAUSE_NONE,
    CAUSE_RELEASE,
    CAUSE_RESOURCE_BUSY,
    CAUSE_RESOURCE_CALENDAR,
    STATUS_COMPLETED,
    STATUS_PARTIAL,
    STATUS_UNSCHEDULED,
    build_schedule,
)
from tests.conftest import day, make_resource, make_task, make_workload


def spans(schedule, tid):
    return [(s.day.day, s.resource_id, s.start_minute, s.end_minute) for s in schedule[tid].segments]


def test_task_spans_days_at_daily_capacity():
    schedule = build_schedule(make_workload([make_resource(hours=8)], [make_task("T1", effort=12)]))
    assert spans(schedule, "T1") == [(2, "A", 0, 480), (3, "A", 0, 240)]
    assert schedule["T1"].finish_date == day(3)
    assert schedule["T1"].start_cause == CAUSE_NONE


def test_dependent_task_never_starts_before_prerequisite_finishes():
    tasks = [make_task("T2", effort=4, deps=["T1"], priority=1), make_task("T1", effort=12, priority=5)]
    schedule = build_schedule(make_workload([make_resource()], tasks))
    # T2 has the higher priority but must wait; it starts the minute T1 ends (Tuesday, 240).
    assert spans(schedule, "T2") == [(3, "A", 240, 480)]
    assert schedule["T2"].start_cause == CAUSE_DEPENDENCY
    assert schedule["T2"].blocker_task_id == "T1"


def test_dependency_across_resources_hands_over_within_the_day():
    resources = [make_resource("A", hours=8, skills=("dev",)), make_resource("B", hours=4, skills=("qa",))]
    tasks = [make_task("T1", effort=2), make_task("T2", effort=3, deps=["T1"], skill="qa")]
    schedule = build_schedule(make_workload(resources, tasks))
    # B idles until A finishes T1 at minute 120, then uses the rest of its 240-minute day.
    assert spans(schedule, "T2") == [(2, "B", 120, 240), (3, "B", 0, 60)]


def test_higher_priority_task_is_dispatched_first():
    tasks = [make_task("LOW", priority=4), make_task("HIGH", priority=1)]
    schedule = build_schedule(make_workload([make_resource()], tasks))
    assert schedule["HIGH"].start_date == day(2)
    assert schedule["LOW"].start_date == day(3)
    assert (schedule["LOW"].start_cause, schedule["LOW"].blocker_task_id) == (CAUSE_RESOURCE_BUSY, "HIGH")


def test_conflicting_priorities_tie_break_on_due_date_then_id():
    tasks = [
        make_task("T3", priority=2, due=day(10)),
        make_task("T2", priority=2, due=day(10)),
        make_task("T1", priority=2, due=day(12)),
    ]
    schedule = build_schedule(make_workload([make_resource()], tasks))
    order = sorted(schedule, key=lambda tid: schedule[tid].start_date)
    assert order == ["T2", "T3", "T1"]


def test_started_task_is_not_preempted_by_a_later_higher_priority_task():
    tasks = [
        make_task("LONG", effort=24, priority=5),
        make_task("URGENT", effort=4, priority=1, release_date=day(3)),
    ]
    schedule = build_schedule(make_workload([make_resource()], tasks))
    assert schedule["LONG"].finish_date == day(4)
    assert schedule["URGENT"].start_date == day(5)
    assert schedule["URGENT"].start_cause == CAUSE_RESOURCE_BUSY


def test_release_date_is_respected():
    schedule = build_schedule(make_workload([make_resource()], [make_task("T1", release_date=day(4))]))
    assert schedule["T1"].start_date == day(4)
    assert schedule["T1"].start_cause == CAUSE_RELEASE


def test_task_pauses_while_its_resource_is_unavailable():
    res = make_resource(unavailable=[DateRange(day(3), day(3))])
    schedule = build_schedule(make_workload([res], [make_task("T1", effort=12)]))
    assert spans(schedule, "T1") == [(2, "A", 0, 480), (4, "A", 0, 240)]


def test_ready_task_waits_for_unavailable_assigned_resource():
    res = make_resource(unavailable=[DateRange(day(2), day(4))])
    schedule = build_schedule(make_workload([res], [make_task("T1", assigned_resource="A")]))
    assert schedule["T1"].start_date == day(5)
    assert schedule["T1"].start_cause == CAUSE_RESOURCE_CALENDAR


def test_work_is_never_scheduled_on_weekends():
    schedule = build_schedule(make_workload([make_resource()], [make_task("T1", effort=48)]))
    assert [s.day.day for s in schedule["T1"].segments] == [2, 3, 4, 5, 6, 9]


def test_ready_tasks_spread_over_eligible_resources_lowest_id_first():
    tasks = [make_task("T1"), make_task("T2"), make_task("T3", effort=4)]
    schedule = build_schedule(make_workload([make_resource("B"), make_resource("A")], tasks))
    assert (schedule["T1"].resource_id, schedule["T2"].resource_id) == ("A", "B")
    assert schedule["T3"].start_date == day(3) and schedule["T3"].resource_id == "A"


def test_assigned_resource_overrides_skill_eligibility():
    tasks = [make_task("T1"), make_task("T2", assigned_resource="A")]
    schedule = build_schedule(make_workload([make_resource("A"), make_resource("B")], tasks))
    assert schedule["T2"].resource_id == "A"
    assert schedule["T2"].start_date == day(3)  # waits for A although B is idle


def test_multiple_tasks_sharing_a_dependency_all_wait_for_it():
    resources = [make_resource("A"), make_resource("B")]
    tasks = [
        make_task("ROOT", effort=4, priority=1, assigned_resource="A"),
        make_task("C1", effort=2, deps=["ROOT"]),
        make_task("C2", effort=2, deps=["ROOT"]),
    ]
    schedule = build_schedule(make_workload(resources, tasks))
    assert spans(schedule, "C1") == [(2, "A", 240, 360)]
    assert spans(schedule, "C2") == [(2, "B", 240, 360)]


def test_work_beyond_the_period_is_reported_not_dropped():
    tasks = [make_task("T1", effort=100), make_task("T2", effort=8, deps=["T1"])]
    schedule = build_schedule(make_workload([make_resource()], tasks))
    assert schedule["T1"].status == STATUS_PARTIAL
    assert schedule["T1"].scheduled_minutes == 80 * 60
    assert schedule["T1"].remaining_minutes == 20 * 60
    assert schedule["T2"].status == STATUS_UNSCHEDULED
    assert "T1" in schedule["T2"].unscheduled_reason


def test_zero_capacity_leaves_tasks_unscheduled_with_a_reason():
    schedule = build_schedule(make_workload([make_resource(hours=0)], [make_task("T1")]))
    assert schedule["T1"].status == STATUS_UNSCHEDULED
    assert schedule["T1"].unscheduled_reason == "No eligible resource has any capacity in the period."


def test_fully_booked_reason_when_capacity_runs_out():
    tasks = [make_task("T1", effort=80, priority=1), make_task("T2")]
    schedule = build_schedule(make_workload([make_resource()], tasks))
    assert schedule["T1"].status == STATUS_COMPLETED
    assert "fully booked" in schedule["T2"].unscheduled_reason


def test_empty_workload_produces_an_empty_schedule():
    assert build_schedule(make_workload([make_resource()], [])) == {}
    assert build_schedule(make_workload([], [])) == {}


def test_schedule_is_deterministic_and_independent_of_input_order(default_workload):
    first = build_schedule(default_workload)
    shuffled = default_workload.copy()
    shuffled.tasks.reverse()
    shuffled.resources.reverse()
    assert build_schedule(shuffled) == first
    assert build_schedule(default_workload) == first


def test_a_resource_never_works_on_two_tasks_at_once_or_beyond_its_day(default_workload):
    schedule = build_schedule(default_workload)
    by_resource_day = {}
    for entry in schedule.values():
        for seg in entry.segments:
            by_resource_day.setdefault((seg.resource_id, seg.day), []).append(seg)
    for (rid, when), segments in by_resource_day.items():
        segments.sort(key=lambda s: s.start_minute)
        for earlier, later in zip(segments, segments[1:], strict=False):
            assert earlier.end_minute <= later.start_minute
        assert segments[-1].end_minute <= daily_capacity_minutes(default_workload.resource(rid), when)


def test_every_dependency_is_respected_in_the_demo_dataset(default_workload):
    schedule = build_schedule(default_workload)
    for task in default_workload.tasks:
        for dep in task.dependencies:
            assert schedule[dep].finish_date <= schedule[task.id].start_date
