# Testing

## Strategy

Tests were written alongside the engine, not after it. The scheduler was first checked against tiny workloads whose correct schedule can be worked out by hand; the synthetic dataset's results were then pinned so any change in policy or data fails a test.

| Layer | Location | What it covers |
| --- | --- | --- |
| Unit | `tests/unit/` | Capacity and calendar maths, validation rules, scheduling policy (dependencies, priority, tie-breaks, no preemption, pauses, period overflow, zero capacity), metric formulas, each scenario type, scenario isolation, file parsing, export safety, recommendation grounding. |
| Integration | `tests/integration/` | Dataset to results with pinned figures; baseline to scenario to comparison for scenarios B to E; reproducibility; mock explanation from evidence; JSON report; logging of runs and validation failures. |
| End-to-end | `tests/e2e/` | The dashboard driven headlessly with Streamlit `AppTest`: opening state, a full baseline to before/after workflow, every scenario type through the UI, an invalid scenario, restoring the default dataset, empty and unschedulable workloads. |

## Commands

```bash
pip install -r requirements-dev.txt

ruff format --check app tests assets     # formatting
ruff check app tests assets              # lint (includes flake8-bandit "S" security rules)
python -m compileall -q app tests        # syntax
python -m pytest                         # all tests
python -m pytest tests/unit              # one layer
pip-audit -r requirements.txt            # dependency vulnerabilities

docker compose up --build -d             # container
docker compose ps                        # expect "healthy"
docker compose logs
docker compose down
```

## Results

Executed on 11 October 2026: Windows 11, Python 3.12.10, Docker 29.8.2, Compose v5.5.1.

| Gate | Check | Result |
| --- | --- | --- |
| A - Static | `ruff format --check` (34 files), `ruff check`, `compileall` | PASS |
| A - Static | Dependency consistency: the pinned `requirements.txt` installs and runs in a clean `python:3.12-slim` image | PASS |
| B - Unit | 124 tests | PASS |
| C - Integration | 15 tests | PASS |
| E2E | 10 `AppTest` workflows | PASS |
| D - Security | `pip-audit -r requirements.txt`: no known vulnerabilities | PASS (run inside a `python:3.12-slim` container; see known issues) |
| D - Security | Search for secrets and for `eval`, `exec`, `pickle`, `subprocess`, `os.system` in the code | PASS (none) |
| D - Security | Input validation tests (part of the unit suite) | PASS |
| D - Security | Container review on the running container: UID 10001, read-only root filesystem (write attempt refused), all capabilities dropped, `no-new-privileges`, 1 GB memory and 256 process limits, port bound to 127.0.0.1 | PASS |
| E - Docker | Image build; `docker compose up`; health check healthy; HTTP 200 on port 8501; `docker compose restart` returns to healthy; logs contain no errors or warnings; `docker compose down` removes the container and frees the port | PASS |
| F - Functional demo | In the running container, through a headless browser: baseline loaded; scenarios B, C, D (both variants) and E run; results identical to the pinned figures; mock explanation and assumptions warning present; no browser console errors or failed requests | PASS |
| G - Documentation | Relative links and image references resolve; commands above are the ones executed; screenshots taken from the running container | PASS |
| Observability | Startup, run ID, scenario name, duration and scenario type appear in container logs; validation failures and AI-mode fallback are asserted in tests | PASS |

Total: **149 automated tests, 149 passed.** Engine time for the 18-task dataset was 2.5 to 3.4 ms per run in the container logs.

## Not run

| Check | Status | Reason |
| --- | --- | --- |
| File upload through a real browser | NOT RUN | `AppTest` cannot drive the upload widget; the parser behind it is unit-tested, including hostile input. |
| Chart rendering assertions | NOT RUN (automated) | Charts were inspected visually in headless-browser screenshots only. |
| Load and performance tests | NOT RUN | Out of scope for a single-user proof of concept. |
| Other operating systems and Python versions | NOT RUN | Only the environment above and the Linux container were available. |
| Container image vulnerability scan | NOT RUN | No image scanner was installed; only Python dependencies were audited. |

## Known issues

- `pip-audit` could not reach PyPI from the Windows host because of a local TLS certificate verification failure. Certificate checks were not disabled; the audit was run inside a container instead, where it completed normally.
- The image is about 777 MB, almost all of it Streamlit's own dependencies.
- The scheduler is greedy, so a scenario can move an unrelated task slightly (documented in [limitations.md](limitations.md)). This is model behaviour, not a defect.
