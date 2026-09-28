"""Page view counter: one view per browser session.

Primary backend: Upstash Redis (free tier) via its REST API — durable and
cumulative across redeploys, unlike Streamlit Cloud's ephemeral filesystem.
Configure with either Streamlit secrets::

    [upstash_redis]
    rest_url = "https://....upstash.io"
    rest_token = "..."

or the env vars UPSTASH_REDIS_REST_URL / UPSTASH_REDIS_REST_TOKEN.

Optional: seed_views = 80 (or UPSTASH_SEED_VIEWS) seeds the cumulative
total once via SETNX — it never overwrites an existing count, so it's
safe to leave in secrets.

Fallback: the previous file-based counter (data/view_count.txt) when Redis
isn't configured or unreachable. The file counter resets on redeploy —
expected, and documented in the footer methodology, not a bug.
"""
from __future__ import annotations

import os
from pathlib import Path

import requests
import streamlit as st

_COUNT_FILE = Path(__file__).resolve().parent.parent / "data" / "view_count.txt"
_REDIS_KEY = "usms:views:total"


def _file_increment() -> int:
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


def _redis_creds() -> tuple[str | None, str | None]:
    url = token = None
    try:
        cfg = st.secrets.get("upstash_redis", {})
        url = cfg.get("rest_url")
        token = cfg.get("rest_token")
    except Exception:
        pass  # no secrets configured
    url = url or os.environ.get("UPSTASH_REDIS_REST_URL")
    token = token or os.environ.get("UPSTASH_REDIS_REST_TOKEN")
    return (url, token) if url and token else (None, None)


def _seed_value() -> int | None:
    """Best-guess historical total, applied once via SETNX (never overwrites)."""
    seed = None
    try:
        seed = st.secrets.get("upstash_redis", {}).get("seed_views")
    except Exception:
        pass
    seed = seed or os.environ.get("UPSTASH_SEED_VIEWS")
    try:
        seed = int(seed)
    except (TypeError, ValueError):
        return None
    return seed if seed > 0 else None


def _redis_seed(url: str, token: str, seed: int) -> None:
    """SETNX: seed the cumulative total only if the key doesn't exist yet."""
    r = requests.post(
        f"{url.rstrip('/')}/setnx/{_REDIS_KEY}/{seed}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=8,
    )
    r.raise_for_status()


def _redis_incr(url: str, token: str) -> int:
    """Atomic INCR on the Redis key; returns the new cumulative total."""
    r = requests.post(
        f"{url.rstrip('/')}/incr/{_REDIS_KEY}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=8,
    )
    r.raise_for_status()
    return int(r.json()["result"])


def get_view_count() -> int:
    """Return the total view count, incrementing once per user session."""
    if "_view_count" not in st.session_state:
        url, token = _redis_creds()
        if url and token:
            try:
                seed = _seed_value()
                if seed:
                    _redis_seed(url, token, seed)  # no-op if key exists
                st.session_state["_view_count"] = _redis_incr(url, token)
            except Exception:
                st.session_state["_view_count"] = _file_increment()
        else:
            st.session_state["_view_count"] = _file_increment()
    return int(st.session_state["_view_count"])
