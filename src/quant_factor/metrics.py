"""Portfolio performance metrics and reports."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from quant_factor.config import load_config


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

    # 报告 CSV 和图表都属于运行产物，会被 .gitignore 忽略。
    summary.to_csv(reports_dir / "performance_summary.csv", index=False)
    drawdowns.to_csv(reports_dir / "drawdown.csv", index=False)
    plot_nav_and_drawdown(backtest, figures_dir)
    return {"summary": summary, "drawdowns": drawdowns}


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
