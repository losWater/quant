"""Factor evaluation utilities."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import pandas as pd

from quant_factor.config import load_config
from quant_factor.factors import FACTOR_COLUMNS


# IC 是因子检验的核心指标：每天看因子排序和未来收益排序是否同向。
def rank_ic(factor: pd.Series, forward_return: pd.Series) -> float:
    """Calculate Spearman rank IC for one cross-section."""
    aligned = pd.concat([factor, forward_return], axis=1).dropna()
    if len(aligned) < 2:
        return float("nan")
    return float(aligned.iloc[:, 0].corr(aligned.iloc[:, 1], method="spearman"))


def calculate_forward_returns(
    prices: pd.DataFrame,
    *,
    forward_days: int = 1,
) -> pd.DataFrame:
    """Calculate per-symbol forward returns from close prices.

    The value on date T is the return from T to T + forward_days, so it can be
    joined to factors observed at T without using future data in factor inputs.
    """
    # T 日这一行保存的是 T 到 T+forward_days 的收益，用来和 T 日因子合并。
    required = {"trade_date", "symbol", "close"}
    missing = required - set(prices.columns)
    if missing:
        raise ValueError(f"Price data is missing required columns: {sorted(missing)}")

    data = prices.loc[:, ["trade_date", "symbol", "close"]].copy()
    data["trade_date"] = pd.to_datetime(data["trade_date"], errors="coerce")
    data["close"] = pd.to_numeric(data["close"], errors="coerce")
    data = data.dropna(subset=["trade_date", "symbol", "close"])
    data = data.sort_values(["symbol", "trade_date"])
    data["forward_return"] = data.groupby("symbol")["close"].transform(
        lambda close: close.shift(-forward_days) / close - 1
    )
    return data.loc[:, ["trade_date", "symbol", "forward_return"]]


def merge_factors_and_returns(
    factors: pd.DataFrame,
    forward_returns: pd.DataFrame,
) -> pd.DataFrame:
    """Join factor values at T with forward returns after T."""
    # 只按同一只股票、同一个 T 日合并；未来收益已经提前 shift 到 T 日。
    factors_data = factors.copy()
    returns_data = forward_returns.copy()
    factors_data["trade_date"] = pd.to_datetime(factors_data["trade_date"], errors="coerce")
    returns_data["trade_date"] = pd.to_datetime(returns_data["trade_date"], errors="coerce")
    return factors_data.merge(returns_data, on=["trade_date", "symbol"], how="inner")


def calculate_ic_series(
    evaluation_data: pd.DataFrame,
    *,
    factor_columns: list[str] | None = None,
) -> pd.DataFrame:
    """Calculate daily RankIC for each factor."""
    # 每个交易日单独算一次 RankIC，得到一条随时间变化的 IC 序列。
    factor_columns = factor_columns or [
        column for column in FACTOR_COLUMNS if column in evaluation_data.columns
    ]
    rows: list[dict[str, Any]] = []
    for trade_date, date_data in evaluation_data.groupby("trade_date", sort=True):
        row: dict[str, Any] = {"trade_date": trade_date}
        for factor in factor_columns:
            row[factor] = rank_ic(date_data[factor], date_data["forward_return"])
        rows.append(row)
    return pd.DataFrame(rows).sort_values("trade_date").reset_index(drop=True)


def summarize_ic(ic_series: pd.DataFrame) -> pd.DataFrame:
    """Summarize IC mean, stability, and hit rate for each factor."""
    # IC_IR 衡量因子方向是否稳定；正值比例用于观察因子胜率。
    rows = []
    for factor in [column for column in ic_series.columns if column != "trade_date"]:
        values = pd.to_numeric(ic_series[factor], errors="coerce").dropna()
        ic_std = values.std(ddof=1)
        rows.append(
            {
                "factor": factor,
                "ic_mean": values.mean(),
                "ic_std": ic_std,
                "ic_ir": values.mean() / ic_std if ic_std and not pd.isna(ic_std) else float("nan"),
                "ic_positive_rate": (values > 0).mean() if not values.empty else float("nan"),
                "observations": len(values),
            }
        )
    return pd.DataFrame(rows)


def assign_quantile_groups(
    data: pd.DataFrame,
    *,
    factor: str,
    groups: int = 5,
) -> pd.Series:
    """Assign 1-based factor quantile groups within each trade date."""

    def assign_one_date(values: pd.Series) -> pd.Series:
        # 小样本时可用组数会少于配置组数，避免 qcut 因样本不足失败。
        valid = values.dropna()
        if valid.empty:
            return pd.Series(pd.NA, index=values.index, dtype="Int64")
        effective_groups = min(groups, valid.nunique(), len(valid))
        if effective_groups < 2:
            return pd.Series(1, index=values.index, dtype="Int64").where(values.notna())
        ranks = valid.rank(method="first")
        labels = range(1, effective_groups + 1)
        assigned = pd.qcut(ranks, q=effective_groups, labels=labels).astype("Int64")
        result = pd.Series(pd.NA, index=values.index, dtype="Int64")
        result.loc[valid.index] = assigned
        return result

    return data.groupby("trade_date", group_keys=False)[factor].apply(assign_one_date)


def calculate_group_returns(
    evaluation_data: pd.DataFrame,
    *,
    factor: str,
    groups: int = 5,
) -> pd.DataFrame:
    """Calculate equal-weight forward returns for factor quantile groups."""
    # 分组回测用来观察因子是否有单调性，不在这里计入交易成本。
    data = evaluation_data.loc[:, ["trade_date", "symbol", factor, "forward_return"]].copy()
    data["group"] = assign_quantile_groups(data, factor=factor, groups=groups)
    data = data.dropna(subset=["group", "forward_return"])
    if data.empty:
        return pd.DataFrame(columns=["trade_date", "factor", "group", "forward_return"])

    grouped = (
        data.groupby(["trade_date", "group"], observed=True)["forward_return"]
        .mean()
        .reset_index()
    )
    grouped["factor"] = factor
    return grouped.loc[:, ["trade_date", "factor", "group", "forward_return"]]


def calculate_group_nav(group_returns: pd.DataFrame) -> pd.DataFrame:
    """Convert group forward returns into cumulative net value curves."""
    # 每组把未来收益复利累乘，得到直观的分组净值曲线。
    if group_returns.empty:
        return pd.DataFrame(columns=["trade_date", "factor", "group", "nav"])
    data = group_returns.sort_values(["factor", "group", "trade_date"]).copy()
    data["nav"] = data.groupby(["factor", "group"], observed=True)["forward_return"].transform(
        lambda returns: (1 + returns).cumprod()
    )
    return data.loc[:, ["trade_date", "factor", "group", "nav"]]


def evaluate_factors(config: dict[str, Any]) -> dict[str, pd.DataFrame]:
    """Run factor IC and quantile group evaluation, then persist reports."""
    # 主流程：价格算未来收益 -> 合并因子 -> IC 检验 -> 分组收益和图表。
    processed_dir = Path(config["data"]["processed_dir"])
    reports_dir = Path(config["output"]["reports_dir"])
    figures_dir = Path(config["output"]["figures_dir"])
    reports_dir.mkdir(parents=True, exist_ok=True)
    figures_dir.mkdir(parents=True, exist_ok=True)

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

    evaluation_config = config.get("evaluation", {})
    forward_returns = calculate_forward_returns(
        prices,
        forward_days=evaluation_config.get("forward_return_days", 1),
    )
    evaluation_data = merge_factors_and_returns(factors, forward_returns)
    factor_columns = [column for column in FACTOR_COLUMNS if column in evaluation_data.columns]

    ic_series = calculate_ic_series(evaluation_data, factor_columns=factor_columns)
    ic_summary = summarize_ic(ic_series)
    group_returns = pd.concat(
        [
            calculate_group_returns(
                evaluation_data,
                factor=factor,
                groups=evaluation_config.get("quantile_groups", 5),
            )
            for factor in factor_columns
        ],
        ignore_index=True,
    )
    group_nav = calculate_group_nav(group_returns)

    ic_series.to_csv(reports_dir / "ic_series.csv", index=False)
    ic_summary.to_csv(reports_dir / "ic_summary.csv", index=False)
    group_returns.to_csv(reports_dir / "group_returns.csv", index=False)
    group_nav.to_csv(reports_dir / "group_nav.csv", index=False)
    plot_group_nav(group_nav, figures_dir / "group_nav.png")

    return {
        "ic_series": ic_series,
        "ic_summary": ic_summary,
        "group_returns": group_returns,
        "group_nav": group_nav,
    }


def plot_group_nav(group_nav: pd.DataFrame, output_path: Path) -> None:
    """Plot quantile group NAV curves for each factor."""
    # 图只作为研究报告输出，生成文件由 .gitignore 忽略。
    if group_nav.empty:
        return

    factor_count = group_nav["factor"].nunique()
    fig, axes = plt.subplots(factor_count, 1, figsize=(10, max(3, 3 * factor_count)), sharex=True)
    if factor_count == 1:
        axes = [axes]

    for axis, (factor, factor_data) in zip(
        axes,
        group_nav.groupby("factor", sort=True),
        strict=False,
    ):
        for group, group_data in factor_data.groupby("group", sort=True):
            axis.plot(group_data["trade_date"], group_data["nav"], label=f"group {group}")
        axis.set_title(f"{factor} group NAV")
        axis.set_ylabel("NAV")
        axis.legend(loc="best")
        axis.grid(alpha=0.3)

    axes[-1].set_xlabel("Trade date")
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate factor predictive power.")
    parser.add_argument("--config", default="config.yaml", help="Path to project config YAML.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    outputs = evaluate_factors(config)
    summary = outputs["ic_summary"]
    print("Saved factor evaluation reports to results/reports")
    if not summary.empty:
        print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
