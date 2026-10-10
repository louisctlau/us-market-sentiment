"""Event dates for chart annotations (FOMC decisions, CPI releases).

FOMC decision dates are derived from the scheduled meeting calendar
(decision day = second day of the meeting). CPI dates are the 2026 BLS
release schedule. New module (2026-10-10).
"""
from __future__ import annotations

from datetime import date, timedelta

# FOMC scheduled meeting *start* dates, 2022-2026. Standard FOMC calendar.
_FOMC_STARTS = [
    date(2022, 1, 25), date(2022, 3, 15), date(2022, 5, 3), date(2022, 6, 14),
    date(2022, 7, 26), date(2022, 9, 20), date(2022, 11, 1), date(2022, 12, 13),
    date(2023, 1, 31), date(2023, 3, 21), date(2023, 5, 2), date(2023, 6, 13),
    date(2023, 7, 25), date(2023, 9, 19), date(2023, 10, 31), date(2023, 12, 12),
    date(2024, 1, 30), date(2024, 3, 19), date(2024, 4, 30), date(2024, 6, 11),
    date(2024, 7, 30), date(2024, 9, 17), date(2024, 11, 6), date(2024, 12, 17),
    date(2025, 1, 28), date(2025, 3, 18), date(2025, 5, 6), date(2025, 6, 17),
    date(2025, 7, 29), date(2025, 9, 16), date(2025, 10, 28), date(2025, 12, 9),
    date(2026, 1, 27), date(2026, 3, 17), date(2026, 4, 28), date(2026, 6, 16),
    date(2026, 7, 28), date(2026, 9, 15), date(2026, 10, 27), date(2026, 12, 8),
]
FOMC_DECISIONS = [d + timedelta(days=1) for d in _FOMC_STARTS]

# BLS CPI release schedule, 2026 (matches the sidebar catalyst dates,
# verified at bls.gov/schedule/2026).
CPI_DATES = [
    date(2026, 1, 13), date(2026, 2, 11), date(2026, 3, 11),
    date(2026, 4, 10), date(2026, 5, 12), date(2026, 6, 10),
    date(2026, 7, 14), date(2026, 8, 12), date(2026, 9, 11),
    date(2026, 10, 14), date(2026, 11, 10), date(2026, 12, 10),
]


def events_in_range(start, end) -> list[tuple[date, str, str]]:
    """[(date, label, kind)] with kind in {"fomc", "cpi"}, sorted by date.
    Accepts date/datetime/Timestamp bounds; never raises."""
    try:
        s = start.date() if hasattr(start, "date") else start
        e = end.date() if hasattr(end, "date") else end
    except Exception:
        return []
    out = ([(d, "FOMC decision", "fomc") for d in FOMC_DECISIONS if s <= d <= e]
           + [(d, "CPI release", "cpi") for d in CPI_DATES if s <= d <= e])
    return sorted(out)


def add_event_vlines(fig, start, end, max_lines: int = 60):
    """Add subtle vertical markers for FOMC/CPI events in [start, end].
    FOMC = gray dashed, CPI = light dotted. Mutates fig in place."""
    evts = events_in_range(start, end)[:max_lines]
    for d, label, kind in evts:
        try:
            # NB: pass an ISO string, not a datetime.date — Plotly's
            # add_vline raises TypeError in _get_subplot when x is a date
            # object on a Timestamp axis, which aborts the whole app.
            fig.add_vline(
                x=d.isoformat(), line_dash="dash" if kind == "fomc" else "dot",
                line_color=("rgba(150,150,150,0.55)" if kind == "fomc"
                            else "rgba(150,150,150,0.30)"),
                line_width=1)
        except Exception:
            # A single bad marker must never take down the app.
            continue
    return fig
