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
    # 清洗层只处理“数据质量”问题，不做任何“策略判断”。
    # 这点很重要：比如成交量为 0 可以视为不可交易/停牌数据，应该清洗；
    # 但“涨太多要不要剔除”属于策略假设，不能偷偷混在数据清洗里。
    cleaned = data.copy()
    required = {"trade_date", "symbol", "open", "close", "high", "low", "volume", "amount"}
    missing = required - set(cleaned.columns)
    if missing:
        raise ValueError(f"Cleaned price data is missing required columns: {sorted(missing)}")

    cleaned["trade_date"] = pd.to_datetime(cleaned["trade_date"], errors="coerce")
    cleaned["symbol"] = cleaned["symbol"].map(normalize_symbol)
    for column in NUMERIC_PRICE_COLUMNS:
        if column in cleaned:
            # 外部接口经常把数字以字符串形式返回；统一转数值后，
            # 后面的 rolling、pct_change、回测收益计算才不会出现隐式类型问题。
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
    # 缓存文件可能来自旧版本代码，旧缓存不一定有 market/source。
    # 这里做兼容，是为了让工程能平滑迭代，不因为增加 schema 字段就要求手工删缓存。
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
    # 股票池是回测假设的一部分，应该像代码一样被版本管理。
    # 如果配置了 universe_file，就直接读取本地 CSV，避免股票池藏在 raw 缓存里不可见；
    # 如果没有配置文件，才走旧的“手动 symbols / 外部指数接口”逻辑。
    data_config = config["data"]
    universe_file = data_config.get("universe_file")
    if universe_file:
        return standardize_universe_frame(_read_csv(Path(universe_file)))

    # 外部接口股票池写入 raw 目录。默认优先读缓存，避免每次运行都请求网络。
    # 量化研究里“能复现”比“每次取最新”更重要；refresh=True 时才主动刷新。
    raw_dir = Path(data_config["raw_dir"])
    provider = data_config.get("provider", "akshare")
    universe_name = data_config.get("universe", "csi300")
    cache_path = raw_dir / f"universe_{universe_name}.csv"

    if cache_path.exists() and not refresh:
        return standardize_universe_frame(_read_csv(cache_path))

    if provider == "yfinance":
        # 当前美股路线使用手动股票池。以后如果接 S&P 500 历史成分股，
        # 可以新增一个数据源适配器，而不用改后面的因子和回测。
        universe = build_manual_universe(data_config.get("symbols", []))
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
    # 这个函数是数据源分发点。调用方只说“我要某只股票的历史行情”，
    # 至于走 yfinance 还是 AkShare，由 config 控制。
    # 这样后续支持港股/澳股时，新增分支即可，不必重写主流程。
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
    # 如果某一只股票下载坏了，只需要看它自己的 raw/prices/{symbol}.csv。
    data_config = config["data"]
    raw_dir = Path(data_config["raw_dir"])
    price_dir = raw_dir / "prices"
    symbol = normalize_symbol(symbol)
    cache_path = price_dir / f"{symbol}.csv"

    if cache_path.exists() and not refresh:
        # 默认读缓存，能减少外部接口不稳定带来的噪音。
        # 这也让测试和复盘更稳定：同一份 raw 数据可以反复生成 processed 数据。
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
                # 网络接口失败是常态，不应该因为一次超时就中断整条研究流程。
                # 这里做逐次退避等待，给数据源一点恢复时间。
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
    # 这里故意把“单票失败”记录下来但默认不中断，因为真实数据源经常有个别票断连。
    # 研究阶段先保留可用样本继续往后跑，再在 download_failures.csv 里审计失败股票。
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
