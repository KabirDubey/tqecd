"""Ground-truth-free *predictors* of fault tolerance (``stim`` + ``tqecd``).

These are objective functions, not ground truth (see ``README.md``): they measure absolute
properties of a single circuit without comparing it to any reference annotation.

* :func:`missing_parities`--GF(2) flow-completeness: are all deterministic measurement
  parities the circuit guarantees actually captured by its emitted ``DETECTOR`` / ``OBSERVABLE``
  set? A nonzero result is a parity the annotator failed to attach. Strictly stronger than
  distance.
* :func:`shortest_graphlike_error`--the code distance of the noisy circuit, compared to the
  expected ``2k + 1``.

The GF(2) linear algebra is sourced from ``tqecd`` itself--:class:`tqecd.cover.BinaryVectorBasis`,
the same incremental Gaussian-elimination primitive ``tqecd`` uses to reduce detector candidates.
Measurement-record sets are encoded as arbitrary-precision integer bit-vectors (one bit per
measurement), exactly as ``tqecd.window`` encodes them, so no separate matrix library is needed.
"""

from __future__ import annotations

from collections.abc import Iterable

import stim

from tqecd.cover import BinaryVectorBasis

_MEASUREMENT_GATES = frozenset(
    {"M", "MR", "MX", "MY", "MZ", "MRX", "MRY", "MRZ", "MPP"}
)


def _records_to_vector(indices: Iterable[int]) -> int:
    """Encode absolute measurement-record indices as a GF(2) integer bit-vector."""
    vector = 0
    for index in indices:
        vector ^= 1 << index
    return vector


def _gf2_rank(vectors: Iterable[int]) -> int:
    """Rank over GF(2) of integer bit-vectors, via ``tqecd``'s :class:`BinaryVectorBasis`.

    Each vector added independently of the running basis increments the rank; ``BinaryVectorBasis``
    is the same XOR-reduction primitive ``tqecd`` uses to keep only independent detector
    candidates, so the predictor and the annotator share one notion of GF(2) independence.
    """
    basis = BinaryVectorBasis()
    return sum(1 for vector in vectors if basis.add(vector))


def _emitted_vectors(circuit: stim.Circuit) -> list[int]:
    """Bit-vectors (over measurement records) of every ``DETECTOR`` and ``OBSERVABLE``."""
    vectors: list[int] = []
    count = 0
    for instruction in circuit.flattened():
        name = instruction.name
        if name in _MEASUREMENT_GATES:
            count += instruction.num_measurements
        elif name in ("DETECTOR", "OBSERVABLE_INCLUDE"):
            indices = [
                count + target.value
                for target in instruction.targets_copy()
                if target.is_measurement_record_target
            ]
            vectors.append(_records_to_vector(indices))
    return vectors


def _complete_vectors(circuit: stim.Circuit) -> list[int]:
    """Complete deterministic measurement-parity space (flow generators with trivial in/out)."""
    vectors: list[int] = []
    for flow in circuit.flow_generators():
        if len(flow.input_copy()) == 0 and len(flow.output_copy()) == 0:
            indices = flow.measurements_copy()
            if indices:
                vectors.append(_records_to_vector(indices))
    return vectors


def count_missing_parities(circuit: stim.Circuit) -> int:
    """Number of independent deterministic parities the annotation failed to capture.

    Reduces the circuit's complete deterministic-parity space (``stim`` flow generators with
    trivial input/output) against the annotator's emitted ``DETECTOR`` / ``OBSERVABLE`` subspace
    over GF(2). Returns ``rank([E; C]) - rank(E)``: zero iff every deterministic parity is
    spanned by the emitted annotations, i.e. the annotation is complete.
    """
    emitted = _emitted_vectors(circuit)
    complete = _complete_vectors(circuit)
    if not complete:
        return 0
    rank_e = _gf2_rank(emitted)
    rank_ec = _gf2_rank([*emitted, *complete])
    return rank_ec - rank_e


def missing_parities(circuit: stim.Circuit) -> bool:
    """``True`` iff the circuit has at least one missing deterministic parity."""
    return count_missing_parities(circuit) > 0


def describe_missing_parities(circuit: stim.Circuit) -> str:
    """Human-readable one-liner about parity completeness."""
    n = count_missing_parities(circuit)
    if n == 0:
        return "complete: every deterministic parity is captured by the annotation"
    return f"incomplete: {n} deterministic parit{'y' if n == 1 else 'ies'} not attached"


def shortest_graphlike_error(
    noisy_circuit: stim.Circuit, *, ignore_ungraphlike_errors: bool = False
) -> int | None:
    """Code distance of an already-noisy circuit, or ``None`` if it has no logical errors.

    The caller is responsible for applying a noise model (kept ``tqec``-free here). Compare the
    result to the expected ``2 * k + 1``.

    This is an analytic minimum-weight search over the detector error model: it does not
    sample the circuit, so it never invokes the Sinter simulator and stays independent of
    the optional simulation mode (which is the only sampling path). The caller applies a noise
    model at some physical error rate ``p`` to instantiate the error mechanisms, but the returned
    weight (the distance) depends only on the noise *model*, not the ``p`` value -- any ``p`` in
    ``(0, 1)`` gives the same result.
    """
    try:
        error = noisy_circuit.shortest_graphlike_error(
            ignore_ungraphlike_errors=ignore_ungraphlike_errors
        )
    except ValueError:
        return None
    return len(error)
