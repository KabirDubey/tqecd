"""CLI: ``python -m tools.experiment --gallery cnot --k 1,2`` or ``--config cfg.toml``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from tools.experiment.config import ExperimentConfig
from tools.experiment.core import run_experiment


def _gallery_graph(name: str):
    from tqec import gallery
    from tqec.utils.enums import Basis

    builders = {
        "cnot": lambda: gallery.cnot(Basis.Z),
        "cnot_open": lambda: gallery.cnot(None),
        "three_cnots": lambda: gallery.three_cnots(Basis.Z),
        "memory": lambda: gallery.memory(Basis.Z),
        "cz": lambda: gallery.cz(Basis.Z),
    }
    if name not in builders:
        raise SystemExit(f"unknown gallery gadget {name!r}; choose from {sorted(builders)}")
    return builders[name]()


def _ints(text: str) -> tuple[int, ...]:
    return tuple(int(x) for x in text.split(",") if x.strip())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.experiment")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--config", type=Path, help="TOML experiment config")
    source.add_argument("--gallery", help="gallery gadget name (cnot, three_cnots, memory, ...)")
    source.add_argument("--input", type=Path, action="append", help=".dae / .bgraph input (repeatable)")
    parser.add_argument("--k", type=_ints, help="comma-separated ks, e.g. 1,2,3")
    parser.add_argument("--conventions", type=lambda s: tuple(s.split(",")))
    parser.add_argument("--windows", type=_ints)
    parser.add_argument("--manhattan-radii", type=_ints, dest="manhattan_radii")
    parser.add_argument("--oracles", type=lambda s: tuple(s.split(",")))
    parser.add_argument("--out", type=Path, default=Path("experiment_out"))
    args = parser.parse_args(argv)

    if args.config:
        config = ExperimentConfig.from_toml(args.config)
    else:
        config = ExperimentConfig()

    overrides = {}
    if args.k:
        overrides["ks"] = args.k
    if args.conventions:
        overrides["conventions"] = args.conventions
    if args.windows:
        overrides["windows"] = args.windows
    if args.manhattan_radii:
        overrides["manhattan_radii"] = args.manhattan_radii
    if args.oracles:
        overrides["oracles"] = args.oracles
    if overrides:
        config = config.with_overrides(**overrides)

    if args.gallery:
        inputs = [_gallery_graph(args.gallery)]
    elif args.input:
        inputs = [str(p) for p in args.input]
    else:  # config-only run defaults to a cnot smoke gadget
        inputs = [_gallery_graph("cnot")]

    report = run_experiment(inputs, config, args.out)
    print(report.to_text())
    print(f"\nwrote {args.out}/report.json, report.html, report.txt")
    s = report.summary()
    return 0 if s["predictors_fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
