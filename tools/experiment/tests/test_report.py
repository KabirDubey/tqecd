"""Tests for report rendering (JSON / HTML / text); no ``tqec`` needed."""

from __future__ import annotations

import json

from tools.experiment.report import _COL_SPECS, ExperimentReport, ExperimentRow


def _report() -> ExperimentReport:
    return ExperimentReport(
        rows=[
            ExperimentRow(
                gadget_id="g0", source="mem", name="cnot", convention="fixed_bulk",
                k=1, window=2, status="ready", status_kind="pass",
                missing_parities=0, parities_ok=True, distance=3, expected_distance=3,
                distance_ok=True, predictors_pass=True, native_missing=0,
                oracle_verdicts={"user_ref": {"equivalent": True}},
            ),
            ExperimentRow(
                gadget_id="g1", source="mem", name="cnot", convention="fixed_bulk",
                k=1, window=2, status="compile_failed", status_kind="prep_fail",
            ),
        ]
    )


def test_summary_counts():
    s = _report().summary()
    assert s["rows"] == 2 and s["scored"] == 1
    assert s["passed"] == 1 and s["predictor_failed"] == 0 and s["prep_failed"] == 1
    assert s["not_scored"] == 0 and s["predictors_fail"] == 0


def test_write_produces_all_artifacts(tmp_path):
    _report().write(tmp_path)
    assert (tmp_path / "report.json").exists()
    assert (tmp_path / "report.html").exists()
    assert (tmp_path / "report.txt").exists()
    data = json.loads((tmp_path / "report.json").read_text())
    assert data["summary"]["passed"] == 1
    assert len(data["rows"]) == 2


def test_html_is_self_contained(tmp_path):
    html = _report().to_html()
    assert "<table" in html and "badge" in html
    # no external resources (self-contained, CSP-friendly)
    assert "http://" not in html and "https://" not in html and "cdn" not in html.lower()


def test_every_column_has_a_toggle_checkbox():
    # item 6: all columns toggleable -- one menu checkbox per leaf column.
    html = _report().to_html()
    for key, _, _ in _COL_SPECS:
        assert f'data-colcb="{key}"' in html, f"missing toggle for {key}"
    # the Gadget group header and per-column data-idx (for sorting) are present
    assert 'data-col="__group_gadget"' in html and 'data-idx="0"' in html


def test_observable_and_failure_notes_render():
    # items 4 + 5: observable in its own column; a predictor failure's reason in Notes.
    report = ExperimentReport(
        rows=[
            ExperimentRow(
                gadget_id="g", source="mem", name="cnot", convention="fixed_bulk",
                k=2, window=2, status="ready",
                status_kind="predictor_fail", missing_parities=0, parities_ok=True,
                distance=1, expected_distance=5, distance_ok=False, predictors_pass=False,
                observable="XXXI", notes="distance 1 != expected 5",
            )
        ]
    )
    html = report.to_html()
    assert 'data-col="observable"' in html and "XXXI" in html
    # the failure reason shows in the Notes cell and in the result badge's hover tooltip (item 9)
    assert 'data-col="notes"' in html and "distance 1 != expected 5" in html
    assert 'title="predictor fail: distance 1 != expected 5"' in html
