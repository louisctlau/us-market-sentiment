"""Basic technical analysis: SMA, RSI, MACD, drawdown from highs."""
from __future__ import annotations

import numpy as np
import pandas as pd


def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window).mean()


def rsi(close: pd.Series, window: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / window, adjust=False).mean()
    loss = -delta.clip(upper=0).ewm(alpha=1 / window, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.fillna(50.0)


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    line = ema_fast - ema_slow
    sig = line.ewm(span=signal, adjust=False).mean()
    return line, sig, line - sig


def technical_snapshot(df: pd.DataFrame) -> dict:
    """One-row technical summary for an index/ETF dataframe."""
    close = df["close"]
    last = float(close.iloc[-1])
    s50 = sma(close, 50)
    s200 = sma(close, 200)
    r = rsi(close).iloc[-1]
    m_line, m_sig, m_hist = macd(close)
    hi_52w = float(close.tail(252).max())
    return {
        "last": last,
        "sma50": float(s50.iloc[-1]) if not np.isnan(s50.iloc[-1]) else None,
        "sma200": float(s200.iloc[-1]) if not np.isnan(s200.iloc[-1]) else None,
        "above_sma50": bool(last > s50.iloc[-1]) if not np.isnan(s50.iloc[-1]) else None,
        "above_sma200": bool(last > s200.iloc[-1]) if not np.isnan(s200.iloc[-1]) else None,
        "golden_cross": bool(s50.iloc[-1] > s200.iloc[-1])
        if not (np.isnan(s50.iloc[-1]) or np.isnan(s200.iloc[-1]))
        else None,
        "rsi": float(r),
        "rsi_state": "Overbought" if r >= 70 else ("Oversold" if r <= 30 else "Neutral"),
        "macd_hist": float(m_hist.iloc[-1]),
        "macd_bullish": bool(m_hist.iloc[-1] > 0),
        "off_52w_high_pct": float(last / hi_52w - 1) * 100,
        "ret_1d": float(close.iloc[-1] / close.iloc[-2] - 1) * 100 if len(close) > 1 else None,
        "ret_1w": float(close.iloc[-1] / close.iloc[-6] - 1) * 100 if len(close) > 5 else None,
        "ret_1m": float(close.iloc[-1] / close.iloc[-22] - 1) * 100 if len(close) > 21 else None,
    }
