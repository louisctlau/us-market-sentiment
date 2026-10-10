"""Sahm rule recession indicator.

Sahm = 3-month average unemployment rate minus its 12-month low.
>= 0.50 percentage points -> a recession has started (Claudia Sahm's rule,
which has never fired a false positive in post-war US data).

New module (2026-10-10): previously computed inline in app.py.
"""
from __future__ import annotations

import pandas as pd

TRIGGER = 0.50


def sahm_rule(unrate: pd.Series) -> tuple[float | None, bool]:
    """(sahm value in pp, triggered?). None when there's too little data.

    unrate: monthly unemployment-rate series (e.g. FRED UNRATE "value").
    Mirrors the previous inline computation: 3-mo rolling mean vs its
    12-mo low, requiring at least 12 observations.
    """
    try:
        u3m = unrate.rolling(3).mean()
    except Exception:
        return None, False
    if u3m is None or len(u3m) < 12:
        return None, False
    try:
        low = u3m.tail(12).min()
        cur = u3m.iloc[-1]
    except Exception:
        return None, False
    if pd.isna(cur) or pd.isna(low):
        return None, False
    val = float(cur - low)
    return val, val >= TRIGGER
