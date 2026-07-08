import pandas as pd
import pytest

from quant_factor.backtest import run_long_only_backtest, select_sector_neutral
from quant_factor.neutralization import summarize_all_samples

# 4 只股票、两个行业：Tech = {AAA, BBB}，Health = {CCC, DDD}。
# 等权基准下每个行业占 2/4 = 50%，用来验证行业中性权重是否正确对齐。
SECTOR_MAP = pd.Series({"AAA": "Tech", "BBB": "Tech", "CCC": "Health", "DDD": "Health"})


def _factors_one_date() -> pd.DataFrame:
    # 同一个调仓日，Tech 里 AAA 动量更高，Health 里 CCC 更高。
    return pd.DataFrame(
        {
            "trade_date": pd.to_datetime(["2021-01-29"] * 4),
            "symbol": ["AAA", "BBB", "CCC", "DDD"],
            "momentum": [0.9, 0.1, 0.8, 0.2],
        }
    )


def test_sector_neutral_weights_align_to_benchmark() -> None:
    selected = select_sector_neutral(
        _factors_one_date(),
        SECTOR_MAP,
        factor="momentum",
        portfolio_quantile=0.5,
    )

    # 每行业 2 只选 top 50% = 1 只：Tech 选 AAA，Health 选 CCC。
    assert set(selected["symbol"]) == {"AAA", "CCC"}
    # 每个行业总权重 = 基准 50%，行业内只 1 只，所以每只 0.5，且权重和为 1（满仓）。
    assert selected["target_weight"].sum() == pytest.approx(1.0)
    assert selected.set_index("symbol").loc["AAA", "target_weight"] == pytest.approx(0.5)
    assert selected.set_index("symbol").loc["CCC", "target_weight"] == pytest.approx(0.5)


def test_sector_neutral_picks_top_within_each_sector() -> None:
    selected = select_sector_neutral(
        _factors_one_date(),
        SECTOR_MAP,
        factor="momentum",
        portfolio_quantile=0.5,
    )

    # 中性化不是全市场选最强，而是每个行业各选自己的最强。
    # 若是全市场 top 2，会选 AAA(0.9) 和 CCC(0.8)，这里恰好一致，
    # 但 BBB(0.1) 属于 Tech、DDD(0.2) 属于 Health，验证没有跨行业挤占。
    assert "BBB" not in set(selected["symbol"])
    assert "DDD" not in set(selected["symbol"])


def test_run_long_only_backtest_sector_neutral_requires_map() -> None:
    prices = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(["2021-01-04", "2021-01-05"]),
            "symbol": ["AAA", "AAA"],
            "close": [100.0, 101.0],
        }
    )
    factors = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(["2021-01-04"]),
            "symbol": ["AAA"],
            "momentum": [0.5],
        }
    )

    with pytest.raises(ValueError, match="sector_map"):
        run_long_only_backtest(
            prices,
            factors,
            factor="momentum",
            rebalance_frequency="monthly",
            portfolio_quantile=0.2,
            buy_commission_rate=0.0,
            sell_commission_rate=0.0,
            stamp_tax_rate=0.0,
            slippage_rate=0.0,
            sector_neutral=True,
        )


def test_summarize_all_samples_tags_series_and_samples() -> None:
    returns = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(["2021-06-01", "2022-06-01"]),
            "net_return": [0.05, -0.02],
        }
    )

    summary = summarize_all_samples(
        returns,
        "demo",
        train_end_date="2021-12-31",
        test_start_date="2022-01-01",
    )

    assert set(summary["series"]) == {"demo"}
    assert set(summary["sample"]) == {"full_sample", "in_sample", "out_of_sample"}
