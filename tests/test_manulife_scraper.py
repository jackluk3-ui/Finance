"""Unit-test the Manulife fetcher with mocked HTTP — no network needed."""

from __future__ import annotations

import json
from datetime import date

import respx
from httpx import Response

from manulife_analyzer.config import Fund, HttpConfig, ManulifeConfig
from manulife_analyzer.data.manulife import ManulifeFundFetcher, build_fetcher


def _fund() -> Fund:
    return Fund(
        code="MGF-USEQ",
        isin="HK0000000001",
        name="Test US Equity",
        category="equity",
        region="us",
        currency="USD",
    )


@respx.mock
def test_fund_list_parses(tmp_path):
    fetcher = build_fetcher(
        HttpConfig(rate_limit_seconds=0.0),
        ManulifeConfig(),
        cache_dir=tmp_path / "cache",
    )
    payload = {
        "funds": [
            {
                "fundCode": "MGFAE",
                "fundNameEn": "Manulife Global Fund - Asian Equity",
                "fundNameTC": "宏利環球基金 - 亞洲股票",
                "isin": "HK0000000001",
                "currency": "USD",
                "category": "Equity",
                "region": "Asia",
                "nav": 12.34,
                "navDate": "2026-05-15",
            },
            {
                "fundCode": "MGFGB",
                "fundNameEn": "Manulife Global Fund - Global Bond",
                "fundNameTC": "宏利環球基金 - 環球債券",
                "isin": "HK0000000002",
                "currency": "USD",
                "category": "Bond",
                "region": "Global",
                "nav": 9.87,
                "navDate": "2026-05-15",
            },
        ]
    }
    respx.get("https://www.manulife.com.hk").mock(
        return_value=Response(200, content=json.dumps(payload).encode())
    )

    infos = fetcher.fetch_fund_list(product_id=16, product_name="宏利投資計劃")
    assert len(infos) == 2
    assert infos[0].code == "MGFAE"
    assert infos[0].name_zh == "宏利環球基金 - 亞洲股票"
    assert infos[0].category == "equity"
    assert infos[0].latest_nav == 12.34
    assert infos[0].latest_nav_date == date(2026, 5, 15)
    assert infos[1].category == "bond"


@respx.mock
def test_fund_list_handles_alternative_field_names(tmp_path):
    fetcher = build_fetcher(
        HttpConfig(rate_limit_seconds=0.0),
        ManulifeConfig(),
        cache_dir=tmp_path / "cache",
    )
    payload = {
        "data": [
            {
                "code": "X1",
                "name": "Fund X",
                "chineseName": "X 基金",
                "isin": "ISIN001",
                "ccy": "HKD",
                "assetClass": "Fixed Income",
                "geography": "Asia",
                "price": "10,234.50",
                "priceDate": "15/05/2026",
            }
        ]
    }
    respx.get("https://www.manulife.com.hk").mock(
        return_value=Response(200, content=json.dumps(payload).encode())
    )
    infos = fetcher.fetch_fund_list(product_id=16)
    assert len(infos) == 1
    assert infos[0].code == "X1"
    assert infos[0].latest_nav == 10234.5
    assert infos[0].latest_nav_date == date(2026, 5, 15)
    assert infos[0].category == "bond"


@respx.mock
def test_fetch_latest_navs_returns_price_points(tmp_path):
    fetcher = build_fetcher(
        HttpConfig(rate_limit_seconds=0.0),
        ManulifeConfig(),
        cache_dir=tmp_path / "cache",
    )
    respx.get("https://www.manulife.com.hk").mock(
        return_value=Response(
            200,
            content=json.dumps({
                "funds": [{
                    "fundCode": "X1", "fundNameEn": "Fund X", "isin": "ISIN001",
                    "currency": "USD", "category": "Equity", "region": "US",
                    "nav": 10.0, "navDate": "2026-05-15",
                }]
            }).encode(),
        )
    )
    points = fetcher.fetch_latest_navs({16: "宏利投資計劃"})
    assert len(points) == 1
    assert points[0].symbol == "X1"
    assert points[0].nav == 10.0


@respx.mock
def test_fund_list_failure_returns_empty(tmp_path):
    fetcher = build_fetcher(
        HttpConfig(rate_limit_seconds=0.0),
        ManulifeConfig(),
        cache_dir=tmp_path / "cache",
    )
    respx.get("https://www.manulife.com.hk").mock(return_value=Response(500))
    assert fetcher.fetch_fund_list(product_id=16) == []


def test_html_history_parser(tmp_path):
    fetcher = ManulifeFundFetcher(http=None, config=ManulifeConfig())
    html = """
    <html><body>
      <table>
        <tr><th>日期</th><th>NAV</th></tr>
        <tr><td>2026-05-14</td><td>12.34</td></tr>
        <tr><td>2026-05-15</td><td>12.50</td></tr>
      </table>
    </body></html>
    """
    points = list(fetcher._parse_html_table(_fund(), html))
    assert len(points) == 2
    assert points[1].nav == 12.50
