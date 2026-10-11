from app.domain.models import CapacityBoost, DateRange
from app.engine.capacity import business_days_after, capacity_minutes, daily_capacity_minutes
from tests.conftest import day, make_resource


def test_daily_capacity_applies_focus_factor_not_calendar_hours():
    res = make_resource(hours=8, focus=0.8)
    assert daily_capacity_minutes(res, day(2)) == 384  # 8 h * 0.8 = 6.4 h


def test_no_capacity_on_non_working_weekday():
    res = make_resource(working_days=(0, 1, 2, 3))
    assert daily_capacity_minutes(res, day(6)) == 0  # Friday
    assert daily_capacity_minutes(res, day(7)) == 0  # Saturday


def test_no_capacity_while_unavailable():
    res = make_resource(unavailable=[DateRange(day(3), day(4))])
    assert [daily_capacity_minutes(res, day(d)) for d in (2, 3, 4, 5)] == [480, 0, 0, 480]


def test_capacity_boost_only_inside_its_period_and_on_working_days():
    res = make_resource(hours=6, focus=0.5, capacity_boosts=[CapacityBoost(DateRange(day(3), day(8)), 2)])
    assert daily_capacity_minutes(res, day(2)) == 180
    assert daily_capacity_minutes(res, day(3)) == 240  # (6 + 2) * 0.5 h
    assert daily_capacity_minutes(res, day(7)) == 0  # Saturday stays non-working


def test_period_capacity_counts_only_working_days():
    res = make_resource(hours=8, focus=1.0)
    assert capacity_minutes(res, day(2), day(13)) == 10 * 480


def test_business_days_after_skips_weekends():
    assert business_days_after(day(6), day(9)) == 1  # Friday -> Monday
    assert business_days_after(day(2), day(6)) == 4
    assert business_days_after(day(6), day(6)) == 0
    assert business_days_after(day(9), day(6)) == 0
