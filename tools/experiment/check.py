"""Check one stim circuit: are its detectors deterministic, what is its fault distance, does it pass?

:func:`check_circuit` is the single scoring path of the testbed: :mod:`tools.experiment.core` calls
it for every re-annotated circuit and every oracle circuit, and it works just as well on any stim
circuit or ``.stim`` file::

    from tools.experiment import check_circuit

    result = check_circuit("memory_d5.stim", expected_distance=5)
    print(result.summary())   # "PASS: deterministic, 0 missing parities, distance 5 (expected 5)"

:func:`compare_circuits` checks two circuits that should behave identically, for example a circuit
and a copy whose coordinates were transformed: same determinism, same distance, same missing
parities and the same detector error model once coordinates are dropped.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import stim

from tools.experiment import predictors

#: How noise is applied before the distance search.
#:
#: * a name of a ``tqec`` ``NoiseModel`` factory (``"uniform_depolarizing"``, ``"si1000"``),
#:   instantiated at the physical error rate ``p``;
#: * a callable returning the noisy circuit (``p`` is not used);
#: * ``None``: the circuit already carries its noise and is used as given.
NoiseModelSpec = str | Callable[[stim.Circuit], stim.Circuit] | None

DEFAULT_NOISE_MODEL = "uniform_depolarizing"
DEFAULT_P = 1e-3


def _first_line(message: str) -> str:
    return message.strip().splitlines()[0] if message.strip() else message


def apply_noise(
    circuit: stim.Circuit,
    noise_model: NoiseModelSpec = DEFAULT_NOISE_MODEL,
    p: float = DEFAULT_P,
) -> stim.Circuit:
    """Return ``circuit`` with noise applied as described by ``noise_model`` (see :data:`NoiseModelSpec`).

    Raises:
        ValueError: if ``noise_model`` names no ``tqec`` ``NoiseModel`` factory.
    """
    if noise_model is None:
        return circuit
    if callable(noise_model):
        return noise_model(circuit)
    from tqec.utils.noise_model import NoiseModel

    factories = {
        name: value.__func__
        for name, value in vars(NoiseModel).items()
        if isinstance(value, staticmethod) and not name.startswith("_")
    }
    factory = factories.get(noise_model)
    if factory is None:
        raise ValueError(
            f"unknown noise model {noise_model!r}; choose from {sorted(factories)}"
        )
    return factory(p).noisy_circuit(circuit)


def _describe_noise(noise_model: NoiseModelSpec, p: float) -> str:
    if noise_model is None:
        return "as given"
    if callable(noise_model):
        return "callable"
    return f"{noise_model}(p={p:g})"


def _load(circuit: stim.Circuit | str | os.PathLike[str]) -> stim.Circuit:
    if isinstance(circuit, stim.Circuit):
        return circuit
    return stim.Circuit.from_file(Path(circuit))


@dataclass(frozen=True)
class CircuitCheck:
    """The outcome of :func:`check_circuit`.

    A field is ``None`` when its check was not requested, or (for ``distance``) could not run.

    Attributes:
        deterministic: every ``DETECTOR`` and ``OBSERVABLE_INCLUDE`` is deterministic in the
            noiseless circuit (stim builds its detector error model without error).
        determinism_error: the first line of stim's error when not deterministic.
        distance_checked: whether the distance search was requested.
        missing_parities: number of independent deterministic measurement parities that no
            detector or observable captures (see :func:`predictors.count_missing_parities`).
        distance: length of the shortest graphlike logical error of the noisy circuit. ``None``
            when the distance was not requested, the circuit is not deterministic, the search
            failed (see ``distance_error``), or the circuit has no graphlike logical error.
        distance_error: why the distance search failed, when it failed for a reason other than
            "no graphlike logical error" (for example an error stim could not decompose).
        expected_distance: the distance the circuit is checked against, if any.
        noise: how noise was applied for the distance search, e.g. ``"si1000(p=0.001)"``.
        num_qubits, num_detectors, num_observables: size of the circuit, for context.
    """

    deterministic: bool
    determinism_error: str | None
    distance_checked: bool
    missing_parities: int | None
    distance: int | None
    distance_error: str | None
    expected_distance: int | None
    noise: str
    num_qubits: int
    num_detectors: int
    num_observables: int

    @property
    def parities_ok(self) -> bool | None:
        """``missing_parities == 0``, or ``None`` if parities were not checked."""
        return None if self.missing_parities is None else self.missing_parities == 0

    @property
    def distance_ok(self) -> bool | None:
        """``distance == expected_distance``, or ``None`` if there is nothing to compare."""
        if self.expected_distance is None or not self.distance_checked:
            return None
        return self.deterministic and self.distance == self.expected_distance

    @property
    def passed(self) -> bool:
        """Deterministic, and every requested check succeeded.

        A requested distance search that failed (``distance_error``) fails the check even
        without an expected distance. Without an expected distance, any distance (including
        "no graphlike logical error") passes: there is nothing to compare it to.
        """
        return not self.failure_reasons()

    def failure_reasons(self) -> list[str]:
        """One short reason per failed check (empty when the circuit passes)."""
        if not self.deterministic:
            return [self.determinism_error or "non-deterministic detectors"]
        reasons: list[str] = []
        if self.parities_ok is False:
            n = self.missing_parities
            reasons.append(f"{n} missing parit{'y' if n == 1 else 'ies'}")
        if self.distance_error is not None:
            reasons.append(f"distance search failed: {self.distance_error}")
        elif self.distance_ok is False:
            found = (
                "no graphlike logical error" if self.distance is None else self.distance
            )
            reasons.append(f"distance {found} != expected {self.expected_distance}")
        return reasons

    def summary(self) -> str:
        """One line for logs and the CLI."""
        parts = ["deterministic" if self.deterministic else "NOT deterministic"]
        if self.missing_parities is not None:
            parts.append(f"{self.missing_parities} missing parities")
        if self.distance_checked and self.deterministic:
            if self.distance_error is not None:
                parts.append("distance search failed")
            else:
                found = (
                    "no graphlike logical error"
                    if self.distance is None
                    else f"distance {self.distance}"
                )
                if self.expected_distance is not None:
                    found += f" (expected {self.expected_distance})"
                parts.append(found)
        verdict = "PASS" if self.passed else "FAIL"
        text = f"{verdict}: {', '.join(parts)}"
        reasons = self.failure_reasons()
        return f"{text} -- {'; '.join(reasons)}" if reasons else text


def check_circuit(
    circuit: stim.Circuit | str | os.PathLike[str],
    *,
    expected_distance: int | None = None,
    noise_model: NoiseModelSpec = DEFAULT_NOISE_MODEL,
    p: float = DEFAULT_P,
    check_parities: bool = True,
    check_distance: bool = True,
) -> CircuitCheck:
    """Check that ``circuit`` is deterministic and measure its fault distance.

    Args:
        circuit: a ``stim.Circuit`` or the path of a ``.stim`` file. It should not be noisy unless
            ``noise_model`` is ``None``.
        expected_distance: the distance the circuit should have (e.g. ``2 * k + 1``); when given,
            a different distance fails the check.
        noise_model: how noise is applied before the distance search (see
            :data:`NoiseModelSpec`). The distance depends on the model, not on ``p``.
        p: physical error rate for a named noise model.
        check_parities: count the deterministic parities no annotation captures (a GF(2)
            reduction over stim's flow generators; slow on large circuits).
        check_distance: search the shortest graphlike logical error.

    Returns:
        A :class:`CircuitCheck`. Determinism is always checked; the distance search only runs on a
        deterministic circuit.
    """
    circuit = _load(circuit)
    try:
        circuit.without_noise().detector_error_model()
        deterministic, determinism_error = True, None
    except ValueError as exc:
        deterministic, determinism_error = False, _first_line(str(exc))

    distance = distance_error = None
    if check_distance and deterministic:
        try:
            distance = predictors.shortest_graphlike_error(
                apply_noise(circuit, noise_model, p)
            )
        except ValueError as exc:
            distance_error = _first_line(str(exc))

    return CircuitCheck(
        deterministic=deterministic,
        determinism_error=determinism_error,
        distance_checked=check_distance,
        missing_parities=(
            predictors.count_missing_parities(circuit) if check_parities else None
        ),
        distance=distance,
        distance_error=distance_error,
        expected_distance=expected_distance,
        noise=_describe_noise(noise_model, p) if check_distance else "",
        num_qubits=circuit.num_qubits,
        num_detectors=circuit.num_detectors,
        num_observables=circuit.num_observables,
    )


def _coordinate_free_dem(dem: stim.DetectorErrorModel) -> stim.DetectorErrorModel:
    """``dem`` flattened, with every ``detector`` declaration stripped of its coordinates."""
    out = stim.DetectorErrorModel()
    for instruction in dem.flattened():
        if instruction.type == "detector":
            instruction = stim.DemInstruction(
                "detector", [], instruction.targets_copy()
            )
        out.append(instruction)
    return out


@dataclass(frozen=True)
class CircuitComparison:
    """The outcome of :func:`compare_circuits`.

    Attributes:
        a, b: the :class:`CircuitCheck` of each circuit.
        same_dem_without_coords: the two noisy detector error models are identical once flattened
            and stripped of detector coordinates (a structural comparison: same detector and
            observable counts and the same error instructions in the same order). ``None`` when a
            model could not be built (a circuit is not deterministic, or stim failed on the noisy
            circuit).
    """

    a: CircuitCheck
    b: CircuitCheck
    same_dem_without_coords: bool | None

    def differences(self) -> list[str]:
        """One short line per property on which the two circuits differ."""
        diffs: list[str] = []
        for name in (
            "num_detectors",
            "num_observables",
            "deterministic",
            "missing_parities",
            "distance",
            "distance_error",
        ):
            va, vb = getattr(self.a, name), getattr(self.b, name)
            if va != vb:
                diffs.append(f"{name}: {va} != {vb}")
        if self.same_dem_without_coords is None:
            diffs.append("detector error models not comparable")
        elif not self.same_dem_without_coords:
            diffs.append("detector error models differ (ignoring coordinates)")
        return diffs

    @property
    def equivalent(self) -> bool:
        """Both circuits behave identically: no :meth:`differences` and comparable models."""
        return not self.differences()


def compare_circuits(
    a: stim.Circuit | str | os.PathLike[str],
    b: stim.Circuit | str | os.PathLike[str],
    *,
    expected_distance: int | None = None,
    noise_model: NoiseModelSpec = DEFAULT_NOISE_MODEL,
    p: float = DEFAULT_P,
    check_parities: bool = True,
    check_distance: bool = True,
) -> CircuitComparison:
    """Check two circuits that should behave identically (e.g. before and after a coordinate map).

    Both circuits go through :func:`check_circuit` with the same arguments; their noisy detector
    error models are then compared with coordinates dropped. Two non-deterministic circuits are
    never reported equivalent, since their models cannot be compared.
    """
    a, b = _load(a), _load(b)
    kwargs = {
        "expected_distance": expected_distance,
        "noise_model": noise_model,
        "p": p,
        "check_parities": check_parities,
        "check_distance": check_distance,
    }
    check_a, check_b = check_circuit(a, **kwargs), check_circuit(b, **kwargs)
    same_dem: bool | None = None
    if check_a.deterministic and check_b.deterministic:
        try:
            dem_a = apply_noise(a, noise_model, p).detector_error_model()
            dem_b = apply_noise(b, noise_model, p).detector_error_model()
        except ValueError:
            pass  # the failure is in the checks' distance_error when the distance was searched
        else:
            same_dem = _coordinate_free_dem(dem_a) == _coordinate_free_dem(dem_b)
    return CircuitComparison(check_a, check_b, same_dem)
