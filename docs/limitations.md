# Limitations and future work

## Modelling limitations

- **Estimates are taken as exact.** No uncertainty, ranges or probabilities. A task estimated at 16 h takes 16 h.
- **Greedy, not optimal.** The scheduler follows fixed dispatch rules. A better plan may exist, and small changes can shift unrelated tasks (in the demo, giving the developer more hours moves one coordinator task a day later).
- **One task at a time, no interruptions.** Real people multitask and get pulled onto urgent work; the model has no preemption or hand-over. If someone becomes unavailable mid-task, the task waits for them.
- **Skills are yes or no.** Everyone with a skill is equally fast. No learning curve, seniority or partial fit.
- **Unassigned tasks go to the lowest resource ID that is free**, not to the best choice.
- **Day-level calendar.** Everyone starts at the same time; no time zones, half days or public holidays (enter holidays as unavailability).
- **A single focus factor per person** stands in for meetings, admin and context switching.
- **Dependencies are finish-to-start only.** No lags, partial overlaps or review loops.
- **Nothing happens after the planning period.** Work that does not fit is reported as unscheduled; its lateness is a lower bound.
- **Bottleneck attribution is a heuristic** over one schedule, and the 85% "high load" threshold is a convention.
- **Not a live twin.** It is a snapshot model of data you supply, not synchronised with any real system.

## Product limitations

- Workloads are edited as JSON files; the UI has no task or resource editor.
- One what-if at a time, compared with the baseline. Scenarios cannot be combined or saved in the UI (the engine supports several modifications per scenario).
- No persistence, users or authentication. Single-user local demo.
- Explanations are templates. No real LLM provider is implemented.
- English only; dates are shown in ISO or English formats.

## Verification limitations

- Tested on Windows 11 with Python 3.12 and in the Linux container. No other platforms were tried.
- End-to-end tests drive the app with Streamlit's `AppTest`, which does not render charts or exercise file upload in a browser. Charts were checked visually in a headless browser; the upload path is covered at the parser level only.
- No load or performance testing. The engine takes a few milliseconds on the 18-task demo; behaviour near the 500-task limit was not measured.
- No measurement of planning time saved was made, so none is claimed.

## Possible next steps

1. In-app editing of tasks and resources, and CSV import.
2. Combining and saving scenarios; comparing several side by side.
3. Effort ranges with Monte Carlo runs, reported honestly as distributions.
4. Smarter assignment for tasks with several eligible people.
5. An optional LLM explanation provider behind the existing contract.
6. Public-holiday calendars and per-day hours.
