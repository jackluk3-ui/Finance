from datetime import date

from manulife_analyzer.storage import MacroPoint, PricePoint


def test_upsert_prices_inserts_and_updates(tmp_db):
    p1 = PricePoint("AAA", "test", date(2026, 1, 1), 10.0, "USD")
    p2 = PricePoint("AAA", "test", date(2026, 1, 1), 11.0, "USD")  # same key, new value
    p3 = PricePoint("AAA", "test", date(2026, 1, 2), 12.0, "USD")
    assert tmp_db.upsert_prices([p1]) == 1
    assert tmp_db.upsert_prices([p2, p3]) == 2

    df = tmp_db.prices_df("AAA")
    assert len(df) == 2
    assert float(df[df["asof"] == "2026-01-01"]["nav"].iloc[0]) == 11.0


def test_upsert_macro(tmp_db):
    pts = [MacroPoint("DGS10", date(2026, 1, 1), 4.5), MacroPoint("DGS10", date(2026, 1, 2), 4.6)]
    assert tmp_db.upsert_macro(pts) == 2
    df = tmp_db.macro_df("DGS10")
    assert len(df) == 2
    assert df.iloc[-1]["value"] == 4.6


def test_metrics_roundtrip(tmp_db):
    tmp_db.upsert_metrics([("AAA", "return_30d", date(2026, 5, 1), 0.05)])
    df = tmp_db.metrics_df("return_30d")
    assert len(df) == 1
    assert df.iloc[0]["value"] == 0.05
