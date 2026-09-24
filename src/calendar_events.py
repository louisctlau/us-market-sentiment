"""US economic calendar (FOMC, CPI, NFP, PCE, GDP...).

Source: FairEconomy / ForexFactory free JSON feed (no API key).
"""
from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone

FEED_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"


def fetch_calendar(country: str = "USD") -> list[dict]:
    req = urllib.request.Request(FEED_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        events = json.loads(resp.read())
    now = datetime.now(timezone.utc)
    out = []
    for e in events:
        if e.get("country") != country:
            continue
        try:
            dt = datetime.fromisoformat(e["date"])
        except Exception:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        out.append({
            "datetime_utc": dt,
            "date": dt.strftime("%a %b %d"),
            "time_et": dt.astimezone().strftime("%H:%M"),
            "event": e.get("title", ""),
            "impact": e.get("impact") or "Low",
            "forecast": e.get("forecast") or "—",
            "previous": e.get("previous") or "—",
            "upcoming": dt >= now,
        })
    out.sort(key=lambda x: x["datetime_utc"])
    return out
