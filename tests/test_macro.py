from manulife_analyzer.analysis.macro import summarize_macro


def test_macro_summary_handles_inversion(loaded_db):
    summary = summarize_macro(loaded_db.macro_df())
    assert summary.yield_curve_spread is not None
    assert summary.cpi_yoy is not None
    assert summary.fed_funds_rate is not None
    assert summary.cpi_trend in {"rising", "falling", "flat"}
    assert len(summary.commentary) >= 1


def test_macro_summary_empty():
    import pandas as pd

    empty = pd.DataFrame(columns=["series_id", "asof", "value"])
    summary = summarize_macro(empty)
    assert summary.yield_curve_spread is None
    assert summary.commentary == []
