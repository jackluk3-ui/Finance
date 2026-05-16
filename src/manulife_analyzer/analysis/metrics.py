"""Per-fund return, volatility, Sharpe, drawdown."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

TRADING_DAYS = 252


@dataclass(frozen=True)
class FundMetrics:
    symbol: str
    asof: pd.Timestamp
    return_pct: dict[int, float]            # window_days -> total return
    vol_annualised: float                   # 30D vol annualised
    sharpe: float                           # 90D Sharpe
    max_drawdown_pct: float                 # over `drawdown_window_days`
    last_price: float


def _to_series(df: pd.DataFrame) -> pd.Series:
    """Take a price dataframe (asof, nav) -> sorted unique series."""
    s = df.set_index("asof")["nav"].sort_index()
    s = s[~s.index.duplicated(keep="last")]
    return s.asfreq("D").ffill()


def compute_fund_metrics(
    prices_df: pd.DataFrame,
    symbol: str,
    return_windows: list[int],
    vol_window: int,
    sharpe_window: int,
    drawdown_window: int,
    risk_free_annual: float = 0.04,
) -> FundMetrics | None:
    """Compute headline metrics for one symbol.

    `prices_df` is the slice for this symbol (columns: asof, nav).
    Returns None if there is not enough data to be meaningful.
    """
    if prices_df.empty:
        return None

    series = _to_series(prices_df)
    if len(series) < 30:
        return None

    asof = series.index[-1]
    last_price = float(series.iloc[-1])

    returns_pct: dict[int, float] = {}
    for w in return_windows:
        if len(series) > w:
            past = series.iloc[-1 - w]
            if past > 0:
                returns_pct[w] = float(series.iloc[-1] / past - 1.0)

    daily_ret = series.pct_change().dropna()

    vol_tail = daily_ret.tail(vol_window)
    vol_annualised = float(vol_tail.std() * np.sqrt(TRADING_DAYS)) if len(vol_tail) else float("nan")

    sharpe_tail = daily_ret.tail(sharpe_window)
    if len(sharpe_tail) >= 10 and sharpe_tail.std() > 0:
        excess = sharpe_tail.mean() * TRADING_DAYS - risk_free_annual
        sharpe = float(excess / (sharpe_tail.std() * np.sqrt(TRADING_DAYS)))
    else:
        sharpe = float("nan")

    dd_window = series.tail(drawdown_window)
    if len(dd_window) > 1:
        running_max = dd_window.cummax()
        drawdown = dd_window / running_max - 1.0
        max_dd = float(drawdown.min())
    else:
        max_dd = float("nan")

    return FundMetrics(
        symbol=symbol,
        asof=asof,
        return_pct=returns_pct,
        vol_annualised=vol_annualised,
        sharpe=sharpe,
        max_drawdown_pct=max_dd,
        last_price=last_price,
    )


def metrics_to_rows(m: FundMetrics) -> list[tuple[str, str, pd.Timestamp, float]]:
    """Flatten a FundMetrics into (symbol, metric, asof, value) rows for storage."""
    rows: list[tuple[str, str, pd.Timestamp, float]] = []
    asof = m.asof.date() if hasattr(m.asof, "date") else m.asof
    for w, val in m.return_pct.items():
        rows.append((m.symbol, f"return_{w}d", asof, val))
    rows.append((m.symbol, "vol_30d_annualised", asof, m.vol_annualised))
    rows.append((m.symbol, "sharpe_90d", asof, m.sharpe))
    rows.append((m.symbol, "max_drawdown_1y", asof, m.max_drawdown_pct))
    rows.append((m.symbol, "last_price", asof, m.last_price))
    return [(s, mn, a, v) for s, mn, a, v in rows if v == v]  # filter NaN
