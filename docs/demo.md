# Demo: before and after

All figures below were produced by the engine on the built-in synthetic dataset and are pinned by `tests/integration/test_pipeline.py`. The data describes a fictional four-person studio delivering two projects between 2 November and 4 December 2026.

## Before: planning by hand

To answer "will we deliver on time?" without a tool, someone has to add up each person's real working hours, walk 18 tasks in dependency order, notice that four of them compete for one part-time designer, and redo the whole exercise for every "what if". The usual shortcut is to compare total hours (242 h of work against 571 h of capacity) and conclude there is plenty of room. That conclusion is wrong.

## After: the same question in the simulator

Start the app (`docker compose up --build`, then <http://localhost:8501>).

**1. Initial workload and capacity.** The overview shows 571.2 h of capacity, 242 h of workload, 42.4% utilization, 3 of 18 deadlines at risk, and completion on 27 Nov 2026.

**2. Baseline bottleneck.** On *Resource capacity*, Maya Stern (designer, part-time) is marked Overloaded: work due by 17 Nov needs 106.5% of her capacity up to that date. On *Work schedule*, the late tasks T03, T11 and T12 all trace back to waiting for her. *Recommendations* notes that nobody else has the design skill.

**3. A plausible but useless fix.** Open *What-if simulator*, choose **D - Additional capacity**, keep the defaults (Dana Levi, +2 h/day for the whole period) and press **Run simulation**.

**4. The fix that works.** Change the resource to **Maya Stern** and run again.

**5. Before/after comparison.**

| Plan | Capacity | Utilization | Missed deadlines | Total lateness | Final completion |
| --- | --- | --- | --- | --- | --- |
| A - Baseline | 571.2 h | 42.4% | 3 (T03, T11, T12) | 5 business days | 27 Nov |
| D - Dana +2 h/day | 611.2 h (+40) | 39.6% | 3 | 5 business days | 27 Nov |
| D - Maya +2 h/day | 601.6 h (+30.4) | 40.2% | 0 | 0 | 25 Nov |

**6. Recommendation.** For Dana the tool states that adding 40 h of capacity does not improve any deadline and the bottleneck is still Maya Stern. For Maya it reports that all three violations are resolved and completion moves two business days earlier.

**7. Assumptions warning.** The *Recommendations* tab ends with the model's assumptions and the reminder that these are estimates for a human to weigh.

## The other scenarios

Each uses the default values offered by the simulator.

| Scenario | Workload | Missed deadlines | Total lateness | Final completion | What it shows |
| --- | --- | --- | --- | --- | --- |
| A - Baseline | 242 h | 3 | 5 days | 27 Nov | |
| B - Add 40 h of backend work (2 tasks, due 20 Nov, priority 2) | 282 h | 6 | 11 days | 1 Dec | Three new violations (T15, T17, X02); the bottleneck moves to the backend developer. |
| C - Eli Cohen away 18 to 20 Nov | 242 h | 9 | 17 days | 1 Dec | Three days off cause six new violations, including tasks that are not his but depend on his. |
| E - T03 raised to priority 1 | 242 h | 4 | 8 days | 30 Nov | A trade-off: T03 is now on time, T14 and T18 become late. |
| E - T03 due date moved to 12 Nov | 242 h | 5 | 10 days | 30 Nov | A tighter deadline reorders the designer's queue and hurts the other project. |
| F - T08 assigned to Noa Barak | 242 h | 3 | 5 days | 27 Nov | No effect: she was already the only eligible person. The tool says so. |

## What the business value is, and is not

The value shown here is measurable scheduling difference: which commitments break, by how many days, and which intervention changes that. No claim is made about time saved in planning; that was not measured.
