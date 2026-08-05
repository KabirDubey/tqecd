"""``experiment``--run batched experiments over gadgets using ``tqec.orchestration``.

A developer tool (living outside ``src/tqecd``, so ``tqecd`` itself never depends on ``tqec``):
it hands gadgets to ``tqec.orchestration.prepare_batch``, re-annotates each prepared circuit with
``tqecd``, and measures ground-truth-free predictors (plus reference oracles where valid, and an
optional gold-standard LER/Lambda mode).

Importing this package isolates ``tqec``'s detector-database cache (see :func:`_isolate_detector_db`).
"""

import os as _os
from pathlib import Path as _Path


def _isolate_detector_db() -> None:
    """Point ``tqec`` at a tester-owned detector-database cache, isolated from the shared one.

    ``tqec`` caches computed detectors in a single machine-wide pickle
    (``TQEC_DETECTOR_DATABASE_PATH``, default ``~/.../TQEC/detector_database.pkl``) shared by every
    ``tqec`` checkout on the machine. Different versions pickle incompatible class layouts, so a
    cache written by one version makes another quarantine it with an ``AttributeError`` warning
    (harmless--it only caches native detector computation, never the ``tqecd`` reannotation under
    test--but noisy). Redirecting the tester to its own path keeps its cache warm and conflict-free.

    Set as an import side effect so it lands before ``tqec`` is first imported; only sets the
    variable when the user has not already chosen one (``setdefault``).
    """
    default = _Path.home() / ".cache" / "tqec-experiment" / "detector_database.pkl"
    if _os.environ.setdefault("TQEC_DETECTOR_DATABASE_PATH", str(default)) == str(default):
        default.parent.mkdir(parents=True, exist_ok=True)


_isolate_detector_db()

from tools.experiment.config import ExperimentConfig, SimulationConfig
from tools.experiment.core import (
    reannotate_run,
    render_report,
    run_experiment,
    simulate_run,
)
from tools.experiment.report import ExperimentReport, ExperimentRow

__all__ = [
    "ExperimentConfig",
    "SimulationConfig",
    "ExperimentReport",
    "ExperimentRow",
    "reannotate_run",
    "render_report",
    "run_experiment",
    "simulate_run",
]
