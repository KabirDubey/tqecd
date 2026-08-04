# /// script
# requires-python = ">=3.11"
# ///
"""Live documentation of the experiment tool's supported uses.

Run it against the tqec checkout that carries ``tqec.orchestration`` and the tqecd under test::

    PYTHONPATH="<tqecd_worktree>/src:<tqecd_worktree>" \\
      marimo edit tools/experiment/notebooks/workflow.py

The spec this notebook demonstrates is ``tools/experiment/SPEC.md``.
"""

import marimo

__generated_with = "0.23.16"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo

    return (mo,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # The gadget experiment workflow

    Build a gadget's circuits **once**, then re-measure and re-draw them cheaply. Every stage
    reads the previous stage's on-disk output and writes into the same run directory. This
    notebook runs each stage live; the written contract is `tools/experiment/SPEC.md`.

    | stage | what it does | recompiles? |
    | --- | --- | --- |
    | **run** | compile (via `tqec.orchestration`) + re-annotate with `tqecd` + score | yes (once) |
    | **render** | rebuild `report.html` from `report.json` -- UI only | no |
    | **reannotate** | re-annotate + re-score the prepared circuits | no |
    | **simulate** | measure LER-vs-p under a noise model | no |
    """)
    return


@app.cell
def _(mo):
    # Entry points + a throwaway run directory shared by every stage below.
    import tempfile
    from pathlib import Path

    try:
        from tools.experiment import (
            ExperimentConfig,
            reannotate_run,
            render_report,
            run_experiment,
            simulate_run,
        )
        from tqec import gallery
        from tqec.utils.enums import Basis

        _ready = True
        _msg = ""
    except Exception as exc:  # tqec / tqecd not importable in this environment
        _ready = False
        _msg = f"Could not import the tool + tqec: `{exc}`.  Launch with the PYTHONPATH shown at the top."

    out_dir = Path(tempfile.mkdtemp(prefix="experiment_nb_"))
    mo.stop(not _ready, mo.md(f"⚠️ {_msg}"))

    GADGETS = {
        "cnot": lambda: gallery.cnot(Basis.Z),
        "memory": lambda: gallery.memory(Basis.Z),
        "three_cnots": lambda: gallery.three_cnots(Basis.Z),
    }
    mo.md(f"Run directory for this session: `{out_dir}`")
    return (
        ExperimentConfig,
        GADGETS,
        out_dir,
        reannotate_run,
        render_report,
        run_experiment,
        simulate_run,
    )


@app.cell(hide_code=True)
def _(GADGETS, mo):
    gadget = mo.ui.dropdown(list(GADGETS), value="cnot", label="gadget")
    convention = mo.ui.dropdown(["fixed_bulk", "fixed_boundary"], value="fixed_bulk", label="convention")
    kk = mo.ui.slider(1, 3, value=1, label="k")
    win = mo.ui.slider(2, 4, value=2, label="tqecd window")
    run_btn = mo.ui.run_button(label="▶ Run experiment")
    mo.vstack([
        mo.md("## 1. run\nPick a gadget and press run. This is the only stage that compiles."),
        mo.hstack([gadget, convention, kk, win, run_btn], justify="start"),
    ])
    return convention, gadget, kk, run_btn, win


@app.cell
def _(
    ExperimentConfig,
    GADGETS,
    convention,
    gadget,
    kk,
    mo,
    out_dir,
    run_btn,
    run_experiment,
    win,
):
    mo.stop(not run_btn.value, mo.md("*Press **Run experiment** above to build and score.*"))
    config = ExperimentConfig(
        conventions=(convention.value,),
        ks=(kk.value,),
        windows=(win.value,),
        manhattan_radii=(2,),
    )
    report = run_experiment([GADGETS[gadget.value]()], config, out_dir, show_progress=False)
    mo.md(f"```\n{report.to_text()}\n```")
    return (report,)


@app.cell(hide_code=True)
def _(mo, out_dir, report):
    # Show the report.html the run just wrote (rendered inline).
    _ = report  # gate on a completed run
    mo.iframe((out_dir / "report.html").read_text(encoding="utf-8"), height="560px")
    return


@app.cell(hide_code=True)
def _(mo, report):
    render_btn = mo.ui.run_button(label="▶ Re-render (UI only)")
    _ = report
    mo.vstack([
        mo.md(
            """## 2. render
            Rebuild `report.html` from `report.json` alone -- no circuits read, no annotation, no
            re-score. Use it after changing the report/visuals code."""
        ),
        mo.hstack([render_btn], justify="start"),
    ])
    return (render_btn,)


@app.cell
def _(mo, out_dir, render_btn, render_report):
    mo.stop(not render_btn.value, mo.md("*idle*"))
    _rendered = render_report(out_dir)
    mo.md(f"Rebuilt `report.html` from `report.json` — {len(_rendered.rows)} rows, unchanged scores.")
    return


@app.cell(hide_code=True)
def _(mo, report):
    new_window = mo.ui.slider(2, 5, value=3, label="new tqecd window")
    reann_btn = mo.ui.run_button(label="▶ Re-annotate + re-score")
    _ = report
    mo.vstack([
        mo.md(
            """## 3. reannotate
            Re-annotate the prepared circuits with `tqecd` and re-score -- no recompile. Sweep the
            matching window without rebuilding (or point `PYTHONPATH` at another `tqecd`)."""
        ),
        mo.hstack([new_window, reann_btn], justify="start"),
    ])
    return new_window, reann_btn


@app.cell
def _(mo, new_window, out_dir, reann_btn, reannotate_run):
    mo.stop(not reann_btn.value, mo.md("*idle*"))
    _rescored = reannotate_run(out_dir, overrides={"windows": (new_window.value,)}, show_progress=False)
    mo.md(f"```\n{_rescored.to_text()}\n```")
    return


@app.cell(hide_code=True)
def _(mo, report):
    noise = mo.ui.dropdown(["uniform_depolarizing"], value="uniform_depolarizing", label="noise model")
    sim_btn = mo.ui.run_button(label="▶ Measure LER")
    _ = report
    mo.vstack([
        mo.md(
            """## 4. simulate
            Measure LER-vs-p on the prepared circuits under a noise model -- no recompile. Two noise
            models measured this way differ only by the model, not by an accident of rebuilding."""
        ),
        mo.hstack([noise, sim_btn], justify="start"),
    ])
    return noise, sim_btn


@app.cell
def _(mo, noise, out_dir, sim_btn, simulate_run):
    mo.stop(not sim_btn.value, mo.md("*idle -- note: sampling takes a few seconds*"))
    _measured = simulate_run(
        out_dir, noise_models=(noise.value,), ps=(2e-3, 5e-3, 1e-2), show_progress=False
    )
    _plots = [r.ler_plot for r in _measured.rows if r.ler_plot]
    mo.vstack(
        [mo.md(f"Measured under **{noise.value}** — {len(_plots)} LER curve(s).")]
        + [mo.Html(f'<img src="{p}" style="max-width:100%"/>') for p in _plots]
    )
    return


if __name__ == "__main__":
    app.run()
