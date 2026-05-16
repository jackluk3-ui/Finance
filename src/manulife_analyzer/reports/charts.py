"""Matplotlib chart helpers — render to base64 PNG for inline HTML embed."""

from __future__ import annotations

import base64
import io

import matplotlib

matplotlib.use("Agg")  # headless
import matplotlib.pyplot as plt
import pandas as pd


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
    ax.set_xlabel("Return (%)")
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
