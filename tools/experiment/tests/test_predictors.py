"""Unit tests for the ground-truth-free predictors (``stim`` + ``tqecd`` GF(2), no ``tqec``)."""

from __future__ import annotations

import stim

from tools.experiment.predictors import (
    _gf2_rank,
    _records_to_vector,
    count_missing_parities,
    describe_missing_parities,
    missing_parities,
    shortest_graphlike_error,
)


def test_gf2_rank_basic():
    # Vectors are integer bit-masks over measurement records (tqecd's BinaryVectorBasis encoding).
    assert _gf2_rank([]) == 0
    assert _gf2_rank([_records_to_vector(s) for s in ([0], [1], [2])]) == 3
    # two identical vectors -> rank 1
    assert _gf2_rank([_records_to_vector([0, 1]), _records_to_vector([0, 1])]) == 1
    # xor-dependent vectors ({0} ^ {1} = {0,1}) -> rank 2
    assert (
        _gf2_rank(
            [_records_to_vector([0]), _records_to_vector([1]), _records_to_vector([0, 1])]
        )
        == 2
    )


def test_complete_annotation_has_no_missing_parities():
    # Three resets + measurements; the two pairwise parities are deterministic and both declared.
    circuit = stim.Circuit("""
        R 0 1
        M 0 1
        DETECTOR rec[-2] rec[-1]
        OBSERVABLE_INCLUDE(0) rec[-1]
    """)
    assert count_missing_parities(circuit) == 0
    assert missing_parities(circuit) is False
    assert "complete" in describe_missing_parities(circuit)


def test_dropped_detector_is_flagged_missing():
    # Deterministic parity rec[-2]^rec[-1] exists but is NOT declared -> one missing parity.
    circuit = stim.Circuit("""
        R 0 1
        M 0 1
        OBSERVABLE_INCLUDE(0) rec[-1]
    """)
    assert count_missing_parities(circuit) == 1
    assert missing_parities(circuit) is True
    assert "incomplete" in describe_missing_parities(circuit)


def test_shortest_graphlike_error_none_when_no_logical_error():
    # A trivial circuit with no observable has no logical error.
    circuit = stim.Circuit("R 0\nM 0")
    assert shortest_graphlike_error(circuit) is None
