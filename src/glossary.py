"""One-line definitions for the "What am I looking at?" expanders.

Keyed by tab name. New module (2026-10-10).
"""
from __future__ import annotations

import streamlit as st

GLOSSARY: dict[str, list[str]] = {
    "Overview": [
        "**Composite Sentiment** — one 0–100 number blending 8 market sleeves "
        "(trend, momentum, volatility, credit, macro, sectors, positioning, news). "
        "100 = most bullish.",
        "**Sleeve** — one input to the composite, each scored 0–100 and given a "
        "weight (Trend 20%, Volatility/Macro/Sectors 15% each, Momentum/Credit/"
        "Positioning 10% each, News 5%).",
        "**Regime** — the gauge's plain-English read: Risk-On (≥70), Neutral "
        "(45–70), Risk-Off (30–45), Extreme Fear (<30).",
        "**Headline gauge** — the big number is a 3-day average, so one wild "
        "session can't swing it 10+ points.",
        "**Attribution** — how many points each sleeve adds (green) or "
        "subtracts (red) vs the neutral 50 baseline.",
    ],
    "Indices": [
        "**RSI (14)** — momentum oscillator 0–100; above 70 = overbought, "
        "below 30 = oversold.",
        "**SMA 50 / SMA 200** — 50- and 200-day simple moving averages; price "
        "above them is a bullish trend sign.",
        "**Golden cross** — the 50-day average crossing above the 200-day: a "
        "classic long-term bullish signal.",
        "**MACD histogram** — momentum gauge; positive and rising means "
        "upside momentum is building.",
    ],
    "Volatility": [
        "**VIX** — the market's 30-day fear gauge, implied from S&P 500 "
        "options. <15 complacent, 15–20 normal, 20–30 elevated, >30 panic.",
        "**VVIX** — volatility *of* the VIX: demand for volatility "
        "protection itself. Above 120 = heavy hedging.",
        "**SKEW** — how much traders pay for downside (tail) protection vs "
        "upside. ≥135 = crash protection is expensive.",
        "**MOVE** — the bond market's VIX: implied volatility in Treasuries. "
        "≥140 = real rates stress.",
        "**Contango / backwardation** — contango (curve sloping up) is the "
        "normal state; backwardation (front above back) means near-term fear "
        "exceeds longer-term expectations.",
    ],
    "Macro": [
        "**FEDFUNDS / DFF** — the effective federal funds rate: what banks "
        "actually charge each other overnight.",
        "**UNRATE** — the US unemployment rate (monthly, FRED).",
        "**Sahm rule** — 3-month average unemployment vs its 12-month low; "
        "≥0.50pp has never fired without a recession following.",
        "**10Y–2Y spread** — 10-year minus 2-year Treasury yield. Negative "
        "(inverted) has preceded every modern US recession.",
        "**CPI / PCE** — the two inflation gauges the Fed watches; PCE is "
        "the Fed's preferred one.",
    ],
    "Sector Rotation": [
        "**Offensive sectors** — tech, consumer discretionary, "
        "communication: outperform when investors chase growth.",
        "**Defensive sectors** — staples, utilities, health care: "
        "outperform when investors hide.",
        "**Rotation read** — offensive beating defensive = risk-on tilt, and "
        "vice versa.",
    ],
    "News Risk": [
        "**Headline Risk** — 0–100 gauge from ~30 fresh headlines (Google "
        "News + CNBC): keyword + VADER sentiment scoring, averaged over the "
        "10 riskiest.",
        "**Severity bands** — 0–20 Calm, 20–40 Low, 40–60 Elevated, 60–80 "
        "High, 80–100 Severe.",
        "**Verb-aware** — 'yields surge' scores as risk, 'yields ease' as "
        "relief; 'deal signed' vs 'deal collapses' read oppositely.",
    ],
    "Economic Calendar": [
        "**Forecast / Previous / Actual** — what economists expected, what "
        "the last print was, what just landed.",
        "**Verdict** — the Actual cell turns green when the release beats "
        "expectations, red when it misses.",
        "**Impact** — how much the event typically moves markets.",
    ],
    "Earnings": [
        "**EPS surprise** — reported earnings per share vs consensus "
        "estimate, in %.",
        "**Beat / miss** — green highlight = beat expectations, red = miss.",
        "**Notable** — filtered to companies ≥ $5B market cap.",
    ],
    "GEX": [
        "**GEX (gamma exposure)** — how much dealer hedging flows amplify "
        "or dampen S&P moves, in $M per 1-point move.",
        "**Net GEX** — positive = dealers long gamma (dampens moves); "
        "negative = short gamma (amplifies moves).",
        "**Put wall / Call wall** — strikes with the heaviest put/call "
        "gamma: magnets that act as support / resistance.",
        "**γflip** — the strike where net gamma flips sign; below it, "
        "dealer hedging starts amplifying moves instead of dampening.",
        "**GEX history** — the same daily snapshot, tracked over time from "
        "the archived option chains.",
    ],
    "Fed Watch": [
        "**Target range** — where the FOMC sets the fed funds rate "
        "(currently 3.75–4.00%, set Sep 16, 2026).",
        "**Implied probabilities** — odds of each rate outcome stripped "
        "from 30-day Fed Funds futures (CME ZQ).",
        "**DFF** — the effective (actually-traded) fed funds rate, daily "
        "from FRED.",
        "**Vertical markers** — gray dashed = FOMC decisions, light dotted "
        "= CPI releases.",
    ],
}


def show(tab_name: str) -> None:
    """Render the glossary expander for a tab. Unknown tabs render nothing."""
    items = GLOSSARY.get(tab_name)
    if not items:
        return
    with st.expander("What am I looking at?"):
        for line in items:
            st.markdown(f"- {line}")
