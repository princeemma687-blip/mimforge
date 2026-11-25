"""Pendulum proof-of-pipeline experiment (synthetic data only).

This package lives OUTSIDE ``src/mimforge`` on purpose: it is allowed to
be pendulum-specific. It proves the product pipeline end to end on
synthetic data --

    generated demonstration video -> centroid extraction -> readings
    table -> slope -> recovered constant, in parallel with a physics
    simulation pushed through the identical table path --

and wires the results through the generic core schema
(``mimforge.models``: Demonstration, ObservationSpec, VerificationRun).
See README.md in this directory for scope and honesty labels.
"""
