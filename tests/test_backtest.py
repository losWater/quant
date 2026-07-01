import pandas as pd
import pytest

from quant_factor.backtest import (
    calculate_daily_returns,
    calculate_turnover,
    get_rebalance_dates,
    run_long_only_backtest,
    select_top_quantile,
    transaction_cost,
)


def test_transaction_cost_includes_commission_tax_and_slippage() -> None:
    cost = transaction_cost(
        turnover=1.0,
        buy_commission_rate=0.0003,
        sell_commission_rate=0.0003,
        stamp_tax_rate=0.001,
        slippage_rate=0.001,
    )

    assert cost == pytest.approx(0.0026)


def test_calculate_daily_returns_per_symbol() -> None:
    prices = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(["2023-01-01", "2023-01-02", "2023-01-01"]),
            "symbol": ["000001", "000001", "000002"],
            "close": [100.0, 110.0, 200.0],
        }
    )

    result = calculate_daily_returns(prices)

    second_day = result[result["symbol"] == "000001"].iloc[1]
    assert second_day["daily_return"] == pytest.approx(0.1)


def test_get_rebalance_dates_uses_month_end_trading_dates() -> None:
    dates = pd.Series(pd.to_datetime(["2023-01-02", "2023-01-31", "2023-02-01"]))

    result = get_rebalance_dates(dates, frequency="monthly")

    assert result.tolist() == [pd.Timestamp("2023-01-31"), pd.Timestamp("2023-02-01")]


def test_select_top_quantile_assigns_equal_weights() -> None:
    factors = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(["2023-01-01", "2023-01-01", "2023-01-01"]),
            "symbol": ["000001", "000002", "000003"],
            "momentum": [0.1, 0.3, 0.2],
        }
    )

    result = select_top_quantile(factors, factor="momentum", portfolio_quantile=0.5)

    assert result["symbol"].tolist() == ["000002", "000003"]
    assert result["target_weight"].tolist() == [0.5, 0.5]


def test_calculate_turnover_uses_one_way_turnover() -> None:
    current = pd.Series({"000001": 1.0})
    target = pd.Series({"000002": 1.0})

    assert calculate_turnover(current, target) == pytest.approx(1.0)


def test_run_long_only_backtest_applies_one_day_signal_delay_and_costs() -> None:
    prices = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(
                ["2023-01-01", "2023-01-02", "2023-01-03"] * 2
            ),
            "symbol": ["000001", "000001", "000001", "000002", "000002", "000002"],
            "close": [100.0, 110.0, 121.0, 100.0, 90.0, 81.0],
        }
    )
    factors = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(["2023-01-01", "2023-01-01"]),
            "symbol": ["000001", "000002"],
            "momentum": [1.0, -1.0],
        }
    )

    backtest, target_weights, active_weights = run_long_only_backtest(
        prices,
        factors,
        factor="momentum",
        rebalance_frequency="daily",
        portfolio_quantile=0.5,
        buy_commission_rate=0.001,
        sell_commission_rate=0.0,
        stamp_tax_rate=0.0,
        slippage_rate=0.0,
    )

    assert target_weights["symbol"].tolist() == ["000001"]
    assert active_weights["symbol"].iloc[0] == "000001"
    assert backtest.loc[0, "net_return"] == pytest.approx(0.0)
    assert backtest.loc[1, "cost"] == pytest.approx(0.001)
    assert backtest.loc[2, "net_return"] == pytest.approx(0.1)
