"""Assemble the report dataframe + charts and render via Jinja."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Literal

import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..analysis import (
    build_all_portfolios,
    build_theme_spotlights,
    compute_fund_metrics,
    summarize_macro,
)
from ..analysis.metrics import metrics_to_rows
from ..config import Settings
from ..storage import Database
from .charts import macro_chart, return_bar_chart

TEMPLATE_DIR = Path(__file__).parent / "templates"
ReportKind = Literal["weekly", "monthly"]

# 顯示順序
PORTFOLIO_ORDER = ["1m", "3m", "1y", "long_term"]

# FRED series id -> 中文圖表標題 / 縱軸標籤
MACRO_CHART_LABELS = {
    "T10Y2Y": ("美國 10Y-2Y 國債利差 (%)", "利差 (%)"),
    "CPIAUCSL": ("美國消費物價指數 (CPI)", "指數"),
    "DFF": ("聯邦基金有效利率 (%)", "%"),
}


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(["html"]),
    )


def _ensure_metrics(db: Database, settings: Settings) -> None:
    """Compute metrics for every tracked symbol (funds + benchmarks + themes)."""
    prices = db.prices_df()
    if prices.empty:
        return

    a = settings.analysis
    risk_free_annual = _latest_risk_free(db, a.risk_free_series)

    # Compute metrics for funds AND for every benchmark / theme ticker we have
    # prices on so the theme spotlight can use them.
    symbols = set(f.code for f in settings.funds) | set(prices["symbol"].unique())

    rows: list[tuple] = []
    for symbol in symbols:
        slice_ = prices[prices["symbol"] == symbol]
        m = compute_fund_metrics(
            slice_,
            symbol=symbol,
            return_windows=a.return_windows_days,
            vol_window=a.volatility_window_days,
            sharpe_window=a.sharpe_window_days,
            drawdown_window=a.drawdown_window_days,
            risk_free_annual=risk_free_annual,
        )
        if m is None:
            continue
        rows.extend(metrics_to_rows(m))

    if rows:
        prepared = [(s, mn, _to_date(a), v) for s, mn, a, v in rows]
        db.upsert_metrics(prepared)


def _to_date(value) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    return pd.Timestamp(value).date()


def _latest_risk_free(db: Database, series_id: str) -> float:
    df = db.macro_df(series_id)
    if df.empty:
        return 0.04
    last = float(df.sort_values("asof").iloc[-1]["value"])
    return last / 100.0 if last > 1 else last


def _fund_table_rows(db: Database, settings: Settings, lookback_days: int) -> list[dict]:
    metrics = db.metrics_df()
    if metrics.empty:
        return []
    latest = metrics.sort_values("asof").groupby(["symbol", "metric"]).tail(1)
    wide = latest.pivot(index="symbol", columns="metric", values="value")

    nearest_window = min(
        settings.analysis.return_windows_days,
        key=lambda w: abs(w - lookback_days),
    )
    return_col = f"return_{nearest_window}d"
    return_180_col = "return_180d"

    rows: list[dict] = []
    for fund in settings.funds:
        if fund.code not in wide.index:
            continue
        r = wide.loc[fund.code]
        rows.append(
            {
                "name": fund.name,
                "name_zh": fund.name_zh,
                "category": fund.category,
                "region": fund.region,
                "theme": fund.theme,
                "return_pct": _f(r.get(return_col)),
                "return_180d": _f(r.get(return_180_col)),
                "vol": _f(r.get("vol_30d_annualised")),
                "sharpe": _f(r.get("sharpe_90d")),
                "max_dd": _f(r.get("max_drawdown_1y")),
            }
        )
    rows.sort(key=lambda x: (x["return_pct"] is None, -(x["return_pct"] or 0)))
    return rows


def _f(value) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def _macro_charts(db: Database) -> list[str]:
    df = db.macro_df()
    if df.empty:
        return []
    charts: list[str] = []
    for sid, (title, ylabel) in MACRO_CHART_LABELS.items():
        sub = df[df["series_id"] == sid].sort_values("asof")
        if sub.empty:
            continue
        series = sub.set_index("asof")["value"].tail(365 * 2)
        charts.append(macro_chart(series, title, ylabel))
    return charts


def _return_chart(table_rows: list[dict], title: str) -> str | None:
    rows = [r for r in table_rows if r["return_pct"] is not None]
    if not rows:
        return None
    df = pd.DataFrame(
        [{"label": r["name_zh"] or r["name"], "return_pct": r["return_pct"]} for r in rows]
    )
    return return_bar_chart(df, value_col="return_pct", label_col="label", title=title)


def _volatility_alert(table_rows: list[dict]) -> str | None:
    high_vol = [r for r in table_rows if (r["vol"] or 0) > 0.25]
    if not high_vol:
        return None
    names = "、".join((r["name_zh"] or r["name"]) for r in high_vol[:3])
    return (
        f"有 {len(high_vol)} 隻基金年化波動超過 25% — "
        f"留意倉位集中度（例如：{names}）。"
    )


def build_report(
    db: Database,
    settings: Settings,
    kind: ReportKind,
    output_dir: Path | None = None,
) -> Path:
    _ensure_metrics(db, settings)

    window = settings.reports.weekly if kind == "weekly" else settings.reports.monthly
    output_dir = output_dir or settings.reports.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    metrics = db.metrics_df()
    macro = summarize_macro(db.macro_df())
    fund_table = _fund_table_rows(db, settings, window.lookback_days)
    return_chart = _return_chart(
        fund_table, f"基金過去 {window.lookback_days} 日回報"
    )

    themes = build_theme_spotlights(metrics, settings.themes.themes, settings.funds)
    portfolios = build_all_portfolios(
        metrics, settings.funds, settings.portfolios.horizons
    )

    title = ("每週" if kind == "weekly" else "每月") + "市場觀察報告"

    context: dict = {
        "title": title,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "lookback_days": window.lookback_days,
        "fund_count": len(settings.funds),
        "macro": macro,
        "macro_charts": _macro_charts(db),
        "fund_table": fund_table,
        "return_chart": return_chart,
        "themes": themes,
        "portfolios": portfolios,
        "portfolio_order": PORTFOLIO_ORDER,
        "volatility_alert": _volatility_alert(fund_table),
    }

    template_name = f"{kind}.html.j2"
    html = _env().get_template(template_name).render(**context)

    today = date.today().isoformat()
    out_path = output_dir / f"{today}-{kind}.html"
    out_path.write_text(html, encoding="utf-8")
    return out_path
