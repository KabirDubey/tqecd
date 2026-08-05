"""Debugging visuals for the report: crumble links and block-graph / ZX pictures.

Everything here is best-effort and side-effect-light: each helper returns ``None`` (or skips) if a
picture cannot be produced, so a rendering problem never breaks a run.

The positioned ZX diagram is inlined into the report for small graphs and written to a file and
linked for large ones (more than :data:`ZX_INLINE_MAX_NODES` cubes), so a big gadget never bloats
the single-file report.
"""

from __future__ import annotations

import urllib.parse
from pathlib import Path

import stim

CRUMBLE_BASE = "https://algassert.com/crumble"

# Block graphs with more than this many cubes get a linked ZX picture instead of an inlined one.
ZX_INLINE_MAX_NODES = 20


def crumble_url(circuit: stim.Circuit) -> str:
    """A crumble.dev link that opens ``circuit`` in the interactive editor."""
    return f"{CRUMBLE_BASE}#circuit={urllib.parse.quote(str(circuit), safe='')}"


def load_block_graph(path, graph_name: str = ""):
    """Load a ``BlockGraph`` from its saved JSON, tolerating pipeless (single-cube) graphs.

    ``tqec``'s ``BlockGraph.from_json`` rejects any graph with zero pipes (memory and stability
    gadgets are a single cube), so this falls back to rebuilding the graph from the JSON with
    ``add_cube`` / ``add_pipe`` when the built-in reader refuses it. Returns ``None`` if neither
    path works.
    """
    from tqec.computation.block_graph import BlockGraph

    try:
        return BlockGraph.from_json(path, graph_name=graph_name)
    except Exception:
        pass
    try:
        import json

        from tqec.utils.position import Position3D

        data = json.loads(Path(path).read_text())
        graph = BlockGraph(graph_name or data.get("name", ""))
        for cube in data.get("cubes", []):
            graph.add_cube(
                Position3D(*cube["position"]), cube["kind"], cube.get("label", "")
            )
        for pipe in data.get("pipes", []):
            graph.add_pipe(
                Position3D(*pipe["u"]), Position3D(*pipe["v"]), pipe.get("kind")
            )
        return graph
    except Exception:
        return None


def write_circuit(circuit: stim.Circuit, path: Path) -> Path:
    """Write a stim circuit to ``path`` (creating parents) and return it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    circuit.to_file(path)
    return path


def write_block_graph_html(
    graph, path: Path, correlation_surface=None, *, pop_faces=("-Y",)
) -> Path | None:
    """Write ``BlockGraph.view_as_html`` and return the path.

    When ``correlation_surface`` is the observable being simulated, the ``-Y`` faces are popped so
    the surface is visible inside the 3D model (the convention used across ``tqec``'s own gallery
    notebooks). Popping is skipped when there is no surface to reveal.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        graph.view_as_html(
            write_html_filepath=str(path),
            show_correlation_surface=correlation_surface,
            pop_faces_at_directions=pop_faces
            if correlation_surface is not None
            else (),
        )
        return path
    except Exception:
        return None


def _render_zx_png(graph, title: str | None, surface=None) -> bytes | None:
    """Render the positioned ZX diagram to PNG bytes, decorated with ``surface`` if given.

    When ``surface`` is the correlation surface of the observable being simulated, it is drawn
    over the ZX graph with ``tqec``'s own ``draw_correlation_surface_on`` so the Pauli web of the
    logical observable is visible on the picture. Returns ``None`` on any failure.
    """
    try:
        import io

        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from tqec.interop.pyzx.plot import (
            draw_correlation_surface_on,
            plot_positioned_zx_graph,
        )
    except Exception:
        return None
    try:
        zx = graph.to_zx_graph()
        fig, ax = plot_positioned_zx_graph(zx, title=title, figsize=(4.0, 4.5))
        if surface is not None:
            try:
                draw_correlation_surface_on(surface, zx, ax)
            except Exception:
                pass
        buffer = io.BytesIO()
        fig.savefig(buffer, format="png", dpi=110, bbox_inches="tight")
        plt.close(fig)
        return buffer.getvalue()
    except Exception:
        return None


def positioned_zx_png_data_uri(
    graph, *, title: str | None = None, surface=None
) -> str | None:
    """Render the positioned ZX diagram (decorated with ``surface``) as a base64 PNG ``data:`` URI."""
    import base64

    png = _render_zx_png(graph, title, surface)
    if png is None:
        return None
    return f"data:image/png;base64,{base64.b64encode(png).decode('ascii')}"


def write_positioned_zx_png(
    graph, path: Path, *, title: str | None = None, surface=None
) -> Path | None:
    """Write the positioned ZX diagram (decorated with ``surface``) to a PNG file; return the path."""
    png = _render_zx_png(graph, title, surface)
    if png is None:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)
    return path
