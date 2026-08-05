"""Tests for the re-annotation layer (``stim`` + ``tqecd``: strip via tqecd, reattach here)."""

from __future__ import annotations

import stim

from tools.experiment import annotators


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
    bare = annotators.strip_annotations(_sample_circuit())
    assert bare.num_detectors == 0
    assert bare.num_observables == 0
    assert bare.num_measurements == 3


def test_observable_records_and_reattach_roundtrip():
    circuit = _sample_circuit()
    records = annotators.observable_records(circuit)
    assert {idx for idx, _ in records} == {0, 1}
    bare = annotators.strip_annotations(circuit)
    restored = annotators.reattach_observables(bare, records)
    assert restored.num_observables == 2
    got = dict(annotators.observable_records(restored))
    assert got[0] == [2]
    assert got[1] == [0]


def test_reannotate_with_uses_the_supplied_annotator():
    # reannotate_with strips, runs the annotator on the bare circuit, and reattaches observables.
    circuit = _sample_circuit()
    seen = {}

    def fake_annotate(bare: stim.Circuit) -> stim.Circuit:
        seen["detectors"] = bare.num_detectors
        return bare  # a no-op annotator: no detectors added

    out = annotators.reannotate_with(circuit, fake_annotate)
    assert seen["detectors"] == 0  # the annotator saw a bare (stripped) circuit
    assert out.num_observables == 2  # observables were reattached
    assert out.num_detectors == 0


# reannotate() calls tqecd's fragment matcher, which needs a real QEC circuit (not a toy
# reset/measure snippet); that path is exercised on real prepared gadgets in test_gadgets.py.
