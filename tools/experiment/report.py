"""Experiment rows and reports: ``report.json`` + a self-contained ``report.html`` + text + CSV.

``report.json`` is the authoritative detailed artifact; ``report.html`` is the human-facing view.
The HTML is a single self-contained file (inline CSS/JS, no CDN): each gadget's 3D block-graph link
and decorated ZX picture sit in their own columns beside the gadget name; every column is
toggleable; the result badge and observable explain themselves on hover; rows shade on hover; and
an expandable detail row carries oracle results, circuit links and the LER plot. Optional
``orjson`` is used for the JSON when present.
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


# status_kind values, each with a distinct visual state in the report.
PASS = "pass"
PREDICTOR_FAIL = "predictor_fail"
PREP_FAIL = "prep_fail"
NOT_SCORED = "not_scored"
SIM_FAIL = "sim_fail"

_BADGE_TEXT = {
    PASS: "pass",
    PREDICTOR_FAIL: "predictor fail",
    PREP_FAIL: "prep fail",
    NOT_SCORED: "not scored",
    SIM_FAIL: "sim fail",
}

# Leaf columns in display order: (key, label, default_visible). Every column is toggleable.
# name / block_graph / zx are the subcolumns of the "Gadget" group in the two-row header.
_COL_SPECS: tuple[tuple[str, str, bool], ...] = (
    ("result", "Result", True),
    ("name", "Gadget", True),
    ("block_graph", "3D", True),
    ("zx", "ZX", True),
    ("observable", "Observable", True),
    ("convention", "Convention", True),
    ("k", "k", True),
    ("radius", "Radius", False),
    ("window", "Window", True),
    ("missing", "Missing parities", True),
    ("distance", "Distance", True),
    ("expected", "Expected", False),
    ("native", "Native missing", False),
    ("lambda", "Lambda", False),
    ("runtime", "Runtime (s)", False),
    ("links", "Links", True),
    ("notes", "Notes", True),
    ("source", "Source", False),
    ("status", "Status", False),
)
_NLEAF = len(_COL_SPECS)


@dataclass
class ExperimentRow:
    """One measured (gadget, convention, k, Manhattan radius, window) cell."""

    gadget_id: str
    source: str
    name: str
    convention: str
    k: int
    manhattan_radius: int
    window: int
    status: str
    status_kind: str = NOT_SCORED
    missing_parities: int | None = None
    parities_ok: bool | None = None
    distance: int | None = None
    expected_distance: int | None = None
    distance_ok: bool | None = None
    predictors_pass: bool | None = None
    native_missing: int | None = None
    observable: str = ""
    oracle_verdicts: dict[str, dict[str, Any]] = field(default_factory=dict)
    visuals: dict[str, Any] = field(default_factory=dict)
    ler_plot: str | None = None
    lambda_factor: float | None = None
    runtime_s: float | None = None
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExperimentRow:
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class ExperimentReport:
    """A collection of rows plus JSON / HTML / text / CSV renderers."""

    rows: list[ExperimentRow] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
    gadget_visuals: dict[str, dict[str, Any]] = field(default_factory=dict)

    def summary(self) -> dict[str, int]:
        counts = {PASS: 0, PREDICTOR_FAIL: 0, PREP_FAIL: 0, NOT_SCORED: 0, SIM_FAIL: 0}
        for row in self.rows:
            counts[row.status_kind] = counts.get(row.status_kind, 0) + 1
        scored = counts[PASS] + counts[PREDICTOR_FAIL]
        return {
            "rows": len(self.rows),
            "scored": scored,
            "passed": counts[PASS],
            "predictor_failed": counts[PREDICTOR_FAIL],
            "prep_failed": counts[PREP_FAIL],
            "sim_failed": counts[SIM_FAIL],
            "not_scored": counts[NOT_SCORED],
            # kept for backwards-compatible callers / CLI exit code
            "predictors_fail": counts[PREDICTOR_FAIL],
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "meta": self.meta,
            "summary": self.summary(),
            "gadget_visuals": self.gadget_visuals,
            "rows": [r.to_dict() for r in self.rows],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExperimentReport:
        """Reconstruct a report from a serialized ``report.json`` payload (round-trips ``to_dict``)."""
        return cls(
            rows=[ExperimentRow.from_dict(r) for r in data.get("rows", [])],
            meta=data.get("meta", {}),
            gadget_visuals=data.get("gadget_visuals", {}),
        )

    @classmethod
    def from_json(cls, path: str | Path) -> ExperimentReport:
        """Load a report from a ``report.json`` file or the run directory that contains it."""
        path = Path(path)
        if path.is_dir():
            path = path / "report.json"
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def write(self, out_dir: str | Path) -> Path:
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "report.json").write_bytes(_dumps(self.to_dict()))
        (out / "report.html").write_text(self.to_html(), encoding="utf-8")
        (out / "report.txt").write_text(self.to_text(), encoding="utf-8")
        return out / "report.json"

    # Plain-text table: readable column names, no abbreviations that need a key.
    _COLUMNS = (
        ("status_kind", "result"),
        ("gadget_id", "gadget"),
        ("observable", "observable"),
        ("convention", "convention"),
        ("k", "k"),
        ("manhattan_radius", "radius"),
        ("window", "window"),
        ("missing_parities", "missing parities"),
        ("distance", "distance"),
        ("expected_distance", "expected"),
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
            f"\n{s['passed']}/{s['scored']} scored gadgets passed "
            f"({s['predictor_failed']} predictor failures, {s['prep_failed']} prep failures, "
            f"{s['not_scored']} not scored)"
        )
        runtimes = [r.runtime_s for r in self.rows if r.runtime_s is not None]
        if runtimes:
            footer += (
                f"\nruntime: {sum(runtimes):.2f}s total, "
                f"{sum(runtimes) / len(runtimes):.3f}s mean over {len(runtimes)} scored rows "
                "(annotation + analysis)"
            )
        return "\n".join(lines) + footer

    def to_html(self) -> str:
        rows_html = "\n".join(self._row_html(i, r) for i, r in enumerate(self.rows))
        s = self.summary()
        chips = "".join(
            f'<button class="chip" data-filter="{key}">{label}: <b>{s[key]}</b></button>'
            for key, label in (
                ("rows", "rows"),
                ("passed", "passed"),
                ("predictor_failed", "predictor failures"),
                ("prep_failed", "prep failures"),
                ("not_scored", "not scored"),
            )
        )
        has_plots = any(r.ler_plot for r in self.rows)
        show_plots = "" if has_plots else ' style="display:none"'
        html_out = _HTML
        html_out = html_out.replace("__CHIPS__", chips)
        html_out = html_out.replace("__HEADER__", self._header_html())
        html_out = html_out.replace("__MENU__", self._menu_html())
        html_out = html_out.replace("__DEFAULTS__", self._defaults_json())
        html_out = html_out.replace("__ROWS__", rows_html)
        html_out = html_out.replace("__SHOWPLOTS__", show_plots)
        return html_out

    def _row_html(self, index: int, r: ExperimentRow) -> str:
        gv = self.gadget_visuals.get(r.gadget_id, {})
        badge = _BADGE_TEXT.get(r.status_kind, r.status_kind or "?")
        explanation = _result_explanation(r)
        cells = [
            # 0 result -- the badge explains its pass/fail condition on hover (item 9)
            f'<td class="col-result" data-col="result"><span class="badge {r.status_kind}" '
            f'title="{html.escape(explanation)}">{html.escape(badge)}</span></td>',
            # 1 gadget name -- clicking it (or the arrow) expands the detail row
            f'<td class="col-gadget" data-col="name"><button class="expand" aria-expanded="false" '
            f'aria-controls="d{index}" title="show details">&#9656;</button>'
            f'<span class="gname" title="{html.escape(r.gadget_id)}">{html.escape(r.gadget_id)}</span></td>',
            # 2 3D block-graph link, 3 decorated ZX thumbnail -- Gadget subcolumns (item 3)
            f'<td data-col="block_graph">{_block_graph_cell(gv)}</td>',
            f'<td data-col="zx">{_zx_cell(gv)}</td>',
            _text_td(r.observable, "observable"),
            _text_td(r.convention, "convention"),
            _num_td(r.k, "k"),
            _num_td(r.manhattan_radius, "radius"),
            _num_td(r.window, "window"),
            _num_td(r.missing_parities, "missing"),
            _num_td(r.distance, "distance"),
            _num_td(r.expected_distance, "expected"),
            _num_td(r.native_missing, "native"),
            _num_td(r.lambda_factor, "lambda"),
            _num_td(r.runtime_s, "runtime"),
            self._links_cell(r),
            _text_td(r.notes, "notes"),
            _text_td(r.source, "source"),
            _text_td(r.status, "status"),
        ]
        main = (
            f'<tr class="datarow {r.status_kind}" data-kind="{r.status_kind}" '
            f'data-gadget="{html.escape(r.gadget_id.lower())}">'
            + "".join(cells)
            + "</tr>"
        )
        detail = (
            f'<tr class="detail" id="d{index}" hidden><td colspan="{_NLEAF}">'
            + self._detail_html(r, gv)
            + "</td></tr>"
        )
        return main + "\n" + detail

    def _links_cell(self, r: ExperimentRow) -> str:
        """Compact crumble / stim hyperlinks (the 3D link now has its own Gadget subcolumn)."""
        v = r.visuals or {}
        links: list[str] = []
        if v.get("crumble"):
            links.append(
                f'<a class="link" href="{html.escape(v["crumble"])}" target="_blank" '
                f'rel="noopener" title="open in crumble">crumble</a>'
            )
        if v.get("circuit"):
            links.append(
                f'<a class="link" href="{html.escape(v["circuit"])}" target="_blank" '
                f'rel="noopener" title="annotated .stim circuit">stim</a>'
            )
        inner = " &middot; ".join(links) if links else "&ndash;"
        return f'<td class="col-links" data-col="links">{inner}</td>'

    def _detail_html(self, r: ExperimentRow, gv: dict[str, Any]) -> str:
        parts: list[str] = []
        if r.oracle_verdicts:
            items = "".join(
                f"<li>{html.escape(name)}: "
                f"{'equivalent' if v.get('equivalent') else 'not equivalent'}"
                f" &mdash; {html.escape(str(v.get('detail', '')))}</li>"
                for name, v in r.oracle_verdicts.items()
            )
            parts.append(f"<div><b>oracles</b><ul>{items}</ul></div>")

        v = r.visuals or {}
        links: list[str] = []
        if v.get("crumble"):
            links.append(
                f'<a class="link" href="{html.escape(v["crumble"])}" target="_blank" rel="noopener">crumble</a>'
            )
        if v.get("circuit"):
            links.append(
                f'<a class="link" href="{html.escape(v["circuit"])}" target="_blank" rel="noopener">annotated circuit</a>'
            )
        if v.get("detector_free"):
            links.append(
                f'<a class="link" href="{html.escape(v["detector_free"])}" target="_blank" rel="noopener">detector-free circuit</a>'
            )
        if links:
            parts.append(
                '<div class="links"><b>circuit</b> ' + " &middot; ".join(links) + "</div>"
            )

        if r.ler_plot:
            parts.append(
                f'<figure class="ler"><figcaption>logical error rate</figcaption><img src="{r.ler_plot}" alt="LER plot"/></figure>'
            )

        return "".join(parts) or "<p><i>no additional details</i></p>"

    def _header_html(self) -> str:
        """Two-row header: a Gadget group spanning name / 3D / ZX; every other column is flat."""
        labels = {key: label for key, label, _ in _COL_SPECS}
        idx = {key: i for i, (key, _, _) in enumerate(_COL_SPECS)}
        numeric = {
            "k", "radius", "window", "missing", "distance",
            "expected", "native", "lambda", "runtime",
        }
        unsortable = {"block_graph", "zx", "links"}

        def th(key: str, rowspan: int = 1) -> str:
            cls = ' class="num"' if key in numeric else ""
            rs = f' rowspan="{rowspan}"' if rowspan != 1 else ""
            label = html.escape(labels[key])
            inner = label if key in unsortable else f'<button type="button">{label}</button>'
            sort = "" if key in unsortable else ' aria-sort="none"'
            return f'<th{cls} data-col="{key}" data-idx="{idx[key]}"{rs} scope="col"{sort}>{inner}</th>'

        row1 = [
            "<tr>",
            th("result", rowspan=2),
            '<th class="group" data-col="__group_gadget" colspan="3" scope="colgroup">Gadget</th>',
        ]
        for key, _, _ in _COL_SPECS:
            if key in ("result", "name", "block_graph", "zx"):
                continue
            row1.append(th(key, rowspan=2))
        row1.append("</tr>")
        row2 = ["<tr>", th("name"), th("block_graph"), th("zx"), "</tr>"]
        return "".join(row1) + "\n" + "".join(row2)

    def _menu_html(self) -> str:
        """A checkbox per column so every column is toggleable (item 6)."""
        return "".join(
            f'<label><input type="checkbox" data-colcb="{key}"/> {html.escape(label)}</label>'
            for key, label, _ in _COL_SPECS
        )

    def _defaults_json(self) -> str:
        return json.dumps({key: default for key, _, default in _COL_SPECS})


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if value is True:
        return "PASS"
    if value is False:
        return "FAIL"
    if isinstance(value, float):
        return f"{value:.3g}"
    return str(value)


def _text_td(value: Any, col: str) -> str:
    text = _fmt(value)
    return f'<td data-col="{col}" title="{html.escape(text)}">{html.escape(text)}</td>'


def _num_td(value: Any, col: str) -> str:
    text = _fmt(value)
    sort = "" if value is None else str(value)
    return (
        f'<td class="num" data-col="{col}" '
        f'data-sort-value="{html.escape(sort)}">{html.escape(text)}</td>'
    )


def _block_graph_cell(gv: dict[str, Any]) -> str:
    """The Gadget "3D" subcolumn: a link to the 3D block-graph viewer, or a dash."""
    href = gv.get("block_graph_html")
    if href:
        return (
            f'<a class="link" href="{html.escape(href)}" target="_blank" rel="noopener" '
            f'title="3D block graph with the observable surface">3D</a>'
        )
    return "&ndash;"


def _zx_cell(gv: dict[str, Any]) -> str:
    """The Gadget "ZX" subcolumn: an inline decorated-ZX thumbnail, a link, or a dash."""
    png = gv.get("zx_png")
    if png:
        return (
            f'<a href="{png}" target="_blank" rel="noopener" title="open full-size positioned ZX">'
            f'<img class="zxthumb" src="{png}" alt="positioned ZX with observable"/></a>'
        )
    link = gv.get("zx_link")
    if link:
        return (
            f'<a class="link" href="{html.escape(link)}" target="_blank" rel="noopener" '
            f'title="positioned ZX (large graph)">ZX</a>'
        )
    return "&ndash;"


def _result_explanation(r: ExperimentRow) -> str:
    """Plain-language reason for the row's result badge, shown as its hover tooltip (item 9)."""
    if r.status_kind == PASS:
        return (
            f"pass: annotation complete (0 missing parities) and "
            f"distance {r.distance} == expected {r.expected_distance}"
        )
    if r.status_kind == PREDICTOR_FAIL:
        return "predictor fail: " + (
            r.notes or "did not reach full distance / parity completeness"
        )
    if r.status_kind == PREP_FAIL:
        base = "prep fail: tqec could not prepare this gadget"
        return f"{base} ({r.notes})" if r.notes else base
    if r.status_kind == SIM_FAIL:
        return "sim fail: the simulation stage failed for this row"
    return "not scored: no predictors were run for this row"


_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Gadget experiment report</title>
<style>
:root { color-scheme: light dark; --bg:#fff; --fg:#111; --line:#d8dde3; --head:#f6f8fa; --muted:#57606a;
  --pass:#1a7f37; --pfail:#cf222e; --prep:#9a6700; --skip:#57606a; --sim:#8250df; --accent:#0969da; --hover:#eef1f4; }
@media (prefers-color-scheme: dark) { :root { --bg:#0d1117; --fg:#e6edf3; --line:#30363d; --head:#161b22;
  --muted:#8b949e; --pass:#3fb950; --pfail:#f85149; --prep:#d29922; --skip:#8b949e; --sim:#a371f7; --accent:#58a6ff; --hover:#1b2129; } }
* { box-sizing: border-box; }
body { font-family: ui-sans-serif, system-ui, sans-serif; margin: clamp(.5rem, 2vw, 2rem); background: var(--bg); color: var(--fg); }
h1 { font-size: 1.3rem; margin: 0 0 .25rem; }
caption { text-align: left; color: var(--muted); font-size: .85rem; padding: .25rem 0 .5rem; }
.bar { display: flex; flex-wrap: wrap; gap: .4rem; margin: .5rem 0; }
.chip { border: 1px solid var(--line); background: var(--head); color: var(--fg); border-radius: 999px;
  padding: .2rem .7rem; cursor: pointer; font-size: .85rem; }
.chip.active { outline: 2px solid var(--accent); }
.controls { display: flex; flex-wrap: wrap; gap: .6rem; align-items: center; margin: .6rem 0; }
.controls input[type=search] { padding: .3rem .5rem; border: 1px solid var(--line); border-radius: 6px; background: var(--bg); color: var(--fg); }
.seg button { border: 1px solid var(--line); background: var(--bg); color: var(--fg); padding: .25rem .6rem; cursor: pointer; }
.seg button:first-child { border-radius: 6px 0 0 6px; } .seg button:last-child { border-radius: 0 6px 6px 0; }
.seg button[aria-pressed=true] { background: var(--accent); color: #fff; }
details.cols summary { cursor: pointer; }
details.cols .menu { display: flex; flex-direction: column; gap: .2rem; padding: .4rem; border: 1px solid var(--line); border-radius: 6px; margin-top: .3rem; }
.switch { display: inline-flex; gap: .35rem; align-items: center; }
.wrap { overflow-x: auto; border: 1px solid var(--line); border-radius: 8px; }
table { border-collapse: collapse; width: 100%; font-variant-numeric: tabular-nums; }
th, td { padding: .35rem .55rem; border-bottom: 1px solid var(--line); text-align: left; white-space: nowrap; }
th { background: var(--head); position: sticky; top: 0; z-index: 2; }
th button { all: unset; cursor: pointer; font-weight: 600; }
th[aria-sort=ascending] button::after { content: " \25B2"; } th[aria-sort=descending] button::after { content: " \25BC"; }
td.num, th.num { text-align: right; }
th.group { text-align: center; border-left: 1px solid var(--line); border-right: 1px solid var(--line); }
tbody tr.datarow:hover > td { background: var(--hover); }
.zxthumb { max-height: 2.6rem; width: auto; border: 1px solid var(--line); background: #fff; vertical-align: middle; cursor: zoom-in; }
.hidden-col { display: none !important; }
.gname { cursor: pointer; display: inline-block; max-width: 16rem; overflow: hidden; text-overflow: ellipsis; vertical-align: bottom; }
.badge { font-size: .72rem; padding: .1rem .45rem; border-radius: 999px; color: #fff; }
.badge.pass { background: var(--pass); } .badge.predictor_fail { background: var(--pfail); }
.badge.prep_fail { background: var(--prep); } .badge.not_scored { background: var(--skip); } .badge.sim_fail { background: var(--sim); }
button.expand { all: unset; cursor: pointer; color: var(--muted); margin-right: .3rem; }
button.expand[aria-expanded=true] { transform: rotate(90deg); display: inline-block; }
tr.detail td { background: var(--head); white-space: normal; }
tr.detail .pics { display: flex; flex-wrap: wrap; gap: 1rem; align-items: flex-start; }
tr.detail figure { margin: .3rem 0; } tr.detail img, tr.detail svg { max-width: 22rem; height: auto; border: 1px solid var(--line); background: #fff; }
tr.detail figcaption { font-size: .8rem; color: var(--muted); }
.link { color: var(--accent); } .col-links a { margin-right: .4rem; white-space: nowrap; }
.notes { margin: .2rem 0; }
#announce { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
</style>
</head>
<body>
<h1>Gadget experiment report</h1>
<div class="bar">__CHIPS__</div>

<div class="controls">
  <label>Filter gadgets <input type="search" id="q" placeholder="gadget id..."/></label>
  <span class="seg" role="group" aria-label="result filter">
    <button type="button" data-seg="all" aria-pressed="true">All</button>
    <button type="button" data-seg="failed" aria-pressed="false">Failed</button>
    <button type="button" data-seg="not_scored" aria-pressed="false">Not scored</button>
  </span>
  <details class="cols"><summary>Columns</summary>
    <div class="menu">__MENU__</div>
  </details>
  <label class="switch"__SHOWPLOTS__><input type="checkbox" id="plots" checked/> Show plots</label>
</div>

<div class="wrap" tabindex="0">
<table id="t">
<caption>One row per (gadget, convention, k, radius, window). Click a header to sort; click a gadget name to expand its details. Use Columns to show or hide any column.</caption>
<thead>__HEADER__</thead>
<tbody>
__ROWS__
</tbody>
</table>
</div>
<div id="announce" aria-live="polite"></div>

<script>
const KEY = "experiment-report-v1";
const state = JSON.parse(localStorage.getItem(KEY) || "{}");
const table = document.getElementById("t");
const tb = table.tBodies[0];
const announce = document.getElementById("announce");

function pairs() {
  const out = [];
  const rows = [...tb.rows];
  for (let i = 0; i < rows.length; i += 2) out.push([rows[i], rows[i + 1]]);
  return out;
}

// expand / collapse a row's detail
tb.addEventListener("click", (e) => {
  let btn = e.target.closest("button.expand");
  if (!btn && e.target.closest(".gname")) btn = e.target.closest("tr").querySelector("button.expand");
  if (!btn) return;
  const detail = document.getElementById(btn.getAttribute("aria-controls"));
  const open = btn.getAttribute("aria-expanded") === "true";
  btn.setAttribute("aria-expanded", String(!open));
  detail.hidden = open;
});

// column visibility -- every column toggleable; the Gadget group's colspan tracks visible members.
// Uses a class with !important (not inline display) so re-showing a default-hidden column works.
const DEFAULTS = __DEFAULTS__;
const GROUPS = { gadget: ['name', 'block_graph', 'zx'] };
state.cols = state.cols || {};
for (const k in DEFAULTS) if (!(k in state.cols)) state.cols[k] = DEFAULTS[k];
function colVisible(c) { return state.cols[c] !== false; }
function applyCols() {
  document.querySelectorAll('td[data-col], th[data-col]').forEach(el => {
    const c = el.getAttribute('data-col');
    if (c.indexOf('__group') === 0) return;
    el.classList.toggle('hidden-col', !colVisible(c));
  });
  for (const g in GROUPS) {
    const th = document.querySelector('th[data-col="__group_' + g + '"]');
    if (!th) continue;
    const vis = GROUPS[g].filter(colVisible);
    th.colSpan = Math.max(vis.length, 1);
    th.classList.toggle('hidden-col', vis.length === 0);
  }
}
document.querySelectorAll('.menu input[data-colcb]').forEach(cb => {
  const c = cb.getAttribute('data-colcb');
  cb.checked = colVisible(c);
  cb.addEventListener('change', () => { state.cols[c] = cb.checked; save(); applyCols(); });
});

// filtering (search + segmented result filter)
let seg = state.seg || "all";
const q = document.getElementById("q");
q.value = state.q || "";
function matches(row) {
  const kind = row.getAttribute("data-kind");
  const text = row.getAttribute("data-gadget");
  const okSeg = seg === "all" ? true
    : seg === "failed" ? (kind === "predictor_fail" || kind === "prep_fail" || kind === "sim_fail")
    : kind === "not_scored";
  const okQ = !q.value || text.includes(q.value.toLowerCase());
  return okSeg && okQ;
}
function applyFilter() {
  let shown = 0;
  for (const [row, detail] of pairs()) {
    const on = matches(row);
    row.hidden = !on; if (!on) detail.hidden = true;
    if (on) shown++;
  }
  announce.textContent = shown + " rows shown";
}
q.addEventListener("input", () => { state.q = q.value; save(); applyFilter(); });
document.querySelectorAll('.seg button').forEach(b => b.addEventListener('click', () => {
  seg = b.getAttribute('data-seg');
  document.querySelectorAll('.seg button').forEach(x => x.setAttribute('aria-pressed', String(x === b)));
  state.seg = seg; save(); applyFilter();
}));
document.querySelectorAll('.chip').forEach(c => c.addEventListener('click', () => {
  const f = c.getAttribute('data-filter');
  const map = { rows: 'all', passed: 'all', predictor_failed: 'failed', prep_failed: 'failed', not_scored: 'not_scored' };
  seg = map[f] || 'all';
  document.querySelectorAll('.seg button').forEach(x => x.setAttribute('aria-pressed', String(x.getAttribute('data-seg') === seg)));
  document.querySelectorAll('.chip').forEach(x => x.classList.toggle('active', x === c));
  state.seg = seg; save(); applyFilter();
}));

// sorting via header buttons; body cells follow data-idx order regardless of the grouped header
table.querySelectorAll('thead th[data-idx]').forEach(th => {
  const btn = th.querySelector('button');
  if (!btn) return;
  const i = parseInt(th.getAttribute('data-idx'), 10);
  btn.addEventListener('click', () => {
    const asc = th.getAttribute('aria-sort') !== 'ascending';
    table.querySelectorAll('thead th').forEach(x => x.setAttribute('aria-sort', 'none'));
    th.setAttribute('aria-sort', asc ? 'ascending' : 'descending');
    const rows = pairs();
    rows.sort(([a], [b]) => {
      const ca = a.cells[i], cb = b.cells[i];
      const va = ca.getAttribute('data-sort-value'), vb = cb.getAttribute('data-sort-value');
      const na = parseFloat(va), nb = parseFloat(vb);
      const bothNum = va !== null && vb !== null && !isNaN(na) && !isNaN(nb);
      const cmp = bothNum ? na - nb : (ca.innerText).localeCompare(cb.innerText);
      return asc ? cmp : -cmp;
    });
    rows.forEach(([r, d]) => { tb.appendChild(r); tb.appendChild(d); });
    announce.textContent = 'sorted by ' + th.innerText.trim() + ' ' + (asc ? 'ascending' : 'descending');
  });
});

// show/hide plots
const plots = document.getElementById("plots");
if (state.plots === false) plots.checked = false;
function applyPlots() { document.querySelectorAll('figure.ler').forEach(f => f.style.display = plots.checked ? '' : 'none'); }
plots.addEventListener('change', () => { state.plots = plots.checked; save(); applyPlots(); });

function save() { localStorage.setItem(KEY, JSON.stringify(state)); }
document.querySelectorAll('.seg button').forEach(x => x.setAttribute('aria-pressed', String(x.getAttribute('data-seg') === seg)));
applyCols(); applyFilter(); applyPlots();
</script>
</body>
</html>
"""
