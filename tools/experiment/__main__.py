"""CLI for the experiment tool.

Examples::

    python -m tools.experiment --gallery cnot --k 1,2
    python -m tools.experiment --gallery all --k 1,2
    python -m tools.experiment --config tools/experiment/configs/manhattan_sensitivity.toml
    python -m tools.experiment --input my_gadget.dae --k 1,2,3

``--gallery all`` runs every gadget in ``tqec.gallery`` in one experiment; ``--gallery <name>``
runs a single one; ``--list-gallery`` prints the available names.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Callable

from tools.experiment.config import ExperimentConfig
from tools.experiment.core import run_experiment


def _gallery_builders() -> dict[str, Callable[[], Any]]:
    """A zero-arg builder for every gadget in ``tqec.gallery`` (plus open-port variants).

    Every builder in ``tqec.gallery`` is wired here, so the CLI can drive the whole gallery. The
    ``*_open`` variants leave the ports open (``prepare_batch`` then fills them for simulation).
    """
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


# The canonical gadgets `--gallery all` runs (the closed, port-filled form of every gallery entry).
_GALLERY_ALL = (
    "cnot",
    "cz",
    "memory",
    "move_rotation",
    "stability",
    "steane_encoding",
    "three_cnots",
)


def _gallery_graphs(name: str) -> list[Any]:
    """Build the requested gallery input(s); ``all`` builds every canonical gadget."""
    builders = _gallery_builders()
    if name == "all":
        return [builders[n]() for n in _GALLERY_ALL]
    if name not in builders:
        raise SystemExit(
            f"unknown gallery gadget {name!r}; choose from {sorted(builders)} or 'all'"
        )
    return [builders[name]()]


def _ints(text: str) -> tuple[int, ...]:
    return tuple(int(x) for x in text.split(",") if x.strip())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.experiment")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--config", type=Path, help="TOML experiment config")
    source.add_argument(
        "--gallery", help="gallery gadget name, or 'all' for every gadget (see --list-gallery)"
    )
    source.add_argument(
        "--input", type=Path, action="append", help=".dae / .bgraph input (repeatable)"
    )
    source.add_argument(
        "--list-gallery",
        action="store_true",
        help="print the available gallery gadget names and exit",
    )
    parser.add_argument("--k", type=_ints, help="comma-separated ks, e.g. 1,2,3")
    parser.add_argument("--conventions", type=lambda s: tuple(s.split(",")))
    parser.add_argument("--windows", type=_ints)
    parser.add_argument("--manhattan-radii", type=_ints, dest="manhattan_radii")
    parser.add_argument("--oracles", type=lambda s: tuple(s.split(",")))
    parser.add_argument("--out", type=Path, default=Path("experiment_out"))
    args = parser.parse_args(argv)

    if args.list_gallery:
        print("gallery gadgets:", ", ".join(sorted(_gallery_builders())))
        print("'all' runs every canonical gadget:", ", ".join(_GALLERY_ALL))
        return 0

    config = ExperimentConfig.from_toml(args.config) if args.config else ExperimentConfig()

    overrides: dict[str, Any] = {}
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
        inputs = _gallery_graphs(args.gallery)
    elif args.input:
        inputs = [str(p) for p in args.input]
    else:  # config-only run defaults to a cnot smoke gadget
        inputs = _gallery_graphs("cnot")

    report = run_experiment(inputs, config, args.out)
    print(report.to_text())
    print(f"\nwrote {args.out}/report.json, report.html, report.txt")
    s = report.summary()
    return 0 if s["predictors_fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
