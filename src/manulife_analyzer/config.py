"""Load and validate config from YAML + environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

load_dotenv()

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"
DATA_DIR = REPO_ROOT / "data"


@dataclass(frozen=True)
class Fund:
    code: str
    isin: str
    name: str
    category: str           # equity / bond / balanced / money_market / multi_asset
    region: str             # us / asia / greater_china / global / emerging / etc.
    currency: str
    benchmark: str | None = None       # Yahoo ticker for analytics fallback
    manulife_url: str | None = None
    name_zh: str | None = None         # 中文名稱
    theme: str | None = None           # 板塊主題：semiconductor / ai / healthcare / tech / esg / ...
    risk_level: int | None = None      # 宏利風險評級 1-5


@dataclass(frozen=True)
class HttpConfig:
    timeout: int = 20
    user_agent: str = "ManulifeAnalyzer/0.1"
    cache_hours: int = 24
    rate_limit_seconds: float = 1.5


@dataclass(frozen=True)
class ManulifeConfig:
    base_url: str = "https://www.manulife.com.hk"
    fundlist_path: str = (
        "/zh-hk/individual/fund-price/investment-linked-assurance-scheme.html/v2/fundlist"
    )
    nav_history_path: str = (
        "/zh-hk/individual/fund-price/investment-linked-assurance-scheme.html/v2/fundprice"
    )
    products: dict[int, str] = field(
        default_factory=lambda: {16: "宏利投資計劃"}
    )


@dataclass(frozen=True)
class AnalysisConfig:
    return_windows_days: list[int] = field(default_factory=lambda: [7, 30, 90, 180, 365])
    volatility_window_days: int = 30
    sharpe_window_days: int = 90
    risk_free_series: str = "DGS3MO"
    momentum_window_days: int = 90
    drawdown_window_days: int = 365


@dataclass(frozen=True)
class PortfolioConfig:
    """Targets for each horizon portfolio.

    horizon_key -> dict with:
      n_funds: int          how many funds to hold
      equity_min/max: float overall equity ceiling (0-1)
      bond_min: float       overall bond floor (0-1)
      scoring: str          "momentum_30d" | "momentum_90d" | "sharpe_90d" | "diversified"
    """
    horizons: dict[str, dict] = field(
        default_factory=lambda: {
            "1m": {
                "label_zh": "短炒組合（1個月）",
                "n_funds": 3,
                "equity_max": 1.0,
                "bond_min": 0.0,
                "scoring": "momentum_30d",
                "description_zh": "以最近30日表現排名揀基金，波動風險高，適合短線進取客戶",
            },
            "3m": {
                "label_zh": "短中線組合（3個月）",
                "n_funds": 5,
                "equity_max": 0.8,
                "bond_min": 0.1,
                "scoring": "momentum_90d",
                "description_zh": "結合30日加90日動量，加入少量債券對沖波動",
            },
            "1y": {
                "label_zh": "中長線組合（1年）",
                "n_funds": 6,
                "equity_max": 0.7,
                "bond_min": 0.2,
                "scoring": "sharpe_90d",
                "description_zh": "以風險調整後回報（夏普比率）排名，分散行業同地區",
            },
            "long_term": {
                "label_zh": "長線組合（5年以上）",
                "n_funds": 8,
                "equity_max": 0.6,
                "bond_min": 0.3,
                "scoring": "diversified",
                "description_zh": "策略性資產配置，跨資產類別分散，控制最大回撤",
            },
        }
    )


@dataclass(frozen=True)
class ThemeConfig:
    """Theme benchmark watch — pulled from Yahoo so we can flag hot sectors even
    if the user's fund universe has no exposure to them."""
    themes: dict[str, dict] = field(
        default_factory=lambda: {
            "semiconductor": {"label_zh": "半導體", "tickers": ["SMH", "SOXX", "^SOX"]},
            "tech": {"label_zh": "科技板塊", "tickers": ["QQQ", "XLK"]},
            "ai": {"label_zh": "人工智能", "tickers": ["BOTZ", "AIQ"]},
            "healthcare": {"label_zh": "醫療保健", "tickers": ["XLV", "IBB"]},
            "energy": {"label_zh": "能源", "tickers": ["XLE", "USO"]},
            "china_tech": {"label_zh": "中概科技", "tickers": ["KWEB", "MCHI"]},
            "gold": {"label_zh": "黃金", "tickers": ["GLD"]},
        }
    )


@dataclass(frozen=True)
class ReportWindow:
    lookback_days: int
    top_n_funds: int


@dataclass(frozen=True)
class ReportsConfig:
    output_dir: Path
    weekly: ReportWindow
    monthly: ReportWindow
    language: str = "zh-HK"  # zh-HK (繁體) / en


@dataclass(frozen=True)
class Settings:
    http: HttpConfig
    manulife: ManulifeConfig
    storage_db: Path
    analysis: AnalysisConfig
    portfolios: PortfolioConfig
    themes: ThemeConfig
    fred_series: dict[str, str]
    benchmark_tickers: list[str]
    reports: ReportsConfig
    funds: list[Fund]

    @property
    def fred_api_key(self) -> str | None:
        return os.getenv("FRED_API_KEY") or None

    @property
    def theme_tickers(self) -> list[str]:
        out: list[str] = []
        for cfg in self.themes.themes.values():
            out.extend(cfg["tickers"])
        return sorted(set(out))


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open() as fh:
        return yaml.safe_load(fh) or {}


def _env_override(value: Any, env_key: str, caster=str):
    raw = os.getenv(env_key)
    if raw is None:
        return value
    try:
        return caster(raw)
    except (TypeError, ValueError):
        return value


def load_settings(
    settings_path: Path | None = None,
    funds_path: Path | None = None,
) -> Settings:
    settings_path = settings_path or CONFIG_DIR / "settings.yaml"
    funds_path = funds_path or CONFIG_DIR / "funds.yaml"

    raw = _read_yaml(settings_path)
    funds_raw = _read_yaml(funds_path)

    http_raw = raw.get("http", {})
    http = HttpConfig(
        timeout=_env_override(http_raw.get("timeout", 20), "HTTP_TIMEOUT", int),
        user_agent=_env_override(
            http_raw.get("user_agent", "ManulifeAnalyzer/0.1"),
            "HTTP_USER_AGENT",
        ),
        cache_hours=int(http_raw.get("cache_hours", 24)),
        rate_limit_seconds=float(http_raw.get("rate_limit_seconds", 1.5)),
    )

    m_raw = raw.get("manulife", {})
    products_raw = m_raw.get("products", {16: "宏利投資計劃"})
    manulife = ManulifeConfig(
        base_url=m_raw.get("base_url", ManulifeConfig().base_url),
        fundlist_path=m_raw.get("fundlist_path", ManulifeConfig().fundlist_path),
        nav_history_path=m_raw.get("nav_history_path", ManulifeConfig().nav_history_path),
        products={int(k): v for k, v in products_raw.items()},
    )

    storage_db = REPO_ROOT / raw.get("storage", {}).get("database_path", "data/manulife.db")

    a_raw = raw.get("analysis", {})
    analysis = AnalysisConfig(
        return_windows_days=list(a_raw.get("return_windows_days", [7, 30, 90, 180, 365])),
        volatility_window_days=int(a_raw.get("volatility_window_days", 30)),
        sharpe_window_days=int(a_raw.get("sharpe_window_days", 90)),
        risk_free_series=a_raw.get("risk_free_series", "DGS3MO"),
        momentum_window_days=int(a_raw.get("momentum_window_days", 90)),
        drawdown_window_days=int(a_raw.get("drawdown_window_days", 365)),
    )

    portfolios = PortfolioConfig(
        horizons=raw.get("portfolios", PortfolioConfig().horizons)
    )

    themes = ThemeConfig(
        themes=raw.get("themes", ThemeConfig().themes)
    )

    r_raw = raw.get("reports", {})
    reports = ReportsConfig(
        output_dir=REPO_ROOT / r_raw.get("output_dir", "data/reports"),
        weekly=ReportWindow(
            lookback_days=int(r_raw.get("weekly", {}).get("lookback_days", 7)),
            top_n_funds=int(r_raw.get("weekly", {}).get("top_n_funds", 5)),
        ),
        monthly=ReportWindow(
            lookback_days=int(r_raw.get("monthly", {}).get("lookback_days", 30)),
            top_n_funds=int(r_raw.get("monthly", {}).get("top_n_funds", 10)),
        ),
        language=r_raw.get("language", "zh-HK"),
    )

    funds = [Fund(**f) for f in funds_raw.get("funds", [])]

    return Settings(
        http=http,
        manulife=manulife,
        storage_db=storage_db,
        analysis=analysis,
        portfolios=portfolios,
        themes=themes,
        fred_series=dict(raw.get("fred_series", {})),
        benchmark_tickers=list(raw.get("benchmark_tickers", [])),
        reports=reports,
        funds=funds,
    )
