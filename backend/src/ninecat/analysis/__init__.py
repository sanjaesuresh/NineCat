"""Offline analysis over already-persisted NineCat data (backtests, reports).

Distinct from sync/ (which talks to Yahoo and writes rows) and engine/ (which
is pure math with no DB access): this package sits above both, driving the
engine with real historical inputs to answer "how good is the projection,
really" -- see analysis/backtest.py.
"""
