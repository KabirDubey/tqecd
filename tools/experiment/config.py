"""``ExperimentConfig``--a thin façade that lowers to a ``tqec.orchestration.BatchConfig``.

The ``tqec`` import is deferred into :meth:`ExperimentConfig.to_batch_config` so that importing
this module (and the ``stim`` + ``tqecd`` + ``numpy`` layers) never requires the optional
``tqec`` dependency.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SimulationConfig:
    """Optional gold-standard simulation (LER / Lambda). Off by default."""

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


@dataclass(frozen=True)
class ExperimentConfig:
    """Knobs for a batched gadget experiment. Lowers to ``BatchConfig`` per manhattan radius."""

    conventions: tuple[str, ...] = ("fixed_bulk",)
    ks: tuple[int, ...] = (1, 2, 3)
    windows: tuple[int, ...] = (2,)
    manhattan_radii: tuple[int, ...] = (2,)
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
    def to_batch_config(self, *, manhattan_radius: int) -> Any:
        """Lower to a ``tqec.orchestration.BatchConfig`` for one manhattan radius.

        When simulation is enabled the sweep values (``ps``, ``noise_models``, ``max_shots``,
        ``decoders``) come from :attr:`simulation`, so the written manifest is directly usable by
        ``simulate_batch``. Prepared circuits are noiseless, so this never affects the predictors.
        """
        from tqec.orchestration import BatchConfig

        sim = self.simulation
        return BatchConfig(
            conventions=self.conventions,
            ks=self.ks,
            ps=sim.ps if sim.enabled else self.ps,
            noise_models=sim.noise_models if sim.enabled else self.noise_models,
            decoders=sim.decoders,
            manhattan_radius=manhattan_radius,
            max_shots=sim.max_shots,
            max_errors=sim.max_errors,
            expected_distance=self.expected_distance,
            circuit_mode=self.circuit_mode,
            logical_observables=self.logical_observables,
        )

    # construction
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExperimentConfig":
        known = {f for f in cls.__dataclass_fields__}
        kwargs: dict[str, Any] = {k: v for k, v in data.items() if k in known}
        for name in (
            "conventions",
            "ks",
            "windows",
            "manhattan_radii",
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
