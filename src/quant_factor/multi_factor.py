"""Stage 18 multi-factor composite in the sector-neutral framework.

阶段 17 诊断给出了明确处方，这一阶段就是把它落成一个"方向摆正的弱多因子"：

- 剔除 ma_deviation：和 momentum 相关 0.83，冗余。
- 方向对齐：momentum 21 天 IC 为负（短期反转区间），翻转符号（-1）；reversal、volatility 取 +1。
- 把方向对齐后的标准化因子等权相加，得到一个综合分 composite_score。

综合分只是换了个"排序依据"，所以直接塞进已有的行业中性回测机器（factor="composite_score"），
和"单因子 momentum 中性版"并排对比。核心问题：方向摆正的多因子，能不能比单因子更稳、
尤其改善 2022 这样的坏年份。

诚实预期：阶段 17 显示所有因子 IR ≤ 0.20，弱信号，组合改善大概率有限——这本身也是可接受的结论。
因子符号是研究判断（写在 config 里、可审阅），不是在同一份数据上拟合出来的，避免偷看未来。
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import pandas as pd

from quant_factor.backtest import run_long_only_backtest
from quant_factor.config import load_config
from quant_factor.exposure import load_sector_map
from quant_factor.factors import zscore
from quant_factor.neutralization import summarize_all_samples
from quant_factor.robustness import build_yearly_performance

# 默认综合分配方：依据阶段 17 诊断。sign = +1 保持方向、-1 翻转。
# 不含 ma_deviation（与 momentum 冗余）。
DEFAULT_FACTOR_SIGNS: dict[str, int] = {"momentum": -1, "reversal": 1, "volatility": 1}

SINGLE_LABEL = "single_factor_neutral"
MULTI_LABEL = "multi_factor_neutral"


def build_composite_score(
    factors: pd.DataFrame,
    factor_signs: dict[str, int],
) -> pd.DataFrame:
    """Add a sign-aligned, equal-weight composite score column to the factor table."""
    # 每个因子先在当天截面上重新 z-score，再乘方向符号、等权相加。
    # 重新 z-score 是为了让每个因子对综合分贡献相同的方差（等权才名副其实），
    # 不会因为某个因子残留的尺度更大而悄悄占主导。
    columns = [factor for factor in factor_signs if factor in factors.columns]
    if not columns:
        raise ValueError(
            f"None of the composite factors {sorted(factor_signs)} are present in the data."
        )

    data = factors.copy()
    data["trade_date"] = pd.to_datetime(data["trade_date"], errors="coerce")
    parts = []
    for factor in columns:
        standardized = data.groupby("trade_date")[factor].transform(zscore)
        parts.append(int(factor_signs[factor]) * standardized)
    data["composite_score"] = sum(parts)
    return data


def _benchmark_returns(benchmark_nav: pd.DataFrame, benchmark: str) -> pd.DataFrame:
    """Extract one benchmark's daily return stream for uniform summarization."""
    data = benchmark_nav[benchmark_nav["benchmark"] == benchmark]
    return pd.DataFrame(
        {
            "trade_date": pd.to_datetime(data["trade_date"], errors="coerce"),
            "net_return": pd.to_numeric(data["benchmark_return"], errors="coerce").fillna(0.0),
        }
    )


def plot_multi_factor_nav(
    single_backtest: pd.DataFrame,
    multi_backtest: pd.DataFrame,
    benchmark_nav: pd.DataFrame,
    figures_dir: Path,
) -> None:
    """Plot single-factor vs multi-factor neutral NAV against SPY and equal-weight."""
    figures_dir.mkdir(parents=True, exist_ok=True)
    fig, axis = plt.subplots(figsize=(11, 5))
    axis.plot(single_backtest["trade_date"], single_backtest["nav"], label=SINGLE_LABEL)
    axis.plot(multi_backtest["trade_date"], multi_backtest["nav"], label=MULTI_LABEL)
    for benchmark, group in benchmark_nav.groupby("benchmark", sort=False):
        axis.plot(group["trade_date"], group["benchmark_nav"], label=str(benchmark), alpha=0.7)
    axis.set_title("Multi-Factor vs Single-Factor (sector-neutral) NAV")
    axis.set_ylabel("NAV")
    axis.grid(alpha=0.3)
    axis.legend(loc="best", fontsize=8)
    fig.tight_layout()
    fig.savefig(figures_dir / "multi_factor_comparison.png", dpi=150)
    plt.close(fig)


def build_multi_factor_report(config: dict[str, Any]) -> dict[str, pd.DataFrame]:
    """Build the sign-aligned composite, backtest it sector-neutral, compare to single factor."""
    processed_dir = Path(config["data"]["processed_dir"])
    reports_dir = Path(config["output"]["reports_dir"])
    figures_dir = Path(config["output"]["figures_dir"])
    reports_dir.mkdir(parents=True, exist_ok=True)

    sector_map = load_sector_map(config)
    if sector_map.empty:
        raise ValueError("Multi-factor stage needs a 'sector' column in the universe file.")

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

    multi_factor_config = config.get("multi_factor", {})
    factor_signs = {
        str(k): int(v) for k, v in multi_factor_config.get("factors", DEFAULT_FACTOR_SIGNS).items()
    }
    scored = build_composite_score(factors, factor_signs)

    backtest_config = config.get("backtest", {})
    common_kwargs = {
        "rebalance_frequency": backtest_config.get("rebalance_frequency", "monthly"),
        "portfolio_quantile": backtest_config.get("portfolio_quantile", 0.2),
        "buy_commission_rate": backtest_config.get("buy_commission_rate", 0.0),
        "sell_commission_rate": backtest_config.get("sell_commission_rate", 0.0),
        "stamp_tax_rate": backtest_config.get("stamp_tax_rate", 0.0),
        "slippage_rate": backtest_config.get("slippage_rate", 0.0),
        "sector_neutral": True,
        "sector_map": sector_map,
    }
    # 两条线都做行业中性，唯一区别是排序依据：单因子 momentum vs 多因子综合分。
    # 这样对比只隔离"多因子 vs 单因子"这一个变量，行业 beta 已经被中性化掉。
    single_backtest, _, _ = run_long_only_backtest(
        prices, factors, factor=backtest_config.get("factor", "momentum"), **common_kwargs
    )
    multi_backtest, _, _ = run_long_only_backtest(
        prices, scored, factor="composite_score", **common_kwargs
    )

    robustness_config = config.get("robustness", {})
    train_end_date = robustness_config.get("train_end_date", "2021-12-31")
    test_start_date = robustness_config.get("test_start_date", "2022-01-01")

    benchmark_path = reports_dir / "benchmark_nav.csv"
    benchmark_nav = (
        pd.read_csv(benchmark_path, parse_dates=["trade_date"])
        if benchmark_path.exists()
        else pd.DataFrame()
    )

    frames = [
        summarize_all_samples(
            single_backtest,
            SINGLE_LABEL,
            train_end_date=train_end_date,
            test_start_date=test_start_date,
        ),
        summarize_all_samples(
            multi_backtest,
            MULTI_LABEL,
            train_end_date=train_end_date,
            test_start_date=test_start_date,
        ),
    ]
    if not benchmark_nav.empty:
        for benchmark in [str(backtest_config.get("benchmark", "SPY")), "equal_weight_universe"]:
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
    comparison = pd.concat(frames, ignore_index=True)

    # 逐年对比专门用来看 2022：多因子有没有把那一年的坏结果改善。
    yearly = pd.concat(
        [
            build_yearly_performance(single_backtest).assign(strategy=SINGLE_LABEL),
            build_yearly_performance(multi_backtest).assign(strategy=MULTI_LABEL),
        ],
        ignore_index=True,
    )
    yearly = yearly.loc[:, ["strategy", *[c for c in yearly.columns if c != "strategy"]]]

    comparison.to_csv(reports_dir / "multi_factor_comparison.csv", index=False)
    yearly.to_csv(reports_dir / "multi_factor_yearly.csv", index=False)
    if not benchmark_nav.empty:
        plot_multi_factor_nav(single_backtest, multi_backtest, benchmark_nav, figures_dir)

    return {"comparison": comparison, "yearly": yearly}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run stage-18 multi-factor comparison.")
    parser.add_argument("--config", default="config.yaml", help="Path to project config YAML.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    outputs = build_multi_factor_report(config)
    print("Saved multi-factor reports to results/reports")
    comparison = outputs["comparison"]
    print(
        comparison.loc[
            :, ["series", "sample", "total_return", "sharpe_ratio", "max_drawdown"]
        ].to_string(index=False)
    )


if __name__ == "__main__":
    main()
