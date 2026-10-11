# Assurance

Controls are sized for a local proof of concept running on synthetic data. No formal compliance with any standard or regulation is claimed.

## Input controls

- **Accepted format:** `.json` only, at most 1 MB (enforced in `services/loader.py` and by Streamlit's `maxUploadSize`).
- **Parsing:** the standard JSON parser. No `eval`, `exec`, `pickle`, YAML or other code-carrying formats anywhere in the application.
- **Schema:** every field is type-checked; unknown fields are rejected, not ignored; text is limited to 200 characters.
- **Semantics:** duplicate IDs, unknown references, self and cyclic dependencies, non-positive or non-finite effort, invalid priorities, impossible dates, missing skills and out-of-range hours are all reported together in plain language.
- **Limits:** 50 resources, 500 tasks, a 366-day planning period, 10,000 hours per task.
- Scenario inputs pass through the same validation as files before anything is simulated.

## Security

- **No secrets.** The app needs no API key or credential. `.env` is git-ignored; `.env.example` contains only two non-sensitive settings.
- **No outbound network calls** at run time. Streamlit usage statistics are disabled.
- **Exports:** CSV text cells beginning with `=`, `+`, `-`, `@`, tab or carriage return are prefixed with `'` to prevent spreadsheet formula injection. JSON export contains plain values only.
- **Container:** non-root user, read-only root filesystem, all Linux capabilities dropped, `no-new-privileges`, memory, CPU and process limits, health check, port published on `127.0.0.1` only.
- **Dependencies:** three pinned runtime packages. `pip-audit` reported no known vulnerabilities on the date in [testing.md](testing.md).
- **Not designed for public internet exposure.** There is no authentication, and none is appropriate to add for a local single-user demo. Do not publish the port or deploy it to a shared network as is.

## Observability

Standard Python logging to stderr (visible with `docker compose logs`), level set by `CAPACITYTWIN_LOG_LEVEL`.

| Event | Logged fields |
| --- | --- |
| Application startup | AI mode, log level |
| Simulation run | run ID, scenario name, task and resource counts, missed deadlines, duration in ms |
| Scenario run from the UI | scenario type, run ID |
| Validation failure | scenario name, number of issues, first issue |
| Rejected upload | number of issues |
| Calculation or explanation failure | stack trace with run ID |
| Unsupported AI mode | the requested mode, fallback to mock |

Each run has an ID derived from its input, shown in *Data and export* with the engine time. Logs contain no secrets. Task and resource IDs can appear in validation messages; with real data, treat logs accordingly.

Users see controlled messages: a list of validation issues, or a generic failure notice pointing to the log. No stack traces are shown in the UI.

## AI boundaries

- Every number comes from the deterministic engine. The explanation layer receives a read-only snapshot of those numbers and returns text.
- Only **mock mode** exists: fixed templates, no model, no network. It is labelled as such wherever its output appears.
- Setting `CAPACITYTWIN_AI_MODE` to anything else logs a warning and falls back to mock.
- If a real LLM provider is added later, it must stay behind the same contract: explain and summarise only, clearly labelled, with timeouts and graceful failure, and no ability to alter results or trigger actions.

## Privacy

- The bundled dataset is synthetic and says so in the file, the UI and the JSON report. The people and projects are invented.
- Nothing is persisted. Uploaded files live in the browser session's memory and disappear on restart.
- If you load real data, you are responsible for it: use the minimum needed (IDs or roles instead of names work fine), and keep the app local.

## Human oversight

- The tool recommends; it does not assign work, change calendars, send messages or enforce anything.
- Outputs are estimates under the assumptions in [simulation-methodology.md](simulation-methodology.md). A person who knows the team decides.
- It measures workload against capacity, not people. It must not be used for performance evaluation, disciplinary action or employment decisions.
