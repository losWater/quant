"""End-to-end project pipeline runner."""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from typing import Any

from quant_factor.backtest import run_backtest
from quant_factor.config import load_config
from quant_factor.data_loader import build_price_dataset
from quant_factor.diagnostics import build_diagnostics_report
from quant_factor.evaluation import evaluate_factors
from quant_factor.exposure import build_exposure_report
from quant_factor.factors import build_factor_dataset
from quant_factor.metrics import build_performance_report
from quant_factor.multi_factor import (
    build_multi_factor_report,
    build_rolling_multi_factor,
)
from quant_factor.neutralization import (
    build_neutralization_report,
    build_rolling_neutral_comparison,
)
from quant_factor.robustness import build_robustness_report

PIPELINE_STEPS = [
    "data",
    "factors",
    "evaluation",
    "diagnostics",
    "backtest",
    "metrics",
    "exposure",
    "robustness",
    "neutralization",
    "rolling_neutral",
    "multi_factor",
    "rolling_multi_factor",
]


def run_pipeline(
    config: dict[str, Any],
    *,
    steps: Iterable[str] = PIPELINE_STEPS,
    symbols: Iterable[str] | None = None,
    limit: int | None = None,
    refresh: bool = False,
) -> dict[str, Any]:
    """Run selected project pipeline steps in dependency order."""
    selected_steps = list(steps)
    outputs: dict[str, Any] = {}

    # 这里按研究流程顺序执行；每一步都只依赖前一步落盘后的标准文件。
    # 设计思路是“可分阶段、也可一键跑”：
    # - 调试下载时可以只跑 data
    # - 改因子时可以从 factors 开始
    # - 最终复现时直接跑完整 pipeline
    # 这样既适合学习，也适合以后放到 CI 或定时任务里。
    if "data" in selected_steps:
        outputs["data"] = build_price_dataset(
            config,
            symbols=symbols,
            limit=limit,
            refresh=refresh,
        )

    if "factors" in selected_steps:
        outputs["factors"] = build_factor_dataset(config)

    if "evaluation" in selected_steps:
        outputs["evaluation"] = evaluate_factors(config)

    if "diagnostics" in selected_steps:
        # 阶段 17 因子诊断：多 horizon IC + 相关性，为后续多因子组合确定选哪些因子、什么符号。
        # 只依赖 factors.csv，放在 evaluation 之后、backtest 之前，都属于策略前的因子分析。
        outputs["diagnostics"] = build_diagnostics_report(config)

    if "backtest" in selected_steps:
        outputs["backtest"] = run_backtest(config)

    if "metrics" in selected_steps:
        outputs["metrics"] = build_performance_report(config)

    if "exposure" in selected_steps:
        # 阶段 14 风险暴露分析：依赖 backtest 落盘的持仓，解释收益来自哪些行业和股票。
        # 放在 metrics 之后、robustness 之前，因为它和 robustness 一样只“解读”策略，不改策略。
        outputs["exposure"] = build_exposure_report(config)

    if "robustness" in selected_steps:
        # robustness 依赖前面已经生成的 backtest_nav 和 factors。
        # 它不改变策略，只负责检查策略结论是否稳定。
        outputs["robustness"] = build_robustness_report(config)

    if "neutralization" in selected_steps:
        # 阶段 15 行业中性化：并排跑原策略与行业中性版，验证收益是行业 beta 还是选股 alpha。
        # 复用 metrics 落盘的 benchmark_nav 做四方对照。
        outputs["neutralization"] = build_neutralization_report(config)

    if "rolling_neutral" in selected_steps:
        # 阶段 16：对行业中性版跑滚动样本外验证，检验阶段 15 的样本外优势是否只是单窗口偶然。
        outputs["rolling_neutral"] = build_rolling_neutral_comparison(config)

    if "multi_factor" in selected_steps:
        # 阶段 18：按阶段 17 诊断把方向对齐后的因子拼成综合分，行业中性下对比单因子 vs 多因子。
        outputs["multi_factor"] = build_multi_factor_report(config)

    if "rolling_multi_factor" in selected_steps:
        # 阶段 19：严格版滚动验证——每个训练窗口内单独重推因子符号，堵住阶段 18 的符号泄漏。
        outputs["rolling_multi_factor"] = build_rolling_multi_factor(config)

    return outputs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the quant project pipeline.")
    parser.add_argument("--config", default="config.yaml", help="Path to project config YAML.")
    parser.add_argument(
        "--steps",
        nargs="+",
        choices=PIPELINE_STEPS,
        default=PIPELINE_STEPS,
        help="Pipeline steps to run in order.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of symbols for data download smoke runs.",
    )
    parser.add_argument(
        "--symbols",
        nargs="*",
        help="Explicit symbols to download, e.g. 000001 600519.",
    )
    parser.add_argument("--refresh", action="store_true", help="Ignore local raw-data cache.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    outputs = run_pipeline(
        config,
        steps=args.steps,
        symbols=args.symbols,
        limit=args.limit,
        refresh=args.refresh,
    )
    print(f"Pipeline finished: {', '.join(outputs)}")


if __name__ == "__main__":
    main()
