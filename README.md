# Quant Factor Project

多因子选股与严谨回测项目。目标不是追求夸张收益，而是建立一个可复现、可解释、能讨论风险和偏差的量化研究流程。

## Project Scope

- 市场：美股，初始股票池使用 `config.yaml` 中的手动股票列表
- 频率：日频
- 数据源：默认使用 yfinance；A 股适配代码仍保留 AkShare 支持
- 方法：因子构造、RankIC 检验、分组回测、含成本策略回测、绩效评估
- 工程目标：配置集中管理、源码模块化、单元测试、结果可复现

## Repository Layout

```text
.
├── config.yaml
├── data/
│   ├── raw/
│   └── processed/
├── docs/
├── notebooks/
├── results/
│   ├── figures/
│   └── reports/
├── src/
│   └── quant_factor/
└── tests/
```

## Setup

建议使用 Python 3.11。当前项目可以用 `uv` 管理本地虚拟环境：

```bash
uv python install 3.11
uv venv --python 3.11
source .venv/bin/activate
uv pip install -r requirements-dev.txt
```

## Development

开发过程记录见 [docs/development_log.md](docs/development_log.md)。

运行测试：

```bash
pytest
```

下载并清洗少量样本数据：

```bash
uv run python -m quant_factor.data_loader --limit 3
```

也可以指定股票代码：

```bash
uv run python -m quant_factor.data_loader --symbols AAPL MSFT NVDA
```

输出文件：

- `data/raw/universe_csi300.csv`
- `data/raw/prices/*.csv`
- `data/processed/daily_prices.csv`
- `data/processed/download_failures.csv`，仅当个别股票下载失败时生成

注意：当前美股股票池是手动列表，适合项目起步和工程闭环验证。严谨回测阶段需要替换为历史指数成分股或明确讨论幸存者偏差。
全量下载时会按 `config.yaml` 中的 `request_retries`、`request_sleep_seconds`、`request_timeout` 做重试和限速。

计算基础因子：

```bash
uv run python -m quant_factor.factors
```

输出文件：

- `data/processed/factors.csv`

评估因子有效性：

```bash
uv run python -m quant_factor.evaluation
```

输出文件：

- `results/reports/ic_series.csv`
- `results/reports/ic_summary.csv`
- `results/reports/group_returns.csv`
- `results/reports/group_nav.csv`
- `results/figures/group_nav.png`

运行含成本多头回测：

```bash
uv run python -m quant_factor.backtest
```

输出文件：

- `results/reports/backtest_nav.csv`
- `results/reports/backtest_target_weights.csv`
- `results/reports/backtest_active_weights.csv`

当前回测默认使用 `config.yaml` 中的 `backtest.factor: momentum`。小样本结果只用于验证流程，不代表策略有效性。

生成绩效评估报告：

```bash
uv run python -m quant_factor.metrics
```

输出文件：

- `results/reports/performance_summary.csv`
- `results/reports/drawdown.csv`
- `results/figures/backtest_nav.png`
- `results/figures/backtest_drawdown.png`

一键运行完整流程：

```bash
uv run python -m quant_factor.pipeline --limit 3
```

正式跑完整股票池时去掉 `--limit`。这会耗时更久，并依赖 AkShare 网络接口稳定性。

后续计划：

- 下载完整股票池数据并重新运行全流程
