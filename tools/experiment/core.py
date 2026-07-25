"""``run_experiment``: drive ``prepare_batch``, re-annotate, score, and render a report.

This is the only module (besides :mod:`tools.experiment.simulate`) that imports ``tqec``. It is a
pure downstream consumer of ``tqec.orchestration``: ``prepare_batch`` does the splitting,
compilation and native circuit generation; this loop reads the circuits off disk, re-annotates them
with ``tqecd``, measures predictors and oracles, writes debugging artifacts (circuits, crumble
links, stim diagrams, structure pictures), logs progress, and prints a console summary.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Sequence

import stim

from tools.experiment import annotate, predictors, runlog, visuals
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
    return int(eval(expr, {"__builtins__": {}}, {"k": k}))  # noqa: S307 - trusted config expr


def _noisy(circuit: stim.Circuit, noise_model: str, p: float) -> stim.Circuit:
    from tqec.utils.noise_model import NoiseModel

    factory = getattr(NoiseModel, noise_model, None)
    if factory is None:
        factory = NoiseModel.uniform_depolarizing
    return factory(p).noisy_circuit(circuit)


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
    radius: int,
    window: int,
    config: ExperimentConfig,
    oracles: Sequence[Any],
) -> ExperimentRow:
    row = ExperimentRow(
        gadget_id=unit.gadget_id,
        source=getattr(unit, "source", ""),
        name=getattr(unit, "name", ""),
        convention=unit.convention,
        k=k,
        manhattan_radius=radius,
        window=window,
        status=unit.status,
    )

    if config.run_parities:
        row.missing_parities = predictors.count_missing_parities(reannotated)
        row.parities_ok = row.missing_parities == 0
        row.native_missing = predictors.count_missing_parities(native)

    if config.run_distance:
        row.expected_distance = _expected_distance(config.expected_distance, k)
        noisy = _noisy(reannotated, config.noise_models[0], config.ps[0])
        row.distance = predictors.shortest_graphlike_error(noisy)
        row.distance_ok = row.distance == row.expected_distance

    checks = [ok for ok in (row.parities_ok, row.distance_ok) if ok is not None]
    row.predictors_pass = all(checks) if checks else None
    row.status_kind = _status_kind(unit.status, row.predictors_pass)

    for oracle in oracles:
        if oracle.applies(unit, config):
            verdict = oracle.compare(reannotated, oracle.reference(unit, k, native))
            row.oracle_verdicts[oracle.name] = verdict.to_dict()

    return row


def _prep_row(unit: Any, radius: int) -> ExperimentRow:
    status = unit.status
    return ExperimentRow(
        gadget_id=unit.gadget_id,
        source=getattr(unit, "source", ""),
        name=getattr(unit, "name", ""),
        convention=unit.convention,
        k=-1,
        manhattan_radius=radius,
        window=-1,
        status=status,
        status_kind=_status_kind(status, None),
        notes=getattr(unit, "error", "") or getattr(unit, "notes", ""),
    )


def _relpath(path: Path, out_dir: Path) -> str:
    return os.path.relpath(path, out_dir)


def _ensure_gadget_visuals(
    unit: Any,
    manifest: Any,
    gadget_visuals: dict[str, dict[str, Any]],
    artifacts: Path,
    out_dir: Path,
    log,
) -> None:
    """Compute the per-gadget structure pictures once (positioned ZX + block-graph Pauli web)."""
    gid = unit.gadget_id
    if gid in gadget_visuals or not getattr(unit, "graph", None):
        return
    gadget_visuals[gid] = {}
    try:
        from tqec.computation.block_graph import BlockGraph

        graph = BlockGraph.from_json(manifest.run_dir / unit.graph, graph_name=gid)
    except Exception as exc:
        log.info("gadget visuals: could not load graph for %s: %s", gid, exc)
        return
    try:
        surfaces = graph.find_correlation_surfaces()
        surface = surfaces[0] if surfaces else None
    except Exception:
        surface = None
    zx = visuals.positioned_zx_png_data_uri(graph, title=gid)
    if zx:
        gadget_visuals[gid]["zx_png"] = zx
    bg_path = artifacts / gid / "block_graph.html"
    written = visuals.write_block_graph_html(graph, bg_path, correlation_surface=surface)
    if written:
        gadget_visuals[gid]["block_graph_html"] = _relpath(written, out_dir)


def _attach_visuals(
    row: ExperimentRow,
    native: stim.Circuit,
    reannotated: stim.Circuit,
    config: ExperimentConfig,
    artifacts: Path,
    out_dir: Path,
) -> None:
    """Write per-row circuit artifacts and failure-directed stim diagrams onto ``row.visuals``."""
    cell = artifacts / row.gadget_id / f"{row.convention}_k{row.k}_r{row.manhattan_radius}_w{row.window}"
    v: dict[str, Any] = {}
    try:
        v["crumble"] = visuals.crumble_url(reannotated)
        v["circuit"] = _relpath(visuals.write_circuit(reannotated, cell / "annotated.stim"), out_dir)
        detector_free = annotate.strip_annotations(native)
        v["detector_free"] = _relpath(
            visuals.write_circuit(detector_free, cell / "detector_free.stim"), out_dir
        )
    except Exception:
        pass

    error = "" if row.distance_ok is not False else "distance"
    if row.parities_ok is False:
        error = "parities"
    diagrams: list[dict[str, str]] = []
    for kind in visuals.diagnostic_kinds(row.status, error):
        source = reannotated
        if kind == visuals.MATCHGRAPH:
            try:
                source = _noisy(reannotated, config.noise_models[0], config.ps[0])
            except Exception:
                source = reannotated
        svg = visuals.diagram_svg(source, kind)
        if svg:
            diagrams.append({"label": kind, "svg": svg})
    if diagrams:
        v["diagrams"] = diagrams
    row.visuals = v


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
        config: experiment knobs (conventions, ks, windows, manhattan radii, predictors, oracles).
        out_dir: directory for the run artifacts and the report.
        oracles: optional user-supplied reference oracles (objects), compared up to logical
            symmetry; merged with any registered by name in ``config.oracles``. Ground truth is
            opt-in and often absent, so this defaults to empty.
        show_progress: draw a per-row progress bar and print a console summary at the end.

    Returns:
        The :class:`ExperimentReport` (already written to disk).
    """
    from tqec.orchestration import prepare_batch

    out_dir = Path(out_dir)
    artifacts = out_dir / "artifacts"
    log, log_path = runlog.make_logger(out_dir)
    log.info(
        "start: conventions=%s ks=%s windows=%s manhattan_radii=%s inputs=%d",
        config.conventions, config.ks, config.windows, config.manhattan_radii, len(inputs),
    )

    active_oracles = [*oracles, *config.enabled_oracles()]
    gadget_visuals: dict[str, dict[str, Any]] = {}
    rows: list[ExperimentRow] = []
    work: list[tuple[Any, int, stim.Circuit, int, int]] = []
    last_manifest = None

    for radius in config.manhattan_radii:
        batch_config = config.to_batch_config(manhattan_radius=radius)
        log.info("prepare_batch: manhattan_radius=%d", radius)
        manifest = prepare_batch(inputs, batch_config, out_dir / f"mr{radius}")
        last_manifest = manifest
        for unit in manifest.units:
            _ensure_gadget_visuals(unit, manifest, gadget_visuals, artifacts, out_dir, log)
            if unit.status != "ready" or not unit.circuits:
                rows.append(_prep_row(unit, radius))
                log.info("prep %s [%s] status=%s", unit.gadget_id, unit.convention, unit.status)
                continue
            for k, rel in unit.circuits.items():
                native = stim.Circuit.from_file(manifest.run_dir / rel)
                for window in config.windows:
                    work.append((unit, k, native, radius, window))

    iterator: Any = work
    if show_progress:
        try:
            from tqdm import tqdm

            iterator = tqdm(work, desc="scoring rows", unit="row")
        except Exception:
            iterator = work

    for unit, k, native, radius, window in iterator:
        reannotated = annotate.reannotate(native, window=window)
        row = _score(native, reannotated, unit, k, radius, window, config, active_oracles)
        _attach_visuals(row, native, reannotated, config, artifacts, out_dir)
        rows.append(row)
        log.info(
            "score %s [%s] k=%s r=%s w=%s missing=%s dist=%s pass=%s",
            unit.gadget_id, unit.convention, k, radius, window,
            row.missing_parities, row.distance, row.predictors_pass,
        )

    report = ExperimentReport(
        rows=rows,
        gadget_visuals=gadget_visuals,
        meta={
            "conventions": list(config.conventions),
            "ks": list(config.ks),
            "windows": list(config.windows),
            "manhattan_radii": list(config.manhattan_radii),
            "oracles": [getattr(o, "name", str(o)) for o in active_oracles],
            "log": _relpath(log_path, out_dir),
        },
    )

    if config.simulation.enabled and last_manifest is not None:
        from tools.experiment import simulate

        last_radius = config.manhattan_radii[-1]
        simulate.augment(report, last_manifest, config, radius=last_radius)

    report.write(out_dir)
    log.info("wrote report to %s", out_dir)
    if show_progress:
        _print_console_summary(report, out_dir, log_path)
    return report


def _print_console_summary(report: ExperimentReport, out_dir: Path, log_path: Path) -> None:
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
    print(f"  or the json/csv: open {out_dir.resolve()}", file=sys.stderr)
