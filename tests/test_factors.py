import pandas as pd
import pytest

from quant_factor.factors import (
    calculate_raw_factors,
    momentum,
    moving_average_deviation,
    preprocess_factors,
    reversal,
    volatility,
    winsorize_mad,
    zscore,
)


def test_momentum_uses_only_trailing_prices() -> None:
    close = pd.Series([100.0, 110.0, 121.0])

    result = momentum(close, window=1)

    assert result.iloc[2] == pytest.approx(0.1)


def test_reversal_is_negative_momentum() -> None:
    close = pd.Series([100.0, 110.0])

    result = reversal(close, window=1)

    assert result.iloc[1] == pytest.approx(-0.1)


def test_volatility_returns_rolling_std() -> None:
    close = pd.Series([100.0, 101.0, 102.0, 103.0])

    result = volatility(close, window=2)

    assert result.notna().sum() == 2


def test_moving_average_deviation_uses_trailing_average() -> None:
    close = pd.Series([100.0, 110.0, 121.0])

    result = moving_average_deviation(close, window=2)

    assert result.iloc[2] == pytest.approx(121.0 / 115.5 - 1)


def test_calculate_raw_factors_keeps_symbols_separate() -> None:
    prices = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(
                ["2023-01-01", "2023-01-02", "2023-01-01", "2023-01-02"]
            ),
            "symbol": ["000001", "000001", "000002", "000002"],
            "close": [100.0, 110.0, 200.0, 180.0],
        }
    )

    result = calculate_raw_factors(
        prices,
        {
            "momentum_window": 1,
            "reversal_window": 1,
            "volatility_window": 1,
            "moving_average_window": 1,
        },
    )

    symbol_1 = result[result["symbol"] == "000001"].iloc[-1]
    symbol_2 = result[result["symbol"] == "000002"].iloc[-1]
    assert symbol_1["momentum"] == pytest.approx(0.1)
    assert symbol_2["momentum"] == pytest.approx(-0.1)


def test_winsorize_mad_clips_extreme_values() -> None:
    values = pd.Series([1.0, 1.0, 2.0, 2.0, 100.0])

    result = winsorize_mad(values, limit=3.0)

    assert result.max() < 100.0


def test_zscore_standardizes_values() -> None:
    result = zscore(pd.Series([1.0, 2.0, 3.0]))

    assert result.mean() == pytest.approx(0.0)
    assert result.std(ddof=1) == pytest.approx(1.0)


def test_preprocess_factors_runs_by_trade_date() -> None:
    factors = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(["2023-01-01", "2023-01-01", "2023-01-02"]),
            "symbol": ["000001", "000002", "000001"],
            "momentum": [1.0, 3.0, 10.0],
            "reversal": [3.0, 1.0, 10.0],
        }
    )

    result = preprocess_factors(
        factors,
        factor_columns=["momentum", "reversal"],
        winsorize_method="none",
        standardize=True,
    )

    first_day = result[result["trade_date"] == pd.Timestamp("2023-01-01")]
    single_name_day = result[result["trade_date"] == pd.Timestamp("2023-01-02")]
    assert first_day["momentum"].mean() == pytest.approx(0.0)
    assert single_name_day["momentum"].iloc[0] == pytest.approx(0.0)
