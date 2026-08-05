"""Experiment rows and reports: ``report.json`` + a self-contained ``report.html`` + text.

``report.json`` is the authoritative artifact; ``report.html`` is the human-facing view. The HTML is
a single self-contained file (inline CSS/JS, no CDN) whose shape is driven by the run's config: the
columns present, the per-oracle column groups, and the MCMC-sampling section all follow what the
run actually measured. Structure links (3D block graph, decorated ZX) are columns beside the gadget
name; there is no expand/dropdown. Optional ``orjson`` is used for the JSON when present.
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
    """One measured (gadget, convention, k, window) cell."""

    gadget_id: str
    source: str
    name: str
    convention: str
    k: int
    window: int
    status: str
    status_kind: str = NOT_SCORED
    missing_parities: int | None = None
    parities_ok: bool | None = None
    distance: int | None = None
    expected_distance: int | None = None
    distance_ok: bool | None = None
    predictors_pass: bool | None = None
    observable: str = ""
    oracle_results: dict[str, dict[str, Any]] = field(default_factory=dict)
    visuals: dict[str, Any] = field(default_factory=dict)
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
    """A collection of rows plus JSON / HTML / text renderers."""

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
            "predictors_fail": counts[PREDICTOR_FAIL],  # back-compat / CLI exit code
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

    # ---- plain-text table (console) -----------------------------------------------------------
    def _text_columns(self) -> list[tuple[str, Any]]:
        cols: list[tuple[str, Any]] = [
            ("result", lambda r: r.status_kind),
            ("gadget", lambda r: r.gadget_id),
            ("observable", lambda r: r.observable),
            ("convention", lambda r: r.convention),
            ("k", lambda r: r.k),
            ("window", lambda r: r.window),
            ("missing", lambda r: r.missing_parities),
            ("distance", lambda r: r.distance),
            ("expected", lambda r: r.expected_distance),
            ("runtime", lambda r: r.runtime_s),
        ]
        for name in self.meta.get("oracles", []):
            cols.append(
                (
                    f"{name}:dist",
                    (
                        lambda n: (
                            lambda r: (r.oracle_results.get(n) or {}).get("distance")
                        )
                    )(name),
                )
            )
        return cols

    def to_text(self) -> str:
        cols = self._text_columns()
        headers = [label for label, _ in cols]
        table = [headers]
        for r in self.rows:
            table.append([_fmt(getter(r)) for _, getter in cols])
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

    # ---- HTML ---------------------------------------------------------------------------------
    def _columns(self) -> list[dict[str, Any]]:
        """The ordered leaf columns for the HTML table -- config-driven, incl. per-oracle groups."""
        predictors = self.meta.get("predictors", ["parities", "distance"])
        gv = self.gadget_visuals

        def num(attr: str) -> Any:
            return lambda r: getattr(r, attr)

        cols: list[dict[str, Any]] = [
            {
                "key": "result",
                "label": "Result",
                "default": True,
                "render": _result_cell,
            },
            {
                "key": "name",
                "label": "Name",
                "group": "gadget",
                "glabel": "Gadget",
                "default": True,
                "sortable": True,
                "render": _name_cell,
            },
            {
                "key": "block_graph",
                "label": "3D",
                "group": "gadget",
                "default": True,
                "render": lambda r: _block_graph_cell(gv.get(r.gadget_id, {})),
            },
            {
                "key": "zx",
                "label": "ZX",
                "group": "gadget",
                "default": True,
                "render": lambda r: _zx_cell(gv.get(r.gadget_id, {})),
            },
            {
                "key": "observable",
                "label": "Observable",
                "default": True,
                "sortable": True,
                "render": lambda r: _text_cell(r.observable),
            },
            {
                "key": "convention",
                "label": "Convention",
                "default": True,
                "sortable": True,
                "render": lambda r: _text_cell(r.convention),
            },
            {
                "key": "k",
                "label": "k",
                "default": True,
                "numeric": True,
                "value": num("k"),
            },
            {
                "key": "window",
                "label": "Window",
                "default": False,
                "numeric": True,
                "value": num("window"),
            },
            {
                "key": "missing",
                "label": "Missing parities",
                "default": "parities" in predictors,
                "numeric": True,
                "value": num("missing_parities"),
            },
            {
                "key": "distance",
                "label": "Distance",
                "default": "distance" in predictors,
                "numeric": True,
                "value": num("distance"),
            },
            {
                "key": "expected",
                "label": "Expected",
                "default": False,
                "numeric": True,
                "value": num("expected_distance"),
            },
            {
                "key": "runtime",
                "label": "Runtime (s)",
                "default": True,
                "numeric": True,
                "value": num("runtime_s"),
            },
            {"key": "links", "label": "Links", "default": True, "render": _links_cell},
            {
                "key": "notes",
                "label": "Notes",
                "default": True,
                "sortable": True,
                "render": lambda r: _text_cell(r.notes),
            },
            {
                "key": "input",
                "label": "Input",
                "default": False,
                "sortable": True,
                "render": lambda r: _text_cell(r.source),
            },
        ]
        for name in self.meta.get("oracles", []):
            g = f"oracle:{name}"
            cols += [
                {
                    "key": f"{g}:dist",
                    "label": "dist",
                    "group": g,
                    "glabel": name,
                    "mlabel": f"{name} dist",
                    "default": True,
                    "numeric": True,
                    "value": (
                        lambda n: (
                            lambda r: (r.oracle_results.get(n) or {}).get("distance")
                        )
                    )(name),
                },
                {
                    "key": f"{g}:eq",
                    "label": "≡",
                    "group": g,
                    "mlabel": f"{name} equivalent",
                    "default": True,
                    "sortable": True,
                    "render": (
                        lambda n: (
                            lambda r: _eq_cell(
                                (r.oracle_results.get(n) or {}).get("equivalent")
                            )
                        )
                    )(name),
                },
                {
                    "key": f"{g}:stim",
                    "label": "stim",
                    "group": g,
                    "mlabel": f"{name} stim",
                    "default": True,
                    "render": (
                        lambda n: (
                            lambda r: _oracle_stim_cell(r.oracle_results.get(n) or {})
                        )
                    )(name),
                },
            ]
        return cols

    def _header_html(self, cols: list[dict[str, Any]]) -> str:
        members: dict[str, list[int]] = {}
        for idx, col in enumerate(cols):
            if col.get("group"):
                members.setdefault(col["group"], []).append(idx)

        def th(idx: int, col: dict[str, Any], rowspan: int) -> str:
            cls = ' class="num"' if col.get("numeric") else ""
            rs = f' rowspan="{rowspan}"' if rowspan != 1 else ""
            sortable = col.get("sortable") or col.get("numeric")
            label = html.escape(col["label"])
            inner = f'<button type="button">{label}</button>' if sortable else label
            sort = ' aria-sort="none"' if sortable else ""
            return f'<th{cls} data-col="{col["key"]}" data-idx="{idx}"{rs} scope="col"{sort}>{inner}</th>'

        row1, row2, opened = ["<tr>"], ["<tr>"], set()
        for idx, col in enumerate(cols):
            group = col.get("group")
            if not group:
                row1.append(th(idx, col, rowspan=2))
                continue
            if group not in opened:
                opened.add(group)
                glabel = html.escape(cols[members[group][0]].get("glabel", group))
                row1.append(
                    f'<th class="group" data-col="__group_{group}" colspan="{len(members[group])}" '
                    f'scope="colgroup">{glabel}</th>'
                )
            row2.append(th(idx, col, rowspan=1))
        row1.append("</tr>")
        row2.append("</tr>")
        return "".join(row1) + "\n" + "".join(row2)

    def _row_html(self, cols: list[dict[str, Any]], r: ExperimentRow) -> str:
        cells = []
        for col in cols:
            key = col["key"]
            if col.get("numeric"):
                value = col["value"](r)
                sort = "" if value is None else str(value)
                cells.append(
                    f'<td class="num" data-col="{key}" data-sort-value="{html.escape(sort)}">'
                    f"{html.escape(_fmt(value))}</td>"
                )
            else:
                cells.append(f'<td data-col="{key}">{col["render"](r)}</td>')
        return (
            f'<tr class="datarow {r.status_kind}" data-kind="{r.status_kind}" '
            f'data-gadget="{html.escape(r.gadget_id.lower())}">'
            + "".join(cells)
            + "</tr>"
        )

    def _menu_html(self, cols: list[dict[str, Any]]) -> str:
        return "".join(
            f'<label><input type="checkbox" data-colcb="{col["key"]}"/> '
            f"{html.escape(col.get('mlabel', col['label']))}</label>"
            for col in cols
        )

    def _defaults_json(self, cols: list[dict[str, Any]]) -> str:
        return json.dumps({col["key"]: bool(col["default"]) for col in cols})

    def _groups_json(self, cols: list[dict[str, Any]]) -> str:
        groups: dict[str, list[str]] = {}
        for col in cols:
            if col.get("group"):
                groups.setdefault(col["group"], []).append(col["key"])
        return json.dumps(groups)

    def _top_header(self) -> str:
        title = html.escape(self.meta.get("name") or "Gadget experiment report")
        bits = []
        if self.meta.get("timestamp"):
            bits.append(f"run {html.escape(self.meta['timestamp'])}")
        if self.meta.get("config"):
            bits.append(
                f'<a class="link" href="{html.escape(self.meta["config"])}" target="_blank" '
                f'rel="noopener">config.toml</a>'
            )
        sub = " &middot; ".join(bits)
        return f"<h1>{title}</h1>" + (
            f'<div class="runmeta">{sub}</div>' if sub else ""
        )

    def _mcmc_section(self) -> str:
        mcmc = self.meta.get("mcmc")
        if not mcmc or not mcmc.get("enabled"):
            return ""
        setup = mcmc.get("setup")
        setup_link = (
            f' &middot; <a class="link" href="{html.escape(setup)}" target="_blank" rel="noopener">sampling setup</a>'
            if setup
            else ""
        )
        head = (
            f'<p class="muted">Monte-Carlo (sinter) sampling &mdash; aggregate '
            f"{html.escape(str(mcmc.get('aggregate', '')))}, {mcmc.get('results', 0)} sampled cases"
            f"{setup_link}</p>"
        )
        rows = []
        for g in mcmc.get("gadgets", []):
            plot = g.get("plot")
            plot_cell = (
                f'<a href="{html.escape(plot)}" target="_blank" rel="noopener">'
                f'<img class="plotthumb" src="{html.escape(plot)}" alt="LER-vs-p plot"/></a>'
                if plot
                else "&ndash;"
            )
            lam = g.get("lambda")
            rows.append(
                "<tr><td>"
                + html.escape(g.get("gadget_id", ""))
                + "</td><td>"
                + html.escape(g.get("convention", ""))
                + '</td><td class="num">'
                + (f"{lam:.3g}" if isinstance(lam, (int, float)) else "&ndash;")
                + "</td><td>"
                + plot_cell
                + "</td></tr>"
            )
        return (
            '<section class="mcmc"><h2>MCMC sampling</h2>'
            + head
            + '<div class="wrap"><table><thead><tr><th>Gadget</th><th>Convention</th>'
            + '<th class="num">Lambda</th><th>LER-vs-p plot</th></tr></thead><tbody>'
            + "".join(rows)
            + "</tbody></table></div></section>"
        )

    def to_html(self) -> str:
        cols = self._columns()
        rows_html = "\n".join(self._row_html(cols, r) for r in self.rows)
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
        out = _HTML
        out = out.replace("__TOPHEADER__", self._top_header())
        out = out.replace("__CHIPS__", chips)
        out = out.replace("__HEADER__", self._header_html(cols))
        out = out.replace("__MENU__", self._menu_html(cols))
        out = out.replace("__DEFAULTS__", self._defaults_json(cols))
        out = out.replace("__GROUPS__", self._groups_json(cols))
        out = out.replace("__ROWS__", rows_html)
        out = out.replace("__MCMC__", self._mcmc_section())
        return out


# ---- module cell helpers ----------------------------------------------------------------------
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


def _text_cell(value: Any) -> str:
    text = _fmt(value)
    return f'<span title="{html.escape(text)}">{html.escape(text)}</span>'


def _result_cell(r: ExperimentRow) -> str:
    badge = _BADGE_TEXT.get(r.status_kind, r.status_kind or "?")
    return (
        f'<span class="badge {r.status_kind}" title="{html.escape(_result_explanation(r))}">'
        f"{html.escape(badge)}</span>"
    )


def _name_cell(r: ExperimentRow) -> str:
    return f'<span class="gname" title="{html.escape(r.gadget_id)}">{html.escape(r.gadget_id)}</span>'


def _block_graph_cell(gv: dict[str, Any]) -> str:
    href = gv.get("block_graph_html")
    if href:
        return (
            f'<a class="link" href="{html.escape(href)}" target="_blank" rel="noopener" '
            f'title="3D block graph with the observable surface">3D</a>'
        )
    return "&ndash;"


def _zx_cell(gv: dict[str, Any]) -> str:
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


def _links_cell(r: ExperimentRow) -> str:
    v = r.visuals or {}
    links: list[str] = []
    if v.get("crumble"):
        links.append(
            f'<a class="link" href="{html.escape(v["crumble"])}" target="_blank" rel="noopener" '
            f'title="open in crumble">crumble</a>'
        )
    if v.get("circuit"):
        links.append(
            f'<a class="link" href="{html.escape(v["circuit"])}" target="_blank" rel="noopener" '
            f'title="annotated .stim circuit">stim</a>'
        )
    if v.get("detector_free"):
        links.append(
            f'<a class="link" href="{html.escape(v["detector_free"])}" target="_blank" rel="noopener" '
            f'title="detector-free .stim circuit">bare</a>'
        )
    return " &middot; ".join(links) if links else "&ndash;"


def _eq_cell(equivalent: Any) -> str:
    if equivalent is True:
        return (
            '<span title="logically equivalent to the experimental annotation">✓</span>'
        )
    if equivalent is False:
        return '<span class="bad" title="NOT logically equivalent to the experimental annotation">✗</span>'
    return "&ndash;"


def _oracle_stim_cell(res: dict[str, Any]) -> str:
    if res.get("error"):
        return (
            f'<span class="bad" title="{html.escape(str(res["error"]))}">error</span>'
        )
    stim = res.get("stim")
    if stim:
        return (
            f'<a class="link" href="{html.escape(stim)}" target="_blank" rel="noopener" '
            f'title="this oracle\'s annotated .stim">stim</a>'
        )
    return "&ndash;"


def _result_explanation(r: ExperimentRow) -> str:
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
  --pass:#1a7f37; --pfail:#cf222e; --prep:#9a6700; --skip:#57606a; --sim:#8250df; --accent:#0969da;
  --hover:#eef1f4; --bad:#cf222e; }
@media (prefers-color-scheme: dark) { :root { --bg:#0d1117; --fg:#e6edf3; --line:#30363d; --head:#161b22;
  --muted:#8b949e; --pass:#3fb950; --pfail:#f85149; --prep:#d29922; --skip:#8b949e; --sim:#a371f7;
  --accent:#58a6ff; --hover:#1b2129; --bad:#f85149; } }
* { box-sizing: border-box; }
html, body { max-width: 100%; overflow-x: hidden; }
body { font-family: ui-sans-serif, system-ui, sans-serif; margin: clamp(.5rem, 2vw, 1.5rem); background: var(--bg); color: var(--fg); }
h1 { font-size: 1.3rem; margin: 0 0 .15rem; }
h2 { font-size: 1.05rem; margin: 1.2rem 0 .3rem; }
.runmeta { color: var(--muted); font-size: .85rem; margin-bottom: .5rem; }
.muted { color: var(--muted); font-size: .85rem; }
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
details.cols .menu { display: grid; grid-template-columns: repeat(auto-fill, minmax(12rem, 1fr)); gap: .2rem;
  padding: .4rem; border: 1px solid var(--line); border-radius: 6px; margin-top: .3rem; max-height: 16rem; overflow: auto; }
.wrap { overflow-x: auto; max-width: 100%; border: 1px solid var(--line); border-radius: 8px; }
table { border-collapse: collapse; width: 100%; font-variant-numeric: tabular-nums; }
th, td { padding: .35rem .55rem; border-bottom: 1px solid var(--line); text-align: left; white-space: nowrap; }
th { background: var(--head); position: sticky; top: 0; z-index: 2; }
th button { all: unset; cursor: pointer; font-weight: 600; }
th[aria-sort=ascending] button::after { content: " \25B2"; } th[aria-sort=descending] button::after { content: " \25BC"; }
th.group { text-align: center; border-left: 1px solid var(--line); border-right: 1px solid var(--line); }
td.num, th.num { text-align: right; }
tbody tr.datarow:hover > td { background: var(--hover); }
.gname { display: inline-block; max-width: 18rem; overflow: hidden; text-overflow: ellipsis; vertical-align: bottom; }
.badge { font-size: .72rem; padding: .1rem .45rem; border-radius: 999px; color: #fff; }
.badge.pass { background: var(--pass); } .badge.predictor_fail { background: var(--pfail); }
.badge.prep_fail { background: var(--prep); } .badge.not_scored { background: var(--skip); } .badge.sim_fail { background: var(--sim); }
.link { color: var(--accent); } td .link { margin-right: .3rem; }
.bad { color: var(--bad); }
.zxthumb { max-height: 2.6rem; width: auto; border: 1px solid var(--line); background: #fff; vertical-align: middle; cursor: zoom-in; }
.plotthumb { max-height: 7rem; width: auto; border: 1px solid var(--line); background: #fff; }
.hidden-col { display: none !important; }
#announce { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
</style>
</head>
<body>
__TOPHEADER__
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
</div>

<div class="wrap" tabindex="0">
<table id="t">
<caption>One row per (gadget, convention, k, observable). Click a header to sort; use Columns to show or hide any column.</caption>
<thead>__HEADER__</thead>
<tbody>
__ROWS__
</tbody>
</table>
</div>

__MCMC__
<div id="announce" aria-live="polite"></div>

<script>
const KEY = "experiment-report-v2";
const state = JSON.parse(localStorage.getItem(KEY) || "{}");
const table = document.getElementById("t");
const tb = table.tBodies[0];
function save() { localStorage.setItem(KEY, JSON.stringify(state)); }

// column visibility -- every column toggleable; a group header's colspan tracks its visible members.
const DEFAULTS = __DEFAULTS__;
const GROUPS = __GROUPS__;
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
    : seg === "not_scored" ? kind === "not_scored" : true;
  const okQ = !state.q || text.indexOf(state.q.toLowerCase()) >= 0;
  return okSeg && okQ;
}
function applyFilter() { [...tb.rows].forEach(r => { r.hidden = !matches(r); }); }
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

// sorting by header buttons; body cells follow data-idx order
table.querySelectorAll('thead th[data-idx] button').forEach(btn => {
  const th = btn.closest('th');
  const i = parseInt(th.getAttribute('data-idx'), 10);
  btn.addEventListener('click', () => {
    const asc = th.getAttribute('aria-sort') !== 'ascending';
    table.querySelectorAll('thead th').forEach(x => x.setAttribute('aria-sort', 'none'));
    th.setAttribute('aria-sort', asc ? 'ascending' : 'descending');
    const rs = [...tb.rows];
    rs.sort((a, b) => {
      const ca = a.cells[i], cb = b.cells[i];
      const va = ca.getAttribute('data-sort-value'), vb = cb.getAttribute('data-sort-value');
      const na = parseFloat(va), nb = parseFloat(vb);
      const bothNum = va !== null && vb !== null && !isNaN(na) && !isNaN(nb);
      const cmp = bothNum ? na - nb : (ca.innerText).localeCompare(cb.innerText);
      return asc ? cmp : -cmp;
    });
    rs.forEach(r => tb.appendChild(r));
  });
});

document.querySelectorAll('.seg button').forEach(x => x.setAttribute('aria-pressed', String(x.getAttribute('data-seg') === seg)));
applyCols(); applyFilter();
</script>
</body>
</html>
"""
