"""Deterministic, template-based explanations. No network, no model, no randomness."""

from __future__ import annotations

from app.ai.provider import MODE_MOCK, Evidence, Explanation, PlanFacts

LABEL = "Template-based explanation (mock mode, no AI model involved)"
CAVEAT = (
    "These figures are estimates from a simplified model with explicit assumptions, "
    "not a prediction of what will happen. A person should make the final call."
)


def _percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value:g}%"


def _plan_sentence(facts: PlanFacts) -> str:
    text = (
        f"In '{facts.name}', the team has {facts.capacity_hours:g} h of productive capacity for "
        f"{facts.workload_hours:g} h of estimated work; {_percent(facts.utilization_pct)} of capacity is used."
    )
    if facts.missed_deadlines:
        bound = "at least " if facts.lateness_is_lower_bound else ""
        text += (
            f" {len(facts.missed_deadlines)} task(s) miss their deadline "
            f"({', '.join(facts.missed_deadlines)}), {bound}{facts.total_lateness_days} business day(s) late in total."
        )
    else:
        text += " No task misses its deadline."
    if facts.final_completion:
        text += f" The last task finishes on {facts.final_completion}."
    else:
        text += f" {facts.unscheduled_hours:g} h of work does not fit in the planning period."
    if facts.bottleneck_name:
        text += f" The main bottleneck is {facts.bottleneck_name}."
    return text


class MockExplanationProvider:
    mode = MODE_MOCK

    def explain(self, evidence: Evidence) -> Explanation:
        parts = [_plan_sentence(evidence.baseline)]
        if evidence.scenario is not None:
            parts.append(_plan_sentence(evidence.scenario))
            parts.extend(finding.text for finding in evidence.scenario_findings)
        elif evidence.baseline.findings:
            parts.append(evidence.baseline.findings[0].text)
        parts.append(CAVEAT)
        return Explanation(text="\n\n".join(parts), mode=self.mode, label=LABEL)
