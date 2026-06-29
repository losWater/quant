# Quant Factor Project

多因子选股与严谨回测项目。目标不是追求夸张收益，而是建立一个可复现、可解释、能讨论风险和偏差的量化研究流程。

## Project Scope

- 市场：A 股，初始股票池建议使用沪深300成分股
- 频率：日频
- 数据源：优先使用 akshare，也可切换到 tushare
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
uv run python -m quant_factor.data_loader --symbols 000001 600519
```

输出文件：

- `data/raw/universe_csi300.csv`
- `data/raw/prices/*.csv`
- `data/processed/daily_prices.csv`

注意：当前股票池使用 AkShare 返回的最新沪深300成分股，适合项目起步和工程闭环验证。严谨回测阶段需要替换为历史成分股或明确讨论幸存者偏差。

计算基础因子：

```bash
uv run python -m quant_factor.factors
```

输出文件：

- `data/processed/factors.csv`

后续计划：

- 实现 RankIC 与分组回测
- 实现含手续费、滑点和调仓逻辑的回测引擎
- 输出净值曲线、回撤曲线和绩效指标
