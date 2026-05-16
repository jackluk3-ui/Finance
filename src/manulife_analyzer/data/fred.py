"""FRED (Federal Reserve Economic Data) fetcher."""

from __future__ import annotations

import logging
from datetime import date, timedelta

from ..storage import MacroPoint

LOG = logging.getLogger(__name__)


def fetch_fred_series(
    series_ids: list[str],
    api_key: str | None,
    lookback_days: int = 365 * 3,
) -> list[MacroPoint]:
    """Pull each FRED series back `lookback_days`.

    Requires a free API key. If `api_key` is None this returns [] and logs a
    warning rather than crashing — the pipeline can still run on Yahoo data
    alone.
    """
    if not api_key:
        LOG.warning("FRED_API_KEY not set; skipping FRED fetch")
        return []

    from fredapi import Fred  # imported lazily so missing key doesn't break imports

    fred = Fred(api_key=api_key)
    start = (date.today() - timedelta(days=lookback_days)).isoformat()
    out: list[MacroPoint] = []
    for sid in series_ids:
        try:
            series = fred.get_series(sid, observation_start=start)
        except Exception as exc:  # noqa: BLE001
            LOG.warning("FRED fetch failed for %s: %s", sid, exc)
            continue
        for ts, value in series.dropna().items():
            out.append(
                MacroPoint(series_id=sid, asof=ts.date(), value=float(value))
            )
        LOG.info("FRED: %s -> %d points", sid, len(series.dropna()))
    return out
