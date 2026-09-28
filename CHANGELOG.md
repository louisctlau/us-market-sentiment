## 2026-09-28 — Cumulative view counter (Upstash Redis)
- The footer view counter no longer resets on redeploy: it now increments an atomic counter in Upstash Redis (free tier), falling back to the file counter only when Redis isn't configured.
- Setup needed: add `[upstash_redis]` rest_url + rest_token to Streamlit secrets (or env vars locally). Until then the footer keeps the previous ephemeral behavior.
- Note: counts from before this change are unrecoverable — the old file counter reset with every deploy, so the durable total starts fresh when Redis is connected.

## 2026-09-28 — News Risk engine v2 (negation/verb-aware + VADER)
- Headline classifier rebuilt: negation handling ("recession fears ease", "avoids default" no longer flag as risk), verb-aware nouns ("deal signed" bullish vs "deal collapses" high risk; bare "deal" neutral), net scoring across all keyword hits instead of first-match-wins, and Fed/CPI/payrolls treated as neutral context.
- VADER sentiment blended in (negative sentiment adds to risk) to catch what keywords miss. Tested 24 tricky headlines: 22/24 correct vs 12/24 for the old engine.

## 2026-09-27 — Sentiment score rebuilt (7 components)
- Score now blends seven components: Trend 20%, Momentum 15%, Volatility 15%, Credit 10% (new), Macro 15%, Sectors 15%, Positioning 10% (new).
- Headline is a 3-day moving average; the daily value shows in the detail table.
- New inputs: MOVE index (^MOVE, bond-market volatility), RSP equal-weight breadth, ICE BofA High-Yield OAS (FRED: BAMLH0A0HYM2).
- Volatility is percentile-based (VIX, VVIX, SKEW, MOVE, futures curve) with a 5-day spike penalty; macro uses continuous DXY distance-from-average and 10Y–2Y spread; sectors normalized by trailing volatility; positioning folds in the Fear Context and Risk-Off Rotation gauges.
- Any missing input falls back to neutral-50 instead of silently skewing the score.

## 2026-09-27 — Volatility tab rework
- Tab renamed from "Volatility & Macro" to "Volatility"; added VVIX, SKEW, VIX 9D and VIX 3M series with regime reads.
- New charts: VIX/VVIX/SKEW 1-year, VIX 9D/30D/3M term structure, CBOE VX futures curve (daily settlements), 30-day realized vs implied vol, HYG/LQD credit fear gauge.
- DXY chart moved to the Economy tab; Yahoo 10Y/5Y yield charts removed (yields live on Economy via FRED).

## 2026-09-26 — Reliability diagnostics
- One failed Yahoo ticker no longer kills the whole dashboard — failed tickers return empty and score neutral-50 with an "unavailable" label.
- FRED fetches retry 3× with backoff; `curl-cffi` added to requirements; dead code removed.

## 2026-09-25 — FRED integration + Economy tab
- New Economy tab: Fed funds, unemployment, CPI, PCE, jobless claims, payrolls, GDP, 2Y/10Y yields — metric cards, labor-market read, 5-year charts. Requires a free FRED API key.
- Yield curve chart (now vs 1-month-ago vs 1-year-ago) plus 10Y–2Y spread.

## 2026-09-25 — News Risk upgrades
- Headlines now merge Google News RSS with two CNBC feeds, deduped and sorted by recency; per-headline publish timestamps and a "fetched {time} ({age})" caption.
- Severity legend in 5 bands (0–20 Calm … 80–100 Severe); gauge colors fixed to match (green→red).

## 2026-09-25 — Economic calendar: rolling 7 days
- Calendar now shows the next 7 days (was: rest of the week); event times properly converted to ET.

## 2026-09-25 — GEX convention finalized
- Net GEX uses the standard convention (calls +, puts −; dealers long calls / short puts): (call OI × call γ − put OI × put γ) × 100 × spot.
