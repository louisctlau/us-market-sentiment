"""Sleeve attribution for the composite sentiment score.

Contribution of each sleeve vs the neutral 50 baseline:
    contribution = (sleeve_score - 50) * weight
Contributions sum to (composite - 50). New module (2026-10-10): keep
attribution logic out of sentiment_v2.py so a stale-module deploy can
never break the score itself.
"""
from __future__ import annotations

import plotly.graph_objects as go

# Sleeves whose inputs are price-based and therefore lag cleanly by one
# trading day. Positioning, News and Macro are today-only inputs
# (GEX/Fed-stance/news meter have no history), so including them in a
# day-over-day delta would show artificial moves.
PRICE_SLEEVES = ("Trend", "Momentum", "Volatility", "Credit", "Sectors")


def contributions(breakdown: dict, weights: dict) -> dict[str, float]:
    """Per-sleeve point contribution vs neutral 50. Defaults keep a stale
    breakdown payload from crashing the chart."""
    out = {}
    for name, w in (weights or {}).items():
        s = (breakdown or {}).get(name, {}).get("score", 50)
        try:
            out[name] = (float(s) - 50) * float(w)
        except (TypeError, ValueError):
            out[name] = 0.0
    return out


def attribution_figure(breakdown: dict, weights: dict) -> go.Figure:
    """Horizontal bar chart of sleeve contributions. Green = adds to the
    score (bullish), red = drags it down (bearish)."""
    contrib = contributions(breakdown, weights)
    names = list(contrib)
    vals = [contrib[n] for n in names]
    colors = ["#2ecc71" if v >= 0 else "#e74c3c" for v in vals]
    fig = go.Figure(go.Bar(
        x=vals, y=names, orientation="h", marker_color=colors,
        text=[f"{v:+.1f}" for v in vals], textposition="outside",
        hovertemplate="%{y}: %{x:+.2f} pts<extra></extra>"))
    fig.add_vline(x=0, line_color="#888", line_width=1)
    fig.update_layout(title="Sleeve attribution vs neutral (50)",
                      xaxis_title="Points added / subtracted",
                      height=max(260, 40 * len(names) + 80),
                      margin=dict(t=40, b=40, l=10, r=50))
    return fig


def sleeve_deltas(today: dict, yday: dict) -> dict[str, float]:
    """Day-over-day sleeve score change for price-based sleeves only."""
    out = {}
    for name in PRICE_SLEEVES:
        t = (today or {}).get(name)
        y = (yday or {}).get(name)
        try:
            if t is not None and y is not None:
                out[name] = float(t[0]) - float(y[0])
        except (TypeError, ValueError, IndexError):
            continue
    return out
