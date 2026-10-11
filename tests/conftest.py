"""Shared builders for small, hand-checkable workloads.

The test period is Monday 2 November 2026 to Friday 13 November 2026.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.domain.models import Resource, Task, Workload
from app.engine.simulation import SimulationEngine, SimulationResult
from app.services.loader import load_default_workload


def day(d: int, month: int = 11) -> date:
    return date(2026, month, d)


def make_resource(
    rid: str = "A", hours: float = 8, skills=("dev",), focus: float = 1.0, **kwargs
) -> Resource:
    return Resource(
        id=rid,
        name=f"Res {rid}",
        role="",
        skills=tuple(skills),
        hours_per_day=hours,
        focus_factor=focus,
        **kwargs,
    )


def make_task(
    tid: str, effort: float = 8, deps=(), due: date | None = None, priority: int = 3, **kwargs
) -> Task:
    return Task(
        id=tid,
        description=f"Task {tid}",
        project="P",
        effort_hours=effort,
        priority=priority,
        due_date=due or day(13),
        required_skill=kwargs.pop("skill", "dev"),
        dependencies=tuple(deps),
        **kwargs,
    )


def make_workload(resources, tasks, start: date | None = None, end: date | None = None) -> Workload:
    return Workload("test", start or day(2), end or day(13), list(resources), list(tasks))


def run(workload: Workload, name: str = "Baseline") -> SimulationResult:
    return SimulationEngine().run(workload, name)


@pytest.fixture
def default_workload() -> Workload:
    return load_default_workload()


@pytest.fixture
def baseline(default_workload) -> SimulationResult:
    return run(default_workload)
