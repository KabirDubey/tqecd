"""Tests for the oracle framework (pure ``stim`` + ``numpy``)."""

from __future__ import annotations

import pytest
import stim

from tools.experiment.oracle import (
    NATIVE_ORACLE,
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


def test_only_native_is_built_in():
    # The built-in `native` oracle ships registered; nothing else is ground truth by default.
    assert available_oracles() == ["native"]


def test_native_oracle_resolves_and_scopes_to_fixed_bulk():
    # Selectable by name with one keyword, and only a valid reference for fixed_bulk.
    assert build_oracles(["native"])[0] is NATIVE_ORACLE
    assert NATIVE_ORACLE.applies(_Unit("fixed_bulk"), None) is True
    assert NATIVE_ORACLE.applies(_Unit("fixed_boundary"), None) is False


def test_native_oracle_reference_is_the_native_circuit_and_compares():
    native = _circuit("DETECTOR rec[-2] rec[-1]")
    # the reference the oracle hands back is exactly tqec's native circuit passed to it
    assert NATIVE_ORACLE.reference(_Unit("fixed_bulk"), 1, native) is native
    # a tqecd reannotation matching native is equivalent; a different subspace is not
    same = _circuit("DETECTOR rec[-2] rec[-1]")
    diff = _circuit("DETECTOR rec[-1]")
    assert NATIVE_ORACLE.compare(same, native).equivalent is True
    assert NATIVE_ORACLE.compare(diff, native).equivalent is False


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
