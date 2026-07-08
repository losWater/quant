"""Stage 15 sector-neutral variant and side-by-side comparison.

阶段 14 证实了策略收益很大程度来自 IT/成长行业 beta。阶段 15 做一个控制变量实验：
把"行业押注"这个已知 beta 剥掉（每个行业强制等于等权基准权重，只在行业内部选股），
然后看策略相对等权股票池的超额收益是变干净了、还是直接消失了。

这个模块不改变主策略，而是并排跑"原策略 vs 行业中性策略 vs SPY vs 等权股票池"，
并用阶段 14 的 exposure 逻辑验证中性版的行业偏离确实被压到了 0。

判断标准不是"绝对收益谁高"，而是"相对等权股票池的超额收益是否更稳、更正"：
- 中性后还能跑赢等权池 -> 存在行业内选股 alpha，值钱。
- 中性后归零或转负 -> 诚实结论：收益基本就是行业 beta。这是很有价值的负面结果。
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import pandas as pd

from quant_factor.backtest import run_long_only_backtest
from quant_factor.config import load_config
from quant_factor.exposure import build_sector_exposure, load_sector_map, prepare_holdings
from quant_factor.metrics import summarize_performance
from quant_factor.robustness import build_rolling_validation, build_sample_split_performance

ORIGINAL_LABEL = "original_strategy"
NEUTRAL_LABEL = "sector_neutral_strategy"


def summarize_all_samples(
    source: pd.DataFrame,
    series_name: str,
    *,
    train_end_date: str,
    test_start_date: str,
) -> pd.DataFrame:
    """Summarize a return stream over full sample plus in/out-of-sample splits."""
    # 对照实验最怕"只看完整样本"。策略在完整样本靠某几年撑起来是常见陷阱，
    # 所以每条曲线都同时报告完整样本、样本内、样本外，重点看样本外是否更稳。
    columns = [c for c in ["trade_date", "net_return", "turnover", "cost"] if c in source.columns]
    data = source.loc[:, columns].copy()
    data["trade_date"] = pd.to_datetime(data["trade_date"], errors="coerce")
    for column in ["net_return", "turnover", "cost"]:
        if column not in data.columns:
            data[column] = 0.0
        data[column] = pd.to_numeric(data[column], errors="coerce").fillna(0.0)
    data = data.dropna(subset=["trade_date"]).sort_values("trade_date").reset_index(drop=True)
    # 重新累乘净值，保证和分年度/样本切片使用同一套 nav 口径。
    data["nav"] = (1 + data["net_return"]).cumprod()

    full = summarize_performance(data).assign(sample="full_sample")
    split = build_sample_split_performance(
        data,
        train_end_date=train_end_date,
        test_start_date=test_start_date,
    )
    combined = pd.concat([full, split], ignore_index=True).assign(series=series_name)
    ordered = ["series", "sample", *[c for c in combined.columns if c not in {"series", "sample"}]]
    return combined.loc[:, ordered]


def _benchmark_returns(benchmark_nav: pd.DataFrame, benchmark: str) -> pd.DataFrame:
    """Extract one benchmark's daily return stream for uniform summarization."""
    data = benchmark_nav[benchmark_nav["benchmark"] == benchmark]
    return pd.DataFrame(
        {
            "trade_date": pd.to_datetime(data["trade_date"], errors="coerce"),
            "net_return": pd.to_numeric(data["benchmark_return"], errors="coerce").fillna(0.0),
        }
    )


def build_comparison(
    original_backtest: pd.DataFrame,
    neutral_backtest: pd.DataFrame,
    benchmark_nav: pd.DataFrame,
    *,
    benchmark_symbol: str,
    train_end_date: str,
    test_start_date: str,
) -> pd.DataFrame:
    """Build the four-way performance comparison table across sample windows."""
    # 四方对照：原策略 / 行业中性策略 / SPY / 等权股票池。
    # 等权股票池是最关键的参照——中性化的意义就是看剥掉行业 beta 后能否还赢它。
    frames = [
        summarize_all_samples(
            original_backtest,
            ORIGINAL_LABEL,
            train_end_date=train_end_date,
            test_start_date=test_start_date,
        ),
        summarize_all_samples(
            neutral_backtest,
            NEUTRAL_LABEL,
            train_end_date=train_end_date,
            test_start_date=test_start_date,
        ),
    ]
    if not benchmark_nav.empty:
        for benchmark in [benchmark_symbol, "equal_weight_universe"]:
            benchmark_returns = _benchmark_returns(benchmark_nav, benchmark)
            if benchmark_returns.empty:
                continue
            frames.append(
                summarize_all_samples(
                    benchmark_returns,
                    benchmark,
                    train_end_date=train_end_date,
                    test_start_date=test_start_date,
                )
            )
    return pd.concat(frames, ignore_index=True)


def plot_nav_comparison(
    original_backtest: pd.DataFrame,
    neutral_backtest: pd.DataFrame,
    benchmark_nav: pd.DataFrame,
    figures_dir: Path,
) -> None:
    """Plot original vs sector-neutral strategy NAV against SPY and equal-weight."""
    figures_dir.mkdir(parents=True, exist_ok=True)
    fig, axis = plt.subplots(figsize=(11, 5))
    axis.plot(original_backtest["trade_date"], original_backtest["nav"], label=ORIGINAL_LABEL)
    axis.plot(neutral_backtest["trade_date"], neutral_backtest["nav"], label=NEUTRAL_LABEL)
    for benchmark, group in benchmark_nav.groupby("benchmark", sort=False):
        axis.plot(group["trade_date"], group["benchmark_nav"], label=str(benchmark), alpha=0.7)
    axis.set_title("Sector-Neutral vs Original Strategy NAV")
    axis.set_ylabel("NAV")
    axis.grid(alpha=0.3)
    axis.legend(loc="best", fontsize=8)
    fig.tight_layout()
    fig.savefig(figures_dir / "sector_neutral_comparison.png", dpi=150)
    plt.close(fig)


def build_neutralization_report(config: dict[str, Any]) -> dict[str, pd.DataFrame]:
    """Run the sector-neutral variant, compare to original and benchmarks, persist reports."""
    processed_dir = Path(config["data"]["processed_dir"])
    reports_dir = Path(config["output"]["reports_dir"])
    figures_dir = Path(config["output"]["figures_dir"])
    reports_dir.mkdir(parents=True, exist_ok=True)

    sector_map = load_sector_map(config)
    if sector_map.empty:
        raise ValueError(
            "Sector-neutral analysis needs a 'sector' column in the universe file. "
            "See data/universe/us_large_cap_100.csv."
        )

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
    common_kwargs = {
        "factor": backtest_config.get("factor", "momentum"),
        "rebalance_frequency": backtest_config.get("rebalance_frequency", "monthly"),
        "portfolio_quantile": backtest_config.get("portfolio_quantile", 0.2),
        "buy_commission_rate": backtest_config.get("buy_commission_rate", 0.0),
        "sell_commission_rate": backtest_config.get("sell_commission_rate", 0.0),
        "stamp_tax_rate": backtest_config.get("stamp_tax_rate", 0.0),
        "slippage_rate": backtest_config.get("slippage_rate", 0.0),
    }
    # 两次回测只差 sector_neutral 一个开关，其它假设完全相同，才是干净的对照实验。
    original_backtest, _, _ = run_long_only_backtest(prices, factors, **common_kwargs)
    neutral_backtest, _, neutral_active = run_long_only_backtest(
        prices,
        factors,
        sector_neutral=True,
        sector_map=sector_map,
        **common_kwargs,
    )

    benchmark_path = reports_dir / "benchmark_nav.csv"
    benchmark_nav = (
        pd.read_csv(benchmark_path, parse_dates=["trade_date"])
        if benchmark_path.exists()
        else pd.DataFrame()
    )

    robustness_config = config.get("robustness", {})
    train_end_date = robustness_config.get("train_end_date", "2021-12-31")
    test_start_date = robustness_config.get("test_start_date", "2022-01-01")

    comparison = build_comparison(
        original_backtest,
        neutral_backtest,
        benchmark_nav,
        benchmark_symbol=str(backtest_config.get("benchmark", "SPY")),
        train_end_date=train_end_date,
        test_start_date=test_start_date,
    )

    # 验证中性化确实生效：把中性版持仓喂回阶段 14 的 exposure，检查行业偏离是否归零。
    neutral_holdings = prepare_holdings(neutral_active, prices, sector_map)
    neutral_exposure = build_sector_exposure(neutral_holdings, sector_map)

    comparison.to_csv(reports_dir / "sector_neutral_comparison.csv", index=False)
    neutral_exposure.to_csv(reports_dir / "sector_neutral_exposure.csv", index=False)
    if not benchmark_nav.empty:
        plot_nav_comparison(original_backtest, neutral_backtest, benchmark_nav, figures_dir)

    return {
        "comparison": comparison,
        "neutral_exposure": neutral_exposure,
        "original_backtest": original_backtest,
        "neutral_backtest": neutral_backtest,
    }


_ROLLING_KEEP_COLUMNS = [
    "test_year",
    "selected_momentum_window",
    "test_total_return",
    "test_sharpe_ratio",
    "beat_spy",
    "beat_equal_weight",
]


def build_rolling_neutral_comparison(config: dict[str, Any]) -> dict[str, pd.DataFrame]:
    """Stage 16: run rolling out-of-sample validation for original vs sector-neutral.

    阶段 15 里中性版的样本外优势只来自 2022-2023 一个窗口。阶段 16 用滚动样本外框架
    在多个测试年重复检验：每个测试年都在训练期选动量窗口，再用选出的参数测下一整年，
    原策略和行业中性版各跑一遍逐年对比。只有多窗口都成立，才敢说中性化是可靠改进。
    """
    processed_dir = Path(config["data"]["processed_dir"])
    reports_dir = Path(config["output"]["reports_dir"])
    reports_dir.mkdir(parents=True, exist_ok=True)

    sector_map = load_sector_map(config)
    if sector_map.empty:
        raise ValueError(
            "Rolling sector-neutral validation needs a 'sector' column in the universe file."
        )

    # 滚动验证内部会按每个动量窗口重算因子，所以只需要价格，不需要预先算好的 factors.csv。
    prices = pd.read_csv(
        processed_dir / "daily_prices.csv",
        dtype={"symbol": "string"},
        parse_dates=["trade_date"],
    )
    benchmark_path = reports_dir / "benchmark_nav.csv"
    benchmark_nav = (
        pd.read_csv(benchmark_path, parse_dates=["trade_date"])
        if benchmark_path.exists()
        else pd.DataFrame()
    )

    rolling_config = config.get("rolling_validation", {})
    common_kwargs = {
        "train_years": int(rolling_config.get("train_years", 3)),
        "test_years": [int(year) for year in rolling_config.get("test_years", [2021, 2022, 2023])],
        "momentum_windows": rolling_config.get("momentum_windows", [10, 20, 40, 60]),
        "selection_metric": rolling_config.get("selection_metric", "sharpe_ratio"),
        "benchmark_nav": benchmark_nav,
    }
    # 原策略和中性版走同一套滚动逻辑、同样的训练期选参数规则，只差 sector_neutral 一个开关。
    original_summary, _ = build_rolling_validation(prices, config, **common_kwargs)
    neutral_summary, _ = build_rolling_validation(
        prices,
        config,
        sector_neutral=True,
        sector_map=sector_map,
        **common_kwargs,
    )

    frames = []
    for label, summary in [(ORIGINAL_LABEL, original_summary), (NEUTRAL_LABEL, neutral_summary)]:
        if summary.empty:
            continue
        columns = [c for c in _ROLLING_KEEP_COLUMNS if c in summary.columns]
        frames.append(summary.loc[:, columns].assign(strategy=label))
    comparison = (
        pd.concat(frames, ignore_index=True)
        if frames
        else pd.DataFrame(columns=["strategy", *_ROLLING_KEEP_COLUMNS])
    )
    if not comparison.empty:
        ordered = ["strategy", *[c for c in comparison.columns if c != "strategy"]]
        comparison = comparison.loc[:, ordered].sort_values(["test_year", "strategy"])
        comparison = comparison.reset_index(drop=True)

    comparison.to_csv(reports_dir / "rolling_neutral_comparison.csv", index=False)
    return {"rolling_comparison": comparison}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run stage-15 sector-neutral comparison.")
    parser.add_argument("--config", default="config.yaml", help="Path to project config YAML.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    outputs = build_neutralization_report(config)
    print("Saved sector-neutral reports to results/reports")
    comparison = outputs["comparison"]
    full_sample = comparison[comparison["sample"] == "full_sample"]
    print(
        full_sample.loc[
            :, ["series", "sample", "total_return", "sharpe_ratio", "max_drawdown"]
        ].to_string(index=False)
    )


if __name__ == "__main__":
    main()
