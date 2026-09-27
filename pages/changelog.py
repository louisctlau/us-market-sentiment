"""Changelog — version history for the US Market Sentiment dashboard."""
from __future__ import annotations

from pathlib import Path

import streamlit as st

st.set_page_config(page_title="Changelog — US Market Sentiment", layout="wide")
# Navigation lives in the footer link; keep the tabbed UX clean.
st.markdown("<style>[data-testid='stSidebarNav']{display:none;}</style>",
            unsafe_allow_html=True)

st.title("Changelog")
st.caption("Every shipped change to the US Market Sentiment dashboard, newest first.")
st.markdown("[← Back to dashboard](/)")
st.divider()

md = (Path(__file__).resolve().parent.parent / "CHANGELOG.md").read_text()
st.markdown(md)
