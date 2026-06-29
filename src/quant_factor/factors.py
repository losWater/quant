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


def momentum(close: pd.Series, window: int = 20) -> pd.Series:
    """Calculate trailing return over a lookback window."""
    return close.pct_change(window)


def reversal(close: pd.Series, window: int = 5) -> pd.Series:
    """Calculate short-term reversal as negative trailing return."""
    return -close.pct_change(window)


def volatility(close: pd.Series, window: int = 20) -> pd.Series:
    """Calculate rolling volatility from daily returns."""
    return close.pct_change().rolling(window).std()


def moving_average_deviation(close: pd.Series, window: int = 20) -> pd.Series:
    """Calculate price deviation from its trailing moving average."""
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
    values = pd.to_numeric(values, errors="coerce")
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
    values = pd.to_numeric(values, errors="coerce")
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
