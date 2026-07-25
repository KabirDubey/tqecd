"""``run_experiment``--drive ``prepare_batch``, re-annotate, and score each prepared circuit.

This is the only module (besides :mod:`tools.experiment.simulate`) that imports ``tqec``. It is
a pure downstream consumer of ``tqec.orchestration``: ``prepare_batch`` does the splitting,
compilation and native circuit generation; this loop reads the circuits off disk, re-annotates
them with ``tqecd``, and measures predictors + oracles.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

import stim

from tools.experiment import annotate, predictors
from tools.experiment.config import ExperimentConfig
from tools.experiment.report import ExperimentReport, ExperimentRow


def _expected_distance(expr: str, k: int) -> int:
    return int(eval(expr, {"__builtins__": {}}, {"k": k}))  # noqa: S307 - trusted config expr


def _noisy(circuit: stim.Circuit, noise_model: str, p: float) -> stim.Circuit:
    from tqec.utils.noise_model import NoiseModel

    factory = getattr(NoiseModel, noise_model, None)
    if factory is None:
        factory = NoiseModel.uniform_depolarizing
    return factory(p).noisy_circuit(circuit)


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

    for oracle in oracles:
        if oracle.applies(unit, config):
            verdict = oracle.compare(reannotated, oracle.reference(unit, k, native))
            row.oracle_verdicts[oracle.name] = verdict.to_dict()

    return row


def run_experiment(
    inputs: Sequence[str | Path | Any],
    config: ExperimentConfig,
    out_dir: str | Path,
    *,
    oracles: Sequence[Any] = (),
) -> ExperimentReport:
    """Run a batched gadget experiment and write ``report.{json,html,txt}`` under ``out_dir``.

    Args:
        inputs: a mix of ``.dae`` / ``.bgraph`` paths and in-memory ``BlockGraph`` objects, passed
            straight to ``tqec.orchestration.prepare_batch``.
        config: experiment knobs (conventions, ks, windows, manhattan radii, predictors, oracles).
        out_dir: directory for the run artifacts and the report.
        oracles: optional user-supplied reference oracles (objects) compared up to logical
            symmetry; merged with any registered by name in ``config.oracles``. Ground truth
            is opt-in and often absent, so this defaults to empty.

    Returns:
        The :class:`ExperimentReport` (already written to disk).
    """
    from tqec.orchestration import prepare_batch

    active_oracles = [*oracles, *config.enabled_oracles()]
    out_dir = Path(out_dir)
    rows: list[ExperimentRow] = []
    last_manifest = None

    for radius in config.manhattan_radii:
        batch_config = config.to_batch_config(manhattan_radius=radius)
        manifest = prepare_batch(inputs, batch_config, out_dir / f"mr{radius}")
        last_manifest = manifest
        for unit in manifest.units:
            if unit.status != "ready" or not unit.circuits:
                rows.append(
                    ExperimentRow(
                        gadget_id=unit.gadget_id,
                        source=getattr(unit, "source", ""),
                        name=getattr(unit, "name", ""),
                        convention=unit.convention,
                        k=-1,
                        manhattan_radius=radius,
                        window=-1,
                        status=unit.status,
                        notes=getattr(unit, "error", "") or getattr(unit, "notes", ""),
                    )
                )
                continue
            for k, rel in unit.circuits.items():
                native = stim.Circuit.from_file(manifest.run_dir / rel)
                for window in config.windows:
                    reannotated = annotate.reannotate(native, window=window)
                    rows.append(
                        _score(
                            native, reannotated, unit, k, radius, window, config, active_oracles
                        )
                    )

    report = ExperimentReport(
        rows=rows,
        meta={
            "conventions": list(config.conventions),
            "ks": list(config.ks),
            "windows": list(config.windows),
            "manhattan_radii": list(config.manhattan_radii),
            "oracles": list(config.oracles),
        },
    )

    if config.simulation.enabled and last_manifest is not None:
        from tools.experiment import simulate

        simulate.augment(report, last_manifest, config)

    report.write(out_dir)
    return report
