"""組合構建 — 為 4 個時間框架（1個月 / 3個月 / 1年 / 長線）生成基金組合建議。

設計重點：
1. 唔同 horizon 用唔同打分公式
   - 1m  : 30日動量為主（短線進取）
   - 3m  : 30日+90日動量混合
   - 1y  : 90日夏普比率（risk-adjusted）
   - long: 跨資產類別 diversified 評分（注重最大回撤同分散）
2. 跟 PortfolioConfig 入面嘅 equity_max / bond_min 做硬性約束
3. 權重用 score-proportional（score 越高 weight 越大），加總 100%
4. 每個組合附帶人類可讀嘅 rationale（中文）

注意：呢度只係 *候選建議*，唔係買賣指令。最終要由持牌人簽字。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..config import Fund


@dataclass(frozen=True)
class PortfolioHolding:
    symbol: str
    name: str
    name_zh: str
    category: str
    region: str
    theme: str | None
    weight: float                   # 0.0 - 1.0
    score: float
    return_30d: float | None
    return_90d: float | None
    sharpe_90d: float | None
    vol_30d: float | None


@dataclass(frozen=True)
class Portfolio:
    horizon_key: str
    label: str
    description: str
    holdings: list[PortfolioHolding]
    expected_vol: float | None      # 簡化估算：加權平均年化波動
    expected_return_annual: float | None  # 用 90D 收益年化作粗估
    asset_mix: dict[str, float]     # category -> weight
    rationale: list[str]            # 中文逐點解釋


# ── helpers ──────────────────────────────────────────────
def _pivot_metrics(metrics_df: pd.DataFrame) -> pd.DataFrame:
    if metrics_df.empty:
        return pd.DataFrame()
    latest = metrics_df.sort_values("asof").groupby(["symbol", "metric"]).tail(1)
    return latest.pivot(index="symbol", columns="metric", values="value")


def _zscore(s: pd.Series) -> pd.Series:
    clean = s.dropna()
    if len(clean) < 2 or clean.std() == 0:
        return pd.Series(0.0, index=s.index)
    return (s - clean.mean()) / clean.std()


def _score(wide: pd.DataFrame, scoring: str) -> pd.Series:
    """Higher = better."""
    if scoring == "momentum_30d":
        return _zscore(wide.get("return_30d", pd.Series()))
    if scoring == "momentum_90d":
        return (
            0.5 * _zscore(wide.get("return_30d", pd.Series()))
            + 0.5 * _zscore(wide.get("return_90d", pd.Series()))
        )
    if scoring == "sharpe_90d":
        return _zscore(wide.get("sharpe_90d", pd.Series()))
    if scoring == "diversified":
        # 強調風險調整 + 低回撤；返 / 波 / 回撤 三者平均
        s_ret = _zscore(wide.get("return_180d", pd.Series()))
        s_sharpe = _zscore(wide.get("sharpe_90d", pd.Series()))
        # 回撤越細越好（drawdown 為負值，越接近 0 越好）
        s_dd = _zscore(wide.get("max_drawdown_1y", pd.Series()))
        return 0.3 * s_ret + 0.5 * s_sharpe + 0.2 * s_dd
    return pd.Series(0.0, index=wide.index)


def _enforce_constraints(
    ranked: list[tuple[str, float, Fund]],
    equity_max: float,
    bond_min: float,
    n: int,
) -> list[tuple[str, float, Fund]]:
    """Greedy: 順序入選，但跟蹤 asset class 比例。"""
    chosen: list[tuple[str, float, Fund]] = []
    eq_count = bond_count = 0
    target_bond = max(int(round(bond_min * n)), 1 if bond_min > 0 else 0)

    # 先嘗試填曬目標債券名額（按排名揀 bond）
    for sym, score, fund in ranked:
        if bond_count >= target_bond:
            break
        if fund.category == "bond":
            chosen.append((sym, score, fund))
            bond_count += 1

    used = {c[0] for c in chosen}
    # 然後按排名順序填其餘
    for sym, score, fund in ranked:
        if len(chosen) >= n:
            break
        if sym in used:
            continue
        if fund.category == "equity":
            if (eq_count + 1) / n > equity_max:
                continue
            eq_count += 1
        chosen.append((sym, score, fund))
        used.add(sym)

    # 仍未夠數 -> 放寬約束補齊
    for sym, score, fund in ranked:
        if len(chosen) >= n:
            break
        if sym not in used:
            chosen.append((sym, score, fund))
            used.add(sym)

    return chosen


def _to_weights(scores: list[float]) -> list[float]:
    """Map raw scores (can be negative) to positive weights summing to 1."""
    if not scores:
        return []
    arr = np.array(scores, dtype=float)
    # shift so min is 0.5 -> always positive, preserves ranking
    shifted = arr - arr.min() + 0.5
    weights = shifted / shifted.sum()
    return weights.tolist()


def _safe(value) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def _build_rationale(
    horizon: str,
    holdings: list[PortfolioHolding],
    description: str,
    asset_mix: dict[str, float],
) -> list[str]:
    bullets = [description]
    eq_pct = asset_mix.get("equity", 0) * 100
    bd_pct = asset_mix.get("bond", 0) * 100
    bal_pct = (asset_mix.get("balanced", 0) + asset_mix.get("multi_asset", 0)) * 100
    bullets.append(
        f"資產分配：股票 {eq_pct:.0f}%、債券 {bd_pct:.0f}%、平衡/多元資產 {bal_pct:.0f}%"
    )
    themes = {h.theme for h in holdings if h.theme}
    if themes:
        bullets.append("板塊佈局：" + "、".join(sorted(themes)))
    if holdings:
        top = holdings[0]
        if top.return_30d is not None:
            bullets.append(
                f"頭號倉位 {top.name_zh or top.name}（{top.weight * 100:.1f}%），"
                f"30日表現 {top.return_30d * 100:+.1f}%"
            )
    return bullets


def build_portfolio(
    metrics_df: pd.DataFrame,
    funds: list[Fund],
    horizon_key: str,
    horizon_cfg: dict,
) -> Portfolio | None:
    wide = _pivot_metrics(metrics_df)
    if wide.empty:
        return None

    fund_lookup = {f.code: f for f in funds}
    wide = wide.loc[wide.index.isin(fund_lookup)]
    if wide.empty:
        return None

    for col in ("return_30d", "return_90d", "return_180d", "sharpe_90d",
                "vol_30d_annualised", "max_drawdown_1y"):
        if col not in wide.columns:
            wide[col] = float("nan")

    scores = _score(wide, horizon_cfg.get("scoring", "sharpe_90d"))
    ranked_all = sorted(
        [
            (sym, float(scores.get(sym, 0.0)), fund_lookup[sym])
            for sym in wide.index
        ],
        key=lambda x: x[1],
        reverse=True,
    )

    chosen = _enforce_constraints(
        ranked_all,
        equity_max=float(horizon_cfg.get("equity_max", 1.0)),
        bond_min=float(horizon_cfg.get("bond_min", 0.0)),
        n=int(horizon_cfg.get("n_funds", 5)),
    )
    if not chosen:
        return None

    weights = _to_weights([s for _, s, _ in chosen])

    holdings: list[PortfolioHolding] = []
    asset_mix: dict[str, float] = {}
    for (sym, score, fund), w in zip(chosen, weights):
        r = wide.loc[sym]
        holdings.append(
            PortfolioHolding(
                symbol=sym,
                name=fund.name,
                name_zh=fund.name_zh or fund.name,
                category=fund.category,
                region=fund.region,
                theme=fund.theme,
                weight=float(w),
                score=score,
                return_30d=_safe(r.get("return_30d")),
                return_90d=_safe(r.get("return_90d")),
                sharpe_90d=_safe(r.get("sharpe_90d")),
                vol_30d=_safe(r.get("vol_30d_annualised")),
            )
        )
        asset_mix[fund.category] = asset_mix.get(fund.category, 0.0) + float(w)

    # 簡化估算：加權平均
    vols = [(h.vol_30d, h.weight) for h in holdings if h.vol_30d is not None]
    expected_vol = (
        sum(v * w for v, w in vols) if vols else None
    )
    rets = [(h.return_90d, h.weight) for h in holdings if h.return_90d is not None]
    if rets:
        weighted_90d = sum(r * w for r, w in rets)
        expected_return_annual = (1 + weighted_90d) ** (365 / 90) - 1 if weighted_90d > -0.99 else None
    else:
        expected_return_annual = None

    return Portfolio(
        horizon_key=horizon_key,
        label=horizon_cfg.get("label_zh", horizon_key),
        description=horizon_cfg.get("description_zh", ""),
        holdings=holdings,
        expected_vol=expected_vol,
        expected_return_annual=expected_return_annual,
        asset_mix=asset_mix,
        rationale=_build_rationale(
            horizon_key, holdings, horizon_cfg.get("description_zh", ""), asset_mix
        ),
    )


def build_all_portfolios(
    metrics_df: pd.DataFrame,
    funds: list[Fund],
    horizons: dict[str, dict],
) -> dict[str, Portfolio]:
    out: dict[str, Portfolio] = {}
    for key, cfg in horizons.items():
        p = build_portfolio(metrics_df, funds, key, cfg)
        if p:
            out[key] = p
    return out
