"""US Market Sentiment Dashboard — SPX / Nasdaq / Russell breadth, VIX, USD,
yields, technicals, sector rotation, headline risk, economic calendar."""
from __future__ import annotations

import pandas as pd
import numpy as np
import plotly.graph_objects as go
import streamlit as st
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from src import commentary as C
from src import fedwatch as F
from src import fred as FR
from src import gex as G
from src import sentiment_v2 as S
from src.econ_calendar_v2 import fetch_calendar
from src.data import (
    CROSS_ASSETS,
    DEFENSIVE_SECTORS,
    INDICES,
    OFFENSIVE_SECTORS,
    ROTATION_GROWTH,
    ROTATION_SAFE,
    SECTORS,
    VOL_EXTRA,
    VOL_MACRO,
    fetch_all,
    pct_change,
)
from src.earnings import fetch_earnings
from src.news import fetch_headlines, risk_meter
from src.technicals import rsi, sma, technical_snapshot
from src.vix_futures import fetch_vix_futures_curve

# NYSE full-day closures (weekends are handled separately). Extend yearly.
_NYSE_HOLIDAYS = {
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25",
    "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25",
    "2027-01-01", "2027-01-18", "2027-02-15", "2027-04-02", "2027-05-31",
    "2027-06-18", "2027-07-05", "2027-09-06", "2027-11-25", "2027-12-24",
}
# 1:00 PM ET closes (day after Thanksgiving, Christmas Eve).
_NYSE_EARLY_CLOSE = {"2026-11-27", "2026-12-24", "2027-11-26"}


def market_status(now=None):
    """NYSE session status for the dashboard caption."""
    et = ZoneInfo("America/Toronto")
    now = now or datetime.now(et)
    d = now.strftime("%Y-%m-%d")
    t = now.hour + now.minute / 60 + now.second / 3600
    if now.weekday() >= 5 or d in _NYSE_HOLIDAYS:
        return "🔴 Market closed"
    if d in _NYSE_EARLY_CLOSE:
        return ("🟢 Market open · early close 1:00 PM ET" if t < 13.0
                else "🔴 Market closed · early close 1:00 PM ET")
    if t < 4.0:
        return "🔴 Market closed"
    if t < 9.5:
        return "🟡 Pre-market · opens 9:30 AM ET"
    if t < 16.0:
        return "🟢 Market open · closes 4:00 PM ET"
    if t < 20.0:
        return "🟡 After-hours"
    return "🔴 Market closed"


st.set_page_config(page_title="US Market Sentiment", layout="wide")
# Sidebar nav is hidden: the app is tab-based, and the changelog page is
# reached via the link under the title.
st.markdown(
    "<style>"
    "[data-testid='stSidebarNav']{display:none;}"  # tab-based app; sidebar is the catalysts panel
    "[data-testid='stSidebarUserContent']{display:flex;flex-direction:column;}"
    ".sidebar-spacer{flex:1 1 auto;min-height:2rem;}"
    "</style>",
    unsafe_allow_html=True)
st.title("US Market Sentiment Dashboard")
st.markdown("<span style='color:#ff4b4b;font-size:0.85rem;'>"
           "Disclaimer: For educational and experimental purposes only. Not investment advice."
           "</span>", unsafe_allow_html=True)
st.caption(market_status())
st.page_link("pages/changelog.py", label="Changelog")

# ---- Sidebar: upcoming catalysts countdown ----
# CPI/payrolls dates verified at bls.gov/schedule/2026; PCE (Personal
# Income and Outlays) at bea.gov/news/schedule; FOMC mirrors F.MEETINGS.
# Release times: BLS and BEA reports hit at 8:30 AM ET; the FOMC statement
# at 2:00 PM ET (press conference 2:30 PM). Extend these lists as new
# schedules publish.
_CPI_DATES = [date(2026, 10, 14), date(2026, 11, 10), date(2026, 12, 10)]
_PAYROLLS_DATES = [date(2026, 10, 2), date(2026, 11, 6), date(2026, 12, 4)]
_PCE_DATES = [date(2026, 9, 30), date(2026, 10, 29), date(2026, 11, 25),
              date(2026, 12, 23)]


def _ref_month(d):
    # Release's reference month: CPI/payrolls/PCE always report the
    # previous month (e.g. the Oct 14 CPI covers September).
    return (d.replace(day=1) - timedelta(days=1)).strftime("%b")


def _next_catalysts(today):
    out = []
    fomc = [d for d, _ in F.MEETINGS if d >= today]
    if fomc:
        out.append(("FOMC decision", fomc[0], "2:00 PM ET", ""))
    cpi = [d for d in _CPI_DATES if d >= today]
    if cpi:
        out.append(("CPI", cpi[0], "8:30 AM ET", _ref_month(cpi[0])))
    pce = [d for d in _PCE_DATES if d >= today]
    if pce:
        out.append(("PCE", pce[0], "8:30 AM ET", _ref_month(pce[0])))
    nfp = [d for d in _PAYROLLS_DATES if d >= today]
    if nfp:
        out.append(("Non-farm payrolls", nfp[0], "8:30 AM ET", _ref_month(nfp[0])))
    out.sort(key=lambda x: x[1])
    return out


st.sidebar.subheader("Upcoming catalysts")
_today = datetime.now(ZoneInfo("America/Toronto")).date()
for _name, _d, _t, _p in _next_catalysts(_today):
    _n = (_d - _today).days
    _when = "today" if _n == 0 else "tomorrow" if _n == 1 else f"in {_n}d"
    _label = f"{_name} ({_p})" if _p else _name
    st.sidebar.markdown(f"**{_label}**<br>{_d.strftime('%a %b %d')} · {_t} · {_when}",
                        unsafe_allow_html=True)
st.sidebar.markdown('<div class="sidebar-spacer"></div>', unsafe_allow_html=True)
st.sidebar.divider()
st.sidebar.page_link("pages/changelog.py", label="Changelog")


@st.cache_data(ttl=900)
def load_data():
    idx = fetch_all(INDICES, period="1y")
    vm = fetch_all(VOL_MACRO, period="1y")
    vx = fetch_all(VOL_EXTRA, period="1y")
    sec = fetch_all(SECTORS, period="6mo")
    xa = fetch_all(CROSS_ASSETS, period="1y")
    br = fetch_all({"RSP (Equal-Weight S&P)": "RSP"}, period="1y")
    # Risk-off rotation baskets (Tasty formula): day-% change only. Reuse the
    # sector frames already fetched; pull just the 8 non-sector tickers.
    rot_syms = {**ROTATION_GROWTH, **ROTATION_SAFE}
    rot_new = fetch_all({k: t for k, t in rot_syms.items() if k not in sec},
                        period="5d")
    rot_data = {k: sec[k] if k in sec else rot_new[k] for k in rot_syms}
    return idx, vm, vx, sec, xa, br, rot_data, datetime.now(timezone.utc)


@st.cache_data(ttl=6 * 3600)
def load_credit_5y():
    return fetch_all({k: CROSS_ASSETS[k] for k in ("High-Yield (HYG)", "Inv-Grade (LQD)")},
                     period="5y")


@st.cache_data(ttl=6 * 3600)
def load_score_fred():
    """FRED series the sentiment score needs. Independent of the Macro tab's
    strict loader: one dead series is skipped, a missing key yields {} —
    every consumer degrades to neutral 50."""
    out = {}
    for sid in ("DGS2", "UNRATE", "BAMLH0A0HYM2"):
        try:
            out[sid] = FR.get_series(sid, observation_start="2020-01-01")
        except Exception:
            continue
    return out


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


@st.cache_data(ttl=3600)
def load_vix_futures():
    # Latest VX futures curve from CBOE's free settlement CSVs; (curve, asof, err).
    try:
        curve, asof = fetch_vix_futures_curve()
        return curve, asof, None
    except Exception as e:
        return None, None, str(e)


def gauge(value: float, title: str, color_ranges=True, invert=False,
          steps: list | None = None) -> go.Figure:
    default_steps = [{"range": [0, 30], "color": "#e74c3c"},
                     {"range": [30, 45], "color": "#f39c12"},
                     {"range": [45, 70], "color": "#f1c40f"},
                     {"range": [70, 100], "color": "#2ecc71"}]
    if invert:  # high = bad (fear, risk-off)
        default_steps = [{"range": [0, 30], "color": "#2ecc71"},
                         {"range": [30, 45], "color": "#f1c40f"},
                         {"range": [45, 70], "color": "#f39c12"},
                         {"range": [70, 100], "color": "#d62728"}]
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


idx, vm, vx, sec, xa, br, rot_data, data_ts = load_data()
vx_fut, vx_fut_asof, vx_fut_err = load_vix_futures()
sfred = load_score_fred()
cr5y = load_credit_5y()
failed = sorted({name for group in (idx, vm, vx, sec, xa, br)
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
def _cut(df, n):
    """Truncate a frame by n trailing rows (lagged score recomputation).
    Returns the full frame when there isn't enough history to lag."""
    if n and df is not None and not df.empty and len(df) > n + 20:
        return df.iloc[:-n]
    return df


def build_components(n=0, gex=None, fed=None, news_meter=None):
    """Full component set as of n trading days ago (n=0 → today).

    gex / fed / news_meter are today-only inputs (no history exists);
    past days score those sleeves neutral. Set gex=None etc. to degrade
    gracefully when a feed fails."""
    idx_n = {k: _cut(v, n) for k, v in idx.items()}
    vm_n = {k: _cut(v, n) for k, v in vm.items()}
    vx_n = {k: _cut(v, n) for k, v in vx.items()}
    sec_n = {k: _cut(v, n) for k, v in sec.items()}
    snaps = {k: technical_snapshot(v) for k, v in idx_n.items() if not v.empty}
    rsp = _cut(br["RSP (Equal-Weight S&P)"], n)
    spx = idx_n["S&P 500"]
    breadth = ((rsp["close"] / spx["close"]).dropna()
               if not rsp.empty and not spx.empty else None)
    hyg_n = _cut(cr5y["High-Yield (HYG)"], n)
    lqd_n = _cut(cr5y["Inv-Grade (LQD)"], n)
    oas = (_cut(sfred["BAMLH0A0HYM2"], n)["value"]
           if "BAMLH0A0HYM2" in sfred else None)
    dgs2 = _cut(sfred["DGS2"], n)["value"] if "DGS2" in sfred else None
    unrate = _cut(sfred["UNRATE"], n)["value"] if "UNRATE" in sfred else None
    return {
        "Trend": S.trend_score(snaps, breadth),
        "Momentum": S.momentum_score(snaps),
        "Volatility": S.volatility_score(vm_n["VIX"], vx_n.get("VVIX"),
                                         vx_n.get("SKEW"), vx_n.get("MOVE"),
                                         vx_fut if n == 0 else None),
        "Credit": S.credit_score(hyg_n, lqd_n, oas),
        "Macro": S.macro_score(vm_n["DXY (USD Index)"], vm_n["US 10Y Yield"],
                               dgs2, unrate, fed if n == 0 else None),
        "Sectors": S.sector_score(sec_n),
        "Positioning": S.positioning_score(gex if n == 0 else None),
        "News": S.news_score(news_meter if n == 0 else None),
    }


headlines, news_err, news_ts = load_news()
headline_meter, headline_detail = risk_meter(headlines) if headlines else (0.0, "no headlines")

# Today-only composite inputs: SPY dealer positioning + Fed stance.
# Failures degrade to neutral sleeves, never crash the score.
try:
    spy_gex = load_gex("SPY")
except Exception:
    spy_gex = None
try:
    fed = S.fed_stance(load_fedwatch()["meetings"])
except Exception:
    fed = None

components = build_components(0, gex=spy_gex, fed=fed,
                              news_meter=headline_meter if headlines else None)
score_today, breakdown = S.composite(components)
# Headline is the 3-day average — one volatile session can't swing it 10+ points.
past = [S.composite(build_components(n))[0] for n in (1, 2)]
score = float(np.mean([score_today, *past]))


@st.cache_data(ttl=3600)
def composite_history(days: int = 22):
    """Trailing composite, oldest → newest. Past days use price-based
    sleeves only (GEX/Fed/news are today-only inputs, neutral before)."""
    return [S.composite(build_components(n))[0] for n in range(days - 1, -1, -1)]

fear, fear_detail = S.fear_context(vm["VIX"], idx["S&P 500"])
rot, rot_detail = S.risk_off_rotation(rot_data)
snaps = {n: technical_snapshot(df) for n, df in idx.items() if not df.empty}

tabs = st.tabs(["Overview", "Indices", "Volatility", "Macro",
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
        hist = composite_history()
        hdates = idx["S&P 500"].index[-len(hist):]
        sfig = go.Figure(go.Scatter(x=hdates, y=hist, mode="lines",
                                    line=dict(color="#1f77b4", width=2),
                                    name="Composite"))
        sfig.add_hline(y=50, line_dash="dot", line_color="#888")
        sfig.update_layout(title="Past month", height=200,
                           margin=dict(t=30, b=10, l=10, r=10),
                           yaxis=dict(range=[0, 100]), xaxis_title="",
                           yaxis_title="")
        st.plotly_chart(sfig, use_container_width=True)
    with c2:
        st.subheader("What drives the score")
        rows = [{"Component": k, "Score": round(v["score"], 1),
                 "Weight": f"{int(S.WEIGHTS[k]*100)}%", "Detail": v["detail"]}
                for k, v in breakdown.items()]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        st.caption("100 = most bullish. Headline is the 3-day average "
                   f"(today {score_today:.1f}). Weights: " +
                   ", ".join(f"{k} {int(w * 100)}%"
                             for k, w in S.WEIGHTS.items()) + ".")

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
        # Day-change is rendered as a custom pill, not st.metric's delta:
        # Streamlit adds its own arrow to string deltas (always up/green),
        # which produced the doubled "↑ ▼" and wrong color.
        col.metric(name, f"{s['last']:,.1f}")
        ret = s["ret_1d"]
        if ret is not None:
            up = ret >= 0
            arrow = "▲" if up else "▼"
            color = "#3ddc84" if up else "#ff6b6b"
            bg = "rgba(61,220,132,0.15)" if up else "rgba(255,107,107,0.15)"
            col.markdown(
                f"<span style='display:inline-block;padding:0.15rem 0.7rem;"
                f"border-radius:999px;background:{bg};color:{color};"
                f"font-weight:600;font-size:0.85rem;'>"
                f"{arrow} {ret:+.2f}% today</span>",
                unsafe_allow_html=True)
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
        st.caption(f"{rot_detail} — growth vs safe-haven day move.")

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

# ---------------- VOLATILITY ----------------
with tabs[2]:
    st.subheader("Volatility overview")
    st.info(C.volatility_overview(vm["VIX"], vx["VVIX"], vx["SKEW"],
                                  vx["VIX 9D"], vx["VIX 3M"],
                                  spx_df=idx["S&P 500"],
                                  hyg_df=xa["High-Yield (HYG)"],
                                  lqd_df=xa["Inv-Grade (LQD)"]))

    mcols = st.columns(4)
    for col, (label, df, fmt) in zip(
            mcols,
            [("VIX", vm["VIX"], "{:.1f}"),
             ("VVIX", vx["VVIX"], "{:.0f}"),
             ("SKEW", vx["SKEW"], "{:.0f}"),
             ("MOVE", vx["MOVE"], "{:.0f}")]):
        with col:
            if df.empty:
                st.metric(label, "n/a")
                continue
            st.metric(label, fmt.format(float(df["close"].iloc[-1])))

    if not vm["VIX"].empty:
        st.plotly_chart(line_chart(vm["VIX"].tail(252), "VIX — 1 year",
                                   {"SMA 50": sma(vm["VIX"]["close"], 50).tail(252)}),
                        use_container_width=True)
        vix = float(vm["VIX"]["close"].iloc[-1])
        st.write(f"**VIX {vix:.1f}** — " +
                 ("complacent (<15)" if vix < 15 else
                  "normal (15–20)" if vix < 20 else
                  "elevated (20–30)" if vix < 30 else "panic (>30)"))

    if not vx["VVIX"].empty:
        st.plotly_chart(line_chart(vx["VVIX"].tail(252), "VVIX — volatility of VIX, 1 year",
                                   {"SMA 50": sma(vx["VVIX"]["close"], 50).tail(252)}),
                        use_container_width=True)
        vv = float(vx["VVIX"]["close"].iloc[-1])
        st.write(f"**VVIX {vv:.0f}** — " +
                 ("elevated (>120): heavy demand for volatility protection" if vv > 120 else
                  "subdued (<80): little demand for crash protection" if vv < 80 else
                  "in its normal range (80–120)"))

    if not vx["SKEW"].empty:
        st.plotly_chart(line_chart(vx["SKEW"].tail(252), "SKEW — tail-risk pricing, 1 year",
                                   {"SMA 50": sma(vx["SKEW"]["close"], 50).tail(252)}),
                        use_container_width=True)
        sk = float(vx["SKEW"]["close"].iloc[-1])
        st.write(f"**SKEW {sk:.0f}** — " +
                 ("elevated (≥135): downside protection is expensive" if sk >= 135 else
                  "calm (≤115): downside protection is cheap" if sk <= 115 else
                  "middling: tail fear neither stretched nor complacent"))

    if not vx["MOVE"].empty:
        st.plotly_chart(line_chart(vx["MOVE"].tail(252), "MOVE — bond-market volatility, 1 year",
                                   {"SMA 50": sma(vx["MOVE"]["close"], 50).tail(252)}),
                        use_container_width=True)
        mv = float(vx["MOVE"]["close"].iloc[-1])
        st.write(f"**MOVE {mv:.0f}** — " +
                 ("stressed (≥140): bond volatility pricing real rates risk" if mv >= 140 else
                  "calm (≤80): rates volatility subdued" if mv <= 80 else
                  "normal: no acute stress in rates markets"))

    v9d, v3m = vx["VIX 9D"], vx["VIX 3M"]
    if not v9d.empty and not v3m.empty and not vm["VIX"].empty:
        fig = go.Figure()
        for s, name in [(v9d.tail(252)["close"], "VIX 9D"),
                        (vm["VIX"].tail(252)["close"], "VIX 30D"),
                        (v3m.tail(252)["close"], "VIX 3M")]:
            fig.add_trace(go.Scatter(x=s.index, y=s, name=name))
        fig.update_layout(title="VIX term structure — 1 year", height=320,
                          margin=dict(t=40, b=10))
        st.plotly_chart(fig, use_container_width=True)
        l9, l30, l3 = (float(v9d["close"].iloc[-1]),
                       float(vm["VIX"]["close"].iloc[-1]),
                       float(v3m["close"].iloc[-1]))
        shape = ("backwardation ⚠️ — near-term fear exceeds longer-term expectations"
                 if l9 > l30 else
                 "flat — no strong near-vs-far fear signal"
                 if abs(l3 - l9) < 1.0 else
                 "contango — the normal upward-sloping vol curve")
        st.write(f"**{l9:.1f} / {l30:.1f} / {l3:.1f}** (9D / 30D / 3M) — {shape}")

    st.subheader("VIX futures term structure (CBOE)")
    if vx_fut_err:
        st.warning(f"VIX futures unavailable: {vx_fut_err}")
    elif vx_fut is not None and not vx_fut.empty:
        fig = go.Figure(go.Scatter(x=vx_fut["expiration"], y=vx_fut["price"],
                                   mode="lines+markers", name="VX"))
        fig.update_layout(title=f"VX futures curve — as of {vx_fut_asof:%b %d, %Y}",
                          height=320, margin=dict(t=40, b=10),
                          xaxis_title="Expiration", yaxis_title="Price")
        st.plotly_chart(fig, use_container_width=True)
        front = float(vx_fut["price"].iloc[0])
        back = float(vx_fut["price"].iloc[-1])
        st.write(f"**Front {front:.2f} → back {back:.2f}** — " +
                 ("backwardation ⚠️ — futures traders expect near-term stress"
                  if front > back else
                  "contango — futures curve upward-sloping as usual"))
        st.caption("Source: CBOE daily settlement CSVs (free, no key).")

    st.subheader("Realized vs implied volatility")
    spx = idx["S&P 500"]
    if spx.empty or vm["VIX"].empty:
        st.warning("Realized-vol data unavailable.")
    else:
        realized = spx["close"].pct_change().rolling(30).std() * (252 ** 0.5) * 100
        both = pd.DataFrame({"Realized 30D": realized,
                             "VIX (implied)": vm["VIX"]["close"]}).dropna().tail(252)
        fig = go.Figure()
        for col in both.columns:
            fig.add_trace(go.Scatter(x=both.index, y=both[col], name=col))
        fig.update_layout(title="30-day realized vol vs VIX — 1 year", height=320,
                          margin=dict(t=40, b=10), yaxis_title="Vol (ann. %)")
        st.plotly_chart(fig, use_container_width=True)
        lv, lr = float(both["VIX (implied)"].iloc[-1]), float(both["Realized 30D"].iloc[-1])
        st.write(f"**VIX {lv:.1f} vs realized {lr:.1f}** — " +
                 ("options pricing fear the tape hasn't shown yet" if lv - lr > 2 else
                  "realized vol running hotter than options imply" if lr - lv > 2 else
                  "implied and realized roughly in line"))

    st.subheader("Credit fear gauge — HYG/LQD")
    cr5y = load_credit_5y()
    hyg, lqd = cr5y["High-Yield (HYG)"], cr5y["Inv-Grade (LQD)"]
    if hyg.empty or lqd.empty:
        st.warning("Credit data unavailable.")
    else:
        ratio = (hyg["close"] / lqd["close"]).dropna()  # 5y: band calibration
        disp = ratio.tail(504)  # 2y chart window
        fig = line_chart(pd.DataFrame({"close": disp}), "HYG / LQD — 2 years",
                         {"SMA 50": sma(ratio, 50).tail(504)})
        st.plotly_chart(fig, use_container_width=True)
        rl = float(ratio.iloc[-1])
        m50 = float(sma(ratio, 50).iloc[-1])
        st.write(f"**HYG/LQD {rl:.3f}** — " +
                 (f"below 50-day avg ({m50:.3f}): credit stress the VIX may be missing"
                  if rl < m50 else
                  f"above 50-day avg ({m50:.3f}): credit markets calm"))
        pctl = float((ratio <= rl).mean()) * 100
        band = ("near 2-year highs — strong credit risk appetite" if pctl >= 80 else
                "in the upper part of its 2-year range" if pctl >= 60 else
                "mid-range vs the last 2 years" if pctl >= 40 else
                "in the lower part of its 2-year range — fading risk appetite" if pctl >= 20 else
                "near 2-year lows — credit stress")
        q20 = float(ratio.quantile(0.2)); q80 = float(ratio.quantile(0.8))
        with st.expander("How to read this gauge"):
            st.markdown(
                "- **What it is:** HYG (high-yield “junk” bonds) ÷ LQD "
                "(investment-grade bonds). Both are bond funds, so the ratio "
                "isolates appetite for *credit* risk.\n"
                "- **How to read it:** a *rising* ratio means investors are "
                "comfortable reaching for yield (risk-on); a *falling* ratio "
                "means flight from junk into quality (risk-off) — it often "
                "leads or confirms equity stress.\n"
                f"- **Right now:** {rl:.3f} sits in the {pctl:.0f}th percentile "
                f"of its 5-year range — {band}."
            )
            st.markdown("**Regime bands** — percentiles of the trailing 5-year "
                        "range (they move as the window rolls):")
            st.markdown(
                "| Regime | HYG/LQD range |\n"
                "|---|---|\n"
                f"| 🟢 Complacent (low fear) | ≥ {q80:.3f} |\n"
                f"| 🟡 Normal | {q20:.3f} – {q80:.3f} |\n"
                f"| 🔴 High fear | < {q20:.3f} |"
            )

# ---------------- MACRO (FRED API) ----------------
with tabs[3]:
    st.subheader("US Macro — FRED")
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
        st.info("The Macro tab needs a free FRED API key — get one at "
                "https://fred.stlouisfed.org/docs/api/api_key.html and add it as "
                "the `FRED_API_KEY` secret (Streamlit Cloud: app Settings → Secrets; "
                "local runs: `.streamlit/secrets.toml`). Then press ↻ Refresh.")
    elif econ_err:
        st.warning(f"FRED data unavailable: {econ_err}")
    else:
        st.info(C.macro_overview(econ, vm["DXY (USD Index)"]))

        def econ_display(sid: str, df: pd.DataFrame) -> pd.Series:
            v = df["value"]
            if sid in ("CPIAUCSL", "PCEPI", "PCEPILFE"):
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
                "PCEPILFE": "{:+.1f}%", "T5YIE": "{:.2f}%",
                "ICSA": "{:,.0f}", "PAYEMS": "{:+,.0f}k",
                "GDP": "{:+.1f}%", "DGS2": "{:.2f}%", "DGS10": "{:.2f}%"}
        heads, asofs = {}, {}
        for sid in FR.ECON_SERIES:
            heads[sid], asofs[sid] = FR.headline_value(sid, econ[sid])

        def econ_cards(sids, cols=None):
            cols = cols or st.columns(len(sids))
            for col, sid in zip(cols, sids):
                val = heads[sid]
                col.metric(FR.ECON_SERIES[sid],
                           fmts[sid].format(val) if val is not None else "n/a",
                           help=f"As of {asofs[sid]}")

        def econ_chart(sid, col=None):
            s = econ_display(sid, econ[sid]).dropna().tail(260)
            fig = go.Figure(go.Scatter(x=s.index, y=s, line=dict(width=2)))
            fig.update_layout(title=f"{FR.ECON_SERIES[sid]} — 5 years",
                              height=300, margin=dict(t=40, b=10))
            (col or st).plotly_chart(fig, use_container_width=True)

        st.subheader("Inflation")
        econ_cards(["CPIAUCSL", "PCEPI", "PCEPILFE", "T5YIE"])
        cols = st.columns(2)
        econ_chart("CPIAUCSL", cols[0])
        econ_chart("PCEPI", cols[1])
        cols = st.columns(2)
        econ_chart("PCEPILFE", cols[0])
        econ_chart("T5YIE", cols[1])

        st.subheader("Fed Funds Rate")
        econ_cards(["FEDFUNDS", "DGS2", "DGS10"])
        econ_chart("FEDFUNDS")
        y2 = econ_display("DGS2", econ["DGS2"]).dropna().tail(260)
        y10 = econ_display("DGS10", econ["DGS10"]).dropna().tail(260)
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=y2.index, y=y2, name="2Y"))
        fig.add_trace(go.Scatter(x=y10.index, y=y10, name="10Y"))
        fig.update_layout(title="Treasury yields (FRED) — 5 years",
                          height=300, margin=dict(t=40, b=10))
        st.plotly_chart(fig, use_container_width=True)
        spr_hist = (y10 - y2).dropna().tail(260)
        fig = go.Figure(go.Scatter(x=spr_hist.index, y=spr_hist,
                                   line=dict(width=2),
                                   fill="tozeroy"))
        fig.add_hline(y=0, line_dash="dash", line_color="gray")
        fig.update_layout(title="10Y–2Y spread — 5 years",
                          height=300, margin=dict(t=40, b=10),
                          yaxis_ticksuffix="pp")
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

        st.subheader("Labour Market")
        unrate = econ["UNRATE"]["value"]
        u3m = unrate.rolling(3).mean()
        sahm = u3m.iloc[-1] - u3m.tail(12).min() if len(u3m) >= 12 else None
        lm_cols = st.columns(4)
        econ_cards(["UNRATE", "ICSA", "PAYEMS"], lm_cols[:3])
        with lm_cols[3]:
            trig = sahm is not None and not pd.isna(sahm) and sahm >= 0.50
            st.metric("Sahm rule",
                      f"{sahm:.2f}pp" if sahm is not None and not pd.isna(sahm) else "n/a",
                      "⚠️ above 0.50 trigger" if trig else "below 0.50 trigger",
                      help=f"As of {asofs['UNRATE']}; 3-mo avg unemployment "
                           "vs its 12-mo low — a recession has started when it hits 0.50")
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
        if sahm is not None:
            labor_bits.append(
                f"Sahm rule {sahm:.2f}pp "
                f"({'⚠️ recession trigger (≥0.50)' if sahm >= 0.50 else 'below 0.50 trigger'}")
        if labor_bits:
            st.info("**Labor read:** " + "; ".join(labor_bits) + ".")
        cols = st.columns(2)
        econ_chart("UNRATE", cols[0])
        econ_chart("ICSA", cols[1])
        econ_chart("PAYEMS")

        st.subheader("GDP")
        econ_cards(["GDP"])
        econ_chart("GDP")

        st.caption("Series IDs: " + ", ".join(
            dict.fromkeys(list(FR.ECON_SERIES) +
                          [sid for sid, _yrs in FR.YIELD_CURVE_SERIES.values()])) +
            ". Source: FRED API, Federal Reserve Bank of St. Louis.")

    st.subheader("Dollar Strength")
    st.caption("Yahoo Finance (DX-Y.NYB) — 1 year.")
    if vm["DXY (USD Index)"].empty:
        st.warning("DXY data unavailable.")
    else:
        st.plotly_chart(line_chart(vm["DXY (USD Index)"].tail(252), "DXY — 1 year",
                                   {"SMA 50": sma(vm["DXY (USD Index)"]["close"], 50).tail(252)}),
                        use_container_width=True)
        st.markdown("- " + C.dxy_commentary(vm["DXY (USD Index)"]))

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
            st.caption("Negation- and verb-aware keywords + VADER sentiment, "
                       "net-scored per headline. 'Deal'/'tariff'/'yield' "
                       "scored by context ('deal signed' vs 'deal collapses', "
                       "'yields ease' vs 'yields surge'); gauge averages the "
                       "10 riskiest headlines. Fed/CPI are neutral context.")
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
        st.subheader(f"US economic calendar — this week + next 7 days ({len(events)})")
        # Streamlined filters: one search box (matches date, time, event,
        # forecast, previous, actual) + impact selector.
        fs, fi = st.columns([3, 1])
        q = fs.text_input("Search events", placeholder="e.g. FOMC, CPI, payrolls…",
                          key="cal_q", label_visibility="collapsed")
        impacts = sorted({e["impact"] for e in events})
        sel_impacts = fi.multiselect("Impact", impacts, default=impacts,
                                     key="cal_f_impact",
                                     label_visibility="collapsed",
                                     placeholder="Impact")
        ql = q.lower()
        # .get() with defaults: never crash if a cached older event payload
        # (e.g. from a previous deploy) lacks the newer keys.
        filtered = [
            e for e in events
            if e.get("impact") in sel_impacts
            and (not ql or ql in f"{e.get('date', '')} {e.get('time_et', '')} "
                                f"{e.get('event', '')} {e.get('period', '') or ''} "
                                f"{e.get('forecast', '—')} "
                                f"{e.get('previous', '—')} {e.get('actual', '—')}".lower())
        ]
        st.caption(f"Showing {len(filtered)} of {len(events)} events.")
        verdicts = [e.get("verdict") for e in filtered]
        rows = [{"Date": e.get("date", ""), "Time": e.get("time_et", ""),
                 "Event": e.get("event", "") +
                          (f" ({e['period']})" if e.get("period") else ""),
                 "Impact": e.get("impact", ""),
                 "Forecast": e.get("forecast", "—"),
                 "Previous": e.get("previous", "—"),
                 "Actual": e.get("actual", "—")}
                for e in filtered]
        cdf = pd.DataFrame(rows)
        def highlight(row):
            v = verdicts[row.name]
            icolor = {"High": "#e74c3c", "Medium": "#f39c12"}.get(row["Impact"], "")
            itint = f"background-color: {icolor}33" if icolor else ""
            out = []
            for col in row.index:
                if col == "Actual" and v == "good":
                    out.append("background-color: #27ae6055; font-weight: 600")
                elif col == "Actual" and v == "bad":
                    out.append("background-color: #e74c3c55; font-weight: 600")
                else:
                    out.append(itint)
            return out
        st.dataframe(cdf.style.apply(highlight, axis=1),
                     use_container_width=True, hide_index=True)
        st.caption("Source: Nasdaq economic calendar (times ET). Released events "
                   "stay on the calendar all week — actuals are highlighted "
                   "🟢 green when better than forecast/previous, 🔴 red when worse. "
                   "The period in brackets is the reference period each release "
                   "reports (e.g. CPI (Sep), GDP (Q3)), derived from each "
                   "indicator's standard reporting lag.")
    else:
        st.info("No events found.")

# ---------------- EARNINGS ----------------
with tabs[7]:
    earnings, err = load_earnings()
    if err:
        st.warning(f"Earnings feed unavailable: {err}")
    elif earnings:
        today_str = _today.isoformat()
        # .get() with defaults: never crash if a cached older payload
        # (e.g. from a previous deploy) lacks the newer keys.
        reported = [e for e in earnings if e.get("date", "") < today_str]
        upcoming = [e for e in earnings if e.get("date", "") >= today_str]
        if reported:
            st.subheader(f"Reported yesterday ({len(reported)})")
            rrows = [{"Date": e.get("date", ""), "Symbol": e.get("symbol", ""),
                      "Company": e.get("name", ""),
                      "Mkt Cap ($B)": e.get("mcap_b", ""),
                      "EPS actual": e.get("eps_actual") or "—",
                      "EPS est.": e.get("eps_forecast") or "—",
                      "Surprise": (f"{e['surprise']:+.1f}%"
                                   if e.get("surprise") is not None else "—")}
                     for e in reported]
            verdicts = [("beat" if (s or 0) > 0 else "miss" if (s or 0) < 0 else "")
                        for s in (e.get("surprise") for e in reported)]
            def earn_highlight(row):
                v = verdicts[row.name]
                return [("background-color: #27ae6055; font-weight: 600"
                         if col == "EPS actual" and v == "beat" else
                         "background-color: #e74c3c55; font-weight: 600"
                         if col == "EPS actual" and v == "miss" else "")
                        for col in row.index]
            st.dataframe(pd.DataFrame(rrows).style.apply(earn_highlight, axis=1),
                         use_container_width=True, hide_index=True)
            st.caption("Surprise 🟢 green = beat, 🔴 red = miss vs consensus.")
        else:
            st.caption("No notable earnings reported yesterday.")
        if upcoming:
            st.subheader(f"Upcoming — next 7 days ({len(upcoming)} notable)")
            rows = [{"Date": e.get("date", ""), "Time": e.get("time") or "—",
                     "Symbol": e.get("symbol", ""), "Company": e.get("name", ""),
                     "Mkt Cap ($B)": e.get("mcap_b", ""),
                     "EPS est.": e.get("eps_forecast") or "—"} for e in upcoming]
            st.dataframe(pd.DataFrame(rows),
                         use_container_width=True, hide_index=True)
        st.caption("Source: Nasdaq earnings calendar. Filtered to companies ≥ $5B market cap.")
    else:
        st.info("No notable earnings in the last day / next 7 days.")

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
