"""板塊主題監察 — 即使客戶基金池冇半導體基金，
都會用 SMH / SOXX / QQQ 等 ETF 睇住板塊熱度。

這樣解答客戶「最近半導體咁勁，點解你冇推?」嘅問題：
- 如果基金池冇相關基金 → 報告會主動標示「板塊有機會，但你目前基金池冇曝險」
- 如果基金池有相關基金 → 報告會顯示你個基金 vs 板塊基準嘅相對表現
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ..config import Fund


@dataclass(frozen=True)
class ThemeSpotlight:
    key: str
    label_zh: str
    tickers: list[str]
    return_30d: float | None
    return_90d: float | None
    return_180d: float | None
    vol_30d: float | None
    has_exposure: bool              # 基金池入面有冇相關 theme 基金
    exposed_funds: list[str]        # 基金中文名 list
    commentary_zh: str


def _latest_series_metric(
    metrics_df: pd.DataFrame, symbol: str, metric: str
) -> float | None:
    sub = metrics_df[
        (metrics_df["symbol"] == symbol) & (metrics_df["metric"] == metric)
    ].sort_values("asof")
    if sub.empty:
        return None
    v = float(sub.iloc[-1]["value"])
    return v if v == v else None


def _agg_metric(metrics_df: pd.DataFrame, tickers: list[str], metric: str) -> float | None:
    vals = [v for v in (_latest_series_metric(metrics_df, t, metric) for t in tickers) if v is not None]
    if not vals:
        return None
    return sum(vals) / len(vals)


def build_theme_spotlights(
    metrics_df: pd.DataFrame,
    themes_cfg: dict[str, dict],
    funds: list[Fund],
) -> list[ThemeSpotlight]:
    spotlights: list[ThemeSpotlight] = []
    for key, cfg in themes_cfg.items():
        tickers = cfg.get("tickers", [])
        label = cfg.get("label_zh", key)
        r30 = _agg_metric(metrics_df, tickers, "return_30d")
        r90 = _agg_metric(metrics_df, tickers, "return_90d")
        r180 = _agg_metric(metrics_df, tickers, "return_180d")
        vol = _agg_metric(metrics_df, tickers, "vol_30d_annualised")

        exposed = [f for f in funds if f.theme == key]
        has_exposure = bool(exposed)

        commentary = _theme_commentary(label, r30, r90, has_exposure, exposed)

        spotlights.append(
            ThemeSpotlight(
                key=key,
                label_zh=label,
                tickers=tickers,
                return_30d=r30,
                return_90d=r90,
                return_180d=r180,
                vol_30d=vol,
                has_exposure=has_exposure,
                exposed_funds=[f.name_zh or f.name for f in exposed],
                commentary_zh=commentary,
            )
        )

    # 排序：30 日表現高排前
    spotlights.sort(key=lambda s: (s.return_30d or -999), reverse=True)
    return spotlights


def _theme_commentary(
    label: str,
    r30: float | None,
    r90: float | None,
    has_exposure: bool,
    exposed: list[Fund],
) -> str:
    if r30 is None and r90 is None:
        return f"{label}：暫時冇足夠歷史數據評估。"
    parts: list[str] = [f"{label}"]
    if r30 is not None:
        parts.append(f"30日 {r30 * 100:+.1f}%")
    if r90 is not None:
        parts.append(f"90日 {r90 * 100:+.1f}%")
    base = "，".join(parts)
    if has_exposure:
        names = "、".join(f.name_zh or f.name for f in exposed[:3])
        return f"{base}。客戶基金池已有相關曝險：{names}。"
    if r30 is not None and r30 > 0.05:
        return f"{base}。⚠️ 板塊強勢但你目前基金池冇相關曝險，可考慮加入主題基金。"
    return f"{base}。客戶基金池冇相關曝險。"
