"""Generate a sample weekly + monthly report using synthetic data.

Run with: `uv run python scripts/demo_report.py`

This is here so you can see what the reports look like before wiring up real
data sources (FRED key, Manulife feed). It writes HTML to ./data/reports/.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from manulife_analyzer.config import (
    AnalysisConfig,
    Fund,
    HttpConfig,
    ReportsConfig,
    ReportWindow,
    Settings,
    load_settings,
)
from manulife_analyzer.reports import build_report
from manulife_analyzer.storage import Database, MacroPoint, PricePoint


def _synthetic_prices(symbol: str, days: int, drift: float, vol: float, seed: int):
    rng = np.random.default_rng(seed)
    dates = pd.date_range(end=pd.Timestamp.today().normalize(), periods=days, freq="D")
    rets = rng.normal(drift, vol, size=days)
    prices = 100.0 * np.exp(np.cumsum(rets))
    return [
        PricePoint(symbol=symbol, source="demo", asof=d.date(), nav=float(p), currency="USD")
        for d, p in zip(dates, prices)
    ]


def main() -> None:
    base = load_settings()  # uses real config/funds.yaml so the demo reflects your universe

    out_dir = Path("data/demo_reports")
    db_path = out_dir / "demo.db"
    if db_path.exists():
        db_path.unlink()

    settings = Settings(
        http=base.http,
        storage_db=db_path,
        analysis=base.analysis,
        fred_series=base.fred_series,
        benchmark_tickers=base.benchmark_tickers,
        reports=ReportsConfig(
            output_dir=out_dir,
            weekly=base.reports.weekly,
            monthly=base.reports.monthly,
        ),
        funds=base.funds,
    )

    db = Database(settings.storage_db)

    rng_seed = 1
    for fund in settings.funds:
        # equity funds: more drift + more vol; bonds: less; balanced: in between
        if fund.category == "equity":
            drift, vol = 0.0005, 0.013
        elif fund.category == "bond":
            drift, vol = 0.00015, 0.004
        else:
            drift, vol = 0.0003, 0.008
        db.upsert_prices(_synthetic_prices(fund.code, 400, drift, vol, rng_seed))
        rng_seed += 1

    dates = pd.date_range(end=pd.Timestamp.today().normalize(), periods=400, freq="D")
    # mild inversion early, normalising recently
    db.upsert_macro([
        MacroPoint("T10Y2Y", d.date(), -0.3 + (i / 400) * 0.5)
        for i, d in enumerate(dates)
    ])
    # CPI gently rising
    db.upsert_macro([
        MacroPoint("CPIAUCSL", d.date(), 305 + i * 0.04) for i, d in enumerate(dates)
    ])
    # Fed funds at 5.25, then easing
    db.upsert_macro([
        MacroPoint("DFF", d.date(), 5.25 - max(0.0, (i - 250) / 200))
        for i, d in enumerate(dates)
    ])
    db.upsert_macro([
        MacroPoint("UNRATE", d.date(), 3.8 + (i / 400) * 0.4) for i, d in enumerate(dates)
    ])

    weekly = build_report(db, settings, "weekly")
    monthly = build_report(db, settings, "monthly")
    print(f"Weekly:  {weekly}")
    print(f"Monthly: {monthly}")


if __name__ == "__main__":
    main()
