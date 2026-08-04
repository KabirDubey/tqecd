# `tools/experiment` -- workflow spec

This is the authoritative spec the experiment tool is built against: the desiderata, the stage
contract, and the explicit non-goals. It supersedes the prose in `usage.md` of the standalone
`gadgetTesting/` harness, which this tool is the orchestration-native successor to.

**Source of the desiderata:** the original harness workflow described in
`ytqec/gadgetTesting/usage.md`, plus the UX/visuals requirements captured in
`ytqec/mergeLogs/25Jul26_0906_gadget_experiment_visuals_and_ux.md`. Where this tool diverges from
`usage.md`, the divergence is deliberate and listed under *Non-goals* below.

## Purpose

Exercise `tqecd`'s detector annotation across a battery of gadgets and assert it is correct --
without a gold standard. `tqec.orchestration` (#1008) owns splitting, compilation, and native
circuit generation; this tool is a pure downstream consumer that re-annotates the prepared
circuits with `tqecd`, scores them against absolute invariants, and reports.

## Ground-truth-free validation (core invariant)

A gadget **passes** when its `tqecd`-annotated circuit satisfies two absolute properties of the
circuit itself -- never a comparison to `native`:

1. **`missing_parities == 0`** -- GF(2) flow-completeness: stim's full deterministic-parity space
   reduced against the annotator's emitted DETECTOR/OBSERVABLE subspace leaves no residual.
2. **`distance == 2k+1`** -- `shortest_graphlike_error` on the noisy circuit reaches the code
   distance. This is an analytic minimum-weight search over the detector error model; it does not
   sample, so it never invokes the simulator.

`native_missing` is reported alongside as a non-authoritative reference column, never asserted.

## Stages (the contract)

"Build the circuits once; re-measure and re-draw cheaply." Each stage reads the previous stage's
on-disk output and writes into the same run directory.

| stage | CLI | reads | does | writes |
| --- | --- | --- | --- | --- |
| run | `--gallery` / `--input` / `--config` | inputs | prepare_batch (compile) + re-annotate + score | full run dir + `report.*` |
| render | `--render <dir>` | `report.json` | rebuild the HTML/txt/csv view only -- no tqec/tqecd code runs | `report.{html,txt,csv}` |
| reannotate | `--reannotate <dir>` | `mr*/manifest.json` circuits | re-annotate with `tqecd` + re-score (no recompile) | `report.*` + fresh visuals |
| simulate | `--simulate <dir>` | `mr*/manifest.json` circuits + `report.json` | measure LER-vs-p under a noise model (no recompile) | `report.*` + LER plots |

- **run** persists the full config to `config.json` so later stages recover it.
- **render** needs only `report.json` (rows already carry their `visuals`); it works even after the
  prepared circuits are cleaned.
- **reannotate** re-applies `--windows` / `--oracles`; `--k` / `--conventions` /
  `--manhattan-radii` are baked into the prepared circuits and are ignored with a notice. Pointing
  `PYTHONPATH` at a different `tqecd` re-scores against that annotator on identical circuits.
- **simulate** re-measures under `--noise-models` / `--ps` on identical circuits, so a difference
  between two noise models is the noise model, not an accident of rebuilding.

## Config

TOML (`[experiment]` table), lowered to a `tqec.orchestration.BatchConfig` per Manhattan radius:
`conventions`, `ks`, `windows` (the tqecd knob under test), `manhattan_radii`,
`logical_observables`, `predictors` (`parities`, `distance`), `oracles`, `noise_models`, `ps`,
`expected_distance` (`2*k + 1`), `circuit_mode`, and an optional `[simulation]` block.

## Report

One row per (gadget, convention, k, Manhattan radius, window). Every row records
`missing_parities`, `distance` vs `expected_distance`, `predictors_pass`, `runtime_s` (annotation +
analysis wall time), and per-row debugging artifacts. A gadget `tqec` cannot compile yet is a
non-ready row carried into the report, not a silent drop.

`report.html` is a single self-contained file: compact default table, always-visible external
links (crumble / annotated stim / 3D block graph), per-row expandable details (notes, oracle
results, positioned-ZX + block-graph pictures, circuit and detector-free links, LER plot),
selectable columns (incl. runtime), accessible sortable headers, and result/text filters. Runtime
totals/means are summarized in the text footer.

The 3D block-graph viewer is written for every gadget, including pipeless single-cube ones (memory,
stability) that `tqec`'s `BlockGraph.from_json` rejects -- the tool loads them with a tolerant
fallback. The positioned ZX diagram is inlined for small graphs and, for graphs with more than 20
cubes, written to a PNG file and linked instead, so a large gadget never bloats the report.

## Outputs (run dir layout)

```
<out>/
  config.json                 full ExperimentConfig (lets render/reannotate/simulate recover it)
  report.{json,html,txt,csv}  json is authoritative; html is the human view
  logs/<DDMMMYY_HHMM>_*.log    one per stage invocation
  artifacts/<gadget>/...       block_graph.html, per-cell annotated.stim / detector_free.stim
  mr<radius>/                  prepared, noiseless circuits + manifest.json + graphs (from tqec)
```

All artifact paths are stored relative to the run dir, so a run folder is portable.

## Live documentation

`notebooks/workflow.py` is a marimo notebook that runs each stage interactively against a chosen
gadget -- the executable companion to this spec.

## Non-goals (deliberate divergences from `gadgetTesting/usage.md`)

- **No `native` / lightStim / stimflow gold-standard comparison.** Validation is ground-truth-free
  (invariants above); `native_missing` is shown only as a reference.
- **No embedded stim circuit diagrams** (detector slices, match graphs, timeslice / timeline SVGs).
  They scaled to tens of megabytes per gadget and made the report unopenable; the circuit is
  inspected through the crumble link and the written `.stim` files, and structure through the
  positioned ZX diagram and 3D block-graph viewer.
- **No `selection` selectors** (`all` / `indices` / `last`). Inputs are listed directly via
  `--gallery` / `--input`; observable selection is `logical_observables`.
- **No compile-only stage.** `tqec.orchestration.prepare_batch` owns compilation; `run` invokes it
  and the other three stages reuse its on-disk output.
