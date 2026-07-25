"""Test helpers: disjoint-union of block graphs and Hadamard-pipe arrangements."""

from __future__ import annotations

from tqec.computation.block_graph import BlockGraph
from tqec.utils.enums import Basis
from tqec.utils.position import Position3D


def disjoint_union(*graphs: BlockGraph, gap: int = 20, name: str = "disjoint") -> BlockGraph:
    """Merge several graphs into one disconnected graph, offsetting each along +x.

    ``prepare_batch`` (via ``BlockGraph.split_block_graph_batch``) splits the result back into one
    gadget per connected component, so this exercises the batch-split path from a single input.
    """
    merged = BlockGraph(name)
    offset = 0
    for graph in graphs:
        shifted = graph.shift_by(dx=offset)
        for cube in shifted.cubes:
            merged.add_cube(cube.position, cube.kind, cube.label)
        for pipe in shifted.pipes:
            merged.add_pipe(pipe.u.position, pipe.v.position, pipe.kind)
        offset += int(shifted.bounding_box_size()[0]) + gap
    return merged


# Cube kinds either side of an auto-inferred Hadamard pipe, per connecting axis. Taken from
# tqec's own compile tests (temporal + spatial-vertical-correlation Hadamard constructions).
_HADAMARD_KINDS = {
    "x": ("ZXZ", "XZX"),
    "y": ("XZZ", "ZXX"),
    "z": ("XZZ", "ZXX"),
}

HADAMARD_DIRECTIONS = ("+x", "-x", "+y", "-y", "+z", "-z")


def hadamard_pipe_pair(direction: str, *, name: str | None = None) -> BlockGraph:
    """Two cubes joined by an auto-inferred Hadamard pipe along ``direction``.

    ``direction`` is one of ``+x -x +y -y +z -z``. The two cubes differ in basis across the
    connecting axis, so ``add_pipe(kind=None)`` auto-infers a Hadamard transition. The sign
    chooses which side the second cube sits on (and thus the pipe's orientation).
    """
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


def hadamard_arrangements() -> dict[str, BlockGraph]:
    """One Hadamard-pipe graph per direction in :data:`HADAMARD_DIRECTIONS`."""
    return {d: hadamard_pipe_pair(d) for d in HADAMARD_DIRECTIONS}


BASIS_BY_NAME = {"x": Basis.X, "z": Basis.Z}
