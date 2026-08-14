"""Shared population-z helper used across the value/ modules.

Extracted (slop cleanup) from three near-identical private copies in
value/ninecat.py, value/playoffs.py, and value/composite.py -- same
population-std / zero-variance-is-0.0 convention as ninecat.engine.zscores,
but standardizing this pipeline's own derived composites rather than a raw
fantasy category, so it lives here instead of reaching into the engine.
"""

from __future__ import annotations


def population_zscores(values: list[float]) -> list[float]:
    """Standardize a list to population mean 0 / std 1; zero variance -> all 0.0."""
    n = len(values)
    if n == 0:
        return []
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / n
    std = variance**0.5
    if std == 0:
        return [0.0] * n
    return [(v - mean) / std for v in values]
