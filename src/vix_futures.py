"""VIX futures term structure from CBOE's free daily settlement CSVs.

Keyless endpoint (verified working 2026-09-27):
    https://www.cboe.com/us/futures/market_statistics/settlement/csv?dt=YYYY-MM-DD
One CSV per trading day: Product,Symbol,Expiration Date,Price.
Only the latest trading day's curve is fetched (history would need one
request per day); the loader walks back over weekends/holidays.
"""
from __future__ import annotations

import io
from datetime import date, timedelta

import pandas as pd
import requests

_CSV_URL = "https://www.cboe.com/us/futures/market_statistics/settlement/csv"
_UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"}


def fetch_vix_futures_curve(max_lookback_days: int = 7) -> tuple[pd.DataFrame, date]:
    """Latest VX futures curve.

    Returns (DataFrame with `expiration`/`price` columns sorted by expiry,
    as-of date). Raises RuntimeError if no trading day in the lookback
    window yields data.
    """
    last_err: Exception | None = None
    for back in range(max_lookback_days):
        d = date.today() - timedelta(days=back)
        try:
            r = requests.get(_CSV_URL, params={"dt": d.isoformat()},
                             headers=_UA, timeout=30)
            r.raise_for_status()
            df = pd.read_csv(io.StringIO(r.text))
            vx = df[df["Product"] == "VX"].copy()
            if vx.empty:
                continue
            vx["expiration"] = pd.to_datetime(vx["Expiration Date"])
            vx = (vx.sort_values("expiration")[["expiration", "Price"]]
                    .rename(columns={"Price": "price"})
                    .reset_index(drop=True))
            return vx, d
        except Exception as e:  # noqa: BLE001 - keep walking back on any failure
            last_err = e
    raise RuntimeError(
        f"no VIX futures data in the last {max_lookback_days} days: {last_err}")
