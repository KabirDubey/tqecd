"""Experiment rows and reports: ``report.json`` + a self-contained ``report.html`` + text.

Heavy formatting libraries are all optional. ``orjson`` is used for JSON when present (stdlib
``json`` otherwise); ``polars`` for CSV/Parquet export and pivots when present; the HTML is a
single self-contained file (inline CSS/JS, no CDN) so it needs no template engine, though
``minijinja`` is used if available.
"""

from __future__ import annotations

import html
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

try:  # optional, fast, Rust-backed
    import orjson

    def _dumps(obj: Any) -> bytes:
        return orjson.dumps(obj, option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS)
except ModuleNotFoundError:  # pragma: no cover - fallback

    def _dumps(obj: Any) -> bytes:
        return json.dumps(obj, indent=2, sort_keys=True).encode()


@dataclass
class ExperimentRow:
    """One measured (gadget, convention, k, radius, window) cell."""

    gadget_id: str
    source: str
    name: str
    convention: str
    k: int
    manhattan_radius: int
    window: int
    status: str
    missing_parities: int | None = None
    parities_ok: bool | None = None
    distance: int | None = None
    expected_distance: int | None = None
    distance_ok: bool | None = None
    predictors_pass: bool | None = None
    native_missing: int | None = None
    oracle_verdicts: dict[str, dict[str, Any]] = field(default_factory=dict)
    ler_plot: str | None = None
    lambda_factor: float | None = None
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ExperimentReport:
    """A collection of rows plus JSON / HTML / text renderers."""

    rows: list[ExperimentRow] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    # summary
    def summary(self) -> dict[str, int]:
        scored = [r for r in self.rows if r.predictors_pass is not None]
        return {
            "rows": len(self.rows),
            "scored": len(scored),
            "predictors_pass": sum(1 for r in scored if r.predictors_pass),
            "predictors_fail": sum(1 for r in scored if not r.predictors_pass),
            "skipped": sum(1 for r in self.rows if r.predictors_pass is None),
        }

    # serialization
    def to_dict(self) -> dict[str, Any]:
        return {
            "meta": self.meta,
            "summary": self.summary(),
            "rows": [r.to_dict() for r in self.rows],
        }

    def write(self, out_dir: str | Path) -> Path:
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "report.json").write_bytes(_dumps(self.to_dict()))
        (out / "report.html").write_text(self.to_html(), encoding="utf-8")
        (out / "report.txt").write_text(self.to_text(), encoding="utf-8")
        self._maybe_write_dataframe(out)
        return out / "report.json"

    def _maybe_write_dataframe(self, out: Path) -> None:
        try:
            import polars as pl
        except ModuleNotFoundError:
            return
        flat = []
        for r in self.rows:
            d = r.to_dict()
            d["oracle_verdicts"] = json.dumps(d["oracle_verdicts"])
            d.pop("ler_plot", None)  # data URI, keep it out of the table
            flat.append(d)
        if flat:
            pl.DataFrame(flat).write_csv(out / "report.csv")

    # text
    _COLUMNS = (
        ("gadget_id", "gadget"),
        ("convention", "conv"),
        ("k", "k"),
        ("manhattan_radius", "mr"),
        ("window", "win"),
        ("missing_parities", "missing"),
        ("distance", "dist"),
        ("expected_distance", "exp"),
        ("predictors_pass", "pass"),
    )

    def to_text(self) -> str:
        headers = [label for _, label in self._COLUMNS]
        table = [headers]
        for r in self.rows:
            table.append([_fmt(getattr(r, attr)) for attr, _ in self._COLUMNS])
        widths = [max(len(row[i]) for row in table) for i in range(len(headers))]
        lines = []
        for ridx, row in enumerate(table):
            lines.append("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)))
            if ridx == 0:
                lines.append("  ".join("-" * widths[i] for i in range(len(headers))))
        s = self.summary()
        footer = (
            f"\n{s['predictors_pass']}/{s['scored']} passed predictors "
            f"({s['predictors_fail']} failed, {s['skipped']} skipped)"
        )
        return "\n".join(lines) + footer

    # html
    def to_html(self) -> str:
        rows_html = "\n".join(self._row_html(r) for r in self.rows)
        s = self.summary()
        plots = "\n".join(
            f'<figure><figcaption>{html.escape(r.gadget_id)} '
            f'(conv={html.escape(r.convention)}, k={r.k})</figcaption>'
            f'<img src="{r.ler_plot}" alt="LER plot"/></figure>'
            for r in self.rows
            if r.ler_plot
        )
        plots_section = f'<section class="plots"><h2>LER plots</h2>{plots}</section>' if plots else ""
        return _HTML_TEMPLATE.format(
            summary=(
                f"{s['predictors_pass']}/{s['scored']} passed predictors, "
                f"{s['predictors_fail']} failed, {s['skipped']} skipped"
            ),
            rows=rows_html,
            plots=plots_section,
        )

    def _row_html(self, r: ExperimentRow) -> str:
        if r.predictors_pass is None:
            cls = "skip"
        elif r.predictors_pass:
            cls = "pass"
        else:
            cls = "fail"
        oracle = ", ".join(
            f"{name}:{'ok' if v.get('equivalent') else 'DIFF'}"
            for name, v in r.oracle_verdicts.items()
        )
        cells = [
            html.escape(r.gadget_id),
            html.escape(r.convention),
            str(r.k),
            str(r.manhattan_radius),
            str(r.window),
            _fmt(r.missing_parities),
            _fmt(r.distance),
            _fmt(r.expected_distance),
            _fmt(r.native_missing),
            html.escape(oracle) or "-",
            _fmt(r.predictors_pass),
        ]
        tds = "".join(f"<td>{c}</td>" for c in cells)
        return f'<tr class="{cls}">{tds}</tr>'


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if value is True:
        return "PASS"
    if value is False:
        return "FAIL"
    return str(value)


_HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Gadget experiment report</title>
<style>
:root {{ color-scheme: light dark; --bg:#fff; --fg:#111; --line:#ddd; --pass:#1a7f37; --fail:#cf222e; --skip:#57606a; --head:#f6f8fa; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#0d1117; --fg:#e6edf3; --line:#30363d; --pass:#3fb950; --fail:#f85149; --skip:#8b949e; --head:#161b22; }} }}
body {{ font-family: ui-sans-serif, system-ui, sans-serif; margin: 2rem; background: var(--bg); color: var(--fg); }}
h1 {{ font-size: 1.4rem; }}
.summary {{ margin: .5rem 0 1.5rem; font-size: 1.05rem; }}
.wrap {{ overflow-x: auto; }}
table {{ border-collapse: collapse; width: 100%; font-variant-numeric: tabular-nums; }}
th, td {{ padding: .35rem .6rem; border-bottom: 1px solid var(--line); text-align: left; white-space: nowrap; }}
th {{ background: var(--head); cursor: pointer; position: sticky; top: 0; }}
tr.pass td:last-child {{ color: var(--pass); font-weight: 600; }}
tr.fail td:last-child {{ color: var(--fail); font-weight: 600; }}
tr.skip td {{ color: var(--skip); }}
figure {{ margin: 1rem 0; }} img {{ max-width: 100%; }}
</style>
</head>
<body>
<h1>Gadget experiment report</h1>
<div class="summary">{summary}</div>
<div class="wrap">
<table id="t">
<thead><tr>
<th>gadget</th><th>conv</th><th>k</th><th>mr</th><th>win</th>
<th>missing</th><th>dist</th><th>exp</th><th>native&nbsp;missing</th><th>oracle</th><th>predictors</th>
</tr></thead>
<tbody>
{rows}
</tbody>
</table>
</div>
{plots}
<script>
document.querySelectorAll('#t th').forEach((th, i) => th.addEventListener('click', () => {{
  const tb = th.closest('table').tBodies[0];
  const rows = [...tb.rows];
  const asc = th.dataset.asc = th.dataset.asc === 'true' ? '' : 'true';
  rows.sort((a, b) => {{
    const x = a.cells[i].innerText, y = b.cells[i].innerText;
    const nx = parseFloat(x), ny = parseFloat(y);
    const cmp = (!isNaN(nx) && !isNaN(ny)) ? nx - ny : x.localeCompare(y);
    return asc ? cmp : -cmp;
  }});
  rows.forEach(r => tb.appendChild(r));
}}));
</script>
</body>
</html>
"""
