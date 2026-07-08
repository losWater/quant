import pandas as pd
import pytest

from quant_factor.multi_factor import build_composite_score, derive_factor_signs


def _factors_one_date() -> pd.DataFrame:
    # 单个调仓日、4 只股票。momentum 与 volatility 刻意反向排列，
    # 用来验证方向对齐（momentum 翻转符号）后综合分的排序是否符合预期。
    return pd.DataFrame(
        {
            "trade_date": pd.to_datetime(["2021-01-29"] * 4),
            "symbol": ["AAA", "BBB", "CCC", "DDD"],
            "momentum": [2.0, 1.0, -1.0, -2.0],
            "reversal": [0.0, 0.0, 0.0, 0.0],
            "volatility": [0.0, 0.0, 0.0, 0.0],
        }
    )


def test_composite_flips_momentum_sign() -> None:
    scored = build_composite_score(_factors_one_date(), {"momentum": -1}).set_index("symbol")

    # momentum 符号为 -1：momentum 最高的 AAA 应得到最低综合分，最低的 DDD 得到最高分。
    assert scored.loc["AAA", "composite_score"] < scored.loc["DDD", "composite_score"]
    assert scored.loc["AAA", "composite_score"] == pytest.approx(
        -scored.loc["DDD", "composite_score"]
    )


def test_composite_equal_weights_standardized_factors() -> None:
    # 两个因子完全相同、符号都 +1：综合分应等于单因子 z-score 的 2 倍（等权相加）。
    factors = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(["2021-01-29"] * 3),
            "symbol": ["AAA", "BBB", "CCC"],
            "momentum": [1.0, 0.0, -1.0],
            "volatility": [1.0, 0.0, -1.0],
        }
    )

    combined = build_composite_score(factors, {"momentum": 1, "volatility": 1})
    combined = combined.set_index("symbol")["composite_score"]
    only_momentum = build_composite_score(factors, {"momentum": 1})
    only_momentum = only_momentum.set_index("symbol")["composite_score"]

    assert combined.to_numpy() == pytest.approx(2 * only_momentum.to_numpy())


def test_derive_factor_signs_from_train_window() -> None:
    # 训练窗口 2020 全年。价格单调：AAA 涨最快、CCC 最慢 -> 未来收益 AAA>BBB>CCC。
    dates = pd.bdate_range("2020-01-01", "2020-06-30")
    price_rows = []
    for symbol, step in [("AAA", 3.0), ("BBB", 2.0), ("CCC", 1.0)]:
        close = 100.0
        for date in dates:
            price_rows.append({"trade_date": date, "symbol": symbol, "close": close})
            close += step
    prices = pd.DataFrame(price_rows)

    factor_rows = []
    for symbol, good, bad in [("AAA", 3.0, 1.0), ("BBB", 2.0, 2.0), ("CCC", 1.0, 3.0)]:
        for date in dates:
            factor_rows.append(
                {"trade_date": date, "symbol": symbol, "good": good, "bad": bad}
            )
    factors = pd.DataFrame(factor_rows)

    signs = derive_factor_signs(
        factors,
        prices,
        ["good", "bad"],
        start_date="2020-01-01",
        end_date="2020-06-30",
        horizon=5,
    )

    # good 与未来收益同向 -> IC 正 -> +1；bad 与未来收益反向 -> IC 负 -> -1。
    assert signs["good"] == 1
    assert signs["bad"] == -1


def test_composite_requires_known_factor() -> None:
    factors = pd.DataFrame(
        {"trade_date": pd.to_datetime(["2021-01-29"]), "symbol": ["AAA"], "momentum": [1.0]}
    )

    with pytest.raises(ValueError, match="composite factors"):
        build_composite_score(factors, {"nonexistent_factor": 1})
