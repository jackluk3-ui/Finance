"""World Bank indicators (free, no key).

API: https://api.worldbank.org/v2/country/{code}/indicator/{indicator}?format=json
"""

from __future__ import annotations

import logging
from datetime import date

from ..storage import MacroPoint
from .http import HttpClient

LOG = logging.getLogger(__name__)

WB_BASE = "https://api.worldbank.org/v2"

# A short curated set of useful indicators
DEFAULT_INDICATORS = {
    "NY.GDP.MKTP.KD.ZG": "GDP growth (annual %)",
    "FP.CPI.TOTL.ZG": "Inflation, consumer prices (annual %)",
}

DEFAULT_COUNTRIES = ["USA", "CHN", "JPN", "DEU", "HKG"]


def fetch_world_bank(
    http: HttpClient,
    countries: list[str] | None = None,
    indicators: dict[str, str] | None = None,
) -> list[MacroPoint]:
    countries = countries or DEFAULT_COUNTRIES
    indicators = indicators or DEFAULT_INDICATORS

    out: list[MacroPoint] = []
    for country in countries:
        for ind_id in indicators:
            url = f"{WB_BASE}/country/{country}/indicator/{ind_id}"
            try:
                payload = http.get_json(url, params={"format": "json", "per_page": 60})
            except Exception as exc:  # noqa: BLE001
                LOG.warning("World Bank fetch failed (%s/%s): %s", country, ind_id, exc)
                continue

            if not (isinstance(payload, list) and len(payload) >= 2):
                continue
            for row in payload[1] or []:
                value = row.get("value")
                year = row.get("date")
                if value is None or not year:
                    continue
                try:
                    asof = date(int(year), 12, 31)
                except ValueError:
                    continue
                series_id = f"WB:{country}:{ind_id}"
                out.append(MacroPoint(series_id=series_id, asof=asof, value=float(value)))
    LOG.info("World Bank: %d total points", len(out))
    return out
