import pandas as pd

from manulife_analyzer.analysis.metrics import compute_fund_metrics, metrics_to_rows


def test_compute_fund_metrics(loaded_db):
    prices = loaded_db.prices_df("MGF-USEQ")
    m = compute_fund_metrics(
        prices,
        symbol="MGF-USEQ",
        return_windows=[7, 30, 90],
        vol_window=30,
        sharpe_window=90,
        drawdown_window=365,
    )
    assert m is not None
    assert 7 in m.return_pct and 30 in m.return_pct and 90 in m.return_pct
    assert m.vol_annualised > 0
    assert -1 < m.max_drawdown_pct <= 0  # drawdown is negative
    assert m.last_price > 0


def test_compute_returns_none_on_empty():
    empty = pd.DataFrame(columns=["asof", "nav"])
    assert compute_fund_metrics(empty, "X", [30], 30, 90, 365) is None


def test_metrics_to_rows_filters_nan(loaded_db):
    prices = loaded_db.prices_df("MGF-USEQ")
    m = compute_fund_metrics(prices, "MGF-USEQ", [30], 30, 90, 365)
    rows = metrics_to_rows(m)
    assert all(v == v for _, _, _, v in rows)
    metric_names = {r[1] for r in rows}
    assert "return_30d" in metric_names
    assert "vol_30d_annualised" in metric_names
