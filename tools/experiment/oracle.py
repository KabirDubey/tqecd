"""Reference *oracles*--ground truth where it legitimately exists (``stim`` + ``numpy``).

The general case has no ground truth: for an arbitrary supplied gadget it may be unknown whether
*any* detector annotation reaches full distance. But in narrow configurations / circuit
conventions a known-correct reference does exist, and there it *is* ground truth. Example: on
``feat/yfragmentflow`` ``tqec``'s native annotation is correct for the ``fixed_bulk`` convention,
so native is "oracled in" there.

An :class:`Oracle` is a small pluggable protocol so new references can be registered per
convention/config without touching the core. Comparison is by **logical equivalence up to
symmetry**, not byte-equality: two annotations agree iff their ``DETECTOR`` / ``OBSERVABLE``
parity subspaces span the same space over GF(2).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import numpy as np
import stim

from tools.experiment.predictors import _emitted_subspace, _gf2_rank

if TYPE_CHECKING:
    from tools.experiment.config import ExperimentConfig


@dataclass(frozen=True)
class OracleVerdict:
    """Outcome of comparing a re-annotated circuit to an oracle reference."""

    oracle: str
    applies: bool
    equivalent: bool
    detail: str

    def to_dict(self) -> dict[str, object]:
        return {
            "oracle": self.oracle,
            "applies": self.applies,
            "equivalent": self.equivalent,
            "detail": self.detail,
        }


def logically_equivalent(a: stim.Circuit, b: stim.Circuit) -> bool:
    """``True`` iff the two circuits' emitted annotation subspaces span the same GF(2) space."""
    ea = _emitted_subspace(a)
    eb = _emitted_subspace(b)
    if ea.shape[1] != eb.shape[1]:
        # Different measurement counts -> not comparable at the record level.
        return False
    ra = _gf2_rank(ea)
    rb = _gf2_rank(eb)
    rab = _gf2_rank(np.vstack([ea, eb])) if ea.size or eb.size else 0
    return ra == rb == rab


@runtime_checkable
class Oracle(Protocol):
    """A known-correct reference annotation, valid only where :meth:`applies` says so."""

    name: str

    def applies(self, unit: object, config: "ExperimentConfig") -> bool:
        """Whether this oracle is a valid ground truth for ``unit`` under ``config``."""

    def reference(self, unit: object, k: int, native: stim.Circuit) -> stim.Circuit:
        """The known-correct circuit to compare against."""

    def compare(self, reannotated: stim.Circuit, reference: stim.Circuit) -> OracleVerdict:
        """Compare a re-annotated circuit to the reference, up to logical symmetry."""


class NativeFixedBulkOracle:
    """``tqec``'s native annotation, valid ground truth for the ``fixed_bulk`` convention.

    ``reference`` returns the native circuit ``prepare_batch`` already wrote; ``compare`` checks
    the re-annotated circuit is logically equivalent to it.
    """

    name = "native_fixed_bulk"

    def applies(self, unit: object, config: "ExperimentConfig") -> bool:
        return getattr(unit, "convention", None) == "fixed_bulk"

    def reference(self, unit: object, k: int, native: stim.Circuit) -> stim.Circuit:
        return native

    def compare(self, reannotated: stim.Circuit, reference: stim.Circuit) -> OracleVerdict:
        equivalent = logically_equivalent(reannotated, reference)
        detail = (
            "logically equivalent to native (fixed_bulk)"
            if equivalent
            else "NOT logically equivalent to native (fixed_bulk)"
        )
        return OracleVerdict(self.name, applies=True, equivalent=equivalent, detail=detail)


_REGISTRY: dict[str, type] = {
    NativeFixedBulkOracle.name: NativeFixedBulkOracle,
}


def build_oracles(names: list[str]) -> list[Oracle]:
    """Instantiate the named oracles; unknown names raise ``KeyError`` with the valid set."""
    oracles: list[Oracle] = []
    for name in names:
        try:
            oracles.append(_REGISTRY[name]())
        except KeyError:
            raise KeyError(
                f"unknown oracle {name!r}; available: {sorted(_REGISTRY)}"
            ) from None
    return oracles


def available_oracles() -> list[str]:
    return sorted(_REGISTRY)
