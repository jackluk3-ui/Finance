"""Rank-and-screen funds by combined momentum + risk signals.

This produces *candidates for further review* — not buy/sell instructions.
Final calls remain with the licensed adviser.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ..config import Fund


@dataclass(frozen=True)
class ScreenResult:
    symbol: str
    name: str
    category: str
    region: str
    score: float                # higher = more interesting
    return_30d: float | None
    vol_30d: float | None
    sharpe_90d: float | None
    max_drawdown_1y: float | None
    rationale: str


def _pivot_metrics(metrics_df: pd.DataFrame) -> pd.DataFrame:
    """Long metrics table -> wide table (one row per symbol, latest values)."""
    if metrics_df.empty:
        return pd.DataFrame()
    latest = metrics_df.sort_values("asof").groupby(["symbol", "metric"]).tail(1)
    wide = latest.pivot(index="symbol", columns="metric", values="value")
    return wide


def screen_funds(
    metrics_df: pd.DataFrame,
    funds: list[Fund],
    top_n: int = 5,
    horizon: str = "short_term",
) -> list[ScreenResult]:
    """Score and rank funds.

    Scoring (`short_term`):
      + 30-day return (z-score)
      - 30-day annualised vol (z-score)
      + 90-day Sharpe (z-score)
      - max drawdown magnitude

    `short_term` weights momentum heavily; `long_term` would weight risk-adjusted
    return more. We expose `horizon` to make this explicit even though we only
    implement one weighting today.
    """
    wide = _pivot_metrics(metrics_df)
    if wide.empty:
        return []

    fund_lookup = {f.code: f for f in funds}

    # Only score symbols that are in our fund universe (skip benchmarks).
    wide = wide.loc[wide.index.isin(fund_lookup)]
    if wide.empty:
        return []

    needed = ["return_30d", "vol_30d_annualised", "sharpe_90d", "max_drawdown_1y"]
    for col in needed:
        if col not in wide.columns:
            wide[col] = float("nan")

    def z(col: pd.Series) -> pd.Series:
        s = col.dropna()
        if len(s) < 2 or s.std() == 0:
            return pd.Series(0.0, index=col.index)
        return (col - s.mean()) / s.std()

    if horizon == "short_term":
        w_ret, w_vol, w_sharpe, w_dd = 0.5, 0.2, 0.2, 0.1
    else:
        w_ret, w_vol, w_sharpe, w_dd = 0.2, 0.2, 0.5, 0.1

    score = (
        w_ret * z(wide["return_30d"])
        - w_vol * z(wide["vol_30d_annualised"])
        + w_sharpe * z(wide["sharpe_90d"])
        - w_dd * z(-wide["max_drawdown_1y"])  # bigger drawdown -> worse
    )

    wide = wide.assign(score=score).sort_values("score", ascending=False)

    out: list[ScreenResult] = []
    for symbol, row in wide.head(top_n).iterrows():
        fund = fund_lookup[symbol]
        rationale = _rationale(row, horizon)
        out.append(
            ScreenResult(
                symbol=symbol,
                name=fund.name,
                category=fund.category,
                region=fund.region,
                score=float(row["score"]),
                return_30d=_safe(row.get("return_30d")),
                vol_30d=_safe(row.get("vol_30d_annualised")),
                sharpe_90d=_safe(row.get("sharpe_90d")),
                max_drawdown_1y=_safe(row.get("max_drawdown_1y")),
                rationale=rationale,
            )
        )
    return out


def _safe(value) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def _rationale(row: pd.Series, horizon: str) -> str:
    parts: list[str] = []
    r30 = row.get("return_30d")
    if r30 == r30 and r30 is not None:
        parts.append(f"30D return {r30 * 100:+.1f}%")
    vol = row.get("vol_30d_annualised")
    if vol == vol and vol is not None:
        parts.append(f"vol {vol * 100:.1f}%")
    sharpe = row.get("sharpe_90d")
    if sharpe == sharpe and sharpe is not None:
        parts.append(f"Sharpe 90D {sharpe:.2f}")
    dd = row.get("max_drawdown_1y")
    if dd == dd and dd is not None:
        parts.append(f"max DD {dd * 100:.1f}%")
    horizon_label = "short-term momentum lens" if horizon == "short_term" else "risk-adjusted lens"
    return f"{horizon_label}: " + ", ".join(parts) if parts else horizon_label
