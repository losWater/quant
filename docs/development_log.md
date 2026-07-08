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
- 输出时间对齐审计表，检查信号日、成本日和开始计收益日期

运行命令：

```bash
uv run python -m quant_factor.backtest
```

输出文件：

- `results/reports/backtest_nav.csv`
- `results/reports/backtest_target_weights.csv`
- `results/reports/backtest_active_weights.csv`
- `results/reports/backtest_timing_audit.csv`

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
- 回测调仓日、选股、换手率、成本、信号延迟和旧持仓替换
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

- 总收益：4.6999
- 年化收益：0.3373
- 年化波动率：0.2582
- 夏普比率：1.2558
- 最大回撤：-0.3054
- 平均换手率：0.0336
- 总交易成本：0.0812

SPY 对比：

- 策略总收益：4.6999；SPY 总收益：0.9554
- 策略年化收益：0.3373；SPY 年化收益：0.1185
- 策略年化波动率：0.2582；SPY 年化波动率：0.2038
- 策略夏普比率：1.2558；SPY 夏普比率：0.6519
- 策略最大回撤：-0.3054；SPY 最大回撤：-0.3372

等权股票池对比：

- 等权买入并持有总收益：2.3805
- 等权买入并持有年化收益：0.2256
- 等权买入并持有年化波动率：0.2301
- 等权买入并持有夏普比率：0.9996
- 等权买入并持有最大回撤：-0.2913

说明：

- 这次已经不是 3 只股票 smoke run，而是当前配置下的完整美股股票池运行。
- 修复旧持仓未清零问题后，策略收益仍高于 SPY 和等权股票池，但不再出现极端的 -92% 最大回撤。
- 加入 SPY 后可以看到策略收益更高，最大回撤与 SPY 接近但略小。
- 加入等权股票池后可以看到，当前股票池本身表现也很好；策略相对等权股票池收益更高，回撤略高。

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
- 当前策略跑赢 SPY，修复持仓替换逻辑后，最大回撤与 SPY 接近但略小。
- 仍需要继续做持仓归因，检查收益是否主要来自少数股票和集中暴露。

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

- 策略总收益：4.6999；等权股票池总收益：2.3805；SPY 总收益：0.9554
- 策略最大回撤：-0.3054；等权股票池最大回撤：-0.2913；SPY 最大回撤：-0.3372
- 近似收益贡献靠前的股票：`NFLX`、`NVDA`、`LLY`、`META`、`AAPL`

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
- 策略回撤与两个基准接近，收益更高，但仍需要更大股票池验证稳定性。
- 持仓贡献表显示收益贡献靠前的股票集中在少数大牛股上，后续需要做更严格的归因和风险控制。

## 阶段 10：时间对齐审计与持仓替换修复

代码位置：

- `src/quant_factor/backtest.py`
- `tests/test_backtest.py`

已完成内容：

- 新增 `backtest_timing_audit.csv`
- 每次调仓记录：
  - `signal_date`：信号生成日
  - `cost_date`：计入交易成本日
  - `first_return_date`：开始计入该次持仓收益日
  - `active_symbols_match_selected`：开始计收益时的实际持仓是否等于信号选股
- 修复旧持仓未清零问题：调仓日未被选中的股票现在会显式权重归零
- 增加测试，确认新一期选股会替换旧持仓

发现的问题：

- 旧逻辑在调仓日只给新选中的股票写入权重，没有把未选中的旧股票置 0。
- 后续 `ffill` 会错误保留旧股票权重，导致组合逐步累积越来越多股票。
- 这使之前的低换手率和极端回撤结果不可信。

修复后的检查结果：

- 完整调仓窗口：71 个
- 时间顺序全部通过：`signal_date < cost_date < first_return_date`
- 实际开始计收益持仓全部等于信号选股
- 最后 1 个调仓窗口不完整，因为样本结束于 2023-12-29，没有后续 T+1/T+2 数据
- 每个交易日最多持有 4 只股票，符合 20 只股票池、`portfolio_quantile: 0.2` 的预期

修复后的绩效对比：

- 策略总收益：4.6999；SPY 总收益：0.9554；等权股票池总收益：2.3805
- 策略年化收益：0.3373；SPY 年化收益：0.1185；等权股票池年化收益：0.2256
- 策略最大回撤：-0.3054；SPY 最大回撤：-0.3372；等权股票池最大回撤：-0.2913

验证命令：

```bash
uv run pytest -q
uv run ruff check .
uv run python -m quant_factor.pipeline
```

说明：

- 这一步很关键：它推翻并修正了之前基于错误持仓延续逻辑的回测数字。
- 修复后策略仍然跑赢两个基准，但结论更可信，也更适合进入下一步风险控制。

## 阶段 11：稳健性与过拟合检查

代码位置：

- `src/quant_factor/robustness.py`
- `tests/test_robustness.py`
- `src/quant_factor/pipeline.py`

已完成内容：

- 新增稳健性检查入口：

```bash
uv run python -m quant_factor.robustness
```

- 一键流程已加入 `robustness` 步骤：

```bash
uv run python -m quant_factor.pipeline
```

输出文件：

- `results/reports/yearly_performance.csv`
- `results/reports/sample_split_performance.csv`
- `results/reports/cost_sensitivity.csv`
- `results/reports/momentum_window_sensitivity.csv`

样本内 / 样本外：

- 样本内：2018-2021
- 样本外：2022-2023
- 样本内总收益：3.3184，年化收益：0.4416，夏普：1.5486，最大回撤：-0.2783
- 样本外总收益：0.3199，年化收益：0.1498，夏普：0.6686，最大回撤：-0.3054

分年度表现：

- 2018：总收益 0.0206，最大回撤 -0.1931
- 2019：总收益 0.4147，最大回撤 -0.1028
- 2020：总收益 0.6734，最大回撤 -0.2783
- 2021：总收益 0.7872，最大回撤 -0.0661
- 2022：总收益 -0.1568，最大回撤 -0.3054
- 2023：总收益 0.5654，最大回撤 -0.1078

成本敏感性：

- 成本 0 倍：总收益 5.1804，夏普 1.3078
- 成本 1 倍：总收益 4.6999，夏普 1.2558
- 成本 3 倍：总收益 3.8466，夏普 1.1509

动量窗口敏感性：

- 10 日窗口：总收益 1.8152，夏普 0.7927，最大回撤 -0.4218
- 20 日窗口：总收益 4.6999，夏普 1.2558，最大回撤 -0.3054
- 40 日窗口：总收益 3.9678，夏普 1.1434，最大回撤 -0.3162
- 60 日窗口：总收益 4.8691，夏普 1.2728，最大回撤 -0.2357

验证命令：

```bash
uv run pytest -q
uv run ruff check .
uv run python -m quant_factor.robustness
uv run python -m quant_factor.pipeline
```

说明：

- 样本外明显弱于样本内，这是过拟合风险信号，必须诚实记录。
- 2022 年表现为负，说明策略并非每年都有效。
- 成本提高到 3 倍后策略仍为正，但收益和夏普下降，说明成本敏感但没有被成本完全吃掉。
- 动量窗口不是只有 20 日有效，40 日和 60 日也能保持较好结果；10 日窗口明显较弱。
- 当前结论仍基于 20 只手动美股股票池，下一步应扩大股票池，降低样本偶然性。

## 阶段 12：第二阶段启动，扩大美股股票池

代码位置：

- `data/universe/us_large_cap_100.csv`
- `src/quant_factor/data_loader.py`
- `tests/test_data_loader.py`
- `docs/phase2_expanded_universe.md`

已完成内容：

- 新增可提交的股票池目录 `data/universe/`
- 新增 100 只代表性美股大盘股股票池
- `config.yaml` 默认从 `data/universe/us_large_cap_100.csv` 读取股票池
- 数据加载逻辑支持 `data.universe_file`
- 保留旧的 `symbols` 手动配置能力，方便 smoke run 或临时实验
- 新增单元测试，确认配置里的 CSV 股票池会被读取并标准化
- 完整运行 100 只股票 pipeline，确认处理后行情数据覆盖 100 只股票

100 只股票完整样本结果：

- 策略总收益：1.1966
- 策略年化收益：0.1404
- 策略夏普：0.7167
- 策略最大回撤：-0.3003
- SPY 总收益：0.9554
- 等权股票池总收益：1.4780

样本内 / 样本外：

- 2018-2021 样本内总收益：1.2759，夏普：1.0169
- 2022-2023 样本外总收益：-0.0349，夏普：0.0011

重要观察：

- 扩大股票池后，策略只小幅跑赢 SPY，但跑输等权股票池。
- 样本外基本失效，说明第一阶段 20 只股票结果可能受小样本和幸存者偏差影响。
- 这不是坏结果，而是更接近真实研究过程的风险暴露。
- 当前不适合直接进入复杂机器学习，应先建立更严格的样本外、滚动验证和股票池构建方式。

验证命令：

```bash
uv run pytest -q
uv run ruff check .
uv run python -m quant_factor.pipeline --limit 3
uv run python -m quant_factor.pipeline
```

## 阶段 13：滚动样本外验证

代码位置：

- `src/quant_factor/robustness.py`
- `tests/test_robustness.py`

已完成内容：

- 新增 `rolling_validation` 配置项
- 每个测试年使用过去 3 年作为训练期
- 在训练期里从 `10, 20, 40, 60` 日动量窗口中选择 Sharpe 最高的参数
- 用训练期选出的参数测试下一整年
- 输出参数候选表和最终滚动验证表

输出文件：

- `results/reports/rolling_validation.csv`
- `results/reports/rolling_validation_candidates.csv`

滚动样本外结果：

- 2021：选择 60 日动量，测试期收益 0.4057，跑赢 SPY 和等权股票池
- 2022：选择 20 日动量，测试期收益 -0.1810，略跑赢 SPY，但跑输等权股票池
- 2023：选择 60 日动量，测试期收益 0.1474，跑输 SPY 和等权股票池

重要观察：

- 策略不是完全无效，2021 年滚动样本外表现较好。
- 但它不稳定，2023 年训练期选出的参数没有跑赢简单基准。
- 当前仍不适合把机器学习作为主线，应先处理股票池、风险暴露和验证框架。

验证命令：

```bash
uv run pytest -q
uv run ruff check .
uv run python -m quant_factor.robustness
```

## 阶段 14：风险暴露分析

代码位置：

- `src/quant_factor/exposure.py`
- `tests/test_exposure.py`
- `data/universe/us_large_cap_100.csv`（新增 `sector` 行业列）

目的：

在上马机器学习前，先回答一个更根本的问题——策略的收益到底来自哪里。
如果收益主要来自行业/风格暴露而不是选股 alpha，那再复杂的模型也只是包装同一份 beta。
这个阶段只拆解已经跑完的 `backtest_active_weights.csv`，不改变任何策略规则。

已完成内容：

- 给 100 只股票池手动打上 GICS 11 行业标签，并把 `sector` 加入 universe schema 白名单
- 新增 `exposure` pipeline 步骤，位于 `metrics` 之后、`robustness` 之前
- 行业暴露表：每年/完整样本各行业平均权重，以及相对等权股票池基准的主动偏离 `active_tilt`
- 持仓集中度表：有效持仓数（1 / 平均每日 HHI）、Top-N 收益贡献占比、每年头号贡献股
- 行业收益归因表：把每天每只股票的收益贡献按行业汇总
- 行业暴露随时间变化的堆叠面积图

输出文件：

- `results/reports/holding_industry_exposure.csv`
- `results/reports/holding_symbol_concentration.csv`
- `results/reports/sector_performance_attribution.csv`
- `results/figures/sector_exposure.png`

关键结果（完整样本 2018-2023）：

- 信息技术行业平均权重 27.5%，相对等权基准 21% 超配 +6.5%，是最大的主动偏离；2019/2020 一度超配 +11%
- 收益归因：IT 贡献约 40% 毛收益，IT + 医药合计约 62%
- 一致性证据：2022 年（策略失效那年）IT 反而低配 -5.1%，说明动量在行业轮动之后才调仓
- 组合本身分散（等权 20 只，有效持仓数 = 20），但 Top10 名字约占毛收益贡献 35%，头号贡献股基本都是 IT/成长股

结论：

- 策略跑输等权股票池、样本外失效，很大程度上能用「IT/成长行业暴露」解释，而不是 momentum 选股 alpha。
- 这为下一步「行业中性化 / 行业权重上限」提供了明确动机，也再次说明现在还不适合直接上 ML。

验证命令：

```bash
uv run pytest -q
uv run ruff check .
uv run python -m quant_factor.exposure
```

## 阶段 15：行业中性化对照实验

代码位置：

- `src/quant_factor/backtest.py`（新增 `select_sector_neutral`，`run_long_only_backtest` 加 `sector_neutral` 开关）
- `src/quant_factor/neutralization.py`
- `tests/test_neutralization.py`

目的：

阶段 14 证实收益很大程度来自 IT 行业 beta。阶段 15 做控制变量实验——把行业押注剥掉
（每个行业强制等于等权基准权重，只在行业内部按动量选股），看策略相对等权股票池的表现是
变干净了还是消失了。两次回测只差 `sector_neutral` 一个开关，其余假设完全相同。

已完成内容：

- 行业中性选股：每个行业内部各选 top 20%，行业总权重对齐等权股票池基准
- 新增 `neutralization` pipeline 步骤，并排跑原策略与中性版
- 四方对照表（原策略 / 行业中性 / SPY / 等权股票池），同时报告完整样本、样本内、样本外
- 用阶段 14 的 exposure 逻辑验证中性版行业偏离是否归零
- 原策略 vs 中性版 vs 基准的净值对比图

输出文件：

- `results/reports/sector_neutral_comparison.csv`
- `results/reports/sector_neutral_exposure.csv`
- `results/figures/sector_neutral_comparison.png`

关键结果：

- 中性化生效验证：中性版所有行业 `active_tilt` 精确为 0，IT 从超配 +6.5% 压到 0。
- 完整样本：中性版 Sharpe 0.769 略高于原策略 0.717（总收益 1.274 vs 1.197）。
- 样本内 2018-2021（科技牛市）：中性版 Sharpe 0.929 低于原策略 1.017——牛市里超配 IT 是顺风，中性化吃亏。
- 样本外 2022-2023：原策略 Sharpe 0.001（基本失效），中性版 Sharpe 0.394 起死回生，
  且中性版样本外收益 +11.6% 同时跑赢 SPY(+3.2%) 和等权股票池(+8.5%)。

结论：

- 原策略 2022-2023 的灾难性失效，很大程度是"追涨 IT → 撞上 2022 崩盘 → 又割在底部"的行业择时造成的，而不是选股本身无效。
- 剥掉行业赌注后，剩下的"行业内动量选股"在样本外反而显出一点价值——但这只是一个 2 年窗口，还不能下定论，需要用滚动验证进一步检验。
- 这个结果修正了阶段 14 偏悲观的初步判断：收益不是纯 beta，行业内选股可能有微弱 alpha，但行业择时是明显的负贡献。

验证命令：

```bash
uv run pytest -q
uv run ruff check .
uv run python -m quant_factor.neutralization
```

## 阶段 16：行业中性版的滚动样本外验证

代码位置：

- `src/quant_factor/robustness.py`（`_run_configured_backtest` 和 `build_rolling_validation` 增加 `sector_neutral` / `sector_map`）
- `src/quant_factor/neutralization.py`（`build_rolling_neutral_comparison`）

目的：

阶段 15 里中性版的样本外优势只来自 2022-2023 一个固定窗口，说服力有限。阶段 16 用现有滚动
样本外框架逐年重复检验：每个测试年在训练期选动量窗口，再用选出的参数测试下一整年，
原策略和行业中性版各跑一遍逐年对比。原则是"一个好结果先当成可疑的好运，用更多样本外证伪它"。

已完成内容：

- 给滚动验证框架加 `sector_neutral` 开关（复用整套逐年逻辑，不复制流程）
- 新增 `rolling_neutral` pipeline 步骤，输出原策略 vs 中性版的逐年滚动对比表

输出文件：

- `results/reports/rolling_neutral_comparison.csv`

关键结果（逐年滚动，每年训练期选动量窗口）：

| 测试年 | 原策略 Sharpe | 中性版 Sharpe | 原策略赢等权池 | 中性版赢等权池 |
|---:|---:|---:|---|---|
| 2021 | 1.93 | 2.19 | 是 | 是 |
| 2022 | -0.80 | -0.81 | 否 | 否 |
| 2023 | 0.91 | 2.01 | 否 | 是 |

结论：

- 中性版每一年的 Sharpe 都不差于原版（2021 更高、2022 基本打平、2023 明显更高），
  说明阶段 15 的样本外改善不是单个窗口的偶然，风险调整后是稳定的。
- 战胜基准的战绩变好：跑赢等权池从 1/3 年提升到 2/3 年，跑赢 SPY 从 2/3 提升到 3/3。
- 但中性化不是万能药：2022 仍是双双亏损年，中性版也没把它救成正的；策略还没做到全面碾压等权池。
- 综合阶段 14-16：行业中性是真实、稳健的风险调整改进，足以定为往后的默认 baseline，但策略仍有坏年份。

验证命令：

```bash
uv run pytest -q
uv run ruff check .
uv run python -m quant_factor.pipeline --steps rolling_neutral
```

## 阶段 17：因子诊断（多 horizon IC + 相关性）

代码位置：

- `src/quant_factor/diagnostics.py`
- `tests/test_diagnostics.py`

目的：

多因子组合之前先体检。现有 IC 只在 1 天尺度算，但策略是月度调仓；4 个因子也不能无脑相加，
得先知道各自方向、强度、是否冗余。这一阶段只产诊断报告，不改策略、不做组合。

已完成内容：

- 多 horizon IC：在 1 / 5 / 21 天尺度各算一遍 RankIC，复用 evaluation 的 IC 口径
- 因子相关性：每日截面 Spearman 相关取平均，找冗余
- 新增 `diagnostics` pipeline 步骤和 config 段

输出文件：

- `results/reports/factor_ic_by_horizon.csv`
- `results/reports/factor_correlation.csv`

关键结果：

- IC 绝对值随 horizon 变大，1 天尺度会把因子强度看没——印证"必须匹配策略尺度"。
- 剧情反转：`momentum` 在所有 horizon 都是负 IC（21 天 -0.041，IR -0.20）。20 天属于短期反转区间，
  买近期赢家在截面上是略微亏本的选择；`reversal` 是其镜像、弱正。
- `momentum` 与 `ma_deviation` 相关 0.83，高度冗余。
- `volatility` 与其它因子几乎不相关、21 天 IC 正且随 horizon 增强，是最好的分散化苗子。

结论（闭环）：

- 策略核心信号（20 天动量）在截面上是负的，选股每步都在轻微减分；股票池整体上涨的 beta 让它
  仍为正，但拖累它跑输等权池。这和阶段 14（收益来自 IT beta）、15-16（剥掉 beta 后弱选股撑不住 2022）完全自洽。
- 直接指导阶段 18：剔除冗余的 ma_deviation；momentum 翻转符号或改用 reversal；保留独立的 volatility；
  但所有 IR ≤ 0.20，属弱信号，组合改善大概率有限。

验证命令：

```bash
uv run pytest -q
uv run ruff check .
uv run python -m quant_factor.diagnostics
```

## 阶段 18：多因子组合（行业中性框架下）

代码位置：

- `src/quant_factor/multi_factor.py`
- `tests/test_multi_factor.py`

目的：

把阶段 17 的诊断处方落成一个"方向摆正的弱多因子"，在行业中性框架下对比单因子 vs 多因子，
核心看 2022 有没有改善。

已完成内容：

- 剔除冗余的 ma_deviation；momentum 方向翻转（-1）、reversal/volatility 取 +1
- 每因子当天截面重新 z-score、乘符号等权相加 = 综合分 composite_score
- 综合分作为新列塞进已有的行业中性回测（factor="composite_score"），不改回测引擎
- 新增 `multi_factor` pipeline 步骤和 config 段；符号写在 config、是研究判断不做拟合

输出文件：

- `results/reports/multi_factor_comparison.csv`
- `results/reports/multi_factor_yearly.csv`
- `results/figures/multi_factor_comparison.png`

关键结果：

- 里程碑：多因子中性版样本外（2022-2023）第一次同时跑赢 SPY 和等权股票池（0.178 vs 0.085），
  样本外 Sharpe 0.490 > 单因子 0.394 > 等权 0.304 > SPY 0.180。
- 2022 改善：-13.9% → -10.5%，Sharpe -0.58 → -0.28，但仍是亏损年。
- 没有免费午餐：多因子完整样本收益更高（1.504 vs 1.274），但回撤更大（-0.387 vs -0.310），
  完整样本 Sharpe 基本打平（0.766 vs 0.769），仍略低于等权池 0.815。
- 2020 变差：综合分本质"买近期输家 + 高波动"，成长股狂奔环境吃亏。

结论：

- 符合阶段 17 "弱因子、改善有限"的诚实预期；样本外稳健性有真实小幅提升，可作新默认 baseline。
- 但样本外只有一个窗口，"第一次跑赢等权池"需滚动样本外进一步证伪；回撤变大要配合风控看。

验证命令：

```bash
uv run pytest -q
uv run ruff check .
uv run python -m quant_factor.multi_factor
```

## 阶段 19：严格版滚动验证（窗口内重推因子符号）

代码位置：

- `src/quant_factor/multi_factor.py`（`derive_factor_signs`、`build_rolling_multi_factor`）
- `tests/test_multi_factor.py`

目的：

阶段 18 的因子符号用了全样本（含测试年）定，是一处泄漏。阶段 19 改严格版：每个测试年只用自己的
训练期重新推导符号，堵住这个漏，看多因子的优势是否还在。原则：凡从数据学来的决定，只能用训练期学。

已完成内容：

- `derive_factor_signs`：在训练窗口内算每个因子的 IC，正取 +1、负取 -1
- `build_rolling_multi_factor`：逐个测试年、窗口内重推符号、搭综合分、只读测试年表现，单因子做对照
- 记录每个窗口推出的符号（符号稳不稳 = 因子方向可靠性的白送诊断）
- 新增 `rolling_multi_factor` pipeline 步骤和 config 的 sign_ic_horizon

输出文件：

- `results/reports/rolling_multi_factor_comparison.csv`

关键结果：

- 因子方向非常稳定：三个不重叠训练期各自独立推导，符号分毫不差（momentum 每次 -1、reversal +1、
  volatility +1）。证明方向不是全样本偷看的假象。
- 堵住符号泄漏后，多因子优势仍在：3/3 窗口跑赢等权池，3/3 不差于单因子；连 2022 也是四者中亏得最少的
  （-10.5% vs 单因子 -13.9% vs 等权 -16.9% vs SPY -18.2%）。

结论：

- 比阶段 18 "一个泄漏窗口的好结果"含金量高得多——优势在多个干净窗口下都成立。
- 但漏点②（因子的选择仍用全样本）还在；只有 3 个重叠窗口；2022 仍亏。唯一彻底干净的考场是真新数据。

验证命令：

```bash
uv run pytest -q
uv run ruff check .
uv run python -m quant_factor.pipeline --steps rolling_multi_factor
```

## 阶段 20：真新数据的终极检验（2024–2025）

代码位置：

- `src/quant_factor/out_of_time.py`
- `tests/test_out_of_time.py`

目的：

前面所有样本外都多少沾泄漏。这一步是唯一 100% 干净的考场：把策略锁死，拉取研究期之外的
2024–2025 真实行情检验。独立运行（需联网）：`uv run python -m quant_factor.out_of_time`。

已完成内容：

- 独立目录拉取 2024–2025 真实行情，策略决定全部来自 2018–2023、新数据只提供收益打分
- 锁死的行业中性多因子 vs SPY vs 等权股票池

输出文件：

- `results/reports/out_of_time_comparison.csv`
- `results/reports/out_of_time_yearly.csv`
- `results/figures/out_of_time_comparison.png`

关键结果（2024–2025，100% 干净）：

| 序列 | 总收益 | Sharpe | 最大回撤 |
|---|---:|---:|---:|
| 锁死策略 | +49.4% | 1.235 | -18.8% |
| SPY | +47.0% | 1.263 | -18.8% |
| 等权股票池 | +41.6% | 1.303 | -16.7% |

结论（诚实版）：

- 收益上策略跑赢两个基准（终于在收益上赢了等权池）；但风险调整（Sharpe）略输给两个基准、回撤略大。
- 差距都很小——本质上"大致等于市场"：没有令人信服的持续 alpha，但也没崩。
- 整条路的规律很典型：样本内很强 → 泄漏样本外赢等权 → 真新数据大致等于市场。
  每去掉一层自我欺骗，表面优势就往市场水平收缩。这正是纯价量因子策略的真实归宿。

## 项目当前总结论

用严谨的分阶段流程（工程闭环 → 因子诊断 → 行业中性 → 多因子 → 防泄漏 → 真新数据检验），
诚实地得到一个结论：**当前基于价量因子的策略，在最干净的检验下大致等于市场，没有明显 alpha。**
这不是失败，而是成功的证伪——它清楚回答了"策略为什么有效、什么时候失效、收益来自哪里"。

## 下一步（诚实的方向）

- 不再调价量因子参数（大概率仍是市场水平）。
- 换更好的原料：修幸存者偏差（历史成分股）、加入基本面等价量之外的因子，才可能有真 alpha。
- 若上机器学习：特征若仍是这几个价量因子，结果大概率仍是市场水平——要清醒。
- 把"会证伪自己、用真新数据检验"本身作为项目核心亮点。

## 问题清单

当前集中问题和风险已整理到 `docs/current_issues.md`，包括：

- 策略扩大股票池后跑输等权股票池
- 固定样本外基本失效
- 滚动样本外不稳定
- 股票池仍有幸存者偏差
- 未做行业、市值和风格中性化
- 当前不适合直接进入复杂机器学习主线
