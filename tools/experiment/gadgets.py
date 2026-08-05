"""Input builders: resolve experiment input specs to block graphs (or file paths).

A config or the CLI names its inputs as strings; :func:`resolve_inputs` turns those into the
concrete inputs ``tqec.orchestration.prepare_batch`` accepts. Three kinds of spec are understood:

* a ``tqec.gallery`` gadget name (``cnot``, ``memory``, ...), or ``all`` for every canonical one;
* a **tool-provided batch** name (:data:`NAMED_BATCHES`) -- gadget families the tester supplies
  itself, not sourced from ``tqec.gallery`` (e.g. the Hadamard-pipe arrangements, the spatial
  junctions used for the annotator comparison);
* a path to a ``.dae`` or ``.bgraph`` file (kept as a string; ``prepare_batch`` reads it).

``tqec`` is imported lazily inside the builders so importing this module stays cheap.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

_FILE_SUFFIXES = (".dae", ".bgraph")


def gallery_builders() -> dict[str, Callable[[], Any]]:
    """A zero-arg builder for every gadget in ``tqec.gallery`` (plus open-port variants)."""
    from tqec import gallery
    from tqec.utils.enums import Basis

    return {
        "cnot": lambda: gallery.cnot(Basis.Z),
        "cnot_open": lambda: gallery.cnot(None),
        "cz": lambda: gallery.cz(),
        "memory": lambda: gallery.memory(Basis.Z),
        "move_rotation": lambda: gallery.move_rotation(Basis.Z),
        "move_rotation_open": lambda: gallery.move_rotation(None),
        "stability": lambda: gallery.stability(Basis.Z),
        "steane_encoding": lambda: gallery.steane_encoding(Basis.Z),
        "steane_encoding_open": lambda: gallery.steane_encoding(None),
        "three_cnots": lambda: gallery.three_cnots(Basis.Z),
        "three_cnots_open": lambda: gallery.three_cnots(None),
    }


# The canonical gadgets ``all`` runs (the closed, port-filled form of every gallery entry).
GALLERY_ALL = (
    "cnot",
    "cz",
    "memory",
    "move_rotation",
    "stability",
    "steane_encoding",
    "three_cnots",
)

# Cube kinds either side of an auto-inferred Hadamard pipe, per connecting axis (from tqec's own
# compile tests: temporal + spatial-vertical-correlation Hadamard constructions).
_HADAMARD_KINDS = {
    "x": ("ZXZ", "XZX"),
    "y": ("XZZ", "ZXX"),
    "z": ("XZZ", "ZXX"),
}
HADAMARD_DIRECTIONS = ("+x", "-x", "+y", "-y", "+z", "-z")


def hadamard_pipe_pair(direction: str, *, name: str | None = None) -> Any:
    """Two cubes joined by an auto-inferred Hadamard pipe along ``direction`` (``+x``..``-z``)."""
    from tqec.computation.block_graph import BlockGraph
    from tqec.utils.position import Position3D

    axis = direction[1]
    sign = 1 if direction[0] == "+" else -1
    before, after = _HADAMARD_KINDS[axis]
    graph = BlockGraph(name or f"hadamard_{direction[0]}{axis}")
    origin = Position3D(0, 0, 0)
    delta = {"x": (sign, 0, 0), "y": (0, sign, 0), "z": (0, 0, sign)}[axis]
    other = Position3D(*delta)
    graph.add_cube(origin, before)
    graph.add_cube(other, after)
    graph.add_pipe(origin, other, None)
    return graph


def hadamard_arrangements() -> list[Any]:
    """Every arrangement of a single Hadamard pipe: one graph per direction."""
    return [hadamard_pipe_pair(d) for d in HADAMARD_DIRECTIONS]


def _spatial_junction(center_kind: str, name: str) -> Any:
    """A three-arm in-plane (spatial) junction: a centre cube with +x, -x, +y arms of one kind."""
    from tqec.computation.block_graph import BlockGraph
    from tqec.utils.position import Position3D

    graph = BlockGraph(name)
    centre = Position3D(0, 0, 0)
    graph.add_cube(centre, center_kind)
    for delta in ((1, 0, 0), (-1, 0, 0), (0, 1, 0)):
        arm = Position3D(*delta)
        graph.add_cube(arm, center_kind)
        graph.add_pipe(centre, arm, None)
    return graph


def spatial_junctions() -> list[Any]:
    """A Z-type and an X-type spatial junction (centre ``ZZX`` / ``XXZ``), for annotator comparison."""
    return [
        _spatial_junction("ZZX", "spatial_z_junction"),
        _spatial_junction("XXZ", "spatial_x_junction"),
    ]


#: Tool-provided gadget batches -- families the tester supplies itself (not from ``tqec.gallery``).
NAMED_BATCHES: dict[str, Callable[[], list[Any]]] = {
    "hadamard_arrangements": hadamard_arrangements,
    "spatial_junctions": spatial_junctions,
}


def available_inputs() -> dict[str, list[str]]:
    """The names :func:`resolve_inputs` understands, grouped by kind (for ``--list-gallery``)."""
    return {
        "gallery": sorted(gallery_builders()),
        "batches": sorted(NAMED_BATCHES),
        "special": ["all"],
    }


def resolve_inputs(specs: Sequence[str]) -> list[Any]:
    """Resolve input specs (gallery names, batch names, or file paths) to prepare_batch inputs.

    A file-path spec (ending in ``.dae`` / ``.bgraph``) is kept as a string; every other spec must
    be a gallery gadget, ``all``, or a tool batch name. Unknown specs raise ``ValueError``.
    """
    builders = gallery_builders()
    out: list[Any] = []
    for spec in specs:
        if spec.endswith(_FILE_SUFFIXES):
            path = Path(spec)
            if not path.exists():
                raise ValueError(f"input file not found: {spec}")
            out.append(str(path))
        elif spec == "all":
            out.extend(builders[name]() for name in GALLERY_ALL)
        elif spec in NAMED_BATCHES:
            out.extend(NAMED_BATCHES[spec]())
        elif spec in builders:
            out.append(builders[spec]())
        else:
            choices = sorted({*builders, *NAMED_BATCHES, "all"})
            raise ValueError(f"unknown input {spec!r}; choose from {choices} or a .dae/.bgraph path")
    return out
