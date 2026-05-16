from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from manulife_analyzer.config import (
    AnalysisConfig,
    Fund,
    HttpConfig,
    ManulifeConfig,
    PortfolioConfig,
    ReportsConfig,
    ReportWindow,
    Settings,
    ThemeConfig,
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
            name_zh="測試美國股票",
            category="equity",
            region="us",
            currency="USD",
            benchmark="^GSPC",
            risk_level=5,
        ),
        Fund(
            code="MGF-WTECH",
            isin="HK0000000004",
            name="Test World Technology",
            name_zh="測試世界科技",
            category="equity",
            region="global",
            currency="USD",
            benchmark="QQQ",
            theme="tech",
            risk_level=5,
        ),
        Fund(
            code="MGF-SEMI",
            isin="HK0000000005",
            name="Test Semiconductor",
            name_zh="測試半導體",
            category="equity",
            region="global",
            currency="USD",
            benchmark="SMH",
            theme="semiconductor",
            risk_level=5,
        ),
        Fund(
            code="MGF-GLBD",
            isin="HK0000000002",
            name="Test Global Bond",
            name_zh="測試環球債券",
            category="bond",
            region="global",
            currency="USD",
            benchmark="AGG",
            risk_level=2,
        ),
        Fund(
            code="MGF-USHY",
            isin="HK0000000003",
            name="Test US High Yield",
            name_zh="測試美國高收益",
            category="bond",
            region="us",
            currency="USD",
            benchmark="HYG",
            risk_level=3,
        ),
        Fund(
            code="MGF-BAL",
            isin="HK0000000006",
            name="Test Balanced",
            name_zh="測試平衡",
            category="balanced",
            region="global",
            currency="USD",
            benchmark="AOR",
            risk_level=3,
        ),
    ]


@pytest.fixture
def sample_settings(tmp_path, sample_funds) -> Settings:
    return Settings(
        http=HttpConfig(),
        manulife=ManulifeConfig(),
        storage_db=tmp_path / "manulife.db",
        analysis=AnalysisConfig(),
        portfolios=PortfolioConfig(),
        themes=ThemeConfig(),
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
    """A DB pre-loaded with synthetic price + macro + theme data."""
    # Funds: different drift/vol so ranking is meaningful
    fund_params = [
        (0.0005, 0.014),   # USEQ
        (0.0008, 0.018),   # WTECH (best return)
        (0.0009, 0.022),   # SEMI (highest return, also vol)
        (0.0001, 0.005),   # GLBD
        (0.0003, 0.009),   # USHY
        (0.0003, 0.008),   # BAL
    ]
    for i, fund in enumerate(sample_funds):
        drift, vol = fund_params[i]
        tmp_db.upsert_prices(_make_price_series(fund.code, drift=drift, vol=vol, seed=i + 1))

    # Benchmarks + theme ETFs
    for j, (sym, drift, vol) in enumerate([
        ("^GSPC", 0.0004, 0.011),
        ("SMH", 0.0010, 0.020),     # semis hot
        ("SOXX", 0.0010, 0.020),
        ("^SOX", 0.0010, 0.020),
        ("QQQ", 0.0007, 0.016),
        ("XLK", 0.0007, 0.016),
        ("AIQ", 0.0006, 0.018),
        ("BOTZ", 0.0006, 0.018),
        ("XLV", 0.0003, 0.012),
        ("IBB", 0.0003, 0.014),
        ("XLE", 0.0002, 0.018),
        ("USO", 0.0001, 0.020),
        ("KWEB", -0.0001, 0.025),
        ("MCHI", 0.0000, 0.020),
        ("GLD", 0.0002, 0.010),
    ]):
        tmp_db.upsert_prices(_make_price_series(sym, drift=drift, vol=vol, seed=100 + j))

    # Macro
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
