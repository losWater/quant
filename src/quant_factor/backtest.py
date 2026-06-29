"""Backtesting utilities."""

from __future__ import annotations


def transaction_cost(
    turnover: float,
    buy_commission_rate: float,
    sell_commission_rate: float,
    stamp_tax_rate: float,
    slippage_rate: float,
) -> float:
    """Estimate cost from one-way turnover using conservative round-trip rates."""
    return turnover * (
        buy_commission_rate + sell_commission_rate + stamp_tax_rate + slippage_rate
    )
