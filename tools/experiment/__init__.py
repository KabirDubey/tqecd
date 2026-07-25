"""``experiment`` -- run batched experiments over gadgets using ``tqec.orchestration``.

A developer tool (living outside ``src/tqecd``, so ``tqecd`` itself never depends on ``tqec``):
it hands gadgets to ``tqec.orchestration.prepare_batch``, re-annotates each prepared circuit with
``tqecd``, and measures ground-truth-free predictors (plus reference oracles where valid, and an
optional gold-standard LER/Lambda mode).

The ``welder`` / ``weld`` name is reserved for a separate future tool.
"""

from tools.experiment.config import ExperimentConfig, SimulationConfig
from tools.experiment.core import run_experiment
from tools.experiment.report import ExperimentReport, ExperimentRow

__all__ = [
    "ExperimentConfig",
    "SimulationConfig",
    "ExperimentReport",
    "ExperimentRow",
    "run_experiment",
]
