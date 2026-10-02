.. _experiment_workflow:

Gadget experiment workflow
==========================

.. note::

   The gadget testbed (``python -m tools.experiment``) is a development tool, not part of the
   ``tqecd`` package. Its user interface (the command-line options and the HTML report) and its
   functionality may be revised, so treat this page as a description of the tool as it is on this
   branch rather than as a stable interface.

The ``experiment`` tool runs batched detector-annotation experiments over a set of gadgets. It is
a developer tool that lives in ``tools/experiment`` -- **outside** ``src/tqecd``, so it adds no
dependency to ``tqecd`` itself -- and it is a thin consumer of ``tqec.orchestration``: it hands
gadgets to ``prepare_batch``, re-annotates each prepared circuit with ``tqecd``, and measures how
well that annotation performs.

The tool is a **command-line program with an HTML report**: you run it in a terminal, it prints a
summary and writes ``report.html`` (plus ``report.json`` and ``report.txt``), and you open the HTML in a
browser. There is no interactive terminal UI.

The primary measures are **ground-truth-free predictors** -- absolute properties of the
re-annotated circuit (missing parities, code distance) that need no reference. When a run
configures **oracles**, those are *alternate annotators* (``tqec``'s native annotation, the
windowless main-branch ``tqecd``, or a user-supplied one) scored on the same metric and shown side
by side, so you can compare annotators directly.

Where the gadgets come from
---------------------------

The testbed does not define gadgets or compile circuits itself. Every gadget is a ``tqec`` block
graph, and ``tqec.orchestration.prepare_batch`` compiles it into one noiseless ``.stim`` circuit per
code-distance scale factor ``k``. ``tqecd`` then re-annotates that circuit. An input is one of:

* a gadget from ``tqec.gallery`` -- the names are listed by ``--list-gallery`` (``cnot``, ``cz``,
  ``memory``, ``move_rotation``, ``stability``, ``steane_encoding``, ``three_cnots``, plus ``_open``
  variants with open ports for ``cnot``, ``move_rotation``, ``steane_encoding`` and
  ``three_cnots``). ``all`` runs the seven closed forms (``cnot``, ``cz``, ``memory``,
  ``move_rotation``, ``stability``, ``steane_encoding``, ``three_cnots``);
* a **tool batch**, a family of block graphs built by ``tools/experiment/gadgets.py`` and handed to
  ``tqec``: ``hadamard_arrangements`` (one Hadamard pipe per direction ``+x``, ``-x``, ``+y``,
  ``-y``, ``+z``, ``-z``), ``spatial_junctions`` (a Z-type and an X-type three-arm junction) and
  ``y_half_cube``;
* a ``.dae`` or ``.bgraph`` file path (``--input``, repeatable). The file must exist.

``y_half_cube`` is the 16 ``.bgraph`` files bundled under ``tools/experiment/gadgets/y_half_cube/``:
``g01_gadget_1`` to ``g12_gadget_12``, ``s_gate_x``, ``s_gate_y``, ``s_gate_z`` and
``ymem_y_init_y_meas``. The files only describe the gadgets; the circuit that is annotated is whatever
the ``tqec`` installed in your environment generates for them, so the result depends on that
``tqec`` having a Y-half-cube circuit generator. The comments in the bundled configs say the
generator they were written against supports only the ``fixed_bulk`` convention and that
``fixed_boundary`` is then recorded as a prep failure; this has not been re-checked here.

A gadget that ``tqec`` cannot compile is recorded as a ``prep_fail`` row; it does not abort the run.

How it works
------------

.. code-block:: text

    inputs (BlockGraph / .dae / .bgraph)
      -> tqec.orchestration.prepare_batch   split, compile, write one noiseless .stim per k
      -> reannotate with tqecd              strip detectors, re-run annotate_detectors_automatically, reattach observables
      -> measure
           predictors  (always)   missing_parities, shortest_graphlike_error vs 2k+1
           oracles     (optional)  alternate annotators scored on the same metric, side by side
           mcmc        (opt-in)    Monte-Carlo sampling: LER-vs-p plots and Lambda factors
      -> report.{json,html,txt}

Three tiers of signal
~~~~~~~~~~~~~~~~~~~~~~~

Predictors
    Cheap, static objective functions on a single circuit, with no reference needed.
    ``missing_parities`` reduces the circuit's complete deterministic-parity space (stim flow
    generators with trivial input/output) against the emitted ``DETECTOR`` / ``OBSERVABLE``
    subspace over GF(2); a nonzero result is a parity the annotation failed to capture.
    ``shortest_graphlike_error`` is the code distance of the noisy circuit, compared to ``2k+1``.

Oracles
    Optional alternate annotators, each scored on the same metric as the experimental one
    (distance vs ``2k+1``) and additionally checked for logical (GF(2) span) equivalence to it.
    Two ship built in -- ``native`` (tqec's own annotation) and ``tqecd_main`` (the windowless
    main-branch ``tqecd``) -- and users can add their own. See :ref:`experiment_configuration`.

    The idea is that there is no single annotation that can be trusted as ground truth: an oracle
    is not assumed correct, it is another annotator whose circuit gets the same two measurements
    (missing parities, distance against ``2k+1``) as the one under test. The equivalence check
    says whether the two annotations span the same GF(2) space of detectors and observables
    (it pools the two kinds, so it does not certify that observables match observables). Reading
    the oracle columns next to the experimental ones tells you whether a failure is specific to
    the ``tqecd`` annotation or shared by the other annotators.

MCMC sampling
    An opt-in Monte-Carlo mode that runs ``tqec.orchestration.simulate_batch`` (one
    ``sinter.collect``) and attaches an LER-vs-p plot and Lambda (Lambda) suppression factor per
    gadget, shown in the report's MCMC section. Slow, so it is off by default.

Installing and running
----------------------

The tool has its own ``pyproject.toml`` under ``tools/experiment`` and is not installed as part of
``tqecd``. It needs:

* ``tqecd`` with ``annotate_detectors_automatically``. The testbed inspects its signature once: if
  it accepts ``window`` (windowed ``tqecd``), ``windows`` is swept as configured; if it does not
  (the windowless build of PR #74), ``windows`` is ignored with one logged warning, the annotator
  runs once per (gadget, convention, ``k``), and each row records ``window = -1``;
* ``tqec`` providing ``tqec.orchestration`` (``[tool.uv.sources].tqec`` in
  ``tools/experiment/pyproject.toml`` is a relative path to one developer's checkout; point it at
  yours, or put your ``tqec`` on ``PYTHONPATH``);
* ``stim`` (core), and optionally ``matplotlib`` for the LER plots (``orjson`` is used for the
  JSON if present).

Run from the command line:

.. code-block:: bash

    # one gallery gadget
    python -m tools.experiment --gallery cnot --k 1,2

    # every gadget in tqec.gallery, in one experiment
    python -m tools.experiment --gallery all --k 1,2

    # a tool batch, for example the bundled Y half cube gadgets
    python -m tools.experiment --gallery y_half_cube --k 1,2

    # from a config file
    python -m tools.experiment --config tools/experiment/configs/ler.toml

    # from a .dae / .bgraph file (substitute a real path -- the file must exist)
    python -m tools.experiment --input path/to/gadget.bgraph --k 1,2,3

    # list the available gallery gadgets
    python -m tools.experiment --list-gallery

    # rebuild report.html from an existing report.json (UI only)
    python -m tools.experiment --render out

    # re-annotate and re-score a run's on-disk circuits with tqecd (no recompile)
    python -m tools.experiment --reannotate out

    # measure an existing run under a noise model (LER plots); delete a run's output
    python -m tools.experiment --simulate out --noise-models uniform_depolarizing
    python -m tools.experiment --clean out

The process exit code is ``0`` when no row is a ``predictor_fail`` or ``annotate_fail`` and ``1``
otherwise. Rows that are ``prep_fail`` or ``not_scored`` do not change the exit code.

While a run is scoring, a ``tqdm`` progress bar labelled ``scoring rows`` advances once per
(gadget, convention, k, window) circuit as it is re-annotated with ``tqecd`` and measured. A
gadget's **score** is a pass/fail verdict: it passes when its ``tqecd`` annotation is complete (zero
missing parities) and its noisy circuit reaches the expected code distance ``2k + 1``.

Command-line options
--------------------

``python -m tools.experiment`` requires exactly one *mode* option, from this list (argparse enforces
that they are mutually exclusive):

``--config CONFIG``
    Run an experiment from a TOML file (:ref:`experiment_configuration`). With only ``--config``,
    the inputs come from the config's ``inputs``; if it has none, a ``cnot`` smoke gadget runs.
``--gallery NAME``
    Run a ``tqec.gallery`` gadget, a tool batch, or ``all`` (see ``--list-gallery``).
``--input PATH``
    Run a ``.dae`` or ``.bgraph`` file; repeat the option for several files.
``--list-gallery``
    Print the available gadget and batch names and exit (needs ``tqec`` importable).
``--render RUN_DIR``
    Rebuild ``report.html`` and ``report.txt`` from ``RUN_DIR/report.json`` only.
``--reannotate RUN_DIR``
    Re-annotate and re-score the run's prepared circuits with the current ``tqecd``.
``--simulate RUN_DIR``
    Sample the run's circuits under a noise model and add LER-vs-p plots to its report.
``--clean [RUN_DIR]``
    Delete a run directory (default ``experiment_out``). It refuses a directory that does not look
    like a run (no ``report.json``, ``logs`` or ``config.json``, and not named ``experiment_out``).

Modifiers (with ``--config``, ``--gallery`` or ``--input``, unless noted):

``--k K``
    Comma-separated code-distance scale factors, for example ``1,2,3``. Overrides the config.
``--conventions C``
    Comma-separated conventions, ``fixed_bulk`` and/or ``fixed_boundary``.
``--windows W``
    Comma-separated ``tqecd`` matching windows to sweep. Also applies to ``--reannotate``.
``--oracles NAMES``
    Comma-separated oracle names, for example ``native,tqecd_main``. Also applies to
    ``--reannotate``.
``--out DIR``
    Output directory for a new run. Default ``experiment_out``.
``--noise-models NAMES`` and ``--ps PS``
    Noise model names and physical error rates; they are read by ``--simulate`` only (for example
    ``--noise-models si1000,uniform_depolarizing --ps 1e-3,2e-3``).

With ``--reannotate``, ``--k`` and ``--conventions`` are ignored with a notice. Several of these
combinations (``--reannotate``, ``--simulate`` with the run directory options) were read from the
code, not exercised for this page.

Re-using a run without recompiling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Every run persists its full config to ``<out>/config.json``, its prepared noiseless circuits under
``<out>/prepared/``, and the authoritative ``<out>/report.json``. You can reuse that on-disk data using either of following flags, where re-rendering is cheaper than re-annotating:

``--render <out>`` rebuilds ``report.html`` (and ``report.txt``) from the existing
``report.json`` -- **UI only**. No circuits are read, no annotation runs, and no scores change; it
runs no ``tqec`` or ``tqecd`` code. Use it to refresh the HTML after the report/visuals code
changed. It needs nothing but ``report.json`` (the embedded pictures render regardless; the file
links resolve when the artifacts are still on disk).

.. code-block:: bash

    python -m tools.experiment --render out

``--reannotate <out>`` reads the prepared ``prepared/`` circuits back, re-annotates them with
``tqecd``, re-scores, and rewrites the whole report with fresh visuals -- **without recompiling any
circuit**. Use it to re-score at a different ``tqecd`` matching window, or against a different
``tqecd`` on the ``PYTHONPATH``, in a second or two rather than a full run:

.. code-block:: bash

    # same settings, re-annotated with the current tqecd
    python -m tools.experiment --reannotate out

    # re-score every prepared circuit at a different tqecd window
    python -m tools.experiment --reannotate out --windows 3

For ``--reannotate``, ``--windows`` and ``--oracles`` are re-applied; ``--k`` / ``--conventions``
are baked into the prepared circuits and are ignored with a notice (re-run the experiment to change
them). ``--reannotate`` needs the ``prepared/`` circuits on disk -- if a run was cleaned down to
just ``report.*``, ``--render`` still rebuilds the UI, but re-scoring needs a full re-run.

.. dropdown:: Minimal example (click to expand)

    The smallest useful run: one gadget, default predictors, two code distances.

    .. code-block:: python

        from tools.experiment import run_experiment, ExperimentConfig
        from tqec.gallery import cnot
        from tqec.utils.enums import Basis

        report = run_experiment([cnot(Basis.Z)], ExperimentConfig(ks=(1, 2)), "out")
        print(report.to_text())

End-to-end example
------------------

Run a CNOT across both conventions and three code distances, then read the report:

.. code-block:: python

    from tools.experiment import run_experiment, ExperimentConfig
    from tqec.gallery import cnot
    from tqec.utils.enums import Basis

    config = ExperimentConfig(
        conventions=("fixed_bulk", "fixed_boundary"),
        ks=(1, 2, 3),
        windows=(2,),
        predictors=("parities", "distance"),
    )
    report = run_experiment([cnot(Basis.Z)], config, "cnot_run")
    print(report.to_text())

``run_experiment`` writes three files into ``cnot_run/``:

* ``report.json`` -- the full structured result (one row per prepared gadget / convention / k /
  window, with the simulated observable named in the row);
* ``report.html`` -- the report described below (embedded LER plots when simulation runs);
* ``report.txt`` -- the same table as plain text.

The run directory also holds ``config.json`` and ``config.toml`` (the configuration used),
``prepared/`` (the compiled noiseless circuits and manifest), ``artifacts/`` (per-row ``.stim``
files and per-gadget 3D block-graph pages) and ``logs/`` (a timestamped log file).

Each row records ``missing_parities`` (0 means the annotation is complete), ``distance`` versus
``expected_distance`` (``2k+1``), and an overall ``predictors_pass``. A gadget that ``tqec``
cannot compile yet is recorded as a non-ready row rather than a failure.

The HTML report
~~~~~~~~~~~~~~~

``report.html`` is a single page you open in a browser (the console prints the ``open <path>``
command when a run finishes). It is generated by ``tools/experiment/report.py`` with inline CSS and
JavaScript and needs no server. It contains:

* a header with the run name, the run time and a link to ``config.toml``, and summary counts
  (rows, passed, predictor failures, prep failures, annotate failures, not scored);
* a table with one row per prepared (gadget, convention, k, observable). A **Result** badge shows
  ``pass``, ``predictor fail``, ``prep fail``, ``annotate fail`` or ``not scored``; further columns
  hold the gadget name, links to a 3D block-graph page and a ZX picture, the observable,
  convention, ``k``, window, missing parities, shortest graphlike error against the expected
  distance, runtime and links to the ``.stim`` circuits and a crumble view of the annotated one.
  Each oracle you select adds its own ``[dist | equiv | stim]`` column group;
* a filter box (by gadget id), an All / Failed / Not scored toggle, sortable column headers and a
  **Columns** menu to show or hide any column (the choice is remembered in the browser);
* an **MCMC sampling** section with a Lambda value and an LER-vs-p plot per gadget, only when
  simulation ran.

The ZX pictures and some links point at files under ``artifacts/``, so keep the run directory
together if you move the report.

To compare annotators, select oracles by name (``native`` and ``tqecd_main`` ship built in):

.. code-block:: bash

    # spatial Z/X junctions: tqecd windowing vs native vs windowless main-branch tqecd
    python -m tools.experiment --config tools/experiment/configs/spatial_junction_comparison.toml

Each oracle appears as its own column group ``[dist | equiv | stim]`` beside the experimental
distance, so you can read all three annotators on one row. That config was written to show the
windowed ``tqecd`` regressing on the spatial junctions at ``k>=2`` (its header comment says so); no
result is claimed here, since this page was written without running it. To supply your own reference, pass an oracle object to ``run_experiment`` (see
:ref:`experiment_configuration`).

See also
--------

* :ref:`experiment_configuration` -- every configuration option in detail.
