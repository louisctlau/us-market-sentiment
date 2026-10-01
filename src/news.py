"""Market news headlines + headline-risk classification.

Sources: Google News RSS + CNBC RSS (free, no API key).

Risk engine v2 (2026-09-28): negation-aware, verb-aware, net-scored keywords
blended with VADER sentiment.
  - Negation: a keyword hit is flipped/dampened when negators or reversal
    verbs ("no", "not", "avoids", "eases", "fades"...) appear within ±3 words.
    "Recession fears ease" and "avoids default" no longer score as risk.
  - Verb-aware nouns: "deal", "tariff", "rate cut", "rate hike", "yield" are
    directionless alone, so neighboring verbs decide the sign —
    "deal signed" is bullish, "deal collapses" is high risk, bare "deal"
    scores 0; "yields surge" is risk (+0.8), "yields ease" is relief (-0.4).
    A verb consumed by this branch is not re-counted as a negator, so
    "yields ease" stays bullish instead of flipping back to risk.
  - Net scoring: every keyword hit contributes its signed weight instead of
    first-match-wins, so "stocks rally as recession fears fade" nets out
    instead of flagging high risk on "recession" alone.
  - Event words ("fed", "cpi", "payrolls", "fomc"...) are neutral context and
    score 0 by themselves; only directional words move the gauge.
  - VADER compound sentiment is blended in at 0.6 weight (negative sentiment
    adds to risk) to catch what the keyword lists miss.
  - Headline-risk gauge (risk_meter) concentrates on the 3 riskiest
    headlines — Tasty-style weighted top-3 (0.55/0.30/0.15) — not all
    headlines: most feed items are filler, and an all-headline average
    structurally caps the gauge when the market-moving stories run hot.
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
    "https://www.cnbc.com/id/10000664/device/rss/rss.html",  # Finance
]

# Directional keywords: fixed signed weights (positive = risk, negative = bullish).
KEYWORD_WEIGHTS: dict[str, float] = {
    # high risk (+1.0)
    "recession": 1.0, "crash": 1.0, "plunge": 1.0, "collapse": 1.0,
    "emergency": 1.0, "war": 1.0, "missile": 1.0, "sanction": 1.0,
    "default": 1.0, "bankrupt": 1.0, "layoff": 1.0, "downgrade": 1.0,
    "selloff": 1.0, "sell-off": 1.0, "panic": 1.0, "fear": 1.0,
    "warning": 1.0, "probe": 1.0, "indict": 1.0, "tumbles": 1.0,
    # medium risk (+0.5)
    "inflation": 0.5, "deficit": 0.5, "debt ceiling": 0.5, "shutdown": 0.5,
    "earnings miss": 0.5, "guidance cut": 0.5, "lawsuit": 0.5,
    "antitrust": 0.5, "bond selloff": 0.5, "yields surge": 0.5,
    # bullish (-0.6)
    "record high": -0.6, "all-time high": -0.6, "rally": -0.6, "surge": -0.6,
    "beats": -0.6, "beat estimates": -0.6, "raises guidance": -0.6,
    "stimulus": -0.6, "merger": -0.6,
}

# Neutral event/context words: calendar context, not risk — score 0 alone.
EVENT_WORDS = {
    "fed", "federal reserve", "warsh", "fomc", "cpi",
    "jobs report", "payrolls", "gdp",
}

# Directionless nouns scored by neighboring verbs:
# phrase -> (positive_verbs, negative_verbs, default_w, pos_w, neg_w)
VERB_AWARE: dict[str, tuple[frozenset, frozenset, float, float, float]] = {
    "deal": (
        frozenset({"reached", "reach", "reaches", "signed", "sign", "struck",
                   "strike", "announced", "announce", "closes", "close",
                   "agreed", "agree", "sealed", "seal", "inked", "ink",
                   "clinched", "clinch"}),
        frozenset({"collapses", "collapse", "collapsed", "fails", "fail",
                   "failed", "falls", "fall", "fell", "blocked", "block",
                   "scrapped", "scrap", "stalls", "stall", "stalled",
                   "threatens", "threaten", "unravels", "unravel",
                   "breaks", "break", "dead", "doomed"}),
        0.0, -0.6, 1.0,
    ),
    "tariff": (
        frozenset({"paused", "pause", "delayed", "delay", "eased", "ease",
                   "lifted", "lift", "deal", "cut", "reduced", "relief",
                   "lower", "lowers", "lowered", "slash", "slashes",
                   "slashed"}),
        frozenset({"impose", "imposes", "imposed", "hits", "hit",
                   "threatens", "threaten", "escalates", "escalate",
                   "war", "hike", "hiked", "raised", "raise"}),
        0.5, -0.4, 1.0,
    ),
    "rate cut": (
        frozenset(),
        frozenset({"emergency", "surprise", "unexpected", "shock"}),
        -0.3, -0.3, 1.0,
    ),
    "rate hike": (
        frozenset(),
        frozenset({"surprise", "unexpected", "aggressive", "shock"}),
        0.5, 0.5, 1.0,
    ),
    # Bond yields move markets on their own: rising verbs are risk,
    # easing verbs are relief. Bare "yield" in a headline is mild risk.
    "yield": (
        frozenset({"ease", "eases", "eased", "easing",
                   "fall", "falls", "falling", "fell",
                   "drop", "drops", "dropping", "dropped",
                   "retreat", "retreats", "retreating",
                   "cool", "cools", "cooled", "cooling",
                   "decline", "declines", "declining"}),
        frozenset({"surge", "surges", "surging",
                   "jump", "jumps", "jumping",
                   "climb", "climbs", "climbing",
                   "rise", "rises", "rising", "rose",
                   "spike", "spikes", "spiking",
                   "hit", "hits", "hitting",
                   "soar", "soars", "soaring"}),
        0.3, -0.4, 0.8,
    ),
}

# Negators / reversal verbs: flip a nearby keyword hit (checked ±3 words).
NEGATORS = frozenset({
    "no", "not", "never", "none", "without", "hardly", "scarcely",
    "avoid", "avoids", "avoided", "avert", "averts", "averted",
    "ease", "eases", "eased", "easing",
    "recede", "recedes", "receded", "receding",
    "fade", "fades", "faded", "fading",
    "cool", "cools", "cooled", "cooling",
    "dodge", "dodges", "dodged", "defuse", "defused",
    "allay", "allayed", "relief", "respite", "spared", "spare",
})

VADER_WEIGHT = 0.6
_ANALYZER = None


def _analyzer():
    global _ANALYZER
    if _ANALYZER is None:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
        _ANALYZER = SentimentIntensityAnalyzer()
    return _ANALYZER


_WORD_RE = re.compile(r"[a-z]+(?:'[a-z]+)?")


def _tokens(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower())


def _weq(tok: str, word: str) -> bool:
    # Whole-word match with light plural tolerance both directions
    # ("tariffs" ~ "tariff", "raises" ~ "raise").
    # Token-level matching means "war" never flags "forward"/"reward".
    if tok == word:
        return True
    if len(word) > 2 and tok.endswith("s") and tok[:-1] == word:
        return True
    return len(tok) > 2 and word.endswith("s") and word[:-1] == tok


def _find_spans(toks: list[str], phrase: list[str]):
    n = len(phrase)
    for i in range(len(toks) - n + 1):
        if all(_weq(toks[i + k], phrase[k]) for k in range(n)):
            yield (i, i + n)


def _negated(toks: list[str], i: int, j: int,
             skip: frozenset = frozenset()) -> bool:
    window = toks[max(0, i - 3): j + 3]
    return any((_weq(t, n) or "n't" in t) and t not in skip
               for t in window for n in NEGATORS)


def _apply_negation(w: float, toks: list[str], i: int, j: int,
                    skip: frozenset = frozenset()) -> tuple[float, bool]:
    """Negated hit: flip sign at half magnitude (mild, not full reversal).

    A negated zero-weight noun ("no deal") becomes mild risk (+0.3).

    `skip` holds verbs already consumed by the verb-aware branch: a verb
    like "ease" doubles as a negator, and without the skip "yields ease"
    would flip from bullish back to risk.
    """
    if _negated(toks, i, j, skip):
        return (0.3, True) if w == 0 else (-0.5 * w, True)
    return w, False


def _score_hits(title: str) -> tuple[list[tuple[str, float, str]], float]:
    """Return ([(phrase, weight, note)], vader_compound) for a headline."""
    toks = _tokens(title)
    hits: list[tuple[str, float, str]] = []

    for phrase, (pos_v, neg_v, default, pos_w, neg_w) in VERB_AWARE.items():
        for (i, j) in _find_spans(toks, _tokens(phrase)):
            window = toks[max(0, i - 4): j + 4]
            neg_hit = {t for t in window if t in neg_v}
            pos_hit = {t for t in window if t in pos_v}
            if neg_hit:
                w, note, skip = neg_w, "verb", neg_hit
            elif pos_hit:
                w, note, skip = pos_w, "verb", pos_hit
            else:
                w, note, skip = default, "", frozenset()
            w, neg = _apply_negation(w, toks, i, j, skip)
            if neg:
                note = (note + "+neg" if note else "neg")
            if w != 0:
                hits.append((phrase, w, note))
            break  # first span per phrase only

    for phrase, w0 in KEYWORD_WEIGHTS.items():
        for (i, j) in _find_spans(toks, _tokens(phrase)):
            w, neg = _apply_negation(w0, toks, i, j)
            hits.append((phrase, w, "neg" if neg else ""))
            break  # first span per phrase only

    vader_c = _analyzer().polarity_scores(title)["compound"]
    return hits, vader_c


def classify_risk(title: str) -> tuple[str, str]:
    """Net-scored risk class + compact reason string."""
    hits, vader_c = _score_hits(title)
    kw_net = sum(w for _, w, _ in hits)
    # VADER compound is sentiment (-1 bad .. +1 good); risk is the opposite
    # direction, so negative sentiment ADDS to the risk score.
    net = kw_net - VADER_WEIGHT * vader_c

    if net >= 0.6:
        risk = "high"
    elif net >= 0.2:
        risk = "medium"
    elif net <= -0.35:
        risk = "bullish"
    else:
        risk = "low"

    parts = []
    for phrase, w, note in hits:
        s = f"'{phrase}' {w:+.1f}"
        if note:
            s += f"({note})"
        parts.append(s)
    parts.append(f"VADER {vader_c:+.2f}")
    if not hits and abs(vader_c) < 0.05:
        reason = "no keywords, VADER neutral"
    else:
        reason = f"net {net:+.1f}: " + ", ".join(parts)
    return risk, reason


def risk_meter(headlines: list[dict]) -> tuple[float, str]:
    """0-100 headline-risk gauge (100 = maximum risk).

    Top-3 concentration, adapted from TastyDayTraders' News Risk:
    gauge = round(0.55 × riskiest + 0.30 × 2nd + 0.15 × 3rd), capped at
    100. Concentrating on the top 3 lets the market-moving stories drive
    the gauge instead of being diluted by filler headlines. With fewer
    than 3 headlines the weights renormalize (a single headline reads
    at face value). The 20-pt severity bands are unchanged.
    """
    if not headlines:
        return 0.0, "no headlines"
    weights = {"high": 1.0, "medium": 0.5, "low": 0.1, "bullish": -0.3}
    ranked = sorted(
        (weights.get(h.get("risk", "low"), 0.1) for h in headlines),
        reverse=True,
    )
    base_w = (0.55, 0.30, 0.15)
    k = min(3, len(ranked))
    wsum = sum(base_w[:k])
    meter = round(max(0.0, min(100.0,
                               sum(base_w[i] / wsum * ranked[i] for i in range(k)) * 100)))
    n_high = sum(1 for h in headlines if h.get("risk") == "high")
    return meter, f"{n_high} high-risk of {len(headlines)} headlines (weighted top-3)"


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
