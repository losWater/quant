"""Data loading, caching, and cleaning entry points."""

from __future__ import annotations

import argparse
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pandas as pd

from quant_factor.config import load_config
from quant_factor.data_sources.akshare_source import fetch_csi300_universe, fetch_stock_history
from quant_factor.data_sources.schema import (
    NUMERIC_PRICE_COLUMNS,
    build_manual_universe,
    normalize_symbol,
    standardize_price_frame,
    standardize_universe_frame,
)
from quant_factor.data_sources.yfinance_source import fetch_yfinance_history


def clean_price_data(data: pd.DataFrame, *, exclude_suspended: bool = True) -> pd.DataFrame:
    """Clean standardized daily price data.

    The current pass covers the first production rules: stable types, duplicate
    removal, chronological ordering, and optional suspended-day filtering.
    """
    # 清洗层只处理通用数据质量问题，不在这里做任何策略判断。
    cleaned = data.copy()
    required = {"trade_date", "symbol", "open", "close", "high", "low", "volume", "amount"}
    missing = required - set(cleaned.columns)
    if missing:
        raise ValueError(f"Cleaned price data is missing required columns: {sorted(missing)}")

    cleaned["trade_date"] = pd.to_datetime(cleaned["trade_date"], errors="coerce")
    cleaned["symbol"] = cleaned["symbol"].map(normalize_symbol)
    for column in NUMERIC_PRICE_COLUMNS:
        if column in cleaned:
            cleaned[column] = pd.to_numeric(cleaned[column], errors="coerce")

    cleaned = cleaned.dropna(subset=["trade_date", "symbol", "open", "close", "high", "low"])
    if exclude_suspended and "volume" in cleaned:
        cleaned = cleaned[cleaned["volume"] > 0]

    return (
        cleaned.drop_duplicates(subset=["symbol", "trade_date"], keep="last")
        .sort_values(["symbol", "trade_date"])
        .reset_index(drop=True)
    )


def _write_csv(data: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data.to_csv(path, index=False)


def _read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype={"symbol": "string"})


def _standardize_cached_price_data(data: pd.DataFrame, data_config: dict[str, Any]) -> pd.DataFrame:
    """Normalize cached CSV data back to the shared price schema."""
    market = (
        data["market"].iloc[0]
        if "market" in data and not data.empty
        else data_config["market"]
    )
    source = (
        data["source"].iloc[0]
        if "source" in data and not data.empty
        else data_config["provider"]
    )
    return standardize_price_frame(data, market=market, source=source)


def load_or_fetch_universe(config: dict[str, Any], *, refresh: bool = False) -> pd.DataFrame:
    """Load the cached universe or fetch/build it from the configured source."""
    # 股票池写入 raw 目录。默认优先读缓存，避免每次运行都请求网络。
    raw_dir = Path(config["data"]["raw_dir"])
    provider = config["data"].get("provider", "akshare")
    universe_name = config["data"].get("universe", "csi300")
    cache_path = raw_dir / f"universe_{universe_name}.csv"

    if cache_path.exists() and not refresh:
        return standardize_universe_frame(_read_csv(cache_path))

    if provider == "yfinance":
        universe = build_manual_universe(config["data"].get("symbols", []))
    else:
        index_code = "000300" if universe_name == "csi300" else universe_name
        universe = fetch_csi300_universe(index_code=index_code)
    _write_csv(universe, cache_path)
    return universe


def _fetch_price_history(
    symbol: str,
    data_config: dict[str, Any],
    timeout: float | None,
) -> pd.DataFrame:
    """Fetch one symbol from the configured provider."""
    provider = data_config.get("provider")
    if provider == "yfinance":
        return fetch_yfinance_history(
            symbol,
            start_date=data_config["start_date"],
            end_date=data_config["end_date"],
            adjusted_price=data_config.get("adjusted_price", "auto"),
            timeout=timeout,
        )
    return fetch_stock_history(
        symbol,
        start_date=data_config["start_date"],
        end_date=data_config["end_date"],
        adjust=data_config.get("adjusted_price", ""),
        timeout=timeout,
    )


def load_or_fetch_price_history(
    symbol: str,
    config: dict[str, Any],
    *,
    refresh: bool = False,
) -> pd.DataFrame:
    """Load one stock's cached price history or fetch it from the configured provider."""
    # 单只股票一个 CSV，后续增量更新或定位脏数据会更容易。
    data_config = config["data"]
    raw_dir = Path(data_config["raw_dir"])
    price_dir = raw_dir / "prices"
    symbol = normalize_symbol(symbol)
    cache_path = price_dir / f"{symbol}.csv"

    if cache_path.exists() and not refresh:
        return _standardize_cached_price_data(_read_csv(cache_path), data_config)

    retries = int(data_config.get("request_retries", 3))
    sleep_seconds = float(data_config.get("request_sleep_seconds", 0.5))
    timeout = data_config.get("request_timeout")
    timeout = float(timeout) if timeout is not None else None

    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            data = _fetch_price_history(symbol, data_config, timeout)
            _write_csv(data, cache_path)
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)
            return data
        except Exception as exc:
            last_error = exc
            if attempt < retries:
                wait_seconds = sleep_seconds * attempt
                print(
                    f"[data] retry {symbol} attempt {attempt + 1}/{retries} after {exc}",
                    flush=True,
                )
                if wait_seconds > 0:
                    time.sleep(wait_seconds)

    assert last_error is not None
    raise last_error


def build_price_dataset(
    config: dict[str, Any],
    *,
    symbols: Iterable[str] | None = None,
    limit: int | None = None,
    refresh: bool = False,
    continue_on_error: bool = True,
) -> pd.DataFrame:
    """Build and persist the cleaned daily price dataset."""
    # 主流程：股票池 -> 单票行情 -> 合并清洗 -> 输出 processed 数据集。
    universe = load_or_fetch_universe(config, refresh=refresh)
    selected_symbols = [normalize_symbol(symbol) for symbol in (symbols or universe["symbol"])]
    if limit is not None:
        selected_symbols = selected_symbols[:limit]

    frames = []
    failures = []
    total = len(selected_symbols)
    for index, symbol in enumerate(selected_symbols, start=1):
        print(f"[data] {index}/{total} loading {symbol}", flush=True)
        try:
            frames.append(load_or_fetch_price_history(symbol, config, refresh=refresh))
        except Exception as exc:
            failures.append({"symbol": symbol, "error": str(exc)})
            print(f"[data] failed {symbol}: {exc}", flush=True)
            if not continue_on_error:
                raise

    processed_dir = Path(config["data"]["processed_dir"])
    if failures:
        _write_csv(pd.DataFrame(failures), processed_dir / "download_failures.csv")
    elif (processed_dir / "download_failures.csv").exists():
        (processed_dir / "download_failures.csv").unlink()

    if not frames:
        raise RuntimeError("No price data was downloaded or loaded.")

    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    cleaned = clean_price_data(
        combined,
        exclude_suspended=config.get("filters", {}).get("exclude_suspended", True),
    )

    processed_path = processed_dir / "daily_prices.csv"
    _write_csv(cleaned, processed_path)
    return cleaned


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download and clean daily price data.")
    parser.add_argument("--config", default="config.yaml", help="Path to project config YAML.")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of symbols for a smoke run.",
    )
    parser.add_argument(
        "--symbols",
        nargs="*",
        help="Explicit symbols to download, e.g. AAPL MSFT NVDA.",
    )
    parser.add_argument("--refresh", action="store_true", help="Ignore local raw-data cache.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    data = build_price_dataset(
        config,
        symbols=args.symbols,
        limit=args.limit,
        refresh=args.refresh,
    )
    output_path = Path(config["data"]["processed_dir"]) / "daily_prices.csv"
    symbol_count = data["symbol"].nunique() if not data.empty else 0
    print(f"Saved {len(data)} rows for {symbol_count} symbols to {output_path}")


if __name__ == "__main__":
    main()
