# Quant Factor Project

多因子选股与严谨回测项目。目标不是追求夸张收益，而是建立一条可复现、可解释、能主动讨论风险和偏差的量化研究流程。

当前项目使用美股日频数据作为主线，A 股数据适配代码仍保留。原始项目指南只保留在本地，不上传 Git。

## 核心结论

当前配置：

- 股票池：`data/universe/us_large_cap_100.csv` 中的 100 只代表性美股大盘股
- 时间区间：2018-01-01 到 2023-12-31
- 数据源：`yfinance`
- 因子：`momentum`、`reversal`、`volatility`、`ma_deviation`
- 策略：按 `momentum` 月度调仓，选前 20%，等权持有
- 成本：买卖佣金、滑点，当前无美股印花税
- 基准：`SPY`、100 只股票等权买入并持有

完整样本表现：

| series | total_return | annualized_return | sharpe_ratio | max_drawdown |
|---|---:|---:|---:|---:|
| strategy | 1.1966 | 0.1404 | 0.7167 | -0.3003 |
| SPY | 0.9554 | 0.1185 | 0.6519 | -0.3372 |
| equal_weight_universe | 1.4780 | 0.1636 | 0.8148 | -0.3267 |

样本内 / 样本外表现：

| sample | total_return | annualized_return | sharpe_ratio | max_drawdown |
|---|---:|---:|---:|---:|
| 2018-2021 in-sample | 1.2759 | 0.2283 | 1.0169 | -0.3003 |
| 2022-2023 out-of-sample | -0.0349 | -0.0177 | 0.0011 | -0.2919 |

关键观察：

- 策略在完整样本中小幅跑赢 `SPY`，但跑输 100 只股票等权买入并持有。
- 样本外 2022-2023 基本失效，这是比 20 只股票 baseline 更严格的过拟合风险信号。
- 滚动样本外验证显示：2021 跑赢两个基准，2022 只跑赢 SPY，2023 跑输两个基准。
- 2022 年策略表现为负，说明策略不是每年都有效。
- 成本提高到 3 倍后策略仍为正，但收益和夏普下降。
- 动量窗口 40、60 天好于 20 天，说明当前参数仍有继续验证空间。
- 扩大股票池后结论变弱，说明第一阶段 20 只股票结果可能受小样本影响。

## 项目范围

- 市场：美股，当前股票池使用 `data/universe/us_large_cap_100.csv`
- 频率：日频
- 数据源：默认使用 `yfinance`；A 股适配代码仍保留 AkShare 支持
- 方法：因子构造、RankIC 检验、分组回测、含成本策略回测、绩效评估、稳健性检查
- 工程目标：配置集中管理、源码模块化、单元测试、结果可复现

## 项目结构

```text
.
├── config.yaml
├── data/
│   ├── universe/
│   ├── raw/
│   └── processed/
├── docs/
├── notebooks/
├── results/
│   ├── figures/
│   └── reports/
├── src/
│   └── quant_factor/
│       ├── data_sources/
│       ├── data_loader.py
│       ├── factors.py
│       ├── evaluation.py
│       ├── backtest.py
│       ├── metrics.py
│       ├── robustness.py
│       └── pipeline.py
└── tests/
```

## 环境安装

建议使用 Python 3.11。当前项目可以用 `uv` 管理本地虚拟环境：

```bash
uv python install 3.11
uv venv --python 3.11
source .venv/bin/activate
uv pip install -r requirements-dev.txt
```

## 一键复现

小样本 smoke run：

```bash
uv run python -m quant_factor.pipeline --limit 3
```

完整股票池：

```bash
uv run python -m quant_factor.pipeline
```

完整流程会依次运行：

```text
data -> factors -> evaluation -> backtest -> metrics -> robustness
```

## 分阶段运行

下载并清洗数据：

```bash
uv run python -m quant_factor.data_loader
```

也可以指定股票代码：

```bash
uv run python -m quant_factor.data_loader --symbols AAPL MSFT NVDA
```

计算因子：

```bash
uv run python -m quant_factor.factors
```

评估因子：

```bash
uv run python -m quant_factor.evaluation
```

运行含成本多头回测：

```bash
uv run python -m quant_factor.backtest
```

生成绩效报告：

```bash
uv run python -m quant_factor.metrics
```

运行稳健性检查：

```bash
uv run python -m quant_factor.robustness
```

## 输出文件

数据：

- `data/universe/us_large_cap_100.csv`
- `data/raw/prices/*.csv`
- `data/processed/daily_prices.csv`
- `data/processed/factors.csv`
- `data/processed/download_failures.csv`，仅当个别股票下载失败时生成

因子评估：

- `results/reports/ic_series.csv`
- `results/reports/ic_summary.csv`
- `results/reports/group_returns.csv`
- `results/reports/group_nav.csv`
- `results/figures/group_nav.png`

回测与绩效：

- `results/reports/backtest_nav.csv`
- `results/reports/backtest_target_weights.csv`
- `results/reports/backtest_active_weights.csv`
- `results/reports/backtest_timing_audit.csv`
- `results/reports/performance_summary.csv`
- `results/reports/performance_comparison.csv`
- `results/reports/benchmark_nav.csv`
- `results/reports/holding_summary.csv`
- `results/reports/drawdown.csv`
- `results/figures/backtest_nav.png`
- `results/figures/backtest_drawdown.png`
- `results/figures/benchmark_comparison_nav.png`

稳健性检查：

- `results/reports/yearly_performance.csv`
- `results/reports/sample_split_performance.csv`
- `results/reports/cost_sensitivity.csv`
- `results/reports/momentum_window_sensitivity.csv`
- `results/reports/rolling_validation.csv`
- `results/reports/rolling_validation_candidates.csv`

## 工程验证

运行测试：

```bash
uv run pytest -q
```

运行代码风格检查：

```bash
uv run ruff check .
```

当前测试覆盖：

- 数据字段标准化、股票代码格式化、停牌过滤、去重
- 因子按单只股票独立滚动计算
- MAD 去极值和 z-score 标准化
- T 日因子与未来收益的时间对齐
- RankIC、IC 汇总、分组收益和分组净值
- 回测调仓日、选股、换手率、成本、信号延迟和旧持仓替换
- SPY 和等权股票池基准对齐
- 样本内外、年度表现、成本敏感性和参数敏感性
- 滚动样本外参数选择和测试期基准对比

## 重要假设与局限

- 当前股票池是手动挑选的 100 只代表性美股大盘股，仍然存在幸存者偏差。
- 结果不能视为可实盘交易结论，只能说明工程闭环和初步研究流程已经建立。
- 当前回测使用日频 close-to-close 收益近似持仓收益，尚未建模开盘成交、盘口冲击和真实流动性。
- 当前没有做行业、市值、风格中性化。
- 当前没有接入财报、新闻、公告等事件数据。
- 样本外表现明显弱于样本内，需要继续扩大股票池、引入历史成分股并做滚动验证。

## 后续计划

- 用历史成分股或更系统的股票池构建方式，继续降低幸存者偏差
- 加入更多基准和风险暴露分析
- 做行业/市值中性化或更完整的多因子组合
- 增加单只股票最大权重、波动率控制或回撤控制
- 在主线稳定后，再迭代异常事件类因子

## 开发记录

完整开发过程见 [docs/development_log.md](docs/development_log.md)。

辅助文档：

- [项目总结与面试讲稿](docs/project_summary.md)
- [第二阶段：扩大股票池与机器学习门槛](docs/phase2_expanded_universe.md)
- [当前问题与风险清单](docs/current_issues.md)
- [复现检查清单](docs/reproducibility_checklist.md)
