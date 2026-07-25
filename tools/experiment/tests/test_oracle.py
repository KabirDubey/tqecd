"""Tests for the oracle framework (pure ``stim`` + ``numpy``)."""

from __future__ import annotations

import stim

from tools.experiment.oracle import (
    NativeFixedBulkOracle,
    available_oracles,
    build_oracles,
    logically_equivalent,
)


class _Unit:
    def __init__(self, convention):
        self.convention = convention


def _circuit(detectors: str) -> stim.Circuit:
    return stim.Circuit(f"R 0 1\nM 0 1\n{detectors}")


def test_registry():
    assert "native_fixed_bulk" in available_oracles()
    assert isinstance(build_oracles(["native_fixed_bulk"])[0], NativeFixedBulkOracle)


def test_logically_equivalent_same_span():
    a = _circuit("DETECTOR rec[-2] rec[-1]")
    # a different but spanning-equivalent way of writing the same parity space
    b = _circuit("DETECTOR rec[-1] rec[-2]")
    assert logically_equivalent(a, b)


def test_logically_inequivalent_different_span():
    a = _circuit("DETECTOR rec[-2] rec[-1]\nOBSERVABLE_INCLUDE(0) rec[-1]")
    b = _circuit("DETECTOR rec[-2] rec[-1]")
    assert not logically_equivalent(a, b)


def test_native_fixed_bulk_oracle_applies_only_to_fixed_bulk():
    oracle = NativeFixedBulkOracle()
    assert oracle.applies(_Unit("fixed_bulk"), config=None)
    assert not oracle.applies(_Unit("fixed_boundary"), config=None)


def test_native_fixed_bulk_oracle_verdict():
    oracle = NativeFixedBulkOracle()
    native = _circuit("DETECTOR rec[-2] rec[-1]\nOBSERVABLE_INCLUDE(0) rec[-1]")
    verdict = oracle.compare(native, native)
    assert verdict.applies and verdict.equivalent
    assert verdict.oracle == "native_fixed_bulk"
