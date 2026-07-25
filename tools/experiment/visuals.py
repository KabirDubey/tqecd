"""Debugging visuals for the report: stim diagrams, crumble links, and graph pictures.

Everything here is best-effort and side-effect-light: each helper returns ``None`` (or skips) if
a diagram cannot be produced, so a rendering problem never breaks a run. Small SVGs (detector
slices, match graphs) are cheap and are inlined into the report; heavier artifacts (the block-graph
3D viewer, the full circuit) are written to files under the run directory and linked.

Failure-directed visuals (:func:`diagnostic_kinds`) pick the stim diagram that actually helps for a
given failure: a short code distance is best seen in the match graph and detector slices, a missing
parity in the detector slices next to the detector-free circuit, a compile failure in the block
graph and ZX pictures (the circuit does not exist yet).
"""

from __future__ import annotations

import urllib.parse
from pathlib import Path

import stim

CRUMBLE_BASE = "https://algassert.com/crumble"

# stim diagram kinds we use, smallest first.
DETSLICE = "detslice-svg"
DETSLICE_OPS = "detslice-with-ops-svg"
MATCHGRAPH = "matchgraph-svg"
TIMESLICE = "timeslice-svg"
TIMELINE = "timeline-svg"


def crumble_url(circuit: stim.Circuit) -> str:
    """A crumble.dev link that opens ``circuit`` in the interactive editor."""
    return f"{CRUMBLE_BASE}#circuit={urllib.parse.quote(str(circuit), safe='')}"


def diagram_svg(circuit: stim.Circuit, kind: str) -> str | None:
    """Return the SVG text of a stim diagram, or ``None`` if it cannot be produced."""
    try:
        return str(circuit.diagram(kind))
    except Exception:
        return None


def diagnostic_kinds(status: str, error: str = "") -> list[str]:
    """Pick the stim diagram kinds most useful for debugging a given outcome.

    Args:
        status: the unit/row status (``"ready"`` rows are scored; others are prep failures).
        error: the failure message, used to distinguish a distance shortfall from a parity gap.

    Returns:
        Diagram kinds to render for this row. A prep/compile failure has no circuit, so it returns
        an empty list (the block-graph/ZX pictures cover it instead).
    """
    text = error.lower()
    if status != "ready":
        # Import / compile / observable failures have no circuit to slice.
        return []
    if "distance" in text or "graphlike" in text:
        return [MATCHGRAPH, DETSLICE]
    if "parit" in text:
        return [DETSLICE, DETSLICE_OPS]
    # A passing (or otherwise scored) row: a compact detector slice is the cheap default.
    return [DETSLICE]


def write_circuit(circuit: stim.Circuit, path: Path) -> Path:
    """Write a stim circuit to ``path`` (creating parents) and return it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    circuit.to_file(path)
    return path


def write_block_graph_html(graph, path: Path, correlation_surface=None) -> Path | None:
    """Write ``BlockGraph.view_as_html`` (optionally showing a Pauli web) and return the path."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        graph.view_as_html(write_html_filepath=str(path), show_correlation_surface=correlation_surface)
        return path
    except Exception:
        return None


def positioned_zx_png_data_uri(graph, *, title: str | None = None) -> str | None:
    """Render the block graph's positioned ZX diagram as a base64 PNG ``data:`` URI."""
    try:
        import base64
        import io

        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        from tqec.interop.pyzx import plot_positioned_zx_graph
    except Exception:
        return None
    try:
        zx = graph.to_zx_graph()
        fig, _ = plot_positioned_zx_graph(zx, title=title, figsize=(4.0, 4.5))
        buffer = io.BytesIO()
        fig.savefig(buffer, format="png", dpi=110, bbox_inches="tight")
        plt.close(fig)
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/png;base64,{encoded}"
    except Exception:
        return None
