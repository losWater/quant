# 复现检查清单

这份清单用于每次准备展示或提交项目前，确认项目能从干净环境重新跑通。

## 环境

- Python 版本使用 3.11
- 依赖通过 `requirements-dev.txt` 安装
- 项目配置集中在 `config.yaml`
- 原始数据、处理后数据、结果报告不提交到 Git

安装命令：

```bash
uv python install 3.11
uv venv --python 3.11
source .venv/bin/activate
uv pip install -r requirements-dev.txt
```

## 基础检查

运行测试：

```bash
uv run pytest -q
```

运行代码风格检查：

```bash
uv run ruff check .
```

当前预期：

- 测试全部通过
- ruff 无错误

## 小样本 smoke run

先用少量股票确认整条流程不崩：

```bash
uv run python -m quant_factor.pipeline --limit 3
```

检查点：

- 能生成 `data/processed/daily_prices.csv`
- 能生成 `data/processed/factors.csv`
- 能生成 `results/reports/backtest_nav.csv`
- 能生成 `results/reports/performance_summary.csv`
- 能生成 `results/reports/sample_split_performance.csv`
- 能生成 `results/reports/rolling_validation.csv`

## 完整流程

正式复现当前 README 里的结果：

```bash
uv run python -m quant_factor.pipeline
```

完整流程应输出：

```text
Pipeline finished: data, factors, evaluation, diagnostics, backtest, metrics, exposure, robustness, neutralization, rolling_neutral, multi_factor, rolling_multi_factor
```

## 关键结果核对

当前完整样本的主要结果应接近：

- 策略总收益：1.1966
- 策略年化收益：0.1404
- 策略夏普比率：0.7167
- 策略最大回撤：-0.3003
- SPY 总收益：0.9554
- 等权股票池总收益：1.4780

样本内 / 样本外结果应接近：

- 样本内总收益：1.2759
- 样本外总收益：-0.0349
- 样本外夏普：0.0011

滚动样本外结果应接近：

- 2021 测试年：选择 60 日动量，策略跑赢 SPY 和等权股票池
- 2022 测试年：选择 20 日动量，策略跑赢 SPY 但跑输等权股票池
- 2023 测试年：选择 60 日动量，策略跑输 SPY 和等权股票池

风险暴露（阶段 14）结果应接近，检查 `results/reports/holding_industry_exposure.csv`：

- 完整样本信息技术平均权重约 0.275，相对等权基准 0.21 超配约 +0.065
- `sector_performance_attribution.csv` 中 IT 毛收益贡献占比约 40%
- `holding_symbol_concentration.csv` 中有效持仓数约 20，Top10 收益贡献占比约 0.35

行业中性化（阶段 15）结果应接近，检查 `results/reports/sector_neutral_comparison.csv`：

- `sector_neutral_exposure.csv` 中所有行业 `active_tilt` 应全部为 0（中性化生效）
- 完整样本中性版 Sharpe 约 0.769，略高于原策略 0.717
- 样本外 2022-2023：原策略 Sharpe 约 0.001，中性版约 0.394（收益约 +11.6%）

中性版滚动验证（阶段 16）结果应接近，检查 `results/reports/rolling_neutral_comparison.csv`：

- 2021 测试年：中性版 Sharpe 约 2.19（原策略约 1.93），均跑赢等权池
- 2022 测试年：两者 Sharpe 都约 -0.80，均跑输等权池
- 2023 测试年：中性版 Sharpe 约 2.01、跑赢等权池；原策略约 0.91、跑输等权池

因子诊断（阶段 17）结果应接近，检查 `results/reports/factor_ic_by_horizon.csv`：

- momentum 21 天 IC 约 -0.041（负），ma_deviation 约 -0.035，reversal 约 +0.017，volatility 约 +0.031
- `factor_correlation.csv` 中 momentum 与 ma_deviation 相关约 0.83，volatility 与其它因子约 0

多因子组合（阶段 18）结果应接近，检查 `results/reports/multi_factor_comparison.csv`：

- 完整样本多因子中性版收益约 1.504、Sharpe 约 0.766、回撤约 -0.387
- 样本外 2022-2023 多因子 Sharpe 约 0.490，跑赢单因子（0.394）、等权池（0.304）、SPY（0.180）
- `multi_factor_yearly.csv` 中 2022：单因子 -13.9%、多因子 -10.5%

严格版滚动验证（阶段 19）结果应接近，检查 `results/reports/rolling_multi_factor_comparison.csv`：

- 三个测试年（2021/2022/2023）窗口内推出的符号应完全一致：momentum:-1;reversal:+1;volatility:+1
- 多因子在 3/3 窗口跑赢等权池（multi_beat_equal_weight 全为 True），也不差于单因子
- 2022 多因子约 -10.5%，是四者中亏得最少的（单因子 -13.9%、等权 -16.9%、SPY -18.2%）

真新数据终极检验（阶段 20，需联网单独运行 `uv run python -m quant_factor.out_of_time`）：

- 2024-2025 锁死策略收益约 +49%，Sharpe 约 1.24；SPY 约 +47%/1.26；等权池约 +42%/1.30
- 结论：收益略赢基准，但风险调整略输——大致等于市场、无明显 alpha
- 注：依赖 yfinance 实时数据，具体数值随数据更新会有小幅变化

## 时间对齐检查

检查 `results/reports/backtest_timing_audit.csv`：

- 完整调仓窗口的 `timing_ok` 应为 `True`
- 完整调仓窗口的 `active_symbols_match_selected` 应为 `True`
- 最后一个窗口可能是 `incomplete`，因为样本结束后没有 T+1/T+2 数据

## Git 提交前检查

确认只提交代码、配置、测试和文档：

```bash
git status --short --ignored
```

不应提交：

- `.venv/`
- `.pytest_cache/`
- `.ruff_cache/`
- `data/raw/`
- `data/processed/`
- `results/reports/`
- `results/figures/`
- 原始项目指南 `docs/量化项目分步指南.md`

## 当前已知局限

- 手动 100 只美股大盘股仍然存在幸存者偏差
- 样本外弱于样本内
- 滚动样本外表现不稳定
- 未做行业/市值中性化
- 未做真实成交价和盘口冲击建模
- 当前结论不能直接视为实盘策略结论
