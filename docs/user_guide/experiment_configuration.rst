.. _experiment_configuration:

Experiment configuration
========================

.. note::

   The gadget testbed is a development tool and its options may be revised. The inputs named in
   ``inputs`` are described in :ref:`experiment_workflow`.

An experiment is driven by an ``ExperimentConfig``. Build it in Python, or load it from a TOML
file with ``ExperimentConfig.from_toml``. Every option has a sensible default, so an empty config
is a valid (CNOT smoke) run.

Experiment options
------------------

``name``
    An optional label for the experiment, shown at the top of the report. Default ``""``.

``inputs``
    The gadgets this run scores, so a config fully defines its own experiment (no CLI ``--gallery``
    needed). Each entry is a ``tqec.gallery`` name (``"cnot"``, ...), ``"all"``, a tool-provided
    batch (``"hadamard_arrangements"``, ``"spatial_junctions"``, ``"y_half_cube"``), or a ``.dae`` / ``.bgraph`` path.
    Default ``()`` (the CLI supplies the inputs instead).

``conventions``
    Compilation conventions to build each gadget under. Available: ``"fixed_bulk"`` and
    ``"fixed_boundary"``. Default ``("fixed_bulk",)``.

``ks``
    Code-distance scale factors. Each gadget is generated once per ``k``; the circuit grows with
    ``k``. Default ``(1, 2, 3)``.

``windows``
    ``tqecd`` matching-window widths to sweep -- the ``tqecd`` knob under test, forwarded to
    ``annotate_detectors_automatically(window=...)``. Default ``(2,)``.

``logical_observables``
    How ``prepare_batch`` selects logical observables and fills open ports: ``"all"``,
    ``"all_possible"``, ``"area_minimized"`` or ``"random"``. Default ``"all"``.

``predictors``
    Which static predictors to run: ``"parities"`` (missing-parity completeness) and/or
    ``"distance"`` (shortest graphlike error vs ``2k+1``). Default ``("parities", "distance")``.

``oracles``
    Names of oracle *alternate annotators* to score side by side (see `Oracles`_). Two are built
    in: ``"native"`` (tqec's own annotation) and ``"tqecd_main"`` (the windowless main-branch
    ``tqecd``). Default ``()`` -- just the experimental annotator.

``noise_models``
    The noise **model** the ``distance`` predictor applies before its (analytic) minimum-weight
    search -- only ``noise_models[0]`` is used. The distance depends on the model (which error
    mechanisms exist and whether the detector error model is graphlike), so this choice matters.
    ``"uniform_depolarizing"`` or ``"si1000"``. Default ``("uniform_depolarizing",)``.

``ps``
    The physical error rate the ``distance`` predictor applies (only ``ps[0]`` is used) to
    instantiate the error mechanisms. It is **not a sampling parameter**: ``shortest_graphlike_error``
    is an analytic search whose result (the minimum error *count*) is independent of the ``p``
    value -- any ``p`` in ``(0, 1)`` gives the same distance. The ``ps`` sweep that MCMC actually
    *samples* over lives under ``[experiment.simulation]``. Default ``(1e-3,)``.

``expected_distance``
    Expression for the expected distance, evaluated with ``k`` in scope. Default ``"2*k + 1"``.

``circuit_mode``
    How ``prepare_batch`` writes circuits: ``"materialized"`` or ``"streaming"``. Default
    ``"materialized"``.

``simulation``
    A ``SimulationConfig`` (below) for the optional MCMC sampling stage.

Simulation options
------------------

Set under ``[experiment.simulation]`` in TOML, or via ``SimulationConfig``. Off by default.

``enabled``
    Turn MCMC sampling on. Default ``false``.

``noise_models`` / ``ps``
    Noise model(s) and physical error rate sweep for sampling. When simulation is enabled these
    drive ``prepare_batch`` / ``simulate_batch`` instead of the predictor ``noise_models`` /
    ``ps``. Defaults ``("uniform_depolarizing",)`` and ``(1e-3, 2e-3, 5e-3, 1e-2)``.

``max_shots`` / ``max_errors``
    ``sinter.collect`` stopping conditions. Defaults ``10000`` and ``None``.

``decoders``
    Decoders to run. Default ``("pymatching",)``.

``plot``
    Embed a per-gadget LER-vs-p plot (base64 PNG) into ``report.html``. Default ``false``.

``lambda_factor``
    Compute the Lambda suppression factor per gadget. Default ``false``.

TOML file format
----------------

.. code-block:: toml

    [experiment]
    conventions = ["fixed_bulk", "fixed_boundary"]
    ks = [1, 2, 3]
    windows = [2]
    predictors = ["parities", "distance"]

    [experiment.simulation]
    enabled = true
    ps = [0.001, 0.002, 0.004, 0.008]
    max_shots = 20000
    plot = true
    lambda_factor = true

Load and run it:

.. code-block:: python

    from tools.experiment import run_experiment, ExperimentConfig
    from tqec.gallery import cnot
    from tqec.utils.enums import Basis

    config = ExperimentConfig.from_toml("my_config.toml")
    run_experiment([cnot(Basis.Z)], config, "out")

Oracles
-------

The experimental subject is always ``tqecd``'s windowed ``annotate_detectors_automatically``. An
**oracle is an alternate annotator**: it produces its own annotation of the same gadget, which is
scored on the *same* metric (distance vs ``2k+1``, missing parities), checked for logical
equivalence to the experimental one (their ``DETECTOR`` / ``OBSERVABLE`` parity subspaces span the
same GF(2) space), and gets its ``.stim`` written for a report link. Each oracle appears as its own
column group ``[dist | equiv | stim]``. Oracles are opt-in; none run unless selected.

Two ship built in:

* ``native`` -- ``tqec``'s own native annotation (the circuit ``prepare_batch`` wrote), every
  convention.
* ``tqecd_main`` -- the main-branch ``tqecd`` ``annotate_detectors_automatically``,
  run out-of-process; it isolates the effect of your change to ``tqecd``. It needs the
  main-branch source: a worktree at ``.tqecd-main`` in the directory that contains this repository checkout
  (see ``DEFAULT_MAIN_SRC`` in ``tools/experiment/annotators.py``) or the ``TQECD_MAIN_SRC`` environment
  variable. When selected but missing, it is not skipped: the row records the error in that
  oracle's cell.

.. code-block:: bash

    # spatial Z/X junctions: tqecd windowing vs native vs windowless main-branch tqecd
    python -m tools.experiment --config tools/experiment/configs/spatial_junction_comparison.toml

This config is meant to isolate whether windowing regresses the spatial junctions at ``k>=2`` (its
header comment states that it does); the outcome was not re-run for this page.

For your own reference, two kinds are provided:

``CircuitOracle(name, reference_circuit, applies_to=...)``
    A fixed annotated ``stim.Circuit`` used as the reference wherever it applies.

``CallableOracle(name, emit, applies_to=...)``
    A callable ``emit(unit, k, native) -> stim.Circuit`` that produces the reference per unit --
    e.g. a differently-built circuit with the same macroscopic behavior, or one loaded from disk.

Pass oracle objects straight to ``run_experiment``:

.. code-block:: python

    from tools.experiment.oracle import CircuitOracle

    oracle = CircuitOracle(
        "my_reference",
        reference_circuit,
        applies_to=lambda unit, config: unit.convention == "fixed_bulk",
    )
    run_experiment(inputs, config, "out", oracles=[oracle])

or register them by name so a config's ``oracles`` list can select them:

.. code-block:: python

    from tools.experiment.oracle import register_oracle

    register_oracle(oracle)   # then set oracles = ["my_reference"] in the config
