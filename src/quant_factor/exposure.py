"""Stage 14 risk-exposure analysis.

这个模块回答一个比“回测收益多少”更重要的问题：策略的收益到底来自哪里？
- 策略是不是重仓某几个行业（比如科技）？
- 收益是不是集中在少数几只股票上？
- 相对“股票池等权买入并持有”，策略在行业上到底偏离了多少？

它不改变任何策略规则，只对已经跑完的 backtest_active_weights.csv 做拆解。
这样做的原因：在样本外不稳定、股票池有幸存者偏差的情况下，
如果不先搞清楚收益来源，直接上机器学习，很可能只是更复杂的过拟合。
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import pandas as pd

from quant_factor.backtest import calculate_daily_returns
from quant_factor.config import load_config
from quant_factor.data_loader import load_or_fetch_universe
from quant_factor.data_sources.schema import normalize_symbol

UNKNOWN_SECTOR = "Unknown"


def load_sector_map(config: dict[str, Any]) -> pd.Series:
    """Return a symbol -> sector mapping from the configured universe file."""
    # 行业标签放在股票池 CSV 里，而不是硬编码在代码里，原因有两个：
    # 1. 行业分类本身是一种“研究假设”，应该和股票池放在一起、可被审阅。
    # 2. 以后换股票池（比如扩到 S&P 500）时，只要新 CSV 带 sector 列就能直接用。
    universe = load_or_fetch_universe(config)
    if "sector" not in universe.columns:
        # 缺列时不报错，而是整体标成 Unknown。暴露分析属于“辅助解释”，
        # 不应该因为股票池暂时没填行业就阻断整个 pipeline。
        return pd.Series(dtype="object")
    sectors = universe.loc[:, ["symbol", "sector"]].copy()
    sectors["symbol"] = sectors["symbol"].map(normalize_symbol)
    sectors["sector"] = sectors["sector"].fillna(UNKNOWN_SECTOR).replace("", UNKNOWN_SECTOR)
    return sectors.dropna(subset=["symbol"]).set_index("symbol")["sector"]


def prepare_holdings(
    active_weights: pd.DataFrame,
    prices: pd.DataFrame,
    sector_map: pd.Series,
) -> pd.DataFrame:
    """Attach daily return and sector to each held position, plus a year column."""
    # 三个下游报告（行业暴露、集中度、行业归因）都需要同一份“加工好的持仓”：
    # 每一行 = 某天某只股票的权重、当天收益、所属行业。抽成一个函数避免三处重复。
    required = {"trade_date", "symbol", "weight"}
    missing = required - set(active_weights.columns)
    if missing:
        raise ValueError(f"Active weights are missing required columns: {sorted(missing)}")

    holdings = active_weights.loc[:, ["trade_date", "symbol", "weight"]].copy()
    holdings["trade_date"] = pd.to_datetime(holdings["trade_date"], errors="coerce")
    holdings["symbol"] = holdings["symbol"].map(normalize_symbol)
    holdings["weight"] = pd.to_numeric(holdings["weight"], errors="coerce")
    holdings = holdings.dropna(subset=["trade_date", "symbol", "weight"])
    holdings = holdings[holdings["weight"] > 0]

    daily_returns = calculate_daily_returns(prices)
    holdings = holdings.merge(daily_returns, on=["trade_date", "symbol"], how="left")
    holdings["daily_return"] = pd.to_numeric(holdings["daily_return"], errors="coerce").fillna(0)
    # 用当天持仓权重乘当天收益近似该股票对组合的收益贡献，和 build_holding_summary 口径一致。
    holdings["gross_return_contribution"] = holdings["weight"] * holdings["daily_return"]
    holdings["sector"] = holdings["symbol"].map(sector_map).fillna(UNKNOWN_SECTOR)
    holdings["year"] = holdings["trade_date"].dt.year
    return holdings


def _period_frames(holdings: pd.DataFrame) -> list[tuple[str, pd.DataFrame]]:
    """Yield ('full_sample', all) then one frame per calendar year."""
    # 每个报告都按“完整样本 + 逐年”两个粒度看。逐年很关键：
    # 行业偏斜或收益集中往往随年份漂移，只看完整样本会把这些变化平均掉。
    periods: list[tuple[str, pd.DataFrame]] = [("full_sample", holdings)]
    for year, year_data in holdings.groupby("year", sort=True):
        periods.append((str(int(year)), year_data))
    return periods


def build_sector_exposure(
    holdings: pd.DataFrame,
    sector_map: pd.Series,
) -> pd.DataFrame:
    """Average sector weight per period versus the equal-weight universe benchmark."""
    # 这是最核心的一张表：策略在每个行业上到底配了多少，
    # 以及相对“股票池等权买入并持有”超配/低配了多少（active_tilt）。
    # 如果策略大幅超配科技，而这几年科技又恰好强势，那所谓的动量收益，
    # 很可能只是行业 beta，而不是选股 alpha。
    universe_share = _universe_sector_share(sector_map)
    rows = []
    for period_label, period_data in _period_frames(holdings):
        active_days = period_data["trade_date"].nunique()
        if active_days == 0:
            continue
        # 每个行业的权重之和 / 该期活跃交易天数 = 该行业的平均配置权重。
        # 没有持仓的行业在某天贡献 0，但那一天仍计入分母，所以这是“真实平均配置”。
        sector_weight = period_data.groupby("sector")["weight"].sum() / active_days
        for sector, average_weight in sector_weight.items():
            benchmark_weight = float(universe_share.get(sector, 0.0))
            rows.append(
                {
                    "period": period_label,
                    "sector": sector,
                    "average_weight": float(average_weight),
                    "universe_weight": benchmark_weight,
                    "active_tilt": float(average_weight) - benchmark_weight,
                    "active_days": int(active_days),
                }
            )
    result = pd.DataFrame(rows)
    if result.empty:
        return result
    return result.sort_values(
        ["period", "average_weight"], ascending=[True, False]
    ).reset_index(drop=True)


def _universe_sector_share(sector_map: pd.Series) -> pd.Series:
    """Equal-weight share each sector would get if the whole universe were held equally."""
    # 等权股票池基准里，每只股票权重都是 1/N，所以某行业的中性权重 = 行业内股票数 / N。
    # 这个基准之所以重要：交接文档里策略恰好“跑输等权股票池”，
    # 只有和这个基准比，才能看出策略是主动偏离了行业，还是只是复制了股票池。
    if sector_map.empty:
        return pd.Series(dtype="float64")
    counts = sector_map.value_counts()
    return counts / counts.sum()


def build_symbol_concentration(holdings: pd.DataFrame) -> pd.DataFrame:
    """Per-period concentration of holdings and of return contribution."""
    # 集中度回答两个不同的问题：
    # 1. 组合本身是否分散（有效持仓数 = 1 / 平均每日 HHI）。
    # 2. 收益是否集中在少数股票（Top-N 贡献占比）。
    # 等权 20 只股票的组合，有效持仓数应接近 20；但收益贡献可能高度集中在少数几只，
    # 这正是“收益是不是靠运气踩中几只大牛股”的量化检查。
    rows = []
    for period_label, period_data in _period_frames(holdings):
        active_days = period_data["trade_date"].nunique()
        if active_days == 0:
            continue
        # 每日 HHI = 当天各持仓权重平方和；等权 k 只时 HHI=1/k，有效持仓数=1/HHI=k。
        daily_hhi = period_data.groupby("trade_date")["weight"].apply(lambda w: (w**2).sum())
        daily_names = period_data.groupby("trade_date")["symbol"].nunique()
        average_hhi = float(daily_hhi.mean())

        symbol_contribution = (
            period_data.groupby("symbol")["gross_return_contribution"].sum().sort_values(
                ascending=False
            )
        )
        total_abs = symbol_contribution.abs().sum()
        rows.append(
            {
                "period": period_label,
                "active_days": int(active_days),
                "average_holdings": float(daily_names.mean()),
                "average_daily_hhi": average_hhi,
                "effective_holdings": (1.0 / average_hhi) if average_hhi else 0.0,
                "top1_return_contribution_share": _top_share(symbol_contribution, 1, total_abs),
                "top5_return_contribution_share": _top_share(symbol_contribution, 5, total_abs),
                "top10_return_contribution_share": _top_share(symbol_contribution, 10, total_abs),
                "top_contributor": (
                    str(symbol_contribution.index[0]) if not symbol_contribution.empty else ""
                ),
            }
        )
    return pd.DataFrame(rows)


def _top_share(contribution: pd.Series, n: int, total_abs: float) -> float:
    """Share of total absolute contribution held by the top-n most positive contributors."""
    if not total_abs or contribution.empty:
        return 0.0
    return float(contribution.head(n).abs().sum() / total_abs)


def build_sector_attribution(holdings: pd.DataFrame) -> pd.DataFrame:
    """Approximate gross return contribution grouped by sector, per period."""
    # 行业收益归因：把每天每只股票的收益贡献按行业汇总。
    # 它和行业暴露表配合使用——暴露表说“配了多少”，归因表说“赚/亏了多少”。
    # 如果收益几乎全来自一个行业，即便回测总收益好看，策略也谈不上稳健。
    rows = []
    for period_label, period_data in _period_frames(holdings):
        sector_group = period_data.groupby("sector")
        contribution = sector_group["gross_return_contribution"].sum()
        total_abs = contribution.abs().sum()
        holding_days = sector_group["trade_date"].nunique()
        active_days = period_data["trade_date"].nunique()
        average_weight = sector_group["weight"].sum() / active_days if active_days else 0.0
        summary = pd.DataFrame(
            {
                "period": period_label,
                "sector": contribution.index,
                "average_weight": average_weight.reindex(contribution.index).to_numpy(),
                "holding_days": holding_days.reindex(contribution.index).to_numpy(),
                "gross_return_contribution": contribution.to_numpy(),
                "absolute_contribution_share": (
                    (contribution.abs() / total_abs).to_numpy() if total_abs else 0.0
                ),
            }
        )
        rows.append(summary.sort_values("gross_return_contribution", ascending=False))
    if not rows:
        return pd.DataFrame()
    return pd.concat(rows, ignore_index=True)


def plot_sector_exposure(holdings: pd.DataFrame, figures_dir: Path) -> None:
    """Plot monthly sector-weight composition as a stacked area chart."""
    # 用图直观展示“行业配置随时间怎么漂移”。按月重采样是为了压掉日频噪声，
    # 让科技等行业的长期超配趋势更容易一眼看出来。
    if holdings.empty:
        return
    figures_dir.mkdir(parents=True, exist_ok=True)
    daily_sector_weight = (
        holdings.groupby(["trade_date", "sector"])["weight"].sum().unstack(fill_value=0.0)
    )
    monthly = daily_sector_weight.resample("ME").mean()
    # 按平均权重从大到小排列行业，图例顺序才和“谁是主力仓位”一致。
    order = monthly.mean().sort_values(ascending=False).index
    monthly = monthly.loc[:, order]

    fig, axis = plt.subplots(figsize=(11, 5))
    axis.stackplot(monthly.index, monthly.to_numpy().T, labels=list(order))
    axis.set_title("Strategy Sector Exposure Over Time (monthly average weight)")
    axis.set_ylabel("Portfolio weight")
    axis.margins(x=0)
    axis.legend(loc="upper left", bbox_to_anchor=(1.01, 1.0), fontsize=8)
    fig.tight_layout()
    fig.savefig(figures_dir / "sector_exposure.png", dpi=150)
    plt.close(fig)


def build_exposure_report(config: dict[str, Any]) -> dict[str, pd.DataFrame]:
    """Load backtest holdings, run stage-14 exposure analysis, and persist reports."""
    # 主入口：只消费已经落盘的回测持仓和价格，不重新回测。
    # 这样暴露分析和回测规则彼此独立，改策略后重跑就能自动刷新暴露结论。
    reports_dir = Path(config["output"]["reports_dir"])
    figures_dir = Path(config["output"]["figures_dir"])
    reports_dir.mkdir(parents=True, exist_ok=True)

    active_weights_path = reports_dir / "backtest_active_weights.csv"
    if not active_weights_path.exists():
        raise FileNotFoundError(
            f"Missing backtest holdings: {active_weights_path}. Run the backtest step first."
        )
    active_weights = pd.read_csv(
        active_weights_path,
        dtype={"symbol": "string"},
        parse_dates=["trade_date"],
    )
    prices = pd.read_csv(
        Path(config["data"]["processed_dir"]) / "daily_prices.csv",
        dtype={"symbol": "string"},
        parse_dates=["trade_date"],
    )

    sector_map = load_sector_map(config)
    holdings = prepare_holdings(active_weights, prices, sector_map)

    sector_exposure = build_sector_exposure(holdings, sector_map)
    concentration = build_symbol_concentration(holdings)
    sector_attribution = build_sector_attribution(holdings)

    sector_exposure.to_csv(reports_dir / "holding_industry_exposure.csv", index=False)
    concentration.to_csv(reports_dir / "holding_symbol_concentration.csv", index=False)
    sector_attribution.to_csv(reports_dir / "sector_performance_attribution.csv", index=False)
    plot_sector_exposure(holdings, figures_dir)

    return {
        "sector_exposure": sector_exposure,
        "concentration": concentration,
        "sector_attribution": sector_attribution,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run stage-14 risk exposure analysis.")
    parser.add_argument("--config", default="config.yaml", help="Path to project config YAML.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    outputs = build_exposure_report(config)
    print("Saved exposure reports to results/reports")
    full_sample = outputs["sector_exposure"]
    full_sample = full_sample[full_sample["period"] == "full_sample"]
    print(full_sample.to_string(index=False))


if __name__ == "__main__":
    main()
