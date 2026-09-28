"""Composite market-sentiment scoring. Every sub-score is 0-100 (100 = most bullish).

Component weights (sum to 1.0):
    Trend 20% · Momentum 15% · Volatility 15% · Credit 10% ·
    Macro 15% · Sectors 15% · Positioning 10%

Design notes:
- Percentile-based inputs (VIX, VVIX, SKEW, MOVE, credit) are measured
  against trailing history instead of fixed levels, so the score adapts
  as volatility regimes drift.
- Every sleeve degrades to neutral 50 when its data is missing, and
  sleeves are re-weighted over what's available — a failed feed never
  tanks the composite.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .data import DEFENSIVE_SECTORS, GROWTH_SECTORS, HAVEN_SECTORS, OFFENSIVE_SECTORS, pct_change
from .technicals import ordinal, rsi, sma


def _clip(x: float) -> float:
    return float(max(0.0, min(100.0, x)))


def _is_empty(df) -> bool:
    """True when a price frame is missing/empty — never let iloc[-1] crash."""
    return df is None or getattr(df, "empty", True)


def _pct_rank(s: pd.Series) -> float:
    """Percentile of the last value within the series (0-100)."""
    s = s.dropna()
    if len(s) < 2:
        return 50.0
    return float((s <= s.iloc[-1]).mean()) * 100


def _blend(sleeves: list[tuple[float | None, float]]) -> float:
    """Weighted average over available sleeves (None = missing → skipped),
    re-normalized so missing data can't drag the result toward zero."""
    avail = [(s, w) for s, w in sleeves if s is not None]
    if not avail:
        return 50.0
    return _clip(sum(s * w for s, w in avail) / sum(w for _, w in avail))


def trend_score(snapshots: dict[str, dict], breadth: pd.Series | None = None) -> tuple[float, str]:
    flags = [s["above_sma50"] for s in snapshots.values() if s["above_sma50"] is not None]
    if not flags:
        return 50.0, "no SMA50 data"
    share = sum(flags) / len(flags)
    base = _clip(share * 100)
    label = f"{sum(flags)}/{len(flags)} indices above 50-day average"
    # Breadth: RSP (equal-weight S&P) vs SPX — rising = broad participation,
    # falling = narrow mega-cap leadership. ±1.5pp vs 50d maps to 0/100.
    if breadth is not None and len(breadth.dropna()) > 50:
        b = breadth.dropna()
        ma50 = b.rolling(50).mean().iloc[-1]
        if not np.isnan(ma50) and ma50 != 0:
            dev = (b.iloc[-1] / ma50 - 1) * 100
            bscore = _clip(50 + dev / 1.5 * 50)
            return _clip(0.7 * base + 0.3 * bscore), label + f"; breadth {dev:+.2f}pp vs 50d"
    return base, label


def momentum_score(snapshots: dict[str, dict]) -> tuple[float, str]:
    rsis = [s["rsi"] for s in snapshots.values() if s.get("rsi") is not None]
    if not rsis:
        return 50.0, "no RSI data"
    avg = float(np.mean(rsis))
    # RSI 30 -> 0, 50 -> 50, 70 -> 100
    score = _clip((avg - 30) / 40 * 100)
    return score, f"avg RSI(14) {avg:.1f}"


def volatility_score(vix_df, vvix_df=None, skew_df=None, move_df=None,
                     futures_curve=None) -> tuple[float, str]:
    """Volatility complex: 1y percentiles (inverted — high vol = bearish) of
    VIX/VVIX/SKEW/MOVE plus the VX futures curve shape. Missing sleeves are
    skipped, not zeroed."""
    if _is_empty(vix_df):
        return 50.0, "VIX data unavailable"

    def pct_inv(df, weight):
        if _is_empty(df):
            return None
        return 100.0 - _pct_rank(df["close"].tail(252)), weight

    sleeves = [
        pct_inv(vix_df, 0.35),
        pct_inv(vvix_df, 0.20),
        pct_inv(skew_df, 0.15),
        pct_inv(move_df, 0.10),
    ]
    # Futures curve shape: contango (back > front) = healthy, backwardation = stress.
    # ±15% front-to-back slope maps to 0/100. Uses the latest curve only —
    # CBOE serves one trading day per file, so no multi-day history.
    if futures_curve is not None and not futures_curve.empty and len(futures_curve) >= 2:
        front = float(futures_curve["price"].iloc[0])
        back = float(futures_curve["price"].iloc[-1])
        if front > 0:
            slope = (back - front) / front
            sleeves.append((_clip(50 + slope / 0.15 * 50), 0.20))
    sleeves = [s for s in sleeves if s is not None]
    score = _blend(sleeves)
    last = float(vix_df["close"].iloc[-1])
    detail = f"VIX {last:.1f} ({ordinal(_pct_rank(vix_df["close"].tail(252)))} pct 1y)"
    spike = pct_change(vix_df, 5)
    if spike is not None and spike > 20:
        score = _clip(score - 15)
        detail += f" (+{spike:.0f}% in 5d — spike penalty)"
    return score, detail


def credit_score(hyg_df, lqd_df, oas: pd.Series | None = None) -> tuple[float, str]:
    """Credit stress: HYG/LQD 5y percentile (rising = risk appetite) and
    ICE BofA HY option-adjusted spread percentile, inverted (wide = fear).
    FRED only carries ~3y of OAS history (licence change, Apr 2026)."""
    sleeves, notes = [], []
    if not _is_empty(hyg_df) and not _is_empty(lqd_df):
        ratio = (hyg_df["close"] / lqd_df["close"]).dropna()
        if len(ratio) > 50:
            pr = _pct_rank(ratio)
            sleeves.append((pr, 0.5))
            notes.append(f"HYG/LQD {ordinal(pr)} pct 5y")
    if oas is not None and len(oas.dropna()) > 50:
        o = oas.dropna()
        pr = 100.0 - _pct_rank(o)
        sleeves.append((pr, 0.5))
        notes.append(f"HY OAS {float(o.iloc[-1]):.2f}% ({ordinal(100 - pr)} pct)")
    if not sleeves:
        return 50.0, "credit data unavailable"
    return _blend(sleeves), "; ".join(notes)


def macro_score(dxy_df, y10_df, dgs2: pd.Series | None = None,
                unrate: pd.Series | None = None) -> tuple[float, str]:
    """Macro backdrop: USD vs 50d (continuous — falling dollar = risk-on),
    10Y–2Y curve spread (±1pp → 0/100), and the Sahm rule (0.00 → 100,
    0.50 trigger → 0, linear)."""
    sleeves, notes = [], []
    if not _is_empty(dxy_df):
        d = dxy_df["close"].dropna()
        ma50 = sma(d, 50).iloc[-1]
        if len(d) > 50 and not np.isnan(ma50) and ma50 != 0:
            dev = (d.iloc[-1] / ma50 - 1) * 100
            sleeves.append((_clip(50 - dev / 2 * 50), 0.4))
            notes.append(f"DXY {dev:+.2f}% vs 50d")
    if not _is_empty(y10_df) and dgs2 is not None and len(dgs2.dropna()) > 0:
        spread = float(y10_df["close"].iloc[-1]) - float(dgs2.dropna().iloc[-1])
        sleeves.append((_clip(50 + spread * 50), 0.3))
        notes.append(f"10Y–2Y {spread:+.2f}pp")
    if unrate is not None and len(unrate.dropna()) >= 12:
        u = unrate.dropna()
        u3m = u.rolling(3).mean()
        sahm = float(u3m.iloc[-1] - u3m.tail(12).min())
        sleeves.append((_clip((0.50 - sahm) / 0.50 * 100), 0.3))
        notes.append(f"Sahm {sahm:.2f}pp")
    if not sleeves:
        return 50.0, "macro data unavailable"
    return _blend(sleeves), "; ".join(notes)


def sector_score(sector_data: dict[str, object]) -> tuple[float, str]:
    """Offensive vs defensive 1M spread, z-scored against its own trailing
    6M volatility so the component uses its full range in calm markets too."""
    off, dfn = [], []
    for name, df in sector_data.items():
        if _is_empty(df):
            continue
        r = df["close"].pct_change()
        if name in OFFENSIVE_SECTORS:
            off.append(r)
        elif name in DEFENSIVE_SECTORS:
            dfn.append(r)
    if not off or not dfn:
        return 50.0, "insufficient sector data"
    spread_daily = pd.concat(off, axis=1).mean(axis=1) - pd.concat(dfn, axis=1).mean(axis=1)
    spread_1m = spread_daily.rolling(21).sum().dropna()  # trailing 1M spreads
    if len(spread_1m) < 30:
        return 50.0, "insufficient sector history"
    now = float(spread_1m.iloc[-1])
    vol = float(spread_1m.std())
    z = now / vol if vol > 0 else 0.0
    score = _clip(50 + z / 2 * 50)  # z = ±2 → 0/100
    tilt = "offensive" if now > 0 else "defensive"
    return score, f"{tilt} tilt ({now:+.2f}pp 1M, z={z:+.1f})"


def positioning_score(fear: tuple[float, str],
                      rotation: tuple[float, str]) -> tuple[float, str]:
    """Folds the Overview's Fear Context and Risk-Off Rotation gauges into the
    composite (both are 0-100, high = bad → inverted)."""
    score = _clip(100 - 0.5 * fear[0] - 0.5 * rotation[0])
    return score, f"fear {fear[0]:.0f} / rotation {rotation[0]:.0f} (inverted)"


def fear_context(vix_df, spx_df) -> tuple[float, str]:
    """VIX/SPX-driven fear, 0 = calm … 100 = panic. Market volatility, not news."""
    if _is_empty(vix_df) or _is_empty(spx_df):
        return 50.0, "VIX/SPX data unavailable"
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


def regime(score: float) -> str:
    if score >= 70:
        return "Risk-On"
    if score >= 45:
        return "Neutral"
    if score >= 25:
        return "Risk-Off"
    return "Extreme Fear"


WEIGHTS = {"Trend": 0.20, "Momentum": 0.15, "Volatility": 0.15, "Credit": 0.10,
           "Macro": 0.15, "Sectors": 0.15, "Positioning": 0.10}


def composite(components: dict[str, tuple[float, str]]) -> tuple[float, dict]:
    total = sum(score * WEIGHTS[name] for name, (score, _) in components.items())
    return _clip(total), {n: {"score": s, "detail": d} for n, (s, d) in components.items()}
