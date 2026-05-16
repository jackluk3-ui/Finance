from manulife_analyzer.analysis import build_all_portfolios
from manulife_analyzer.analysis.metrics import compute_fund_metrics, metrics_to_rows
from manulife_analyzer.config import PortfolioConfig


def _populate_metrics(db, funds):
    prices = db.prices_df()
    rows = []
    for fund in funds:
        slice_ = prices[prices["symbol"] == fund.code]
        m = compute_fund_metrics(slice_, fund.code, [7, 30, 90, 180, 365], 30, 90, 365)
        if m:
            rows.extend(metrics_to_rows(m))
    db.upsert_metrics([(s, mn, a if hasattr(a, "year") else a.date(), v) for s, mn, a, v in rows])


def test_build_all_horizons(loaded_db, sample_funds):
    _populate_metrics(loaded_db, sample_funds)
    metrics = loaded_db.metrics_df()
    cfg = PortfolioConfig()
    out = build_all_portfolios(metrics, sample_funds, cfg.horizons)
    assert set(out) == {"1m", "3m", "1y", "long_term"}

    for key, p in out.items():
        assert p.label
        assert 0 < len(p.holdings) <= cfg.horizons[key]["n_funds"]
        total = sum(h.weight for h in p.holdings)
        assert 0.99 < total < 1.01
        assert all(h.weight > 0 for h in p.holdings)
        # asset mix sums to ~1 too
        assert 0.99 < sum(p.asset_mix.values()) < 1.01


def test_long_term_holds_more_than_short(loaded_db, sample_funds):
    _populate_metrics(loaded_db, sample_funds)
    metrics = loaded_db.metrics_df()
    cfg = PortfolioConfig()
    out = build_all_portfolios(metrics, sample_funds, cfg.horizons)
    # long_term targets 8 funds but we only have 6 -> caps at 6
    assert len(out["long_term"].holdings) >= len(out["1m"].holdings)


def test_bond_floor_respected(loaded_db, sample_funds):
    _populate_metrics(loaded_db, sample_funds)
    metrics = loaded_db.metrics_df()
    cfg = PortfolioConfig()
    out = build_all_portfolios(metrics, sample_funds, cfg.horizons)
    long = out["long_term"]
    bond_weight = sum(h.weight for h in long.holdings if h.category == "bond")
    # long_term has bond_min=0.3 so at least one bond should be present
    bond_count = sum(1 for h in long.holdings if h.category == "bond")
    assert bond_count >= 1, f"expected bonds in long-term, weight={bond_weight}"
