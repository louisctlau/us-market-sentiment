"""Daily history store for the dashboard (data/history.json).

Streamlit Cloud's filesystem is ephemeral, so the durable daily record
lives in the repo: scripts/daily_snapshot.py (VM cron, weekdays ~17:30 ET)
appends one record per trading day and pushes the file; the app only reads.

Record shape (every field optional except date/composite — readers use
.get() with defaults so older/sparser records never crash the UI):
    {date, composite, composite_headline, sleeves {name: score},
     news_risk, spy_close, spy_zero_gamma, spy_net_gex_m, src}

Seed: the 2015 → 2026-09-29 block comes from the v2 backtest
(scores_v2.csv; bands 70/45/30 were calibrated on it). In seed records
Positioning and News are neutral 50 (no live GEX/headline history exists
for those days) and news_risk / zero-gamma are null. Live snapshots
(src="snapshot") accrue from 2026-10-22.

Earnings scorecard entries live under "earnings":
    {ticker, date, time, implied_pct, implied_asof, implied_source,
     pre_close, post_close, realized_pct}
Implied moves are captured from the live CBOE chain BEFORE the print
(or, for META 2026-10-21, reconstructed from the daily chain archive) —
never backfilled after the fact. Realized = |post_close/pre_close - 1|
where pre/post bracket the reaction session (after-hours print: close on
the print date -> next session's close; pre-market: prior close -> print
date close).
"""
from __future__ import annotations

import json
import os
from datetime import date, timedelta

_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "data", "history.json")

SLEEVES = ("Trend", "Momentum", "Volatility", "Credit",
           "Macro", "Sectors", "Positioning", "News")


def load_history(path: str | None = None) -> dict:
    """Full history payload; empty structure when the file is missing/bad."""
    try:
        with open(path or _PATH) as f:
            data = json.load(f)
    except Exception:
        return {"records": [], "earnings": []}
    if not isinstance(data, dict):
        return {"records": [], "earnings": []}
    data.setdefault("records", [])
    data.setdefault("earnings", [])
    return data


def records(data: dict | None = None) -> list[dict]:
    """Daily records sorted by date (oldest first)."""
    data = data if data is not None else load_history()
    recs = [r for r in data.get("records", []) if r.get("date")]
    return sorted(recs, key=lambda r: r["date"])


def latest_record(data: dict | None = None,
                  before: str | None = None) -> dict | None:
    """Most recent record (optionally strictly before an ISO date)."""
    recs = records(data)
    if before:
        recs = [r for r in recs if r["date"] < before]
    return recs[-1] if recs else None


def percentile_of(value: float, recs: list[dict], days: int,
                  today: date | None = None) -> tuple[float | None, int]:
    """Percentile (0-100) of `value` among records in the trailing `days`
    calendar window, and the sample size. None when too few records."""
    today = today or date.today()
    cut = (today - timedelta(days=days)).isoformat()
    vals = [r["composite"] for r in recs
            if r["date"] >= cut and r.get("composite") is not None]
    if len(vals) < 20:
        return None, len(vals)
    pct = sum(1 for v in vals if v <= value) / len(vals) * 100
    return pct, len(vals)


def extremes(recs: list[dict], high: float = 70.0, low: float = 30.0,
             limit: int = 60) -> list[dict]:
    """Extreme days (composite >= high or <= low), newest first, each with
    the S&P's subsequent 20-trading-day return in % where it can be
    honestly computed: 20 recorded sessions later AND that session within
    32 calendar days (guards the seed/snapshot seam gap). Pending else."""
    out = []
    closes = [r.get("spy_close") for r in recs]
    for i, r in enumerate(recs):
        c = r.get("composite")
        if c is None or not (c >= high or c <= low):
            continue
        fwd = None
        if i + 20 < len(recs) and closes[i] and closes[i + 20]:
            d0 = date.fromisoformat(r["date"])
            d1 = date.fromisoformat(recs[i + 20]["date"])
            if (d1 - d0).days <= 32:
                fwd = (closes[i + 20] / closes[i] - 1) * 100
        out.append({"date": r["date"], "composite": c,
                    "spy_close": closes[i], "fwd20_pct": fwd,
                    "src": r.get("src", "")})
    return list(reversed(out))[:limit]


def news_series(recs: list[dict], days: int = 30) -> list[dict]:
    """Records carrying a News Risk gauge, most recent `days` of them."""
    have = [r for r in recs if r.get("news_risk") is not None]
    return have[-days:]


def earnings_entries(data: dict | None = None) -> list[dict]:
    data = data if data is not None else load_history()
    return sorted(data.get("earnings", []),
                  key=lambda e: (e.get("date", ""), e.get("ticker", "")))
