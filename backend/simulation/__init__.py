"""
Tetris Simulation Layer
=======================

Deterministic pre-launch verification and simulation engine for generated web applications.
"""

from simulation.engine import (
    SimulationEngine,
    SimulationCheck,
    run_simulation,
)

__all__ = [
    "SimulationEngine",
    "SimulationCheck",
    "run_simulation",
]
