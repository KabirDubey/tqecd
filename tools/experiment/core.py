"""``run_experiment``: drive ``prepare_batch``, re-annotate, score, and render a report.

This is the only module (besides :mod:`tools.experiment.simulate`) that imports ``tqec``. It is a
pure downstream consumer of ``tqec.orchestration``: ``prepare_batch`` does the splitting,
compilation and native circuit generation; this loop reads the circuits off disk, re-annotates them
with ``tqecd``, measures predictors and oracles, writes debugging artifacts (circuits, crumble
links, stim diagrams, structure pictures), logs progress, and prints a console summary.
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import stim

from tools.experiment import annotators, predictors, runlog, visuals
from tools.experiment.config import ExperimentConfig
from tools.experiment.report import (
    NOT_SCORED,
    PASS,
    PREDICTOR_FAIL,
    PREP_FAIL,
    ExperimentReport,
    ExperimentRow,
)


def _expected_distance(expr: str, k: int) -> int:
    return int(eval(expr, {"__builtins__": {}}, {"k": k}))


def _noisy(circuit: stim.Circuit, noise_model: str, p: float) -> stim.Circuit:
    from tqec.utils.noise_model import NoiseModel

    factory = getattr(NoiseModel, noise_model, None)
    if factory is None:
        factory = NoiseModel.uniform_depolarizing
    return factory(p).noisy_circuit(circuit)


def _observable_label(unit: Any) -> str:
    """The simulated observable(s) as a compact string of external stabilizers (item 4)."""
    observables = getattr(unit, "logical_observables", ()) or ()
    return ", ".join(o.external_stabilizer for o in observables)


def _failure_reason(row: ExperimentRow) -> str:
    """A one-line reason a scored row failed its predictors, for the report's Notes column."""
    reasons: list[str] = []
    if row.parities_ok is False and row.missing_parities is not None:
        plural = "y" if row.missing_parities == 1 else "ies"
        reasons.append(f"{row.missing_parities} missing parit{plural}")
    if row.distance_ok is False:
        reasons.append(f"distance {row.distance} != expected {row.expected_distance}")
    return "; ".join(reasons)


def _status_kind(unit_status: str, predictors_pass: bool | None) -> str:
    """Classify a row for the report's distinct visual states."""
    if unit_status != "ready":
        return NOT_SCORED if unit_status == "skipped" else PREP_FAIL
    if predictors_pass is True:
        return PASS
    if predictors_pass is False:
        return PREDICTOR_FAIL
    return NOT_SCORED


def _score(
    native: stim.Circuit,
    reannotated: stim.Circuit,
    unit: Any,
    k: int,
    window: int,
    config: ExperimentConfig,
) -> ExperimentRow:
    row = ExperimentRow(
        gadget_id=unit.gadget_id,
        source=getattr(unit, "source", ""),
        name=getattr(unit, "name", ""),
        convention=unit.convention,
        k=k,
        window=window,
        status=unit.status,
        observable=_observable_label(unit),
    )

    if config.run_parities:
        row.missing_parities = predictors.count_missing_parities(reannotated)
        row.parities_ok = row.missing_parities == 0

    if config.run_distance:
        row.expected_distance = _expected_distance(config.expected_distance, k)
        noisy = _noisy(reannotated, config.noise_models[0], config.ps[0])
        row.distance = predictors.shortest_graphlike_error(noisy)
        row.distance_ok = row.distance == row.expected_distance

    checks = [ok for ok in (row.parities_ok, row.distance_ok) if ok is not None]
    row.predictors_pass = all(checks) if checks else None
    row.status_kind = _status_kind(unit.status, row.predictors_pass)
    if row.predictors_pass is False:
        row.notes = _failure_reason(row)

    return row


def _score_oracles(
    row: ExperimentRow,
    reannotated: stim.Circuit,
    unit: Any,
    k: int,
    native: stim.Circuit,
    config: ExperimentConfig,
    oracles: Sequence[Any],
    artifacts: Path,
    out_dir: Path,
) -> None:
    """Score every applicable oracle as an alternate annotator, side by side with the experimental.

    Each oracle produces an alternate annotation; it is scored on the *same* metric (distance vs
    ``2k+1`` and missing parities), checked for logical equivalence to the experimental circuit,
    and its ``.stim`` written for a report link. Results land in ``row.oracle_results[name]``.
    """
    from tools.experiment.oracle import logically_equivalent

    for oracle in oracles:
        if not oracle.applies(unit, config):
            continue
        name = oracle.name
        try:
            circuit = oracle.annotate(unit, k, native)
        except Exception as exc:  # a missing worktree / subprocess failure is recorded, not fatal
            row.oracle_results[name] = {"error": str(exc)[:200]}
            continue
        res: dict[str, Any] = {"equivalent": logically_equivalent(reannotated, circuit)}
        if config.run_parities:
            res["missing_parities"] = predictors.count_missing_parities(circuit)
        if config.run_distance:
            noisy = _noisy(circuit, config.noise_models[0], config.ps[0])
            distance = predictors.shortest_graphlike_error(noisy)
            res["distance"] = distance
            res["distance_ok"] = distance == row.expected_distance
        cell = artifacts / row.gadget_id / f"{row.convention}_k{row.k}_w{row.window}"
        try:
            path = visuals.write_circuit(circuit, cell / f"oracle_{name}.stim")
            res["stim"] = _relpath(path, out_dir)
        except Exception:
            pass
        row.oracle_results[name] = res


def _prep_row(unit: Any) -> ExperimentRow:
    status = unit.status
    return ExperimentRow(
        gadget_id=unit.gadget_id,
        source=getattr(unit, "source", ""),
        name=getattr(unit, "name", ""),
        convention=unit.convention,
        k=-1,
        window=-1,
        status=status,
        status_kind=_status_kind(status, None),
        notes=getattr(unit, "error", "") or getattr(unit, "notes", ""),
    )


def _relpath(path: Path, out_dir: Path) -> str:
    return os.path.relpath(path, out_dir)


def _select_observable_surface(graph: Any, unit: Any) -> Any:
    """Pick the correlation surface of the observable this unit simulates (else the first).

    ``prepare_batch`` records each simulated observable's external stabilizer on the unit; this
    matches it back to a live ``CorrelationSurface`` so the ZX and 3D pictures decorate the *same*
    observable that is being scored, not an arbitrary one.
    """
    try:
        surfaces = graph.find_correlation_surfaces()
    except Exception:
        return None
    if not surfaces:
        return None
    observables = getattr(unit, "logical_observables", ()) or ()
    wanted = getattr(observables[0], "external_stabilizer", "") if observables else ""
    if wanted:
        for surface in surfaces:
            try:
                if surface.external_stabilizer_on_graph(graph) == wanted:
                    return surface
            except Exception:
                continue
    return surfaces[0]


def _ensure_gadget_visuals(
    unit: Any,
    manifest: Any,
    gadget_visuals: dict[str, dict[str, Any]],
    artifacts: Path,
    out_dir: Path,
    log,
) -> None:
    """Compute the per-gadget structure pictures once (positioned ZX + 3D block graph).

    Both pictures are decorated with the correlation surface of the observable being simulated:
    the ZX diagram overlays its Pauli web, and the 3D block graph shows the surface with its ``-Y``
    faces popped so it is visible inside the model.
    """
    gid = unit.gadget_id
    if gid in gadget_visuals or not getattr(unit, "graph", None):
        return
    gadget_visuals[gid] = {}
    graph = visuals.load_block_graph(manifest.run_dir / unit.graph, graph_name=gid)
    if graph is None:
        log.info("gadget visuals: could not load graph for %s", gid)
        return
    surface = _select_observable_surface(graph, unit)
    # Positioned ZX: inline for small graphs, linked to a PNG file for large ones so a big gadget
    # never bloats the single-file report.
    try:
        n_nodes = len(list(graph.cubes))
    except Exception:
        n_nodes = 0
    if n_nodes > visuals.ZX_INLINE_MAX_NODES:
        written_zx = visuals.write_positioned_zx_png(
            graph, artifacts / gid / "positioned_zx.png", title=gid, surface=surface
        )
        if written_zx:
            gadget_visuals[gid]["zx_link"] = _relpath(written_zx, out_dir)
    else:
        zx = visuals.positioned_zx_png_data_uri(graph, title=gid, surface=surface)
        if zx:
            gadget_visuals[gid]["zx_png"] = zx
    # The 3D block-graph viewer is written for every gadget (including pipeless single-cube ones),
    # so the report's 3D link is never missing.
    bg_path = artifacts / gid / "block_graph.html"
    written = visuals.write_block_graph_html(
        graph, bg_path, correlation_surface=surface
    )
    if written:
        gadget_visuals[gid]["block_graph_html"] = _relpath(written, out_dir)


def _attach_visuals(
    row: ExperimentRow,
    native: stim.Circuit,
    reannotated: stim.Circuit,
    artifacts: Path,
    out_dir: Path,
) -> None:
    """Write per-row circuit artifacts (crumble link + ``.stim`` files) onto ``row.visuals``.

    Stim's embedded circuit diagrams are no longer produced; the circuit is inspected through the
    crumble link and the written ``.stim`` files instead.
    """
    cell = artifacts / row.gadget_id / f"{row.convention}_k{row.k}_w{row.window}"
    v: dict[str, Any] = {}
    try:
        v["crumble"] = visuals.crumble_url(reannotated)
        v["circuit"] = _relpath(
            visuals.write_circuit(reannotated, cell / "annotated.stim"), out_dir
        )
        detector_free = annotators.strip_annotations(native)
        v["detector_free"] = _relpath(
            visuals.write_circuit(detector_free, cell / "detector_free.stim"), out_dir
        )
    except Exception:
        pass
    row.visuals = v


def _write_config(config: ExperimentConfig, out_dir: Path) -> None:
    """Persist the full config (JSON for round-trip; TOML linked at the top of the report)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "config.json").write_text(
        json.dumps(config.to_dict(), indent=2), encoding="utf-8"
    )
    (out_dir / "config.toml").write_text(config.to_toml(), encoding="utf-8")


def _load_config(run_dir: Path) -> ExperimentConfig:
    """Recover a previous run's config: ``config.json`` first, then the ``report.json`` meta."""
    cfg_path = run_dir / "config.json"
    if cfg_path.is_file():
        return ExperimentConfig.from_dict(json.loads(cfg_path.read_text()))
    report_path = run_dir / "report.json"
    if report_path.is_file():
        meta = json.loads(report_path.read_text()).get("meta", {})
        return ExperimentConfig.from_dict(meta)
    return ExperimentConfig()


def _discover_manifests(run_dir: Path) -> list[Any]:
    """Load the run's prepared ``prepared/manifest.json`` (tolerating legacy ``mr*/`` run dirs)."""
    from tqec.orchestration import BatchManifest

    prepared = run_dir / "prepared" / "manifest.json"
    if prepared.is_file():
        return [BatchManifest.read(prepared)]
    found: list[Any] = []
    for mdir in sorted(run_dir.glob("mr*")):
        manifest_path = mdir / "manifest.json"
        if manifest_path.is_file():
            found.append(BatchManifest.read(manifest_path))
    return found


def _score_and_render(
    manifests: Sequence[Any],
    config: ExperimentConfig,
    out_dir: Path,
    *,
    oracles: Sequence[Any],
    show_progress: bool,
    log: Any,
    log_path: Path,
) -> ExperimentReport:
    """Score already-prepared manifests, attach visuals, and write the report.

    Shared by :func:`run_experiment` (which prepares the manifests first) and
    :func:`render_report` (which loads them off disk). This never calls ``prepare_batch``, so no
    circuits are recompiled here--only re-annotated with ``tqecd``, scored, and rendered.
    """
    artifacts = out_dir / "artifacts"
    gadget_visuals: dict[str, dict[str, Any]] = {}
    rows: list[ExperimentRow] = []
    work: list[tuple[Any, int, stim.Circuit, int]] = []
    last_manifest = None

    for manifest in manifests:
        last_manifest = manifest
        for unit in manifest.units:
            _ensure_gadget_visuals(
                unit, manifest, gadget_visuals, artifacts, out_dir, log
            )
            if unit.status != "ready" or not unit.circuits:
                rows.append(_prep_row(unit))
                log.info(
                    "prep %s [%s] status=%s",
                    unit.gadget_id,
                    unit.convention,
                    unit.status,
                )
                continue
            for k, rel in unit.circuits.items():
                native = stim.Circuit.from_file(manifest.run_dir / rel)
                for window in config.windows:
                    work.append((unit, k, native, window))

    iterator: Any = work
    if show_progress:
        try:
            from tqdm import tqdm

            iterator = tqdm(work, desc="scoring rows", unit="row")
        except Exception:
            iterator = work

    for unit, k, native, window in iterator:
        started = time.perf_counter()
        reannotated = annotators.reannotate(native, window=window)
        row = _score(native, reannotated, unit, k, window, config)
        row.runtime_s = time.perf_counter() - started
        _score_oracles(row, reannotated, unit, k, native, config, oracles, artifacts, out_dir)
        _attach_visuals(row, native, reannotated, artifacts, out_dir)
        rows.append(row)
        log.info(
            "score %s [%s] k=%s w=%s missing=%s dist=%s pass=%s",
            unit.gadget_id,
            unit.convention,
            k,
            window,
            row.missing_parities,
            row.distance,
            row.predictors_pass,
        )

    report = ExperimentReport(
        rows=rows,
        gadget_visuals=gadget_visuals,
        meta={
            "name": config.name,
            "timestamp": runlog.pretty_now(),
            "config": "config.toml" if (out_dir / "config.toml").is_file() else "",
            "conventions": list(config.conventions),
            "ks": list(config.ks),
            "windows": list(config.windows),
            "predictors": list(config.predictors),
            "oracles": [getattr(o, "name", str(o)) for o in oracles],
            "simulation_enabled": config.simulation.enabled,
            "log": _relpath(log_path, out_dir),
        },
    )

    if config.simulation.enabled and last_manifest is not None:
        from tools.experiment import simulate

        simulate.augment(report, last_manifest, config, out_dir)

    report.write(out_dir)
    log.info("wrote report to %s", out_dir)
    if show_progress:
        _print_console_summary(report, out_dir, log_path)
    return report


def run_experiment(
    inputs: Sequence[str | Path | Any],
    config: ExperimentConfig,
    out_dir: str | Path,
    *,
    oracles: Sequence[Any] = (),
    show_progress: bool = True,
) -> ExperimentReport:
    """Run a batched gadget experiment and write ``report.{json,html,txt,csv}`` under ``out_dir``.

    Args:
        inputs: a mix of ``.dae`` / ``.bgraph`` paths and in-memory ``BlockGraph`` objects, passed
            straight to ``tqec.orchestration.prepare_batch``.
        config: experiment knobs (conventions, ks, windows, predictors, oracles).
        out_dir: directory for the run artifacts and the report.
        oracles: optional user-supplied reference oracles (objects), compared up to logical
            symmetry; merged with any registered by name in ``config.oracles``. Ground truth is
            opt-in and often absent, so this defaults to empty.
        show_progress: draw a per-row progress bar and print a console summary at the end.

    Returns:
        The :class:`ExperimentReport` (already written to disk). The full config is also written to
        ``out_dir/config.json`` so :func:`render_report` can re-render the run from disk.
    """
    from tqec.orchestration import prepare_batch

    out_dir = Path(out_dir)
    if not inputs and config.inputs:
        from tools.experiment import gadgets

        inputs = gadgets.resolve_inputs(config.inputs)  # the config defines its own inputs
    log, log_path = runlog.make_logger(out_dir)
    log.info(
        "start: conventions=%s ks=%s windows=%s inputs=%d",
        config.conventions,
        config.ks,
        config.windows,
        len(inputs),
    )
    _write_config(config, out_dir)

    active_oracles = [*oracles, *config.enabled_oracles()]
    log.info("prepare_batch")
    manifest = prepare_batch(inputs, config.to_batch_config(), out_dir / "prepared")

    return _score_and_render(
        [manifest],
        config,
        out_dir,
        oracles=active_oracles,
        show_progress=show_progress,
        log=log,
        log_path=log_path,
    )


def reannotate_run(
    run_dir: str | Path,
    *,
    overrides: dict[str, Any] | None = None,
    oracles: Sequence[Any] = (),
    show_progress: bool = True,
) -> ExperimentReport:
    """Re-annotate and re-score a run from its on-disk circuits--no recompile.

    ``run_dir`` is an experiment output directory that still holds its ``prepared/manifest.json``
    and the circuits and graphs they reference. The native circuits are read off disk, re-annotated
    with ``tqecd``, scored, and written back out with fresh visuals and a fresh report. Use it to
    re-score with a different ``tqecd`` matching window / ``oracles`` / predictor selection, or
    against a different ``tqecd`` on the ``PYTHONPATH``, without paying for a recompile. To rebuild
    only the ``report.html`` UI from an existing ``report.json`` (no annotation), use
    :func:`render_report`.

    Args:
        run_dir: a prior run directory (the ``--out`` of an earlier run).
        overrides: config fields to override before re-scoring. Only knobs that do not require
            recompilation take effect (``windows``, ``predictors``, ``oracles``, ``noise_models``,
            ``ps``, ``expected_distance``, ``simulation``); ``ks`` / ``conventions`` /
            ``logical_observables`` are baked into the prepared circuits and are read back from the
            manifests on disk.
        oracles: extra reference oracles, as in :func:`run_experiment`.
        show_progress: draw the progress bar and print the console summary.

    Returns:
        The re-scored :class:`ExperimentReport` (already written back into ``run_dir``).
    """
    run_dir = Path(run_dir)
    if not run_dir.is_dir():
        raise FileNotFoundError(f"reannotate: {run_dir} is not a directory")

    config = _load_config(run_dir)
    if overrides:
        config = config.with_overrides(**overrides)

    manifests = _discover_manifests(run_dir)
    if not manifests:
        raise FileNotFoundError(
            f"reannotate: no prepared circuits under {run_dir} (expected prepared/manifest.json). "
            "This run's circuits were cleaned up; re-run the experiment to regenerate them."
        )

    log, log_path = runlog.make_logger(run_dir, name="reannotate")
    log.info(
        "reannotate: run_dir=%s windows=%s predictors=%s",
        run_dir,
        config.windows,
        config.predictors,
    )
    active_oracles = [*oracles, *config.enabled_oracles()]
    return _score_and_render(
        manifests,
        config,
        run_dir,
        oracles=active_oracles,
        show_progress=show_progress,
        log=log,
        log_path=log_path,
    )


def render_report(run_dir: str | Path) -> ExperimentReport:
    """Rebuild ``report.html`` (and ``report.txt`` / ``report.csv``) from an existing report--UI only.

    This reads the run's ``report.json`` and re-renders it through the current report UI. No
    circuits are read, no annotation runs, and no scores change: it is a pure view rebuild for
    refreshing the HTML after the report/visuals code changed. It runs no ``tqec`` or ``tqecd``
    code and needs nothing but ``report.json`` (the artifacts it links to should still be on disk
    for the file links to resolve, but the embedded pictures render regardless). To re-annotate
    and re-score from prepared circuits instead, use :func:`reannotate_run`.

    Args:
        run_dir: a prior run directory, or the path to its ``report.json`` directly.

    Returns:
        The rebuilt :class:`ExperimentReport` (already written back next to ``report.json``).
    """
    path = Path(run_dir)
    report_path = path / "report.json" if path.is_dir() else path
    if not report_path.is_file():
        raise FileNotFoundError(f"render: no report.json found at {report_path}")
    report = ExperimentReport.from_json(report_path)
    report.write(report_path.parent)
    return report


def simulate_run(
    run_dir: str | Path,
    *,
    noise_models: Sequence[str] | None = None,
    ps: Sequence[float] | None = None,
    plot: bool = True,
    lambda_factor: bool = False,
    show_progress: bool = True,
) -> ExperimentReport:
    """Measure an existing run's prepared circuits under a (possibly different) noise model.

    Reads the run's prepared ``prepared/manifest.json`` circuits and its ``report.json``, applies noise
    with ``tqec.orchestration.simulate_batch`` (one flattened ``sinter.collect``), and attaches
    LER-vs-p plots (and Lambda factors) to the report--**without recompiling or re-annotating**.
    This is the standalone re-measure stage: build once, then sample under as many noise models as
    you like, exactly as a scheduler would (each measures the same circuit files, so a difference
    is the noise model, not an accident of rebuilding).

    Args:
        run_dir: a prior run directory (the ``--out`` of an earlier run).
        noise_models: noise-model factory names to sample under (default: the run's own).
        ps: physical error rates to sweep (default: the run's own).
        plot: embed one LER-vs-p figure per gadget into the report.
        lambda_factor: also compute the Lambda suppression factor from the two largest k.
        show_progress: print the console summary and the open hint.

    Returns:
        The report with fresh LER curves (already written back into ``run_dir``).
    """
    from dataclasses import replace

    run_dir = Path(run_dir)
    if not run_dir.is_dir():
        raise FileNotFoundError(f"simulate: {run_dir} is not a directory")
    report_path = run_dir / "report.json"
    if not report_path.is_file():
        raise FileNotFoundError(f"simulate: no report.json found at {report_path}")

    config = _load_config(run_dir)
    sim = replace(
        config.simulation,
        enabled=True,
        noise_models=tuple(noise_models)
        if noise_models
        else config.simulation.noise_models,
        ps=tuple(ps) if ps else config.simulation.ps,
        plot=plot,
        lambda_factor=lambda_factor,
    )
    config = config.with_overrides(simulation=sim)

    manifests = _discover_manifests(run_dir)
    if not manifests:
        raise FileNotFoundError(
            f"simulate: no prepared circuits under {run_dir} (expected prepared/manifest.json). "
            "This run's circuits were cleaned up; re-run the experiment to regenerate them."
        )
    manifest = manifests[-1]
    # point the manifest's generation config at the requested noise so simulate_batch measures it
    manifest.config = config.to_batch_config()

    report = ExperimentReport.from_json(report_path)
    # a re-measure replaces any earlier LER curves rather than keeping stale ones
    for row in report.rows:
        row.ler_plot = None
        row.lambda_factor = None

    from tools.experiment import simulate as simulate_mod

    log, log_path = runlog.make_logger(run_dir, name="simulate")
    log.info(
        "simulate: run_dir=%s noise_models=%s ps=%s",
        run_dir,
        sim.noise_models,
        sim.ps,
    )
    simulate_mod.augment(report, manifest, config, run_dir)
    report.write(run_dir)
    log.info("wrote report to %s", run_dir)
    if show_progress:
        print(report.to_text(), file=sys.stderr)
        print(
            f"simulated under noise_models={list(sim.noise_models)} ps={list(sim.ps)}",
            file=sys.stderr,
        )
        print(
            f"to see it in your browser run: open {(run_dir / 'report.html').resolve()}",
            file=sys.stderr,
        )
    return report


def _print_console_summary(
    report: ExperimentReport, out_dir: Path, log_path: Path
) -> None:
    s = report.summary()
    print(report.to_text(), file=sys.stderr)
    html_path = (out_dir / "report.html").resolve()
    print(
        f"\n{s['passed']}/{s['scored']} scored gadgets passed; "
        f"{s['prep_failed']} prep failures, {s['not_scored']} not scored. "
        f"log: {log_path}",
        file=sys.stderr,
    )
    print(f"to see the report in your browser run: open {html_path}", file=sys.stderr)
    print(f"  or the json / txt: open {out_dir.resolve()}", file=sys.stderr)
