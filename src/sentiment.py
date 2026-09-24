"""Composite market-sentiment scoring. Every sub-score is 0-100 (100 = most bullish)."""
from __future__ import annotations

import numpy as np

from .data import DEFENSIVE_SECTORS, GROWTH_SECTORS, HAVEN_SECTORS, OFFENSIVE_SECTORS, pct_change
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


def fear_context(vix_df, spx_df) -> tuple[float, str]:
    """VIX/SPX-driven fear, 0 = calm … 100 = panic. Market volatility, not news."""
    vix = vix_df["close"]
    last = float(vix.iloc[-1])
    # Level: VIX 12 -> 0, 40 -> 100
    level = _clip((last - 12) / (40 - 12) * 100)
    # Spike: +50% in 20d -> 100
    spike = _clip(max(0.0, float(vix.iloc[-1] / vix.iloc[-21] - 1)) / 0.5 * 100) if len(vix) > 21 else 0.0
    # SPX drawdown from 20d high: -10% -> 100
    hi = float(spx_df["close"].iloc[-21:].max()) if len(spx_df) > 21 else float(spx_df["close"].iloc[-1])
    dd = _clip(max(0.0, 1 - float(spx_df["close"].iloc[-1]) / hi) / 0.10 * 100)
    score = _clip(0.6 * level + 0.25 * spike + 0.15 * dd)
    label = ("panic" if score >= 70 else "elevated" if score >= 40
             else "calm" if score < 20 else "normal")
    return score, f"VIX {last:.1f} — {label}"


def risk_off_rotation(sector_data: dict, tlt_df) -> tuple[float, str]:
    """Growth -> safe-haven flow, 0 = risk-on … 100 = full risk-off (1M returns)."""
    growth = [r for n in GROWTH_SECTORS if n in sector_data
              for r in [pct_change(sector_data[n], 21)] if r is not None]
    haven = [r for n in HAVEN_SECTORS if n in sector_data
             for r in [pct_change(sector_data[n], 21)] if r is not None]
    tlt_r = pct_change(tlt_df, 21)
    if tlt_r is not None:
        haven.append(tlt_r)
    if not growth or not haven:
        return 50.0, "insufficient data"
    spread = float(np.mean(haven) - np.mean(growth))  # + = rotating to safety
    score = _clip(50 + spread / 6 * 50)  # +/-6pp maps to 0/100
    tilt = "risk-off" if spread > 1 else "risk-on" if spread < -1 else "mixed"
    return score, f"{tilt} flow ({spread:+.1f}pp haven-vs-growth 1M)"


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
