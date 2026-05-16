"""Fetch Manulife-linked fund NAVs.

The HK fund-price page at https://www.manulife.com.hk/en/individual/services/forms-tools/fund-price.html
is the public, non-account NAV page used by distributors and clients. Its
internal data API delivers JSON. The exact endpoint changes from time to
time, so the fetcher is designed to be replaced: implement `fetch_nav_for`
to return a list of `PricePoint`s for a fund given its ISIN.

If your distributor agreement gives you an official feed (CSV, SFTP, API),
swap `ManulifeFundFetcher.fetch_nav_for` to read from it instead — that is
the recommended path for production use.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable

from bs4 import BeautifulSoup

from ..config import Fund, HttpConfig
from ..storage import PricePoint
from .http import HttpClient

LOG = logging.getLogger(__name__)

# Manulife HK publishes a JSON endpoint that backs the fund-price page. The
# field names and exact URL are subject to change. Override via the
# MANULIFE_NAV_ENDPOINT env var if needed.
DEFAULT_NAV_ENDPOINT = (
    "https://www.manulife.com.hk/content/dam/insurance/hk/en/documents/"
    "fund-prices/{isin}.json"
)


@dataclass
class ManulifeFundFetcher:
    http: HttpClient
    nav_endpoint: str = DEFAULT_NAV_ENDPOINT
    source_label: str = "manulife_hk"

    def fetch_nav_for(self, fund: Fund) -> list[PricePoint]:
        """Return historical NAV points for one fund.

        Tries:
          1. JSON endpoint (template substituted with ISIN)
          2. Fund's own page (`fund.manulife_url`), parsing the embedded table

        Returns an empty list on failure rather than raising; failures are
        logged. Upstream code can decide whether to abort or continue.
        """
        if not fund.isin and not fund.manulife_url:
            LOG.warning("Fund %s has no ISIN or URL; skipping", fund.code)
            return []

        try:
            data = self.http.get_json(self.nav_endpoint.format(isin=fund.isin))
            return list(self._parse_json(fund, data))
        except Exception as exc:  # noqa: BLE001
            LOG.info("JSON endpoint failed for %s (%s); trying HTML page", fund.code, exc)

        if fund.manulife_url:
            try:
                html = self.http.get(fund.manulife_url).decode("utf-8", errors="replace")
                return list(self._parse_html(fund, html))
            except Exception as exc:  # noqa: BLE001
                LOG.warning("HTML scrape failed for %s: %s", fund.code, exc)

        return []

    def _parse_json(self, fund: Fund, data: dict) -> Iterable[PricePoint]:
        """Parse Manulife's NAV JSON.

        Expected shape (subject to change — adjust if Manulife restructures):

            {
                "isin": "HK...",
                "currency": "USD",
                "prices": [
                    {"date": "2026-05-15", "nav": 12.345},
                    ...
                ]
            }
        """
        currency = data.get("currency") or fund.currency
        for row in data.get("prices", []):
            asof = _parse_date(row.get("date"))
            nav = row.get("nav") or row.get("price")
            if asof is None or nav is None:
                continue
            yield PricePoint(
                symbol=fund.code,
                source=self.source_label,
                asof=asof,
                nav=float(nav),
                currency=currency,
            )

    def _parse_html(self, fund: Fund, html: str) -> Iterable[PricePoint]:
        """Fallback HTML table parser.

        Looks for a `<table>` whose header includes a date column and a NAV
        column. Brittle by design — JSON should be preferred when available.
        """
        soup = BeautifulSoup(html, "lxml")
        for table in soup.find_all("table"):
            headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
            if not any("date" in h for h in headers):
                continue
            date_idx = next(i for i, h in enumerate(headers) if "date" in h)
            nav_idx = next(
                (i for i, h in enumerate(headers) if "nav" in h or "price" in h), None
            )
            if nav_idx is None:
                continue
            for tr in table.find_all("tr")[1:]:
                cells = [td.get_text(strip=True) for td in tr.find_all("td")]
                if len(cells) <= max(date_idx, nav_idx):
                    continue
                asof = _parse_date(cells[date_idx])
                try:
                    nav = float(cells[nav_idx].replace(",", ""))
                except ValueError:
                    continue
                if asof is None:
                    continue
                yield PricePoint(
                    symbol=fund.code,
                    source=self.source_label,
                    asof=asof,
                    nav=nav,
                    currency=fund.currency,
                )

    def fetch_many(self, funds: Iterable[Fund]) -> list[PricePoint]:
        out: list[PricePoint] = []
        for fund in funds:
            points = self.fetch_nav_for(fund)
            LOG.info("Manulife: %s -> %d points", fund.code, len(points))
            out.extend(points)
        return out


def _parse_date(text: str | None) -> date | None:
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            continue
    return None


def build_fetcher(
    http_cfg: HttpConfig,
    cache_dir=None,
) -> ManulifeFundFetcher:
    client = HttpClient(
        user_agent=http_cfg.user_agent,
        timeout=http_cfg.timeout,
        cache_hours=http_cfg.cache_hours,
        rate_limit_seconds=http_cfg.rate_limit_seconds,
        cache_dir=cache_dir,
    )
    return ManulifeFundFetcher(http=client)
