"""Financial Modeling Prep (free tier) — revenue estimates/actuals for earnings.

The Nasdaq earnings calendar carries no revenue data, so this fills the gap.
Needs an FMP_API_KEY: set it as a Streamlit secret (Cloud: app Settings ->
Secrets), or the FMP_API_KEY env var locally. Free tier = 250 calls/day.

One /stable/earnings-calendar call covers a whole date range, so the
earnings tab costs ~1 request per refresh. Without a key, callers simply
omit the revenue columns.
"""
from __future__ import annotations

import os

import requests
import streamlit as st


def api_key() -> str | None:
    """FMP API key from Streamlit secrets, else the FMP_API_KEY env var."""
    try:
        secret = st.secrets.get("FMP_API_KEY")
    except Exception:
        secret = None
    return secret or os.environ.get("FMP_API_KEY") or None


def _num(v) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def fetch_revenues(from_ds: str, to_ds: str, key: str) -> dict[str, dict]:
    """symbol -> {'revenue_est': float|None, 'revenue_actual': float|None} (USD).

    Raises on HTTP/API errors; the caller decides how to degrade.
    """
    r = requests.get(
        "https://financialmodelingprep.com/stable/earnings-calendar",
        params={"from": from_ds, "to": to_ds, "apikey": key},
        timeout=20)
    r.raise_for_status()
    out: dict[str, dict] = {}
    for row in r.json() or []:
        sym = (row.get("symbol") or "").strip().upper()
        if not sym or sym in out:
            continue
        out[sym] = {"revenue_est": _num(row.get("revenueEstimated")),
                    "revenue_actual": _num(row.get("revenueActual"))}
    return out


def fmt_revenue(v: float | None) -> str:
    """1.5e9 -> '$1.50B'. '—' when missing."""
    if v is None:
        return "—"
    if v >= 1e9:
        return f"${v / 1e9:.2f}B"
    if v >= 1e6:
        return f"${v / 1e6:.1f}M"
    return f"${v:,.0f}"


def revenue_surprise(actual: float | None, est: float | None) -> float | None:
    """Percent beat/miss vs estimate. None when not computable."""
    if actual is None or not est:
        return None
    return (actual - est) / est * 100
