"""Yahoo Finance benchmark prices via yfinance."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Iterable

import pandas as pd
import yfinance as yf

from ..storage import PricePoint

LOG = logging.getLogger(__name__)


def fetch_yahoo_prices(
    tickers: Iterable[str],
    lookback_days: int = 400,
    source_label: str = "yahoo",
) -> list[PricePoint]:
    """Pull daily closes for each ticker.

    Uses yfinance's batch download. Returns adjusted-close values.
    """
    tickers = list(tickers)
    if not tickers:
        return []

    end = date.today()
    start = end - timedelta(days=lookback_days)

    try:
        raw = yf.download(
            tickers,
            start=start.isoformat(),
            end=end.isoformat(),
            auto_adjust=True,
            progress=False,
            group_by="ticker",
            threads=True,
        )
    except Exception as exc:  # noqa: BLE001
        LOG.warning("yfinance download failed: %s", exc)
        return []

    points: list[PricePoint] = []
    if isinstance(raw.columns, pd.MultiIndex):
        for ticker in tickers:
            if ticker not in raw.columns.get_level_values(0):
                continue
            series = raw[ticker]["Close"].dropna()
            for asof, value in series.items():
                points.append(
                    PricePoint(
                        symbol=ticker,
                        source=source_label,
                        asof=asof.date(),
                        nav=float(value),
                        currency=None,
                    )
                )
    else:
        # single ticker case
        series = raw["Close"].dropna()
        ticker = tickers[0]
        for asof, value in series.items():
            points.append(
                PricePoint(
                    symbol=ticker,
                    source=source_label,
                    asof=asof.date(),
                    nav=float(value),
                    currency=None,
                )
            )

    LOG.info("Yahoo: fetched %d points across %d tickers", len(points), len(tickers))
    return points
