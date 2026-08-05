"""Reference *oracles*--optional, user-supplied ground truth (``stim`` + ``numpy``).

The general case has **no ground truth**: for an arbitrary gadget it is often unknown whether any
detector annotation reaches full distance, and ``tqec``'s own native ``fixed_bulk`` annotation is
*not* a reliable reference for most gadgets. So this module ships **no** default oracle, and an
experiment need not use one at all.

Oracles are entirely opt-in. A user who does have a known-correct reference for a gadget wires it
in here as either

* a fixed annotated ``stim.Circuit`` (:class:`CircuitOracle`), or
* a callable that emits one per ``(unit, k, native)`` (:class:`CallableOracle`) -- e.g. a method
  that synthesises a differently-built circuit with the *same macroscopic behavior*.

A reference is expected to share the gadget's logical action, so agreement is checked by
**logical equivalence up to symmetry**: two annotations agree iff their ``DETECTOR`` /
``OBSERVABLE`` parity subspaces span the same space over GF(2) (not by byte-equality). Register an
oracle with :func:`register_oracle` (resolved by name from config) or pass oracle objects straight
to :func:`tools.experiment.core.run_experiment`.

One built-in oracle ships registered: :data:`NATIVE_ORACLE`, named ``"native"``. It uses ``tqec``'s
own native annotation (the subtemplate route in ``tqec.compile.detectors.compute``) as the ground
truth for the ``tqecd.annotate_detectors_automatically`` reannotation under test. This is the one
documented exception to "no ground truth": native is a reliable reference **for the ``fixed_bulk``
convention** (so the oracle only applies there). It is still opt-in -- nothing runs it unless a run
selects it by name (``oracles = ["native"]`` in a config, or ``--oracles native`` on the CLI).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import stim

from tools.experiment.predictors import _emitted_vectors, _gf2_rank

if TYPE_CHECKING:
    from tools.experiment.config import ExperimentConfig

#: A callable emitting the reference annotated circuit for one prepared unit.
ReferenceEmitter = Callable[[object, int, stim.Circuit], stim.Circuit]
#: A predicate deciding whether an oracle is a valid reference for a given unit.
AppliesPredicate = Callable[[object, "ExperimentConfig"], bool]


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
    if a.num_measurements != b.num_measurements:
        # Different measurement counts -> not comparable at the record level.
        return False
    ea = _emitted_vectors(a)
    eb = _emitted_vectors(b)
    ra = _gf2_rank(ea)
    rb = _gf2_rank(eb)
    rab = _gf2_rank([*ea, *eb])
    return ra == rb == rab


def _verdict(
    name: str, reannotated: stim.Circuit, reference: stim.Circuit
) -> OracleVerdict:
    equivalent = logically_equivalent(reannotated, reference)
    detail = (
        "logically equivalent to reference"
        if equivalent
        else "NOT logically equivalent to reference"
    )
    return OracleVerdict(name, applies=True, equivalent=equivalent, detail=detail)


@runtime_checkable
class Oracle(Protocol):
    """A user-supplied known-correct reference, valid only where :meth:`applies` says so."""

    name: str

    def applies(self, unit: object, config: ExperimentConfig) -> bool:
        """Whether this oracle is a valid ground truth for ``unit`` under ``config``."""

    def reference(self, unit: object, k: int, native: stim.Circuit) -> stim.Circuit:
        """The known-correct circuit to compare against."""

    def compare(
        self, reannotated: stim.Circuit, reference: stim.Circuit
    ) -> OracleVerdict:
        """Compare a re-annotated circuit to the reference, up to logical symmetry."""


def _always(unit: object, config: ExperimentConfig) -> bool:
    return True


@dataclass(frozen=True)
class CircuitOracle:
    """A fixed, user-supplied annotated reference circuit.

    Use when the same known-correct circuit is the reference for every prepared unit the oracle
    applies to (constrain that set with ``applies_to``).
    """

    name: str
    reference_circuit: stim.Circuit
    applies_to: AppliesPredicate = _always

    def applies(self, unit: object, config: ExperimentConfig) -> bool:
        return self.applies_to(unit, config)

    def reference(self, unit: object, k: int, native: stim.Circuit) -> stim.Circuit:
        return self.reference_circuit

    def compare(
        self, reannotated: stim.Circuit, reference: stim.Circuit
    ) -> OracleVerdict:
        return _verdict(self.name, reannotated, reference)


@dataclass(frozen=True)
class CallableOracle:
    """A user-supplied callable emitting the reference annotated circuit per ``(unit, k, native)``.

    The callable may synthesise a differently-built circuit with the same macroscopic behavior, or
    return an externally-annotated circuit loaded from disk--anything ``stim`` can represent.
    """

    name: str
    emit: ReferenceEmitter
    applies_to: AppliesPredicate = _always

    def applies(self, unit: object, config: ExperimentConfig) -> bool:
        return self.applies_to(unit, config)

    def reference(self, unit: object, k: int, native: stim.Circuit) -> stim.Circuit:
        return self.emit(unit, k, native)

    def compare(
        self, reannotated: stim.Circuit, reference: stim.Circuit
    ) -> OracleVerdict:
        return _verdict(self.name, reannotated, reference)


# The registry is EMPTY by default: no annotation is treated as ground truth unless a user
# explicitly registers a reference (or passes oracle objects straight to run_experiment).
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


def _native_reference(unit: object, k: int, native: stim.Circuit) -> stim.Circuit:
    """Reference emitter for the built-in native oracle: tqec's own native annotation."""
    return native


def _is_fixed_bulk(unit: object, config: ExperimentConfig) -> bool:
    """native is a reliable reference only for the ``fixed_bulk`` convention."""
    return getattr(unit, "convention", "") == "fixed_bulk"


#: Built-in oracle: tqec's native ``fixed_bulk`` annotation as ground truth for the
#: ``annotate_detectors_automatically`` reannotation under test. Opt in with ``oracles=["native"]``.
NATIVE_ORACLE = CallableOracle(
    name="native", emit=_native_reference, applies_to=_is_fixed_bulk
)
register_oracle(NATIVE_ORACLE)
