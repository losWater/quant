import pandas as pd
import pytest

from quant_factor.robustness import (
    build_cost_sensitivity,
    build_momentum_window_sensitivity,
    build_sample_split_performance,
    build_yearly_performance,
)


def test_build_yearly_performance_resets_nav_inside_each_year() -> None:
    backtest = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(["2022-12-30", "2023-01-03", "2023-01-04"]),
            "net_return": [0.1, 0.1, -0.1],
            "nav": [1.1, 1.21, 1.089],
            "turnover": [0.0, 0.0, 0.0],
            "cost": [0.0, 0.0, 0.0],
        }
    )

    result = build_yearly_performance(backtest)

    year_2023 = result[result["year"] == "2023"].iloc[0]
    assert year_2023["total_return"] == pytest.approx(-0.01)


def test_build_sample_split_performance_uses_fixed_dates() -> None:
    backtest = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(["2021-12-31", "2022-01-03"]),
            "net_return": [0.1, -0.1],
            "nav": [1.1, 0.99],
            "turnover": [0.0, 0.0],
            "cost": [0.0, 0.0],
        }
    )

    result = build_sample_split_performance(
        backtest,
        train_end_date="2021-12-31",
        test_start_date="2022-01-01",
    )

    assert result["sample"].tolist() == ["in_sample", "out_of_sample"]
    assert result.loc[result["sample"] == "in_sample", "total_return"].iloc[0] == pytest.approx(0.1)
    assert result.loc[result["sample"] == "out_of_sample", "total_return"].iloc[0] == pytest.approx(
        -0.1
    )


def test_build_cost_sensitivity_runs_multiple_cost_assumptions() -> None:
    prices = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(["2023-01-01", "2023-01-02", "2023-01-03"] * 2),
            "symbol": ["AAA", "AAA", "AAA", "BBB", "BBB", "BBB"],
            "close": [100.0, 110.0, 121.0, 100.0, 90.0, 81.0],
        }
    )
    factors = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(["2023-01-01", "2023-01-01"]),
            "symbol": ["AAA", "BBB"],
            "momentum": [1.0, -1.0],
        }
    )
    config = {
        "backtest": {
            "factor": "momentum",
            "rebalance_frequency": "daily",
            "portfolio_quantile": 0.5,
            "buy_commission_rate": 0.001,
            "sell_commission_rate": 0.0,
            "stamp_tax_rate": 0.0,
            "slippage_rate": 0.0,
        }
    }

    result = build_cost_sensitivity(prices, factors, config, cost_multipliers=[0.0, 1.0])

    assert result["cost_multiplier"].tolist() == ["0", "1"]
    assert result.loc[0, "total_cost"] < result.loc[1, "total_cost"]


def test_build_momentum_window_sensitivity_recalculates_factors() -> None:
    dates = pd.date_range("2023-01-01", periods=5)
    prices = pd.DataFrame(
        {
            "trade_date": list(dates) * 2,
            "symbol": ["AAA"] * 5 + ["BBB"] * 5,
            "close": [100.0, 101.0, 102.0, 103.0, 104.0, 100.0, 99.0, 98.0, 97.0, 96.0],
        }
    )
    config = {
        "factors": {
            "momentum_window": 1,
            "reversal_window": 1,
            "volatility_window": 1,
            "moving_average_window": 1,
            "winsorize_method": "none",
            "standardize": False,
        },
        "backtest": {
            "factor": "momentum",
            "rebalance_frequency": "daily",
            "portfolio_quantile": 0.5,
            "buy_commission_rate": 0.0,
            "sell_commission_rate": 0.0,
            "stamp_tax_rate": 0.0,
            "slippage_rate": 0.0,
        },
    }

    result = build_momentum_window_sensitivity(prices, config, momentum_windows=[1, 2])

    assert result["momentum_window"].tolist() == ["1", "2"]
    assert result["observations"].gt(0).all()
