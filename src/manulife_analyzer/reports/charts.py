"""Matplotlib chart helpers — render to base64 PNG for inline HTML embed.

Configures a CJK-capable font so Chinese titles/labels render correctly.
"""

from __future__ import annotations

import base64
import io

import matplotlib

matplotlib.use("Agg")  # headless
import matplotlib.pyplot as plt
from matplotlib import font_manager
import pandas as pd


# 嘗試用 CJK 字體（系統一般裝咗 WenQuanYi / Noto CJK 其中一個）
_CJK_FONT_CANDIDATES = [
    "WenQuanYi Zen Hei",
    "Noto Sans CJK TC",
    "Noto Sans CJK SC",
    "Noto Sans CJK HK",
    "PingFang HK",
    "Microsoft JhengHei",
    "Heiti TC",
]


def _configure_font() -> None:
    available = {f.name for f in font_manager.fontManager.ttflist}
    for name in _CJK_FONT_CANDIDATES:
        if name in available:
            plt.rcParams["font.sans-serif"] = [name, "DejaVu Sans"]
            plt.rcParams["axes.unicode_minus"] = False
            return
    # fall back silently if no CJK font available
    plt.rcParams["axes.unicode_minus"] = False


_configure_font()


def _to_data_uri(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=110)
    plt.close(fig)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def price_chart(series: pd.Series, title: str) -> str:
    fig, ax = plt.subplots(figsize=(7, 3))
    series.plot(ax=ax, color="#1f4e79", linewidth=1.4)
    ax.set_title(title, fontsize=11)
    ax.set_xlabel("")
    ax.grid(True, linestyle="--", alpha=0.4)
    return _to_data_uri(fig)


def return_bar_chart(df: pd.DataFrame, value_col: str, label_col: str, title: str) -> str:
    fig, ax = plt.subplots(figsize=(7, max(3, 0.35 * len(df))))
    colors = ["#2e7d32" if v >= 0 else "#c62828" for v in df[value_col]]
    ax.barh(df[label_col], df[value_col] * 100, color=colors)
    ax.set_title(title, fontsize=11)
    ax.axvline(0, color="#333", linewidth=0.8)
    ax.set_xlabel("回報率 (%)")
    ax.grid(True, axis="x", linestyle="--", alpha=0.4)
    ax.invert_yaxis()
    return _to_data_uri(fig)


def macro_chart(series: pd.Series, title: str, ylabel: str = "") -> str:
    fig, ax = plt.subplots(figsize=(7, 3))
    series.plot(ax=ax, color="#b35900", linewidth=1.4)
    ax.set_title(title, fontsize=11)
    ax.set_ylabel(ylabel)
    ax.set_xlabel("")
    ax.grid(True, linestyle="--", alpha=0.4)
    return _to_data_uri(fig)
