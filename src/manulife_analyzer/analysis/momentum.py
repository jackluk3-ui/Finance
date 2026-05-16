"""Cross-sectional momentum ranking across funds."""

from __future__ import annotations

import pandas as pd


def rank_momentum(metrics_df: pd.DataFrame, window_days: int = 90) -> pd.DataFrame:
    """Rank funds by total return over the given window.

    `metrics_df` is the long-format metrics table (symbol, metric, asof, value).
    Returns a sorted dataframe with columns: symbol, return, rank, percentile.
    """
    metric_name = f"return_{window_days}d"
    df = metrics_df[metrics_df["metric"] == metric_name]
    if df.empty:
        return pd.DataFrame(columns=["symbol", "return", "rank", "percentile"])

    latest = df.sort_values("asof").groupby("symbol").tail(1)[["symbol", "value"]]
    latest = latest.rename(columns={"value": "return"})
    latest = latest.sort_values("return", ascending=False).reset_index(drop=True)
    latest["rank"] = latest.index + 1
    n = len(latest)
    latest["percentile"] = (n - latest["rank"] + 1) / n if n else 0.0
    return latest
