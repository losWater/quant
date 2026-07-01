"""Backtesting utilities."""

from __future__ import annotations

import argparse
from math import ceil
from pathlib import Path
from typing import Any

import pandas as pd

from quant_factor.config import load_config


# 交易成本按换手率扣除，包括买卖佣金、卖出印花税和滑点。
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


def calculate_daily_returns(prices: pd.DataFrame) -> pd.DataFrame:
    """Calculate close-to-close daily returns for each symbol."""
    # 当前版本用收盘到收盘收益近似持仓收益，后续可替换为开盘成交模型。
    required = {"trade_date", "symbol", "close"}
    missing = required - set(prices.columns)
    if missing:
        raise ValueError(f"Price data is missing required columns: {sorted(missing)}")

    data = prices.loc[:, ["trade_date", "symbol", "close"]].copy()
    data["trade_date"] = pd.to_datetime(data["trade_date"], errors="coerce")
    data["close"] = pd.to_numeric(data["close"], errors="coerce")
    data = data.dropna(subset=["trade_date", "symbol", "close"])
    data = data.sort_values(["symbol", "trade_date"])
    data["daily_return"] = data.groupby("symbol")["close"].pct_change()
    return data.loc[:, ["trade_date", "symbol", "daily_return"]]


def get_rebalance_dates(
    trading_dates: pd.Series,
    *,
    frequency: str = "monthly",
) -> pd.DatetimeIndex:
    """Select rebalance dates from available trading dates."""
    # 月度调仓使用每月最后一个可交易日，不假设自然月最后一天一定开市。
    dates = pd.Series(pd.to_datetime(trading_dates).dropna().sort_values().unique())
    if dates.empty:
        return pd.DatetimeIndex([])

    if frequency == "daily":
        return pd.DatetimeIndex(dates)
    if frequency == "monthly":
        grouped = dates.groupby(dates.dt.to_period("M"))
        return pd.DatetimeIndex(grouped.max().sort_values())
    raise ValueError(f"Unsupported rebalance frequency: {frequency}")


def select_top_quantile(
    factors: pd.DataFrame,
    *,
    factor: str,
    portfolio_quantile: float,
) -> pd.DataFrame:
    """Select top-ranked names and assign equal target weights per rebalance date."""
    # 这里只做最简单的多头等权选股：因子值越高，排名越靠前。
    if not 0 < portfolio_quantile <= 1:
        raise ValueError("portfolio_quantile must be in (0, 1].")

    required = {"trade_date", "symbol", factor}
    missing = required - set(factors.columns)
    if missing:
        raise ValueError(f"Factor data is missing required columns: {sorted(missing)}")

    rows = []
    data = factors.loc[:, ["trade_date", "symbol", factor]].copy()
    data["trade_date"] = pd.to_datetime(data["trade_date"], errors="coerce")
    data = data.dropna(subset=["trade_date", "symbol", factor])

    for trade_date, date_data in data.groupby("trade_date", sort=True):
        selected_count = max(1, ceil(len(date_data) * portfolio_quantile))
        selected = date_data.sort_values(factor, ascending=False).head(selected_count)
        weight = 1 / len(selected)
        rows.extend(
            {
                "trade_date": trade_date,
                "symbol": symbol,
                "target_weight": weight,
            }
            for symbol in selected["symbol"]
        )
    return pd.DataFrame(rows, columns=["trade_date", "symbol", "target_weight"])


def calculate_turnover(current_weights: pd.Series, target_weights: pd.Series) -> float:
    """Calculate one-way turnover between current and target portfolio weights."""
    # 单边换手取买入额和卖出额的较大值，适合有现金流约束的组合估算。
    aligned = pd.concat([current_weights, target_weights], axis=1).fillna(0)
    delta = aligned.iloc[:, 1] - aligned.iloc[:, 0]
    buys = delta.clip(lower=0).sum()
    sells = (-delta.clip(upper=0)).sum()
    return float(max(buys, sells))


def run_long_only_backtest(
    prices: pd.DataFrame,
    factors: pd.DataFrame,
    *,
    factor: str,
    rebalance_frequency: str,
    portfolio_quantile: float,
    buy_commission_rate: float,
    sell_commission_rate: float,
    stamp_tax_rate: float,
    slippage_rate: float,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Run an equal-weight long-only factor strategy with one-day signal delay."""
    # 主流程：调仓日选股 -> 生成目标权重 -> 延迟成交 -> 计算收益和成本。
    daily_returns = calculate_daily_returns(prices)
    trading_dates = pd.DatetimeIndex(sorted(daily_returns["trade_date"].dropna().unique()))
    symbols = sorted(daily_returns["symbol"].dropna().unique())
    rebalance_dates = get_rebalance_dates(trading_dates.to_series(), frequency=rebalance_frequency)

    factor_data = factors.copy()
    factor_data["trade_date"] = pd.to_datetime(factor_data["trade_date"], errors="coerce")
    factor_data = factor_data[factor_data["trade_date"].isin(rebalance_dates)]
    target_weights = select_top_quantile(
        factor_data,
        factor=factor,
        portfolio_quantile=portfolio_quantile,
    )

    target_matrix = (
        target_weights.pivot(index="trade_date", columns="symbol", values="target_weight")
        .reindex(trading_dates)
        .reindex(columns=symbols)
    )
    # T 日收盘后生成 signal_weights；shift(2) 让收益从 T+2 开始计入。
    signal_weights = target_matrix.ffill().fillna(0)
    active_weights = signal_weights.shift(2).fillna(0)

    return_matrix = (
        daily_returns.pivot(index="trade_date", columns="symbol", values="daily_return")
        .reindex(trading_dates)
        .reindex(columns=symbols)
        .fillna(0)
    )
    gross_return = (active_weights * return_matrix).sum(axis=1)

    # 成本记在 T+1，和 T 日信号错开，避免把交易发生在信号生成之前。
    previous_signal_weights = signal_weights.shift(1).fillna(0)
    changed = (signal_weights != previous_signal_weights).any(axis=1)
    signal_turnover = pd.Series(0.0, index=trading_dates)
    for trade_date in trading_dates[changed]:
        signal_turnover.loc[trade_date] = calculate_turnover(
            previous_signal_weights.loc[trade_date],
            signal_weights.loc[trade_date],
        )
    turnover = signal_turnover.shift(1).fillna(0)

    cost = turnover.map(
        lambda value: transaction_cost(
            value,
            buy_commission_rate,
            sell_commission_rate,
            stamp_tax_rate,
            slippage_rate,
        )
    )
    net_return = gross_return - cost
    nav = (1 + net_return).cumprod()

    backtest = pd.DataFrame(
        {
            "trade_date": trading_dates,
            "gross_return": gross_return.to_numpy(),
            "turnover": turnover.to_numpy(),
            "cost": cost.to_numpy(),
            "net_return": net_return.to_numpy(),
            "nav": nav.to_numpy(),
        }
    )

    active_weight_table = (
        active_weights.stack()
        .rename("weight")
        .reset_index()
        .rename(columns={"level_0": "trade_date", "level_1": "symbol"})
    )
    active_weight_table = active_weight_table[active_weight_table["weight"] > 0].reset_index(
        drop=True
    )
    return backtest, target_weights, active_weight_table


def run_backtest(config: dict[str, Any]) -> dict[str, pd.DataFrame]:
    """Load processed data, run backtest, and persist reports."""
    # 主入口：读取已处理价格和因子，按 config.yaml 参数运行并保存报告。
    processed_dir = Path(config["data"]["processed_dir"])
    reports_dir = Path(config["output"]["reports_dir"])
    reports_dir.mkdir(parents=True, exist_ok=True)

    prices = pd.read_csv(
        processed_dir / "daily_prices.csv",
        dtype={"symbol": "string"},
        parse_dates=["trade_date"],
    )
    factors = pd.read_csv(
        processed_dir / "factors.csv",
        dtype={"symbol": "string"},
        parse_dates=["trade_date"],
    )

    backtest_config = config.get("backtest", {})
    factor = backtest_config.get("factor", "momentum")
    backtest, target_weights, active_weights = run_long_only_backtest(
        prices,
        factors,
        factor=factor,
        rebalance_frequency=backtest_config.get("rebalance_frequency", "monthly"),
        portfolio_quantile=backtest_config.get("portfolio_quantile", 0.2),
        buy_commission_rate=backtest_config.get("buy_commission_rate", 0.0),
        sell_commission_rate=backtest_config.get("sell_commission_rate", 0.0),
        stamp_tax_rate=backtest_config.get("stamp_tax_rate", 0.0),
        slippage_rate=backtest_config.get("slippage_rate", 0.0),
    )

    backtest.to_csv(reports_dir / "backtest_nav.csv", index=False)
    target_weights.to_csv(reports_dir / "backtest_target_weights.csv", index=False)
    active_weights.to_csv(reports_dir / "backtest_active_weights.csv", index=False)
    return {
        "backtest": backtest,
        "target_weights": target_weights,
        "active_weights": active_weights,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a long-only factor backtest.")
    parser.add_argument("--config", default="config.yaml", help="Path to project config YAML.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    outputs = run_backtest(config)
    backtest = outputs["backtest"]
    final_nav = backtest["nav"].iloc[-1] if not backtest.empty else float("nan")
    print(f"Saved backtest reports to {config['output']['reports_dir']}")
    print(f"Final NAV: {final_nav:.4f}")


if __name__ == "__main__":
    main()
