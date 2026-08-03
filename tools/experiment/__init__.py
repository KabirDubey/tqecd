"""``experiment``--run batched experiments over gadgets using ``tqec.orchestration``.

A developer tool (living outside ``src/tqecd``, so ``tqecd`` itself never depends on ``tqec``):
it hands gadgets to ``tqec.orchestration.prepare_batch``, re-annotates each prepared circuit with
``tqecd``, and measures ground-truth-free predictors (plus reference oracles where valid, and an
optional gold-standard LER/Lambda mode).
"""

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
