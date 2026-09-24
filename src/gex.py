"""Gamma exposure (GEX) from yfinance option chains.

Method: Black-Scholes gamma per contract using the contract's own implied
vol, aggregated by strike across the nearest expiries. Dealer positioning
assumption (standard): dealers are short calls / long puts, so

    GEX(strike) = (put_OI * put_gamma - call_OI * call_gamma) * 100 * spot

in dollars of delta-hedge flow per 1-point move (displayed in $M).
Positive GEX = dealers long gamma (dampens moves, pinning);
negative GEX = dealers short gamma (amplifies moves).

Approximations (documented, not hidden):
- risk-free rate fixed at 4% (gamma is insensitive to r)
- no dividend yield
- time to expiry clamped at >= 6 hours (avoids 0DTE gamma blow-ups)
- open interest is prior-day (yfinance); IV rows that are NaN are skipped
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import yfinance as yf

RISK_FREE = 0.04
MIN_T_YEARS = 0.25 / 365  # 6 hours


def _bs_gamma(S: float, K: np.ndarray, T: float, r: float,
              sigma: np.ndarray) -> np.ndarray:
    """Black-Scholes gamma (same for calls and puts), vectorized over K/sigma."""
    with np.errstate(divide="ignore", invalid="ignore"):
        d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
        n_prime = np.exp(-0.5 * d1 ** 2) / np.sqrt(2 * np.pi)
        gamma = n_prime / (S * sigma * np.sqrt(T))
    return np.where(np.isfinite(gamma), gamma, 0.0)


def gex_by_strike(etf: str, n_expiries: int = 3) -> dict:
    """Aggregate GEX by strike for an ETF. Raises RuntimeError if no chain data."""
    t = yf.Ticker(etf)
    try:
        expiries = list(t.options)[:n_expiries]
    except Exception as e:
        raise RuntimeError(f"no expiry list for {etf}: {e}")
    if not expiries:
        raise RuntimeError(f"no expiries for {etf}")
    hist = t.history(period="5d")
    if hist.empty:
        raise RuntimeError(f"no price history for {etf}")
    spot = float(hist["Close"].iloc[-1])
    today = date.today()

    rows = []
    for exp in expiries:
        T = max((date.fromisoformat(exp) - today).days / 365.0, MIN_T_YEARS)
        try:
            chain = t.option_chain(exp)
        except Exception:
            continue
        for side, sign in (("calls", -1.0), ("puts", 1.0)):
            df = getattr(chain, side)
            if df.empty:
                continue
            df = df[(df["openInterest"].fillna(0) > 0) &
                    (df["impliedVolatility"].fillna(0) > 0) &
                    (df["impliedVolatility"] < 5)].copy()
            if df.empty:
                continue
            K = df["strike"].to_numpy(float)
            iv = df["impliedVolatility"].to_numpy(float)
            oi = df["openInterest"].to_numpy(float)
            gamma = _bs_gamma(spot, K, T, RISK_FREE, iv)
            # $ of hedge flow per 1-pt move, signed by dealer positioning
            df["gex_m"] = sign * gamma * oi * 100.0 * spot / 1e6
            df["side"] = side
            rows.append(df[["strike", "gex_m", "side"]])
    if not rows:
        raise RuntimeError(f"no usable option data for {etf}")

    all_ = pd.concat(rows)
    piv = all_.pivot_table(index="strike", columns="side", values="gex_m",
                           aggfunc="sum").fillna(0.0)
    for c in ("calls", "puts"):
        if c not in piv.columns:
            piv[c] = 0.0
    piv["net_gex"] = piv["puts"] + piv["calls"]  # calls already negative
    piv = piv.sort_index()

    # Key levels
    total_net = float(piv["net_gex"].sum())
    # call wall: strike with largest call-side magnitude above spot (resistance)
    above = piv[piv.index >= spot]
    below = piv[piv.index <= spot]
    call_wall = float(above["calls"].idxmin()) if not above.empty and (above["calls"] < 0).any() else None
    put_wall = float(below["puts"].idxmax()) if not below.empty and (below["puts"] > 0).any() else None
    # zero gamma: first strike (ascending) where cumulative net GEX flips + to -
    cumsum = piv["net_gex"].cumsum()
    zero_gamma = None
    pos = cumsum > 0
    flip = pos & (~pos.shift(-1, fill_value=True))
    hits = flip[flip].index
    zero_gamma = float(hits[0]) if len(hits) else None

    return {
        "etf": etf, "spot": spot, "expiries": expiries,
        "strikes": piv.reset_index(), "total_net": total_net,
        "call_wall": call_wall, "put_wall": put_wall,
        "zero_gamma": zero_gamma,
    }


def gex_chart(g: dict, title: str) -> go.Figure:
    """Net GEX by strike ($M per 1-pt move) with spot, walls, zero-gamma."""
    df = g["strikes"]
    spot = g["spot"]
    df = df[(df["strike"] >= spot * 0.92) & (df["strike"] <= spot * 1.08)]
    colors = ["#2ecc71" if x >= 0 else "#e74c3c" for x in df["net_gex"]]
    fig = go.Figure(go.Bar(x=df["strike"], y=df["net_gex"], marker_color=colors,
                           name="Net GEX ($M/pt)"))
    fig.add_vline(x=spot, line_color="#1f77b4", line_width=2,
                  annotation_text=f"Spot {spot:.0f}")
    if g["put_wall"]:
        fig.add_vline(x=g["put_wall"], line_color="#2ecc71", line_dash="dash",
                      annotation_text=f"Put wall {g['put_wall']:.0f}")
    if g["call_wall"]:
        fig.add_vline(x=g["call_wall"], line_color="#e74c3c", line_dash="dash",
                      annotation_text=f"Call wall {g['call_wall']:.0f}")
    if g["zero_gamma"]:
        fig.add_vline(x=g["zero_gamma"], line_color="#f1c40f", line_dash="dot",
                      annotation_text=f"0γ {g['zero_gamma']:.0f}")
    fig.update_layout(title=title, height=380, margin=dict(t=40, b=10),
                      xaxis_title="Strike", yaxis_title="Net GEX ($M per 1-pt move)",
                      bargap=0.1)
    return fig


def gex_read(g: dict) -> str:
    """One-line interpretation of the positioning."""
    t = g["total_net"]
    tone = ("dealers long gamma — moves tend to be dampened/pinned"
            if t > 0 else
            "dealers short gamma — moves tend to be amplified")
    zg = f" Zero-gamma at {g['zero_gamma']:.0f}: above it, volatility can expand fast." if g["zero_gamma"] else ""
    return (f"Net GEX ${t:+.0f}M/pt — {tone}.{zg}")
