# `tools/experiment` -- workflow spec

This is the authoritative spec the experiment tool is built against: the desiderata, the stage
contract, and the explicit non-goals. It supersedes the prose in `usage.md` of the standalone
`gadgetTesting/` harness, which this tool is the orchestration-native successor to.

**Source of the desiderata:** the original harness workflow described in
`ytqec/gadgetTesting/usage.md`, plus the UX/visuals requirements captured in
`ytqec/mergeLogs/25Jul26_0906_gadget_experiment_visuals_and_ux.md`. Where this tool diverges from
`usage.md`, the divergence is deliberate and listed under *Non-goals* below.

## Purpose

Exercise `tqecd`'s detector annotation across a battery of gadgets and assert it is correct.
`tqec.orchestration` (#1008) owns splitting, compilation, and native circuit generation; this tool
is a downstream consumer that re-annotates the prepared circuits with `tqecd`, scores them against
absolute invariants (and, when configured, against alternate-annotator oracles), and reports.

## Ground-truth-free validation (core invariant)

A gadget **passes** when its `tqecd`-annotated circuit satisfies two absolute properties of the
circuit itself (no reference needed):

1. **`missing_parities == 0`** -- GF(2) flow-completeness: stim's full deterministic-parity space
   reduced against the annotator's emitted DETECTOR/OBSERVABLE subspace leaves no residual.
2. **`distance == 2k+1`** -- `shortest_graphlike_error` on the noisy circuit reaches the code
   distance. This is an analytic minimum-weight search over the detector error model; it does not
   sample, so it never invokes the simulator.

Oracles (when configured) add alternate annotators -- `native`, the windowless `tqecd_main`, or a
user-supplied one -- each scored on the same metric and checked for logical equivalence, shown in
per-oracle `[dist | equiv | stim]` column groups. They inform; they do not gate the pass verdict.

## Stages (the contract)

"Build the circuits once; re-measure and re-draw cheaply." Each stage reads the previous stage's
on-disk output and writes into the same run directory.

| stage | CLI | reads | does | writes |
| --- | --- | --- | --- | --- |
| run | `--gallery` / `--input` / `--config` | inputs | prepare_batch (compile) + re-annotate + score | full run dir + `report.*` |
| render | `--render <dir>` | `report.json` | rebuild the HTML/txt view only -- no tqec/tqecd code runs | `report.{html,txt}` |
| reannotate | `--reannotate <dir>` | `prepared/manifest.json` circuits | re-annotate with `tqecd` + re-score (no recompile) | `report.*` + fresh visuals |
| simulate | `--simulate <dir>` | `prepared/manifest.json` circuits + `report.json` | MCMC sampling: LER-vs-p under a noise model (no recompile) | `report.*` + `mcmc/` |

- **run** persists the full config to `config.json` so later stages recover it.
- **render** needs only `report.json` (rows already carry their `visuals`); it works even after the
  prepared circuits are cleaned.
- **reannotate** re-applies `--windows` / `--oracles`; `--k` / `--conventions` are baked into the
  prepared circuits and are ignored with a notice. Pointing `PYTHONPATH` at a different `tqecd`
  re-scores against that annotator on identical circuits.
- **simulate** re-measures under `--noise-models` / `--ps` on identical circuits, so a difference
  between two noise models is the noise model, not an accident of rebuilding.

## Config

TOML (`[experiment]` table), lowered to a `tqec.orchestration.BatchConfig`:
`name`, `inputs` (the gadgets to score), `conventions`, `ks`, `windows` (the tqecd knob under
test), `logical_observables`, `predictors` (`parities`, `distance`), `oracles`, `noise_models`,
`ps`, `expected_distance` (`2*k + 1`), `circuit_mode`, and an optional `[simulation]` block (MCMC).

## Report

One row per (gadget, convention, k, window). Every row records
`missing_parities`, `distance` vs `expected_distance`, `predictors_pass`, `runtime_s` (annotation +
analysis wall time), and per-row debugging artifacts. A gadget `tqec` cannot compile yet is a
non-ready row carried into the report, not a silent drop.

`report.html` is a single self-contained file whose columns follow the config: a name + timestamp
+ `config.toml` link header; Result / Gadget (with 3D + decorated-ZX subcolumns) / Observable /
predictor columns; a `[dist | equiv | stim]` column group per configured oracle; and, when MCMC
sampling ran, an MCMC section with a per-gadget LER-vs-p plot and a link to the sampling setup.
Every column is toggleable and the page fits the screen (the table scrolls internally); there is no
dropdown. Runtime totals/means are in the text footer.

The 3D block-graph viewer is written for every gadget, including pipeless single-cube ones (memory,
stability) that `tqec`'s `BlockGraph.from_json` rejects -- the tool loads them with a tolerant
fallback. The positioned ZX diagram is inlined for small graphs and, for graphs with more than 20
cubes, written to a PNG file and linked instead, so a large gadget never bloats the report.

## Outputs (run dir layout)

```
<out>/
  config.json / config.toml   full ExperimentConfig (json round-trips; toml is linked in the report)
  report.{json,html,txt}      json is authoritative; html is the human view
  logs/<DDMMMYY_HHMM>_*.log    one per stage invocation
  artifacts/<gadget>/...       block_graph.html, per-cell annotated.stim / detector_free.stim / oracle_*.stim
  mcmc/                        LER-vs-p plot PNGs + setup.txt (when MCMC sampling ran)
  prepared/                    prepared, noiseless circuits + manifest.json + graphs (from tqec)
```

All artifact paths are stored relative to the run dir, so a run folder is portable.

## Live documentation

`notebooks/workflow.py` is a marimo notebook that runs each stage interactively against a chosen
gadget -- the executable companion to this spec.

## Non-goals (deliberate divergences from `gadgetTesting/usage.md`)

- **Predictors are ground-truth-free** (the invariants above); no lightStim / stimflow annotators.
  Oracles are *optional* alternate-annotator comparisons (`native`, `tqecd_main`, or user-supplied),
  scored side by side but never gating the pass verdict.
- **No embedded stim circuit diagrams** (detector slices, match graphs, timeslice / timeline SVGs).
  They scaled to tens of megabytes per gadget and made the report unopenable; the circuit is
  inspected through the crumble link and the written `.stim` files, and structure through the
  positioned ZX diagram and 3D block-graph viewer.
- **No `selection` selectors** (`all` / `indices` / `last`). Inputs are listed directly via
  `--gallery` / `--input`; observable selection is `logical_observables`.
- **No compile-only stage.** `tqec.orchestration.prepare_batch` owns compilation; `run` invokes it
  and the other three stages reuse its on-disk output.
