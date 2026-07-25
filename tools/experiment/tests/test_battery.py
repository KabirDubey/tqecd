"""The gadget-experiment battery (needs the optional ``tqec`` dependency).

Every assertion checks ground-truth-free invariants--zero missing parities and distance
``== 2k + 1`` for the re-annotated circuits--never native-equality. The invariant under test is:
**every prepared (READY) unit passes the predictors**; units ``tqec`` cannot compile yet (e.g.
spatial Hadamard on ``fixed_bulk``) are recorded as non-ready and excluded, not failed.
"""

from __future__ import annotations

import pytest

from tools.experiment import ExperimentConfig, run_experiment
from tools.experiment.tests.fixtures import (
    HADAMARD_DIRECTIONS,
    disjoint_union,
    hadamard_arrangements,
)

from tqec.gallery import cnot, three_cnots
from tqec.orchestration import BatchConfig, prepare_batch
from tqec.utils.enums import Basis

import stim

from tools.experiment import annotate
from tools.experiment.predictors import count_missing_parities


def _ready(report):
    return [r for r in report.rows if r.status == "ready" and r.k >= 0]


def _assert_all_ready_pass(report):
    ready = _ready(report)
    assert ready, "expected at least one READY unit"
    for row in ready:
        assert row.missing_parities == 0, f"{row.gadget_id}/{row.convention} k={row.k} missing"
        assert row.distance == row.expected_distance, (
            f"{row.gadget_id}/{row.convention} k={row.k} distance "
            f"{row.distance} != {row.expected_distance}"
        )
        assert row.predictors_pass is True
    return ready


# 0. reannotate() on a real prepared gadget preserves observables and attaches completely --------
def test_reannotate_real_gadget(out_dir):
    manifest = prepare_batch(
        [cnot(Basis.Z)], BatchConfig(conventions=("fixed_bulk",), ks=(1,), manhattan_radius=2),
        out_dir,
    )
    unit = manifest.units[0]
    native = stim.Circuit.from_file(manifest.run_dir / unit.circuits[1])
    reannotated = annotate.reannotate(native, window=2)
    assert reannotated.num_observables == native.num_observables
    assert reannotated.num_measurements == native.num_measurements
    assert count_missing_parities(reannotated) == 0


# 1. Two CNOTs, different observable bases -------------------------------------
def test_two_cnots_different_observables(out_dir):
    config = ExperimentConfig(conventions=("fixed_bulk",), ks=(1, 2), windows=(2,))
    report = run_experiment([cnot(Basis.X), cnot(Basis.Z)], config, out_dir)
    ready = _assert_all_ready_pass(report)
    # both gadgets present
    assert len({r.gadget_id for r in ready}) == 2


# 2. One CNOT with open ports --------------------------------------------------
def test_cnot_open_ports(out_dir):
    config = ExperimentConfig(conventions=("fixed_bulk",), ks=(1,), windows=(2,),
                              logical_observables="all")
    report = run_experiment([cnot(None)], config, out_dir)
    _assert_all_ready_pass(report)


# 3. Across conventions, with the native_fixed_bulk oracle ---------------------
def test_across_conventions_with_oracle(out_dir):
    config = ExperimentConfig(conventions=("fixed_bulk", "fixed_boundary"), ks=(1,),
                              windows=(2,), oracles=("native_fixed_bulk",))
    report = run_experiment([cnot(Basis.Z)], config, out_dir)
    ready = _assert_all_ready_pass(report)
    by_conv = {r.convention: r for r in ready}
    assert set(by_conv) == {"fixed_bulk", "fixed_boundary"}
    # oracle applies to fixed_bulk (equivalent to native) and not to fixed_boundary
    assert by_conv["fixed_bulk"].oracle_verdicts["native_fixed_bulk"]["equivalent"] is True
    assert by_conv["fixed_boundary"].oracle_verdicts == {}


# 4. Two disjoint CNOTs in one input, swept over k ----------------------------
def test_two_disjoint_cnots_split(out_dir):
    graph = disjoint_union(cnot(Basis.Z), cnot(Basis.Z))
    config = ExperimentConfig(conventions=("fixed_bulk",), ks=(1, 2), windows=(2,))
    report = run_experiment([graph], config, out_dir)
    ready = _assert_all_ready_pass(report)
    assert len({r.gadget_id for r in ready}) == 2  # split into two gadgets


# 5. cnot + three_cnots in one graph (progressively larger), swept over k -----
def test_progressively_larger_gadgets(out_dir):
    graph = disjoint_union(cnot(Basis.Z), three_cnots(Basis.Z))
    config = ExperimentConfig(conventions=("fixed_bulk",), ks=(1, 2), windows=(2,))
    report = run_experiment([graph], config, out_dir)
    ready = _assert_all_ready_pass(report)
    assert len({r.gadget_id for r in ready}) == 2


# 6. FINAL A--every arrangement of a Hadamard pipe --------------------------
def test_hadamard_arrangements_all_directions(out_dir):
    graphs = hadamard_arrangements()
    assert set(graphs) == set(HADAMARD_DIRECTIONS)
    config = ExperimentConfig(conventions=("fixed_bulk", "fixed_boundary"), ks=(1,), windows=(2,))
    report = run_experiment(list(graphs.values()), config, out_dir)
    # every unit tqec could compile attaches correctly...
    ready = _assert_all_ready_pass(report)
    # ...and temporal (z) Hadamard compiles on both conventions (spatial fixed_bulk is not yet
    # implemented in tqec, so it is legitimately recorded as compile_failed, not asserted here).
    z_ready = [r for r in ready if "hadamard_z" in r.gadget_id]
    assert {r.convention for r in z_ready} == {"fixed_bulk", "fixed_boundary"}


# 7. FINAL B--sensitivity to manhattan_radius -------------------------------
def test_manhattan_radius_sweep(out_dir):
    # Sweeps the radius knob and records the (radius -> native_missing / distance) response. For a
    # simple gadget like cnot the response is flat (radius-insensitive)--itself a correct,
    # reportable result; harder gadgets are where a small radius starves the native annotation.
    config = ExperimentConfig(conventions=("fixed_bulk",), ks=(1,), windows=(2,),
                              manhattan_radii=(1, 2, 3))
    report = run_experiment([cnot(Basis.Z)], config, out_dir)
    ready = _ready(report)
    assert {r.manhattan_radius for r in ready} == {1, 2, 3}
    for row in ready:
        assert row.missing_parities is not None
        assert row.native_missing is not None
        assert row.distance is not None
    # reannotated annotation is complete at every radius (tqecd uses `window`, not manhattan_radius)
    _assert_all_ready_pass(report)
