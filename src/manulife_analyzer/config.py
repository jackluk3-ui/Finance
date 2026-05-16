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
    category: str
    region: str
    currency: str
    benchmark: str | None = None
    manulife_url: str | None = None


@dataclass(frozen=True)
class HttpConfig:
    timeout: int = 20
    user_agent: str = "ManulifeAnalyzer/0.1"
    cache_hours: int = 24
    rate_limit_seconds: float = 1.5


@dataclass(frozen=True)
class AnalysisConfig:
    return_windows_days: list[int] = field(default_factory=lambda: [7, 30, 90, 180, 365])
    volatility_window_days: int = 30
    sharpe_window_days: int = 90
    risk_free_series: str = "DGS3MO"
    momentum_window_days: int = 90
    drawdown_window_days: int = 365


@dataclass(frozen=True)
class ReportWindow:
    lookback_days: int
    top_n_funds: int


@dataclass(frozen=True)
class ReportsConfig:
    output_dir: Path
    weekly: ReportWindow
    monthly: ReportWindow


@dataclass(frozen=True)
class Settings:
    http: HttpConfig
    storage_db: Path
    analysis: AnalysisConfig
    fred_series: dict[str, str]
    benchmark_tickers: list[str]
    reports: ReportsConfig
    funds: list[Fund]

    @property
    def fred_api_key(self) -> str | None:
        return os.getenv("FRED_API_KEY") or None


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
    )

    funds = [Fund(**f) for f in funds_raw.get("funds", [])]

    return Settings(
        http=http,
        storage_db=storage_db,
        analysis=analysis,
        fred_series=dict(raw.get("fred_series", {})),
        benchmark_tickers=list(raw.get("benchmark_tickers", [])),
        reports=reports,
        funds=funds,
    )
