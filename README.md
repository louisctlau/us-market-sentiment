# US Market Sentiment Dashboard

A live sentiment dashboard for US equities: **S&P 500, Nasdaq, Russell 2000** —
volatility (VIX), USD strength (DXY), Treasury yields, technicals, S&P sector
rotation, headline risk, and the US economic calendar.

## How it works

A composite **0–100 sentiment score** (100 = most bullish) blends five components:

| Component | Weight | What it measures |
|---|---|---|
| Trend | 25% | Share of indices above their 50-day average |
| Momentum | 20% | Average RSI(14), mapped 30→0 / 50→50 / 70→100 |
| Volatility | 20% | VIX level inverted (12→100, 40→0), minus spike penalty |
| Macro | 15% | DXY vs 50-day + 10Y–5Y yield curve shape |
| Sectors | 20% | Offensive vs defensive 1-month return spread |

Regimes: ≥70 Risk-On · 45–70 Neutral · 25–45 Risk-Off · <25 Extreme Fear.

Headline risk is a keyword-based 0–100 gauge over the latest market headlines
(high-risk: crash, tariff, war…; medium: Fed, CPI, inflation…; bullish words
reduce it). It is intentionally simple — a transparent heuristic, not an NLP model.

## Data sources (all free, no API keys)

- Prices/technicals: Yahoo Finance (`yfinance`)
- Headlines: Google News RSS
- Economic calendar: ForexFactory weekly JSON feed

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Educational — not investment advice.
