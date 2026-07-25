"""Tests for the re-annotation layer (``stim`` + ``tqecd`` only)."""

from __future__ import annotations

import stim

from tools.experiment import annotate


def _sample_circuit() -> stim.Circuit:
    return stim.Circuit("""
        R 0 1 2
        M 0 1 2
        DETECTOR rec[-3] rec[-2]
        DETECTOR rec[-2] rec[-1]
        OBSERVABLE_INCLUDE(0) rec[-1]
        OBSERVABLE_INCLUDE(1) rec[-3]
    """)


def test_strip_removes_all_annotations():
    bare = annotate.strip_annotations(_sample_circuit())
    assert bare.num_detectors == 0
    assert bare.num_observables == 0
    assert bare.num_measurements == 3


def test_observable_records_and_reattach_roundtrip():
    circuit = _sample_circuit()
    records = annotate.observable_records(circuit)
    assert {idx for idx, _ in records} == {0, 1}
    bare = annotate.strip_annotations(circuit)
    restored = annotate.reattach_observables(bare, records)
    assert restored.num_observables == 2
    # observable 0 references the last measurement (absolute index 2)
    got = dict(annotate.observable_records(restored))
    assert got[0] == [2]
    assert got[1] == [0]


# reannotate() calls tqecd's fragment matcher, which requires a real QEC circuit (not a toy
# reset/measure snippet); that path is exercised on real prepared gadgets in test_battery.py.
