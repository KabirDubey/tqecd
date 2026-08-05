"""MCMC sampling: logical-error-rate-vs-p curves and Lambda (Λ) suppression factors.

This is the Monte-Carlo (``sinter``) sampling stage: it applies noise to the prepared circuits and
runs one flattened ``sinter.collect`` (via ``tqec.orchestration.simulate_batch``). It is opt-in and
slow, so it lives outside the core loop. Results are written under ``<out>/mcmc/`` -- a ``setup.txt``
describing the sampling plus, when ``simulation.plot`` is set, one LER-vs-p plot PNG per gadget --
and summarised in ``report.meta["mcmc"]`` so the report can show an MCMC section (a row per gadget
with links to its plot and to the sampling setup).
"""

from __future__ import annotations

import io
import os
from collections import defaultdict
from pathlib import Path
from typing import Any

from tools.experiment.config import ExperimentConfig
from tools.experiment.report import ExperimentReport


def _ler(result: Any) -> float | None:
    if result.shots <= result.discards:
        return None
    return result.errors / (result.shots - result.discards)


def _plot_png(points: dict[int, list[tuple[float, float]]], title: str) -> bytes | None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ModuleNotFoundError:  # pragma: no cover
        return None
    fig, ax = plt.subplots(figsize=(4.5, 3.2), dpi=120)
    for k in sorted(points):
        pts = sorted(points[k])
        ax.plot([p for p, _ in pts], [ler for _, ler in pts], marker="o", label=f"k={k}")
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
    return buffer.getvalue()


def _lambda_factor(points: dict[int, list[tuple[float, float]]]) -> float | None:
    """Λ ≈ LER(d) / LER(d+2) at the largest common p, from the two largest available k."""
    ks = sorted(points)
    if len(ks) < 2:
        return None
    low, high = ks[-2], ks[-1]
    low_map, high_map = dict(points[low]), dict(points[high])
    shared = sorted(set(low_map) & set(high_map))
    if not shared:
        return None
    p = shared[-1]
    if high_map[p] <= 0:
        return None
    return low_map[p] / high_map[p]


def _write_setup(config: ExperimentConfig, mcmc_dir: Path, out_dir: Path, batch_result: Any) -> str:
    """Write a human-readable MCMC-sampling setup file and return its run-relative path."""
    sim = config.simulation
    lines = [
        "MCMC sampling setup",
        "===================",
        f"noise models: {', '.join(sim.noise_models)}",
        f"physical error rates p: {', '.join(str(p) for p in sim.ps)}",
        f"max shots per case: {sim.max_shots}",
        f"max errors per case: {sim.max_errors}",
        f"decoders: {', '.join(sim.decoders)}",
        f"aggregate outcome: {getattr(batch_result, 'aggregate', '')}",
        f"sampled cases: {len(batch_result.results)}",
    ]
    mcmc_dir.mkdir(parents=True, exist_ok=True)
    path = mcmc_dir / "setup.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return os.path.relpath(path, out_dir)


def augment(
    report: ExperimentReport, manifest: Any, config: ExperimentConfig, out_dir: str | Path
) -> ExperimentReport:
    """Run ``simulate_batch`` and record the MCMC results in ``report.meta["mcmc"]``.

    Writes a sampling setup file and, when ``simulation.plot`` is set, one LER-vs-p plot PNG per
    ``(gadget, convention)`` under ``<out_dir>/mcmc/``; the report renders these as an MCMC section
    (a row per gadget with links to its plot and to the setup). The LER is independent of the tqecd
    window, so one curve set is produced per ``(gadget, convention)``.
    """
    from tqec.orchestration import simulate_batch

    out_dir = Path(out_dir)
    mcmc_dir = out_dir / "mcmc"
    batch_result = simulate_batch(manifest)

    curves: dict[tuple[str, str], dict[int, list[tuple[float, float]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for unit_result in batch_result.results:
        ler = _ler(unit_result)
        if ler is None:
            continue
        curves[(unit_result.gadget_id, unit_result.convention)][unit_result.k].append(
            (unit_result.p, ler)
        )

    setup_rel = _write_setup(config, mcmc_dir, out_dir, batch_result)
    gadgets: list[dict[str, Any]] = []
    for (gadget_id, convention), points in sorted(curves.items()):
        plot_rel = None
        if config.simulation.plot:
            png = _plot_png(points, f"{gadget_id} [{convention}]")
            if png:
                path = mcmc_dir / f"ler_{gadget_id}_{convention}.png"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(png)
                plot_rel = os.path.relpath(path, out_dir)
        gadgets.append(
            {
                "gadget_id": gadget_id,
                "convention": convention,
                "plot": plot_rel,
                "lambda": _lambda_factor(points) if config.simulation.lambda_factor else None,
            }
        )

    report.meta["mcmc"] = {
        "enabled": True,
        "aggregate": getattr(batch_result, "aggregate", ""),
        "results": len(batch_result.results),
        "setup": setup_rel,
        "gadgets": gadgets,
    }
    return report
