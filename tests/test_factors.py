import pandas as pd

from quant_factor.factors import momentum, reversal, volatility


def test_momentum_uses_only_trailing_prices() -> None:
    close = pd.Series([100.0, 110.0, 121.0])

    result = momentum(close, window=1)

    assert result.iloc[2] == 0.1


def test_reversal_is_negative_momentum() -> None:
    close = pd.Series([100.0, 110.0])

    result = reversal(close, window=1)

    assert result.iloc[1] == -0.1


def test_volatility_returns_rolling_std() -> None:
    close = pd.Series([100.0, 101.0, 102.0, 103.0])

    result = volatility(close, window=2)

    assert result.notna().sum() == 2
