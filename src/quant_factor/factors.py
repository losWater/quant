"""Factor calculation and preprocessing functions."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pandas as pd

from quant_factor.config import load_config

FACTOR_COLUMNS = [
    "momentum",
    "reversal",
    "volatility",
    "ma_deviation",
]


# 单因子函数只接收价格序列，保持纯函数形态，方便测试和复用。
def momentum(close: pd.Series, window: int = 20) -> pd.Series:
    """Calculate trailing return over a lookback window."""
    # 动量因子的脑洞：过去一段时间涨得强的股票，短期可能继续强。
    # pct_change(window) 只用当前和过去 window 天价格，不会看到未来。
    return close.pct_change(window)


def reversal(close: pd.Series, window: int = 5) -> pd.Series:
    """Calculate short-term reversal as negative trailing return."""
    # 反转因子的脑洞：短期跌太多的股票可能反弹，涨太多的可能回落。
    # 所以这里直接对短期收益取负，方向和 momentum 相反。
    return -close.pct_change(window)


def volatility(close: pd.Series, window: int = 20) -> pd.Series:
    """Calculate rolling volatility from daily returns."""
    # 波动率因子的脑洞：高波动可能代表风险高、情绪极端或定价不稳定。
    # 这里用过去 window 天日收益标准差，仍然只看历史。
    return close.pct_change().rolling(window).std()


def moving_average_deviation(close: pd.Series, window: int = 20) -> pd.Series:
    """Calculate price deviation from its trailing moving average."""
    # 均线偏离的脑洞：价格离近期均值太远，可能存在回归或趋势延续。
    # 它不是天然“看多”或“看空”，需要后续 IC/回测告诉我们方向是否稳定。
    moving_average = close.rolling(window).mean()
    return close / moving_average - 1


def calculate_symbol_factors(
    data: pd.DataFrame,
    *,
    momentum_window: int = 20,
    reversal_window: int = 5,
    volatility_window: int = 20,
    moving_average_window: int = 20,
) -> pd.DataFrame:
    """Calculate raw factors for one symbol's chronologically sorted price data."""
    # 每只股票单独按时间滚动计算，避免把不同股票的价格序列接在一起。
    # 如果把 AAPL 后面直接接 MSFT，pct_change/rolling 会把两只股票当成一条时间序列，
    # 这会产生非常隐蔽的错误，也是量化数据处理里常见的坑。
    required = {"trade_date", "symbol", "close"}
    missing = required - set(data.columns)
    if missing:
        raise ValueError(f"Price data is missing required columns: {sorted(missing)}")

    result = data.sort_values("trade_date").loc[:, ["trade_date", "symbol", "close"]].copy()
    close = result["close"]
    result["momentum"] = momentum(close, momentum_window)
    result["reversal"] = reversal(close, reversal_window)
    result["volatility"] = volatility(close, volatility_window)
    result["ma_deviation"] = moving_average_deviation(close, moving_average_window)
    return result.drop(columns=["close"])


def calculate_raw_factors(price_data: pd.DataFrame, factor_config: dict[str, Any]) -> pd.DataFrame:
    """Calculate raw factors for all symbols in a daily price dataset."""
    # 配置里的窗口参数统一在这里传入，便于后续做参数敏感性测试。
    # 例如阶段 6 会把 momentum_window 改成 10/20/40/60，
    # 观察策略是否只靠一个“刚好好看”的参数。
    data = price_data.copy()
    data["trade_date"] = pd.to_datetime(data["trade_date"], errors="coerce")
    data = data.dropna(subset=["trade_date", "symbol", "close"])

    frames = [
        calculate_symbol_factors(
            symbol_data,
            momentum_window=factor_config.get("momentum_window", 20),
            reversal_window=factor_config.get("reversal_window", 5),
            volatility_window=factor_config.get("volatility_window", 20),
            moving_average_window=factor_config.get("moving_average_window", 20),
        )
        for _, symbol_data in data.groupby("symbol", sort=True)
    ]
    if not frames:
        return pd.DataFrame(columns=["trade_date", "symbol", *FACTOR_COLUMNS])
    return pd.concat(frames, ignore_index=True).sort_values(["trade_date", "symbol"])


def winsorize_mad(values: pd.Series, limit: float = 3.0) -> pd.Series:
    """Winsorize one cross-section using median absolute deviation."""
    # 对每天的截面做稳健去极值，避免极端值主导排序或统计结果。
    # 为什么用 MAD 而不是均值/标准差？
    # 因为极端值本身会把均值和标准差拉歪，而中位数和 MAD 对异常值更不敏感。
    values = pd.to_numeric(values, errors="coerce")
    if values.dropna().empty:
        return values
    median = values.median(skipna=True)
    mad = (values - median).abs().median(skipna=True)
    if pd.isna(mad) or mad == 0:
        return values
    robust_sigma = 1.4826 * mad
    lower = median - limit * robust_sigma
    upper = median + limit * robust_sigma
    return values.clip(lower=lower, upper=upper)


def zscore(values: pd.Series) -> pd.Series:
    """Standardize one cross-section to zero mean and unit sample standard deviation."""
    # 标准化后，不同因子的数值尺度更可比。
    # 比如 momentum 可能是 0.05，volatility 可能是 0.02，
    # 如果以后做多因子模型，必须先让它们在同一个量纲上比较。
    values = pd.to_numeric(values, errors="coerce")
    if values.dropna().empty:
        return values
    std = values.std(skipna=True, ddof=1)
    if pd.isna(std) or std == 0:
        return values * 0
    return (values - values.mean(skipna=True)) / std


def preprocess_factors(
    factors: pd.DataFrame,
    *,
    factor_columns: list[str] | None = None,
    winsorize_method: str = "mad",
    winsorize_limit: float = 3.0,
    standardize: bool = True,
) -> pd.DataFrame:
    """Apply per-date winsorization and standardization to factor columns."""
    # 预处理必须按交易日截面做，不能用未来日期的数据参与当前日期标准化。
    # 这是防未来函数的关键点之一：
    # T 日只能用 T 日这个截面的股票分布做去极值/标准化，
    # 不能拿全年数据一起标准化，否则未来股票分布会泄露给过去。
    factor_columns = factor_columns or FACTOR_COLUMNS
    result = factors.copy()
    result["trade_date"] = pd.to_datetime(result["trade_date"], errors="coerce")

    for column in factor_columns:
        if column not in result:
            continue
        processed = result.groupby("trade_date", group_keys=False)[column]
        if winsorize_method == "mad":
            result[column] = processed.apply(lambda values: winsorize_mad(values, winsorize_limit))
        elif winsorize_method not in {"none", None}:
            raise ValueError(f"Unsupported winsorize method: {winsorize_method}")

        if standardize:
            result[column] = result.groupby("trade_date", group_keys=False)[column].apply(zscore)

    return result.sort_values(["trade_date", "symbol"]).reset_index(drop=True)


def build_factor_dataset(config: dict[str, Any]) -> pd.DataFrame:
    """Build and persist the factor dataset from processed daily prices."""
    # 主流程：读取清洗行情 -> 计算原始因子 -> 截面预处理 -> 输出因子表。
    # 注意：这里每天都计算因子，不代表每天都交易。
    # 每日因子用于 IC/分组研究；回测会按 rebalance_frequency 只取调仓日的因子。
    processed_dir = Path(config["data"]["processed_dir"])
    price_path = processed_dir / "daily_prices.csv"
    if not price_path.exists():
        raise FileNotFoundError(f"Missing processed price dataset: {price_path}")

    prices = pd.read_csv(price_path, dtype={"symbol": "string"}, parse_dates=["trade_date"])
    factor_config = config.get("factors", {})
    raw_factors = calculate_raw_factors(prices, factor_config)
    factors = preprocess_factors(
        raw_factors,
        winsorize_method=factor_config.get("winsorize_method", "mad"),
        winsorize_limit=factor_config.get("winsorize_limit", 3.0),
        standardize=factor_config.get("standardize", True),
    )

    output_path = processed_dir / "factors.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    factors.to_csv(output_path, index=False)
    return factors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Calculate factor values from daily prices.")
    parser.add_argument("--config", default="config.yaml", help="Path to project config YAML.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    data = build_factor_dataset(config)
    output_path = Path(config["data"]["processed_dir"]) / "factors.csv"
    print(f"Saved {len(data)} factor rows to {output_path}")


if __name__ == "__main__":
    main()
