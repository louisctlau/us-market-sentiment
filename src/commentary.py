"""Data-driven market commentary. Every sentence is derived from live data —
no canned text, no model opinions. Thresholds are documented inline."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .data import pct_change
from .technicals import sma


def _ord(n: int) -> str:
    return f"{n}{'th' if 11 <= n % 100 <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def _pct_rank(s: pd.Series) -> float:
    """Percentile of the last value within the series (0-100)."""
    s = s.dropna()
    if len(s) < 2:
        return 50.0
    return float((s <= float(s.iloc[-1])).mean() * 100)


def _sma_pos(s: pd.Series, n: int = 50) -> tuple[float, float] | tuple[None, None]:
    m = sma(s, n)
    if m.isna().all():
        return None, None
    return float(s.iloc[-1]), float(m.iloc[-1])


def vix_commentary(vix_df: pd.DataFrame) -> str:
    """Where VIX stands vs its 1-year range and where it is trending."""
    v = vix_df["close"].dropna()
    if v.empty:
        return "VIX data unavailable."
    last = float(v.iloc[-1])
    pr = _pct_rank(v)
    lo, hi = float(v.min()), float(v.max())
    chg = pct_change(vix_df, 21)
    _, m50 = _sma_pos(v)
    level = ("complacent" if last < 15 else "normal" if last < 20
             else "elevated" if last < 30 else "panic")
    trend = (f"{'above' if last > m50 else 'below'} its 50-day average ({m50:.1f})"
             if m50 else "trend unclear")
    chg_txt = f", {chg:+.0f}% over the past month" if chg is not None else ""
    read = ("Options are pricing calm — the risk is a snap-back if news breaks."
            if last < 15 else
            "Fear is contained; dips have been bought."
            if last < 20 else
            "Hedging demand is building — expect choppy price action."
            if last < 30 else
            "Full risk-off pricing — capitulation or genuine distress.")
    return (f"**VIX {last:.1f} — {level}.** Sits in the {_ord(int(round(pr)))} percentile of its "
            f"1-year range ({lo:.1f}–{hi:.1f}), {trend}{chg_txt}. {read}")


def dxy_commentary(dxy_df: pd.DataFrame) -> str:
    """Where the dollar stands vs its 1-year range and where it is trending."""
    d = dxy_df["close"].dropna()
    if d.empty:
        return "DXY data unavailable."
    last = float(d.iloc[-1])
    pr = _pct_rank(d)
    lo, hi = float(d.min()), float(d.max())
    chg = pct_change(dxy_df, 21)
    _, m50 = _sma_pos(d)
    strength = "strong" if pr >= 70 else "soft" if pr <= 30 else "mid-range"
    trend = (f"{'above' if last > m50 else 'below'} its 50-day average"
             if m50 else "trend unclear")
    chg_txt = f", {chg:+.1f}% over the past month" if chg is not None else ""
    read = ("A firm dollar is a headwind for US multinationals and EM risk assets."
            if pr >= 70 else
            "A soft dollar is a tailwind for risk assets and commodities."
            if pr <= 30 else
            "The dollar is neutral — neither a clear headwind nor tailwind.")
    return (f"**DXY {last:.1f} — {strength}.** {_ord(int(round(pr)))} percentile of its 1-year "
            f"range ({lo:.0f}–{hi:.0f}), {trend}{chg_txt}. {read}")


def yield_commentary(y10_df: pd.DataFrame, y5_df: pd.DataFrame) -> str:
    """Where the 10Y stands vs its 1-year range, its trend, and curve shape."""
    y = y10_df["close"].dropna()
    if y.empty:
        return "Yield data unavailable."
    last = float(y.iloc[-1])
    pr = _pct_rank(y)
    lo, hi = float(y.min()), float(y.max())
    chg_pp = None
    if len(y) > 21:
        chg_pp = float(y.iloc[-1] - y.iloc[-22])
    _, m50 = _sma_pos(y)
    trend = (f"{'above' if last > m50 else 'below'} its 50-day average ({m50:.2f}%)"
             if m50 else "trend unclear")
    chg_txt = f", {chg_pp:+.2f}pp over the past month" if chg_pp is not None else ""
    spread_txt = ""
    if not y5_df.empty:
        spread = float(y.iloc[-1] - y5_df["close"].iloc[-1])
        shape = "normal" if spread > 0.25 else "flat" if spread >= 0 else "inverted"
        spread_txt = f" The 10Y–5Y spread is {spread:+.2f}pp ({shape})."
    read = ("Yields grinding higher tighten financial conditions — a headwind "
            "for duration and growth multiples."
            if (chg_pp or 0) > 0.25 else
            "Yields easing off their highs loosen financial conditions — "
            "supportive for equities."
            if (chg_pp or 0) < -0.25 else
            "Yields are range-bound — rates are background noise for now.")
    return (f"**US 10Y {last:.2f}% — {_ord(int(round(pr)))} percentile of its 1-year range "
            f"({lo:.2f}–{hi:.2f}%), {trend}{chg_txt}.{spread_txt} {read}")


def volatility_overview(vix_df: pd.DataFrame, vvix_df: pd.DataFrame,
                        skew_df: pd.DataFrame, vix9d_df: pd.DataFrame,
                        vix3m_df: pd.DataFrame) -> str:
    """One-paragraph read across the vol complex: VIX level, vol-of-vol,
    tail-risk pricing, and term-structure shape. Thresholds documented inline."""
    v = vix_df["close"].dropna() if vix_df is not None else pd.Series(dtype=float)
    if v.empty:
        return "Volatility data unavailable."
    last = float(v.iloc[-1])
    pr = _pct_rank(v)
    chg = pct_change(vix_df, 21)
    lvl = ("complacent" if last < 15 else "normal" if last < 20
           else "elevated" if last < 30 else "panic")
    bits = [f"VIX {last:.1f} ({lvl}) sits in the {_ord(int(round(pr)))} percentile "
            f"of its 1-year range"
            + (f", {chg:+.0f}% over the past month." if chg is not None else ".")]

    # VVIX (vol-of-vol): typically 70–110; >120 = heavy demand for VIX options,
    # i.e. traders paying up for volatility protection.
    vv = vvix_df["close"].dropna() if vvix_df is not None and not vvix_df.empty else pd.Series(dtype=float)
    if not vv.empty:
        vl = float(vv.iloc[-1])
        vv_read = ("elevated — traders are paying up for volatility protection"
                   if vl > 120 else
                   "subdued — little demand for crash protection"
                   if vl < 80 else "in its normal range")
        bits.append(f"VVIX {vl:.0f} is {vv_read}.")

    # SKEW: 100 = baseline; >=135 = downside protection is expensive (tail fear);
    # <=115 = complacent tail pricing.
    sk = skew_df["close"].dropna() if skew_df is not None and not skew_df.empty else pd.Series(dtype=float)
    if not sk.empty:
        sl = float(sk.iloc[-1])
        sk_read = ("elevated — downside protection is expensive"
                   if sl >= 135 else
                   "calm — downside protection is cheap"
                   if sl <= 115 else "middling")
        bits.append(f"SKEW {sl:.0f}: tail-risk pricing is {sk_read}.")

    # Term structure: normal = contango (9D < 30D < 3M); 9D > 30D (backwardation)
    # means near-term fear exceeds longer-term expectations — classic stress.
    def _last(df):
        s = df["close"].dropna() if df is not None and not df.empty else None
        return float(s.iloc[-1]) if s is not None and not s.empty else None

    v9, v3 = _last(vix9d_df), _last(vix3m_df)
    if v9 is not None and v3 is not None:
        shape = ("in backwardation — near-term fear exceeds longer-term expectations"
                 if v9 > last else
                 "flat — no strong near-vs-far fear signal"
                 if abs(v3 - v9) < 1.0 else
                 "in contango — the normal upward-sloping vol curve")
        bits.append(f"The VIX term structure ({v9:.1f} / {last:.1f} / {v3:.1f} for "
                    f"9D / 30D / 3M) is {shape}.")
    return " ".join(bits)


def market_commentary(ctx: dict) -> str:
    """Overall market take: regime, what supports it, and the single major risk.

    ctx keys: score, regime, breakdown {name: {score, detail}}, fear, rot_detail,
    headline_meter, vix (df), snaps {name: snapshot}, y10 (df), dxy (df).
    """
    score, regime = ctx["score"], ctx["regime"]
    bd = ctx["breakdown"]
    vix = ctx["vix"]["close"].dropna()
    vix_last = float(vix.iloc[-1]) if not vix.empty else float("nan")

    # What is working: top-2 components by score
    ranked = sorted(bd.items(), key=lambda kv: kv[1]["score"], reverse=True)
    top_txt = "; ".join(f"{k} ({v['detail']})" for k, v in ranked[:2])
    lead = (f"The tape is supported by {top_txt}."
            if ranked[0][1]["score"] >= 50 else
            f"Little is working — the least-bad areas are {top_txt}.")

    # Major risk: severity-ranked candidates (severity 0-100)
    risks: list[tuple[float, str]] = []
    spike = pct_change(ctx["vix"], 5)
    if spike is not None and spike > 20:
        risks.append((80, f"a volatility spike — VIX +{spike:.0f}% in 5 days to {vix_last:.1f}"))
    fear = ctx["fear"]
    if fear >= 60:
        risks.append((fear, f"elevated volatility fear (fear context {fear:.0f}/100, VIX {vix_last:.1f})"))
    hm = ctx["headline_meter"]
    if hm >= 60:
        risks.append((hm, f"headline risk ({hm:.0f}/100) — news flow, not positioning, is the threat"))
    rot = ctx["rot"]
    if rot >= 60:
        risks.append((rot, f"defensive rotation — capital moving to safe havens ({ctx['rot_detail']})"))
    rsis = [s["rsi"] for s in ctx["snaps"].values() if s.get("rsi") is not None]
    if rsis:
        avg_rsi = float(np.mean(rsis))
        if avg_rsi >= 65:
            risks.append((55 + min(20, avg_rsi - 65),
                          f"overbought momentum (average RSI {avg_rsi:.0f} — crowded longs)"))
    y = ctx["y10"]["close"].dropna()
    if len(y) > 21:
        ychg = float(y.iloc[-1] - y.iloc[-22])
        if ychg >= 0.5:
            risks.append((55 + min(25, ychg * 30),
                          f"surging yields (10Y +{ychg:.2f}pp in a month — tighter financial conditions)"))
    dchg = pct_change(ctx["dxy"], 21)
    if dchg is not None and dchg >= 3:
        risks.append((55, f"a surging dollar (DXY +{dchg:.1f}% in a month — headwind for risk)"))

    # Baseline watch items, always scored so the top concern is named even
    # when nothing crosses a risk threshold.
    baseline = [
        (fear, f"volatility fear (fear context {fear:.0f}/100)"),
        (hm, f"headline risk ({hm:.0f}/100)"),
        (rot, f"defensive rotation ({rot:.0f}/100)"),
    ]

    if risks:
        sev, major = max(risks, key=lambda r: r[0])
        risk_txt = (f"**The major risk right now is {major}.** "
                    f"That is the one factor most likely to break the {regime.lower()} tape.")
    elif not np.isnan(vix_last) and vix_last < 14:
        risk_txt = (f"**The major risk right now is complacency itself** — VIX {vix_last:.1f} "
                    f"means the market is priced for perfection, so any shock lands harder.")
    else:
        _, closest = max(baseline, key=lambda r: r[0])
        risk_txt = (f"**No single dominant risk** — the closest watch item is {closest}.")

    watch = ""
    if len(risks) > 1:
        sev2, second = sorted(risks, key=lambda r: r[0], reverse=True)[1]
        watch = f" Also on watch: {second}."

    return (f"**Regime: {regime} ({score:.1f}/100).** "
            f"{lead}{watch} {risk_txt}")
