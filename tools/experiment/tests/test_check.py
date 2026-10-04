"""Tests for :func:`check_circuit` / :func:`compare_circuits` and the ``--check`` CLI."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import stim

from tools.experiment import (
    ExperimentConfig,
    apply_noise,
    check_circuit,
    compare_circuits,
)
from tools.experiment.__main__ import main
from tools.experiment.core import _score
from tools.experiment.predictors import shortest_graphlike_error

NON_DETERMINISTIC = stim.Circuit("R 0\nH 0\nM 0\nDETECTOR rec[-1]")


def _memory(distance: int = 3, *, noisy: bool = False) -> stim.Circuit:
    """Stim's rotated Z memory, with ``MR`` split into ``M`` + ``R`` (tqec's noise models lack MR)."""
    p = 1e-3 if noisy else 0
    circuit = stim.Circuit.generated(
        "surface_code:rotated_memory_z",
        distance=distance,
        rounds=distance,
        after_clifford_depolarization=p,
        before_measure_flip_probability=p,
        after_reset_flip_probability=p,
    )
    lines = []
    for line in str(circuit).splitlines():
        stripped = line.lstrip()
        if stripped.startswith("MR"):
            indent = line[: len(line) - len(stripped)]
            gate, _, targets = stripped.partition(" ")
            lines += [
                f"{indent}M{gate[2:]} {targets}",
                f"{indent}TICK",
                f"{indent}R {targets}",
            ]
        else:
            lines.append(line)
    return stim.Circuit("\n".join(lines))


def _map_coordinates(
    circuit: stim.Circuit, scale: float, offset: float
) -> stim.Circuit:
    """``circuit`` with x, y coordinates mapped by ``scale * c + offset`` (shifts only scaled)."""
    out = stim.Circuit()
    for instruction in circuit:
        if isinstance(instruction, stim.CircuitRepeatBlock):
            body = _map_coordinates(instruction.body_copy(), scale, offset)
            out.append(stim.CircuitRepeatBlock(instruction.repeat_count, body))
            continue
        args = instruction.gate_args_copy()
        if instruction.name in ("QUBIT_COORDS", "DETECTOR"):
            args = [a * scale + offset if i < 2 else a for i, a in enumerate(args)]
        elif instruction.name == "SHIFT_COORDS":
            args = [a * scale if i < 2 else a for i, a in enumerate(args)]
        out.append(instruction.name, instruction.targets_copy(), args)
    return out


def test_deterministic_circuit_with_expected_distance_passes():
    result = check_circuit(_memory(3), expected_distance=3)
    assert result.deterministic and result.determinism_error is None
    assert result.missing_parities == 0 and result.parities_ok
    assert result.distance == 3 and result.distance_ok
    assert result.passed and result.failure_reasons() == []
    assert result.noise == "uniform_depolarizing(p=0.001)"
    assert result.summary().startswith("PASS")


def test_wrong_expected_distance_fails_with_a_reason():
    result = check_circuit(_memory(3), expected_distance=5)
    assert result.distance == 3 and result.distance_ok is False
    assert not result.passed
    assert result.failure_reasons() == ["distance 3 != expected 5"]


def test_without_expected_distance_the_distance_is_only_reported():
    result = check_circuit(_memory(3))
    assert result.distance == 3 and result.distance_ok is None and result.passed


def test_non_deterministic_circuit_fails_without_a_distance():
    result = check_circuit(NON_DETERMINISTIC, expected_distance=1)
    assert not result.deterministic
    assert "non-deterministic detectors" in result.determinism_error
    assert result.distance is None and result.distance_error is None
    assert result.distance_ok is False and not result.passed
    assert result.failure_reasons() == [result.determinism_error]


def test_missing_parity_fails():
    circuit = stim.Circuit("R 0 1\nM 0 1\nOBSERVABLE_INCLUDE(0) rec[-1]")
    result = check_circuit(circuit, noise_model=None)
    assert result.deterministic and result.missing_parities == 1
    assert result.parities_ok is False and not result.passed
    assert result.failure_reasons() == ["1 missing parity"]
    # No noise at all: the search finds no logical error, which is not a search failure.
    assert result.distance is None and result.distance_error is None


def test_disabled_checks_are_none():
    result = check_circuit(_memory(3), check_parities=False, check_distance=False)
    assert result.missing_parities is None and result.parities_ok is None
    assert result.distance is None and result.distance_ok is None
    assert not result.distance_checked and result.noise == ""
    assert result.passed


def test_noise_as_given_and_callable():
    noisy = _memory(3, noisy=True)
    assert check_circuit(noisy, noise_model=None, expected_distance=3).passed
    result = check_circuit(_memory(3), noise_model=lambda c: noisy, expected_distance=3)
    assert result.passed and result.noise == "callable"


def test_failed_distance_search_is_reported_not_swallowed():
    # Noise that adds a random detector makes stim's search raise; that is not "no logical error".
    def broken_noise(circuit: stim.Circuit) -> stim.Circuit:
        return apply_noise(circuit) + NON_DETERMINISTIC

    result = check_circuit(_memory(3), noise_model=broken_noise)
    assert result.deterministic and result.distance is None
    assert "non-deterministic" in result.distance_error
    assert not result.passed
    with pytest.raises(ValueError, match="non-deterministic"):
        shortest_graphlike_error(apply_noise(_memory(3)) + NON_DETERMINISTIC)


def test_unknown_noise_model_raises():
    with pytest.raises(ValueError, match="unknown noise model 'nope'"):
        apply_noise(_memory(3), "nope")
    with pytest.raises(ValueError, match="unknown noise model 'noisy_circuit'"):
        apply_noise(_memory(3), "noisy_circuit")


def test_check_reads_a_stim_file(tmp_path):
    path = tmp_path / "memory.stim"
    _memory(3).to_file(path)
    assert check_circuit(path, expected_distance=3).passed
    assert check_circuit(str(path), expected_distance=3).passed


def test_coordinate_transform_compares_equivalent():
    native = _memory(3)
    moved = _map_coordinates(native, 0.5, 1.0)
    assert moved != native
    comparison = compare_circuits(native, moved, expected_distance=3)
    assert comparison.same_dem_without_coords
    assert comparison.equivalent and comparison.differences() == []


def test_removed_gate_is_not_equivalent():
    native = _memory(3)
    text = str(native).replace(
        "CX 2 3 16 17 11 12 15 14 10 9 19 18", "CX 2 3 16 17 11 12 15 14 10 9", 1
    )
    damaged = stim.Circuit(text)
    assert damaged != native
    comparison = compare_circuits(native, damaged)
    assert not comparison.equivalent
    assert comparison.differences()


def test_renumbered_observable_is_not_equivalent():
    native = _memory(3)
    renumbered = stim.Circuit(
        str(native).replace("OBSERVABLE_INCLUDE(0)", "OBSERVABLE_INCLUDE(1)")
    )
    comparison = compare_circuits(native, renumbered, check_parities=False)
    assert comparison.a.distance == comparison.b.distance == 3
    assert comparison.same_dem_without_coords is False and not comparison.equivalent


def test_non_deterministic_circuits_are_never_equivalent():
    comparison = compare_circuits(NON_DETERMINISTIC, NON_DETERMINISTIC)
    assert comparison.same_dem_without_coords is None
    assert not comparison.equivalent
    assert "not comparable" in comparison.differences()[0]


def test_cli_check_one_and_two_files(tmp_path, capsys):
    native, moved = tmp_path / "native.stim", tmp_path / "moved.stim"
    _memory(3).to_file(native)
    _map_coordinates(_memory(3), 0.5, 1.0).to_file(moved)
    assert main(["--check", str(native), "--expected-distance", "3"]) == 0
    assert "PASS" in capsys.readouterr().out
    assert main(["--check", str(native), "--expected-distance", "5"]) == 1
    assert main(["--check", str(native), str(moved), "--noise-models", "si1000"]) == 0
    assert "equivalent" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        main(["--check", str(native), "--ps", "1e-3,2e-3"])


def test_core_scores_through_check_circuit():
    unit = SimpleNamespace(
        gadget_id="g", convention="fixed_bulk", status="ready", logical_observables=()
    )
    config = ExperimentConfig(expected_distance="2*k + 1")
    row = _score(NON_DETERMINISTIC, unit, 1, config)
    assert row.deterministic is False and row.predictors_pass is False
    assert "non-deterministic detectors" in row.notes
    row = _score(_memory(3), unit, 1, config)
    assert row.deterministic and row.distance == 3 and row.distance_ok
    assert row.missing_parities == 0 and row.predictors_pass and row.notes == ""


def test_extra_unused_detector_is_not_equivalent():
    a = stim.Circuit("R 0\nM 0\nDETECTOR rec[-1]")
    b = stim.Circuit("R 0\nM 0\nDETECTOR rec[-1]\nDETECTOR rec[-1]")
    comparison = compare_circuits(a, b, noise_model=None)
    assert comparison.same_dem_without_coords is False
    assert "num_detectors: 1 != 2" in comparison.differences()


def test_compare_reports_a_failing_noise_model_instead_of_raising():
    def broken_noise(circuit: stim.Circuit) -> stim.Circuit:
        return apply_noise(circuit) + NON_DETERMINISTIC

    comparison = compare_circuits(_memory(3), _memory(3), noise_model=broken_noise)
    assert comparison.same_dem_without_coords is None
    assert not comparison.equivalent


def test_core_parity_only_run_needs_no_noise_settings():
    unit = SimpleNamespace(
        gadget_id="g", convention="fixed_bulk", status="ready", logical_observables=()
    )
    config = ExperimentConfig(predictors=("parities",), noise_models=(), ps=())
    row = _score(_memory(3), unit, 1, config)
    assert row.missing_parities == 0 and row.distance is None and row.predictors_pass
