"""Macro regime signals from FRED series."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class MacroSummary:
    yield_curve_spread: float | None        # T10Y2Y latest
    yield_curve_inverted: bool
    cpi_yoy: float | None                   # year-over-year CPI change
    cpi_trend: str                          # "rising" | "falling" | "flat"
    fed_funds_rate: float | None
    fed_funds_trend: str                    # "rising" | "falling" | "flat"
    unemployment_rate: float | None
    commentary: list[str]                   # human-readable bullet points


def _latest(df: pd.DataFrame, series_id: str) -> tuple[pd.Timestamp, float] | None:
    sub = df[df["series_id"] == series_id].sort_values("asof")
    if sub.empty:
        return None
    last = sub.iloc[-1]
    return last["asof"], float(last["value"])


def _trend(df: pd.DataFrame, series_id: str, lookback_days: int = 180) -> str:
    sub = df[df["series_id"] == series_id].sort_values("asof")
    if len(sub) < 2:
        return "flat"
    cutoff = sub["asof"].max() - pd.Timedelta(days=lookback_days)
    recent = sub[sub["asof"] >= cutoff]
    if len(recent) < 2:
        return "flat"
    first = float(recent.iloc[0]["value"])
    last = float(recent.iloc[-1]["value"])
    diff = last - first
    # treat anything within 0.1 absolute units as "flat" (suitable for rates / %)
    if abs(diff) < 0.1:
        return "flat"
    return "rising" if diff > 0 else "falling"


def _cpi_yoy(df: pd.DataFrame) -> float | None:
    sub = df[df["series_id"] == "CPIAUCSL"].sort_values("asof")
    if len(sub) < 13:
        return None
    last = sub.iloc[-1]
    # find observation ~365 days earlier
    target_date = last["asof"] - pd.Timedelta(days=365)
    prior = sub[sub["asof"] <= target_date].tail(1)
    if prior.empty:
        return None
    return float(last["value"] / float(prior.iloc[0]["value"]) - 1.0)


def summarize_macro(macro_df: pd.DataFrame) -> MacroSummary:
    """Build a high-level macro snapshot.

    Expects the long-format macro table (series_id, asof, value).
    """
    commentary: list[str] = []

    spread = _latest(macro_df, "T10Y2Y")
    spread_val = spread[1] if spread else None
    inverted = bool(spread_val is not None and spread_val < 0)
    if spread_val is not None:
        if inverted:
            commentary.append(
                f"Yield curve inverted: 10Y-2Y spread at {spread_val:.2f}%. "
                "Historically a recession lead indicator."
            )
        else:
            commentary.append(
                f"Yield curve positive: 10Y-2Y spread at {spread_val:.2f}%."
            )

    cpi_yoy = _cpi_yoy(macro_df)
    cpi_trend = _trend(macro_df, "CPIAUCSL", lookback_days=180)
    if cpi_yoy is not None:
        commentary.append(
            f"US CPI year-over-year: {cpi_yoy * 100:.2f}% (recent trend: {cpi_trend})."
        )

    fed = _latest(macro_df, "DFF")
    fed_val = fed[1] if fed else None
    fed_trend = _trend(macro_df, "DFF", lookback_days=180)
    if fed_val is not None:
        commentary.append(
            f"Fed funds rate at {fed_val:.2f}% (180-day trend: {fed_trend})."
        )

    unemp = _latest(macro_df, "UNRATE")
    unemp_val = unemp[1] if unemp else None
    if unemp_val is not None:
        commentary.append(f"US unemployment at {unemp_val:.1f}%.")

    return MacroSummary(
        yield_curve_spread=spread_val,
        yield_curve_inverted=inverted,
        cpi_yoy=cpi_yoy,
        cpi_trend=cpi_trend,
        fed_funds_rate=fed_val,
        fed_funds_trend=fed_trend,
        unemployment_rate=unemp_val,
        commentary=commentary,
    )
