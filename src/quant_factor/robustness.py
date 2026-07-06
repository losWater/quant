"""Robustness checks for overfitting and strategy stability."""

from __future__ import annotations

import argparse
import copy
from pathlib import Path
from typing import Any

import pandas as pd

from quant_factor.backtest import run_long_only_backtest
from quant_factor.config import load_config
from quant_factor.factors import calculate_raw_factors, preprocess_factors
from quant_factor.metrics import summarize_performance


def _reset_period_nav(backtest: pd.DataFrame) -> pd.DataFrame:
    """Reset NAV to 1.0 for a period-specific performance calculation."""
    required = {"trade_date", "net_return", "turnover", "cost"}
    missing = required - set(backtest.columns)
    if missing:
        raise ValueError(f"Backtest data is missing required columns: {sorted(missing)}")

    result = backtest.loc[:, ["trade_date", "net_return", "turnover", "cost"]].copy()
    result["trade_date"] = pd.to_datetime(result["trade_date"], errors="coerce")
    result["net_return"] = pd.to_numeric(result["net_return"], errors="coerce").fillna(0)
    result["turnover"] = pd.to_numeric(result["turnover"], errors="coerce").fillna(0)
    result["cost"] = pd.to_numeric(result["cost"], errors="coerce").fillna(0)
    result = result.dropna(subset=["trade_date"]).sort_values("trade_date").reset_index(drop=True)
    result["nav"] = (1 + result["net_return"]).cumprod()
    return result


def _summarize_period(backtest: pd.DataFrame, label_column: str, label: str) -> pd.DataFrame:
    """Summarize one period and attach a label column."""
    summary = summarize_performance(_reset_period_nav(backtest))
    return summary.assign(**{label_column: label})


def build_yearly_performance(backtest: pd.DataFrame) -> pd.DataFrame:
    """Build year-by-year strategy performance."""
    data = backtest.copy()
    data["trade_date"] = pd.to_datetime(data["trade_date"], errors="coerce")
    grouped = data.dropna(subset=["trade_date"]).groupby(data["trade_date"].dt.year)
    rows = [_summarize_period(year_data, "year", str(year)) for year, year_data in grouped]
    if not rows:
        return pd.DataFrame()
    result = pd.concat(rows, ignore_index=True)
    return result.loc[:, ["year", *[column for column in result.columns if column != "year"]]]


def build_sample_split_performance(
    backtest: pd.DataFrame,
    *,
    train_end_date: str,
    test_start_date: str,
) -> pd.DataFrame:
    """Build in-sample and out-of-sample performance from fixed calendar dates."""
    data = backtest.copy()
    data["trade_date"] = pd.to_datetime(data["trade_date"], errors="coerce")
    train_end = pd.Timestamp(train_end_date)
    test_start = pd.Timestamp(test_start_date)
    splits = [
        ("in_sample", data[data["trade_date"] <= train_end]),
        ("out_of_sample", data[data["trade_date"] >= test_start]),
    ]
    rows = [
        _summarize_period(split_data, "sample", split_name)
        for split_name, split_data in splits
        if not split_data.empty
    ]
    if not rows:
        return pd.DataFrame()
    result = pd.concat(rows, ignore_index=True)
    return result.loc[:, ["sample", *[column for column in result.columns if column != "sample"]]]


def _run_configured_backtest(
    prices: pd.DataFrame,
    factors: pd.DataFrame,
    backtest_config: dict[str, Any],
) -> pd.DataFrame:
    """Run the standard long-only backtest with a supplied config."""
    backtest, _, _ = run_long_only_backtest(
        prices,
        factors,
        factor=backtest_config.get("factor", "momentum"),
        rebalance_frequency=backtest_config.get("rebalance_frequency", "monthly"),
        portfolio_quantile=backtest_config.get("portfolio_quantile", 0.2),
        buy_commission_rate=backtest_config.get("buy_commission_rate", 0.0),
        sell_commission_rate=backtest_config.get("sell_commission_rate", 0.0),
        stamp_tax_rate=backtest_config.get("stamp_tax_rate", 0.0),
        slippage_rate=backtest_config.get("slippage_rate", 0.0),
    )
    return backtest


def build_cost_sensitivity(
    prices: pd.DataFrame,
    factors: pd.DataFrame,
    config: dict[str, Any],
    *,
    cost_multipliers: list[float],
) -> pd.DataFrame:
    """Run the strategy under different transaction-cost assumptions."""
    rows = []
    base_backtest_config = config.get("backtest", {})
    for multiplier in cost_multipliers:
        backtest_config = copy.deepcopy(base_backtest_config)
        for key in [
            "buy_commission_rate",
            "sell_commission_rate",
            "stamp_tax_rate",
            "slippage_rate",
        ]:
            backtest_config[key] = float(backtest_config.get(key, 0.0)) * multiplier
        backtest = _run_configured_backtest(prices, factors, backtest_config)
        rows.append(_summarize_period(backtest, "cost_multiplier", f"{multiplier:g}"))
    result = pd.concat(rows, ignore_index=True)
    columns = [
        "cost_multiplier",
        *[column for column in result.columns if column != "cost_multiplier"],
    ]
    return result.loc[:, columns]


def build_momentum_window_sensitivity(
    prices: pd.DataFrame,
    config: dict[str, Any],
    *,
    momentum_windows: list[int],
) -> pd.DataFrame:
    """Recalculate factors with different momentum windows and rerun the strategy."""
    rows = []
    base_factor_config = config.get("factors", {})
    backtest_config = config.get("backtest", {})
    for window in momentum_windows:
        factor_config = copy.deepcopy(base_factor_config)
        factor_config["momentum_window"] = int(window)
        raw_factors = calculate_raw_factors(prices, factor_config)
        factors = preprocess_factors(
            raw_factors,
            winsorize_method=factor_config.get("winsorize_method", "mad"),
            winsorize_limit=factor_config.get("winsorize_limit", 3.0),
            standardize=factor_config.get("standardize", True),
        )
        backtest = _run_configured_backtest(prices, factors, backtest_config)
        rows.append(_summarize_period(backtest, "momentum_window", str(window)))
    result = pd.concat(rows, ignore_index=True)
    columns = [
        "momentum_window",
        *[column for column in result.columns if column != "momentum_window"],
    ]
    return result.loc[:, columns]


def build_robustness_report(config: dict[str, Any]) -> dict[str, pd.DataFrame]:
    """Build and persist robustness reports."""
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
    backtest = pd.read_csv(reports_dir / "backtest_nav.csv", parse_dates=["trade_date"])

    robustness_config = config.get("robustness", {})
    yearly = build_yearly_performance(backtest)
    sample_split = build_sample_split_performance(
        backtest,
        train_end_date=robustness_config.get("train_end_date", "2021-12-31"),
        test_start_date=robustness_config.get("test_start_date", "2022-01-01"),
    )
    cost_sensitivity = build_cost_sensitivity(
        prices,
        factors,
        config,
        cost_multipliers=robustness_config.get("cost_multipliers", [0.0, 0.5, 1.0, 2.0, 3.0]),
    )
    momentum_window_sensitivity = build_momentum_window_sensitivity(
        prices,
        config,
        momentum_windows=robustness_config.get("momentum_windows", [10, 20, 40, 60]),
    )

    yearly.to_csv(reports_dir / "yearly_performance.csv", index=False)
    sample_split.to_csv(reports_dir / "sample_split_performance.csv", index=False)
    cost_sensitivity.to_csv(reports_dir / "cost_sensitivity.csv", index=False)
    momentum_window_sensitivity.to_csv(
        reports_dir / "momentum_window_sensitivity.csv",
        index=False,
    )
    return {
        "yearly": yearly,
        "sample_split": sample_split,
        "cost_sensitivity": cost_sensitivity,
        "momentum_window_sensitivity": momentum_window_sensitivity,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run robustness checks for the strategy.")
    parser.add_argument("--config", default="config.yaml", help="Path to project config YAML.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    outputs = build_robustness_report(config)
    print("Saved robustness reports to results/reports")
    print(outputs["sample_split"].to_string(index=False))


if __name__ == "__main__":
    main()
