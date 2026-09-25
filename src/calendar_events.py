"""US economic calendar — rolling 7-day window (FOMC, CPI, NFP, PCE, GDP...).

Source: FairEconomy / ForexFactory free JSON feed (no API key).
The feed covers the current calendar week, so near week's end fewer than
7 days may be available.
"""
from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

FEED_URLS = [
    "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
    "https://nfs.faireconomy.media/ff_calendar_nextweek.json",  # 404 when unpublished; skipped
]
ET = ZoneInfo("America/Toronto")


def _fetch_feed(url: str) -> list:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())


def fetch_calendar(country: str = "USD", days: int = 7) -> list[dict]:
    events = []
    for url in FEED_URLS:
        try:
            events.extend(_fetch_feed(url))
        except Exception:
            continue  # next-week file isn't always published; this week suffices
    if not events:
        raise RuntimeError("Calendar feeds unreachable (this week + next week).")
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=days)
    out = []
    seen = set()
    for e in events:
        if e.get("country") != country:
            continue
        try:
            dt = datetime.fromisoformat(e["date"])
        except Exception:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if not (now <= dt <= end):
            continue
        key = (dt.isoformat(), e.get("title"))
        if key in seen:
            continue
        seen.add(key)
        local = dt.astimezone(ET)
        out.append({
            "datetime_utc": dt,
            "date": local.strftime("%a %b %d"),
            "time_et": local.strftime("%H:%M"),
            "event": e.get("title", ""),
            "impact": e.get("impact") or "Low",
            "forecast": e.get("forecast") or "—",
            "previous": e.get("previous") or "—",
            "upcoming": True,
        })
    out.sort(key=lambda x: x["datetime_utc"])
    return out
