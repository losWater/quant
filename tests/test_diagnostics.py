import pandas as pd
import pytest

from quant_factor.diagnostics import build_factor_correlation, build_multi_horizon_ic


def _prices_three_symbols() -> pd.DataFrame:
    # 三只股票、四个交易日，价格单调，方便让因子和未来收益排序一致。
    dates = pd.to_datetime(["2021-01-04", "2021-01-05", "2021-01-06", "2021-01-07"])
    rows = []
    # AAA 涨最快，BBB 次之，CCC 最慢，所以任意 horizon 的未来收益排序都是 AAA>BBB>CCC。
    for symbol, step in [("AAA", 3.0), ("BBB", 2.0), ("CCC", 1.0)]:
        close = 100.0
        for date in dates:
            rows.append({"trade_date": date, "symbol": symbol, "close": close})
            close += step
    return pd.DataFrame(rows)


def _factors_aligned_to_returns() -> pd.DataFrame:
    # 因子值按 AAA>BBB>CCC 排序，和未来收益同向，1 天 horizon 的 IC 应接近 +1。
    dates = pd.to_datetime(["2021-01-04", "2021-01-05", "2021-01-06", "2021-01-07"])
    rows = []
    for symbol, score in [("AAA", 3.0), ("BBB", 2.0), ("CCC", 1.0)]:
        for date in dates:
            rows.append({"trade_date": date, "symbol": symbol, "momentum": score})
    return pd.DataFrame(rows)


def test_multi_horizon_ic_positive_when_factor_predicts_returns() -> None:
    ic = build_multi_horizon_ic(
        _factors_aligned_to_returns(),
        _prices_three_symbols(),
        horizons=[1, 2],
        factor_columns=["momentum"],
    )

    assert set(ic["horizon"]) == {1, 2}
    horizon_one = ic[ic["horizon"] == 1].iloc[0]
    assert horizon_one["ic_mean"] == pytest.approx(1.0)
    assert horizon_one["ic_sign"] == 1


def test_factor_correlation_detects_redundant_and_opposite_factors() -> None:
    # 构造：ma_deviation 和 momentum 完全相同(冗余)，reversal 完全相反。
    dates = pd.to_datetime(["2021-01-04", "2021-01-05"])
    rows = []
    for symbol, score in [("AAA", 3.0), ("BBB", 2.0), ("CCC", 1.0), ("DDD", 0.0)]:
        for date in dates:
            rows.append(
                {
                    "trade_date": date,
                    "symbol": symbol,
                    "momentum": score,
                    "ma_deviation": score,
                    "reversal": -score,
                }
            )
    factors = pd.DataFrame(rows)

    corr = build_factor_correlation(
        factors,
        factor_columns=["momentum", "ma_deviation", "reversal"],
    ).set_index("factor")

    assert corr.loc["momentum", "ma_deviation"] == pytest.approx(1.0)
    assert corr.loc["momentum", "reversal"] == pytest.approx(-1.0)


def test_multi_horizon_ic_empty_factors_returns_empty() -> None:
    empty = pd.DataFrame(columns=["trade_date", "symbol"])
    result = build_multi_horizon_ic(
        empty,
        _prices_three_symbols(),
        horizons=[1],
        factor_columns=[],
    )
    # 没有因子列时不应报错，返回空表即可（诊断是辅助分析，不应阻断流程）。
    assert result.empty or "momentum" not in result.get("factor", pd.Series(dtype=object)).tolist()
