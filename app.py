"""US Market Sentiment Dashboard — SPX / Nasdaq / Russell breadth, VIX, USD,
yields, technicals, sector rotation, headline risk, economic calendar."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from src import commentary as C
from src import fedwatch as F
from src import fred as FR
from src import gex as G
from src import sentiment as S
from src.calendar_events import fetch_calendar
from src.data import (
    CROSS_ASSETS,
    DEFENSIVE_SECTORS,
    INDICES,
    OFFENSIVE_SECTORS,
    SECTORS,
    VOL_MACRO,
    fetch_all,
    pct_change,
)
from src.earnings import fetch_earnings
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
    xa = fetch_all(CROSS_ASSETS, period="1y")
    return idx, vm, sec, xa, datetime.now(timezone.utc)


@st.cache_data(ttl=900)
def load_news():
    try:
        hs = fetch_headlines(30)
        return hs, None, datetime.now(timezone.utc)
    except Exception as e:
        return [], str(e), None


@st.cache_data(ttl=3600)
def load_calendar():
    try:
        return fetch_calendar(), None
    except Exception as e:
        return [], str(e)


@st.cache_data(ttl=3600)
def load_gex(etf: str):
    # Failures raise instead of being returned: cache_data never caches
    # exceptions, so a stale error string can't persist across deploys.
    return G.gex_by_strike(etf)


@st.cache_data(ttl=900)
def load_fedwatch():
    # Failures raise instead of being returned (see load_gex note above).
    return F.fedwatch()


@st.cache_data(ttl=3600)
def load_fedwatch_history():
    # Failures raise instead of being returned (see load_gex note above).
    return F.fedwatch_history(90)


@st.cache_data(ttl=900)
def load_ten_year():
    # Optional context metric: None on failure, never raises, so the
    # Fed Watch tab keeps working if DGS10 is unavailable.
    return F.fetch_ten_year()


@st.cache_data(ttl=3600)
def load_earnings():
    try:
        return fetch_earnings(), None
    except Exception as e:
        return [], str(e)


@st.cache_data(ttl=21600)
def load_economy():
    # Failures raise instead of being returned (see load_gex note above).
    return {sid: FR.get_series(sid, observation_start="2020-01-01")
            for sid in FR.ECON_SERIES}


@st.cache_data(ttl=3600)
def load_yield_curve():
    # One dead series shouldn't kill the curve — skip failures.
    out = {}
    for label, (sid, _yrs) in FR.YIELD_CURVE_SERIES.items():
        try:
            out[label] = FR.get_series(sid, observation_start="2024-01-01")
        except Exception:
            continue
    return out


def gauge(value: float, title: str, color_ranges=True, invert=False,
          steps: list | None = None) -> go.Figure:
    default_steps = [{"range": [0, 25], "color": "#e74c3c"},
                     {"range": [25, 45], "color": "#f39c12"},
                     {"range": [45, 70], "color": "#f1c40f"},
                     {"range": [70, 100], "color": "#2ecc71"}]
    if invert:  # high = bad (fear, risk-off)
        default_steps = [{"range": [0, 25], "color": "#2ecc71"},
                         {"range": [25, 45], "color": "#f1c40f"},
                         {"range": [45, 70], "color": "#f39c12"},
                         {"range": [70, 100], "color": "#e74c3c"}]
    steps = default_steps if steps is None else steps
    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=value, title={"text": title},
        number={"suffix": ""},
        gauge={"axis": {"range": [0, 100]},
               "bar": {"color": "#1f77b4"},
               "steps": steps if color_ranges else []},
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


idx, vm, sec, xa, data_ts = load_data()
failed = sorted({name for group in (idx, vm, sec, xa)
                 for name, df in group.items() if df.empty})
if failed:
    st.warning(f"Data unavailable for: {', '.join(failed)} — "
               "affected widgets show neutral values.")
col_ts, col_btn = st.columns([5, 1])
with col_ts:
    st.caption(f"Data refreshed {data_ts.astimezone(ZoneInfo('America/Toronto')):%b %d, %Y · %I:%M %p ET} · use ↻ Refresh to reload")
with col_btn:
    if st.button("↻ Refresh", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
snaps = {n: technical_snapshot(df) for n, df in idx.items() if not df.empty}

components = {
    "Trend": S.trend_score(snaps),
    "Momentum": S.momentum_score(snaps),
    "Volatility": S.volatility_score(vm["VIX"]),
    "Macro": S.macro_score(vm["DXY (USD Index)"], vm["US 10Y Yield"], vm["US 5Y Yield"]),
    "Sectors": S.sector_score(sec),
}
score, breakdown = S.composite(components)

fear, fear_detail = S.fear_context(vm["VIX"], idx["S&P 500"])
rot, rot_detail = S.risk_off_rotation(sec, xa["20Y+ Treasury (TLT)"])

headlines, news_err, news_ts = load_news()
headline_meter, headline_detail = risk_meter(headlines) if headlines else (0.0, "no headlines")

tabs = st.tabs(["Overview", "Indices", "Volatility & Macro", "Economy",
                "Sector Rotation", "News Risk", "Economic Calendar", "Earnings",
                "GEX", "Fed Watch"])

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

    st.subheader("Market commentary")
    ctx = {
        "score": score, "regime": S.regime(score), "breakdown": breakdown,
        "fear": fear, "rot": rot, "rot_detail": rot_detail,
        "headline_meter": headline_meter,
        "vix": vm["VIX"], "y10": vm["US 10Y Yield"], "dxy": vm["DXY (USD Index)"],
        "snaps": snaps,
    }
    st.info(C.market_commentary(ctx))
    st.markdown("**Macro in context — where each stands vs the past year:**")
    st.markdown("- " + C.vix_commentary(vm["VIX"]))
    st.markdown("- " + C.dxy_commentary(vm["DXY (USD Index)"]))
    st.markdown("- " + C.yield_commentary(vm["US 10Y Yield"], vm["US 5Y Yield"]))

    st.subheader("Market snapshot")
    cols = st.columns(4)
    for (name, s), col in zip(snaps.items(), cols):
        arrow = "▲" if (s["ret_1d"] or 0) >= 0 else "▼"
        col.metric(name, f"{s['last']:,.1f}",
                   f"{arrow} {s['ret_1d']:+.2f}% today" if s["ret_1d"] is not None else "")
    mcols = st.columns(3)
    for col, (label, df, fmt) in zip(
            mcols,
            [("VIX", vm["VIX"], "{:.1f}"),
             ("DXY", vm["DXY (USD Index)"], "{:.1f}"),
             ("US 10Y", vm["US 10Y Yield"], "{:.2f}%")]):
        with col:
            if df.empty:
                st.metric(label, "n/a")
                continue
            last = float(df["close"].iloc[-1])
            st.metric(label, fmt.format(last))
            ma50 = df["close"].rolling(50).mean()
            fig = line_chart(df, f"{label} — past year",
                             extra={"50-day avg": ma50})
            fig.update_layout(height=240, margin=dict(t=35, b=10))
            st.plotly_chart(fig, use_container_width=True)

    st.subheader("Fear context & rotation")
    f1, f2 = st.columns(2)
    with f1:
        st.plotly_chart(gauge(fear, "Fear Context (VIX/SPX)", invert=True),
                        use_container_width=True)
        st.caption(f"{fear_detail} — market volatility, not news.")
    with f2:
        st.plotly_chart(gauge(rot, "Risk-Off Rotation", invert=True),
                        use_container_width=True)
        st.caption(f"{rot_detail} — growth → safe-haven flow, 1M.")

    st.subheader("Cross-asset context")
    xa_cols = st.columns(5)
    xa_defs = [("VIX", vm["VIX"], "{:.1f}"),
               ("DXY", vm["DXY (USD Index)"], "{:.1f}"),
               ("WTI Crude", xa["WTI Crude Oil"], "${:.1f}"),
               ("Gold", xa["Gold"], "${:.0f}"),
               ("US 10Y", vm["US 10Y Yield"], "{:.2f}%")]
    for col, (label, df, fmt) in zip(xa_cols, xa_defs):
        if df.empty:
            col.metric(label, "n/a")
            continue
        last = float(df["close"].iloc[-1])
        r1m = pct_change(df, 21)
        col.metric(label, fmt.format(last),
                   f"{r1m:+.1f}% 1M" if r1m is not None else "")

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

# ---------------- ECONOMY (FRED API) ----------------
with tabs[3]:
    st.subheader("US Economy — FRED")
    st.caption("Official macro series via the FRED API "
               "(Federal Reserve Bank of St. Louis).")
    try:
        econ = load_economy()
        econ_err = None
    except FR.FredNoKey:
        econ, econ_err = None, "nokey"
    except Exception as e:
        econ, econ_err = None, str(e)
    if econ_err == "nokey":
        st.info("The Economy tab needs a free FRED API key — get one at "
                "https://fred.stlouisfed.org/docs/api/api_key.html and add it as "
                "the `FRED_API_KEY` secret (Streamlit Cloud: app Settings → Secrets; "
                "local runs: `.streamlit/secrets.toml`). Then press ↻ Refresh.")
    elif econ_err:
        st.warning(f"FRED data unavailable: {econ_err}")
    else:
        def econ_display(sid: str, df: pd.DataFrame) -> pd.Series:
            v = df["value"]
            if sid in ("CPIAUCSL", "PCEPI"):
                return v.pct_change(12) * 100
            if sid == "ICSA":
                return v.rolling(4).mean()
            if sid == "PAYEMS":
                return v.diff()
            if sid == "GDP":
                return (v / v.shift(1)) ** 4 * 100 - 100
            return v

        fmts = {"FEDFUNDS": "{:.2f}%", "UNRATE": "{:.1f}%",
                "CPIAUCSL": "{:+.1f}%", "PCEPI": "{:+.1f}%",
                "ICSA": "{:,.0f}", "PAYEMS": "{:+,.0f}k",
                "GDP": "{:+.1f}%", "DGS2": "{:.2f}%", "DGS10": "{:.2f}%"}
        heads, asofs = {}, {}
        for sid in FR.ECON_SERIES:
            heads[sid], asofs[sid] = FR.headline_value(sid, econ[sid])
        cards = list(FR.ECON_SERIES)
        for row in range(3):
            cols = st.columns(3)
            for col, sid in zip(cols, cards[row * 3:(row + 1) * 3]):
                val = heads[sid]
                col.metric(FR.ECON_SERIES[sid],
                           fmts[sid].format(val) if val is not None else "n/a",
                           help=f"As of {asofs[sid]}")

        unrate = econ["UNRATE"]["value"]
        unrate_yoy = unrate.iloc[-1] - unrate.iloc[-13] if len(unrate) > 13 else None
        pay3m = econ["PAYEMS"]["value"].diff().tail(3).mean()
        labor_bits = []
        if unrate_yoy is not None:
            labor_bits.append(
                f"unemployment {unrate.iloc[-1]:.1f}% "
                f"({'up' if unrate_yoy > 0 else 'down'} {abs(unrate_yoy):.1f}pp "
                "vs a year ago)")
        if not pd.isna(pay3m):
            labor_bits.append(f"payrolls averaging {pay3m:+,.0f}k/month over 3 months")
        if labor_bits:
            st.info("**Labor read:** " + "; ".join(labor_bits) + ".")

        st.subheader("Trends — 5 years")
        chart_ids = ["CPIAUCSL", "PCEPI", "UNRATE", "FEDFUNDS",
                     "ICSA", "PAYEMS", "GDP"]
        for i in range(0, len(chart_ids), 2):
            cols = st.columns(2)
            for col, sid in zip(cols, chart_ids[i:i + 2]):
                s = econ_display(sid, econ[sid]).dropna().tail(260)
                fig = go.Figure(go.Scatter(x=s.index, y=s, line=dict(width=2)))
                fig.update_layout(title=f"{FR.ECON_SERIES[sid]} — 5 years",
                                  height=300, margin=dict(t=40, b=10))
                col.plotly_chart(fig, use_container_width=True)
        y2 = econ_display("DGS2", econ["DGS2"]).dropna().tail(260)
        y10 = econ_display("DGS10", econ["DGS10"]).dropna().tail(260)
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=y2.index, y=y2, name="2Y"))
        fig.add_trace(go.Scatter(x=y10.index, y=y10, name="10Y"))
        fig.update_layout(title="Treasury yields (FRED) — 5 years",
                          height=300, margin=dict(t=40, b=10))
        st.plotly_chart(fig, use_container_width=True)

        st.subheader("US Treasury yield curve")
        yc = load_yield_curve()
        if yc:
            def curve_on(target):
                pts = []
                for label, (_sid, yrs) in FR.YIELD_CURVE_SERIES.items():
                    if label not in yc:
                        continue
                    s = yc[label]["value"]
                    s = s[s.index <= target]
                    if not s.empty:
                        pts.append((yrs, label, float(s.iloc[-1])))
                return pts

            latest = max(df.index[-1] for df in yc.values())
            curves = [
                (curve_on(latest), f"Now ({latest:%b %d, %Y})", None),
                (curve_on(latest - pd.Timedelta(days=30)), "1 month ago", "dash"),
                (curve_on(latest - pd.Timedelta(days=365)), "1 year ago", "dot"),
            ]
            fig = go.Figure()
            for pts, name, dash in curves:
                if not pts:
                    continue
                fig.add_trace(go.Scatter(
                    x=[p[0] for p in pts], y=[p[2] for p in pts],
                    mode="lines+markers", name=name,
                    line=dict(dash=dash) if dash else {},
                    text=[p[1] for p in pts],
                    hovertemplate="%{text}: %{y:.2f}%<extra></extra>"))
            if curves[0][0]:
                fig.update_xaxes(
                    tickvals=[p[0] for p in curves[0][0]],
                    ticktext=[p[1] for p in curves[0][0]])
            fig.update_layout(height=380, margin=dict(t=40, b=10),
                              xaxis_title="Maturity", yaxis_title="Yield (%)",
                              yaxis_ticksuffix="%")
            st.plotly_chart(fig, use_container_width=True)
            d = {p[1]: p[2] for p in curves[0][0]}
            if "10Y" in d and "2Y" in d:
                spr = d["10Y"] - d["2Y"]
                st.caption(f"10Y–2Y spread {spr:+.2f}pp — " +
                           ("inverted ⚠️" if spr < 0 else "normal"))
        st.caption("Series IDs: " + ", ".join(
            dict.fromkeys(list(FR.ECON_SERIES) +
                          [sid for sid, _yrs in FR.YIELD_CURVE_SERIES.values()])) +
            ". Source: FRED API, Federal Reserve Bank of St. Louis.")

# ---------------- SECTOR ROTATION ----------------
with tabs[4]:
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
# Severity bands in 20-point increments; single source for gauge + legend.
HEADLINE_RISK_BANDS = [
    ("0–20 · Calm", 0, 20, "#2ecc71"),
    ("20–40 · Low", 20, 40, "#f1c40f"),
    ("40–60 · Elevated", 40, 60, "#f39c12"),
    ("60–80 · High", 60, 80, "#e67e22"),
    ("80–100 · Severe", 80, 100, "#e74c3c"),
]

with tabs[5]:
    if news_err:
        st.warning(f"News feed unavailable: {news_err}")
    elif headlines:
        if news_ts is not None:
            age_min = int((datetime.now(timezone.utc) - news_ts).total_seconds() // 60)
            age_str = "just now" if age_min < 1 else f"{age_min} min ago"
            st.caption(f"Headlines fetched "
                       f"{news_ts.astimezone(ZoneInfo('America/Toronto')):%b %d, %Y · %I:%M %p ET}"
                       f" ({age_str}) · Sources: Google News, CNBC")
        meter, detail = headline_meter, headline_detail
        c1, c2 = st.columns([1, 2])
        with c1:
            st.plotly_chart(gauge(
                meter, "Headline Risk",
                steps=[{"range": [lo, hi], "color": c}
                       for _lbl, lo, hi, c in HEADLINE_RISK_BANDS]),
                use_container_width=True)
            segs = "".join(
                f"<div style='flex:1;background:{c};"
                f"color:{'#fff' if i >= 2 else '#333'};text-align:center;"
                f"font-size:10px;padding:3px 1px;line-height:1.25;'>{lbl}</div>"
                for i, (lbl, _lo, _hi, c) in enumerate(HEADLINE_RISK_BANDS))
            st.markdown(
                "<div style='display:flex;border-radius:4px;overflow:hidden;'>"
                f"{segs}</div>", unsafe_allow_html=True)
            st.caption("Severity scale: 0 = calm, 100 = maximum headline risk.")
            st.caption(detail)
            st.caption("Keyword-based: high-risk words (crash, tariff, war…), "
                       "medium (Fed, CPI, inflation…), bullish words reduce risk.")
        with c2:
            for h in headlines:
                badge = {"high": "🔴", "medium": "🟡", "low": "⚪",
                         "bullish": "🟢"}[h["risk"]]
                st.markdown(f"`{h['published']}` {badge} **[{h['source']}]** "
                            f"{h['title']} — {h['risk_reason']}")
    else:
        st.info("No headlines right now.")

# ---------------- ECONOMIC CALENDAR ----------------
with tabs[6]:
    events, err = load_calendar()
    if err:
        st.warning(f"Calendar feed unavailable: {err}")
    elif events:
        st.subheader(f"US economic calendar — next 7 days ({len(events)})")
        rows = [{"Date": e["date"], "Time": e["time_et"], "Event": e["event"],
                 "Impact": e["impact"], "Forecast": e["forecast"],
                 "Previous": e["previous"]} for e in events]
        cdf = pd.DataFrame(rows)
        def highlight(row):
            color = {"High": "#e74c3c", "Medium": "#f39c12"}.get(row["Impact"], "")
            return [f"background-color: {color}33" if color else ""] * len(row)
        st.dataframe(cdf.style.apply(highlight, axis=1),
                     use_container_width=True, hide_index=True)
        st.caption("Source: ForexFactory weekly calendar feed (times ET). "
                   "Rolling 7-day window — near week's end the feed may cover "
                   "fewer than 7 days.")
    else:
        st.info("No events found.")

# ---------------- EARNINGS ----------------
with tabs[7]:
    earnings, err = load_earnings()
    if err:
        st.warning(f"Earnings feed unavailable: {err}")
    elif earnings:
        st.subheader(f"Earnings — next 7 days ({len(earnings)} notable)")
        rows = [{"Date": e["date"], "Time": e["time"] or "—", "Symbol": e["symbol"],
                 "Company": e["name"], "Mkt Cap ($B)": e["mcap_b"],
                 "EPS est.": e["eps_forecast"] or "—",
                 "Revenue est.": e["revenue_forecast"] or "—"} for e in earnings]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        st.caption("Source: Nasdaq earnings calendar. Filtered to companies ≥ $5B market cap.")
    else:
        st.info("No notable earnings in the next 7 days.")

# ---------------- GEX ----------------
with tabs[8]:
    st.subheader("Gamma exposure (GEX)")
    st.caption("Dealer gamma positioning from listed option chains — SPY/QQQ/IWM "
               "as S&P 500 / Nasdaq 100 / Russell 2000 proxies. Positive GEX = "
               "dealers long gamma (dampens moves); negative = short gamma "
               "(amplifies moves). Nearest 3 expiries, prior-day open interest. [gex-v5]")
    for name, etf in [("S&P 500", "SPY"), ("Nasdaq 100", "QQQ"),
                      ("Russell 2000", "IWM")]:
        try:
            g = load_gex(etf)
        except Exception as e:
            st.markdown(f"#### {name} ({etf})")
            st.warning(f"GEX unavailable for {etf}: {e}")
            continue
        st.markdown(f"#### {name} ({etf})")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Net GEX", f"${g['total_net']:+.0f}M/pt")
        m2.metric("Put wall (support)",
                  f"{g['put_wall']:.0f}" if g["put_wall"] else "—")
        m3.metric("Call wall (resistance)",
                  f"{g['call_wall']:.0f}" if g["call_wall"] else "—")
        m4.metric("Zero-gamma",
                  f"{g['zero_gamma']:.0f}" if g["zero_gamma"] else "—")
        st.plotly_chart(G.gex_chart(g, f"{name} — net GEX by strike "
                                      f"({', '.join(g['expiries'])})"),
                        use_container_width=True)
        st.info(f"**Read:** {G.gex_read(g)}")
    st.caption("Method: per-contract gamma × open interest from CBOE delayed quotes "
               "(yfinance chains + Black-Scholes gamma as fallback). "
               "GEX = (call OI × call γ − put OI × put γ) × 100 × spot. "
               "Assumes dealers long calls / short puts: positive = long gamma "
               "(dampens), negative = short gamma (amplifies). [gex-v5]")

with tabs[9]:
    st.subheader("Fed Watch — rate probabilities")
    st.caption("Market-implied odds of Fed moves at upcoming FOMC meetings, "
               "stripped from 30-day Fed Funds futures (CME ZQ).")
    st.markdown(f"**Last FOMC decision:** {F.last_decision_text()}")
    try:
        fw = load_fedwatch()
    except Exception as e:
        st.warning(f"Fed Watch unavailable: {e}")
        fw = None
    if fw:
        lo, hi = fw["target_range"]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Effective fed funds rate",
                  f"{fw['effective_rate']:.2f}%",
                  help=f"FRED DFF as of {fw['effective_date']}")
        c2.metric("Target range", f"{lo:.2f}–{hi:.2f}%")
        nxt = fw["meetings"][0]
        c3.metric("Next FOMC decision",
                  nxt["date"].strftime("%b %d"),
                  f"in {nxt['days_away']} days")
        ten = load_ten_year()
        c4.metric("10-year Treasury",
                  f"{ten[0]:.2f}%" if ten else "n/a",
                  help=(f"FRED DGS10 as of {ten[1]}" if ten
                        else "FRED DGS10 unavailable"))
        try:
            fwh = load_fedwatch_history()
        except Exception:
            fwh = None
        for m in fw["meetings"]:
            st.markdown(f"#### {m['date'].strftime('%B %d, %Y')} "
                        f"— decision day ({m['days_away']} days away)")
            st.plotly_chart(F.fedwatch_chart(m, "Implied probabilities"),
                            use_container_width=True)
            st.info(f"**Read:** {F.fedwatch_read(m)}")
            if fwh and m["date"] in fwh:
                st.plotly_chart(
                    F.fedwatch_history_chart(
                        fwh[m["date"]],
                        f"{m['date'].strftime('%b %d')} meeting — "
                        "probability history (90 days)"),
                    use_container_width=True)
        st.caption("Method: implied avg rate = 100 − ZQ futures price; expected "
                   "post-meeting rate strips out pre-decision days (chained across "
                   "meetings); expected move split across adjacent 25bp buckets. "
                   "Data: Yahoo Finance (ZQ), FRED (DFF). Educational — not "
                   "investment advice.")

st.divider()
st.caption("Data: Yahoo Finance (prices), FRED API (economy), Google News + CNBC RSS (headlines), ForexFactory "
           "(calendar), Nasdaq (earnings), CME ZQ futures + FRED (Fed Watch). "
           "Educational — not investment advice. "
           "Data caches refresh on ↻ Refresh.")
