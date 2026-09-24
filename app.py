"""US Market Sentiment Dashboard — SPX / Nasdaq / Russell breadth, VIX, USD,
yields, technicals, sector rotation, headline risk, economic calendar."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src import sentiment as S
from src.calendar_events import fetch_calendar
from src.data import (
    DEFENSIVE_SECTORS,
    INDICES,
    OFFENSIVE_SECTORS,
    SECTORS,
    VOL_MACRO,
    fetch_all,
    pct_change,
)
from src.news import fetch_headlines, risk_meter
from src.technicals import rsi, sma, technical_snapshot

st.set_page_config(page_title="US Market Sentiment", layout="wide")
st.title("US Market Sentiment Dashboard")
st.caption("S&P 500 · Nasdaq · Russell 2000 — volatility, macro, technicals, sectors, headlines, calendar")


@st.cache_data(ttl=900)
def load_data():
    idx = fetch_all(INDICES, period="1y")
    vm = fetch_all(VOL_MACRO, period="1y")
    sec = fetch_all(SECTORS, period="6mo")
    return idx, vm, sec


@st.cache_data(ttl=900)
def load_news():
    try:
        hs = fetch_headlines(30)
        return hs, None
    except Exception as e:
        return [], str(e)


@st.cache_data(ttl=3600)
def load_calendar():
    try:
        return fetch_calendar(), None
    except Exception as e:
        return [], str(e)


def gauge(value: float, title: str, color_ranges=True) -> go.Figure:
    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=value, title={"text": title},
        number={"suffix": ""},
        gauge={"axis": {"range": [0, 100]},
               "bar": {"color": "#1f77b4"},
               "steps": [{"range": [0, 25], "color": "#e74c3c"},
                         {"range": [25, 45], "color": "#f39c12"},
                         {"range": [45, 70], "color": "#f1c40f"},
                         {"range": [70, 100], "color": "#2ecc71"}] if color_ranges else []},
    ))
    fig.update_layout(height=280, margin=dict(t=40, b=10))
    return fig


def line_chart(df: pd.DataFrame, title: str, extra: dict | None = None) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df.index, y=df["close"], name="Close",
                            line=dict(color="#1f77b4", width=2)))
    if extra:
        for label, series in extra.items():
            fig.add_trace(go.Scatter(x=df.index, y=series, name=label,
                                     line=dict(dash="dash", width=1.2)))
    fig.update_layout(title=title, height=320, margin=dict(t=40, b=10),
                      xaxis_title="", yaxis_title="")
    return fig


idx, vm, sec = load_data()
snaps = {n: technical_snapshot(df) for n, df in idx.items() if not df.empty}

components = {
    "Trend": S.trend_score(snaps),
    "Momentum": S.momentum_score(snaps),
    "Volatility": S.volatility_score(vm["VIX"]),
    "Macro": S.macro_score(vm["DXY (USD Index)"], vm["US 10Y Yield"], vm["US 5Y Yield"]),
    "Sectors": S.sector_score(sec),
}
score, breakdown = S.composite(components)

tabs = st.tabs(["Overview", "Indices", "Volatility & Macro", "Sector Rotation",
                "News Risk", "Economic Calendar"])

# ---------------- OVERVIEW ----------------
with tabs[0]:
    c1, c2 = st.columns([1, 2])
    with c1:
        st.plotly_chart(gauge(score, "Composite Sentiment"), use_container_width=True)
        reg = S.regime(score)
        color = {"Risk-On": "green", "Neutral": "gray", "Risk-Off": "orange",
                 "Extreme Fear": "red"}[reg]
        st.markdown(f"### :{color}[{reg}]")
    with c2:
        st.subheader("What drives the score")
        rows = [{"Component": k, "Score": round(v["score"], 1),
                 "Weight": f"{int(S.WEIGHTS[k]*100)}%", "Detail": v["detail"]}
                for k, v in breakdown.items()]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        st.caption("100 = most bullish. Weights: Trend 25%, Momentum 20%, "
                   "Volatility 20%, Macro 15%, Sectors 20%.")
    st.subheader("Market snapshot")
    cols = st.columns(4)
    for (name, s), col in zip(snaps.items(), cols):
        arrow = "▲" if (s["ret_1d"] or 0) >= 0 else "▼"
        col.metric(name, f"{s['last']:,.1f}",
                   f"{arrow} {s['ret_1d']:+.2f}% today" if s["ret_1d"] is not None else "")
    vix_last = float(vm["VIX"]["close"].iloc[-1])
    dxy_last = float(vm["DXY (USD Index)"]["close"].iloc[-1])
    y10 = float(vm["US 10Y Yield"]["close"].iloc[-1])
    st.columns(3)[0].metric("VIX", f"{vix_last:.1f}")
    st.columns(3)[1].metric("DXY", f"{dxy_last:.1f}")
    st.columns(3)[2].metric("US 10Y", f"{y10:.2f}%")

# ---------------- INDICES ----------------
with tabs[1]:
    for name, df in idx.items():
        if df.empty:
            continue
        s = snaps[name]
        st.subheader(name)
        c1, c2 = st.columns([3, 2])
        with c1:
            st.plotly_chart(line_chart(
                df.tail(252), f"{name} — 1 year",
                {"SMA 50": sma(df["close"], 50).tail(252),
                 "SMA 200": sma(df["close"], 200).tail(252)}),
                use_container_width=True)
        with c2:
            def fmt(x, suffix=""):
                return "—" if x is None else f"{x:,.2f}{suffix}"
            st.dataframe(pd.DataFrame([
                {"Metric": "RSI (14)", "Value": f"{s['rsi']:.1f} ({s['rsi_state']})"},
                {"Metric": "Above SMA 50", "Value": str(s["above_sma50"])},
                {"Metric": "Above SMA 200", "Value": str(s["above_sma200"])},
                {"Metric": "Golden cross (50>200)", "Value": str(s["golden_cross"])},
                {"Metric": "MACD histogram",
                 "Value": f"{s['macd_hist']:.2f} ({'bullish' if s['macd_bullish'] else 'bearish'})"},
                {"Metric": "Off 52-week high", "Value": f"{s['off_52w_high_pct']:+.1f}%"},
                {"Metric": "1-day return", "Value": fmt(s["ret_1d"], "%")},
                {"Metric": "1-week return", "Value": fmt(s["ret_1w"], "%")},
                {"Metric": "1-month return", "Value": fmt(s["ret_1m"], "%")},
            ]), use_container_width=True, hide_index=True)

# ---------------- VOLATILITY & MACRO ----------------
with tabs[2]:
    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(line_chart(vm["VIX"].tail(252), "VIX — 1 year",
                                   {"SMA 50": sma(vm["VIX"]["close"], 50).tail(252)}),
                        use_container_width=True)
        vix = float(vm["VIX"]["close"].iloc[-1])
        st.write(f"**VIX {vix:.1f}** — " +
                 ("complacent (<15)" if vix < 15 else
                  "normal (15–20)" if vix < 20 else
                  "elevated (20–30)" if vix < 30 else "panic (>30)"))
    with c2:
        st.plotly_chart(line_chart(vm["DXY (USD Index)"].tail(252), "DXY — USD strength, 1 year",
                                   {"SMA 50": sma(vm["DXY (USD Index)"]["close"], 50).tail(252)}),
                        use_container_width=True)
    c3, c4 = st.columns(2)
    with c3:
        y10 = vm["US 10Y Yield"].tail(252)["close"]
        y5 = vm["US 5Y Yield"].tail(252)["close"]
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=y10.index, y=y10, name="10Y"))
        fig.add_trace(go.Scatter(x=y5.index, y=y5, name="5Y"))
        fig.update_layout(title="US Treasury yields — 1 year", height=320,
                          margin=dict(t=40, b=10))
        st.plotly_chart(fig, use_container_width=True)
    with c4:
        spread = (vm["US 10Y Yield"]["close"] - vm["US 5Y Yield"]["close"]).tail(252)
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=spread.index, y=spread, name="10Y − 5Y",
                                 fill="tozeroy"))
        fig.add_hline(y=0, line_dash="dash", line_color="red")
        fig.update_layout(title="Yield curve (10Y − 5Y spread) — 1 year",
                          height=320, margin=dict(t=40, b=10))
        st.plotly_chart(fig, use_container_width=True)
        last_spread = float(spread.iloc[-1])
        st.write(f"**Spread {last_spread:+.2f}pp** — " +
                 ("inverted ⚠️" if last_spread < 0 else "normal"))

# ---------------- SECTOR ROTATION ----------------
with tabs[3]:
    perf = []
    for name, df in sec.items():
        if df.empty:
            continue
        perf.append({"Sector": name, "Ticker": SECTORS[name],
                     "1M %": pct_change(df, 21), "3M %": pct_change(df, 63)})
    pdf = pd.DataFrame(perf).dropna().sort_values("1M %", ascending=False)
    c1, c2 = st.columns(2)
    with c1:
        colors = ["#2ecc71" if x >= 0 else "#e74c3c" for x in pdf["1M %"]]
        fig = go.Figure(go.Bar(x=pdf["Sector"], y=pdf["1M %"],
                               marker_color=colors, name="1M %"))
        fig.update_layout(title="S&P sector rotation — 1-month returns",
                          height=380, margin=dict(t=40, b=100))
        fig.update_xaxes(tickangle=45)
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        colors = ["#2ecc71" if x >= 0 else "#e74c3c" for x in pdf["3M %"]]
        fig = go.Figure(go.Bar(x=pdf["Sector"], y=pdf["3M %"],
                               marker_color=colors, name="3M %"))
        fig.update_layout(title="S&P sector rotation — 3-month returns",
                          height=380, margin=dict(t=40, b=100))
        fig.update_xaxes(tickangle=45)
        st.plotly_chart(fig, use_container_width=True)
    off = pdf[pdf["Sector"].isin(OFFENSIVE_SECTORS)]["1M %"].mean()
    dfn = pdf[pdf["Sector"].isin(DEFENSIVE_SECTORS)]["1M %"].mean()
    st.info(f"**Rotation read:** offensive sectors avg {off:+.1f}% vs defensive "
            f"{dfn:+.1f}% over 1M — "
            f"{'risk-on tilt' if off > dfn else 'defensive tilt'}.")
    st.dataframe(pdf.style.format({"1M %": "{:+.2f}%", "3M %": "{:+.2f}%"}),
                 use_container_width=True, hide_index=True)

# ---------------- NEWS RISK ----------------
with tabs[4]:
    headlines, err = load_news()
    if err:
        st.warning(f"News feed unavailable: {err}")
    elif headlines:
        meter, detail = risk_meter(headlines)
        c1, c2 = st.columns([1, 2])
        with c1:
            st.plotly_chart(gauge(meter, "Headline Risk"), use_container_width=True)
            st.caption(detail)
            st.caption("Keyword-based: high-risk words (crash, tariff, war…), "
                       "medium (Fed, CPI, inflation…), bullish words reduce risk.")
        with c2:
            for h in headlines:
                badge = {"high": "🔴", "medium": "🟡", "low": "⚪",
                         "bullish": "🟢"}[h["risk"]]
                st.markdown(f"{badge} **[{h['source']}]** {h['title']}  "
                            f"*{h['published']}* — {h['risk_reason']}")
    else:
        st.info("No headlines right now.")

# ---------------- ECONOMIC CALENDAR ----------------
with tabs[5]:
    events, err = load_calendar()
    if err:
        st.warning(f"Calendar feed unavailable: {err}")
    elif events:
        upcoming = [e for e in events if e["upcoming"]]
        st.subheader(f"Upcoming US events ({len(upcoming)})")
        rows = [{"Date": e["date"], "Time": e["time_et"], "Event": e["event"],
                 "Impact": e["impact"], "Forecast": e["forecast"],
                 "Previous": e["previous"]} for e in upcoming]
        cdf = pd.DataFrame(rows)
        def highlight(row):
            color = {"High": "#e74c3c", "Medium": "#f39c12"}.get(row["Impact"], "")
            return [f"background-color: {color}33" if color else ""] * len(row)
        st.dataframe(cdf.style.apply(highlight, axis=1),
                     use_container_width=True, hide_index=True)
        st.caption("Source: ForexFactory weekly calendar feed.")
    else:
        st.info("No events found.")

st.divider()
st.caption("Data: Yahoo Finance (prices), Google News RSS (headlines), ForexFactory "
           "(calendar). Educational — not investment advice. Refreshes every 15 min.")
