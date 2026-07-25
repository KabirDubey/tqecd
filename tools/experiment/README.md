# `experiment` -- batched gadget experiments over `tqec.orchestration`

A developer tool for exercising `tqecd`'s detector annotation across a battery of gadgets. It
consumes `tqec.orchestration.prepare_batch`, re-annotates each prepared circuit with `tqecd`, and
measures how well the annotation performs.

It lives in `tools/experiment/`, **outside `src/tqecd`**, so it adds no dependency to `tqecd`
itself: `tqecd` packages only `src/`, and the optional `tqec` dependency is declared here, never in
`tqecd` core.

## Quick start

```bash
python -m tools.experiment --gallery cnot --k 1,2      # one gadget
python -m tools.experiment --gallery all --k 1,2       # every gadget in tqec.gallery
python -m tools.experiment --config tools/experiment/configs/manhattan_sensitivity.toml
```

```python
from tools.experiment import run_experiment, ExperimentConfig
from tqec.gallery import cnot
from tqec.utils.enums import Basis

report = run_experiment([cnot(Basis.Z)], ExperimentConfig(ks=(1, 2)), "out")
print(report.to_text())   # also writes out/report.{json,html,txt} (+ report.csv with polars)
```

## Signals (no ground truth by default)

- **Predictors** (always): `missing_parities` (GF(2) flow-completeness) and
  `shortest_graphlike_error` vs `2k+1` -- absolute properties of a single circuit.
- **Oracles** (optional): user-supplied reference annotations, compared up to logical symmetry.
  None ship by default -- `tqec`'s native annotation is not a reliable reference for most gadgets.
- **Simulation** (opt-in): LER-vs-p plots and Lambda factors via `simulate_batch`.

## Documentation

Full usage and configuration reference:

- Workflow: [`docs/user_guide/experiment_workflow.rst`](../../docs/user_guide/experiment_workflow.rst)
- Configuration: [`docs/user_guide/experiment_configuration.rst`](../../docs/user_guide/experiment_configuration.rst)

## Tests

```bash
pytest tools/experiment/tests -q
```

The battery checks absolute invariants -- zero missing parities and distance `== 2k+1` for every
prepared (READY) unit -- never native-equality. Units `tqec` cannot compile yet are recorded
non-ready, not failed.
