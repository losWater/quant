import pandas as pd
import pytest

from quant_factor.metrics import (
    annualized_return,
    annualized_volatility,
    build_benchmark_nav,
    build_drawdown_table,
    build_equal_weight_universe_nav,
    build_holding_summary,
    build_performance_comparison,
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


def test_build_benchmark_nav_aligns_to_strategy_dates() -> None:
    price_history = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(["2023-01-02", "2023-01-03", "2023-01-04"]),
            "symbol": ["spy", "SPY", "SPY"],
            "close": [100.0, 101.0, 103.02],
        }
    )

    result = build_benchmark_nav(
        price_history,
        pd.to_datetime(["2023-01-03", "2023-01-04"]),
        benchmark_symbol="SPY",
    )

    assert result["benchmark"].tolist() == ["SPY", "SPY"]
    assert result.loc[0, "benchmark_return"] == pytest.approx(0.01)
    assert result.loc[1, "benchmark_nav"] == pytest.approx(1.0302)


def test_build_performance_comparison_adds_strategy_and_benchmark_rows() -> None:
    backtest = pd.DataFrame(
        {
            "net_return": [0.1, -0.1],
            "nav": [1.1, 0.99],
            "turnover": [1.0, 0.5],
            "cost": [0.001, 0.002],
        }
    )
    benchmark_nav = pd.DataFrame(
        {
            "benchmark_return": [0.02, 0.03],
            "benchmark_nav": [1.02, 1.0506],
        }
    )

    result = build_performance_comparison(backtest, benchmark_nav, benchmark_symbol="spy")

    assert result["series"].tolist() == ["strategy", "SPY"]
    assert result.loc[result["series"] == "SPY", "total_return"].iloc[0] == pytest.approx(0.0506)


def test_build_equal_weight_universe_nav_uses_buy_and_hold_weights() -> None:
    prices = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(
                ["2023-01-02", "2023-01-03", "2023-01-02", "2023-01-03"]
            ),
            "symbol": ["AAA", "AAA", "BBB", "BBB"],
            "close": [100.0, 110.0, 50.0, 45.0],
        }
    )

    result = build_equal_weight_universe_nav(
        prices,
        pd.to_datetime(["2023-01-02", "2023-01-03"]),
    )

    assert result["benchmark"].tolist() == ["equal_weight_universe", "equal_weight_universe"]
    assert result.loc[0, "benchmark_nav"] == pytest.approx(1.0)
    assert result.loc[1, "benchmark_nav"] == pytest.approx(1.0)


def test_build_holding_summary_reports_concentration_and_contribution() -> None:
    active_weights = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(["2023-01-02", "2023-01-03", "2023-01-03"]),
            "symbol": ["AAA", "AAA", "BBB"],
            "weight": [1.0, 0.5, 0.5],
        }
    )
    prices = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(
                ["2023-01-02", "2023-01-03", "2023-01-02", "2023-01-03"]
            ),
            "symbol": ["AAA", "AAA", "BBB", "BBB"],
            "close": [100.0, 110.0, 50.0, 45.0],
        }
    )

    result = build_holding_summary(active_weights, prices)

    assert result.loc[result["symbol"] == "AAA", "holding_days"].iloc[0] == 2
    assert result.loc[result["symbol"] == "AAA", "gross_return_contribution"].iloc[
        0
    ] == pytest.approx(0.05)
    assert result["absolute_contribution_share"].sum() == pytest.approx(1.0)
