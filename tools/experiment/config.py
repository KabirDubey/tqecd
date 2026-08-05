"""``ExperimentConfig``--the knobs for a run, lowered to a ``tqec.orchestration.BatchConfig``."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any


def _toml_value(value: Any) -> str | None:
    """Render a scalar/list as a TOML value, or ``None`` to omit (TOML has no null)."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, (list, tuple)):
        items = [_toml_value(v) for v in value]
        return "[" + ", ".join(i for i in items if i is not None) + "]"
    return '"' + str(value) + '"'


@dataclass(frozen=True)
class SimulationConfig:
    """Optional MCMC sampling (LER-vs-p + Lambda suppression factor). Off by default."""

    enabled: bool = False
    noise_models: tuple[str, ...] = ("uniform_depolarizing",)
    ps: tuple[float, ...] = (1e-3, 2e-3, 5e-3, 1e-2)
    max_shots: int | None = 10_000
    max_errors: int | None = None
    decoders: tuple[str, ...] = ("pymatching",)
    plot: bool = False
    lambda_factor: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SimulationConfig":
        known = {f for f in cls.__dataclass_fields__}
        kwargs = {k: v for k, v in data.items() if k in known}
        for name in ("noise_models", "ps", "decoders"):
            if name in kwargs and kwargs[name] is not None:
                kwargs[name] = tuple(kwargs[name])
        return cls(**kwargs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "noise_models": list(self.noise_models),
            "ps": list(self.ps),
            "max_shots": self.max_shots,
            "max_errors": self.max_errors,
            "decoders": list(self.decoders),
            "plot": self.plot,
            "lambda_factor": self.lambda_factor,
        }


@dataclass(frozen=True)
class ExperimentConfig:
    """Knobs for a batched gadget experiment. Lowers to a ``tqec.orchestration.BatchConfig``."""

    name: str = ""
    inputs: tuple[str, ...] = ()
    conventions: tuple[str, ...] = ("fixed_bulk",)
    ks: tuple[int, ...] = (1, 2, 3)
    windows: tuple[int, ...] = (2,)
    logical_observables: str = "all"
    predictors: tuple[str, ...] = ("parities", "distance")
    oracles: tuple[str, ...] = ()
    noise_models: tuple[str, ...] = ("uniform_depolarizing",)
    ps: tuple[float, ...] = (1e-3,)
    expected_distance: str = "2*k + 1"
    circuit_mode: str = "materialized"
    simulation: SimulationConfig = field(default_factory=SimulationConfig)

    # predictor helpers
    @property
    def run_parities(self) -> bool:
        return "parities" in self.predictors

    @property
    def run_distance(self) -> bool:
        return "distance" in self.predictors

    def enabled_oracles(self) -> list[Any]:
        from tools.experiment.oracle import build_oracles

        return build_oracles(list(self.oracles))

    # lowering to BatchConfig
    def to_batch_config(self) -> Any:
        """Lower to a ``tqec.orchestration.BatchConfig``.

        ``manhattan_radius`` is deliberately not set: it sizes ``tqec``'s native subtemplate search
        and has no effect on ``tqecd.annotate_detectors_automatically`` (the subject under test), so
        the tool leaves it at ``tqec``'s own default. When simulation is enabled the sweep values
        (``ps``, ``noise_models``, ``max_shots``, ``decoders``) come from :attr:`simulation`, so the
        written manifest is directly usable by ``simulate_batch``.
        """
        from tqec.orchestration import BatchConfig

        sim = self.simulation
        return BatchConfig(
            conventions=self.conventions,
            ks=self.ks,
            ps=sim.ps if sim.enabled else self.ps,
            noise_models=sim.noise_models if sim.enabled else self.noise_models,
            decoders=sim.decoders,
            max_shots=sim.max_shots,
            max_errors=sim.max_errors,
            expected_distance=self.expected_distance,
            circuit_mode=self.circuit_mode,
            logical_observables=self.logical_observables,
        )

    def to_dict(self) -> dict[str, Any]:
        """A round-trippable dict (``from_dict(to_dict()) == self``), persisted for ``render``."""
        return {
            "name": self.name,
            "inputs": list(self.inputs),
            "conventions": list(self.conventions),
            "ks": list(self.ks),
            "windows": list(self.windows),
            "logical_observables": self.logical_observables,
            "predictors": list(self.predictors),
            "oracles": list(self.oracles),
            "noise_models": list(self.noise_models),
            "ps": list(self.ps),
            "expected_distance": self.expected_distance,
            "circuit_mode": self.circuit_mode,
            "simulation": self.simulation.to_dict(),
        }

    def to_toml(self) -> str:
        """Render the config as ``[experiment]`` TOML (round-trips through :meth:`from_toml`)."""
        data = self.to_dict()
        simulation = data.pop("simulation")
        lines = ["[experiment]"]
        for key, value in data.items():
            rendered = _toml_value(value)
            if rendered is not None:
                lines.append(f"{key} = {rendered}")
        # Only spell out the MCMC-sampling parameters when sampling is actually enabled; otherwise
        # a config that never samples should not display shots / errors / decoders.
        lines += ["", "[experiment.simulation]"]
        if simulation.get("enabled"):
            for key, value in simulation.items():
                rendered = _toml_value(value)
                if rendered is not None:
                    lines.append(f"{key} = {rendered}")
        else:
            lines.append("enabled = false")
        return "\n".join(lines) + "\n"

    # construction
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExperimentConfig":
        known = {f for f in cls.__dataclass_fields__}
        kwargs: dict[str, Any] = {k: v for k, v in data.items() if k in known}
        for name in (
            "inputs",
            "conventions",
            "ks",
            "windows",
            "predictors",
            "oracles",
            "noise_models",
            "ps",
        ):
            if name in kwargs and kwargs[name] is not None:
                kwargs[name] = tuple(kwargs[name])
        if "simulation" in kwargs and isinstance(kwargs["simulation"], dict):
            kwargs["simulation"] = SimulationConfig.from_dict(kwargs["simulation"])
        return cls(**kwargs)

    @classmethod
    def from_toml(cls, path: str | Path) -> "ExperimentConfig":
        with open(path, "rb") as handle:
            data = tomllib.load(handle)
        # allow an optional [experiment] table wrapper
        if "experiment" in data and isinstance(data["experiment"], dict):
            data = data["experiment"]
        return cls.from_dict(data)

    def with_overrides(self, **overrides: Any) -> "ExperimentConfig":
        return replace(self, **overrides)
