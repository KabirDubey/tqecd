"""Ground-truth-free *predictors* of fault tolerance (``stim`` + ``numpy``).

These are objective functions, not ground truth (see ``README.md``): they measure absolute
properties of a single circuit without comparing it to any reference annotation.

* :func:`missing_parities` -- GF(2) flow-completeness: are all deterministic measurement
  parities the circuit guarantees actually captured by its emitted ``DETECTOR`` / ``OBSERVABLE``
  set? A nonzero result is a parity the annotator failed to attach. Strictly stronger than
  distance.
* :func:`shortest_graphlike_error` -- the code distance of the noisy circuit, compared to the
  expected ``2k + 1``.
"""

from __future__ import annotations

import numpy as np
import stim

_MEASUREMENT_GATES = frozenset(
    {"M", "MR", "MX", "MY", "MZ", "MRX", "MRY", "MRZ", "MPP"}
)


def _gf2_rank(matrix: np.ndarray) -> int:
    """Rank of a 0/1 matrix over GF(2) via Gaussian elimination."""
    m = np.ascontiguousarray(matrix, dtype=np.uint8).copy()
    rows, cols = m.shape
    rank = 0
    for col in range(cols):
        pivot = next((r for r in range(rank, rows) if m[r, col]), None)
        if pivot is None:
            continue
        m[[rank, pivot]] = m[[pivot, rank]]
        mask = m[:, col].copy().astype(bool)
        mask[rank] = False
        m[mask] ^= m[rank]
        rank += 1
        if rank == rows:
            break
    return rank


def _emitted_subspace(circuit: stim.Circuit) -> np.ndarray:
    """Indicator vectors (over measurement indices) of every ``DETECTOR`` and ``OBSERVABLE``."""
    n = circuit.num_measurements
    rows: list[np.ndarray] = []
    count = 0
    for instruction in circuit.flattened():
        name = instruction.name
        if name in _MEASUREMENT_GATES:
            count += instruction.num_measurements
        elif name in ("DETECTOR", "OBSERVABLE_INCLUDE"):
            vector = np.zeros(n, dtype=np.uint8)
            for target in instruction.targets_copy():
                if target.is_measurement_record_target:
                    vector[count + target.value] ^= 1
            rows.append(vector)
    return np.array(rows, dtype=np.uint8) if rows else np.zeros((0, n), dtype=np.uint8)


def _complete_subspace(circuit: stim.Circuit) -> np.ndarray:
    """Complete deterministic measurement-parity space (flow generators with trivial in/out)."""
    n = circuit.num_measurements
    rows: list[np.ndarray] = []
    for flow in circuit.flow_generators():
        if len(flow.input_copy()) == 0 and len(flow.output_copy()) == 0:
            indices = flow.measurements_copy()
            if indices:
                vector = np.zeros(n, dtype=np.uint8)
                for index in indices:
                    vector[index] ^= 1
                rows.append(vector)
    return np.array(rows, dtype=np.uint8) if rows else np.zeros((0, n), dtype=np.uint8)


def count_missing_parities(circuit: stim.Circuit) -> int:
    """Number of independent deterministic parities the annotation failed to capture.

    Reduces the circuit's complete deterministic-parity space (``stim`` flow generators with
    trivial input/output) against the annotator's emitted ``DETECTOR`` / ``OBSERVABLE`` subspace
    over GF(2). Returns ``rank([E; C]) - rank(E)``: zero iff every deterministic parity is
    spanned by the emitted annotations, i.e. the welding is complete.
    """
    emitted = _emitted_subspace(circuit)
    complete = _complete_subspace(circuit)
    rank_e = _gf2_rank(emitted)
    if complete.shape[0] == 0:
        return 0
    rank_ec = _gf2_rank(np.vstack([emitted, complete]))
    return rank_ec - rank_e


def missing_parities(circuit: stim.Circuit) -> bool:
    """``True`` iff the circuit has at least one missing deterministic parity."""
    return count_missing_parities(circuit) > 0


def describe_missing_parities(circuit: stim.Circuit) -> str:
    """Human-readable one-liner about parity completeness."""
    n = count_missing_parities(circuit)
    if n == 0:
        return "complete: every deterministic parity is captured by the annotation"
    return f"incomplete: {n} deterministic parit{'y' if n == 1 else 'ies'} not welded"


def shortest_graphlike_error(
    noisy_circuit: stim.Circuit, *, ignore_ungraphlike_errors: bool = False
) -> int | None:
    """Code distance of an already-noisy circuit, or ``None`` if it has no logical errors.

    The caller is responsible for applying a noise model (kept ``tqec``-free here). Compare the
    result to the expected ``2 * k + 1``.
    """
    try:
        error = noisy_circuit.shortest_graphlike_error(
            ignore_ungraphlike_errors=ignore_ungraphlike_errors
        )
    except ValueError:
        return None
    return len(error)
