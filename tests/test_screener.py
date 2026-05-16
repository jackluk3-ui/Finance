from manulife_analyzer.analysis import screen_funds
from manulife_analyzer.analysis.metrics import compute_fund_metrics, metrics_to_rows
from manulife_analyzer.storage import Database


def _populate_metrics(db: Database, funds) -> None:
    prices = db.prices_df()
    rows = []
    for fund in funds:
        slice_ = prices[prices["symbol"] == fund.code]
        m = compute_fund_metrics(slice_, fund.code, [7, 30, 90, 180, 365], 30, 90, 365)
        if m:
            rows.extend(metrics_to_rows(m))
    db.upsert_metrics([(s, mn, a if hasattr(a, "year") else a.date(), v) for s, mn, a, v in rows])


def test_screener_returns_ranked_candidates(loaded_db, sample_funds):
    _populate_metrics(loaded_db, sample_funds)
    metrics_df = loaded_db.metrics_df()

    results = screen_funds(metrics_df, sample_funds, top_n=3, horizon="short_term")
    assert 1 <= len(results) <= 3
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)
    for r in results:
        assert r.name
        assert r.rationale


def test_screener_handles_no_metrics(sample_funds):
    import pandas as pd

    empty = pd.DataFrame(columns=["symbol", "metric", "asof", "value"])
    assert screen_funds(empty, sample_funds) == []
