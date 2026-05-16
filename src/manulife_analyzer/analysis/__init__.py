"""Quantitative analysis: returns, risk, momentum, macro signals, screening."""

from .metrics import compute_fund_metrics, FundMetrics
from .momentum import rank_momentum
from .macro import summarize_macro, MacroSummary
from .screener import screen_funds, ScreenResult

__all__ = [
    "compute_fund_metrics",
    "FundMetrics",
    "rank_momentum",
    "summarize_macro",
    "MacroSummary",
    "screen_funds",
    "ScreenResult",
]
