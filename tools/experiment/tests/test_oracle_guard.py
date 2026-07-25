"""Oracle logical-equivalence guard on real reference circuits (``stim`` + ``numpy`` only).

The circuits under ``tests/test_circuits`` are genuine annotated stim circuits kept as fixtures:

* ``slide_d3_{west,east}`` -- a logical qubit sliding one lattice step west and east (distance 3,
  with a logical observable);
* ``y_basis_{initialization,measurement}`` -- a Y half cube at the init end and at the measurement
  end (real ``RY`` / ``MY`` operations, detectors only), pulled from the Y-basis branch.

Each must satisfy the guard an oracle relies on: a reference oracle built from the circuit assigns
it as equivalent to itself up to logical (GF(2) span) symmetry, while a de-annotated copy is
correctly rejected.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import stim

from tools.experiment.annotate import strip_annotations
from tools.experiment.oracle import CallableOracle, CircuitOracle, logically_equivalent

CIRCUITS = Path(__file__).parent / "test_circuits"


def _load(name: str) -> stim.Circuit:
    return stim.Circuit(( CIRCUITS / name ).read_text())


@pytest.mark.parametrize("name", ["slide_d3_west.stim", "slide_d3_east.stim"])
def test_oracle_guard_sliding(name: str) -> None:
    circuit = _load(name)
    assert circuit.num_detectors > 0
    oracle = CircuitOracle(name, circuit)
    verdict = oracle.compare(circuit, oracle.reference(unit=None, k=1, native=circuit))
    assert verdict.applies and verdict.equivalent
    assert logically_equivalent(circuit, circuit)
    # the guard rejects an annotation that dropped its detectors/observables
    assert not logically_equivalent(circuit, strip_annotations(circuit))


@pytest.mark.parametrize("name", ["y_basis_initialization.stim", "y_basis_measurement.stim"])
def test_oracle_guard_ybasis(name: str) -> None:
    circuit = _load(name)
    text = str(circuit)
    assert "RY" in text or "MY" in text  # genuinely a Y-basis circuit
    assert circuit.num_detectors > 0
    oracle = CallableOracle(name, emit=lambda unit, k, native: native)
    verdict = oracle.compare(circuit, oracle.reference(unit=None, k=1, native=circuit))
    assert verdict.equivalent
    assert not logically_equivalent(circuit, strip_annotations(circuit))
