"""Market news headlines + keyword-based headline-risk classification.

Source: Google News RSS (free, no API key).
"""
from __future__ import annotations

import re
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

RSS_URL = (
    "https://news.google.com/rss/search"
    "?q=stock%20market%20S%26P%20500%20OR%20Nasdaq%20OR%20Wall%20Street"
    "&hl=en-US&gl=US&ceid=US%3Aen"
)

HIGH_RISK = [
    "recession", "crash", "plunge", "collapse", "emergency", "war", "missile",
    "tariff", "sanction", "default", "bankrupt", "layoff", "downgrade",
    "selloff", "sell-off", "panic", "fear", "warning", "probe", "indict",
    "tumbles",
]
MEDIUM_RISK = [
    "inflation", "cpi", "fed", "powell", "rate hike", "rate cut", "fomc",
    "jobs report", "payrolls", "gdp", "deficit", "debt ceiling", "shutdown",
    "earnings miss", "guidance cut", "lawsuit", "antitrust", "selloff",
    "bond selloff", "yields surge",
]
BULLISH = [
    "record high", "all-time high", "rally", "surge", "beats", "beat estimates",
    "raises guidance", "stimulus", "deal", "merger",
]


def classify_risk(title: str) -> tuple[str, str]:
    t = title.lower()
    for kw in HIGH_RISK:
        if kw in t:
            return "high", f"keyword: '{kw}'"
    for kw in MEDIUM_RISK:
        if kw in t:
            return "medium", f"keyword: '{kw}'"
    for kw in BULLISH:
        if kw in t:
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


def fetch_headlines(limit: int = 30) -> list[dict]:
    req = urllib.request.Request(RSS_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        root = ET.fromstring(resp.read())
    items = root.find("channel").findall("item")[:limit]
    out = []
    for it in items:
        title = _clean(it.findtext("title") or "")
        src = it.find("source")
        try:
            pub = parsedate_to_datetime(it.findtext("pubDate")).strftime("%b %d, %H:%M ET")
        except Exception:
            pub = it.findtext("pubDate") or ""
        risk, reason = classify_risk(title)
        out.append({
            "title": title,
            "source": src.text if src is not None else "",
            "published": pub,
            "url": it.findtext("link") or "",
            "risk": risk,
            "risk_reason": reason,
        })
    return out
