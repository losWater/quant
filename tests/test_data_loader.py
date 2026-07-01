import pandas as pd
import pytest

from quant_factor.data_loader import (
    build_price_dataset,
    clean_price_data,
    load_or_fetch_price_history,
)


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


def test_clean_price_data_requires_core_columns() -> None:
    with pytest.raises(ValueError, match="missing required columns"):
        clean_price_data(pd.DataFrame({"trade_date": ["2023-01-03"]}))


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
            "provider": "yfinance",
            "start_date": "2023-01-01",
            "end_date": "2023-01-02",
            "adjusted_price": "auto",
            "request_retries": 2,
            "request_sleep_seconds": 0,
        }
    }
    calls = {"count": 0}
    price_data = pd.DataFrame(
        {
            "trade_date": ["2023-01-01"],
            "symbol": ["AAPL"],
            "open": [10.0],
            "close": [10.1],
            "high": [10.2],
            "low": [9.9],
            "volume": [1000],
            "amount": [10000],
            "market": ["us_equity"],
            "source": ["test"],
        }
    )

    def fake_fetch(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("temporary network error")
        return price_data

    monkeypatch.setattr("quant_factor.data_loader._fetch_price_history", fake_fetch)

    result = load_or_fetch_price_history("AAPL", config)

    assert calls["count"] == 2
    assert result.loc[0, "symbol"] == "AAPL"
