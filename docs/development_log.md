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

- 当前默认使用 yfinance 获取美股日频行情
- A 股 AkShare 适配代码仍保留，可按配置切回
- 数据源适配器已拆到 `src/quant_factor/data_sources/`
- 数据适配层负责输出统一 schema，后续因子、评估、回测只依赖标准 CSV
- 美股股票池来自 `config.yaml` 中的手动列表
- 将不同数据源字段统一映射成英文列名
- 统一股票代码格式
- 统一价格字段为 `trade_date, symbol, open, close, high, low, volume, amount, market, source`
- 统一日期和数值类型
- 过滤成交量为 0 的停牌日
- 去重并按 `symbol + trade_date` 排序
- 原始数据缓存到 `data/raw/`
- 清洗数据输出到 `data/processed/daily_prices.csv`
- 个别股票下载失败时记录到 `data/processed/download_failures.csv`，其余股票继续处理
- 全量下载使用请求超时、重试和短暂停顿，降低数据源接口断连影响
- A 股模式下东方财富日线接口失败时回退到腾讯日线接口；备用接口字段较少，但保留当前流程需要的价格和成交量

运行命令：

```bash
uv run python -m quant_factor.data_loader --limit 3
```

小样本验证结果：

- 股票：`AAPL`、`AMZN`、`AVGO`
- 行数：4527
- 日期范围：2018-01-02 到 2023-12-29
- 停牌过滤后成交量为 0 的行数：0

重要限制：

- 当前股票池是手动美股列表，用于工程闭环验证可以接受。
- 严谨回测需要历史指数成分股，否则仍然存在幸存者偏差。
- 美股数据字段与 A 股不同，当前价格类因子主要依赖 `close`，所以后续模块可以复用。

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

- 3 只股票小样本时，IC 和分组图只能验证流程，不能作为策略结论。
- 当前完整运行使用 20 只手动美股股票池，仍然是工程验证和初步研究，不代表严格可交易结论。

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
- 按 `config.yaml` 的 `backtest.benchmark` 下载并对齐 SPY 基准
- 计算 20 只股票等权买入并持有基准
- 计算总收益、平均换手率、总交易成本
- 生成回撤序列表
- 生成策略净值曲线和回撤曲线图
- 生成策略和基准的绩效对比表与净值对比图
- 生成持仓天数、平均权重和近似收益贡献检查表

运行命令：

```bash
uv run python -m quant_factor.metrics
```

输出文件：

- `results/reports/performance_summary.csv`
- `results/reports/performance_comparison.csv`
- `results/reports/benchmark_nav.csv`
- `results/reports/holding_summary.csv`
- `results/reports/drawdown.csv`
- `results/figures/backtest_nav.png`
- `results/figures/backtest_drawdown.png`
- `results/figures/benchmark_comparison_nav.png`

说明：

- 当前绩效结果已可基于完整配置股票池生成。
- 严谨分析还需要扩大股票池、加入更多基准对照，并继续检查交易成本、调仓规则和幸存者偏差。

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

## 阶段 7：完整美股股票池跑通

运行命令：

```bash
uv run python -m quant_factor.pipeline
```

运行结果：

- 股票池：`config.yaml` 中的 20 只美股
- 数据行数：30180
- 因子行数：30180
- 回测净值行数：1509
- 下载失败：无
- 流程状态：数据、因子、评估、回测、绩效报告全部跑通

IC 摘要：

- `momentum`：IC 均值 -0.0104，IC_IR -0.0320
- `reversal`：IC 均值 0.0059，IC_IR 0.0180
- `volatility`：IC 均值 0.0016，IC_IR 0.0045
- `ma_deviation`：IC 均值 -0.0122，IC_IR -0.0376

绩效摘要：

- 总收益：14.3228
- 年化收益：0.5774
- 年化波动率：1.0757
- 夏普比率：0.9923
- 最大回撤：-0.9229
- 平均换手率：0.0033
- 总交易成本：0.0080

SPY 对比：

- 策略总收益：14.3228；SPY 总收益：0.9554
- 策略年化收益：0.5774；SPY 年化收益：0.1185
- 策略年化波动率：1.0757；SPY 年化波动率：0.2038
- 策略夏普比率：0.9923；SPY 夏普比率：0.6519
- 策略最大回撤：-0.9229；SPY 最大回撤：-0.3372

等权股票池对比：

- 等权买入并持有总收益：2.3805
- 等权买入并持有年化收益：0.2256
- 等权买入并持有年化波动率：0.2301
- 等权买入并持有夏普比率：0.9996
- 等权买入并持有最大回撤：-0.2913

说明：

- 这次已经不是 3 只股票 smoke run，而是当前配置下的完整美股股票池运行。
- 结果看起来波动和回撤都很大，下一步不应该急着优化收益，而应该继续做基准、风险暴露和结果检查。
- 加入 SPY 后可以看到策略收益更高，但承担的波动和最大回撤也显著更大。
- 加入等权股票池后可以看到，当前股票池本身表现也很好；策略相对等权股票池收益更高，但风险明显更大。

## 阶段 8：加入 SPY 基准对照

代码位置：

- `src/quant_factor/metrics.py`
- `tests/test_metrics.py`

已完成内容：

- 使用 `backtest.benchmark: SPY` 作为市场基准
- 读取或下载 SPY 日线数据
- 将 SPY 收益和策略回测日期对齐
- 输出 `benchmark_nav.csv`
- 输出 `performance_comparison.csv`
- 输出 `benchmark_comparison_nav.png`
- 增加日期对齐和绩效对比的单元测试

验证命令：

```bash
uv run pytest -q
uv run ruff check .
uv run python -m quant_factor.metrics
uv run python -m quant_factor.pipeline
```

说明：

- SPY 是可投资的市场基准，比单看策略净值更有意义。
- 当前策略跑赢 SPY 的同时，也承受了远高于 SPY 的波动和回撤。
- 这说明下一步要继续做持仓归因，检查收益是否主要来自少数股票和集中暴露。

## 阶段 9：加入等权股票池基准和持仓检查

代码位置：

- `src/quant_factor/metrics.py`
- `tests/test_metrics.py`

已完成内容：

- 使用当前 20 只美股构造等权买入并持有基准
- 将等权基准与策略回测日期对齐
- 将 SPY、等权股票池和策略一起写入 `performance_comparison.csv`
- 将多个基准曲线一起写入 `benchmark_nav.csv`
- 输出 `holding_summary.csv`，检查每只股票持仓天数、权重和近似收益贡献
- 增加等权基准和持仓贡献的单元测试

本次结果：

- 策略总收益：14.3228；等权股票池总收益：2.3805；SPY 总收益：0.9554
- 策略最大回撤：-0.9229；等权股票池最大回撤：-0.2913；SPY 最大回撤：-0.3372
- 近似收益贡献靠前的股票：`NVDA`、`LLY`、`AVGO`、`AAPL`、`COST`

验证命令：

```bash
uv run pytest -q
uv run ruff check .
uv run python -m quant_factor.metrics
uv run python -m quant_factor.pipeline
```

说明：

- 策略确实跑赢了 SPY 和当前 20 只股票等权买入并持有。
- 但等权股票池本身也显著上涨，说明股票池选择本身贡献很大。
- 策略风险仍然很高，最大回撤远大于两个基准。
- 持仓贡献表显示收益贡献靠前的股票集中在少数大牛股上，后续需要做更严格的归因和风险控制。

## 下一步

- 检查回测收益是否存在时间对齐问题
- 增加单只股票最大权重、最大回撤控制或波动率控制
- 扩展美股股票池，减少 20 只股票样本过小带来的偶然性
