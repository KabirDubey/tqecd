# `experiment` — batched gadget experiments over `tqec.orchestration`

A developer tool for exercising `tqecd`'s detector annotation across a battery of gadgets. It is
a thin **consumer** of `tqec.orchestration`: it hands gadgets to `prepare_batch`, re-annotates
each prepared circuit with `tqecd`, and measures how well the annotation performs.

> The `welder` / `weld` terminology is reserved for a separate future tool. The core action here
> is `run_experiment(...)`, and the `tqecd`-reannotation step is `reannotate(...)`.

## Where it lives and why

This tool lives in `tools/experiment/`, **outside `src/tqecd`**. `tqecd` packages only `src/`, so
this tree is excluded from the `tqecd` wheel and adds **no** runtime dependency to `tqecd` — in
particular `src/tqecd/**` still imports no `tqec`. The optional `tqec` dependency (which provides
`tqec.orchestration`) is declared here in `pyproject.toml`, never in `tqecd` core.

## Three tiers of signal — and the "no ground truth" principle

For an arbitrary supplied gadget it may simply be **unknown** whether *any* detector annotation
reaches full distance, so the tool never assumes a `native`-match everywhere. It reports three
kinds of signal, kept distinct:

1. **Predictors** (`predictors.py`) — cheap, static objective functions on a single circuit:
   - `missing_parities`: GF(2) flow-completeness. Reduces the circuit's complete deterministic
     parity space (stim `flow_generators`, trivial in/out) against the emitted `DETECTOR` /
     `OBSERVABLE` subspace; a nonzero residual is a parity the annotator failed to weld.
   - `shortest_graphlike_error`: code distance of the noisy circuit, compared to `2k + 1`.
2. **Oracles** (`oracle.py`) — a known-correct reference that legitimately exists in *narrow*
   configurations. There it *is* ground truth, compared up to logical symmetry (same GF(2) parity
   span, not byte-equality). Ships with `NativeFixedBulkOracle`: `tqec`'s native annotation is
   correct for the `fixed_bulk` convention, so it is "oracled in" there. Pluggable — register more
   per convention/config without touching the core.
3. **Gold standard** (`simulate.py`, opt-in) — the LER-vs-p plot and Lambda (Λ) suppression
   factor confirming a fault-tolerant pseudothreshold and threshold. The authoritative signal.

*(Out of scope here: generating / locally resynthesizing different microscopic circuits with the
same macroscopic behavior to search for an annotation that reaches full distance.)*

## Usage

```bash
# smoke run on a gallery gadget
python -m tools.experiment --gallery cnot --k 1,2 --oracles native_fixed_bulk

# from a config
python -m tools.experiment --config tools/experiment/configs/manhattan_sensitivity.toml

# from a file
python -m tools.experiment --input my_gadget.dae --k 1,2,3
```

```python
from tools.experiment import run_experiment, ExperimentConfig
from tqec.gallery import cnot
from tqec.utils.enums import Basis

report = run_experiment([cnot(Basis.Z)],
                        ExperimentConfig(conventions=("fixed_bulk", "fixed_boundary"),
                                         ks=(1, 2, 3), oracles=("native_fixed_bulk",)),
                        "out")
print(report.to_text())          # also writes out/report.{json,html,txt} (+ report.csv)
```

## Outputs

`run_experiment` writes `report.json`, a self-contained `report.html` (inline CSS/JS, no CDN;
embedded LER plots as base64 when simulation runs), and `report.txt`. With `polars` installed it
also writes `report.csv`.

## Dependencies & branch floors

- Core: `stim`, `numpy` (+ `tqecd`, this checkout).
- Optional `tqec` (`orchestration` extra): must carry `tqec.orchestration` (branch
  `kd/dae-batch-processing`). Point `[tool.uv.sources].tqec` at your tqec working tree.
- Optional `analysis` (`polars`, `orjson`, `msgspec`) and `report` (`minijinja`, `matplotlib`)
  extras enhance data handling and the HTML report; the core runs without them.
- `tqecd` itself must carry the windowed detector completion (`window=`, branch
  `feat/yfragmentflow`) — this tool stacks on that branch.

## Tests

```bash
pytest tools/experiment/tests -q
```

The battery asserts ground-truth-free invariants — zero missing parities and distance `== 2k + 1`
for every prepared (READY) unit — never native-equality. Units `tqec` cannot yet compile (e.g.
spatial Hadamard on `fixed_bulk`) are recorded as non-ready and excluded, not failed.
