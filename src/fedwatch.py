"""Fed Watch — market-implied probabilities of Fed rate moves.

Method (CME FedWatch-style, futures-implied):
- 30-day Fed Funds futures (CME ZQ) price the average effective fed funds
  rate over the contract month: implied_rate = 100 - futures_price.
- For each FOMC meeting, the expected post-meeting rate is stripped from
  the meeting-month contract, weighting days before/after the decision day.
  Meetings chain: each meeting's pre-rate is the prior meeting's post-rate.
- The expected move (in 25bp units) is split across the two adjacent
  25bp buckets by linear interpolation, e.g. an expected +17bp move ->
  68% hike 25bp / 32% hold.

Data: Yahoo Finance (ZQ futures), FRED DFF (effective fed funds rate).
Educational — not investment advice.
"""
from __future__ import annotations

import calendar as _calendar
import io
import math
import urllib.request
from datetime import date, datetime, timezone

import pandas as pd
import plotly.graph_objects as go
import yfinance as yf

# (decision date, ZQ contract Yahoo ticker). Verified vs federalreserve.gov
# 2026 FOMC calendar: Oct 27-28, Dec 8-9; 2027: Jan 26-27.
MEETINGS = [
    (date(2026, 10, 28), "ZQV26.CBT"),
    (date(2026, 12, 9), "ZQZ26.CBT"),
    (date(2027, 1, 27), "ZQF27.CBT"),
]

DFF_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFF"

# Target range set 2026-09-16 (25bp hike to 3.75-4.00%). Shown for context;
# probabilities are derived from futures, not this constant.
TARGET_RANGE = (3.75, 4.00)

BUCKET_LABELS = {  # 25bp-unit -> label
    -2: "Cut 50bp", -1: "Cut 25bp", 0: "Hold",
    1: "Hike 25bp", 2: "Hike 50bp",
}
BUCKET_COLORS = {
    -2: "#1f77b4", -1: "#6baed6", 0: "#9e9e9e",
    1: "#fb8c00", 2: "#d62728",
}


def _fetch_dff() -> tuple[float, date]:
    """Effective fed funds rate from FRED (no API key needed)."""
    try:
        from curl_cffi import requests as _rq
        r = _rq.get(DFF_URL, headers={"User-Agent": "Mozilla/5.0"},
                    timeout=20, impersonate="chrome")
        r.raise_for_status()
        df = pd.read_csv(io.BytesIO(r.content))
    except Exception:
        req = urllib.request.Request(DFF_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            df = pd.read_csv(io.BytesIO(resp.read()))
    df = df.dropna()
    date_col = df.columns[0]
    last = df.iloc[-1]
    d = datetime.strptime(str(last[date_col]), "%Y-%m-%d").date()
    return float(last["DFF"]), d


def _fetch_zq(ticker: str) -> float:
    h = yf.Ticker(ticker).history(period="5d", auto_adjust=False)
    if h.empty:
        raise RuntimeError(f"no ZQ data for {ticker}")
    return float(h["Close"].iloc[-1])


def _split_buckets(move_bp: float) -> dict[int, float]:
    """Split an expected move (bp) across adjacent 25bp buckets."""
    x = move_bp / 25.0
    lo = math.floor(x + 1e-9)
    frac = x - lo
    out: dict[int, float] = {}
    if frac > 1e-9:
        out[lo] = 1.0 - frac
        out[lo + 1] = frac
    else:
        out[lo] = 1.0
    return out


def fedwatch() -> dict:
    """Compute futures-implied rate probabilities for upcoming FOMC meetings."""
    eff_rate, eff_date = _fetch_dff()
    today = datetime.now(timezone.utc).date()

    meetings = []
    r_prev = eff_rate
    for decision, ticker in MEETINGS:
        if decision <= today:
            continue
        price = _fetch_zq(ticker)
        implied = 100.0 - price  # avg effective rate over contract month
        n_days = _calendar.monthrange(decision.year, decision.month)[1]
        d = decision.day
        # days 1..d-1 at r_prev, days d..N at r_post
        r_post = (implied * n_days - r_prev * (d - 1)) / (n_days - d + 1)
        move_bp = (r_post - r_prev) * 100.0
        buckets = _split_buckets(move_bp)
        meetings.append({
            "date": decision,
            "days_away": (decision - today).days,
            "ticker": ticker,
            "futures_price": price,
            "implied_month_rate": implied,
            "prev_rate": r_prev,
            "post_rate": r_post,
            "move_bp": move_bp,
            "buckets": buckets,  # 25bp-unit -> probability
        })
        r_prev = r_post

    if not meetings:
        raise RuntimeError("no upcoming FOMC meetings in schedule")
    return {
        "effective_rate": eff_rate,
        "effective_date": eff_date,
        "target_range": TARGET_RANGE,
        "meetings": meetings,
    }


def _bucket_line(buckets: dict[int, float]) -> str:
    parts = []
    for k in sorted(buckets):
        label = BUCKET_LABELS.get(k, f"{k * 25:+d}bp")
        parts.append(f"{label} {buckets[k] * 100:.0f}%")
    return " · ".join(parts)


def fedwatch_read(m: dict) -> str:
    """One-line plain-English read of a meeting's probabilities."""
    best = max(m["buckets"], key=m["buckets"].__getitem__)
    p = m["buckets"][best] * 100
    dstr = m["date"].strftime("%b %d")
    if best == 0:
        return (f"For {dstr}, futures price a {p:.0f}% chance the Fed holds "
                f"(expected move {m['move_bp']:+.0f}bp).")
    direction = "hike" if best > 0 else "cut"
    size = abs(best * 25)
    return (f"For {dstr}, futures imply a {p:.0f}% chance of a {size}bp {direction} "
            f"(expected move {m['move_bp']:+.0f}bp, post-meeting rate ~{m['post_rate']:.2f}%).")


def fedwatch_chart(m: dict, title: str) -> go.Figure:
    keys = sorted(m["buckets"])
    fig = go.Figure(go.Bar(
        y=[BUCKET_LABELS.get(k, f"{k * 25:+d}bp") for k in keys],
        x=[m["buckets"][k] * 100 for k in keys],
        orientation="h",
        marker_color=[BUCKET_COLORS.get(k, "#9e9e9e") for k in keys],
        text=[f"{m['buckets'][k] * 100:.0f}%" for k in keys],
        textposition="outside",
    ))
    fig.update_layout(
        title=title, xaxis_title="Probability (%)",
        xaxis=dict(range=[0, max(100, max(m["buckets"].values()) * 100 + 15)]),
        height=280, margin=dict(l=90, r=40, t=40, b=40),
        showlegend=False,
    )
    return fig
