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
import numpy as np

# (decision date, ZQ contract Yahoo ticker). Verified vs federalreserve.gov
# 2026 FOMC calendar: Oct 27-28, Dec 8-9; 2027: Jan 26-27.
MEETINGS = [
    (date(2026, 10, 28), "ZQV26.CBT"),
    (date(2026, 12, 9), "ZQZ26.CBT"),
    (date(2027, 1, 27), "ZQF27.CBT"),
]

DFF_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFF"
DGS10_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10"

# Target range set 2026-09-16 (25bp hike to 3.75-4.00%). Shown for context;
# probabilities are derived from futures, not this constant.
TARGET_RANGE = (3.75, 4.00)

# Last FOMC decision, shown as a context line on the tab.
# Update after each meeting alongside TARGET_RANGE and MEETINGS.
LAST_DECISION = {
    "date": date(2026, 9, 16),
    "move": "+25bp",
    "vote": "unanimous",
    "note": "first hike since Jul 2023",
    "sep_median_dot": 4.1,  # September SEP median year-end fed funds rate
}


def last_decision_text() -> str:
    """One-line summary of the last FOMC decision for the tab header."""
    lo, hi = TARGET_RANGE
    d = LAST_DECISION
    return (f"{d['date'].strftime('%b %d, %Y')}: {d['move']} to "
            f"{lo:.2f}\u2013{hi:.2f}% ({d['vote']} \u2014 {d['note']}). "
            f"September SEP median year-end dot: {d['sep_median_dot']:.1f}%.")


def _fetch_fred_series(url: str) -> pd.DataFrame:
    """Full FRED series history as DataFrame with a date index (forward-fillable)."""
    try:
        from curl_cffi import requests as _rq
        r = _rq.get(url, headers={"User-Agent": "Mozilla/5.0"},
                    timeout=20, impersonate="chrome")
        r.raise_for_status()
        df = pd.read_csv(io.BytesIO(r.content))
    except Exception:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            df = pd.read_csv(io.BytesIO(resp.read()))
    date_col = df.columns[0]
    df[date_col] = pd.to_datetime(df[date_col])
    return df.set_index(date_col).sort_index()


def _fetch_dff_df() -> pd.DataFrame:
    """Full DFF history as DataFrame with a date index (forward-fillable)."""
    return _fetch_fred_series(DFF_URL)


def fetch_ten_year() -> tuple[float, date] | None:
    """10-year Treasury yield from FRED DGS10 (public CSV, no API key).

    Returns None on any failure so the tab degrades gracefully instead of
    going down when DGS10 is unavailable.
    """
    try:
        df = _fetch_fred_series(DGS10_URL)[["DGS10"]].dropna()
        last = df.iloc[-1]
        return float(last["DGS10"]), last.name.date()
    except Exception:
        return None

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
    df = _fetch_dff_df().dropna()
    last = df.iloc[-1]
    return float(last["DFF"]), last.name.date()


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


def fedwatch_history(days: int = 90) -> dict[date, pd.DataFrame]:
    """Daily history of aggregated hike/hold/cut probabilities per meeting.

    Recomputes the futures-implied distribution for each trading day in the
    lookback window, chaining meetings the same way as fedwatch().
    Returns {decision_date: DataFrame(date, p_hike, p_hold, p_cut)}.
    """
    dff = _fetch_dff_df()[["DFF"]].dropna()
    today = datetime.now(timezone.utc).date()
    upcoming = [(d, t) for d, t in MEETINGS if d > today]
    if not upcoming:
        raise RuntimeError("no upcoming FOMC meetings in schedule")

    # Align all contract histories on a common trading-day index.
    prices = {}
    for _, ticker in upcoming:
        h = yf.Ticker(ticker).history(period=f"{days + 15}d", auto_adjust=False)
        if h.empty:
            raise RuntimeError(f"no ZQ history for {ticker}")
        h.index = h.index.tz_localize(None).normalize()
        prices[ticker] = h["Close"]
    idx = sorted(set().union(*[set(s.index) for s in prices.values()]))
    idx = [d for d in idx if d.date() <= today][-days:]
    if not idx:
        raise RuntimeError("no overlapping ZQ history")
    frame = pd.DataFrame({"date": idx})
    for ticker, s in prices.items():
        frame[ticker] = frame["date"].map(s).ffill()

    dff_daily = dff["DFF"]
    frame["r_prev"] = frame["date"].map(
        lambda d: dff_daily.loc[:d].iloc[-1] if d >= dff_daily.index[0] else np.nan
    ).ffill()

    out: dict[date, pd.DataFrame] = {}
    r_prev_col = "r_prev"
    for decision, ticker in upcoming:
        n_days = _calendar.monthrange(decision.year, decision.month)[1]
        d = decision.day
        implied = 100.0 - frame[ticker]
        r_post = (implied * n_days - frame[r_prev_col] * (d - 1)) / (n_days - d + 1)
        move_bp = (r_post - frame[r_prev_col]) * 100.0
        x = move_bp / 25.0
        lo = np.floor(x + 1e-9)
        frac = x - lo
        # aggregate bucket weights into hike / hold / cut
        p_hold = np.where(lo == 0, 1 - frac, np.where(lo == -1, frac, 0.0))
        p_hike = np.where(lo >= 1, 1 - frac, 0.0) + np.where(lo >= 0, frac, 0.0)
        p_cut = 1.0 - p_hold - p_hike
        out[decision] = pd.DataFrame({
            "date": frame["date"],
            "p_hike": np.clip(p_hike, 0, 1),
            "p_hold": np.clip(p_hold, 0, 1),
            "p_cut": np.clip(p_cut, 0, 1),
        })
        frame[r_prev_col] = r_post  # chain: next meeting starts from here
    return out


def fedwatch_history_chart(df: pd.DataFrame, title: str) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df["date"], y=df["p_hike"] * 100, mode="lines",
                             name="Hike", line=dict(color="#d62728", width=2)))
    fig.add_trace(go.Scatter(x=df["date"], y=df["p_hold"] * 100, mode="lines",
                             name="Hold", line=dict(color="#9e9e9e", width=2)))
    fig.add_trace(go.Scatter(x=df["date"], y=df["p_cut"] * 100, mode="lines",
                             name="Cut", line=dict(color="#1f77b4", width=2)))
    fig.update_layout(
        title=title, yaxis_title="Probability (%)",
        yaxis=dict(range=[0, 100]), height=300,
        margin=dict(l=50, r=20, t=40, b=40),
        hovermode="x unified", legend=dict(orientation="h", y=1.08),
    )
    return fig
