"""Stage 17 factor diagnostics: multi-horizon IC and factor correlation.

多因子组合之前必须先做两件体检，否则组合注定搭错：

1. 多 horizon IC：现有 IC 只在 1 天尺度算，而策略是月度调仓。动量在 1 天是反转、
   在月度才是动量——用错尺子会把有用的因子判成没用、还把方向搞反。所以这里在
   1 / 5 / 21 天多个尺度一起算 IC，看每个因子在贴近策略的月度尺度上的真实符号和强度。

2. 因子相关性：如果两个因子高度相关（预计 momentum 和 ma_deviation 都在刻画"价格在涨"），
   把它们一起塞进组合等于重复下注，并不增加信息。相关性矩阵用来发现这种冗余。

这一阶段只产诊断报告，不改策略、不做组合。组合放到下一阶段，用这里的结论来决定
选哪几个因子、各用什么符号。
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pandas as pd

from quant_factor.config import load_config
from quant_factor.evaluation import (
    calculate_forward_returns,
    calculate_ic_series,
    merge_factors_and_returns,
    summarize_ic,
)
from quant_factor.factors import FACTOR_COLUMNS


def build_multi_horizon_ic(
    factors: pd.DataFrame,
    prices: pd.DataFrame,
    *,
    horizons: list[int],
    factor_columns: list[str] | None = None,
) -> pd.DataFrame:
    """Compute RankIC summary for each factor across several forward-return horizons."""
    # 复用 evaluation 里已经验证过的 IC 计算：只是把 forward_days 换成多个尺度分别跑一遍。
    # 这样多 horizon 结果和主流程的单 horizon IC 用的是完全同一套口径，可直接对照。
    columns = factor_columns or [c for c in FACTOR_COLUMNS if c in factors.columns]
    if not columns or factors.empty:
        # 没有因子列或没有数据时直接返回空表：诊断是辅助分析，不该阻断流程。
        return pd.DataFrame()
    frames = []
    for horizon in horizons:
        forward_returns = calculate_forward_returns(prices, forward_days=int(horizon))
        evaluation_data = merge_factors_and_returns(factors, forward_returns)
        ic_series = calculate_ic_series(evaluation_data, factor_columns=columns)
        summary = summarize_ic(ic_series)
        summary.insert(0, "horizon", int(horizon))
        frames.append(summary)
    if not frames:
        return pd.DataFrame()
    result = pd.concat(frames, ignore_index=True)
    # ic_sign 只是把方向单独拎出来，方便下一阶段对齐符号；不代表因子一定显著。
    result["ic_sign"] = result["ic_mean"].apply(
        lambda value: 0 if pd.isna(value) else (1 if value > 0 else -1)
    )
    return result


def build_factor_correlation(
    factors: pd.DataFrame,
    *,
    factor_columns: list[str] | None = None,
    method: str = "spearman",
) -> pd.DataFrame:
    """Average daily cross-sectional correlation between factors."""
    # 正确的"因子相关性"是每天在截面上算一次相关，再对所有交易日取平均，
    # 而不是把所有 (日期, 股票) 混在一起算——后者会把时间序列和截面混淆。
    # 用 Spearman 是因为选股按排序进行，我们关心的是排序层面的相似度。
    columns = factor_columns or [c for c in FACTOR_COLUMNS if c in factors.columns]
    data = factors.copy()
    data["trade_date"] = pd.to_datetime(data["trade_date"], errors="coerce")
    for column in columns:
        data[column] = pd.to_numeric(data[column], errors="coerce")

    daily_correlations = []
    for _, date_data in data.groupby("trade_date", sort=True):
        cross_section = date_data.loc[:, columns]
        if cross_section.dropna(how="any").shape[0] < 2:
            continue
        daily_correlations.append(cross_section.corr(method=method))
    if not daily_correlations:
        return pd.DataFrame()

    stacked = pd.concat(daily_correlations)
    average = stacked.groupby(stacked.index, sort=False).mean()
    average = average.reindex(index=columns, columns=columns)
    average.index.name = "factor"
    return average.reset_index()


def build_diagnostics_report(config: dict[str, Any]) -> dict[str, pd.DataFrame]:
    """Compute and persist multi-horizon IC and factor correlation reports."""
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

    diagnostics_config = config.get("diagnostics", {})
    horizons = [int(h) for h in diagnostics_config.get("ic_horizons", [1, 5, 21])]
    method = diagnostics_config.get("correlation_method", "spearman")

    ic_by_horizon = build_multi_horizon_ic(factors, prices, horizons=horizons)
    correlation = build_factor_correlation(factors, method=method)

    ic_by_horizon.to_csv(reports_dir / "factor_ic_by_horizon.csv", index=False)
    correlation.to_csv(reports_dir / "factor_correlation.csv", index=False)
    return {"ic_by_horizon": ic_by_horizon, "correlation": correlation}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run stage-17 factor diagnostics.")
    parser.add_argument("--config", default="config.yaml", help="Path to project config YAML.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    outputs = build_diagnostics_report(config)
    print("Saved factor diagnostics to results/reports")
    print("--- IC by horizon ---")
    print(outputs["ic_by_horizon"].to_string(index=False))
    print("--- Factor correlation ---")
    print(outputs["correlation"].to_string(index=False))


if __name__ == "__main__":
    main()
