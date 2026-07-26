"""FINAL C: probe the state of spatial-Hadamard support across tqec versions.

Rebuilds the spatial-Hadamard arrangements exactly as tqec's own compile tests do -- the vertical
and horizontal correlation-surface pipe pairs (``tests/compile/compile_test.py``) -- and runs each
against whatever ``tqec`` is importable, bypassing ``tqec.orchestration``: it compiles each
arrangement per convention, re-annotates with ``tqecd``, and records whether it compiled, its
missing-parity count, and its distance. Run it once per tqec checkout (for example each open
spatial-Hadamard PR) with that checkout on ``PYTHONPATH``, then aggregate the per-version JSONs.

    python -m tools.experiment.final_c_spatial_hadamard probe <label> <out.json>
    python -m tools.experiment.final_c_spatial_hadamard aggregate <out_dir> <label=path.json> ...

The tqec test suite encodes the expected state, which this probe reproduces and compares across
versions: vertical spatial H works only under fixed_boundary; horizontal spatial H works only under
fixed_bulk and only along the Y direction; everything else raises NotImplementedError.
"""

from __future__ import annotations

import html as _html
import json
import sys
import warnings
from pathlib import Path

K = 1
CONVENTIONS = ("fixed_bulk", "fixed_boundary")

NOTIMPL = "not_implemented"
ERROR = "error"
NONDET = "no_det_observable"
PARTIAL = "partial"
FULL = "full"
_ORDER = [NOTIMPL, ERROR, NONDET, PARTIAL, FULL]


def spatial_hadamard_arrangements() -> dict:
    """The spatial-Hadamard pipe pairs from tqec's own compile tests, keyed by a readable label.

    Mirrors ``test_compile_spatial_hadamard_vertical_correlation_surface`` and
    ``..._horizontal_correlation_surface``: a cube of one kind joined by an auto-inferred Hadamard
    pipe to a cube of the transformed kind, one step along X or Y.
    """
    from tqec.computation.block_graph import BlockGraph
    from tqec.utils.position import Direction3D, Position3D

    def pair(before: str, after: str, direction) -> BlockGraph:
        g = BlockGraph("spatial_hadamard")
        p0 = Position3D(0, 0, 0)
        p1 = p0.shift_in_direction(direction, 1)
        g.add_cube(p0, before)
        g.add_cube(p1, after)
        g.add_pipe(p0, p1)
        return g

    out: dict = {}
    for dname, direction in (("x", Direction3D.X), ("y", Direction3D.Y)):
        before = "ZXZ" if dname == "x" else "XZZ"
        after = "XZX" if dname == "x" else "ZXX"
        out[f"vertical_{dname}"] = pair(before, after, direction)
    for obs in ("z", "x"):
        before = "ZZX" if obs == "z" else "XXZ"
        after = "XXZ" if obs == "z" else "ZZX"
        for dname, direction in (("x", Direction3D.X), ("y", Direction3D.Y)):
            out[f"horizontal_{obs}obs_{dname}"] = pair(before, after, direction)
    return out


def probe(label: str, out_json: str) -> None:
    """Compile + re-annotate every spatial-Hadamard arrangement under the importable tqec."""
    warnings.filterwarnings("ignore")
    from tqec import compile_block_graph
    from tqec.compile.convention import ALL_CONVENTIONS
    from tqec.utils.exceptions import TQECError
    from tqec.utils.noise_model import NoiseModel

    from tools.experiment import annotate
    from tools.experiment.predictors import count_missing_parities, shortest_graphlike_error

    def distance(circuit):
        return shortest_graphlike_error(NoiseModel.uniform_depolarizing(1e-3).noisy_circuit(circuit))

    arrangements = spatial_hadamard_arrangements()
    conventions = [c for c in CONVENTIONS if c in ALL_CONVENTIONS]
    conventions += [c for c in ALL_CONVENTIONS if c not in conventions]
    records = []
    for name, graph in arrangements.items():
        for conv_name in conventions:
            rec: dict = {"arrangement": name, "convention": conv_name, "status": ERROR}
            convention = ALL_CONVENTIONS[conv_name]
            try:
                circuit = compile_block_graph(graph, convention, observables="auto").generate_stim_circuit(K)
                rec["compiled"] = True
                reannotated = annotate.reannotate(circuit, window=2)
                rec["missing_parities"] = count_missing_parities(reannotated)
                rec["distance"] = distance(reannotated)
                rec["expected"] = 2 * K + 1
                full = rec["missing_parities"] == 0 and rec["distance"] == rec["expected"]
                rec["status"] = FULL if full else PARTIAL
            except NotImplementedError as exc:
                rec.update(compiled=False, status=NOTIMPL, error=str(exc)[:200])
            except TQECError as exc:
                try:
                    circuit = compile_block_graph(graph, convention, observables=[]).generate_stim_circuit(K)
                    rec["compiled"] = True
                    rec["missing_parities"] = count_missing_parities(annotate.reannotate(circuit, window=2))
                    rec.update(status=NONDET, error=str(exc)[:200])
                except NotImplementedError as exc2:
                    rec.update(compiled=False, status=NOTIMPL, error=str(exc2)[:200])
                except Exception as exc2:  # noqa: BLE001
                    rec.update(compiled=False, status=ERROR, error_type=type(exc2).__name__, error=str(exc2)[:200])
            except Exception as exc:  # noqa: BLE001 - any failure is reportable data
                rec.update(compiled=False, status=ERROR, error_type=type(exc).__name__, error=str(exc)[:200])
            records.append(rec)

    Path(out_json).write_text(json.dumps({"label": label, "records": records}, indent=2))
    n_full = sum(1 for r in records if r["status"] == FULL)
    print(f"{label}: wrote {out_json}  ({n_full}/{len(records)} arrangement-cells reached full)")


def aggregate(out_dir: str, mapping: dict) -> None:
    """Combine per-version JSONs into ``final_c_report.html`` + ``final_c_heatmap.png`` + JSON."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    versions = list(mapping)
    data = {label: json.loads(Path(path).read_text())["records"] for label, path in mapping.items()}
    keys = sorted({(r["arrangement"], r["convention"]) for recs in data.values() for r in recs})

    def cell(label, arrangement, convention):
        for r in data[label]:
            if r["arrangement"] == arrangement and r["convention"] == convention:
                return r
        return {"status": "missing"}

    combined = {"versions": versions, "rows": []}
    for arrangement, convention in keys:
        row = {"arrangement": arrangement, "convention": convention, "cells": {}}
        for label in versions:
            row["cells"][label] = cell(label, arrangement, convention)
        combined["rows"].append(row)
    (out / "final_c.json").write_text(json.dumps(combined, indent=2))
    _write_html(out / "final_c_report.html", versions, keys, cell)
    _write_heatmap(out / "final_c_heatmap.png", versions, keys, cell)
    print(f"aggregate: wrote {out}/final_c_report.html, final_c_heatmap.png, final_c.json")


_GLYPH = {FULL: "&#9679; full", PARTIAL: "&#9680; partial", NOTIMPL: "&#9675; not impl",
          ERROR: "&#9888; error", NONDET: "&#9681; no det obs", "missing": "-"}
_COLOR = {FULL: "#1a7f37", PARTIAL: "#9a6700", NOTIMPL: "#8c959f", ERROR: "#cf222e",
          NONDET: "#6e7781", "missing": "#d0d7de"}


def _detail(rec: dict) -> str:
    bits = []
    if "missing_parities" in rec:
        bits.append(f"missing={rec['missing_parities']}")
    if rec.get("distance") is not None:
        bits.append(f"d={rec['distance']}/{rec.get('expected', '?')}")
    if rec.get("error"):
        bits.append(_html.escape((str(rec.get("error_type", "")) + " " + rec["error"]).strip())[:70])
    return " ".join(bits)


def _write_html(path, versions, keys, cell):
    head = "".join(f"<th>{_html.escape(v)}</th>" for v in versions)
    rows = []
    for arrangement, convention in keys:
        tds = []
        for v in versions:
            rec = cell(v, arrangement, convention)
            st = rec["status"]
            tds.append(f'<td style="background:{_COLOR.get(st, "#eee")};color:#fff">'
                       f'<b>{_GLYPH.get(st, st)}</b><br><small>{_detail(rec)}</small></td>')
        rows.append(f"<tr><th>{arrangement}<br><small>{convention}</small></th>{''.join(tds)}</tr>")
    path.write_text(
        "<!doctype html><meta charset=utf-8><title>FINAL C: spatial Hadamard state</title>"
        "<style>body{font-family:system-ui,sans-serif;margin:2rem}"
        "table{border-collapse:collapse}th,td{border:1px solid #ccc;padding:.4rem .6rem;text-align:left;vertical-align:top}"
        "small{opacity:.85}</style>"
        "<h1>FINAL C: state of spatial-Hadamard implementation</h1>"
        "<p>Each spatial-Hadamard arrangement (the vertical and horizontal correlation-surface pipe "
        "pairs from tqec's own compile tests) compiled directly -- bypassing orchestration -- and "
        "re-annotated with tqecd, per tqec version.</p>"
        f"<table><tr><th>arrangement / convention</th>{head}</tr>{''.join(rows)}</table>"
    )


def _write_heatmap(path, versions, keys, cell):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
    except Exception:
        return
    codes = {s: i for i, s in enumerate(_ORDER)}
    grid = np.full((len(keys), len(versions)), np.nan)
    for r, (arrangement, convention) in enumerate(keys):
        for c, v in enumerate(versions):
            grid[r, c] = codes.get(cell(v, arrangement, convention)["status"], np.nan)
    fig, ax = plt.subplots(figsize=(1.7 * len(versions) + 4, 0.55 * len(keys) + 2))
    cmap = matplotlib.colors.ListedColormap(["#8c959f", "#cf222e", "#6e7781", "#9a6700", "#1a7f37"])
    ax.imshow(grid, cmap=cmap, vmin=0, vmax=len(_ORDER) - 1, aspect="auto")
    ax.set_xticks(range(len(versions)), versions, rotation=30, ha="right")
    ax.set_yticks(range(len(keys)), [f"{a} / {c}" for a, c in keys])
    for r, (arrangement, convention) in enumerate(keys):
        for c, v in enumerate(versions):
            ax.text(c, r, _detail(cell(v, arrangement, convention)), ha="center", va="center", fontsize=6, color="#fff")
    ax.set_title("Spatial-Hadamard state (green=full, amber=partial, grey=not implemented, red=error)")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def _main(argv):
    if len(argv) >= 3 and argv[0] == "probe":
        probe(argv[1], argv[2]); return 0
    if len(argv) >= 2 and argv[0] == "aggregate":
        aggregate(argv[1], dict(pair.split("=", 1) for pair in argv[2:])); return 0
    print(__doc__); return 2


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
