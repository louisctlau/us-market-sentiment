## 2026-10-01 — Reporting periods on calendar + catalysts
- Economic calendar events now show the reference period in brackets —
  e.g. "CPI (Sep)", "GDP (Q3)" — derived from each indicator's standard
  reporting lag (the Nasdaq feed doesn't carry it). Monthly releases report
  the prior month, several Census reports (construction spending, factory
  orders, full trade balance, business inventories, wholesale trade) two
  months back, quarterly releases the prior quarter, current-month surveys
  the release month, and weekly labour data the reference week. Verified
  against this week's actual releases (e.g. the Oct 1 construction spending
  and Oct 2 factory orders both cover August). Events with no numeric
  figure (speeches, auctions, weekly energy stats) get no label.
- Sidebar "Upcoming catalysts" now shows the reference month too:
  CPI (Sep), PCE (Sep), Non-farm payrolls (Sep).

## 2026-10-01 — News Risk: revert to top-10 gauge
- Reverted the Tasty-style weighted top-3 gauge after Louis found the
  100/Severe reading didn't reflect reality: three high-risk headlines
  pinned the gauge at maximum under the 0.55/0.30/0.15 weighting, while the
  broader top-10 average read the same news flow at a saner level. The
  top-10 average is back as the gauge aggregation; the v3 verb-aware yield
  classifier is unchanged.

## 2026-10-01 — News Risk: top-3 weighted gauge (Tasty-style)
- The Headline Risk gauge now concentrates on the 3 riskiest headlines with
  TastyDayTraders' weighting — 0.55 × riskiest + 0.30 × 2nd + 0.15 × 3rd,
  rounded and capped at 100 — replacing the top-10 average. Only their
  aggregation was adopted: their per-event scoring is built for an
  official-posts-only feed (White House/Fed/SEC, manually curated, no time
  decay) and doesn't map onto 30 automated general headlines.
- The 20-point severity bands are unchanged (their bands are calibrated to
  official-post event scores, not headline scores). With fewer than 3
  headlines the weights renormalize so a single headline reads at face value.
- Expect a jumpier gauge than before — top-3 of 30 daily headlines is
  noisier than Tasty's top-3 of a few official posts. That concentration is
  the point: the market-moving stories drive the number.

## 2026-10-01 — News Risk: yield-aware + top-10 gauge
- "Yield" is now verb-aware like "deal"/"tariff": "yields surge/climb" scores
  as risk (+0.8), "yields ease/fall" as relief (-0.4). Previously the engine
  only knew the rigid phrase "yields surge", so "surging Treasury yields" and
  "yields climb to a 24-year high" scored low even as the 10Y hit 5.33%.
- The Headline Risk gauge now averages the 10 riskiest headlines instead of
  all 30: most feed items are filler, and the all-headline average
  structurally capped the gauge on news-sensitive days.
- Drive-by fix: a verb consumed by the verb-aware branch (e.g. "ease") is no
  longer re-counted as a negator, so "yields ease" stays bullish instead of
  flipping back to mild risk. Same latent issue fixed for "tariffs eased".

## 2026-09-30 — Catalyst sidebar: release times
- Each upcoming catalyst now shows its release time: 8:30 AM ET for PCE,
  payrolls, and CPI (BLS/BEA release convention); 2:00 PM ET for the FOMC
  decision (statement; Chair press conference 2:30 PM).

## 2026-09-29 — PCE joins the catalyst sidebar
- The "Upcoming catalysts" panel now tracks PCE (Personal Income and Outlays)
  alongside payrolls, CPI, and the FOMC decision — the Fed's 2% target is
  defined in PCE terms, so it has the better claim than a single inflation
  gauge.

## 2026-09-29 — Composite sentiment: backtested, restructured
- Backtested the composite daily over 2015–2026 (2,952 trading days): median
  58.7, std 13.1. The score printed below 30 at the Mar 2020, Dec 2018, and
  Aug 2024 panics, so Extreme Fear is now <30 (was <25). Honest finding: no
  component predicts forward returns — the composite describes the current
  regime, and is contrarian at extremes (sub-25 readings averaged +2.2% over
  the next 20 sessions).
- Positioning is now genuine dealer positioning from the GEX tab (SPY
  zero-gamma distance + net GEX sign). The old version was a VIX/rotation
  remix that correlated 0.79 with Momentum and double-counted Volatility
  and Sectors.
- News Risk is now an 8th composite sleeve (5%, taken from Momentum's old
  15% — Momentum correlated 0.77 with Trend). Macro adds a Fed stance sleeve
  (nearest-FOMC cut vs hike odds).
- Volatility spike penalty is now continuous (+10%/5d → 0, +50%/5d → −20)
  instead of a −15 cliff at +20%. Credit percentiles use a matched 3y window
  (OAS history is truncated). Sector z-score has a 1pp vol floor so calm
  markets can't pin it at 0/100 on noise.
- Overview adds a past-month composite sparkline under the gauge.

## 2026-09-29 — Economic calendar: actuals with green/red highlights
- The calendar now runs on Nasdaq's economic calendar feed (no key), showing an
  Actual column next to Forecast and Previous for every event.
- Released events stay on the calendar for the whole week instead of
  disappearing once transpired (window is now Monday → today+7 days).
- Actuals are highlighted green when better than forecast (or previous, when no
  forecast is published) and red when worse. The favourable direction is parsed
  from Nasdaq's own "higher/lower than expected" read, with a keyword fallback
  (e.g. lower unemployment / lower inflation = favourable).
- Impact is now tiered by keyword (High/Medium/Low) since Nasdaq doesn't
  publish impact ratings.

## 2026-09-28 — Sidebar catalyst countdown
- The sidebar now shows an "Upcoming catalysts" panel: countdowns to the next
  FOMC decision, CPI, and non-farm payrolls (BLS dates verified; FOMC mirrors
  the Fed Watch schedule), with the Changelog link pinned at the bottom.

## 2026-09-28 — Market status caption
- The subtitle under the dashboard title now shows live NYSE session status
  (🟢 Market open · 🟡 Pre-market / After-hours · 🔴 Market closed), with
  regular, early-close, weekend, and holiday hours handled.

## 2026-09-28 — Navigation reverted to tabs
- Rolled back the sidebar-menu experiment (and the synced top tab bar): the app
  is tab-based again, exactly as before, with the Changelog link under the title.

## 2026-09-28 — Streamlined calendar filters
- The six per-column filter widgets are now one search box (matches date, time,
  event, forecast, previous) plus an Impact selector, in a single row.

## 2026-09-28 — Keep-alive ping
- `.github/workflows/keep_alive.yml`: pings the app every 2 days at 5am ET so Streamlit Community Cloud never sleeps it (7-day inactivity threshold).

## 2026-09-28 — Economic calendar filters
- Every column now has a filter: Date / Time / Impact multiselects plus Event / Forecast / Previous text search, with a "Showing X of N events" count.

## 2026-09-28 — View counter removed
- The footer view counter is gone (per Louis's call): fixed footer bar, `src/views.py`, and `data/view_count.txt` all removed. The Upstash setup is no longer needed.
- Changelog moved to a native `st.page_link` under the dashboard title (visible on every tab) — this also fixes the old raw `/changelog` href, which never routed on Streamlit Cloud. The changelog page got a matching native "← Back to dashboard" link.

## 2026-09-28 — Cumulative view counter (Upstash Redis)
- The footer view counter no longer resets on redeploy: it now increments an atomic counter in Upstash Redis (free tier), falling back to the file counter only when Redis isn't configured.
- Setup needed: add `[upstash_redis]` rest_url + rest_token to Streamlit secrets (or env vars locally). Until then the footer keeps the previous ephemeral behavior.
- Note: counts from before this change are unrecoverable — the old file counter reset with every deploy, so the durable total starts fresh when Redis is connected.
- Seeded at 80 (Louis's best guess of total views to date) via `seed_views`: applied once with SETNX, never overwrites the live count.

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
