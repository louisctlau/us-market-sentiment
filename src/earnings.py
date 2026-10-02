"""Earnings calendar — yesterday's reported actuals + next N days, via Nasdaq's
public calendar API (no key)."""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

_ET = ZoneInfo("America/Toronto")

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept": "application/json",
}


def _parse_mcap(s: str) -> float | None:
    """'$3.12T' / '$812.4B' / '$1,246,465,280' -> billions USD. None if missing."""
    if not s or s.strip() in {"--", "N/A"}:
        return None
    s = s.strip()
    m = re.match(r"\$([\d,.]+)\s*([TBMK])$", s)
    if m:
        val = float(m.group(1).replace(",", ""))
        mult = {"T": 1000.0, "B": 1.0, "M": 0.001, "K": 0.000001}[m.group(2)]
        return val * mult
    m = re.match(r"\$([\d,]+)$", s)  # raw dollars, e.g. $1,246,465,280
    if m:
        return float(m.group(1).replace(",", "")) / 1e9
    return None


def _clean_time(s: str) -> str:
    s = (s or "").strip()
    return (s.replace("time-", "").replace("-", " ")
            .replace("pre market", "Pre-market")
            .replace("after hours", "After-hours")
            .replace("not supplied", "—") or "—")


def _parse_surprise(s: str) -> float | None:
    """'11.63' / '-4.2' -> float percent. None if missing."""
    s = (s or "").strip()
    if s in {"", "--", "N/A"}:
        return None
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


def _clean_actual(s: str) -> str:
    s = (s or "").strip()
    return "" if s in {"--", "N/A"} else s


def fetch_earnings(days: int = 7, past_days: int = 1,
                   min_mcap_b: float = 5.0) -> list[dict]:
    """Earnings from `past_days` days ago through the next `days` days,
    filtered to companies >= min_mcap_b $B.

    Returns rows: date, time, symbol, name, mcap_b, eps_forecast,
    eps_actual ("" if not yet reported), surprise (float %, None if n/a).
    Sorted by date, then market cap desc.
    """
    rows: list[dict] = []
    for i in range(-past_days, days):
        d = datetime.now(_ET).date() + timedelta(days=i)  # ET, not server-local
        ds = d.strftime("%Y-%m-%d")
        payload = None
        # The Nasdaq API intermittently blanks a date; retry so one hiccup
        # doesn't wipe the whole "Reported yesterday" section.
        for _ in range(3):
            try:
                r = requests.get(
                    "https://api.nasdaq.com/api/calendar/earnings",
                    params={"date": ds}, headers=_HEADERS, timeout=15)
                if r.status_code == 200:
                    payload = r.json().get("data") or {}
                    break
            except Exception:
                continue
        if not payload:
            continue
        for row in payload.get("rows") or []:
            mcap_b = _parse_mcap(row.get("marketCap", ""))
            if mcap_b is None or mcap_b < min_mcap_b:
                continue
            rows.append({
                "date": ds,
                "time": _clean_time(row.get("time")),
                "symbol": row.get("symbol", ""),
                "name": row.get("name", ""),
                "mcap_b": round(mcap_b, 1),
                "eps_forecast": (row.get("epsForecast") or "").strip(),
                "eps_actual": _clean_actual(row.get("eps")),
                "surprise": _parse_surprise(row.get("surprise")),
            })
    rows.sort(key=lambda r: (r["date"], -r["mcap_b"]))
    return rows
