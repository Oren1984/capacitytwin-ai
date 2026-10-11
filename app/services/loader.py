"""Safe loading of workload files.

Only JSON is accepted. Files are size-limited, parsed with the standard JSON
parser (no code execution, no pickle) and checked field by field before any
domain object is built. Unknown fields are rejected rather than ignored.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from app.domain.models import CapacityBoost, DateRange, Resource, Task, Workload
from app.domain.validation import WorkloadValidationError, ensure_valid

MAX_FILE_BYTES = 1_000_000
MAX_TEXT_LENGTH = 200
ACCEPTED_EXTENSIONS = (".json",)
DEFAULT_DATASET = Path(__file__).resolve().parents[2] / "data" / "synthetic" / "default_workload.json"

_WORKLOAD_KEYS = {"name", "notice", "period_start", "period_end", "resources", "tasks"}
_RESOURCE_KEYS = {
    "id",
    "name",
    "role",
    "skills",
    "hours_per_day",
    "working_days",
    "focus_factor",
    "unavailable",
    "capacity_boosts",
}
_TASK_KEYS = {
    "id",
    "description",
    "project",
    "effort_hours",
    "priority",
    "due_date",
    "required_skill",
    "dependencies",
    "assigned_resource",
    "release_date",
}


class _Parser:
    def __init__(self) -> None:
        self.issues: list[str] = []

    def keys(self, where: str, raw: Any, allowed: set[str], required: set[str]) -> bool:
        if not isinstance(raw, dict):
            self.issues.append(f"{where}: expected an object.")
            return False
        unknown = sorted(set(raw) - allowed)
        missing = sorted(required - set(raw))
        if unknown:
            self.issues.append(f"{where}: unknown field(s) {', '.join(unknown)}.")
        if missing:
            self.issues.append(f"{where}: missing field(s) {', '.join(missing)}.")
        return not missing

    def text(self, where: str, value: Any, default: str | None = None) -> str:
        if value is None and default is not None:
            return default
        if not isinstance(value, str) or len(value) > MAX_TEXT_LENGTH:
            self.issues.append(f"{where}: expected text of at most {MAX_TEXT_LENGTH} characters.")
            return ""
        return value.strip()

    def number(self, where: str, value: Any) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            self.issues.append(f"{where}: expected a number.")
            return 0.0
        return value

    def integer(self, where: str, value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            self.issues.append(f"{where}: expected a whole number.")
            return 0
        return value

    def day(self, where: str, value: Any) -> date:
        try:
            if not isinstance(value, str):
                raise ValueError
            return date.fromisoformat(value)
        except ValueError:
            self.issues.append(f"{where}: expected a date formatted YYYY-MM-DD.")
            return date.min

    def items(self, where: str, value: Any) -> list:
        if not isinstance(value, list):
            self.issues.append(f"{where}: expected a list.")
            return []
        return value

    def date_range(self, where: str, raw: Any) -> DateRange:
        if not self.keys(where, raw, {"start", "end"}, {"start", "end"}):
            return DateRange(date.min, date.min)
        return DateRange(self.day(f"{where}.start", raw["start"]), self.day(f"{where}.end", raw["end"]))

    def resource(self, where: str, raw: Any) -> Resource | None:
        if not self.keys(where, raw, _RESOURCE_KEYS, {"id", "name", "skills", "hours_per_day"}):
            return None
        boosts = []
        for i, item in enumerate(self.items(f"{where}.capacity_boosts", raw.get("capacity_boosts", []))):
            at = f"{where}.capacity_boosts[{i}]"
            if self.keys(
                at, item, {"start", "end", "extra_hours_per_day"}, {"start", "end", "extra_hours_per_day"}
            ):
                boosts.append(
                    CapacityBoost(
                        DateRange(self.day(f"{at}.start", item["start"]), self.day(f"{at}.end", item["end"])),
                        self.number(f"{at}.extra_hours_per_day", item["extra_hours_per_day"]),
                    )
                )
        return Resource(
            id=self.text(f"{where}.id", raw["id"]),
            name=self.text(f"{where}.name", raw["name"]),
            role=self.text(f"{where}.role", raw.get("role"), default=""),
            skills=tuple(
                self.text(f"{where}.skills", s) for s in self.items(f"{where}.skills", raw["skills"])
            ),
            hours_per_day=self.number(f"{where}.hours_per_day", raw["hours_per_day"]),
            working_days=tuple(
                self.integer(f"{where}.working_days", d)
                for d in self.items(f"{where}.working_days", raw.get("working_days", [0, 1, 2, 3, 4]))
            ),
            focus_factor=self.number(f"{where}.focus_factor", raw.get("focus_factor", 0.8)),
            unavailable=[
                self.date_range(f"{where}.unavailable[{i}]", item)
                for i, item in enumerate(self.items(f"{where}.unavailable", raw.get("unavailable", [])))
            ],
            capacity_boosts=boosts,
        )

    def task(self, where: str, raw: Any) -> Task | None:
        required = {"id", "description", "effort_hours", "priority", "due_date", "required_skill"}
        if not self.keys(where, raw, _TASK_KEYS, required):
            return None
        assigned = raw.get("assigned_resource")
        release = raw.get("release_date")
        return Task(
            id=self.text(f"{where}.id", raw["id"]),
            description=self.text(f"{where}.description", raw["description"]),
            project=self.text(f"{where}.project", raw.get("project"), default="General"),
            effort_hours=self.number(f"{where}.effort_hours", raw["effort_hours"]),
            priority=self.integer(f"{where}.priority", raw["priority"]),
            due_date=self.day(f"{where}.due_date", raw["due_date"]),
            required_skill=self.text(f"{where}.required_skill", raw["required_skill"]),
            dependencies=tuple(
                self.text(f"{where}.dependencies", d)
                for d in self.items(f"{where}.dependencies", raw.get("dependencies", []))
            ),
            assigned_resource=None if assigned is None else self.text(f"{where}.assigned_resource", assigned),
            release_date=None if release is None else self.day(f"{where}.release_date", release),
        )


def workload_from_dict(raw: Any) -> Workload:
    """Build and validate a ``Workload``; raises ``WorkloadValidationError`` with all issues."""
    parser = _Parser()
    required = {"name", "period_start", "period_end", "resources", "tasks"}
    if not parser.keys("File", raw, _WORKLOAD_KEYS, required):
        raise WorkloadValidationError(parser.issues)
    resources = [
        parser.resource(f"resources[{i}]", item)
        for i, item in enumerate(parser.items("resources", raw["resources"]))
    ]
    tasks = [parser.task(f"tasks[{i}]", item) for i, item in enumerate(parser.items("tasks", raw["tasks"]))]
    workload = Workload(
        name=parser.text("name", raw["name"]),
        notice=parser.text("notice", raw.get("notice"), default=""),
        period_start=parser.day("period_start", raw["period_start"]),
        period_end=parser.day("period_end", raw["period_end"]),
        resources=[r for r in resources if r is not None],
        tasks=[t for t in tasks if t is not None],
    )
    if parser.issues:
        raise WorkloadValidationError(parser.issues)
    ensure_valid(workload)
    return workload


def parse_workload_file(filename: str, content: bytes) -> Workload:
    """Parse an uploaded workload file."""
    if not filename.lower().endswith(ACCEPTED_EXTENSIONS):
        raise WorkloadValidationError(["Unsupported file format: only .json workload files are accepted."])
    if len(content) > MAX_FILE_BYTES:
        raise WorkloadValidationError([f"File is larger than the {MAX_FILE_BYTES // 1000} kB limit."])
    try:
        raw = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise WorkloadValidationError(["File is not valid UTF-8 JSON."]) from None
    return workload_from_dict(raw)


def load_default_workload() -> Workload:
    return parse_workload_file(DEFAULT_DATASET.name, DEFAULT_DATASET.read_bytes())


def workload_to_dict(workload: Workload) -> dict:
    """Inverse of ``workload_from_dict`` (JSON-serialisable)."""
    return {
        "name": workload.name,
        "notice": workload.notice,
        "period_start": workload.period_start.isoformat(),
        "period_end": workload.period_end.isoformat(),
        "resources": [
            {
                "id": r.id,
                "name": r.name,
                "role": r.role,
                "skills": list(r.skills),
                "hours_per_day": r.hours_per_day,
                "working_days": list(r.working_days),
                "focus_factor": r.focus_factor,
                "unavailable": [
                    {"start": p.start.isoformat(), "end": p.end.isoformat()} for p in r.unavailable
                ],
                "capacity_boosts": [
                    {
                        "start": b.period.start.isoformat(),
                        "end": b.period.end.isoformat(),
                        "extra_hours_per_day": b.extra_hours_per_day,
                    }
                    for b in r.capacity_boosts
                ],
            }
            for r in workload.resources
        ],
        "tasks": [
            {
                "id": t.id,
                "description": t.description,
                "project": t.project,
                "effort_hours": t.effort_hours,
                "priority": t.priority,
                "due_date": t.due_date.isoformat(),
                "required_skill": t.required_skill,
                "dependencies": list(t.dependencies),
                "assigned_resource": t.assigned_resource,
                "release_date": t.release_date.isoformat() if t.release_date else None,
            }
            for t in workload.tasks
        ],
    }
