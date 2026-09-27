# US Market Sentiment Dashboard

A live sentiment dashboard for US equities: **S&P 500, Nasdaq, Russell 2000** —
volatility (VIX), USD strength (DXY), Treasury yields, technicals, S&P sector
rotation, headline risk, and the US economic calendar.

## How it works

A composite **0–100 sentiment score** (100 = most bullish) blends seven components
(the headline number is the **3-day average** of the daily score, so one volatile
session can't swing it):

| Component | Weight | What it measures |
|---|---|---|
| Trend | 20% | Share of indices above 50-day avg (70%) + RSP/SPY breadth vs 50d (30%) |
| Momentum | 15% | Average RSI(14), mapped 30→0 / 50→50 / 70→100 |
| Volatility | 15% | 1y percentiles (inverted) of VIX / VVIX / SKEW / MOVE + VX futures curve shape; −15 on a 5d VIX spike >20% |
| Credit | 10% | HYG/LQD 5y percentile + ICE BofA HY OAS percentile (inverted) |
| Macro | 15% | DXY vs 50d (continuous) + 10Y–2Y spread + Sahm rule distance from the 0.50 trigger |
| Sectors | 15% | Offensive–defensive 1M spread, z-scored vs its trailing 6M volatility |
| Positioning | 10% | Inverted Fear Context + Risk-Off Rotation gauges (no longer decorative) |

Every sleeve degrades to neutral 50 when its data is missing, and weights are
re-normalized over what's available — a failed feed can't tank the composite.

Regimes: ≥70 Risk-On · 45–70 Neutral · 25–45 Risk-Off · <25 Extreme Fear.

Headline risk is a keyword-based 0–100 gauge over the latest market headlines
(high-risk: crash, tariff, war…; medium: Fed, CPI, inflation…; bullish words
reduce it). It is intentionally simple — a transparent heuristic, not an NLP model.

## Data sources (mostly free, no API keys)

- Prices/technicals/options: Yahoo Finance (`yfinance`), CBOE delayed-quotes API (GEX)
- Headlines: Google News RSS + CNBC RSS
- Economic calendar: ForexFactory weekly JSON feed
- Earnings: Nasdaq public calendar API
- Macro tab: FRED API — needs a free `FRED_API_KEY` (Streamlit secret or env var)
- Fed Watch: CME ZQ futures (Yahoo) + FRED (effective rate, 10Y yield)

10 tabs: Overview · Indices · Volatility · Macro · Sector Rotation ·
News Risk · Economic Calendar · Earnings · GEX · Fed Watch.

Volatility tab: VIX, VVIX (vol-of-vol), SKEW (tail-risk pricing), the VIX
9D/30D/3M term structure (Yahoo), VIX futures curve (CBOE daily settlement
CSVs, free), 30-day realized vs implied vol, and the HYG/LQD credit fear
gauge. DXY lives on the Macro tab (Yahoo), under "Dollar Strength".

Macro tab sections: Inflation (CPI, PCE, core PCE, 5Y breakeven), Fed Funds
Rate (fed funds, 2Y/10Y yields, 10Y–2Y spread history, yield curve), Labour
Market (unemployment, claims, payrolls, Sahm rule), GDP, Dollar Strength.

Data caches refresh when you hit ↻ Refresh (top of the Overview tab).

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Educational — not investment advice.
