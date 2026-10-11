# Simulation methodology

Everything the simulator reports follows from the rules on this page. There is no randomness and no AI in any calculation.

## Units

| Quantity | Unit |
| --- | --- |
| Effort, capacity | hours (whole minutes internally) |
| Dates | calendar days; "due 17 Nov" means finished by the end of 17 Nov |
| Lateness, waiting | business days (Monday to Friday) |
| Priority | 1 (highest) to 5 (lowest) |

## Working calendar and capacity

For a resource on a given day:

```
capacity = 0                                                if the weekday is not one of its working days
capacity = 0                                                if the day is inside an unavailability period
capacity = (hours_per_day + extra hours active that day) x focus_factor     otherwise
```

- `focus_factor` (default 0.8) is the share of scheduled hours that is productive project time. An 8-hour day therefore yields 6.4 hours of capacity, never 8.
- "Extra hours" come from the Additional capacity scenario and are also multiplied by the focus factor.
- Capacity for a period is the sum of daily capacities. There are no public holidays in the model; enter them as unavailability.

## Who can do a task

A task names a required skill. Every resource holding that skill is eligible. If the task has an assigned resource, only that resource is eligible.

## Scheduling algorithm

A dependency-aware priority scheduler (a deterministic dispatch simulation):

1. Time advances day by day through the planning period. Each resource has a daily window of productive minutes starting at minute 0; all resources start their day together.
2. A task is **ready** when its release date (if any) has arrived and all its prerequisites are finished. It can start the same day, at the minute its last prerequisite ends.
3. Whenever one or more resources are free, ready tasks are taken in this order: **priority, then earlier due date, then task ID**. Each goes to the free eligible resource with the **lowest resource ID**.
4. A resource works on **one task at a time** (no parallel work).
5. A started task stays with its resource until finished: **no preemption and no hand-over**. It pauses over days when that resource has no capacity (weekend, non-working day, unavailability) and resumes afterwards.
6. A free resource with nothing ready waits; it is never given work it is not eligible for.
7. The simulation stops at the end of the planning period. Unfinished work is reported as unscheduled hours with a reason per task. It is never dropped.

The result is a feasible schedule under these rules, not an optimal one. Because dispatching is greedy, a change can occasionally move an unrelated task slightly later (for example, a person freed earlier picks up a different task first).

## Metrics

| Metric | Definition |
| --- | --- |
| Available capacity | Sum of all resources' capacity in the planning period. |
| Estimated workload | Sum of task effort. |
| Workload demand ratio | workload / capacity x 100. Can exceed 100%. |
| Capacity utilization | hours actually scheduled / capacity x 100. Never exceeds 100%. |
| Per-resource demand | Effort of tasks the schedule gave to the resource, plus unstarted tasks only that resource may do. |
| Unscheduled work | workload minus scheduled hours. |
| Missed deadline | A task finishing after its due date, or unfinished in the period with a due date inside it. |
| Lateness | Business days after the due date up to the finish date. For unfinished tasks: business days from the due date to the first business day after the period, flagged as a lower bound ("at least"). |
| Final completion date | Finish date of the last task; "Beyond period" if anything is unfinished. |
| Peak deadline load | For each due date D among a resource's tasks: effort due by D / capacity from period start to D (or to the period end, if earlier). The highest value is reported. |

When capacity is zero, ratios are undefined and shown as "n/a" (never as 0% or infinity). A resource with zero capacity has status "No capacity".

Resource status: **Overloaded** if demand exceeds period capacity or peak deadline load is above 100%; **High load** from 85%; otherwise **OK**. The 85% threshold is a fixed convention, not a calibrated value.

## Bottleneck interpretation

For each task the scheduler records why it started when it did:

| Cause | Meaning |
| --- | --- |
| Start of period / release date | Nothing delayed it. |
| Prerequisite | It started the moment its last prerequisite finished (or at the resource's next working time after that). |
| Resource busy | It was ready, but its resource was working on another task. |
| Resource unavailable | It was ready, but its resource was inside an unavailability period. |

For every late task the chain of causes is followed backwards (for example `T03 ← Maya busy on T11 ← Maya busy on T02 ← prerequisite T01`).

- **Main bottleneck** is the resource that the most late tasks had to wait for somewhere in their chain. Ties are broken by total waiting time, then resource ID.
- **Tasks waited** is the total number of business days tasks spent ready but waiting for that resource.

These are descriptive heuristics over one deterministic schedule. No probability or confidence score is produced.

## Reproducibility

The run ID is the first 10 hex characters of a SHA-256 hash of the simulated input. The same workload always yields the same schedule, metrics and run ID, independent of the order of tasks or resources in the file.

## Known modelling limitations

See [limitations.md](limitations.md).
