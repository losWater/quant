import pandas as pd
import pytest

from quant_factor.evaluation import (
    assign_quantile_groups,
    calculate_forward_returns,
    calculate_group_nav,
    calculate_group_returns,
    calculate_ic_series,
    merge_factors_and_returns,
    rank_ic,
    summarize_ic,
)


def test_rank_ic_uses_spearman_rank_correlation() -> None:
    factor = pd.Series([1.0, 2.0, 3.0])
    forward_return = pd.Series([0.1, 0.2, 0.3])

    assert rank_ic(factor, forward_return) == pytest.approx(1.0)


def test_calculate_forward_returns_uses_future_close_per_symbol() -> None:
    prices = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(
                ["2023-01-01", "2023-01-02", "2023-01-01", "2023-01-02"]
            ),
            "symbol": ["000001", "000001", "000002", "000002"],
            "close": [100.0, 110.0, 200.0, 180.0],
        }
    )

    result = calculate_forward_returns(prices, forward_days=1)

    first_symbol = result[result["symbol"] == "000001"].iloc[0]
    second_symbol = result[result["symbol"] == "000002"].iloc[0]
    assert first_symbol["forward_return"] == pytest.approx(0.1)
    assert second_symbol["forward_return"] == pytest.approx(-0.1)


def test_merge_factors_and_returns_aligns_on_date_and_symbol() -> None:
    factors = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(["2023-01-01"]),
            "symbol": ["000001"],
            "momentum": [1.0],
        }
    )
    returns = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(["2023-01-01"]),
            "symbol": ["000001"],
            "forward_return": [0.1],
        }
    )

    result = merge_factors_and_returns(factors, returns)

    assert result.loc[0, "momentum"] == 1.0
    assert result.loc[0, "forward_return"] == 0.1


def test_calculate_ic_series_by_trade_date() -> None:
    data = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(["2023-01-01", "2023-01-01", "2023-01-02"]),
            "symbol": ["000001", "000002", "000001"],
            "momentum": [1.0, 2.0, 1.0],
            "forward_return": [0.1, 0.2, 0.1],
        }
    )

    result = calculate_ic_series(data, factor_columns=["momentum"])

    assert result.loc[0, "momentum"] == pytest.approx(1.0)
    assert pd.isna(result.loc[1, "momentum"])


def test_summarize_ic_reports_mean_ir_and_hit_rate() -> None:
    ic_series = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(["2023-01-01", "2023-01-02"]),
            "momentum": [0.2, -0.1],
        }
    )

    result = summarize_ic(ic_series)

    assert result.loc[0, "factor"] == "momentum"
    assert result.loc[0, "ic_mean"] == pytest.approx(0.05)
    assert result.loc[0, "ic_positive_rate"] == pytest.approx(0.5)


def test_assign_quantile_groups_handles_small_cross_section() -> None:
    data = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(["2023-01-01", "2023-01-01", "2023-01-01"]),
            "momentum": [0.1, 0.2, 0.3],
        }
    )

    result = assign_quantile_groups(data, factor="momentum", groups=5)

    assert result.tolist() == [1, 2, 3]


def test_calculate_group_returns_equal_weights_within_group() -> None:
    data = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(["2023-01-01", "2023-01-01", "2023-01-01"]),
            "symbol": ["000001", "000002", "000003"],
            "momentum": [0.1, 0.2, 0.3],
            "forward_return": [0.01, 0.02, 0.03],
        }
    )

    result = calculate_group_returns(data, factor="momentum", groups=2)

    assert len(result) == 2
    assert result.loc[result["group"] == 1, "forward_return"].iloc[0] == pytest.approx(0.015)


def test_calculate_group_nav_compounds_returns() -> None:
    group_returns = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(["2023-01-01", "2023-01-02"]),
            "factor": ["momentum", "momentum"],
            "group": [1, 1],
            "forward_return": [0.1, 0.1],
        }
    )

    result = calculate_group_nav(group_returns)

    assert result["nav"].iloc[-1] == pytest.approx(1.21)
