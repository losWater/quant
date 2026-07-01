"""End-to-end project pipeline runner."""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from typing import Any

from quant_factor.backtest import run_backtest
from quant_factor.config import load_config
from quant_factor.data_loader import build_price_dataset
from quant_factor.evaluation import evaluate_factors
from quant_factor.factors import build_factor_dataset
from quant_factor.metrics import build_performance_report

PIPELINE_STEPS = ["data", "factors", "evaluation", "backtest", "metrics"]


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

    if "backtest" in selected_steps:
        outputs["backtest"] = run_backtest(config)

    if "metrics" in selected_steps:
        outputs["metrics"] = build_performance_report(config)

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
