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

建议使用 Python 3.11 或 3.12：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
```

## Development

运行测试：

```bash
pytest
```

后续计划：

- 实现数据下载与清洗 pipeline
- 实现动量、反转、波动率等基础因子
- 实现 RankIC 与分组回测
- 实现含手续费、滑点和调仓逻辑的回测引擎
- 输出净值曲线、回撤曲线和绩效指标
