"""File-based page view counter.

Counts one view per browser session (guarded by st.session_state, so
reruns don't inflate it). The count lives in data/view_count.txt.

Caveat: Streamlit Cloud's filesystem is ephemeral — redeploys and
long idle stretches reboot the container, resetting the counter to
whatever value is committed in the repo. Good enough for a rough
readership signal; not analytics-grade.
"""
from __future__ import annotations

from pathlib import Path

import streamlit as st

_COUNT_FILE = Path(__file__).resolve().parent.parent / "data" / "view_count.txt"


def _increment() -> int:
    _COUNT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(_COUNT_FILE, "a+") as f:
        try:
            import fcntl

            fcntl.flock(f, fcntl.LOCK_EX)
        except ImportError:
            pass  # non-POSIX platform; best effort
        f.seek(0)
        try:
            count = int(f.read().strip() or 0)
        except ValueError:
            count = 0
        count += 1
        f.seek(0)
        f.truncate()
        f.write(str(count))
        return count


def get_view_count() -> int:
    """Return the total view count, incrementing once per user session."""
    if "_view_count" not in st.session_state:
        try:
            st.session_state["_view_count"] = _increment()
        except OSError:
            st.session_state["_view_count"] = 0
    return int(st.session_state["_view_count"])
