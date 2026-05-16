"""用合成數據生成示例報告。

執行：`uv run python scripts/demo_report.py`

呢個係畀你喺未接通真實宏利 / FRED 數據之前，預覽報告長咩樣。
寫入 ./data/demo_reports/。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from manulife_analyzer.config import (
    ReportsConfig,
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


def _drift_vol_for(fund) -> tuple[float, float]:
    """假設嘅 drift / vol：科技/半導體強勢，債券平穩。"""
    if fund.theme == "semiconductor":
        return 0.0011, 0.022
    if fund.theme in ("tech", "ai"):
        return 0.0009, 0.018
    if fund.theme == "healthcare":
        return 0.0004, 0.013
    if fund.theme == "energy":
        return -0.0001, 0.020
    if fund.category == "equity":
        return 0.0004, 0.013
    if fund.category == "bond":
        return 0.00015, 0.005
    if fund.category == "money_market":
        return 0.00012, 0.0008
    return 0.0003, 0.010


def main() -> None:
    base = load_settings()

    out_dir = Path("data/demo_reports")
    db_path = out_dir / "demo.db"
    if db_path.exists():
        db_path.unlink()

    settings = Settings(
        http=base.http,
        manulife=base.manulife,
        storage_db=db_path,
        analysis=base.analysis,
        portfolios=base.portfolios,
        themes=base.themes,
        fred_series=base.fred_series,
        benchmark_tickers=base.benchmark_tickers,
        reports=ReportsConfig(
            output_dir=out_dir,
            weekly=base.reports.weekly,
            monthly=base.reports.monthly,
            language=base.reports.language,
        ),
        funds=base.funds,
    )

    db = Database(settings.storage_db)

    # 基金合成價格
    for i, fund in enumerate(settings.funds):
        drift, vol = _drift_vol_for(fund)
        db.upsert_prices(_synthetic_prices(fund.code, 400, drift, vol, seed=i + 1))

    # 板塊 ETF 合成價格（半導體最強，跑贏大盤）
    theme_specs = {
        "SMH": (0.0012, 0.022), "SOXX": (0.0012, 0.022), "^SOX": (0.0012, 0.022),
        "QQQ": (0.0008, 0.016), "XLK": (0.0008, 0.016),
        "AIQ": (0.0007, 0.018), "BOTZ": (0.0007, 0.018),
        "XLV": (0.0003, 0.012), "IBB": (0.0003, 0.014),
        "XLE": (0.0001, 0.018), "USO": (-0.0001, 0.022),
        "KWEB": (-0.0001, 0.025), "MCHI": (0.0000, 0.020),
        "GLD": (0.0003, 0.010),
    }
    seed = 200
    for sym, (d, v) in theme_specs.items():
        db.upsert_prices(_synthetic_prices(sym, 400, d, v, seed=seed))
        seed += 1

    # 大盤基準（fund benchmarks）
    bench_specs = {
        "^GSPC": (0.0005, 0.011), "^STOXX50E": (0.0003, 0.012), "^HSI": (0.0001, 0.014),
        "000300.SS": (0.0001, 0.013), "^N225": (0.0004, 0.013),
        "^RUT": (0.0004, 0.014), "AAXJ": (0.0002, 0.013), "EWJ": (0.0004, 0.012),
        "INDA": (0.0006, 0.014), "AGG": (0.00015, 0.005), "HYG": (0.0003, 0.008),
        "EMB": (0.0002, 0.009), "BND": (0.00015, 0.005), "AOR": (0.0003, 0.008),
        "DX-Y.NYB": (0.0001, 0.005), "GDX": (0.0003, 0.018), "XME": (0.0001, 0.018),
        "IGF": (0.0003, 0.011), "BIL": (0.00012, 0.0008),
    }
    seed = 300
    for sym, (d, v) in bench_specs.items():
        db.upsert_prices(_synthetic_prices(sym, 400, d, v, seed=seed))
        seed += 1

    # 宏觀
    dates = pd.date_range(end=pd.Timestamp.today().normalize(), periods=400, freq="D")
    db.upsert_macro([
        MacroPoint("T10Y2Y", d.date(), -0.3 + (i / 400) * 0.5) for i, d in enumerate(dates)
    ])
    db.upsert_macro([
        MacroPoint("CPIAUCSL", d.date(), 305 + i * 0.04) for i, d in enumerate(dates)
    ])
    db.upsert_macro([
        MacroPoint("DFF", d.date(), 5.25 - max(0.0, (i - 250) / 200))
        for i, d in enumerate(dates)
    ])
    db.upsert_macro([
        MacroPoint("UNRATE", d.date(), 3.8 + (i / 400) * 0.4) for i, d in enumerate(dates)
    ])

    weekly = build_report(db, settings, "weekly")
    monthly = build_report(db, settings, "monthly")
    print(f"週報: {weekly}")
    print(f"月報: {monthly}")


if __name__ == "__main__":
    main()
