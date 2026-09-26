"""Market news headlines + keyword-based headline-risk classification.

Sources: Google News RSS + CNBC RSS (free, no API key).
"""
from __future__ import annotations

import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

ET_TZ = ZoneInfo("America/Toronto")

RSS_URL = (
    "https://news.google.com/rss/search"
    "?q=stock%20market%20S%26P%20500%20OR%20Nasdaq%20OR%20Wall%20Street"
    "&hl=en-US&gl=US&ceid=US%3Aen"
)
CNBC_FEEDS = [
    "https://www.cnbc.com/id/100003114/device/rss/rss.html",  # US Top News
    "https://www.cnbc.com/id/10000664/device/rss/rss.html",   # Finance
]

HIGH_RISK = [
    "recession", "crash", "plunge", "collapse", "emergency", "war", "missile",
    "tariff", "sanction", "default", "bankrupt", "layoff", "downgrade",
    "selloff", "sell-off", "panic", "fear", "warning", "probe", "indict",
    "tumbles",
]
MEDIUM_RISK = [
    "inflation", "cpi", "fed", "federal reserve", "warsh", "rate hike", "rate cut",
    "fomc", "jobs report", "payrolls", "gdp", "deficit", "debt ceiling",
    "shutdown", "earnings miss", "guidance cut", "lawsuit", "antitrust",
    "selloff", "bond selloff", "yields surge",
]
BULLISH = [
    "record high", "all-time high", "rally", "surge", "beats", "beat estimates",
    "raises guidance", "stimulus", "deal", "merger",
]

# Word-boundary matching: "war" must not flag "forward"/"reward"/"software".
def _kw_res(words: list[str]) -> list[tuple[str, "re.Pattern[str]"]]:
    return [(w, re.compile(r"\b" + re.escape(w) + r"\b")) for w in words]


_HIGH_RE = _kw_res(HIGH_RISK)
_MEDIUM_RE = _kw_res(MEDIUM_RISK)
_BULLISH_RE = _kw_res(BULLISH)


def classify_risk(title: str) -> tuple[str, str]:
    t = title.lower()
    for kw, rx in _HIGH_RE:
        if rx.search(t):
            return "high", f"keyword: '{kw}'"
    for kw, rx in _MEDIUM_RE:
        if rx.search(t):
            return "medium", f"keyword: '{kw}'"
    for kw, rx in _BULLISH_RE:
        if rx.search(t):
            return "bullish", f"keyword: '{kw}'"
    return "low", "no risk keywords"


def risk_meter(headlines: list[dict]) -> tuple[float, str]:
    """0-100 headline-risk gauge (100 = maximum risk)."""
    if not headlines:
        return 0.0, "no headlines"
    weights = {"high": 1.0, "medium": 0.5, "low": 0.1, "bullish": -0.3}
    score = sum(weights.get(h.get("risk", "low"), 0.1) for h in headlines)
    meter = max(0.0, min(100.0, score / len(headlines) * 100))
    n_high = sum(1 for h in headlines if h.get("risk") == "high")
    return meter, f"{n_high} high-risk of {len(headlines)} headlines"


def _clean(title: str) -> str:
    # Google News titles end with " - Source"; source is separate, strip it.
    return re.sub(r"\s+-\s+[^-]+$", "", title).strip()


def _fetch_rss(url: str, default_source: str = "") -> list[dict]:
    """Raw items from one RSS feed: title, source, url, parsed dt, raw pubDate."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        root = ET.fromstring(resp.read())
    channel = root.find("channel")
    if channel is None:
        return []
    out = []
    for it in channel.findall("item"):
        title = _clean(it.findtext("title") or "")
        if not title:
            continue
        src = it.find("source")
        source = src.text if src is not None and src.text else default_source
        raw = it.findtext("pubDate") or ""
        try:
            dt = parsedate_to_datetime(raw)
        except Exception:
            dt = None
        out.append({"title": title, "source": source, "url": it.findtext("link") or "",
                    "dt": dt, "raw": raw})
    return out


def _fmt_pub(dt: datetime | None, raw: str) -> str:
    if dt is None:
        return raw
    try:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(ET_TZ).strftime("%b %d, %H:%M ET")
    except Exception:
        return raw


def fetch_headlines(limit: int = 30) -> list[dict]:
    items = _fetch_rss(RSS_URL)
    for feed in CNBC_FEEDS:
        try:
            items.extend(_fetch_rss(feed, default_source="CNBC"))
        except Exception:
            continue  # one dead feed shouldn't kill the tab
    # Dedupe by normalized title (Google News often already includes CNBC).
    seen: dict[str, dict] = {}
    for it in items:
        key = re.sub(r"\W+", "", it["title"].lower())
        if key not in seen:
            seen[key] = it
    deduped = list(seen.values())
    deduped.sort(
        key=lambda h: h["dt"] if h["dt"] is not None else datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    out = []
    for it in deduped[:limit]:
        risk, reason = classify_risk(it["title"])
        out.append({
            "title": it["title"],
            "source": it["source"],
            "published": _fmt_pub(it["dt"], it["raw"]),
            "url": it["url"],
            "risk": risk,
            "risk_reason": reason,
        })
    return out
