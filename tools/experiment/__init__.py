"""``experiment``--run batched experiments over gadgets using ``tqec.orchestration``.

A developer tool that hands gadgets to ``tqec.orchestration.prepare_batch``, re-annotates each
prepared circuit with ``tqecd``, and measures predictors (missing parities, distance) plus, when
configured, alternate-annotator oracles and an opt-in MCMC-sampling (LER-vs-p + Lambda) stage.

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
    if _os.environ.setdefault("TQEC_DETECTOR_DATABASE_PATH", str(default)) == str(
        default
    ):
        default.parent.mkdir(parents=True, exist_ok=True)


_isolate_detector_db()

from tools.experiment.check import (  # noqa: E402
    CircuitCheck,
    CircuitComparison,
    apply_noise,
    check_circuit,
    compare_circuits,
)
from tools.experiment.config import ExperimentConfig, SimulationConfig  # noqa: E402
from tools.experiment.core import (  # noqa: E402
    reannotate_run,
    render_report,
    run_experiment,
    simulate_run,
)
from tools.experiment.report import ExperimentReport, ExperimentRow  # noqa: E402

__all__ = [
    "CircuitCheck",
    "CircuitComparison",
    "apply_noise",
    "check_circuit",
    "compare_circuits",
    "ExperimentConfig",
    "SimulationConfig",
    "ExperimentReport",
    "ExperimentRow",
    "reannotate_run",
    "render_report",
    "run_experiment",
    "simulate_run",
]
