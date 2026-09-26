"""FRED API client (api.stlouisfed.org/fred).

Needs a free API key: https://fred.stlouisfed.org/docs/api/api_key.html
Set it as the `FRED_API_KEY` Streamlit secret, or the FRED_API_KEY
environment variable for local runs.
"""
from __future__ import annotations

import os

import pandas as pd
import requests
import streamlit as st

BASE_URL = "https://api.stlouisfed.org/fred"
TIMEOUT = 25


class FredError(RuntimeError):
    """FRED API returned an error (bad key, unknown series, rate limit...)."""


class FredNoKey(RuntimeError):
    """No FRED API key configured."""


def api_key() -> str | None:
    """FRED API key from Streamlit secrets, else the FRED_API_KEY env var."""
    try:
        secret = st.secrets.get("FRED_API_KEY")
    except Exception:
        secret = None
    return secret or os.environ.get("FRED_API_KEY") or None


def _get(endpoint: str, params: dict) -> dict:
    key = api_key()
    if not key:
        raise FredNoKey(
            "No FRED API key found. Add FRED_API_KEY to Streamlit secrets "
            "(or set the FRED_API_KEY env var)."
        )
    params = {"api_key": key, "file_type": "json", **params}
    try:
        r = requests.get(f"{BASE_URL}/{endpoint}", params=params, timeout=TIMEOUT)
    except requests.RequestException as e:
        raise FredError(f"FRED request failed: {e}") from e
    try:
        payload = r.json()
    except ValueError:
        raise FredError(f"FRED returned non-JSON (HTTP {r.status_code}).") from None
    if r.status_code != 200 or "error_message" in payload:
        raise FredError(payload.get("error_message", f"HTTP {r.status_code}"))
    return payload


def get_series(
    series_id: str,
    observation_start: str | None = None,
    frequency: str | None = None,
    aggregation_method: str | None = None,
    units: str | None = None,
) -> pd.DataFrame:
    """Observations as a DataFrame with a DatetimeIndex and float `value` col.

    FRED marks missing values as "." — they become NaN and are dropped.
    """
    params: dict = {"series_id": series_id, "sort_order": "asc"}
    if observation_start:
        params["observation_start"] = observation_start
    if frequency:
        params["frequency"] = frequency
    if aggregation_method:
        params["aggregation_method"] = aggregation_method
    if units:
        params["units"] = units
    payload = _get("series/observations", params)
    obs = payload.get("observations", [])
    if not obs:
        raise FredError(f"FRED returned no observations for '{series_id}'.")
    df = pd.DataFrame(obs)[["date", "value"]]
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = pd.to_numeric(
        df["value"].replace(".", pd.NA), errors="coerce"
    )
    return df.set_index("date").dropna(subset=["value"]).sort_index()


# Series used by the Economy tab: id -> (label, transform for headline value)
ECON_SERIES = {
    "FEDFUNDS": "Fed funds rate",
    "UNRATE": "Unemployment rate",
    "CPIAUCSL": "CPI (YoY %)",
    "PCEPI": "PCE price index (YoY %)",
    "ICSA": "Initial jobless claims (4-wk avg)",
    "PAYEMS": "Nonfarm payrolls (monthly chg, k)",
    "GDP": "Real GDP (QoQ ann. %)",
    "DGS2": "2Y Treasury yield",
    "DGS10": "10Y Treasury yield",
}


# US Treasury par yield curve: maturity label -> (FRED series id, years)
YIELD_CURVE_SERIES = {
    "1M": ("DGS1MO", 1 / 12),
    "3M": ("DGS3MO", 3 / 12),
    "6M": ("DGS6MO", 6 / 12),
    "1Y": ("DGS1", 1.0),
    "2Y": ("DGS2", 2.0),
    "3Y": ("DGS3", 3.0),
    "5Y": ("DGS5", 5.0),
    "7Y": ("DGS7", 7.0),
    "10Y": ("DGS10", 10.0),
    "20Y": ("DGS20", 20.0),
    "30Y": ("DGS30", 30.0),
}


def headline_value(series_id: str, df: pd.DataFrame) -> tuple[float, str] | tuple[None, str]:
    """Latest headline number and its as-of date for the Economy tab."""
    if df.empty:
        return None, "n/a"
    asof = df.index[-1].strftime("%b %d, %Y")
    v = df["value"]
    if series_id in ("CPIAUCSL", "PCEPI"):
        val = v.pct_change(12).iloc[-1] * 100 if len(v) > 12 else None
    elif series_id == "ICSA":
        val = v.tail(4).mean()
    elif series_id == "PAYEMS":
        val = v.diff().iloc[-1]
    elif series_id == "GDP":
        val = ((v / v.shift(1)) ** 4 - 1).iloc[-1] * 100 if len(v) > 1 else None
    else:
        val = v.iloc[-1]
    return (None if val is None or pd.isna(val) else float(val)), asof
