# 项目开发记录

这份文档记录项目从 0 到当前阶段做了什么、为什么这么做、如何验证。原始项目指南仍然只保留在本地，不上传到 Git。

## 当前原则

- 严谨优先于高收益：先保证数据、时间对齐、成本和测试是可信的。
- 所有可调参数集中放在 `config.yaml`，避免把股票池、日期、成本写死在代码里。
- 原始数据、清洗数据和报告结果都不提交到 Git，只提交代码、配置、测试和文档。
- 测试代码保留在 `tests/`，作为项目工程化能力的一部分。

## 阶段 0：工程骨架

已完成内容：

- 创建独立 Git 仓库并推送到 `https://github.com/losWater/quant`
- 使用 `uv` 管理 Python 3.11 虚拟环境
- 建立标准项目结构：
  - `src/quant_factor/`
  - `tests/`
  - `data/raw/`
  - `data/processed/`
  - `results/reports/`
  - `results/figures/`
  - `docs/`
- 添加 `.gitignore`，忽略虚拟环境、缓存、数据和运行结果
- 添加 `requirements.txt`、`requirements-dev.txt`、`pyproject.toml`、`uv.lock`

验证方式：

```bash
uv run pytest -q
uv run ruff check .
```

## 阶段 1：数据获取与清洗

代码位置：

- `src/quant_factor/data_loader.py`
- `tests/test_data_loader.py`

已完成内容：

- 使用 AkShare 获取最新沪深300成分股
- 下载 A 股日频后复权行情
- 将 AkShare 中文字段统一映射成英文列名
- 统一股票代码为 6 位字符串
- 统一日期和数值类型
- 过滤成交量为 0 的停牌日
- 去重并按 `symbol + trade_date` 排序
- 原始数据缓存到 `data/raw/`
- 清洗数据输出到 `data/processed/daily_prices.csv`
- 个别股票下载失败时记录到 `data/processed/download_failures.csv`，其余股票继续处理
- 全量下载使用请求超时、重试和短暂停顿，降低 AkShare 接口断连影响

运行命令：

```bash
uv run python -m quant_factor.data_loader --limit 3
```

小样本验证结果：

- 股票：`000001`、`000002`、`000063`
- 行数：4331
- 日期范围：2018-01-02 到 2023-12-29
- 停牌过滤后成交量为 0 的行数：0

重要限制：

- 当前股票池是“最新沪深300成分股”，用于工程闭环验证可以接受。
- 严谨回测需要历史成分股，否则存在幸存者偏差。

## 阶段 2：因子构造

代码位置：

- `src/quant_factor/factors.py`
- `tests/test_factors.py`

已完成内容：

- 构造 4 个基础因子：
  - `momentum`：过去 N 日收益率
  - `reversal`：短期收益率取负
  - `volatility`：过去 N 日收益率标准差
  - `ma_deviation`：价格偏离 N 日均线程度
- 按股票分别做滚动计算，避免不同股票数据混在一起
- 按交易日做截面预处理：
  - MAD 去极值
  - z-score 标准化
- 输出到 `data/processed/factors.csv`

运行命令：

```bash
uv run python -m quant_factor.factors
```

说明：

- 20 日窗口类因子在每只股票最开始的 20 个交易日会是空值，这是正常现象。
- 因子只使用当日及过去数据计算，不使用未来价格。

## 阶段 3：因子有效性检验

代码位置：

- `src/quant_factor/evaluation.py`
- `tests/test_evaluation.py`

已完成内容：

- 计算未来收益：T 日因子对应 T+1 收益
- 合并因子和未来收益
- 计算每日 RankIC
- 汇总 IC 均值、IC 标准差、IC_IR、IC 正值比例
- 按因子值做分组收益
- 生成分组净值曲线数据和图片

运行命令：

```bash
uv run python -m quant_factor.evaluation
```

输出文件：

- `results/reports/ic_series.csv`
- `results/reports/ic_summary.csv`
- `results/reports/group_returns.csv`
- `results/reports/group_nav.csv`
- `results/figures/group_nav.png`

说明：

- 当前只有 3 只股票小样本，所以 IC 和分组图只能验证流程，不能作为策略结论。
- 完整沪深300数据跑完后，IC 和分组结果才有研究意义。

## 阶段 4：含成本多头回测

代码位置：

- `src/quant_factor/backtest.py`
- `tests/test_backtest.py`

已完成内容：

- 默认使用 `config.yaml` 中的 `backtest.factor: momentum`
- 每月最后一个交易日生成调仓信号
- 按因子值从高到低选择前 `portfolio_quantile`
- 等权持仓
- 计算组合每日收益、换手率、交易成本、净收益、净值
- 输出目标持仓、实际持仓和净值曲线数据

运行命令：

```bash
uv run python -m quant_factor.backtest
```

输出文件：

- `results/reports/backtest_nav.csv`
- `results/reports/backtest_target_weights.csv`
- `results/reports/backtest_active_weights.csv`

时间对齐规则：

- T 日收盘后计算因子并生成信号
- T+1 记交易成本
- T+2 开始用收盘价收益近似持仓收益

这个规则偏保守，目的是避免用“当天收盘后才知道的信号”去赚当天收益。

## 当前测试覆盖

测试代码保留在 `tests/`，覆盖以下关键风险：

- 数据字段标准化、股票代码格式化、停牌过滤、去重
- 因子按单只股票独立滚动计算
- MAD 去极值和 z-score 标准化
- T 日因子与未来收益的时间对齐
- RankIC、IC 汇总、分组收益和分组净值
- 回测调仓日、选股、换手率、成本和信号延迟
- 基础绩效指标函数

当前验证命令：

```bash
uv run pytest -q
uv run ruff check .
```

## 阶段 5：绩效评估

代码位置：

- `src/quant_factor/metrics.py`
- `tests/test_metrics.py`

已完成内容：

- 从 `backtest_nav.csv` 计算年化收益、年化波动率、夏普比率、最大回撤、Calmar
- 计算总收益、平均换手率、总交易成本
- 生成回撤序列表
- 生成策略净值曲线和回撤曲线图

运行命令：

```bash
uv run python -m quant_factor.metrics
```

输出文件：

- `results/reports/performance_summary.csv`
- `results/reports/drawdown.csv`
- `results/figures/backtest_nav.png`
- `results/figures/backtest_drawdown.png`

说明：

- 当前绩效结果仍然基于 3 只股票小样本，只能验证通路。
- 正式分析需要先下载完整股票池，再重新运行数据、因子、评估、回测和绩效报告。

## 阶段 6：一键运行流程

代码位置：

- `src/quant_factor/pipeline.py`
- `tests/test_pipeline.py`

已完成内容：

- 将数据、因子、评估、回测、绩效报告串成一个统一入口
- 支持 `--limit` 做小样本 smoke run
- 支持 `--symbols` 指定股票
- 支持 `--steps` 只运行部分步骤
- 支持 `--refresh` 忽略本地原始数据缓存

运行小样本完整流程：

```bash
uv run python -m quant_factor.pipeline --limit 3
```

正式跑完整股票池时去掉 `--limit`。

## 下一步

- 下载完整沪深300股票池数据
- 重新运行完整 pipeline
- 检查完整样本下的 IC、分组表现和策略绩效
