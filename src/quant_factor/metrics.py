"""Portfolio performance metrics and reports."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from quant_factor.backtest import calculate_daily_returns
from quant_factor.config import load_config
from quant_factor.data_loader import load_or_fetch_price_history
from quant_factor.data_sources.schema import normalize_symbol


# 绩效指标函数保持独立，便于单元测试，也便于后续复用到不同策略。
def annualized_return(returns: pd.Series, periods_per_year: int = 252) -> float:
    """Calculate annualized return from periodic returns."""
    returns = returns.dropna()
    if returns.empty:
        return float("nan")
    total_return = float((1 + returns).prod())
    years = len(returns) / periods_per_year
    return total_return ** (1 / years) - 1


def annualized_volatility(returns: pd.Series, periods_per_year: int = 252) -> float:
    """Calculate annualized volatility from periodic returns."""
    returns = returns.dropna()
    if returns.empty:
        return float("nan")
    return float(returns.std(ddof=1) * np.sqrt(periods_per_year))


def drawdown_series(nav: pd.Series) -> pd.Series:
    """Calculate drawdown series from a net asset value curve."""
    nav = nav.dropna()
    if nav.empty:
        return pd.Series(dtype="float64")
    return nav / nav.cummax() - 1


def max_drawdown(nav: pd.Series) -> float:
    """Calculate maximum drawdown from a net asset value series."""
    drawdown = drawdown_series(nav)
    if drawdown.empty:
        return float("nan")
    return float(drawdown.min())


def sharpe_ratio(
    returns: pd.Series,
    risk_free_rate: float = 0.0,
    periods_per_year: int = 252,
) -> float:
    """Calculate annualized Sharpe ratio."""
    excess = returns.dropna() - risk_free_rate / periods_per_year
    volatility = excess.std(ddof=1)
    if volatility == 0 or np.isnan(volatility):
        return float("nan")
    return float(excess.mean() / volatility * np.sqrt(periods_per_year))


def calmar_ratio(returns: pd.Series, nav: pd.Series, periods_per_year: int = 252) -> float:
    """Calculate Calmar ratio as annualized return divided by absolute max drawdown."""
    ann_return = annualized_return(returns, periods_per_year)
    max_dd = abs(max_drawdown(nav))
    if max_dd == 0 or np.isnan(max_dd):
        return float("nan")
    return ann_return / max_dd


def summarize_performance(
    backtest: pd.DataFrame,
    *,
    periods_per_year: int = 252,
    risk_free_rate: float = 0.0,
) -> pd.DataFrame:
    """Build a one-row performance summary from a backtest result table."""
    required = {"net_return", "nav", "turnover", "cost"}
    missing = required - set(backtest.columns)
    if missing:
        raise ValueError(f"Backtest data is missing required columns: {sorted(missing)}")

    returns = pd.to_numeric(backtest["net_return"], errors="coerce")
    nav = pd.to_numeric(backtest["nav"], errors="coerce")
    turnover = pd.to_numeric(backtest["turnover"], errors="coerce")
    cost = pd.to_numeric(backtest["cost"], errors="coerce")

    summary = {
        "total_return": nav.iloc[-1] - 1 if not nav.dropna().empty else float("nan"),
        "annualized_return": annualized_return(returns, periods_per_year),
        "annualized_volatility": annualized_volatility(returns, periods_per_year),
        "sharpe_ratio": sharpe_ratio(returns, risk_free_rate, periods_per_year),
        "max_drawdown": max_drawdown(nav),
        "calmar_ratio": calmar_ratio(returns, nav, periods_per_year),
        "average_turnover": turnover.mean(skipna=True),
        "total_cost": cost.sum(skipna=True),
        "observations": int(returns.dropna().shape[0]),
    }
    return pd.DataFrame([summary])


def build_benchmark_nav(
    price_history: pd.DataFrame,
    trading_dates: pd.Series | pd.DatetimeIndex,
    *,
    benchmark_symbol: str,
) -> pd.DataFrame:
    """Build a benchmark NAV curve aligned to strategy trading dates."""
    required = {"trade_date", "symbol", "close"}
    missing = required - set(price_history.columns)
    if missing:
        raise ValueError(f"Benchmark data is missing required columns: {sorted(missing)}")

    # 基准收益和策略使用同一批交易日，避免两个曲线因为日期不同而不可比。
    symbol = normalize_symbol(benchmark_symbol)
    dates = pd.DatetimeIndex(pd.to_datetime(trading_dates).dropna().sort_values().unique())
    benchmark = price_history.loc[:, ["trade_date", "symbol", "close"]].copy()
    benchmark["trade_date"] = pd.to_datetime(benchmark["trade_date"], errors="coerce")
    benchmark["symbol"] = benchmark["symbol"].map(normalize_symbol)
    benchmark["close"] = pd.to_numeric(benchmark["close"], errors="coerce")
    benchmark = benchmark[benchmark["symbol"] == symbol]
    benchmark = benchmark.dropna(subset=["trade_date", "close"]).sort_values("trade_date")
    if benchmark.empty:
        raise ValueError(f"No benchmark price data found for {symbol}")

    returns = benchmark.set_index("trade_date")["close"].pct_change().reindex(dates).fillna(0)
    nav = (1 + returns).cumprod()
    return pd.DataFrame(
        {
            "trade_date": dates,
            "benchmark": symbol,
            "benchmark_return": returns.to_numpy(),
            "benchmark_nav": nav.to_numpy(),
        }
    )


def build_equal_weight_universe_nav(
    prices: pd.DataFrame,
    trading_dates: pd.Series | pd.DatetimeIndex,
) -> pd.DataFrame:
    """Build a buy-and-hold equal-weight universe NAV curve."""
    required = {"trade_date", "symbol", "close"}
    missing = required - set(prices.columns)
    if missing:
        raise ValueError(f"Price data is missing required columns: {sorted(missing)}")

    # 等权买入并持有：第一天每只股票投入相同资金，之后不再每日再平衡。
    dates = pd.DatetimeIndex(pd.to_datetime(trading_dates).dropna().sort_values().unique())
    data = prices.loc[:, ["trade_date", "symbol", "close"]].copy()
    data["trade_date"] = pd.to_datetime(data["trade_date"], errors="coerce")
    data["symbol"] = data["symbol"].map(normalize_symbol)
    data["close"] = pd.to_numeric(data["close"], errors="coerce")
    data = data.dropna(subset=["trade_date", "symbol", "close"])
    close_matrix = (
        data.pivot(index="trade_date", columns="symbol", values="close")
        .sort_index()
        .reindex(dates)
        .ffill()
        .dropna(axis=1, how="all")
    )
    if close_matrix.empty:
        raise ValueError("No valid universe price data found for equal-weight benchmark")
    base_prices = close_matrix.apply(lambda column: column.dropna().iloc[0])
    symbol_nav = close_matrix.divide(base_prices, axis=1)
    nav = symbol_nav.mean(axis=1).fillna(1.0)
    returns = nav.pct_change().fillna(0)
    return pd.DataFrame(
        {
            "trade_date": dates,
            "benchmark": "equal_weight_universe",
            "benchmark_return": returns.to_numpy(),
            "benchmark_nav": nav.to_numpy(),
        }
    )


def build_holding_summary(active_weights: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    """Summarize strategy holdings and approximate return contribution by symbol."""
    required_weights = {"trade_date", "symbol", "weight"}
    missing_weights = required_weights - set(active_weights.columns)
    if missing_weights:
        raise ValueError(f"Active weights are missing required columns: {sorted(missing_weights)}")

    # 持仓贡献用 weight * close-to-close return 近似，帮助定位收益是否集中在少数股票。
    weights = active_weights.loc[:, ["trade_date", "symbol", "weight"]].copy()
    weights["trade_date"] = pd.to_datetime(weights["trade_date"], errors="coerce")
    weights["symbol"] = weights["symbol"].map(normalize_symbol)
    weights["weight"] = pd.to_numeric(weights["weight"], errors="coerce")
    weights = weights.dropna(subset=["trade_date", "symbol", "weight"])
    daily_returns = calculate_daily_returns(prices)
    merged = weights.merge(daily_returns, on=["trade_date", "symbol"], how="left")
    merged["daily_return"] = pd.to_numeric(merged["daily_return"], errors="coerce").fillna(0)
    merged["gross_return_contribution"] = merged["weight"] * merged["daily_return"]
    total_trading_days = prices["trade_date"].dropna().nunique()

    summary = (
        merged.groupby("symbol", as_index=False)
        .agg(
            holding_days=("trade_date", "nunique"),
            average_weight=("weight", "mean"),
            max_weight=("weight", "max"),
            gross_return_contribution=("gross_return_contribution", "sum"),
        )
        .sort_values("gross_return_contribution", ascending=False)
        .reset_index(drop=True)
    )
    summary["holding_day_ratio"] = summary["holding_days"] / total_trading_days
    total_contribution = summary["gross_return_contribution"].abs().sum()
    summary["absolute_contribution_share"] = (
        summary["gross_return_contribution"].abs() / total_contribution
        if total_contribution
        else 0.0
    )
    return summary.loc[
        :,
        [
            "symbol",
            "holding_days",
            "holding_day_ratio",
            "average_weight",
            "max_weight",
            "gross_return_contribution",
            "absolute_contribution_share",
        ],
    ]


def build_performance_comparison(
    backtest: pd.DataFrame,
    benchmark_nav: pd.DataFrame,
    *,
    benchmark_symbol: str,
) -> pd.DataFrame:
    """Build a strategy-versus-benchmark performance comparison table."""
    strategy = summarize_performance(backtest).assign(series="strategy")
    benchmark_rows = []
    benchmark_data = benchmark_nav.copy()
    if "benchmark" not in benchmark_data:
        benchmark_data["benchmark"] = normalize_symbol(benchmark_symbol)
    for name, group in benchmark_data.groupby("benchmark", sort=False):
        benchmark_backtest = pd.DataFrame(
            {
                "net_return": group["benchmark_return"],
                "nav": group["benchmark_nav"],
                "turnover": 0.0,
                "cost": 0.0,
            }
        )
        benchmark_rows.append(summarize_performance(benchmark_backtest).assign(series=name))
    comparison = pd.concat([strategy, *benchmark_rows], ignore_index=True)
    columns = ["series", *[column for column in comparison.columns if column != "series"]]
    return comparison.loc[:, columns]


def build_drawdown_table(backtest: pd.DataFrame) -> pd.DataFrame:
    """Build a date-aligned drawdown report table."""
    required = {"trade_date", "nav"}
    missing = required - set(backtest.columns)
    if missing:
        raise ValueError(f"Backtest data is missing required columns: {sorted(missing)}")

    result = backtest.loc[:, ["trade_date", "nav"]].copy()
    result["trade_date"] = pd.to_datetime(result["trade_date"], errors="coerce")
    result["nav"] = pd.to_numeric(result["nav"], errors="coerce")
    result["drawdown"] = drawdown_series(result["nav"])
    return result


def plot_nav_and_drawdown(backtest: pd.DataFrame, figures_dir: Path) -> None:
    """Plot NAV and drawdown charts for quick inspection."""
    figures_dir.mkdir(parents=True, exist_ok=True)
    data = build_drawdown_table(backtest)

    # 净值图用于观察长期走势，回撤图用于观察最大痛苦区间。
    fig, axis = plt.subplots(figsize=(10, 4))
    axis.plot(data["trade_date"], data["nav"], label="strategy NAV")
    axis.set_title("Backtest NAV")
    axis.set_ylabel("NAV")
    axis.grid(alpha=0.3)
    axis.legend(loc="best")
    fig.tight_layout()
    fig.savefig(figures_dir / "backtest_nav.png", dpi=150)
    plt.close(fig)

    fig, axis = plt.subplots(figsize=(10, 4))
    axis.fill_between(data["trade_date"], data["drawdown"], 0, alpha=0.35)
    axis.set_title("Backtest Drawdown")
    axis.set_ylabel("Drawdown")
    axis.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(figures_dir / "backtest_drawdown.png", dpi=150)
    plt.close(fig)


def plot_benchmark_comparison(
    backtest: pd.DataFrame,
    benchmark_nav: pd.DataFrame,
    figures_dir: Path,
) -> None:
    """Plot strategy NAV against the configured benchmark."""
    figures_dir.mkdir(parents=True, exist_ok=True)
    data = backtest.loc[:, ["trade_date", "nav"]].copy()
    data["trade_date"] = pd.to_datetime(data["trade_date"], errors="coerce")
    benchmark = benchmark_nav.copy()
    benchmark["trade_date"] = pd.to_datetime(benchmark["trade_date"], errors="coerce")

    # 对比图用于回答：策略有没有跑赢一个简单、可投资的市场基准。
    fig, axis = plt.subplots(figsize=(10, 4))
    axis.plot(data["trade_date"], data["nav"], label="strategy NAV")
    for benchmark_name, group in benchmark.groupby("benchmark", sort=False):
        group = group.sort_values("trade_date")
        axis.plot(group["trade_date"], group["benchmark_nav"], label=f"{benchmark_name} NAV")
    axis.set_title("Strategy vs Benchmark NAV")
    axis.set_ylabel("NAV")
    axis.grid(alpha=0.3)
    axis.legend(loc="best")
    fig.tight_layout()
    fig.savefig(figures_dir / "benchmark_comparison_nav.png", dpi=150)
    plt.close(fig)


def build_performance_report(config: dict[str, Any]) -> dict[str, pd.DataFrame]:
    """Load backtest output, calculate metrics, and persist performance reports."""
    reports_dir = Path(config["output"]["reports_dir"])
    figures_dir = Path(config["output"]["figures_dir"])
    backtest_path = reports_dir / "backtest_nav.csv"
    if not backtest_path.exists():
        raise FileNotFoundError(f"Missing backtest output: {backtest_path}")

    backtest = pd.read_csv(backtest_path, parse_dates=["trade_date"])
    summary = summarize_performance(backtest)
    drawdowns = build_drawdown_table(backtest)
    prices = pd.read_csv(
        Path(config["data"]["processed_dir"]) / "daily_prices.csv",
        dtype={"symbol": "string"},
        parse_dates=["trade_date"],
    )

    # 报告 CSV 和图表都属于运行产物，会被 .gitignore 忽略。
    summary.to_csv(reports_dir / "performance_summary.csv", index=False)
    drawdowns.to_csv(reports_dir / "drawdown.csv", index=False)
    plot_nav_and_drawdown(backtest, figures_dir)

    outputs = {"summary": summary, "drawdowns": drawdowns}
    benchmark_frames = [
        build_equal_weight_universe_nav(prices, backtest["trade_date"]),
    ]
    benchmark_symbol = config.get("backtest", {}).get("benchmark")
    if benchmark_symbol:
        benchmark_prices = load_or_fetch_price_history(benchmark_symbol, config)
        benchmark_frames.insert(
            0,
            build_benchmark_nav(
                benchmark_prices,
                backtest["trade_date"],
                benchmark_symbol=benchmark_symbol,
            ),
        )

    benchmark_nav = pd.concat(benchmark_frames, ignore_index=True)
    comparison = build_performance_comparison(
        backtest,
        benchmark_nav,
        benchmark_symbol=benchmark_symbol or "benchmark",
    )
    benchmark_nav.to_csv(reports_dir / "benchmark_nav.csv", index=False)
    comparison.to_csv(reports_dir / "performance_comparison.csv", index=False)
    plot_benchmark_comparison(backtest, benchmark_nav, figures_dir)
    outputs["benchmark_nav"] = benchmark_nav
    outputs["comparison"] = comparison

    active_weights_path = reports_dir / "backtest_active_weights.csv"
    if active_weights_path.exists():
        active_weights = pd.read_csv(
            active_weights_path,
            dtype={"symbol": "string"},
            parse_dates=["trade_date"],
        )
        holding_summary = build_holding_summary(active_weights, prices)
        holding_summary.to_csv(reports_dir / "holding_summary.csv", index=False)
        outputs["holding_summary"] = holding_summary

    return outputs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build performance reports from backtest output.")
    parser.add_argument("--config", default="config.yaml", help="Path to project config YAML.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    outputs = build_performance_report(config)
    print("Saved performance reports to results/reports")
    print(outputs["summary"].to_string(index=False))


if __name__ == "__main__":
    main()
