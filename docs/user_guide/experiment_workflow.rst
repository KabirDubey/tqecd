.. _experiment_workflow:

Gadget experiment workflow
==========================

The ``experiment`` tool runs batched detector-annotation experiments over a set of gadgets. It is
a developer tool that lives in ``tools/experiment`` -- **outside** ``src/tqecd``, so it adds no
dependency to ``tqecd`` itself -- and it is a thin consumer of ``tqec.orchestration``: it hands
gadgets to ``prepare_batch``, re-annotates each prepared circuit with ``tqecd``, and measures how
well that annotation performs.

There is deliberately **no ground truth** built in. For an arbitrary gadget it is often unknown
whether any annotation reaches full distance, and ``tqec``'s own native annotation is not a
reliable reference for most gadgets. The tool therefore reports *absolute* properties of the
re-annotated circuit, and only compares against a reference where a user explicitly supplies one.

How it works
------------

.. code-block:: text

    inputs (BlockGraph / .dae / .bgraph)
      -> tqec.orchestration.prepare_batch   split, compile, write one noiseless .stim per k
      -> reannotate with tqecd              strip detectors, re-run annotate_detectors_automatically, reattach observables
      -> measure
           predictors  (always)   missing_parities, shortest_graphlike_error vs 2k+1
           oracles     (optional)  compare to a user-supplied reference, up to logical symmetry
           simulation  (opt-in)    LER-vs-p plots and Lambda factors
      -> report.{json,html,txt,csv}

Three tiers of signal
~~~~~~~~~~~~~~~~~~~~~~~

Predictors
    Cheap, static objective functions on a single circuit, with no reference needed.
    ``missing_parities`` reduces the circuit's complete deterministic-parity space (stim flow
    generators with trivial input/output) against the emitted ``DETECTOR`` / ``OBSERVABLE``
    subspace over GF(2); a nonzero result is a parity the annotation failed to capture.
    ``shortest_graphlike_error`` is the code distance of the noisy circuit, compared to ``2k+1``.

Oracles
    Optional, user-supplied known-correct references, compared up to logical (GF(2) span)
    symmetry rather than byte-equality. Ground truth is opt-in and often absent. See
    :ref:`experiment_configuration`.

Simulation
    An opt-in gold-standard mode that runs ``tqec.orchestration.simulate_batch`` and attaches an
    LER-vs-p plot and Lambda (Lambda) suppression factor per gadget. Slow, so it is off by default.

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
    python -m tools.experiment --config tools/experiment/configs/manhattan_sensitivity.toml

    # from a .dae / .bgraph file
    python -m tools.experiment --input my_gadget.dae --k 1,2,3

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
``<out>/mr<radius>/``, and the authoritative ``<out>/report.json``. You can reuse that on-disk data using either of following flags, where re-rendering is cheaper than re-annotating:

``--render <out>`` rebuilds ``report.html`` (and ``report.txt`` / ``report.csv``) from the existing
``report.json`` -- **UI only**. No circuits are read, no annotation runs, and no scores change; it
runs no ``tqec`` or ``tqecd`` code. Use it to refresh the HTML after the report/visuals code
changed. It needs nothing but ``report.json`` (the embedded pictures render regardless; the file
links resolve when the artifacts are still on disk).

.. code-block:: bash

    python -m tools.experiment --render out

``--reannotate <out>`` reads the prepared ``mr<radius>/`` circuits back, re-annotates them with
``tqecd``, re-scores, and rewrites the whole report with fresh visuals -- **without recompiling any
circuit**. Use it to re-score at a different ``tqecd`` matching window, or against a different
``tqecd`` on the ``PYTHONPATH``, in a second or two rather than a full run:

.. code-block:: bash

    # same settings, re-annotated with the current tqecd
    python -m tools.experiment --reannotate out

    # re-score every prepared circuit at a different tqecd window
    python -m tools.experiment --reannotate out --windows 3

For ``--reannotate``, ``--windows`` and ``--oracles`` are re-applied; ``--k`` / ``--conventions`` /
``--manhattan-radii`` are baked into the prepared circuits and are ignored with a notice (re-run the
experiment to change them). ``--reannotate`` needs the ``mr<radius>/`` circuits on disk -- if a run
was cleaned down to just ``report.*``, ``--render`` still rebuilds the UI, but re-scoring needs a
full re-run.

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

* ``report.json`` -- the full structured result (one row per gadget / convention / k / radius / window);
* ``report.html`` -- a self-contained, sortable table (embedded LER plots when simulation runs);
* ``report.txt`` -- the same table as plain text.

Each row records ``missing_parities`` (0 means the annotation is complete), ``distance`` versus
``expected_distance`` (``2k+1``), and an overall ``predictors_pass``. A gadget that ``tqec``
cannot compile yet is recorded as a non-ready row rather than a failure.

To add a reference comparison, pass an oracle (see :ref:`experiment_configuration`):

.. code-block:: python

    from tools.experiment.oracle import CallableOracle

    # only meaningful where you know the reference is correct for this gadget
    reference = CallableOracle(
        "my_reference",
        emit=lambda unit, k, native: native,
        applies_to=lambda unit, config: unit.convention == "fixed_bulk",
    )
    report = run_experiment([cnot(Basis.Z)], config, "cnot_run", oracles=[reference])

See also
--------

* :ref:`experiment_configuration` -- every configuration option in detail.
