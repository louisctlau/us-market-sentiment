"""Options-implied earnings move from the live CBOE delayed chain.

Implied move = ATM straddle price / spot for the first expiry bracketing
the earnings print (after-hours print -> first expiry AFTER the date;
pre-market print -> first expiry ON/AFTER the date). Same CBOE delayed-
quotes endpoint the GEX tab uses (src/gex.py) — no GEX math is touched.

Honesty rule: this is only ever computed BEFORE a print (live in the app
for upcoming prints; by scripts/daily_snapshot.py for the scorecard
record). Past implied moves are never reconstructed in-app.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from urllib.request import Request, urlopen

from .gex import CBOE_URL, UA


def _parse_symbol(sym: str) -> tuple[str, str, float]:
    """'META261023C00695000' -> (expiry 'YYYY-MM-DD', 'C'/'P', strike)."""
    expiry = f"20{sym[-15:-13]}-{sym[-13:-11]}-{sym[-11:-9]}"
    side = sym[-9]
    strike = int(sym[-8:]) / 1000.0
    return expiry, side, strike


def _mid(o: dict) -> float | None:
    bid = float(o.get("bid") or 0)
    ask = float(o.get("ask") or 0)
    if bid > 0 and ask > 0:
        return (bid + ask) / 2
    last = float(o.get("last_trade_price") or 0)
    return last if last > 0 else None


def fetch_chain(ticker: str) -> dict:
    req = Request(CBOE_URL.format(ticker), headers=UA)
    with urlopen(req, timeout=25) as resp:
        payload = json.loads(resp.read().decode())
    data = payload["data"]
    return {"spot": float(data["current_price"]),
            "options": data.get("options") or []}


def implied_move(ticker: str, earnings_date: str,
                 time_hint: str = "") -> dict | None:
    """{implied_pct, expiry, strike, spot, straddle} or None.

    earnings_date is ISO 'YYYY-MM-DD'. time_hint is the Nasdaq calendar's
    session label ('Pre-market' / 'After-hours' / '' when unknown)."""
    try:
        chain = fetch_chain(ticker)
    except Exception:
        return None
    spot = chain["spot"]
    if not spot or not chain["options"]:
        return None
    by_exp: dict[str, dict[float, dict[str, dict]]] = {}
    for o in chain["options"]:
        try:
            exp, side, strike = _parse_symbol(o["option"])
        except Exception:
            continue
        by_exp.setdefault(exp, {}).setdefault(strike, {})[side] = o
    expiries = sorted(by_exp)
    if time_hint == "Pre-market":
        cands = [e for e in expiries if e >= earnings_date]
    else:  # after-hours or unknown: reaction is the NEXT session
        cands = [e for e in expiries if e > earnings_date]
    if not cands:
        cands = [e for e in expiries if e >= earnings_date]
    if not cands:
        return None
    expiry = cands[0]
    strikes = by_exp[expiry]
    atm = min(strikes, key=lambda k: abs(k - spot))
    legs = strikes[atm]
    if "C" not in legs or "P" not in legs:
        return None
    cm, pm = _mid(legs["C"]), _mid(legs["P"])
    if cm is None or pm is None:
        return None
    straddle = cm + pm
    return {"implied_pct": round(straddle / spot * 100, 2),
            "expiry": expiry, "strike": atm, "spot": spot,
            "straddle": round(straddle, 2)}


def realized_move(ticker: str, earnings_date: str,
                  time_hint: str = "") -> dict | None:
    """Realized reaction move from daily closes once the reaction session
    has closed: after-hours/unknown -> print-date close to next session;
    pre-market -> prior session to print-date close."""
    import pandas as pd
    import yfinance as yf
    d0 = date.fromisoformat(earnings_date)
    try:
        df = yf.download(ticker, start=(d0 - timedelta(days=10)).isoformat(),
                         end=(d0 + timedelta(days=10)).isoformat(),
                         progress=False, auto_adjust=True)
    except Exception:
        return None
    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    closes = {str(i.date()): float(v) for i, v in df["Close"].items()}
    days = sorted(closes)
    if time_hint == "Pre-market":
        prior = [d for d in days if d < earnings_date]
        if earnings_date not in closes or not prior:
            return None
        pre, post = closes[prior[-1]], closes[earnings_date]
    else:
        after = [d for d in days if d > earnings_date]
        if earnings_date not in closes or not after:
            return None
        pre, post = closes[earnings_date], closes[after[0]]
    if not pre:
        return None
    return {"pre_close": round(pre, 2), "post_close": round(post, 2),
            "realized_pct": round(abs(post / pre - 1) * 100, 2)}
