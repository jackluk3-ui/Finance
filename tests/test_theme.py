from manulife_analyzer.analysis import build_theme_spotlights
from manulife_analyzer.analysis.metrics import compute_fund_metrics, metrics_to_rows
from manulife_analyzer.config import ThemeConfig


def _populate_metrics(db, funds):
    prices = db.prices_df()
    rows = []
    # all symbols (incl benchmarks/themes)
    for sym in prices["symbol"].unique():
        slice_ = prices[prices["symbol"] == sym]
        m = compute_fund_metrics(slice_, sym, [7, 30, 90, 180, 365], 30, 90, 365)
        if m:
            rows.extend(metrics_to_rows(m))
    db.upsert_metrics([(s, mn, a if hasattr(a, "year") else a.date(), v) for s, mn, a, v in rows])


def test_theme_spotlight_detects_exposure(loaded_db, sample_funds):
    _populate_metrics(loaded_db, sample_funds)
    metrics = loaded_db.metrics_df()
    cfg = ThemeConfig()
    spots = build_theme_spotlights(metrics, cfg.themes, sample_funds)

    by_key = {s.key: s for s in spots}
    # We have a fund tagged theme=semiconductor -> has_exposure True
    assert by_key["semiconductor"].has_exposure is True
    # 中文 label populated
    assert "半導體" in by_key["semiconductor"].label_zh
    # tech also has exposure (WTECH fund)
    assert by_key["tech"].has_exposure is True
    # healthcare/energy/etc. have no exposed funds in our sample universe
    assert by_key["healthcare"].has_exposure is False


def test_theme_spotlight_returns_present(loaded_db, sample_funds):
    _populate_metrics(loaded_db, sample_funds)
    metrics = loaded_db.metrics_df()
    cfg = ThemeConfig()
    spots = build_theme_spotlights(metrics, cfg.themes, sample_funds)
    # At least one theme has a 30-day return computed
    assert any(s.return_30d is not None for s in spots)
