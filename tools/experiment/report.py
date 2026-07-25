"""Experiment rows and reports: ``report.json`` + a self-contained ``report.html`` + text + CSV.

``report.json`` is the authoritative detailed artifact; ``report.html`` is the human-facing view.
The HTML is a single self-contained file (inline CSS/JS, no CDN) with a compact default table,
per-row expandable details (status, notes, oracle results, structure pictures, circuit links and
debugging diagrams), selectable columns, accessible sortable headers, and result/text filters.
Optional ``orjson`` is used for JSON and ``polars`` for CSV when present.
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
    oracle_verdicts: dict[str, dict[str, Any]] = field(default_factory=dict)
    visuals: dict[str, Any] = field(default_factory=dict)
    ler_plot: str | None = None
    lambda_factor: float | None = None
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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
            d.pop("visuals", None)
            d.pop("ler_plot", None)
            flat.append(d)
        if flat:
            pl.DataFrame(flat).write_csv(out / "report.csv")

    # Plain-text table: readable column names, no abbreviations that need a key.
    _COLUMNS = (
        ("status_kind", "result"),
        ("gadget_id", "gadget"),
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
        html_out = html_out.replace("__ROWS__", rows_html)
        html_out = html_out.replace("__SHOWPLOTS__", show_plots)
        return html_out

    def _row_html(self, index: int, r: ExperimentRow) -> str:
        badge = _BADGE_TEXT.get(r.status_kind, r.status_kind or "?")
        gv = self.gadget_visuals.get(r.gadget_id, {})
        cells = [
            f'<td class="col-result"><span class="badge {r.status_kind}">{html.escape(badge)}</span></td>',
            (
                f'<td class="col-gadget"><button class="expand" aria-expanded="false" '
                f'aria-controls="d{index}" title="show details">&#9656;</button>'
                f'<span class="gname" title="{html.escape(r.gadget_id)}">{html.escape(r.gadget_id)}</span></td>'
            ),
            f'<td>{html.escape(r.convention)}</td>',
            _num_td(r.k),
            _num_td(r.manhattan_radius),
            _num_td(r.window),
            _num_td(r.missing_parities),
            _num_td(r.distance),
            _num_td(r.expected_distance, optional=True, col="expected"),
            _num_td(r.native_missing, optional=True, col="native"),
            _num_td(r.lambda_factor, optional=True, col="lambda"),
            f'<td class="opt" data-col="source">{html.escape(r.source)}</td>',
            f'<td class="opt" data-col="status">{html.escape(r.status)}</td>',
        ]
        main = (
            f'<tr class="datarow {r.status_kind}" data-kind="{r.status_kind}" '
            f'data-gadget="{html.escape(r.gadget_id.lower())}">' + "".join(cells) + "</tr>"
        )
        detail = (
            f'<tr class="detail" id="d{index}" hidden><td colspan="13">'
            + self._detail_html(r, gv)
            + "</td></tr>"
        )
        return main + "\n" + detail

    def _detail_html(self, r: ExperimentRow, gv: dict[str, Any]) -> str:
        parts: list[str] = []
        if r.notes:
            parts.append(f'<p class="notes"><b>notes:</b> {html.escape(r.notes)}</p>')
        if r.oracle_verdicts:
            items = "".join(
                f"<li>{html.escape(name)}: "
                f'{"equivalent" if v.get("equivalent") else "not equivalent"}'
                f' &mdash; {html.escape(str(v.get("detail", "")))}</li>'
                for name, v in r.oracle_verdicts.items()
            )
            parts.append(f"<div><b>oracles</b><ul>{items}</ul></div>")

        structure: list[str] = []
        if gv.get("zx_png"):
            structure.append(f'<figure><figcaption>positioned ZX</figcaption><img src="{gv["zx_png"]}" alt="positioned ZX"/></figure>')
        if gv.get("block_graph_html"):
            structure.append(f'<a class="link" href="{html.escape(gv["block_graph_html"])}" target="_blank" rel="noopener">block graph (Pauli web)</a>')
        if structure:
            parts.append('<div class="structure"><b>structure</b><div class="pics">' + "".join(structure) + "</div></div>")

        v = r.visuals or {}
        links: list[str] = []
        if v.get("crumble"):
            links.append(f'<a class="link" href="{html.escape(v["crumble"])}" target="_blank" rel="noopener">crumble</a>')
        if v.get("circuit"):
            links.append(f'<a class="link" href="{html.escape(v["circuit"])}" target="_blank" rel="noopener">annotated circuit</a>')
        if v.get("detector_free"):
            links.append(f'<a class="link" href="{html.escape(v["detector_free"])}" target="_blank" rel="noopener">detector-free circuit</a>')
        if links:
            parts.append('<div class="links"><b>circuit</b> ' + " &middot; ".join(links) + "</div>")

        diagrams = v.get("diagrams") or []
        if diagrams:
            figs = "".join(
                f'<figure><figcaption>{html.escape(d["label"])}</figcaption>{d["svg"]}</figure>'
                for d in diagrams
                if d.get("svg")
            )
            if figs:
                parts.append('<div class="diagrams"><b>diagnostics</b><div class="pics">' + figs + "</div></div>")

        if r.ler_plot:
            parts.append(f'<figure class="ler"><figcaption>logical error rate</figcaption><img src="{r.ler_plot}" alt="LER plot"/></figure>')

        return "".join(parts) or "<p><i>no additional details</i></p>"


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


def _num_td(value: Any, *, optional: bool = False, col: str = "") -> str:
    text = _fmt(value)
    sort = "" if value is None else str(value)
    cls = "num opt" if optional else "num"
    colattr = f' data-col="{col}"' if col else ""
    return f'<td class="{cls}"{colattr} data-sort-value="{html.escape(sort)}">{html.escape(text)}</td>'


_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Gadget experiment report</title>
<style>
:root { color-scheme: light dark; --bg:#fff; --fg:#111; --line:#d8dde3; --head:#f6f8fa; --muted:#57606a;
  --pass:#1a7f37; --pfail:#cf222e; --prep:#9a6700; --skip:#57606a; --sim:#8250df; --accent:#0969da; }
@media (prefers-color-scheme: dark) { :root { --bg:#0d1117; --fg:#e6edf3; --line:#30363d; --head:#161b22;
  --muted:#8b949e; --pass:#3fb950; --pfail:#f85149; --prep:#d29922; --skip:#8b949e; --sim:#a371f7; --accent:#58a6ff; } }
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
.col-result, .col-gadget { position: sticky; left: 0; background: var(--bg); z-index: 1; }
.col-gadget { left: 5.5rem; }
th.col-result, th.col-gadget { z-index: 3; background: var(--head); }
.gname { display: inline-block; max-width: 16rem; overflow: hidden; text-overflow: ellipsis; vertical-align: bottom; }
.badge { font-size: .72rem; padding: .1rem .45rem; border-radius: 999px; color: #fff; }
.badge.pass { background: var(--pass); } .badge.predictor_fail { background: var(--pfail); }
.badge.prep_fail { background: var(--prep); } .badge.not_scored { background: var(--skip); } .badge.sim_fail { background: var(--sim); }
button.expand { all: unset; cursor: pointer; color: var(--muted); margin-right: .3rem; }
button.expand[aria-expanded=true] { transform: rotate(90deg); display: inline-block; }
.opt { display: none; }
tr.detail td { background: var(--head); white-space: normal; }
tr.detail .pics { display: flex; flex-wrap: wrap; gap: 1rem; align-items: flex-start; }
tr.detail figure { margin: .3rem 0; } tr.detail img, tr.detail svg { max-width: 22rem; height: auto; border: 1px solid var(--line); background: #fff; }
tr.detail figcaption { font-size: .8rem; color: var(--muted); }
.link { color: var(--accent); }
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
    <div class="menu">
      <label><input type="checkbox" data-col="expected"/> Expected distance</label>
      <label><input type="checkbox" data-col="native"/> Native missing</label>
      <label><input type="checkbox" data-col="lambda"/> Lambda</label>
      <label><input type="checkbox" data-col="source"/> Source</label>
      <label><input type="checkbox" data-col="status"/> Status</label>
    </div>
  </details>
  <label class="switch"__SHOWPLOTS__><input type="checkbox" id="plots" checked/> Show plots</label>
</div>

<div class="wrap" tabindex="0">
<table id="t">
<caption>One row per (gadget, convention, k, radius, window). Click a header to sort; click the arrow to expand details.</caption>
<thead><tr>
<th class="col-result" scope="col" aria-sort="none"><button type="button">Result</button></th>
<th class="col-gadget" scope="col" aria-sort="none"><button type="button">Gadget</button></th>
<th scope="col" aria-sort="none"><button type="button">Convention</button></th>
<th class="num" scope="col" aria-sort="none"><button type="button">k</button></th>
<th class="num" scope="col" aria-sort="none" title="Manhattan radius"><button type="button">Radius</button></th>
<th class="num" scope="col" aria-sort="none" title="tqecd matching window"><button type="button">Window</button></th>
<th class="num" scope="col" aria-sort="none"><button type="button">Missing parities</button></th>
<th class="num" scope="col" aria-sort="none"><button type="button">Distance</button></th>
<th class="num opt" data-col="expected" scope="col" aria-sort="none"><button type="button">Expected</button></th>
<th class="num opt" data-col="native" scope="col" aria-sort="none" title="native annotation missing parities"><button type="button">Native missing</button></th>
<th class="num opt" data-col="lambda" scope="col" aria-sort="none"><button type="button">Lambda</button></th>
<th class="opt" data-col="source" scope="col" aria-sort="none"><button type="button">Source</button></th>
<th class="opt" data-col="status" scope="col" aria-sort="none"><button type="button">Status</button></th>
</tr></thead>
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
  const btn = e.target.closest("button.expand");
  if (!btn) return;
  const detail = document.getElementById(btn.getAttribute("aria-controls"));
  const open = btn.getAttribute("aria-expanded") === "true";
  btn.setAttribute("aria-expanded", String(!open));
  detail.hidden = open;
});

// column visibility
function applyCols() {
  document.querySelectorAll('[data-col]').forEach(el => {
    const c = el.getAttribute('data-col');
    if (el.matches('input')) return;
    el.style.display = state.cols && state.cols[c] ? '' : 'none';
  });
}
document.querySelectorAll('.menu input[data-col]').forEach(cb => {
  const c = cb.getAttribute('data-col');
  state.cols = state.cols || {};
  cb.checked = !!state.cols[c];
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

// sorting via header buttons, typed by data-sort-value when present
table.querySelectorAll('thead th').forEach((th, i) => {
  th.querySelector('button').addEventListener('click', () => {
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
