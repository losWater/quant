import pandas as pd
import pytest

from quant_factor.multi_factor import build_composite_score


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


def test_composite_requires_known_factor() -> None:
    factors = pd.DataFrame(
        {"trade_date": pd.to_datetime(["2021-01-29"]), "symbol": ["AAA"], "momentum": [1.0]}
    )

    with pytest.raises(ValueError, match="composite factors"):
        build_composite_score(factors, {"nonexistent_factor": 1})
