import pandas as pd
import pytest

from quant_factor.exposure import (
    _prepare_holdings,
    _universe_sector_share,
    build_sector_attribution,
    build_sector_exposure,
    build_symbol_concentration,
)

# 一个可手算的小组合：两个交易日，每天等权持有 AAA/BBB/CCC 三只股票。
# AAA、BBB 属于科技，CCC 属于医药，用来验证行业聚合是否正确。
SECTOR_MAP = pd.Series(
    {"AAA": "Tech", "BBB": "Tech", "CCC": "Health"},
    name="sector",
)


def _sample_active_weights() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "trade_date": pd.to_datetime(
                ["2021-01-04", "2021-01-04", "2021-01-04", "2021-01-05", "2021-01-05", "2021-01-05"]
            ),
            "symbol": ["AAA", "BBB", "CCC", "AAA", "BBB", "CCC"],
            "weight": [1 / 3, 1 / 3, 1 / 3, 1 / 3, 1 / 3, 1 / 3],
        }
    )


def _sample_prices() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "trade_date": pd.to_datetime(
                ["2021-01-04", "2021-01-05", "2021-01-04", "2021-01-05", "2021-01-04", "2021-01-05"]
            ),
            "symbol": ["AAA", "AAA", "BBB", "BBB", "CCC", "CCC"],
            "close": [100.0, 110.0, 100.0, 100.0, 100.0, 90.0],
        }
    )


def test_universe_sector_share_sums_to_one() -> None:
    share = _universe_sector_share(SECTOR_MAP)

    assert share["Tech"] == pytest.approx(2 / 3)
    assert share["Health"] == pytest.approx(1 / 3)
    assert share.sum() == pytest.approx(1.0)


def test_sector_exposure_reports_active_tilt() -> None:
    holdings = _prepare_holdings(_sample_active_weights(), _sample_prices(), SECTOR_MAP)

    exposure = build_sector_exposure(holdings, SECTOR_MAP)
    full = exposure[exposure["period"] == "full_sample"].set_index("sector")

    # 每天科技 2 只各 1/3，合计 2/3；医药 1 只 1/3。等权基准也是 2/3 与 1/3，
    # 所以在这个刻意平衡的样本里主动偏离应为 0，验证暴露与基准口径一致。
    assert full.loc["Tech", "average_weight"] == pytest.approx(2 / 3)
    assert full.loc["Health", "average_weight"] == pytest.approx(1 / 3)
    assert full.loc["Tech", "active_tilt"] == pytest.approx(0.0)


def test_symbol_concentration_effective_holdings_matches_equal_weight() -> None:
    holdings = _prepare_holdings(_sample_active_weights(), _sample_prices(), SECTOR_MAP)

    concentration = build_symbol_concentration(holdings)
    full = concentration[concentration["period"] == "full_sample"].iloc[0]

    # 等权 3 只 -> 每日 HHI = 3 * (1/3)^2 = 1/3 -> 有效持仓数 = 3。
    assert full["average_holdings"] == pytest.approx(3.0)
    assert full["effective_holdings"] == pytest.approx(3.0)
    assert 0.0 <= full["top1_return_contribution_share"] <= 1.0


def test_sector_attribution_contribution_signs() -> None:
    holdings = _prepare_holdings(_sample_active_weights(), _sample_prices(), SECTOR_MAP)

    attribution = build_sector_attribution(holdings)
    full = attribution[attribution["period"] == "full_sample"].set_index("sector")

    # AAA 在 01-05 涨 10%，其余科技股不变 -> 科技贡献为正；
    # CCC 在 01-05 跌 10% -> 医药贡献为负。第一天没有前收，收益按 0 处理。
    assert full.loc["Tech", "gross_return_contribution"] > 0
    assert full.loc["Health", "gross_return_contribution"] < 0


def test_missing_weight_column_raises() -> None:
    bad = pd.DataFrame({"trade_date": pd.to_datetime(["2021-01-04"]), "symbol": ["AAA"]})

    with pytest.raises(ValueError, match="weight"):
        _prepare_holdings(bad, _sample_prices(), SECTOR_MAP)
