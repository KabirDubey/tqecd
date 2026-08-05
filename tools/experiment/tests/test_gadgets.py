"""Gadget experiment tests (need the optional ``tqec`` dependency).

Every assertion checks ground-truth-free invariants--zero missing parities and distance
``== 2k + 1`` for the re-annotated circuits--never native-equality. The invariant under test is:
**every prepared (READY) unit passes the predictors**; units ``tqec`` cannot compile yet (e.g.
spatial Hadamard on ``fixed_bulk``) are recorded as non-ready and excluded, not failed.
"""

from __future__ import annotations

import json

import pytest

from tools.experiment import (
    ExperimentConfig,
    reannotate_run,
    render_report,
    run_experiment,
    simulate_run,
)
from tools.experiment.tests.fixtures import (
    HADAMARD_DIRECTIONS,
    disjoint_union,
    hadamard_arrangements,
)

from tqec.gallery import cnot, memory, three_cnots
from tqec.orchestration import BatchConfig, prepare_batch
from tqec.utils.enums import Basis

import stim

from tools.experiment import annotators
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


# reannotate() on a real prepared gadget preserves observables and attaches completely
def test_reannotate_real_gadget(out_dir):
    manifest = prepare_batch(
        [cnot(Basis.Z)], BatchConfig(conventions=("fixed_bulk",), ks=(1,), manhattan_radius=2),
        out_dir,
    )
    unit = manifest.units[0]
    native = stim.Circuit.from_file(manifest.run_dir / unit.circuits[1])
    reannotated = annotators.reannotate(native, window=2)
    assert reannotated.num_observables == native.num_observables
    assert reannotated.num_measurements == native.num_measurements
    assert count_missing_parities(reannotated) == 0


# Two CNOTs, different observable bases
def test_two_cnots_different_observables(out_dir):
    config = ExperimentConfig(conventions=("fixed_bulk",), ks=(1, 2), windows=(2,))
    report = run_experiment([cnot(Basis.X), cnot(Basis.Z)], config, out_dir)
    ready = _assert_all_ready_pass(report)
    # both gadgets present
    assert len({r.gadget_id for r in ready}) == 2


# One CNOT with open ports
def test_cnot_open_ports(out_dir):
    config = ExperimentConfig(conventions=("fixed_bulk",), ks=(1,), windows=(2,),
                              logical_observables="all")
    report = run_experiment([cnot(None)], config, out_dir)
    _assert_all_ready_pass(report)


# Across conventions, plus an opt-in user-supplied reference oracle
def test_across_conventions_with_user_oracle(out_dir):
    from tools.experiment.oracle import CallableOracle

    # Oracles are optional and never default. A user who trusts native for fixed_bulk can wire it
    # in explicitly; here it echoes the native circuit and applies only to fixed_bulk.
    user_oracle = CallableOracle(
        "user_native_fixed_bulk",
        emit=lambda unit, k, native: native,
        applies_to=lambda unit, config: unit.convention == "fixed_bulk",
    )
    config = ExperimentConfig(conventions=("fixed_bulk", "fixed_boundary"), ks=(1,), windows=(2,))
    report = run_experiment([cnot(Basis.Z)], config, out_dir, oracles=[user_oracle])
    ready = _assert_all_ready_pass(report)
    by_conv = {r.convention: r for r in ready}
    assert set(by_conv) == {"fixed_bulk", "fixed_boundary"}
    assert by_conv["fixed_bulk"].oracle_results["user_native_fixed_bulk"]["equivalent"] is True
    assert by_conv["fixed_boundary"].oracle_results == {}


# Two disjoint CNOTs in one input, swept over k
def test_two_disjoint_cnots_split(out_dir):
    graph = disjoint_union(cnot(Basis.Z), cnot(Basis.Z))
    config = ExperimentConfig(conventions=("fixed_bulk",), ks=(1, 2), windows=(2,))
    report = run_experiment([graph], config, out_dir)
    ready = _assert_all_ready_pass(report)
    assert len({r.gadget_id for r in ready}) == 2  # split into two gadgets


# cnot + three_cnots in one graph (progressively larger), swept over k
def test_progressively_larger_gadgets(out_dir):
    graph = disjoint_union(cnot(Basis.Z), three_cnots(Basis.Z))
    config = ExperimentConfig(conventions=("fixed_bulk",), ks=(1, 2), windows=(2,))
    report = run_experiment([graph], config, out_dir)
    ready = _assert_all_ready_pass(report)
    assert len({r.gadget_id for r in ready}) == 2


# FINAL A: every arrangement of a Hadamard pipe
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


# reannotate_run re-scores a run from its on-disk circuits without recompiling
def test_reannotate_reuses_prepared_circuits(out_dir):
    config = ExperimentConfig(conventions=("fixed_bulk",), ks=(1,), windows=(2,))
    original = run_experiment([cnot(Basis.Z)], config, out_dir)
    # the full config is persisted so a later reannotate can recover it
    assert (out_dir / "config.json").is_file()
    assert ExperimentConfig.from_dict(
        json.loads((out_dir / "config.json").read_text())
    ) == config

    # leave the prepared circuits intact and just re-annotate off disk. No prepare_batch is called.
    rescored = reannotate_run(out_dir)
    assert [(r.gadget_id, r.convention, r.k, r.window) for r in _ready(rescored)] == [
        (r.gadget_id, r.convention, r.k, r.window) for r in _ready(original)
    ]
    _assert_all_ready_pass(rescored)


# reannotate can re-score with a different tqecd window without recompiling
def test_reannotate_window_override(out_dir):
    config = ExperimentConfig(conventions=("fixed_bulk",), ks=(1,), windows=(2,))
    run_experiment([cnot(Basis.Z)], config, out_dir)
    rescored = reannotate_run(out_dir, overrides={"windows": (3,)})
    ready = _ready(rescored)
    assert ready and {r.window for r in ready} == {3}
    _assert_all_ready_pass(rescored)


# reannotate on a directory with no prepared circuits fails clearly rather than silently emptily
def test_reannotate_without_prepared_circuits(tmp_path):
    empty = tmp_path / "cleaned_run"
    empty.mkdir()
    with pytest.raises(FileNotFoundError, match="no prepared circuits"):
        reannotate_run(empty)


# render rebuilds report.html from report.json alone--no circuits, no annotation, no re-score
def test_render_rebuilds_ui_from_report_json(out_dir):
    config = ExperimentConfig(conventions=("fixed_bulk",), ks=(1,), windows=(2,))
    original = run_experiment([cnot(Basis.Z)], config, out_dir)

    # remove everything except report.json: the prepared circuits, the HTML, the config.
    import shutil
    shutil.rmtree(out_dir / "prepared")
    (out_dir / "report.html").unlink()
    (out_dir / "config.json").unlink()

    rebuilt = render_report(out_dir)
    # the report is reconstructed identically from report.json...
    assert [r.to_dict() for r in rebuilt.rows] == [r.to_dict() for r in original.rows]
    assert rebuilt.gadget_visuals == original.gadget_visuals
    # ...and report.html is regenerated with its embedded pictures and links.
    html_text = (out_dir / "report.html").read_text()
    assert 'data-col="links"' in html_text and "data:image/png" in html_text


# render fails clearly when there is no report.json to rebuild from
def test_render_without_report_json(tmp_path):
    empty = tmp_path / "no_report"
    empty.mkdir()
    with pytest.raises(FileNotFoundError, match="no report.json"):
        render_report(empty)


# every scored row records the wall time of annotation + analysis
def test_runtime_recorded(out_dir):
    config = ExperimentConfig(conventions=("fixed_bulk",), ks=(1,), windows=(2,))
    report = run_experiment([cnot(Basis.Z)], config, out_dir)
    scored = _ready(report)
    assert scored and all(r.runtime_s is not None and r.runtime_s > 0 for r in scored)


# the 3D block-graph link and ZX picture are produced even for a pipeless single-cube gadget
# (tqec's BlockGraph.from_json rejects those; the tool's tolerant loader must handle them)
def test_gadget_visuals_for_pipeless_gadget(out_dir):
    config = ExperimentConfig(conventions=("fixed_bulk",), ks=(1,), windows=(2,))
    report = run_experiment([memory(Basis.Z)], config, out_dir)
    gid = _ready(report)[0].gadget_id
    gv = report.gadget_visuals.get(gid, {})
    assert gv.get("block_graph_html"), "single-cube gadget must still get a 3D block-graph link"
    assert gv.get("zx_png") or gv.get("zx_link"), "single-cube gadget must still get a ZX picture"
    # stim circuit diagrams are no longer embedded in any row
    assert all("diagrams" not in (r.visuals or {}) for r in report.rows)


# a block graph with more than ZX_INLINE_MAX_NODES cubes gets a linked ZX image, not an inlined one
def test_zx_linked_for_large_graph(out_dir, monkeypatch):
    from tools.experiment import visuals
    monkeypatch.setattr(visuals, "ZX_INLINE_MAX_NODES", 0)  # force the "large graph" path
    config = ExperimentConfig(conventions=("fixed_bulk",), ks=(1,), windows=(2,))
    report = run_experiment([cnot(Basis.Z)], config, out_dir)
    gid = _ready(report)[0].gadget_id
    gv = report.gadget_visuals.get(gid, {})
    assert gv.get("zx_link") and not gv.get("zx_png"), "large graph must link the ZX, not inline it"
    assert (out_dir / gv["zx_link"]).is_file(), "the linked ZX PNG must exist on disk"


# simulate_run measures the prepared circuits under a chosen noise model without recompiling
def test_simulate_run_measures_without_rebuild(out_dir):
    pytest.importorskip("sinter")
    pytest.importorskip("pymatching")
    from tools.experiment.config import SimulationConfig
    config = ExperimentConfig(conventions=("fixed_bulk",), ks=(1,), windows=(2,),
                              simulation=SimulationConfig(max_shots=200))
    run_experiment([cnot(Basis.Z)], config, out_dir)
    report = simulate_run(out_dir, noise_models=("uniform_depolarizing",), ps=(5e-3, 1e-2),
                          show_progress=False)
    mcmc = report.meta.get("mcmc", {})
    assert mcmc.get("enabled") and mcmc.get("results", 0) >= 1
    assert mcmc.get("gadgets")  # one MCMC record per (gadget, convention)
