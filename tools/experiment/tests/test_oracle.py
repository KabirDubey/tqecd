"""Tests for the oracle framework (alternate annotators; ``stim`` + ``tqecd`` GF(2))."""

from __future__ import annotations

import pytest
import stim

from tools.experiment.oracle import (
    MAIN_ORACLE,
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


def test_builtin_oracles_registered():
    # native + tqecd_main (the windowless main-branch annotator) ship registered.
    assert available_oracles() == ["native", "tqecd_main"]


def test_native_oracle_annotates_and_applies_everywhere():
    assert build_oracles(["native"])[0] is NATIVE_ORACLE
    assert NATIVE_ORACLE.applies(_Unit("fixed_bulk"), None) is True
    assert NATIVE_ORACLE.applies(_Unit("fixed_boundary"), None) is True
    native = _circuit("DETECTOR rec[-2] rec[-1]")
    # the native oracle's annotation is exactly tqec's native circuit passed to it
    assert NATIVE_ORACLE.annotate(_Unit("fixed_bulk"), 1, native) is native


def test_main_oracle_registered_and_named():
    assert build_oracles(["tqecd_main"])[0] is MAIN_ORACLE
    assert MAIN_ORACLE.name == "tqecd_main"


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


def test_circuit_oracle_applies_and_annotates():
    ref = _circuit("DETECTOR rec[-2] rec[-1]\nOBSERVABLE_INCLUDE(0) rec[-1]")
    oracle = CircuitOracle(
        "ref", ref, applies_to=lambda unit, config: unit.convention == "fixed_bulk"
    )
    assert oracle.applies(_Unit("fixed_bulk"), config=None)
    assert not oracle.applies(_Unit("fixed_boundary"), config=None)
    # the oracle's annotation is the fixed reference circuit, equivalent to itself
    assert oracle.annotate(_Unit("fixed_bulk"), 1, ref) is ref
    assert logically_equivalent(ref, oracle.annotate(_Unit("fixed_bulk"), 1, ref))


def test_callable_oracle_annotates():
    # A callable oracle synthesises the annotation per unit (here it echoes the native circuit).
    oracle = CallableOracle("echo_native", emit=lambda unit, k, native: native)
    native = _circuit("DETECTOR rec[-2] rec[-1]")
    assert oracle.annotate(_Unit("fixed_bulk"), 1, native) is native
