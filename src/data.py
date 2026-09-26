"""Market data fetching via yfinance (free, no API key)."""
from __future__ import annotations

import pandas as pd
import yfinance as yf

INDICES = {
    "S&P 500": "^GSPC",
    "Nasdaq 100": "^NDX",
    "Nasdaq Composite": "^IXIC",
    "Russell 2000": "^RUT",
}
VOL_MACRO = {
    "VIX": "^VIX",
    "DXY (USD Index)": "DX-Y.NYB",
    "US 10Y Yield": "^TNX",
    "US 5Y Yield": "^FVX",  # 5-year Treasury yield (^FVX); no free Yahoo 2Y series
}
SECTORS = {
    "Technology": "XLK",
    "Health Care": "XLV",
    "Financials": "XLF",
    "Energy": "XLE",
    "Industrials": "XLI",
    "Cons. Staples": "XLP",
    "Cons. Disc.": "XLY",
    "Utilities": "XLU",
    "Materials": "XLB",
    "Real Estate": "XLRE",
    "Communication": "XLC",
}
OFFENSIVE_SECTORS = {"Technology", "Cons. Disc.", "Communication", "Industrials", "Financials",
                     # Cyclical leaners, classified explicitly (never silently defaulted):
                     "Energy", "Materials"}
DEFENSIVE_SECTORS = {"Cons. Staples", "Utilities", "Health Care", "Real Estate"}

# Cross-asset context (free Yahoo futures/ETF series)
CROSS_ASSETS = {
    "WTI Crude Oil": "CL=F",
    "Gold": "GC=F",
    "20Y+ Treasury (TLT)": "TLT",
}
GROWTH_SECTORS = {"Technology", "Cons. Disc."}
HAVEN_SECTORS = {"Utilities", "Cons. Staples"}


def fetch_history(ticker: str, period: str = "1y") -> pd.DataFrame:
    """Daily OHLCV with a flat DatetimeIndex and lowercase columns.

    Never raises: on any failure (network, parse, unexpected schema) returns
    an empty DataFrame. Callers must tolerate empties — see load_data() in
    app.py and the guards in sentiment.py.
    """
    try:
        df = yf.download(ticker, period=period, progress=False, auto_adjust=True)
        if df.empty:
            return df
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.columns = [str(c).lower() for c in df.columns]
        df.index = pd.to_datetime(df.index).tz_localize(None)
        return df[["open", "high", "low", "close", "volume"]].dropna()
    except Exception:
        return pd.DataFrame()


def fetch_all(tickers: dict[str, str], period: str = "1y") -> dict[str, pd.DataFrame]:
    """Per-ticker fault isolation: one bad ticker can't kill the dashboard."""
    out: dict[str, pd.DataFrame] = {}
    for name, t in tickers.items():
        try:
            out[name] = fetch_history(t, period)
        except Exception:  # belt-and-braces; fetch_history already swallows
            out[name] = pd.DataFrame()
    return out


def pct_change(df: pd.DataFrame, days: int) -> float | None:
    if len(df) <= days:
        return None
    return float(df["close"].iloc[-1] / df["close"].iloc[-1 - days] - 1) * 100
