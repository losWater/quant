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
Pipeline finished: data, factors, evaluation, backtest, metrics, exposure, robustness
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
