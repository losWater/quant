"""Stage 20 out-of-time test on genuinely new data (2024-2025).

前面所有"样本外"都多少沾一点泄漏：符号、因子选择或研究路径，都用到了 2018-2023 的信息。
这一步是唯一 100% 干净的考场——把策略完全锁死（行业中性 + 阶段 17-19 定下的因子和符号），
然后拉取 2024-2025 的真实行情：这段数据在我们做研究时根本还不存在，连"出题老师"都没见过。

策略的每一个决定都来自 2018-2023，2024-2025 只提供"未来的收益"来打分。所以：
- 2023 下半年的价格只用于计算因子的回看值（因子本就只用过去价格，不算偷看）。
- 真正评估的收益区间是 2024-01-01 起，全部是研究期之外的新数据。

唯一残留的不干净：股票池仍是"今天的幸存者"（幸存者偏差还在）。但收益数据是全新的。
"""

from __future__ import annotations

import argparse
import copy
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import pandas as pd

from quant_factor.backtest import run_long_only_backtest
from quant_factor.config import load_config
from quant_factor.data_loader import build_price_dataset, load_or_fetch_price_history
from quant_factor.exposure import load_sector_map
from quant_factor.factors import calculate_raw_factors, preprocess_factors
from quant_factor.metrics import (
    build_benchmark_nav,
    build_equal_weight_universe_nav,
    build_performance_comparison,
)
from quant_factor.multi_factor import DEFAULT_FACTOR_SIGNS, build_composite_score
from quant_factor.robustness import build_yearly_performance

# 因子回看缓冲：从 2023-10 开始拉数据，只为让 2024-01 起的因子有合法回看值；
# 真正评估的收益区间从 TEST_START 起。
WARMUP_START = "2023-10-01"
TEST_START = "2024-01-01"
TEST_END = "2025-12-31"


def build_out_of_time_config(config: dict[str, Any]) -> dict[str, Any]:
    """Copy config with an out-of-time date range and separate data dirs."""
    # 用独立的 raw/processed 目录，避免覆盖 2018-2023 的研究数据；深拷贝保证原 config 不被改。
    oot = copy.deepcopy(config)
    data = oot["data"]
    data["start_date"] = WARMUP_START
    data["end_date"] = TEST_END
    data["raw_dir"] = "data/raw_oot"
    data["processed_dir"] = "data/processed_oot"
    return oot


def plot_out_of_time_nav(
    backtest: pd.DataFrame,
    benchmark_nav: pd.DataFrame,
    figures_dir: Path,
) -> None:
    """Plot locked-strategy NAV vs benchmarks over the out-of-time period."""
    figures_dir.mkdir(parents=True, exist_ok=True)
    fig, axis = plt.subplots(figsize=(11, 5))
    axis.plot(backtest["trade_date"], backtest["nav"], label="locked_strategy", linewidth=2)
    for benchmark, group in benchmark_nav.groupby("benchmark", sort=False):
        axis.plot(group["trade_date"], group["benchmark_nav"], label=str(benchmark), alpha=0.75)
    axis.set_title("Out-of-Time Test 2024-2025 (locked strategy vs benchmarks)")
    axis.set_ylabel("NAV")
    axis.grid(alpha=0.3)
    axis.legend(loc="best")
    fig.tight_layout()
    fig.savefig(figures_dir / "out_of_time_comparison.png", dpi=150)
    plt.close(fig)


def build_out_of_time_test(
    config: dict[str, Any],
    *,
    refresh: bool = False,
) -> dict[str, pd.DataFrame]:
    """Run the locked strategy on freshly downloaded 2024-2025 data and compare to benchmarks."""
    reports_dir = Path(config["output"]["reports_dir"])
    figures_dir = Path(config["output"]["figures_dir"])
    reports_dir.mkdir(parents=True, exist_ok=True)

    sector_map = load_sector_map(config)
    if sector_map.empty:
        raise ValueError("Out-of-time test needs a 'sector' column in the universe file.")

    oot_config = build_out_of_time_config(config)
    # 拉取研究期之外的真实行情（2023H2 仅作因子回看，评估从 2024 起）。
    prices = build_price_dataset(oot_config, refresh=refresh)

    factor_config = config.get("factors", {})
    raw_factors = calculate_raw_factors(prices, factor_config)
    factors = preprocess_factors(
        raw_factors,
        winsorize_method=factor_config.get("winsorize_method", "mad"),
        winsorize_limit=factor_config.get("winsorize_limit", 3.0),
        standardize=factor_config.get("standardize", True),
    )

    # 锁死的策略：因子符号全部来自 2018-2023 的研究结论，2024-2025 不参与任何决定。
    factor_signs = {
        str(k): int(v)
        for k, v in config.get("multi_factor", {}).get("factors", DEFAULT_FACTOR_SIGNS).items()
    }
    scored = build_composite_score(factors, factor_signs)

    backtest_config = config.get("backtest", {})
    backtest, _, _ = run_long_only_backtest(
        prices,
        scored,
        factor="composite_score",
        rebalance_frequency=backtest_config.get("rebalance_frequency", "monthly"),
        portfolio_quantile=backtest_config.get("portfolio_quantile", 0.2),
        buy_commission_rate=backtest_config.get("buy_commission_rate", 0.0),
        sell_commission_rate=backtest_config.get("sell_commission_rate", 0.0),
        stamp_tax_rate=backtest_config.get("stamp_tax_rate", 0.0),
        slippage_rate=backtest_config.get("slippage_rate", 0.0),
        sector_neutral=True,
        sector_map=sector_map,
    )

    # 只保留 2024 起的评估区间，并把净值重置到该区间起点。
    backtest["trade_date"] = pd.to_datetime(backtest["trade_date"], errors="coerce")
    test = backtest[
        (backtest["trade_date"] >= pd.Timestamp(TEST_START))
        & (backtest["trade_date"] <= pd.Timestamp(TEST_END))
    ].sort_values("trade_date").copy()
    test["nav"] = (1 + test["net_return"]).cumprod()

    oot_dates = test["trade_date"]
    benchmark_symbol = str(backtest_config.get("benchmark", "SPY"))
    spy_prices = load_or_fetch_price_history(benchmark_symbol, oot_config, refresh=refresh)
    benchmark_nav = pd.concat(
        [
            build_benchmark_nav(spy_prices, oot_dates, benchmark_symbol=benchmark_symbol),
            build_equal_weight_universe_nav(prices, oot_dates),
        ],
        ignore_index=True,
    )

    comparison = build_performance_comparison(
        test, benchmark_nav, benchmark_symbol=benchmark_symbol
    )
    yearly = build_yearly_performance(test)

    comparison.to_csv(reports_dir / "out_of_time_comparison.csv", index=False)
    yearly.to_csv(reports_dir / "out_of_time_yearly.csv", index=False)
    plot_out_of_time_nav(test, benchmark_nav, figures_dir)
    return {"comparison": comparison, "yearly": yearly}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run stage-20 out-of-time test on 2024-2025 data.")
    parser.add_argument("--config", default="config.yaml", help="Path to project config YAML.")
    parser.add_argument("--refresh", action="store_true", help="Ignore cached out-of-time data.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    outputs = build_out_of_time_test(config, refresh=args.refresh)
    print("Saved out-of-time reports to results/reports")
    print("--- 2024-2025 comparison ---")
    print(
        outputs["comparison"]
        .loc[:, ["series", "total_return", "sharpe_ratio", "max_drawdown"]]
        .round(4)
        .to_string(index=False)
    )


if __name__ == "__main__":
    main()
