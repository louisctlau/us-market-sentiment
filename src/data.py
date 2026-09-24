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
    "VIX3M": "^VIX3M",
    "DXY (USD Index)": "DX-Y.NYB",
    "US 10Y Yield": "^TNX",
    "US 2Y Yield": "^FVX",
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
OFFENSIVE_SECTORS = {"Technology", "Cons. Disc.", "Communication", "Industrials", "Financials"}
DEFENSIVE_SECTORS = {"Cons. Staples", "Utilities", "Health Care", "Real Estate"}


def fetch_history(ticker: str, period: str = "1y") -> pd.DataFrame:
    """Daily OHLCV with a flat DatetimeIndex and lowercase columns."""
    df = yf.download(ticker, period=period, progress=False, auto_adjust=True)
    if df.empty:
        return df
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [str(c).lower() for c in df.columns]
    df.index = pd.to_datetime(df.index).tz_localize(None)
    return df[["open", "high", "low", "close", "volume"]].dropna()


def fetch_all(tickers: dict[str, str], period: str = "1y") -> dict[str, pd.DataFrame]:
    return {name: fetch_history(t, period) for name, t in tickers.items()}


def latest_close(df: pd.DataFrame) -> float:
    return float(df["close"].iloc[-1])


def pct_change(df: pd.DataFrame, days: int) -> float | None:
    if len(df) <= days:
        return None
    return float(df["close"].iloc[-1] / df["close"].iloc[-1 - days] - 1) * 100
