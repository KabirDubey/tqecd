"""Tests for report rendering (JSON / HTML / text); no ``tqec`` needed."""

from __future__ import annotations

import json

from tools.experiment.report import ExperimentReport, ExperimentRow


def _report() -> ExperimentReport:
    return ExperimentReport(
        rows=[
            ExperimentRow(
                gadget_id="g0", source="mem", name="cnot", convention="fixed_bulk",
                k=1, manhattan_radius=2, window=2, status="ready", status_kind="pass",
                missing_parities=0, parities_ok=True, distance=3, expected_distance=3,
                distance_ok=True, predictors_pass=True, native_missing=0,
                oracle_verdicts={"user_ref": {"equivalent": True}},
            ),
            ExperimentRow(
                gadget_id="g1", source="mem", name="cnot", convention="fixed_bulk",
                k=1, manhattan_radius=2, window=2, status="compile_failed", status_kind="prep_fail",
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
