"""Explanation provider contract.

The provider only ever receives ``Evidence``: an immutable snapshot of numbers
the deterministic engine already produced. It returns prose. It has no way to
change a schedule or a metric, so the engine stays the single source of truth.

Only the deterministic mock provider is implemented. A real LLM provider would
implement ``ExplanationProvider`` and be registered in ``get_provider``
(see docs/limitations.md).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from app.analytics.comparison import Comparison
from app.analytics.recommendations import (
    Recommendation,
    recommend_for_comparison,
    recommend_for_result,
)
from app.config import ai_mode
from app.engine.simulation import SimulationResult

logger = logging.getLogger("capacitytwin.ai")

MODE_MOCK = "mock"


@dataclass(frozen=True)
class PlanFacts:
    name: str
    run_id: str
    capacity_hours: float
    workload_hours: float
    utilization_pct: float | None
    missed_deadlines: tuple[str, ...]
    total_lateness_days: int
    lateness_is_lower_bound: bool
    unscheduled_hours: float
    final_completion: str | None
    bottleneck_name: str | None
    findings: tuple[Recommendation, ...]


@dataclass(frozen=True)
class Evidence:
    baseline: PlanFacts
    scenario: PlanFacts | None = None
    scenario_findings: tuple[Recommendation, ...] = ()
    has_effect: bool | None = None


@dataclass(frozen=True)
class Explanation:
    text: str
    mode: str
    label: str


class ExplanationProvider(Protocol):
    mode: str

    def explain(self, evidence: Evidence) -> Explanation: ...


def _facts(result: SimulationResult) -> PlanFacts:
    m = result.metrics
    return PlanFacts(
        name=result.scenario_name,
        run_id=result.run_id,
        capacity_hours=m.capacity_hours,
        workload_hours=m.workload_hours,
        utilization_pct=m.utilization_pct,
        missed_deadlines=m.missed_deadlines,
        total_lateness_days=m.total_lateness_days,
        lateness_is_lower_bound=m.lateness_is_lower_bound,
        unscheduled_hours=m.unscheduled_hours,
        final_completion=m.final_completion_date.isoformat() if m.final_completion_date else None,
        bottleneck_name=(
            result.workload.resource(m.bottleneck_resource_id).name if m.bottleneck_resource_id else None
        ),
        findings=tuple(recommend_for_result(result)),
    )


def build_evidence(
    baseline: SimulationResult,
    scenario: SimulationResult | None = None,
    comparison: Comparison | None = None,
) -> Evidence:
    if scenario is None or comparison is None:
        return Evidence(baseline=_facts(baseline))
    return Evidence(
        baseline=_facts(baseline),
        scenario=_facts(scenario),
        scenario_findings=tuple(recommend_for_comparison(baseline, scenario, comparison)),
        has_effect=comparison.has_effect,
    )


def get_provider() -> ExplanationProvider:
    """Provider selected by CAPACITYTWIN_AI_MODE. Anything but 'mock' falls back to mock."""
    from app.ai.mock_provider import MockExplanationProvider

    mode = ai_mode()
    if mode != MODE_MOCK:
        logger.warning("AI mode %r is not implemented; falling back to mock explanations", mode)
    return MockExplanationProvider()
