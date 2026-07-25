"""Re-annotate a circuit with ``tqecd``'s detector matcher (``stim`` + ``tqecd`` only).

This layer imports neither :mod:`tqec` nor anything heavier than ``stim`` and ``tqecd`` so that
it stays independent of the orchestration side and could later migrate into ``tqecd`` proper.

The operation here is deliberately called :func:`reannotate`.
"""

from __future__ import annotations

import stim

from tqecd.construction import annotate_detectors_automatically

_MEASUREMENT_GATES = frozenset(
    {"M", "MR", "MX", "MY", "MZ", "MRX", "MRY", "MRZ", "MPP"}
)
_ANNOTATION_GATES = frozenset({"DETECTOR", "OBSERVABLE_INCLUDE"})


def strip_annotations(circuit: stim.Circuit) -> stim.Circuit:
    """Return ``circuit`` with every ``DETECTOR`` and ``OBSERVABLE_INCLUDE`` removed.

    Repeat blocks are recursed into so annotations inside loops are stripped too.
    """
    out = stim.Circuit()
    for instruction in circuit:
        if isinstance(instruction, stim.CircuitRepeatBlock):
            out.append(
                stim.CircuitRepeatBlock(
                    instruction.repeat_count, strip_annotations(instruction.body_copy())
                )
            )
        elif instruction.name not in _ANNOTATION_GATES:
            out.append(instruction)
    return out


def observable_records(circuit: stim.Circuit) -> list[tuple[int, list[int]]]:
    """Capture each ``OBSERVABLE_INCLUDE`` as ``(observable_index, absolute_measurement_indices)``.

    Absolute indices are counted from the start of the (flattened) circuit, so they are stable
    against re-annotation, which never changes the measurement structure.
    """
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
    """Append ``OBSERVABLE_INCLUDE`` instructions at the given absolute measurement indices."""
    total = circuit.num_measurements
    out = circuit.copy()
    for index, recs in records:
        targets = [stim.target_rec(rec - total) for rec in recs]
        out.append("OBSERVABLE_INCLUDE", targets, index)
    return out


def reannotate(circuit: stim.Circuit, *, window: int = 2) -> stim.Circuit:
    """Strip annotations, re-run ``tqecd`` detector matching, reattach the observables.

    Mirrors ``tqec``'s own compile order (detectors before observables): the logical observables
    are stripped before matching, so ``tqecd`` never sees them while matching detectors, then they
    are reattached at their original measurement records.

    Args:
        circuit: a fully annotated circuit (e.g. a native circuit written by ``prepare_batch``).
        window: matching-window width forwarded to
            :func:`tqecd.construction.annotate_detectors_automatically` (the knob under test).

    Returns:
        The re-annotated circuit: ``tqecd``-computed detectors plus the reattached observables.
    """
    observables = observable_records(circuit)
    bare = strip_annotations(circuit)
    annotated = annotate_detectors_automatically(bare, window=window)
    return reattach_observables(annotated, observables)
