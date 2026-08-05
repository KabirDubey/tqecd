"""Annotators under comparison: turn a native circuit into a re-annotated one.

The experimental subject is ``tqecd``'s windowed :func:`annotate_detectors_automatically`
(:func:`reannotate`). References (oracles, see :mod:`tools.experiment.oracle`) are alternate
annotators scored the same way -- ``tqec``'s own native annotation and the main-branch (windowless)
``tqecd`` run out-of-process.

Stripping detectors/observables is sourced from :func:`tqecd.utils.remove_annotations`; observables
are captured and reattached here because ``annotate_detectors_automatically`` produces detectors on
a bare circuit and does not preserve the logical observables.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

import stim
from tqecd.utils import remove_annotations

_MEASUREMENT_GATES = frozenset(
    {"M", "MR", "MX", "MY", "MZ", "MRX", "MRY", "MRZ", "MPP"}
)

#: Default location of the origin/main ``tqecd`` git worktree (for the windowless oracle).
DEFAULT_MAIN_SRC = Path(__file__).resolve().parents[3] / ".tqecd-main" / "src"


def strip_annotations(circuit: stim.Circuit) -> stim.Circuit:
    """Return ``circuit`` without ``DETECTOR`` / ``OBSERVABLE_INCLUDE`` (via ``tqecd``)."""
    return remove_annotations(circuit, frozenset({"DETECTOR", "OBSERVABLE_INCLUDE"}))


def observable_records(circuit: stim.Circuit) -> list[tuple[int, list[int]]]:
    """Capture each ``OBSERVABLE_INCLUDE`` as ``(index, absolute_measurement_records)``."""
    records: list[tuple[int, list[int]]] = []
    count = 0
    for instruction in circuit.flattened():
        name = instruction.name
        if name in _MEASUREMENT_GATES:
            count += instruction.num_measurements
        elif name == "OBSERVABLE_INCLUDE":
            index = int(instruction.gate_args_copy()[0])
            recs = [
                count + target.value
                for target in instruction.targets_copy()
                if target.is_measurement_record_target
            ]
            records.append((index, recs))
    return records


def reattach_observables(
    circuit: stim.Circuit, records: list[tuple[int, list[int]]]
) -> stim.Circuit:
    """Append ``OBSERVABLE_INCLUDE`` instructions at the given absolute measurement records."""
    total = circuit.num_measurements
    out = circuit.copy()
    for index, recs in records:
        targets = [stim.target_rec(rec - total) for rec in recs]
        out.append("OBSERVABLE_INCLUDE", targets, index)
    return out


def reannotate_with(
    native: stim.Circuit, annotate_bare: Callable[[stim.Circuit], stim.Circuit]
) -> stim.Circuit:
    """Strip ``native``, run ``annotate_bare`` on the bare circuit, reattach the observables.

    Mirrors ``tqec``'s compile order (detectors before observables): the observables are stripped
    before matching so the annotator never sees them, then reattached at their original records.
    """
    observables = observable_records(native)
    bare = strip_annotations(native)
    annotated = annotate_bare(bare)
    return reattach_observables(annotated, observables)


def reannotate(circuit: stim.Circuit, *, window: int = 2) -> stim.Circuit:
    """The experimental annotator: in-repo ``tqecd`` windowed ``annotate_detectors_automatically``."""
    from tqecd.construction import annotate_detectors_automatically

    return reannotate_with(
        circuit, lambda bare: annotate_detectors_automatically(bare, window=window)
    )


def native_annotation(native: stim.Circuit) -> stim.Circuit:
    """The native oracle: ``tqec``'s own annotation, i.e. the circuit as ``prepare_batch`` wrote it."""
    return native


def main_branch_src() -> Path | None:
    """Path to the origin/main ``tqecd`` ``src`` for the windowless oracle, or ``None`` if absent."""
    src = Path(os.environ.get("TQECD_MAIN_SRC", str(DEFAULT_MAIN_SRC)))
    return src if (src / "tqecd" / "construction.py").is_file() else None


def main_branch_reannotation(native: stim.Circuit) -> stim.Circuit:
    """The windowless oracle: re-annotate via main-branch ``tqecd`` in a subprocess.

    The main-branch ``tqecd`` and the in-repo (windowed) one are different packages that cannot
    share a process, so the bare circuit is annotated in a subprocess whose ``PYTHONPATH`` points
    at the main-branch ``src`` (its ``annotate_detectors_automatically`` takes no ``window``).
    """
    src = main_branch_src()
    if src is None:
        raise FileNotFoundError(
            "main-branch tqecd worktree not found; set TQECD_MAIN_SRC or create the "
            f"{DEFAULT_MAIN_SRC} worktree (git worktree add .tqecd-main origin/main)."
        )

    def annotate_bare(bare: stim.Circuit) -> stim.Circuit:
        with tempfile.TemporaryDirectory() as tmp:
            inp, out = Path(tmp) / "bare.stim", Path(tmp) / "annotated.stim"
            bare.to_file(inp)
            script = (
                "import sys, stim; "
                "from tqecd.construction import annotate_detectors_automatically as f; "
                "f(stim.Circuit.from_file(sys.argv[1])).to_file(sys.argv[2])"
            )
            env = {**os.environ, "PYTHONPATH": str(src)}
            subprocess.run(
                [sys.executable, "-c", script, str(inp), str(out)],
                env=env,
                check=True,
                capture_output=True,
            )
            return stim.Circuit.from_file(out)

    return reannotate_with(native, annotate_bare)
