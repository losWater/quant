import pandas as pd
import pytest

from quant_factor.metrics import (
    annualized_return,
    annualized_volatility,
    build_drawdown_table,
    calmar_ratio,
    drawdown_series,
    max_drawdown,
    sharpe_ratio,
    summarize_performance,
)


def test_annualized_return() -> None:
    returns = pd.Series([0.01, 0.01])

    result = annualized_return(returns, periods_per_year=2)

    assert result == pytest.approx(0.0201)


def test_annualized_volatility() -> None:
    returns = pd.Series([0.01, -0.01])

    result = annualized_volatility(returns, periods_per_year=2)

    assert result == pytest.approx(0.02)


def test_drawdown_series() -> None:
    nav = pd.Series([1.0, 1.2, 0.9, 1.1])

    result = drawdown_series(nav)

    assert result.iloc[2] == pytest.approx(-0.25)


def test_max_drawdown() -> None:
    nav = pd.Series([1.0, 1.2, 0.9, 1.1])

    assert max_drawdown(nav) == pytest.approx(-0.25)


def test_sharpe_ratio_handles_nonzero_volatility() -> None:
    returns = pd.Series([0.01, -0.01, 0.02])

    result = sharpe_ratio(returns, periods_per_year=3)

    assert pd.notna(result)


def test_calmar_ratio() -> None:
    returns = pd.Series([0.1, -0.1])
    nav = (1 + returns).cumprod()

    result = calmar_ratio(returns, nav, periods_per_year=2)

    assert result == pytest.approx(-0.1)


def test_summarize_performance() -> None:
    backtest = pd.DataFrame(
        {
            "net_return": [0.1, -0.1],
            "nav": [1.1, 0.99],
            "turnover": [1.0, 0.5],
            "cost": [0.001, 0.002],
        }
    )

    result = summarize_performance(backtest, periods_per_year=2)

    assert result.loc[0, "total_return"] == pytest.approx(-0.01)
    assert result.loc[0, "average_turnover"] == pytest.approx(0.75)
    assert result.loc[0, "total_cost"] == pytest.approx(0.003)
    assert result.loc[0, "observations"] == 2


def test_build_drawdown_table() -> None:
    backtest = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(["2023-01-01", "2023-01-02"]),
            "nav": [1.0, 0.9],
        }
    )

    result = build_drawdown_table(backtest)

    assert result.loc[1, "drawdown"] == pytest.approx(-0.1)
