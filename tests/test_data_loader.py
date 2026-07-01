import pandas as pd
import pytest

from quant_factor.data_loader import (
    build_price_dataset,
    clean_price_data,
    load_or_fetch_price_history,
    normalize_date,
    normalize_symbol,
    standardize_price_data,
    standardize_tencent_price_data,
    standardize_universe,
    to_tencent_symbol,
)


def test_normalize_date_for_akshare() -> None:
    assert normalize_date("2023-01-05") == "20230105"


def test_normalize_symbol_keeps_six_digits() -> None:
    assert normalize_symbol("1") == "000001"
    assert normalize_symbol("600519.SH") == "600519"


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


def test_standardize_price_data_from_akshare_columns() -> None:
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

    result = standardize_price_data(raw)

    assert result.loc[0, "symbol"] == "000001"
    assert result.loc[0, "close"] == 10.5
    assert result.loc[0, "turnover_rate"] == 1.2


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


def test_clean_price_data_removes_suspended_and_duplicate_rows() -> None:
    data = pd.DataFrame(
        {
            "trade_date": ["2023-01-04", "2023-01-03", "2023-01-03"],
            "symbol": ["000001", "1", "000001"],
            "open": [11.0, 10.0, 10.0],
            "close": [11.2, 10.2, 10.3],
            "high": [11.3, 10.4, 10.5],
            "low": [10.9, 9.9, 9.8],
            "volume": [0, 1000, 1000],
            "amount": [0, 10000, 10000],
        }
    )

    result = clean_price_data(data)

    assert len(result) == 1
    assert result.loc[0, "symbol"] == "000001"
    assert result.loc[0, "close"] == 10.3


def test_standardize_price_data_requires_core_columns() -> None:
    with pytest.raises(ValueError, match="missing required columns"):
        standardize_price_data(pd.DataFrame({"日期": ["2023-01-03"]}))


def test_build_price_dataset_records_download_failures(tmp_path, monkeypatch) -> None:
    config = {
        "data": {
            "raw_dir": str(tmp_path / "raw"),
            "processed_dir": str(tmp_path / "processed"),
        },
        "filters": {"exclude_suspended": True},
    }
    universe = pd.DataFrame({"symbol": ["000001", "000002"], "name": ["A", "B"]})
    price_data = pd.DataFrame(
        {
            "trade_date": ["2023-01-01"],
            "symbol": ["000001"],
            "open": [10.0],
            "close": [10.1],
            "high": [10.2],
            "low": [9.9],
            "volume": [1000],
            "amount": [10000],
        }
    )

    monkeypatch.setattr("quant_factor.data_loader.load_or_fetch_universe", lambda *a, **k: universe)

    def fake_load_price(symbol, *args, **kwargs):
        if symbol == "000002":
            raise RuntimeError("network error")
        return price_data

    monkeypatch.setattr("quant_factor.data_loader.load_or_fetch_price_history", fake_load_price)

    result = build_price_dataset(config)

    failures = pd.read_csv(tmp_path / "processed" / "download_failures.csv")
    assert len(result) == 1
    assert failures.loc[0, "symbol"] == 2
    assert failures.loc[0, "error"] == "network error"


def test_load_or_fetch_price_history_retries_download(tmp_path, monkeypatch) -> None:
    config = {
        "data": {
            "raw_dir": str(tmp_path / "raw"),
            "start_date": "2023-01-01",
            "end_date": "2023-01-02",
            "adjusted_price": "hfq",
            "request_retries": 2,
            "request_sleep_seconds": 0,
        }
    }
    calls = {"count": 0}
    price_data = pd.DataFrame(
        {
            "trade_date": ["2023-01-01"],
            "symbol": ["000001"],
            "open": [10.0],
            "close": [10.1],
            "high": [10.2],
            "low": [9.9],
            "volume": [1000],
            "amount": [10000],
        }
    )

    def fake_fetch(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("temporary network error")
        return price_data

    monkeypatch.setattr("quant_factor.data_loader.fetch_stock_history", fake_fetch)

    result = load_or_fetch_price_history("000001", config)

    assert calls["count"] == 2
    assert result.loc[0, "symbol"] == "000001"
