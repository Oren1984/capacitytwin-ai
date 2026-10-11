from app.analytics.metrics import STATUS_HIGH, STATUS_NO_CAPACITY, STATUS_OK, STATUS_OVERLOADED, pct
from app.domain.models import DateRange
from tests.conftest import day, make_resource, make_task, make_workload, run


def test_utilization_formula_and_zero_denominator():
    assert pct(30, 120) == 25.0  # allocated / available * 100
    assert pct(5, 0) is None  # zero capacity: undefined, shown as n/a


def test_capacity_workload_and_utilization_totals():
    result = run(make_workload([make_resource(hours=8)], [make_task("T1", effort=20)]))
    m = result.metrics
    assert (m.capacity_hours, m.workload_hours, m.scheduled_hours) == (80.0, 20.0, 20.0)
    assert m.utilization_pct == 25.0 and m.demand_ratio_pct == 25.0
    assert m.final_completion_date == day(4)


def test_demand_ratio_may_exceed_100_but_utilization_never_does():
    result = run(make_workload([make_resource()], [make_task("T1", effort=100), make_task("T2", effort=20)]))
    m = result.metrics
    assert m.demand_ratio_pct == 150.0
    assert m.utilization_pct == 100.0
    assert m.unscheduled_hours == 40.0
    assert m.final_completion_date is None
    assert m.resource("A").status == STATUS_OVERLOADED


def test_lateness_is_counted_in_business_days_after_the_due_date():
    # 16 h at 8 h/day finishes Tuesday 3 Nov; due Monday 2 Nov -> 1 business day late.
    result = run(make_workload([make_resource()], [make_task("T1", effort=16, due=day(2))]))
    tm = result.metrics.tasks["T1"]
    assert (tm.late, tm.lateness_days, tm.lateness_is_lower_bound) == (True, 1, False)
    assert result.metrics.missed_deadlines == ("T1",)
    assert result.metrics.total_lateness_days == 1


def test_task_finishing_on_its_due_date_is_on_time():
    result = run(make_workload([make_resource()], [make_task("T1", effort=16, due=day(3))]))
    assert result.metrics.missed_deadlines == ()


def test_lateness_across_a_weekend_ignores_saturday_and_sunday():
    # 48 h finishes Monday 9 Nov; due Thursday 5 Nov -> Friday + Monday = 2 business days.
    result = run(make_workload([make_resource()], [make_task("T1", effort=48, due=day(5))]))
    assert result.metrics.tasks["T1"].lateness_days == 2


def test_unfinished_task_lateness_is_a_flagged_lower_bound():
    result = run(make_workload([make_resource()], [make_task("T1", effort=100, due=day(12))]))
    tm = result.metrics.tasks["T1"]
    # Period ends Fri 13 Nov; earliest possible finish is Mon 16 Nov = 2 business days after Thu 12.
    assert (tm.late, tm.lateness_days, tm.lateness_is_lower_bound) == (True, 2, True)
    assert result.metrics.lateness_is_lower_bound


def test_zero_capacity_resource_reports_no_capacity_and_undefined_utilization():
    result = run(make_workload([make_resource(hours=0)], [make_task("T1")]))
    res = result.metrics.resource("A")
    assert res.status == STATUS_NO_CAPACITY
    assert res.utilization_pct is None and res.demand_ratio_pct is None
    assert res.demand_hours == 8.0  # sole eligible resource still carries the demand
    assert result.metrics.utilization_pct is None
    assert result.metrics.unscheduled_hours == 8.0


def test_empty_workload_metrics():
    m = run(make_workload([make_resource()], [])).metrics
    assert (m.workload_hours, m.utilization_pct, m.tasks_total) == (0.0, 0.0, 0)
    assert m.missed_deadlines == () and m.final_completion_date is None


def test_peak_deadline_load_flags_overload_that_period_totals_hide():
    # 24 h due by Tuesday needs 150 % of the 16 h available by then, yet only 30 % of the period.
    result = run(make_workload([make_resource()], [make_task("T1", effort=24, due=day(3))]))
    res = result.metrics.resource("A")
    assert res.peak_deadline_load_pct == 150.0 and res.peak_deadline_date == day(3)
    assert res.demand_ratio_pct == 30.0
    assert res.status == STATUS_OVERLOADED


def test_high_load_and_ok_statuses():
    high = run(make_workload([make_resource()], [make_task("T1", effort=14, due=day(3))]))
    assert high.metrics.resource("A").status == STATUS_HIGH  # 14 / 16 = 87.5 %
    ok = run(make_workload([make_resource()], [make_task("T1", effort=8, due=day(3))]))
    assert ok.metrics.resource("A").status == STATUS_OK


def test_bottleneck_is_the_resource_late_tasks_queued_for():
    resources = [make_resource("A", skills=("design",)), make_resource("B", skills=("dev",))]
    tasks = [
        make_task("D1", effort=16, skill="design", priority=1, due=day(3)),
        make_task("D2", effort=16, skill="design", priority=2, due=day(3)),
        make_task("B1", effort=8, deps=["D2"], due=day(5)),
    ]
    result = run(make_workload(resources, tasks))
    m = result.metrics
    assert m.missed_deadlines == ("B1", "D2")
    assert m.bottleneck_resource_id == "A"
    assert m.resource("A").late_tasks_caused == 2
    assert m.resource("A").queue_wait_days == 2
    assert m.blocking_task_id == "D2"  # the late prerequisite behind B1
    assert [link.task_id for link in m.tasks["B1"].delay_chain] == ["B1", "D2", "D1"]


def test_no_bottleneck_when_nothing_is_late():
    m = run(make_workload([make_resource()], [make_task("T1")])).metrics
    assert m.bottleneck_resource_id is None and m.blocking_task_id is None


def test_unavailability_reduces_capacity():
    res = make_resource(unavailable=[DateRange(day(4), day(6))])
    assert run(make_workload([res], [])).metrics.capacity_hours == 56.0
