.. _experiment_workflow:

Gadget experiment workflow
==========================

The ``experiment`` tool runs batched detector-annotation experiments over a set of gadgets. It is
a developer tool that lives in ``tools/experiment`` -- **outside** ``src/tqecd``, so it adds no
dependency to ``tqecd`` itself -- and it is a thin consumer of ``tqec.orchestration``: it hands
gadgets to ``prepare_batch``, re-annotates each prepared circuit with ``tqecd``, and measures how
well that annotation performs.

The primary measures are **ground-truth-free predictors** -- absolute properties of the
re-annotated circuit (missing parities, code distance) that need no reference. When a run
configures **oracles**, those are *alternate annotators* (``tqec``'s native annotation, the
windowless main-branch ``tqecd``, or a user-supplied one) scored on the same metric and shown side
by side, so you can compare annotators directly.

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

MCMC sampling
    An opt-in Monte-Carlo mode that runs ``tqec.orchestration.simulate_batch`` (one
    ``sinter.collect``) and attaches an LER-vs-p plot and Lambda (Lambda) suppression factor per
    gadget, shown in the report's MCMC section. Slow, so it is off by default.

Installing and running
----------------------

The tool has its own ``pyproject.toml`` under ``tools/experiment`` and is not installed as part of
``tqecd``. It needs:

* ``tqecd`` with windowed detector completion (the ``window=`` argument);
* ``tqec`` providing ``tqec.orchestration`` (point ``[tool.uv.sources].tqec`` at your tqec
  checkout);
* ``stim`` (core), and optionally ``matplotlib`` for the LER plots (``orjson`` is used for the
  JSON if present).

Run from the command line:

.. code-block:: bash

    # one gallery gadget
    python -m tools.experiment --gallery cnot --k 1,2

    # every gadget in tqec.gallery, in one experiment
    python -m tools.experiment --gallery all --k 1,2

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

While a run is scoring, a ``tqdm`` progress bar labelled ``scoring rows`` advances once per
(gadget, convention, k, window) circuit as it is re-annotated with ``tqecd`` and measured. A
gadget's **score** is a pass/fail verdict: it passes when its ``tqecd`` annotation is complete (zero
missing parities) and its noisy circuit reaches the expected code distance ``2k + 1``.

Re-using a run without recompiling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Every run persists its full config to ``<out>/config.json``, its prepared noiseless circuits under
``<out>/prepared/``, and the authoritative ``<out>/report.json``. You can reuse that on-disk data using either of following flags, where re-rendering is cheaper than re-annotating:

``--render <out>`` rebuilds ``report.html`` (and ``report.txt`` / ``report.csv``) from the existing
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

``run_experiment`` writes four files into ``cnot_run/``:

* ``report.json`` -- the full structured result (one row per gadget / convention / k / window);
* ``report.html`` -- a self-contained, sortable table (embedded LER plots when simulation runs);
* ``report.txt`` -- the same table as plain text.

Each row records ``missing_parities`` (0 means the annotation is complete), ``distance`` versus
``expected_distance`` (``2k+1``), and an overall ``predictors_pass``. A gadget that ``tqec``
cannot compile yet is recorded as a non-ready row rather than a failure.

To compare annotators, select oracles by name (``native`` and ``tqecd_main`` ship built in):

.. code-block:: bash

    # spatial Z/X junctions: tqecd windowing vs native vs windowless main-branch tqecd
    python -m tools.experiment --config tools/experiment/configs/spatial_junction_comparison.toml

Each oracle appears as its own column group ``[dist | equiv | stim]`` beside the experimental
distance, so you can read all three annotators on one row. On the spatial junctions this shows the
windowed ``tqecd`` failing at ``k=2`` (distance ``-``) while ``native`` and ``tqecd_main`` both
reach ``2k+1``. To supply your own reference, pass an oracle object to ``run_experiment`` (see
:ref:`experiment_configuration`).

See also
--------

* :ref:`experiment_configuration` -- every configuration option in detail.
