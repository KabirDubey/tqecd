"""Optional gold-standard mode: LER-vs-p plots and Lambda (Λ) suppression factors.

This is the authoritative fault-tolerance signal (as opposed to the static predictors), but it is
opt-in and slow, so it lives outside the core loop. It reuses ``tqec.orchestration.simulate_batch``
(one flattened ``sinter.collect``) and embeds one matplotlib LER-vs-p figure per gadget into the
report as a base64 ``data:`` URI, keeping ``report.html`` a single self-contained file.
"""

from __future__ import annotations

import base64
import io
from collections import defaultdict
from typing import Any

from tools.experiment.config import ExperimentConfig
from tools.experiment.report import ExperimentReport


def _ler(result: Any) -> float | None:
    if result.shots <= result.discards:
        return None
    return result.errors / (result.shots - result.discards)


def _plot_data_uri(points: dict[int, list[tuple[float, float]]], title: str) -> str | None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ModuleNotFoundError:  # pragma: no cover
        return None
    fig, ax = plt.subplots(figsize=(4.5, 3.2), dpi=120)
    for k in sorted(points):
        pts = sorted(points[k])
        ax.plot([p for p, _ in pts], [l for _, l in pts], marker="o", label=f"k={k}")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("physical error rate p")
    ax.set_ylabel("logical error rate")
    ax.set_title(title, fontsize=9)
    ax.legend(fontsize=8)
    ax.grid(True, which="both", alpha=0.3)
    fig.tight_layout()
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png")
    plt.close(fig)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _lambda_factor(points: dict[int, list[tuple[float, float]]]) -> float | None:
    """Λ ≈ LER(d) / LER(d+2) at the largest common p, from the two largest available k."""
    ks = sorted(points)
    if len(ks) < 2:
        return None
    low, high = ks[-2], ks[-1]
    low_map = dict(points[low])
    high_map = dict(points[high])
    shared = sorted(set(low_map) & set(high_map))
    if not shared:
        return None
    p = shared[-1]
    if high_map[p] <= 0:
        return None
    return low_map[p] / high_map[p]


def augment(
    report: ExperimentReport, manifest: Any, config: ExperimentConfig
) -> ExperimentReport:
    """Run ``simulate_batch`` and attach per-gadget LER plots + Λ factors to ``report``."""
    from tqec.orchestration import simulate_batch

    batch_result = simulate_batch(manifest)

    # gadget_id -> {k: [(p, ler)]}
    curves: dict[str, dict[int, list[tuple[float, float]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for unit_result in batch_result.results:
        ler = _ler(unit_result)
        if ler is None:
            continue
        curves[unit_result.gadget_id][unit_result.k].append((unit_result.p, ler))

    report.meta["simulation"] = {
        "aggregate": getattr(batch_result, "aggregate", ""),
        "results": len(batch_result.results),
        "failures": len(getattr(batch_result, "failures", [])),
    }

    for gadget_id, points in curves.items():
        plot = _plot_data_uri(points, gadget_id) if config.simulation.plot else None
        lam = _lambda_factor(points) if config.simulation.lambda_factor else None
        # attach to the first (lowest-k, first radius/window) row of this gadget
        for row in report.rows:
            if row.gadget_id == gadget_id and row.k >= 0:
                if plot is not None and row.ler_plot is None:
                    row.ler_plot = plot
                if lam is not None and row.lambda_factor is None:
                    row.lambda_factor = lam
                break
    return report
