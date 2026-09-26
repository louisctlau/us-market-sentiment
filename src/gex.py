"""Gamma exposure (GEX) for index-proxy ETFs.

Primary source: CBOE delayed-quotes API (public, no key), which publishes
per-contract gamma and open interest. Fallback: yfinance option chains with
Black-Scholes gamma estimated from each contract's implied vol.

Dealer positioning assumption (standard): dealers are long calls / short
puts, so

    GEX(strike) = (call_OI * call_gamma - put_OI * put_gamma) * 100 * spot

in dollars of delta-hedge flow per 1-point move (displayed in $M).
Positive GEX = dealers long gamma (dampens moves, pinning);
negative GEX = dealers short gamma (amplifies moves). [gex-v5]

yfinance fallback approximations (documented, not hidden): risk-free rate
fixed at 4%, no dividend yield, time to expiry clamped at >= 6 hours.
Open interest is prior-day on both sources.
"""
from __future__ import annotations

from datetime import date, datetime
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import plotly.graph_objects as go

CBOE_URL = "https://cdn.cboe.com/api/global/delayed_quotes/options/{}.json"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# --- yfinance fallback: Black-Scholes gamma ---
RISK_FREE = 0.04
MIN_T_YEARS = 0.25 / 365


def _bs_gamma(S: float, K: np.ndarray, T: float, r: float,
              sigma: np.ndarray) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
        n_prime = np.exp(-0.5 * d1 ** 2) / np.sqrt(2 * np.pi)
        gamma = n_prime / (S * sigma * np.sqrt(T))
    return np.where(np.isfinite(gamma), gamma, 0.0)


def _parse_cboe_symbol(sym: str) -> tuple[str, str, float]:
    """'SPY260924C00550000' -> (expiry 'YYYY-MM-DD', side, strike)."""
    expiry = f"20{sym[3:5]}-{sym[5:7]}-{sym[7:9]}"
    side = "calls" if sym[9] == "C" else "puts"
    strike = int(sym[10:]) / 1000.0
    return expiry, side, strike


def _from_cboe(etf: str, n_expiries: int) -> dict:
    import json
    req = Request(CBOE_URL.format(etf), headers=UA)
    try:
        with urlopen(req, timeout=25) as resp:
            raw = resp.read().decode()
    except Exception as e:
        raise RuntimeError(f"CBOE request failed for {etf}: {e}")
    try:
        payload = json.loads(raw)
    except Exception:
        raise RuntimeError(f"CBOE returned non-JSON for {etf} "
                           f"(likely bot-blocked, {len(raw)} bytes)")
    data = payload["data"]
    spot = float(data["current_price"])
    opts = data.get("options") or []
    if not opts:
        raise RuntimeError(f"CBOE returned no contracts for {etf}")

    rows = []
    for o in opts:
        oi = float(o.get("open_interest") or 0)
        gamma = float(o.get("gamma") or 0)
        if oi <= 0 or gamma <= 0:
            continue
        expiry, side, strike = _parse_cboe_symbol(o["option"])
        sign = 1.0 if side == "calls" else -1.0
        rows.append({"strike": strike, "expiry": expiry, "side": side,
                     "gex_m": sign * gamma * oi * 100.0 * spot / 1e6})
    if not rows:
        raise RuntimeError(f"CBOE returned no usable OI/gamma for {etf}")
    df = pd.DataFrame(rows)
    expiries = sorted(df["expiry"].unique())[:n_expiries]
    df = df[df["expiry"].isin(expiries)]
    return {"spot": spot, "expiries": expiries, "contracts": df}


def _from_yfinance(etf: str, n_expiries: int) -> dict:
    import yfinance as yf
    t = yf.Ticker(etf)
    expiries = list(t.options or [])[:n_expiries]
    if not expiries:
        raise RuntimeError(f"no expiries for {etf}")
    hist = t.history(period="5d")
    if hist.empty:
        raise RuntimeError(f"no price history for {etf}")
    spot = float(hist["Close"].iloc[-1])
    today = datetime.now(ZoneInfo("America/Toronto")).date()  # ET, not server-local
    rows = []
    for exp in expiries:
        T = max((date.fromisoformat(exp) - today).days / 365.0, MIN_T_YEARS)
        try:
            chain = t.option_chain(exp)
        except Exception:
            continue
        for side, sign in (("calls", 1.0), ("puts", -1.0)):
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
            df["gex_m"] = sign * gamma * oi * 100.0 * spot / 1e6
            df["side"] = side
            rows.append(df[["strike", "gex_m", "side"]])
    if not rows:
        raise RuntimeError(f"no usable option data for {etf}")
    contracts = pd.concat(rows)
    contracts["expiry"] = ""
    return {"spot": spot, "expiries": expiries, "contracts": contracts}


def gex_by_strike(etf: str, n_expiries: int = 3) -> dict:
    """Aggregate GEX by strike. Tries CBOE first, then yfinance."""
    errors = []
    for fn in (_from_cboe, _from_yfinance):
        try:
            src = fn(etf, n_expiries)
            break
        except Exception as e:
            errors.append(f"{fn.__name__}: {e}")
    else:
        raise RuntimeError("[gex-v5] " + "; ".join(errors))

    contracts = src["contracts"]
    piv = contracts.pivot_table(index="strike", columns="side", values="gex_m",
                                aggfunc="sum").fillna(0.0)
    for c in ("calls", "puts"):
        if c not in piv.columns:
            piv[c] = 0.0
    piv["net_gex"] = piv["calls"] + piv["puts"]  # puts already negative
    piv = piv.sort_index()

    spot = src["spot"]
    total_net = float(piv["net_gex"].sum())
    above = piv[piv.index >= spot]
    below = piv[piv.index <= spot]
    call_wall = (float(above["calls"].idxmax())
                 if not above.empty and (above["calls"] > 0).any() else None)
    put_wall = (float(below["puts"].idxmin())
                if not below.empty and (below["puts"] < 0).any() else None)
    cumsum = piv["net_gex"].cumsum()
    neg = cumsum < 0
    flip = neg & (~neg.shift(-1, fill_value=True))
    hits = flip[flip].index
    zero_gamma = float(hits[0]) if len(hits) else None

    return {"etf": etf, "spot": spot, "expiries": src["expiries"],
            "strikes": piv.reset_index(), "total_net": total_net,
            "call_wall": call_wall, "put_wall": put_wall,
            "zero_gamma": zero_gamma}


def gex_chart(g: dict, title: str) -> go.Figure:
    """Net GEX by strike ($M per 1-pt move): call gamma up, put gamma down.
    Spot, walls, zero-gamma overlaid."""
    df = g["strikes"]
    spot = g["spot"]
    df = df[(df["strike"] >= spot * 0.92) & (df["strike"] <= spot * 1.08)]
    y = df["net_gex"]
    colors = ["#2ecc71" if v >= 0 else "#e74c3c" for v in y]
    fig = go.Figure(go.Bar(x=df["strike"], y=y, marker_color=colors,
                           name="GEX by strike ($M/pt)"))
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
                      xaxis_title="Strike",
                      yaxis_title="Net GEX ($M per 1-pt move)",
                      bargap=0.1)
    return fig


def gex_read(g: dict) -> str:
    """One-line interpretation of the positioning."""
    t = g["total_net"]
    tone = ("dealers long gamma — moves tend to be dampened/pinned"
            if t > 0 else
            "dealers short gamma — moves tend to be amplified")
    zg = (f" Zero-gamma at {g['zero_gamma']:.0f}: below it, dealers are "
          f"short gamma and moves can accelerate." if g["zero_gamma"] else "")
    return f"Net GEX ${t:+.0f}M/pt — {tone}.{zg}"
