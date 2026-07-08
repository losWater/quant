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
    # 分年度/样本内外统计时，不能直接拿整条 nav 的中间值相减。
    # 每个子区间都应该从 1.0 重新开始，才能得到这个阶段自己的收益和回撤。
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


def _filter_period(data: pd.DataFrame, *, start_date: str, end_date: str) -> pd.DataFrame:
    """Slice a date-indexed report table with inclusive calendar boundaries."""
    # 滚动验证会反复切训练期和测试期。统一在这里切片，
    # 可以避免某些地方用 <、某些地方用 <= 导致边界口径不一致。
    result = data.copy()
    result["trade_date"] = pd.to_datetime(result["trade_date"], errors="coerce")
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    return result[(result["trade_date"] >= start) & (result["trade_date"] <= end)].copy()


def build_yearly_performance(backtest: pd.DataFrame) -> pd.DataFrame:
    """Build year-by-year strategy performance."""
    # 分年度表现用于识别“是不是只靠某一年赚钱”。
    # 如果只有 2020 一年特别好，其他年份都不行，就要警惕样本期偶然性。
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
    # 样本内/样本外是过拟合检查的核心。
    # 真实研究里应该先在样本内探索，再在样本外只验证，不继续调参数。
    # 当前项目还没做自动调参，但先建立这个报告框架，方便后续诚实讨论。
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
    *,
    sector_neutral: bool = False,
    sector_map: pd.Series | None = None,
) -> pd.DataFrame:
    """Run the standard long-only backtest with a supplied config."""
    # 稳健性测试会反复跑同一套策略，只改一个假设：
    # 成本倍数、动量窗口等。抽成函数可以减少重复，也避免不同测试口径不一致。
    # sector_neutral 让同一套滚动/敏感性逻辑也能跑行业中性版，无需复制整段流程。
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
        sector_neutral=sector_neutral,
        sector_map=sector_map,
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
    # 成本敏感性回答：“这个策略是不是只在低成本假设下才好看？”
    # 如果成本稍微翻倍就失效，真实可交易性就很弱。
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
            # 只放大交易成本，不改选股逻辑。这样能单独观察成本假设对结果的影响。
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
    # 参数敏感性回答：“20 日动量是不是刚好撞上历史最优？”
    # 如果 10/20/40/60 都差不多，说明策略对窗口不太脆弱；
    # 如果只有 20 好，其他都崩，就很可能是过拟合。
    rows = []
    base_factor_config = config.get("factors", {})
    backtest_config = config.get("backtest", {})
    for window in momentum_windows:
        factor_config = copy.deepcopy(base_factor_config)
        factor_config["momentum_window"] = int(window)
        # 这里必须重新计算因子，而不是简单改 config 后复用旧 factors.csv。
        # 因为 momentum_window 直接决定每一天的 momentum 数值。
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


def _build_factors_for_momentum_window(
    prices: pd.DataFrame,
    factor_config: dict[str, Any],
    *,
    momentum_window: int,
) -> pd.DataFrame:
    """Recalculate factor data for one momentum-window assumption."""
    # 滚动验证和参数敏感性都需要“真正重算因子”。
    # 不能只改 config 里的数字，因为 factors.csv 已经是旧窗口算出来的结果。
    config = copy.deepcopy(factor_config)
    config["momentum_window"] = int(momentum_window)
    raw_factors = calculate_raw_factors(prices, config)
    return preprocess_factors(
        raw_factors,
        winsorize_method=config.get("winsorize_method", "mad"),
        winsorize_limit=config.get("winsorize_limit", 3.0),
        standardize=config.get("standardize", True),
    )


def _summarize_backtest_period(
    backtest: pd.DataFrame,
    *,
    start_date: str,
    end_date: str,
) -> pd.Series:
    """Summarize one calendar period and return the first row as a Series."""
    period = _filter_period(backtest, start_date=start_date, end_date=end_date)
    if period.empty:
        return pd.Series(dtype="float64")
    return summarize_performance(_reset_period_nav(period)).iloc[0]


def _summarize_benchmark_period(
    benchmark_nav: pd.DataFrame,
    *,
    benchmark: str,
    start_date: str,
    end_date: str,
) -> pd.Series:
    """Summarize one benchmark period using benchmark returns reset to 1.0."""
    if benchmark_nav.empty:
        return pd.Series(dtype="float64")
    data = benchmark_nav.copy()
    data["trade_date"] = pd.to_datetime(data["trade_date"], errors="coerce")
    data = data[data["benchmark"] == benchmark]
    data = _filter_period(data, start_date=start_date, end_date=end_date)
    if data.empty:
        return pd.Series(dtype="float64")
    benchmark_backtest = pd.DataFrame(
        {
            "trade_date": data["trade_date"],
            "net_return": pd.to_numeric(data["benchmark_return"], errors="coerce").fillna(0),
            "turnover": 0.0,
            "cost": 0.0,
        }
    )
    benchmark_backtest["nav"] = (1 + benchmark_backtest["net_return"]).cumprod()
    return summarize_performance(benchmark_backtest).iloc[0]


def _selection_value(row: dict[str, Any], column: str) -> float:
    """Read a selection metric and treat missing values as unusable."""
    value = row.get(column, pd.NA)
    return float(value) if pd.notna(value) else float("-inf")


def build_rolling_validation(
    prices: pd.DataFrame,
    config: dict[str, Any],
    *,
    train_years: int,
    test_years: list[int],
    momentum_windows: list[int],
    selection_metric: str = "sharpe_ratio",
    benchmark_nav: pd.DataFrame | None = None,
    sector_neutral: bool = False,
    sector_map: pd.Series | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run rolling out-of-sample validation with train-period parameter selection."""
    # 这是第二阶段最重要的检查：参数只能在训练期选择，不能看完测试期再倒推。
    # 每个 test_year 都模拟一次“站在上一年年底做决定，然后检验下一年”的过程。
    candidate_rows = []
    summary_rows = []
    factor_config = config.get("factors", {})
    backtest_config = config.get("backtest", {})
    benchmark_data = benchmark_nav if benchmark_nav is not None else pd.DataFrame()
    backtest_cache: dict[int, pd.DataFrame] = {}

    for test_year in test_years:
        train_start = f"{test_year - train_years}-01-01"
        train_end = f"{test_year - 1}-12-31"
        test_start = f"{test_year}-01-01"
        test_end = f"{test_year}-12-31"
        window_results = []

        for window in momentum_windows:
            if int(window) not in backtest_cache:
                factors = _build_factors_for_momentum_window(
                    prices,
                    factor_config,
                    momentum_window=window,
                )
                backtest_cache[int(window)] = _run_configured_backtest(
                    prices,
                    factors,
                    {**backtest_config, "factor": "momentum"},
                    sector_neutral=sector_neutral,
                    sector_map=sector_map,
                )
            backtest = backtest_cache[int(window)]
            train_summary = _summarize_backtest_period(
                backtest,
                start_date=train_start,
                end_date=train_end,
            )
            if train_summary.empty:
                continue
            test_summary = _summarize_backtest_period(
                backtest,
                start_date=test_start,
                end_date=test_end,
            )
            row = {
                "test_year": test_year,
                "train_start": train_start,
                "train_end": train_end,
                "test_start": test_start,
                "test_end": test_end,
                "momentum_window": int(window),
                "train_total_return": train_summary.get("total_return", pd.NA),
                "train_sharpe_ratio": train_summary.get("sharpe_ratio", pd.NA),
                "train_max_drawdown": train_summary.get("max_drawdown", pd.NA),
                "test_total_return": test_summary.get("total_return", pd.NA),
                "test_sharpe_ratio": test_summary.get("sharpe_ratio", pd.NA),
                "test_max_drawdown": test_summary.get("max_drawdown", pd.NA),
            }
            candidate_rows.append(row)
            window_results.append((row, backtest))

        if not window_results:
            continue

        selected_row, selected_backtest = max(
            window_results,
            key=lambda item: _selection_value(item[0], f"train_{selection_metric}"),
        )
        test_summary = _summarize_backtest_period(
            selected_backtest,
            start_date=test_start,
            end_date=test_end,
        )
        spy_summary = _summarize_benchmark_period(
            benchmark_data,
            benchmark=str(backtest_config.get("benchmark", "SPY")),
            start_date=test_start,
            end_date=test_end,
        )
        equal_weight_summary = _summarize_benchmark_period(
            benchmark_data,
            benchmark="equal_weight_universe",
            start_date=test_start,
            end_date=test_end,
        )
        strategy_return = test_summary.get("total_return", pd.NA)
        spy_return = spy_summary.get("total_return", pd.NA)
        equal_weight_return = equal_weight_summary.get("total_return", pd.NA)

        summary_rows.append(
            {
                "test_year": test_year,
                "train_start": train_start,
                "train_end": train_end,
                "test_start": test_start,
                "test_end": test_end,
                "selected_momentum_window": selected_row["momentum_window"],
                "selection_metric": selection_metric,
                "selected_train_metric": selected_row[f"train_{selection_metric}"],
                "test_total_return": strategy_return,
                "test_sharpe_ratio": test_summary.get("sharpe_ratio", pd.NA),
                "test_max_drawdown": test_summary.get("max_drawdown", pd.NA),
                "spy_total_return": spy_return,
                "equal_weight_total_return": equal_weight_return,
                "beat_spy": (
                    bool(strategy_return > spy_return)
                    if pd.notna(strategy_return) and pd.notna(spy_return)
                    else pd.NA
                ),
                "beat_equal_weight": (
                    bool(strategy_return > equal_weight_return)
                    if pd.notna(strategy_return) and pd.notna(equal_weight_return)
                    else pd.NA
                ),
            }
        )

    return pd.DataFrame(summary_rows), pd.DataFrame(candidate_rows)


def build_robustness_report(config: dict[str, Any]) -> dict[str, pd.DataFrame]:
    """Build and persist robustness reports."""
    # 稳健性模块不改变主回测结论，而是专门“挑刺”：
    # 1. 换年份还行不行
    # 2. 样本外还行不行
    # 3. 成本高一点还行不行
    # 4. 参数换一下还行不行
    # 这些问题比单次收益更能说明策略是否可信。
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
    benchmark_path = reports_dir / "benchmark_nav.csv"
    benchmark_nav = (
        pd.read_csv(benchmark_path, parse_dates=["trade_date"])
        if benchmark_path.exists()
        else pd.DataFrame()
    )
    rolling_config = config.get("rolling_validation", {})
    rolling_validation, rolling_candidates = build_rolling_validation(
        prices,
        config,
        train_years=int(rolling_config.get("train_years", 3)),
        test_years=[int(year) for year in rolling_config.get("test_years", [2021, 2022, 2023])],
        momentum_windows=rolling_config.get("momentum_windows", [10, 20, 40, 60]),
        selection_metric=rolling_config.get("selection_metric", "sharpe_ratio"),
        benchmark_nav=benchmark_nav,
    )

    yearly.to_csv(reports_dir / "yearly_performance.csv", index=False)
    sample_split.to_csv(reports_dir / "sample_split_performance.csv", index=False)
    cost_sensitivity.to_csv(reports_dir / "cost_sensitivity.csv", index=False)
    momentum_window_sensitivity.to_csv(
        reports_dir / "momentum_window_sensitivity.csv",
        index=False,
    )
    rolling_validation.to_csv(reports_dir / "rolling_validation.csv", index=False)
    rolling_candidates.to_csv(reports_dir / "rolling_validation_candidates.csv", index=False)
    return {
        "yearly": yearly,
        "sample_split": sample_split,
        "cost_sensitivity": cost_sensitivity,
        "momentum_window_sensitivity": momentum_window_sensitivity,
        "rolling_validation": rolling_validation,
        "rolling_validation_candidates": rolling_candidates,
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
