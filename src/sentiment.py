"""Composite market-sentiment scoring. Every sub-score is 0-100 (100 = most bullish)."""
from __future__ import annotations

import numpy as np

from .data import DEFENSIVE_SECTORS, OFFENSIVE_SECTORS, pct_change
from .technicals import rsi, sma


def _clip(x: float) -> float:
    return float(max(0.0, min(100.0, x)))


def trend_score(snapshots: dict[str, dict]) -> tuple[float, str]:
    flags = [s["above_sma50"] for s in snapshots.values() if s["above_sma50"] is not None]
    if not flags:
        return 50.0, "no SMA50 data"
    share = sum(flags) / len(flags)
    label = f"{sum(flags)}/{len(flags)} indices above 50-day average"
    return _clip(share * 100), label


def momentum_score(snapshots: dict[str, dict]) -> tuple[float, str]:
    rsis = [s["rsi"] for s in snapshots.values()]
    avg = float(np.mean(rsis))
    # RSI 30 -> 0, 50 -> 50, 70 -> 100
    score = _clip((avg - 30) / 40 * 100)
    return score, f"avg RSI(14) {avg:.1f}"


def volatility_score(vix_df) -> tuple[float, str]:
    last = float(vix_df["close"].iloc[-1])
    # VIX 12 -> 100, 40 -> 0, linear in between
    score = _clip((40 - last) / (40 - 12) * 100)
    spike = pct_change(vix_df, 5)
    detail = f"VIX {last:.1f}"
    if spike is not None and spike > 20:
        score = _clip(score - 15)
        detail += f" (+{spike:.0f}% in 5d — spike penalty)"
    return score, detail


def macro_score(dxy_df, y10_df, y5_df) -> tuple[float, str]:
    parts, notes = [], []
    # USD: falling dollar = risk-on
    dxy = dxy_df["close"]
    d50 = sma(dxy, 50).iloc[-1]
    if not np.isnan(d50):
        below = bool(dxy.iloc[-1] < d50)
        parts.append(75.0 if below else 35.0)
        notes.append("DXY below 50d avg" if below else "DXY above 50d avg")
    # Yield curve (10Y-5Y segment): positive slope = healthier backdrop
    spread = float(y10_df["close"].iloc[-1] - y5_df["close"].iloc[-1])
    if spread >= 0.5:
        parts.append(80.0)
    elif spread >= 0:
        parts.append(60.0)
    elif spread >= -0.5:
        parts.append(35.0)
    else:
        parts.append(15.0)
    notes.append(f"10Y-5Y spread {spread:+.2f}pp")
    score = _clip(float(np.mean(parts))) if parts else 50.0
    return score, "; ".join(notes)


def sector_score(sector_data: dict[str, object]) -> tuple[float, str]:
    off, dfn = [], []
    for name, df in sector_data.items():
        r = pct_change(df, 21)
        if r is None:
            continue
        (off if name in OFFENSIVE_SECTORS else dfn if name in DEFENSIVE_SECTORS else off).append(r)
    if not off or not dfn:
        return 50.0, "insufficient sector data"
    spread = float(np.mean(off) - np.mean(dfn))
    # +/-6pp monthly spread maps to 0/100
    score = _clip(50 + spread / 6 * 50)
    tilt = "offensive" if spread > 0 else "defensive"
    return score, f"{tilt} tilt ({spread:+.1f}pp 1M)"


def regime(score: float) -> str:
    if score >= 70:
        return "Risk-On"
    if score >= 45:
        return "Neutral"
    if score >= 25:
        return "Risk-Off"
    return "Extreme Fear"


WEIGHTS = {"Trend": 0.25, "Momentum": 0.20, "Volatility": 0.20, "Macro": 0.15, "Sectors": 0.20}


def composite(components: dict[str, tuple[float, str]]) -> tuple[float, dict]:
    total = sum(score * WEIGHTS[name] for name, (score, _) in components.items())
    return _clip(total), {n: {"score": s, "detail": d} for n, (s, d) in components.items()}
