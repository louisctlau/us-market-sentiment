"""Daily snapshot job for the US Market Sentiment dashboard.

Runs on the VM (cron: usms-daily-snapshot, weekdays ~17:30 ET) — NOT on
Streamlit Cloud, whose filesystem is ephemeral. Computes today's composite
+ sleeves, the News Risk gauge and SPY positioning from live sources
(reusing the app's own modules, mirroring app.py's build_components),
appends one record to data/history.json (idempotent per date), maintains
the earnings implied-move scorecard, then pushes via gh_push_usms.py.

FRED inputs (DGS2 / UNRATE / BAMLH0A0HYM2) come from the keyless
fredgraph CSV endpoint — the same trick src/fedwatch.py uses — because
no FRED_API_KEY exists in this environment. If a fredgraph fetch fails,
that sleeve input is simply absent (the scorers degrade to neutral),
exactly as in the app.

Stdout contract for the cron agent:
  SNAPSHOT ...   one summary line (always)
  ALERT: ...     one line per triggered alert (Louis is messaged only
                 when at least one ALERT line prints)
  NO_ALERTS      when nothing triggered
Exit code 0 on success (including "a feed failed, record is partial");
1 only when no record could be written or the push failed.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from src import fedwatch as F  # noqa: E402
from src import gex as G  # noqa: E402
from src import sentiment_v2 as S  # noqa: E402
from src.data import (  # noqa: E402
    CROSS_ASSETS, INDICES, SECTORS, VOL_EXTRA, VOL_MACRO, fetch_all,
    fetch_history,
)
from src.earnings import fetch_earnings  # noqa: E402
from src.earnings_iv import implied_move, realized_move  # noqa: E402
from src.news import fetch_headlines, risk_meter  # noqa: E402
from src.technicals import technical_snapshot  # noqa: E402
from src.vix_futures import fetch_vix_futures_curve  # noqa: E402

ET = ZoneInfo("America/Toronto")
HISTORY_PATH = os.path.join(ROOT, "data", "history.json")
PUSH_SCRIPT = os.path.expanduser("~/workspace/gh_push_usms.py")
CHAIN_TICKERS = {"NVDA", "AMD", "MU", "AAPL", "META", "GOOG", "GOOGL"}
FREDGRAPH = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={}"


def load_score_fred() -> dict:
    """FRED series the score needs, via keyless fredgraph CSVs (mirrors
    app.py's load_score_fred, which uses the API client on Cloud)."""
    out = {}
    for sid in ("DGS2", "UNRATE", "BAMLH0A0HYM2"):
        try:
            df = F._fetch_fred_series(FREDGRAPH.format(sid))
            s = df[sid].replace(".", np.nan)
            s = pd.to_numeric(s, errors="coerce").dropna()
            s = s[s.index >= "2020-01-01"]
            if not s.empty:
                out[sid] = pd.DataFrame({"value": s})
        except Exception:
            continue
    return out


def _cut(df, n):
    if n and df is not None and not df.empty and len(df) > n + 20:
        return df.iloc[:-n]
    return df


class Snapshot:
    """Mirrors app.py's build_components (keep the two in sync)."""

    def __init__(self):
        self.idx = fetch_all(INDICES, period="1y")
        self.vm = fetch_all(VOL_MACRO, period="1y")
        self.vx = fetch_all(VOL_EXTRA, period="1y")
        self.sec = fetch_all(SECTORS, period="6mo")
        self.br = fetch_all({"RSP (Equal-Weight S&P)": "RSP"}, period="1y")
        self.cr5y = fetch_all(
            {k: CROSS_ASSETS[k] for k in ("High-Yield (HYG)", "Inv-Grade (LQD)")},
            period="5y")
        self.sfred = load_score_fred()
        try:
            self.vx_fut, _ = fetch_vix_futures_curve()
        except Exception:
            self.vx_fut = None

    def components(self, n=0, gex=None, fed=None, news_meter=None):
        idx_n = {k: _cut(v, n) for k, v in self.idx.items()}
        vm_n = {k: _cut(v, n) for k, v in self.vm.items()}
        vx_n = {k: _cut(v, n) for k, v in self.vx.items()}
        sec_n = {k: _cut(v, n) for k, v in self.sec.items()}
        snaps = {k: technical_snapshot(v) for k, v in idx_n.items()
                 if not v.empty}
        rsp = _cut(self.br["RSP (Equal-Weight S&P)"], n)
        spx = idx_n["S&P 500"]
        breadth = ((rsp["close"] / spx["close"]).dropna()
                   if not rsp.empty and not spx.empty else None)
        hyg_n = _cut(self.cr5y["High-Yield (HYG)"], n)
        lqd_n = _cut(self.cr5y["Inv-Grade (LQD)"], n)
        oas = (_cut(self.sfred["BAMLH0A0HYM2"], n)["value"]
               if "BAMLH0A0HYM2" in self.sfred else None)
        dgs2 = (_cut(self.sfred["DGS2"], n)["value"]
                if "DGS2" in self.sfred else None)
        unrate = (_cut(self.sfred["UNRATE"], n)["value"]
                  if "UNRATE" in self.sfred else None)
        return {
            "Trend": S.trend_score(snaps, breadth),
            "Momentum": S.momentum_score(snaps),
            "Volatility": S.volatility_score(
                vm_n["VIX"], vx_n.get("VVIX"), vx_n.get("SKEW"),
                vx_n.get("MOVE"), self.vx_fut if n == 0 else None),
            "Credit": S.credit_score(hyg_n, lqd_n, oas),
            "Macro": S.macro_score(vm_n["DXY (USD Index)"],
                                   vm_n["US 10Y Yield"], dgs2, unrate,
                                   fed if n == 0 else None),
            "Sectors": S.sector_score(sec_n),
            "Positioning": S.positioning_score(gex if n == 0 else None),
            "News": S.news_score(news_meter if n == 0 else None),
        }


def canonical(sym: str) -> str:
    return "GOOG" if sym in ("GOOG", "GOOGL") else sym


def maintain_earnings(data: dict, today: str) -> list[str]:
    """Capture pre-print implied moves for chain-name prints still ahead,
    and fill realized moves for prints whose reaction session has closed.
    Implied is captured ONLY while the print is still in the future —
    never backfilled after the fact."""
    notes = []
    entries = {(e["ticker"], e["date"]): e for e in data.get("earnings", [])}
    try:
        rows = fetch_earnings(days=8, past_days=3)
    except Exception:
        rows = []
    for r in rows:
        sym = (r.get("symbol") or "").upper()
        if sym not in CHAIN_TICKERS:
            continue
        tick, d = canonical(sym), r.get("date", "")
        if not d:
            continue
        key = (tick, d)
        e = entries.get(key)
        if d > today:
            if e is None:
                e = {"ticker": tick, "date": d, "time": r.get("time") or "",
                     "implied_pct": None, "implied_asof": None,
                     "implied_source": None, "pre_close": None,
                     "post_close": None, "realized_pct": None}
                entries[key] = e
                data.setdefault("earnings", []).append(e)
            if e.get("implied_pct") is None:
                iv = implied_move(tick, d, r.get("time") or "")
                if iv:
                    e["implied_pct"] = iv["implied_pct"]
                    e["implied_asof"] = today
                    e["implied_source"] = (f"live CBOE chain {today} "
                                           f"(straddle expiry {iv['expiry']})")
                    notes.append(f"implied captured {tick} {d}: "
                                 f"±{iv['implied_pct']:.1f}%")
        if e is not None and e.get("realized_pct") is None and d <= today:
            rm = realized_move(tick, d, e.get("time") or r.get("time") or "")
            if rm:
                e.update(rm)
                notes.append(f"realized filled {tick} {d}: "
                             f"{rm['realized_pct']:.1f}%")
    return notes


def main() -> int:
    today = datetime.now(ET).date().isoformat()
    snap = Snapshot()

    try:
        headlines = fetch_headlines(30)
        meter, _detail = risk_meter(headlines) if headlines else (None, "")
    except Exception:
        meter = None
    try:
        spy_gex = G.gex_by_strike("SPY")
    except Exception:
        spy_gex = None
    try:
        fed = S.fed_stance(F.fedwatch()["meetings"])
    except Exception:
        fed = None

    comps = snap.components(0, gex=spy_gex, fed=fed, news_meter=meter)
    score_today, _ = S.composite(comps)
    past = [S.composite(snap.components(n))[0] for n in (1, 2)]
    headline3d = float(np.mean([score_today, *past]))

    spy_df = fetch_history("SPY", period="5d")
    spy_close = (float(spy_df["close"].iloc[-1])
                 if spy_df is not None and not spy_df.empty else None)

    record = {
        "date": today,
        "composite": round(float(score_today), 2),
        "composite_headline": round(headline3d, 2),
        "sleeves": {k: round(float(v[0]), 2) for k, v in comps.items()},
        "news_risk": (round(float(meter), 1) if meter is not None else None),
        "spy_close": (round(spy_close, 2) if spy_close else None),
        "spy_spot": (round(float(spy_gex["spot"]), 2) if spy_gex else None),
        "spy_zero_gamma": (round(float(spy_gex["zero_gamma"]), 2)
                           if spy_gex and spy_gex.get("zero_gamma") else None),
        "spy_net_gex_m": (round(float(spy_gex["total_net"]), 1)
                          if spy_gex else None),
        "src": "snapshot",
    }

    try:
        with open(HISTORY_PATH) as f:
            data = json.load(f)
    except Exception:
        data = {"records": [], "earnings": []}
    data.setdefault("records", [])
    data.setdefault("earnings", [])
    prev = None
    recs = sorted((r for r in data["records"] if r.get("date")),
                  key=lambda r: r["date"])
    for r in recs:
        if r["date"] < today:
            prev = r
    data["records"] = [r for r in data["records"] if r.get("date") != today]
    data["records"].append(record)
    data["records"].sort(key=lambda r: r["date"])

    notes = maintain_earnings(data, today)

    tmp = HISTORY_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, separators=(",", ":"))
    os.replace(tmp, HISTORY_PATH)

    alerts = []
    c = record["composite"]
    if c >= 70:
        alerts.append(f"Composite {c:.1f} — Risk-On extreme (≥ 70).")
    elif c <= 30:
        alerts.append(f"Composite {c:.1f} — Extreme Fear zone (≤ 30).")
    if record["news_risk"] is not None and record["news_risk"] >= 80:
        alerts.append(f"News Risk {record['news_risk']:.0f} — Severe (≥ 80).")
    if (prev and prev.get("spy_zero_gamma") and record["spy_zero_gamma"]
            and prev.get("spy_close") and record["spy_close"]):
        # Use each record's own SPY close vs its zero-gamma level.
        was_above = prev["spy_close"] > prev["spy_zero_gamma"]
        is_above = record["spy_close"] > record["spy_zero_gamma"]
        if was_above != is_above:
            side = "above" if is_above else "below"
            alerts.append(
                f"SPY crossed {side} its γflip — spot "
                f"{record['spy_close']:,.0f} vs γflip "
                f"{record['spy_zero_gamma']:,.0f} (was "
                f"{'above' if was_above else 'below'} on {prev['date']}).")

    print(f"SNAPSHOT date={today} composite={c:.1f} "
          f"headline3d={headline3d:.1f} "
          f"news_risk={record['news_risk']} spy_close={record['spy_close']} "
          f"zero_gamma={record['spy_zero_gamma']} "
          f"net_gex_m={record['spy_net_gex_m']}")
    for n in notes:
        print(f"NOTE {n}")
    for a in alerts:
        print(f"ALERT: {a}")
    if not alerts:
        print("NO_ALERTS")

    r = subprocess.run([sys.executable, PUSH_SCRIPT,
                        f"Daily snapshot {today}"],
                       cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        print("PUSH FAILED:", (r.stdout + r.stderr)[-800:])
        return 1
    print("PUSHED", r.stdout.strip().splitlines()[-1] if r.stdout else "")
    return 0


if __name__ == "__main__":
    sys.exit(main())
