"""Tests for report rendering (JSON / HTML / text); no ``tqec`` needed."""

from __future__ import annotations

import json

from tools.experiment.report import ExperimentReport, ExperimentRow

_BASE_COLUMNS = (
    "result", "name", "block_graph", "zx", "observable", "convention",
    "k", "window", "missing", "distance", "expected", "runtime", "links", "notes", "input",
)


def _report() -> ExperimentReport:
    return ExperimentReport(
        rows=[
            ExperimentRow(
                gadget_id="g0", source="mem", name="cnot", convention="fixed_bulk",
                k=1, window=2, status="ready", status_kind="pass",
                missing_parities=0, parities_ok=True, distance=3, expected_distance=3,
                distance_ok=True, predictors_pass=True,
                oracle_results={"user_ref": {"equivalent": True, "distance": 3}},
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
    assert s["not_scored"] == 0 and s["predictors_fail"] == 0 and s["annotate_failed"] == 0


def test_annotate_fail_row_is_counted_and_rendered():
    # a tqecd crash on a row -> annotate_fail badge, counted, and folded into the CLI exit code
    r = _report()
    r.rows.append(
        ExperimentRow(
            gadget_id="gx", source="mem", name="y", convention="fixed_bulk", k=1, window=2,
            status="ready", status_kind="annotate_fail", notes="TQECDException: boundary mismatch",
        )
    )
    s = r.summary()
    assert s["annotate_failed"] == 1 and s["predictors_fail"] == 1  # counts toward failure exit
    html = r.to_html()
    assert "annotate fail" in html and "TQECDException: boundary mismatch" in html


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
    for key in _BASE_COLUMNS:
        assert f'data-colcb="{key}"' in html, f"missing toggle for {key}"
    # the Gadget group header and per-column data-idx (for sorting) are present
    assert 'data-col="__group_gadget"' in html and 'data-idx="0"' in html
    # dropdown deprecated: no expand button / detail rows
    assert 'class="expand"' not in html and 'class="detail"' not in html
    # status column removed (item 9)
    assert 'data-colcb="status"' not in html


def test_oracle_columns_and_group_render():
    # item 2: oracles become a per-oracle column group [dist / equiv / stim].
    report = _report()
    report.meta = {"oracles": ["native"], "predictors": ["parities", "distance"]}
    report.rows[0].oracle_results = {"native": {"equivalent": True, "distance": 3, "stim": "a.stim"}}
    html = report.to_html()
    assert 'data-col="__group_oracle:native"' in html
    for sub in ("dist", "eq", "stim"):
        assert f'data-colcb="oracle:native:{sub}"' in html
    assert "a.stim" in html  # the oracle's stim link


def test_mcmc_section_renders_when_present():
    # items 5b/6/12: an MCMC section (per-gadget plot + setup links) appears only when sampled.
    report = _report()
    assert 'class="mcmc"' not in report.to_html()  # no MCMC section by default
    report.meta = {"mcmc": {"enabled": True, "aggregate": "success", "results": 4,
                            "setup": "mcmc/setup.txt",
                            "gadgets": [{"gadget_id": "g0", "convention": "fixed_bulk",
                                         "plot": "mcmc/ler_g0.png", "lambda": 2.5}]}}
    html = report.to_html()
    assert 'class="mcmc"' in html and "mcmc/ler_g0.png" in html and "mcmc/setup.txt" in html


def test_top_header_shows_name_and_config_link():
    # item 11: experiment name + timestamp + config.toml link at the top.
    report = _report()
    report.meta = {"name": "my run", "timestamp": "2026-08-05 07:16", "config": "config.toml"}
    html = report.to_html()
    assert "my run" in html and "2026-08-05 07:16" in html
    assert 'href="config.toml"' in html


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
