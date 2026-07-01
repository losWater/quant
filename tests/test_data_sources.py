import pandas as pd

from quant_factor.data_sources.akshare_source import (
    normalize_date,
    standardize_akshare_price_data,
    standardize_tencent_price_data,
    standardize_universe,
    to_tencent_symbol,
)
from quant_factor.data_sources.schema import build_manual_universe, normalize_symbol
from quant_factor.data_sources.yfinance_source import standardize_yfinance_price_data


def test_normalize_date_for_akshare() -> None:
    assert normalize_date("2023-01-05") == "20230105"


def test_normalize_symbol_for_cross_market_usage() -> None:
    assert normalize_symbol("1") == "000001"
    assert normalize_symbol("600519.SH") == "600519"
    assert normalize_symbol("aapl") == "AAPL"


def test_to_tencent_symbol_adds_market_prefix() -> None:
    assert to_tencent_symbol("000001") == "sz000001"
    assert to_tencent_symbol("600519") == "sh600519"


def test_standardize_universe_from_csindex_columns() -> None:
    raw = pd.DataFrame(
        {
            "日期": ["2026-06-26"],
            "指数代码": ["000300"],
            "指数名称": ["沪深300"],
            "成分券代码": ["1"],
            "成分券名称": ["平安银行"],
            "交易所": ["深圳证券交易所"],
        }
    )

    result = standardize_universe(raw)

    assert result.loc[0, "symbol"] == "000001"
    assert result.loc[0, "name"] == "平安银行"
    assert result.loc[0, "effective_date"] == pd.Timestamp("2026-06-26")


def test_standardize_akshare_price_data() -> None:
    raw = pd.DataFrame(
        {
            "日期": ["2023-01-03"],
            "股票代码": ["1"],
            "开盘": ["10.0"],
            "收盘": ["10.5"],
            "最高": ["10.8"],
            "最低": ["9.9"],
            "成交量": ["1000"],
            "成交额": ["10000"],
            "换手率": ["1.2"],
        }
    )

    result = standardize_akshare_price_data(raw)

    assert result.loc[0, "symbol"] == "000001"
    assert result.loc[0, "close"] == 10.5
    assert result.loc[0, "turnover_rate"] == 1.2
    assert result.loc[0, "market"] == "cn_a_share"


def test_standardize_tencent_price_data() -> None:
    raw = pd.DataFrame(
        {
            "date": ["2023-01-03"],
            "open": ["10.0"],
            "close": ["10.5"],
            "high": ["10.8"],
            "low": ["9.9"],
            "amount": ["1000"],
        }
    )

    result = standardize_tencent_price_data(raw, "1")

    assert result.loc[0, "symbol"] == "000001"
    assert result.loc[0, "volume"] == 1000
    assert pd.isna(result.loc[0, "amount"])
    assert result.loc[0, "source"] == "akshare_tx"


def test_standardize_yfinance_price_data() -> None:
    raw = pd.DataFrame(
        {
            "Date": pd.to_datetime(["2023-01-03"]),
            "Open": [100.0],
            "Close": [101.0],
            "High": [102.0],
            "Low": [99.0],
            "Volume": [1000000],
        }
    ).set_index("Date")

    result = standardize_yfinance_price_data(raw, "aapl")

    assert result.loc[0, "symbol"] == "AAPL"
    assert result.loc[0, "close"] == 101.0
    assert result.loc[0, "volume"] == 1000000
    assert result.loc[0, "market"] == "us_equity"


def test_build_manual_universe() -> None:
    result = build_manual_universe(["aapl", "MSFT"])

    assert result["symbol"].tolist() == ["AAPL", "MSFT"]
    assert result["exchange"].tolist() == ["manual", "manual"]
