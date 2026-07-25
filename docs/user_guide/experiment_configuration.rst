.. _experiment_configuration:

Experiment configuration
========================

An experiment is driven by an ``ExperimentConfig``. Build it in Python, or load it from a TOML
file with ``ExperimentConfig.from_toml``. Every option has a sensible default, so an empty config
is a valid (CNOT smoke) run.

Experiment options
------------------

``conventions``
    Compilation conventions to build each gadget under. Available: ``"fixed_bulk"`` and
    ``"fixed_boundary"``. Default ``("fixed_bulk",)``.

``ks``
    Code-distance scale factors. Each gadget is generated once per ``k``; the circuit grows with
    ``k``. Default ``(1, 2, 3)``.

``windows``
    ``tqecd`` matching-window widths to sweep -- the ``tqecd`` knob under test, forwarded to
    ``annotate_detectors_automatically(window=...)``. Default ``(2,)``.

``manhattan_radii``
    ``tqec`` ``manhattan_radius`` values to sweep. The radius sizes the subtemplate window (side
    ``2*r+1``) that ``tqec``'s native annotation searches; the tool runs one ``prepare_batch`` per
    radius. Default ``(2,)``.

``logical_observables``
    How ``prepare_batch`` selects logical observables and fills open ports: ``"all"``,
    ``"all_possible"``, ``"area_minimized"`` or ``"random"``. Default ``"all"``.

``predictors``
    Which static predictors to run: ``"parities"`` (missing-parity completeness) and/or
    ``"distance"`` (shortest graphlike error vs ``2k+1``). Default ``("parities", "distance")``.

``oracles``
    Names of registered reference oracles to apply (see `Oracles`_). Empty by default -- there is
    no ground truth unless you supply one.

``noise_models``
    Noise model(s) for the ``distance`` predictor (the first is used): ``"uniform_depolarizing"``
    or ``"si1000"``. Default ``("uniform_depolarizing",)``.

``ps``
    Physical error rate(s) for the ``distance`` predictor (the first is used). Default ``(1e-3,)``.

``expected_distance``
    Expression for the expected distance, evaluated with ``k`` in scope. Default ``"2*k + 1"``.

``circuit_mode``
    How ``prepare_batch`` writes circuits: ``"materialized"`` or ``"streaming"``. Default
    ``"materialized"``.

``simulation``
    A ``SimulationConfig`` (below) for the optional gold-standard LER mode.

Simulation options
-----------------

Set under ``[experiment.simulation]`` in TOML, or via ``SimulationConfig``. Off by default.

``enabled``
    Turn the gold-standard LER mode on. Default ``false``.

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
---------------

.. code-block:: toml

    [experiment]
    conventions = ["fixed_bulk", "fixed_boundary"]
    ks = [1, 2, 3]
    windows = [2]
    manhattan_radii = [1, 2, 3]
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

Oracles are **optional** and never enabled by default: ``tqec``'s native annotation is not a
reliable ground truth for most gadgets, so no oracle ships pre-registered. Supply your own only
where you have a known-correct reference that shares the gadget's macroscopic (logical) behavior.
Comparison is by logical equivalence -- the two annotations' ``DETECTOR`` / ``OBSERVABLE`` parity
subspaces must span the same space over GF(2) -- not byte-equality.

Two kinds are provided:

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
