"""Reference *oracles*--alternate annotators to compare the experimental one against.

The experimental subject is ``tqecd``'s windowed ``annotate_detectors_automatically``
(:func:`tools.experiment.annotators.reannotate`). An **oracle is another annotator** producing an
alternate annotation of the same gadget; the report scores each oracle on the *same* metric as the
experimental one (distance vs ``2k+1``) and additionally checks logical equivalence to it, so the
annotators sit side by side. Oracles are opt-in: none run unless a run selects them.

Two oracles ship built in:

* ``native`` -- ``tqec``'s own native annotation (the circuit ``prepare_batch`` wrote), a valid
  same-behavior reference wherever ``tqec`` could compile the gadget (every convention).
* ``tqecd_main`` -- the main-branch (windowless) ``tqecd`` ``annotate_detectors_automatically``,
  run out-of-process (see :mod:`tools.experiment.annotators`); it isolates the effect of windowing.
  It applies only when the main-branch worktree is available.

Users can add their own: a fixed annotated circuit (:class:`CircuitOracle`) or a callable emitting
one per ``(unit, k, native)`` (:class:`CallableOracle`). Equivalence is checked up to logical
symmetry -- the ``DETECTOR`` / ``OBSERVABLE`` parity subspaces must span the same GF(2) space.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import stim

from tools.experiment import annotators
from tools.experiment.predictors import _emitted_vectors, _gf2_rank

if TYPE_CHECKING:
    from tools.experiment.config import ExperimentConfig

#: A callable emitting the alternate annotated circuit for one prepared unit.
ReferenceEmitter = Callable[[object, int, stim.Circuit], stim.Circuit]
#: A predicate deciding whether an oracle is a valid reference for a given unit.
AppliesPredicate = Callable[[object, "ExperimentConfig"], bool]


def logically_equivalent(a: stim.Circuit, b: stim.Circuit) -> bool:
    """``True`` iff the two circuits' emitted annotation subspaces span the same GF(2) space.

    ``DETECTOR`` and ``OBSERVABLE`` records are pooled into one span, so this certifies the same
    overall parity space -- not that observables map to observables specifically. The built-in
    oracles share identical reattached observables, so for them it is an exact check.
    """
    if a.num_measurements != b.num_measurements:
        # Different measurement counts -> not comparable at the record level.
        return False
    ea = _emitted_vectors(a)
    eb = _emitted_vectors(b)
    ra = _gf2_rank(ea)
    rb = _gf2_rank(eb)
    rab = _gf2_rank([*ea, *eb])
    return ra == rb == rab


@runtime_checkable
class Oracle(Protocol):
    """An alternate annotator, valid only where :meth:`applies` says so."""

    name: str

    def applies(self, unit: object, config: ExperimentConfig) -> bool:
        """Whether this oracle can annotate ``unit`` under ``config``."""

    def annotate(self, unit: object, k: int, native: stim.Circuit) -> stim.Circuit:
        """The oracle's alternate annotation, scored side by side with the experimental one."""


def _always(unit: object, config: ExperimentConfig) -> bool:
    return True


@dataclass(frozen=True)
class CircuitOracle:
    """A fixed, user-supplied annotated reference circuit (same one for every unit it applies to)."""

    name: str
    reference_circuit: stim.Circuit
    applies_to: AppliesPredicate = _always

    def applies(self, unit: object, config: ExperimentConfig) -> bool:
        return self.applies_to(unit, config)

    def annotate(self, unit: object, k: int, native: stim.Circuit) -> stim.Circuit:
        return self.reference_circuit


@dataclass(frozen=True)
class CallableOracle:
    """A user-supplied callable emitting the alternate annotation per ``(unit, k, native)``."""

    name: str
    emit: ReferenceEmitter
    applies_to: AppliesPredicate = _always

    def applies(self, unit: object, config: ExperimentConfig) -> bool:
        return self.applies_to(unit, config)

    def annotate(self, unit: object, k: int, native: stim.Circuit) -> stim.Circuit:
        return self.emit(unit, k, native)


# The registry holds the built-in annotator oracles below plus anything a user registers.
_REGISTRY: dict[str, Oracle] = {}


def register_oracle(oracle: Oracle) -> None:
    """Register a reference oracle so a config can select it by ``oracle.name``."""
    _REGISTRY[oracle.name] = oracle


def unregister_oracle(name: str) -> None:
    """Remove a registered oracle (no-op if absent)."""
    _REGISTRY.pop(name, None)


def build_oracles(names: list[str]) -> list[Oracle]:
    """Resolve registered oracles by name; unknown names raise ``KeyError`` with the valid set."""
    oracles: list[Oracle] = []
    for name in names:
        try:
            oracles.append(_REGISTRY[name])
        except KeyError:
            raise KeyError(
                f"unknown oracle {name!r}; register it with register_oracle() first. "
                f"available: {sorted(_REGISTRY)}"
            ) from None
    return oracles


def available_oracles() -> list[str]:
    """Names of the currently registered oracles (``"native"`` plus any the user registered)."""
    return sorted(_REGISTRY)


#: Built-in oracle: tqec's native annotation (the circuit ``prepare_batch`` wrote), every convention.
NATIVE_ORACLE = CallableOracle(
    name="native",
    emit=lambda unit, k, native: annotators.native_annotation(native),
    applies_to=_always,
)
#: Built-in oracle: main-branch (windowless) tqecd, run out-of-process. Isolates the windowing pass.
#: It always applies when selected: if the main-branch worktree is missing, ``annotate`` raises and
#: the row records the error (surfaced in the oracle's cell) rather than silently omitting it.
MAIN_ORACLE = CallableOracle(
    name="tqecd_main",
    emit=lambda unit, k, native: annotators.main_branch_reannotation(native),
    applies_to=_always,
)
register_oracle(NATIVE_ORACLE)
register_oracle(MAIN_ORACLE)
