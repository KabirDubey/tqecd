"""Tests for the oracle framework (pure ``stim`` + ``numpy``)."""

from __future__ import annotations

import pytest
import stim

from tools.experiment.oracle import (
    CallableOracle,
    CircuitOracle,
    available_oracles,
    build_oracles,
    logically_equivalent,
    register_oracle,
    unregister_oracle,
)


class _Unit:
    def __init__(self, convention):
        self.convention = convention


def _circuit(detectors: str) -> stim.Circuit:
    return stim.Circuit(f"R 0 1\nM 0 1\n{detectors}")


def test_registry_is_empty_by_default():
    # No annotation is ground truth unless a user explicitly registers a reference.
    assert available_oracles() == []


def test_register_and_build_by_name():
    oracle = CircuitOracle("my_ref", _circuit("DETECTOR rec[-2] rec[-1]"))
    register_oracle(oracle)
    try:
        assert "my_ref" in available_oracles()
        assert build_oracles(["my_ref"])[0] is oracle
    finally:
        unregister_oracle("my_ref")
    assert "my_ref" not in available_oracles()


def test_build_unknown_oracle_raises():
    with pytest.raises(KeyError):
        build_oracles(["does_not_exist"])


def test_logically_equivalent_same_span():
    a = _circuit("DETECTOR rec[-2] rec[-1]")
    # a different but spanning-equivalent way of writing the same parity space
    b = _circuit("DETECTOR rec[-1] rec[-2]")
    assert logically_equivalent(a, b)


def test_logically_inequivalent_different_span():
    a = _circuit("DETECTOR rec[-2] rec[-1]\nOBSERVABLE_INCLUDE(0) rec[-1]")
    b = _circuit("DETECTOR rec[-2] rec[-1]")
    assert not logically_equivalent(a, b)


def test_circuit_oracle_applies_and_compares():
    ref = _circuit("DETECTOR rec[-2] rec[-1]\nOBSERVABLE_INCLUDE(0) rec[-1]")
    oracle = CircuitOracle(
        "ref", ref, applies_to=lambda unit, config: unit.convention == "fixed_bulk"
    )
    assert oracle.applies(_Unit("fixed_bulk"), config=None)
    assert not oracle.applies(_Unit("fixed_boundary"), config=None)
    verdict = oracle.compare(ref, oracle.reference(_Unit("fixed_bulk"), 1, ref))
    assert verdict.applies and verdict.equivalent and verdict.oracle == "ref"


def test_callable_oracle_emits_reference():
    # A callable oracle can synthesise the reference per unit (here it echoes the native circuit).
    oracle = CallableOracle("echo_native", emit=lambda unit, k, native: native)
    native = _circuit("DETECTOR rec[-2] rec[-1]")
    verdict = oracle.compare(native, oracle.reference(_Unit("fixed_bulk"), 1, native))
    assert verdict.equivalent
