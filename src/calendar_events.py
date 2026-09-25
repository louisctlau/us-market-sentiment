"""US economic calendar — rolling 7-day window.

Source: MarketWatch economic calendar
(https://www.marketwatch.com/economy-politics/calendar),
parsed from the page's embedded JSON (no API key).
MarketWatch does not publish impact ratings or forecasts, so impact is
approximated from the event category and forecast/previous show as "—".
"""
from __future__ import annotations

import json
import re
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

CALENDAR_URL = "https://www.marketwatch.com/economy-politics/calendar"
ET = ZoneInfo("America/Toronto")
UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
              "image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}

HIGH_CATS = {"central banks", "employment", "inflation", "gdp growth",
             "interest rate"}
MEDIUM_CATS = {"labour market", "economic activity", "housing market",
               "consumer sentiment", "confidence index", "foreign trade",
               "balance", "government", "bonds", "credit"}


def _fetch_days() -> list[dict]:
    req = urllib.request.Request(CALENDAR_URL, headers=UA)
    with urllib.request.urlopen(req, timeout=25) as resp:
        html = resp.read().decode("utf-8", errors="replace")
    m = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        html, re.S)
    if not m:
        raise RuntimeError("MarketWatch calendar data not found in page.")
    try:
        return json.loads(m.group(1))["props"]["pageProps"]["calendarData"]
    except (KeyError, TypeError, ValueError):
        raise RuntimeError("MarketWatch calendar data changed shape.")


def _parse_dt(e: dict) -> datetime | None:
    gmt = (e.get("dateGMT") or "").strip()
    try:
        if "T" in gmt:
            dt = datetime.fromisoformat(gmt.replace("Z", "+00:00"))
        else:
            d = datetime.strptime(gmt, "%Y-%m-%d").date()
            dt = datetime(d.year, d.month, d.day, 12, 0,
                          tzinfo=ET).astimezone(timezone.utc)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _impact(cats: list) -> str:
    s = {str(c).lower() for c in cats or []}
    if s & HIGH_CATS:
        return "High"
    if s & MEDIUM_CATS:
        return "Medium"
    return "Low"


def fetch_calendar(days: int = 7) -> list[dict]:
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=days)
    out = []
    seen = set()
    for day in _fetch_days():
        for e in day.get("events") or []:
            dt = _parse_dt(e)
            if dt is None or not (now <= dt <= end):
                continue
            title = (e.get("report") or e.get("description") or "").strip()
            key = (dt.isoformat(), title)
            if key in seen:
                continue
            seen.add(key)
            local = dt.astimezone(ET)
            out.append({
                "datetime_utc": dt,
                "date": local.strftime("%a %b %d"),
                "time_et": (e.get("time") or "").strip() or "TBA",
                "event": title,
                "impact": _impact(e.get("categoryIds")),
                "forecast": "—",
                "previous": "—",
                "upcoming": True,
            })
    out.sort(key=lambda x: x["datetime_utc"])
    return out
