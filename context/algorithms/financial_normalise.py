"""Financial unit normalisation for opportunity Silver layer.

Bronze ``Oppo_Forecast`` and ``Oppo_Cost`` arrive in absolute euros.
Silver canonical form is k€ — both forecast and cost are divided by 1000
so that downstream computed columns (``cc_net``, ``cc_net_weighted``)
and the Gold projections are unit-consistent.

The single helper ``to_keuros`` is the source of truth for that
conversion. Centralising it here means any future scale change touches
exactly one line, and silver_normalise.py / render.py / dbt models do
not each carry their own ``/ 1000.0`` literal.

Usage
-----
>>> from context.algorithms.financial_normalise import to_keuros
>>> to_keuros(125_000.0)
125.0
>>> to_keuros(None) is None
True
"""
from __future__ import annotations

from typing import Optional

import numbers


def to_keuros(value: Optional[float]) -> Optional[float]:
    """Convert an absolute-EUR amount to k€ (thousands of euros).

    NULL-safe: ``None`` passes through. Non-numeric inputs (e.g. NaN
    from pandas) also pass through as ``None`` so downstream arithmetic
    does not silently propagate junk.
    """
    if value is None:
        return None
    if not isinstance(value, numbers.Real):
        return None
    if value != value:  # NaN check without importing math
        return None
    return float(value) / 1000.0
