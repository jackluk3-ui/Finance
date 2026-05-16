from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from manulife_analyzer.config import (
    AnalysisConfig,
    Fund,
    HttpConfig,
    ReportsConfig,
    ReportWindow,
    Settings,
)
from manulife_analyzer.storage import Database, MacroPoint, PricePoint


@pytest.fixture
def tmp_db(tmp_path) -> Database:
    return Database(tmp_path / "test.db")


@pytest.fixture
def sample_funds() -> list[Fund]:
    return [
        Fund(
            code="MGF-USEQ",
            isin="HK0000000001",
            name="Test US Equity",
            category="equity",
            region="us",
            currency="USD",
            benchmark="^GSPC",
        ),
        Fund(
            code="MGF-GLBD",
            isin="HK0000000002",
            name="Test Global Bond",
            category="bond",
            region="global",
            currency="USD",
            benchmark="AGG",
        ),
        Fund(
            code="MGF-USHY",
            isin="HK0000000003",
            name="Test US High Yield",
            category="bond",
            region="us",
            currency="USD",
            benchmark="HYG",
        ),
    ]


@pytest.fixture
def sample_settings(tmp_path, sample_funds) -> Settings:
    return Settings(
        http=HttpConfig(),
        storage_db=tmp_path / "manulife.db",
        analysis=AnalysisConfig(),
        fred_series={"DGS10": "10Y", "T10Y2Y": "Spread", "DFF": "Fed", "CPIAUCSL": "CPI"},
        benchmark_tickers=["^GSPC", "AGG"],
        reports=ReportsConfig(
            output_dir=tmp_path / "reports",
            weekly=ReportWindow(lookback_days=7, top_n_funds=3),
            monthly=ReportWindow(lookback_days=30, top_n_funds=3),
        ),
        funds=sample_funds,
    )


def _make_price_series(
    symbol: str,
    days: int = 400,
    start_price: float = 100.0,
    drift: float = 0.0003,
    vol: float = 0.012,
    seed: int = 1,
) -> list[PricePoint]:
    rng = np.random.default_rng(seed)
    dates = pd.date_range(end=pd.Timestamp.today().normalize(), periods=days, freq="D")
    rets = rng.normal(drift, vol, size=days)
    prices = start_price * np.exp(np.cumsum(rets))
    return [
        PricePoint(symbol=symbol, source="test", asof=d.date(), nav=float(p), currency="USD")
        for d, p in zip(dates, prices)
    ]


@pytest.fixture
def loaded_db(tmp_db: Database, sample_funds) -> Database:
    """A DB pre-loaded with synthetic price + macro data."""
    for i, fund in enumerate(sample_funds):
        # different drift/vol per fund so screening produces ranking
        drift = [0.0005, 0.0001, 0.0003][i]
        vol = [0.014, 0.005, 0.009][i]
        tmp_db.upsert_prices(_make_price_series(fund.code, drift=drift, vol=vol, seed=i + 1))

    tmp_db.upsert_prices(_make_price_series("^GSPC", drift=0.0004, vol=0.011, seed=99))

    # Macro: yield curve briefly inverts, CPI rising, fed funds rising then flat
    macro_dates = pd.date_range(end=pd.Timestamp.today().normalize(), periods=400, freq="D")
    tmp_db.upsert_macro(
        [MacroPoint("T10Y2Y", d.date(), -0.2 + (i / 400) * 0.5) for i, d in enumerate(macro_dates)]
    )
    tmp_db.upsert_macro(
        [MacroPoint("CPIAUCSL", d.date(), 300 + i * 0.05) for i, d in enumerate(macro_dates)]
    )
    tmp_db.upsert_macro(
        [MacroPoint("DFF", d.date(), 5.25 - max(0, (i - 200) / 400)) for i, d in enumerate(macro_dates)]
    )
    return tmp_db
