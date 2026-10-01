"""CLI for the experiment tool.

Examples::

    python -m tools.experiment --gallery cnot --k 1,2
    python -m tools.experiment --gallery all --k 1,2
    python -m tools.experiment --config tools/experiment/configs/ler.toml
    python -m tools.experiment --input my_gadget.dae --k 1,2,3
    python -m tools.experiment --render experiment_out                # rebuild report.html only
    python -m tools.experiment --reannotate experiment_out            # re-score from disk, no recompile
    python -m tools.experiment --reannotate experiment_out --windows 3  # re-score a new tqecd window
    python -m tools.experiment --simulate experiment_out --noise-models si1000  # LER, no rebuild
    python -m tools.experiment --clean experiment_out                # delete a run's output + logs

``--gallery all`` runs every gadget in ``tqec.gallery`` in one experiment; ``--gallery <name>``
runs a single one; ``--list-gallery`` prints the available names. ``--render <run_dir>`` rebuilds
``report.html`` from an existing ``report.json`` (UI only--no annotation, no recompile).
``--reannotate <run_dir>`` re-annotates and re-scores a run's on-disk circuits with ``tqecd``
(no recompile); pass ``--windows`` / ``--oracles`` to re-score with different tqecd settings.
``--simulate <run_dir>`` measures a run's circuits (LER-vs-p plots) under ``--noise-models`` /
``--ps`` without rebuilding, so two noise models can be compared on identical circuits.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from tools.experiment import gadgets
from tools.experiment.config import ExperimentConfig
from tools.experiment.core import run_experiment


def _ints(text: str) -> tuple[int, ...]:
    return tuple(int(x) for x in text.split(",") if x.strip())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.experiment")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--config", type=Path, help="TOML experiment config")
    source.add_argument(
        "--gallery",
        help="a gallery gadget, tool batch, or 'all' (see --list-gallery)",
        metavar="NAME",
    )
    source.add_argument(
        "--input", type=Path, action="append", help=".dae / .bgraph input (repeatable)"
    )
    source.add_argument(
        "--list-gallery",
        action="store_true",
        help="print the available gallery gadget names and exit",
    )
    source.add_argument(
        "--render",
        type=Path,
        metavar="RUN_DIR",
        help="rebuild report.html from an existing run dir's report.json (UI only, no annotation)",
    )
    source.add_argument(
        "--reannotate",
        type=Path,
        metavar="RUN_DIR",
        help="re-annotate and re-score an existing run dir's on-disk circuits with tqecd (no recompile)",
    )
    source.add_argument(
        "--simulate",
        type=Path,
        metavar="RUN_DIR",
        help="measure an existing run dir's circuits under a noise model (LER plots), no recompile",
    )
    source.add_argument(
        "--clean",
        type=Path,
        nargs="?",
        const=Path("experiment_out"),
        metavar="RUN_DIR",
        help="delete a run directory's generated output and logs (default: experiment_out)",
    )
    parser.add_argument("--k", type=_ints, help="comma-separated ks, e.g. 1,2,3")
    parser.add_argument("--conventions", type=lambda s: tuple(s.split(",")))
    parser.add_argument("--windows", type=_ints)
    parser.add_argument("--oracles", type=lambda s: tuple(s.split(",")))
    parser.add_argument(
        "--noise-models",
        dest="noise_models",
        type=lambda s: tuple(x for x in s.split(",") if x.strip()),
        help="comma-separated noise-model names for --simulate, e.g. si1000,uniform_depolarizing",
    )
    parser.add_argument(
        "--ps",
        type=lambda s: tuple(float(x) for x in s.split(",") if x.strip()),
        help="comma-separated physical error rates for --simulate, e.g. 1e-3,2e-3,5e-3",
    )
    parser.add_argument("--out", type=Path, default=Path("experiment_out"))
    args = parser.parse_args(argv)

    if args.list_gallery:
        avail = gadgets.available_inputs()
        print("gallery gadgets:", ", ".join(avail["gallery"]))
        print("tool batches: ", ", ".join(avail["batches"]))
        print(
            "'all' runs every canonical gallery gadget:", ", ".join(gadgets.GALLERY_ALL)
        )
        return 0

    if args.clean is not None:
        import shutil

        target = args.clean
        if not target.exists():
            print(f"nothing to clean: {target} does not exist", file=sys.stderr)
            return 0
        # Guard against a mistyped path wiping something important: only remove a directory that
        # actually looks like an experiment run (its own generated output + logs).
        markers = ("report.json", "logs", "config.json")
        looks_like_run = (
            target.name == "experiment_out"
            or any((target / m).exists() for m in markers)
            or any(target.glob("mr*"))
        )
        if not target.is_dir() or not looks_like_run:
            print(
                f"refusing to clean {target}: it does not look like an experiment run dir "
                "(expected report.json / logs / config.json / mr*).",
                file=sys.stderr,
            )
            return 2
        shutil.rmtree(target)
        print(f"removed experiment run output at {target.resolve()}", file=sys.stderr)
        return 0

    if args.render:
        from tools.experiment.core import render_report

        report = render_report(args.render)
        print(report.to_text(), file=sys.stderr)
        run_dir = Path(args.render)
        html_path = (run_dir if run_dir.is_dir() else run_dir.parent) / "report.html"
        print("re-rendered report.html from report.json", file=sys.stderr)
        print(
            f"to see it in your browser run: open {html_path.resolve()}",
            file=sys.stderr,
        )
        s = report.summary()
        return 0 if s["predictors_fail"] == 0 else 1

    if args.reannotate:
        from tools.experiment.core import reannotate_run

        reannotate_overrides: dict[str, Any] = {}
        if args.windows:
            reannotate_overrides["windows"] = args.windows
        if args.oracles:
            reannotate_overrides["oracles"] = args.oracles
        baked = [
            flag
            for flag, value in (
                ("--k", args.k),
                ("--conventions", args.conventions),
            )
            if value
        ]
        if baked:
            print(
                f"--reannotate ignores {', '.join(baked)}: those are baked into the prepared "
                "circuits on disk. Re-run without --reannotate to change them.",
                file=sys.stderr,
            )
        report = reannotate_run(args.reannotate, overrides=reannotate_overrides)
        s = report.summary()
        return 0 if s["predictors_fail"] == 0 else 1

    if args.simulate:
        from tools.experiment.core import simulate_run

        report = simulate_run(args.simulate, noise_models=args.noise_models, ps=args.ps)
        s = report.summary()
        return 0 if s["predictors_fail"] == 0 else 1

    config = (
        ExperimentConfig.from_toml(args.config) if args.config else ExperimentConfig()
    )

    overrides: dict[str, Any] = {}
    if args.k:
        overrides["ks"] = args.k
    if args.conventions:
        overrides["conventions"] = args.conventions
    if args.windows:
        overrides["windows"] = args.windows
    if args.oracles:
        overrides["oracles"] = args.oracles
    if overrides:
        config = config.with_overrides(**overrides)

    if args.gallery:
        specs = [args.gallery]
    elif args.input:
        specs = [str(p) for p in args.input]
    elif config.inputs:
        specs = list(config.inputs)  # the config fully defines its own inputs
    else:  # nothing specified anywhere -> a cnot smoke gadget
        specs = ["cnot"]
    try:
        inputs = gadgets.resolve_inputs(specs)
    except ValueError as exc:
        raise SystemExit(str(exc)) from None

    report = run_experiment(
        inputs, config, args.out
    )  # prints the console summary + open hint
    s = report.summary()
    return 0 if s["predictors_fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
