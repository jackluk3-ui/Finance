"""Unit-test the Manulife fetcher with mocked HTTP — no network needed."""

from __future__ import annotations

import json
from datetime import date

import respx
from httpx import Response

from manulife_analyzer.config import Fund, HttpConfig
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
def test_fetcher_parses_json(tmp_path, monkeypatch):
    # point the http cache at a temp dir so tests don't clobber real cache
    monkeypatch.chdir(tmp_path)
    fetcher = build_fetcher(HttpConfig(rate_limit_seconds=0.0), cache_dir=tmp_path / "cache")

    payload = {
        "isin": "HK0000000001",
        "currency": "USD",
        "prices": [
            {"date": "2026-05-14", "nav": 12.34},
            {"date": "2026-05-15", "nav": 12.50},
        ],
    }
    route = respx.get("https://www.manulife.com.hk").mock(
        return_value=Response(200, content=json.dumps(payload).encode())
    )

    points = fetcher.fetch_nav_for(_fund())
    assert route.called
    assert len(points) == 2
    assert points[0].asof == date(2026, 5, 14)
    assert points[0].nav == 12.34
    assert points[0].currency == "USD"
    assert points[1].nav == 12.50


@respx.mock
def test_fetcher_swallows_failure(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    fetcher = build_fetcher(HttpConfig(rate_limit_seconds=0.0), cache_dir=tmp_path / "cache")
    respx.get("https://www.manulife.com.hk").mock(return_value=Response(404))
    # fund has no manulife_url fallback either
    assert fetcher.fetch_nav_for(_fund()) == []


def test_html_parser_extracts_nav_table(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    fetcher = ManulifeFundFetcher(http=None)  # html parser doesn't need http
    html = """
    <html><body>
      <table>
        <tr><th>Date</th><th>NAV</th></tr>
        <tr><td>2026-05-14</td><td>12.34</td></tr>
        <tr><td>2026-05-15</td><td>12.50</td></tr>
      </table>
    </body></html>
    """
    points = list(fetcher._parse_html(_fund(), html))
    assert len(points) == 2
    assert points[1].nav == 12.50
