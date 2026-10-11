"""Regenerates assets/architecture-diagram.png (dev-only; needs matplotlib).

Usage: python assets/make_diagram.py
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

STEPS = [
    (
        "Workload + Resources",
        "synthetic JSON dataset or uploaded .json",
        "data/synthetic, services/loader.py",
    ),
    ("Input Validation", "types, IDs, dates, skills, dependency cycles", "domain/validation.py"),
    ("Capacity Simulator", "working calendar + dependency-aware priority scheduler", "engine/"),
    ("Baseline Evaluation", "utilization, lateness, overload, bottlenecks", "analytics/metrics.py"),
    ("What-if Scenarios", "modified copies of the baseline, same engine", "scenarios/manager.py"),
    ("Before / After Metrics", "numeric deltas per metric, task and resource", "analytics/comparison.py"),
    ("Recommendations", "rules + template explanation (mock AI mode)", "analytics/recommendations.py, ai/"),
    ("Human Decision", "Streamlit dashboard, CSV / JSON export", "streamlit_app.py, services/reporting.py"),
]
BLUE, INK, MUTED, EDGE = "#2a78d6", "#0b0b0b", "#52514e", "#c3c2b7"

fig, ax = plt.subplots(figsize=(8, 10.5), dpi=150)
ax.set_xlim(0, 10)
ax.set_ylim(0, len(STEPS) * 1.5 + 0.2)
ax.axis("off")
for index, (title, detail, module) in enumerate(STEPS):
    top = (len(STEPS) - index) * 1.5
    last = index == len(STEPS) - 1
    ax.add_patch(
        FancyBboxPatch(
            (1.2, top - 1.0),
            7.6,
            1.0,
            boxstyle="round,pad=0.02,rounding_size=0.12",
            linewidth=1.4,
            edgecolor=BLUE if not last else INK,
            facecolor="#eef4fc" if not last else "#f0efec",
        )
    )
    ax.text(5, top - 0.3, title, ha="center", va="center", fontsize=13, fontweight="bold", color=INK)
    ax.text(5, top - 0.58, detail, ha="center", va="center", fontsize=9.5, color=MUTED)
    ax.text(5, top - 0.83, module, ha="center", va="center", fontsize=8, color=MUTED, family="monospace")
    if not last:
        ax.annotate(
            "",
            xy=(5, top - 1.5 + 0.02),
            xytext=(5, top - 1.02),
            arrowprops={"arrowstyle": "-|>", "color": EDGE, "lw": 1.6},
        )
fig.savefig(Path(__file__).with_name("architecture-diagram.png"), bbox_inches="tight", facecolor="white")
