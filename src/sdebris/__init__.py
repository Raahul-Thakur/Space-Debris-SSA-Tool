"""sdebris — Space debris SSA tool.

A conjunction-screening engine that ingests live TLE data, propagates orbits
with SGP4, finds close approaches to a target object, estimates collision
probability, and produces structured screening reports.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
