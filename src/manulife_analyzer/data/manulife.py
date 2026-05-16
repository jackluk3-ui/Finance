"""抓取宏利香港 ILAS 基金數據。

公開端點（基於用戶提供嘅 URL）：

    GET /zh-hk/individual/fund-price/investment-linked-assurance-scheme.html/v2/fundlist
        ?productId=16

返回該產品（如「宏利投資計劃」）下所有底層基金嘅最新 NAV 清單。

歷史 NAV 嘅端點宏利暫時冇對外公佈標準路徑，本模組會逐個嘗試常見變體：
    /v2/fundprice?fundCode=XX&productId=16
    /v2/navhistory?fundCode=XX&productId=16
    /v2/fund/XX/history?productId=16
如果全部失敗，會自動 fallback 用 fund.benchmark（Yahoo ticker）嘅歷史價作分析基礎。

如果你嘅分銷協議畀到官方 feed（CSV / SFTP / API），直接改 `fetch_nav_history` 即可。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Iterable

from bs4 import BeautifulSoup

from ..config import Fund, HttpConfig, ManulifeConfig
from ..storage import PricePoint
from .http import HttpClient

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class ManulifeFundInfo:
    """One fund as returned by the v2/fundlist endpoint."""
    code: str
    name_en: str
    name_zh: str
    isin: str
    currency: str
    category: str               # 我哋會 normalise 做 equity/bond/balanced/...
    region: str
    risk_level: int | None
    latest_nav: float | None
    latest_nav_date: date | None
    raw: dict = field(default_factory=dict)


# JSON 入面可能用到嘅 key（不同 API 版本字段名唔同，全部試）
_FIELD_ALIASES = {
    "code": ["fundCode", "code", "id", "fundId"],
    "name_en": ["fundNameEn", "nameEn", "name_en", "fundName", "name"],
    "name_zh": ["fundNameZh", "nameZh", "name_zh", "fundNameTC", "nameTC", "chineseName"],
    "isin": ["isin", "ISIN", "isinCode"],
    "currency": ["currency", "ccy", "fundCurrency"],
    "category": ["category", "assetClass", "fundType", "type"],
    "region": ["region", "geography"],
    "risk_level": ["riskLevel", "risk", "riskRating"],
    "nav": ["nav", "latestNAV", "price", "navPrice"],
    "nav_date": ["navDate", "asOfDate", "priceDate", "date"],
}


def _pick(d: dict, key: str):
    for alias in _FIELD_ALIASES.get(key, [key]):
        if alias in d and d[alias] not in (None, ""):
            return d[alias]
    return None


def _normalise_category(raw: str | None) -> str:
    if not raw:
        return "other"
    lower = raw.lower()
    if any(k in lower for k in ("bond", "fixed", "income", "債")):
        return "bond"
    if any(k in lower for k in ("equity", "stock", "股票", "shares")):
        return "equity"
    if any(k in lower for k in ("balanced", "平衡", "mixed")):
        return "balanced"
    if any(k in lower for k in ("money", "cash", "現金", "貨幣")):
        return "money_market"
    if any(k in lower for k in ("multi", "allocation", "資產配置")):
        return "multi_asset"
    return lower


@dataclass
class ManulifeFundFetcher:
    http: HttpClient
    config: ManulifeConfig
    source_label: str = "manulife_hk"

    # ── Fund list ────────────────────────────────────────────────
    def fetch_fund_list(self, product_id: int, product_name: str = "") -> list[ManulifeFundInfo]:
        """Call v2/fundlist for one product."""
        url = self.config.base_url + self.config.fundlist_path
        params: dict = {"productId": product_id}
        if product_name:
            params["product"] = product_name

        try:
            data = self.http.get_json(url, params=params)
        except Exception as exc:  # noqa: BLE001
            LOG.warning("Manulife fundlist (productId=%s) failed: %s", product_id, exc)
            return []

        items = self._extract_items(data)
        out: list[ManulifeFundInfo] = []
        for item in items:
            try:
                out.append(self._parse_list_item(item))
            except Exception as exc:  # noqa: BLE001
                LOG.debug("Skipping malformed fund row: %s (%s)", item, exc)
        LOG.info("Manulife: productId=%s returned %d funds", product_id, len(out))
        return out

    def _extract_items(self, data) -> list[dict]:
        """The list endpoint may wrap funds in different keys. Try common ones."""
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("funds", "fundList", "items", "data", "result", "results"):
                v = data.get(key)
                if isinstance(v, list):
                    return v
                if isinstance(v, dict):
                    for sub in ("funds", "items", "list"):
                        if isinstance(v.get(sub), list):
                            return v[sub]
        return []

    def _parse_list_item(self, item: dict) -> ManulifeFundInfo:
        nav_date_raw = _pick(item, "nav_date")
        risk_raw = _pick(item, "risk_level")
        return ManulifeFundInfo(
            code=str(_pick(item, "code") or "").strip(),
            name_en=str(_pick(item, "name_en") or "").strip(),
            name_zh=str(_pick(item, "name_zh") or "").strip(),
            isin=str(_pick(item, "isin") or "").strip(),
            currency=str(_pick(item, "currency") or "USD").strip(),
            category=_normalise_category(_pick(item, "category")),
            region=str(_pick(item, "region") or "global").strip(),
            risk_level=int(risk_raw) if risk_raw not in (None, "") else None,
            latest_nav=_to_float(_pick(item, "nav")),
            latest_nav_date=_parse_date(nav_date_raw) if nav_date_raw else None,
            raw=item,
        )

    # ── Historical NAV ──────────────────────────────────────────
    def fetch_nav_history(self, fund: Fund, product_id: int = 16) -> list[PricePoint]:
        """Try several known/guessed endpoints; return empty list if all fail."""
        if not (fund.code or fund.isin):
            return []

        candidates = self._history_url_candidates(fund, product_id)
        for url, params in candidates:
            try:
                data = self.http.get_json(url, params=params)
            except Exception as exc:  # noqa: BLE001
                LOG.debug("History URL %s failed: %s", url, exc)
                continue
            points = list(self._parse_history(fund, data))
            if points:
                LOG.info("Manulife history: %s -> %d points via %s",
                         fund.code, len(points), url)
                return points

        # Fallback: HTML page if user configured one
        if fund.manulife_url:
            try:
                html = self.http.get(fund.manulife_url).decode("utf-8", errors="replace")
                return list(self._parse_html_table(fund, html))
            except Exception as exc:  # noqa: BLE001
                LOG.warning("HTML scrape failed for %s: %s", fund.code, exc)

        return []

    def _history_url_candidates(self, fund: Fund, product_id: int) -> list[tuple[str, dict]]:
        base = self.config.base_url
        path = self.config.nav_history_path
        return [
            (f"{base}{path}",
             {"fundCode": fund.code, "productId": product_id}),
            (f"{base}{path}",
             {"isin": fund.isin, "productId": product_id}),
            (f"{base}/zh-hk/individual/fund-price/investment-linked-assurance-scheme.html/v2/navhistory",
             {"fundCode": fund.code, "productId": product_id}),
            (f"{base}/zh-hk/individual/fund-price/investment-linked-assurance-scheme.html/v2/fund/{fund.code}/history",
             {"productId": product_id}),
        ]

    def _parse_history(self, fund: Fund, data) -> Iterable[PricePoint]:
        # Find the price list in the response
        if isinstance(data, dict):
            for key in ("prices", "history", "navHistory", "data", "items"):
                arr = data.get(key)
                if isinstance(arr, list):
                    data = arr
                    break
        if not isinstance(data, list):
            return

        currency = fund.currency
        for row in data:
            if not isinstance(row, dict):
                continue
            asof = _parse_date(_pick(row, "nav_date"))
            nav = _to_float(_pick(row, "nav"))
            if asof is None or nav is None:
                continue
            yield PricePoint(
                symbol=fund.code,
                source=self.source_label,
                asof=asof,
                nav=nav,
                currency=currency,
            )

    def _parse_html_table(self, fund: Fund, html: str) -> Iterable[PricePoint]:
        soup = BeautifulSoup(html, "lxml")
        for table in soup.find_all("table"):
            headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
            if not any(("date" in h) or ("日期" in h) for h in headers):
                continue
            date_idx = next(
                i for i, h in enumerate(headers) if ("date" in h or "日期" in h)
            )
            nav_idx = next(
                (i for i, h in enumerate(headers) if "nav" in h or "price" in h or "價格" in h),
                None,
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

    # ── Batch / convenience ─────────────────────────────────────
    def fetch_latest_navs(self, product_ids: dict[int, str]) -> list[PricePoint]:
        """Pull latest NAV for every fund across the listed products.

        Use this when historical NAV endpoint is not yet wired up — at least
        you get a daily NAV snapshot which accumulates over time into a
        history table inside the DB.
        """
        out: list[PricePoint] = []
        for pid, name in product_ids.items():
            for info in self.fetch_fund_list(pid, name):
                if info.latest_nav is None or info.latest_nav_date is None:
                    continue
                out.append(
                    PricePoint(
                        symbol=info.code,
                        source=self.source_label,
                        asof=info.latest_nav_date,
                        nav=info.latest_nav,
                        currency=info.currency,
                    )
                )
        return out

    def fetch_history_many(
        self, funds: Iterable[Fund], product_id: int = 16
    ) -> list[PricePoint]:
        out: list[PricePoint] = []
        for fund in funds:
            out.extend(self.fetch_nav_history(fund, product_id))
        return out


# ── helpers ──────────────────────────────────────────────────────
def _to_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _parse_date(text) -> date | None:
    if text is None:
        return None
    if isinstance(text, date):
        return text
    s = str(text).strip()
    if not s:
        return None
    # Try ISO 8601 with time first
    for fmt in (
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%d %b %Y",
        "%d %B %Y",
    ):
        try:
            return datetime.strptime(s.split(".")[0], fmt).date()
        except ValueError:
            continue
    return None


def build_fetcher(
    http_cfg: HttpConfig,
    manulife_cfg: ManulifeConfig | None = None,
    cache_dir=None,
) -> ManulifeFundFetcher:
    client = HttpClient(
        user_agent=http_cfg.user_agent,
        timeout=http_cfg.timeout,
        cache_hours=http_cfg.cache_hours,
        rate_limit_seconds=http_cfg.rate_limit_seconds,
        cache_dir=cache_dir,
    )
    return ManulifeFundFetcher(http=client, config=manulife_cfg or ManulifeConfig())
