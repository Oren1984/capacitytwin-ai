"""Simulation entry point: validate -> schedule -> metrics, with logging and a run ID."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import asdict, dataclass

from app.analytics.metrics import Metrics, compute_metrics
from app.domain.models import Workload
from app.domain.validation import WorkloadValidationError, ensure_valid
from app.engine.scheduler import TaskSchedule, build_schedule

logger = logging.getLogger("capacitytwin.simulation")


@dataclass(frozen=True)
class SimulationResult:
    run_id: str
    scenario_name: str
    workload: Workload
    schedule: dict[str, TaskSchedule]
    metrics: Metrics
    duration_ms: float


def workload_fingerprint(workload: Workload) -> str:
    """Short deterministic hash of the simulated input: same input, same run ID."""
    canonical = json.dumps(asdict(workload), sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()[:10]


class SimulationEngine:
    """The single engine every baseline and what-if scenario runs through."""

    def run(self, workload: Workload, scenario_name: str = "Baseline") -> SimulationResult:
        started = time.perf_counter()
        try:
            ensure_valid(workload)
        except WorkloadValidationError as exc:
            logger.warning(
                "validation failed scenario=%r issues=%d first=%r",
                scenario_name,
                len(exc.issues),
                exc.issues[0],
            )
            raise
        run_id = workload_fingerprint(workload)
        try:
            schedule = build_schedule(workload)
            metrics = compute_metrics(workload, schedule)
        except Exception:
            logger.exception("calculation failed run_id=%s scenario=%r", run_id, scenario_name)
            raise
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        logger.info(
            "simulation run_id=%s scenario=%r tasks=%d resources=%d missed=%d duration_ms=%.2f",
            run_id,
            scenario_name,
            len(workload.tasks),
            len(workload.resources),
            len(metrics.missed_deadlines),
            duration_ms,
        )
        return SimulationResult(run_id, scenario_name, workload, schedule, metrics, duration_ms)
