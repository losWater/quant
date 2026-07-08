# AI 交接说明

这份文档用于把当前项目交接给下一个 AI 或下一轮会话。请优先阅读本文件，再看 `README.md`、`docs/development_log.md` 和 `docs/current_issues.md`。

## 当前项目定位

当前目录：

```text
/Users/ice2447/ruobing/quant_research_project
```

这个目录是量化研究项目的第二阶段版本，用来继续深化策略研究。第一阶段已经单独分离成可展示的公开项目：

```text
/Users/ice2447/ruobing/quant_interview_project
```

第一阶段公开仓库已经推送到：

```text
https://github.com/losWater/quant_interview_project
```

当前研究版仍保留第二阶段内容，包括 100 只股票池、滚动样本外验证、问题清单等。

## 已经完成的事情

### 1. 工程骨架

项目已经是标准 Python 工程结构：

- `src/quant_factor/`：核心代码
- `tests/`：单元测试
- `config.yaml`：集中配置
- `data/`：数据目录
- `results/`：报告和图表目录
- `docs/`：开发日志、复现清单、阶段文档和问题清单

依赖通过 `requirements.txt`、`requirements-dev.txt` 和 `uv.lock` 管理。

### 2. 数据层

已经实现：

- 默认使用 `yfinance` 获取美股日频数据
- 保留 AkShare / A 股适配代码
- 数据源适配层统一输出 OHLCV schema
- 支持本地缓存，避免每次重复下载
- 支持单只股票下载失败后记录失败并继续流程
- 支持从 CSV 股票池读取标的

当前第二阶段股票池：

```text
data/universe/us_large_cap_100.csv
```

该股票池包含 100 只代表性美股大盘股。

### 3. 因子层

当前实现 4 个基础因子：

- `momentum`：过去 N 日收益率
- `reversal`：短期收益率取反
- `volatility`：过去 N 日收益波动率
- `ma_deviation`：收盘价相对移动均线的偏离

因子预处理包括：

- MAD 去极值
- z-score 标准化
- 按交易日截面处理

### 4. 因子评估

已经实现：

- T 日因子对应未来收益，避免未来函数
- RankIC 序列
- IC 汇总
- 分组收益
- 分组净值

输出包括：

- `results/reports/ic_series.csv`
- `results/reports/ic_summary.csv`
- `results/reports/group_returns.csv`
- `results/reports/group_nav.csv`
- `results/figures/group_nav.png`

### 5. 回测

当前主策略：

- 使用 `momentum` 因子
- 月度调仓
- 每次选因子排名前 20%
- 等权持有
- 计入买卖佣金和滑点

时间线：

- T 日收盘后计算信号
- T+1 记录调仓成本
- T+2 开始计算新持仓收益

已经修过一个重要 bug：

- 旧逻辑中，调仓日未选中的旧股票可能被 `ffill` 错误延续
- 现在调仓日会把未选中股票显式置零
- `backtest_timing_audit.csv` 会检查信号日、成本日、开始收益日和活跃持仓是否匹配

### 6. 绩效报告

已经实现：

- 年化收益
- 年化波动率
- Sharpe
- 最大回撤
- Calmar
- 换手率
- 成本汇总
- SPY 基准
- 股票池等权买入并持有基准
- 持仓贡献检查

### 7. 稳健性检查

已经实现：

- 年度表现
- 固定样本内 / 样本外
- 成本敏感性
- 动量窗口敏感性
- 滚动样本外验证

滚动样本外验证逻辑：

- 每个测试年使用过去 3 年作为训练期
- 在训练期里从 `10, 20, 40, 60` 日动量窗口中选择 Sharpe 最高的参数
- 用训练期选出的参数测试下一整年

输出：

- `results/reports/rolling_validation.csv`
- `results/reports/rolling_validation_candidates.csv`

### 8. 风险暴露分析（阶段 14，已完成）

已经实现（代码在 `src/quant_factor/exposure.py`）：

- 给 100 只股票池打上 GICS 行业标签（`data/universe/us_large_cap_100.csv` 新增 `sector` 列）
- 行业暴露表：各行业平均权重 + 相对等权股票池的主动偏离 `active_tilt`
- 持仓集中度表：有效持仓数、Top-N 收益贡献占比
- 行业收益归因表：收益按行业拆解
- 行业暴露随时间变化图

输出：

- `results/reports/holding_industry_exposure.csv`
- `results/reports/holding_symbol_concentration.csv`
- `results/reports/sector_performance_attribution.csv`
- `results/figures/sector_exposure.png`

核心结论：完整样本里 IT 行业超配 +6.5%（最大偏离），贡献约 40% 毛收益；
2022 年策略失效时 IT 反而低配 -5.1%。说明策略收益很大程度来自 IT/成长行业暴露，
而不是 momentum 选股 alpha。详见 `docs/current_issues.md` 问题 5。

### 9. 行业中性化对照实验（阶段 15，已完成）

代码在 `src/quant_factor/neutralization.py` 和 `backtest.select_sector_neutral`。

做法：每个行业强制等于等权基准权重、只在行业内部按动量选股，把"超配科技"这个 beta 剥掉，
和原策略并排对照（原策略 / 行业中性 / SPY / 等权股票池）。

输出：

- `results/reports/sector_neutral_comparison.csv`
- `results/reports/sector_neutral_exposure.csv`（验证中性版 tilt 全为 0）
- `results/figures/sector_neutral_comparison.png`

核心结论：中性版样本外（2022-2023）Sharpe 从原策略的 0.001 提升到 0.394，收益 +11.6%，
同时跑赢 SPY 和等权股票池；样本内（科技牛市）反而略差。说明原策略样本外崩盘主要来自
行业择时（追涨 IT 撞上 2022），而非选股无效。收益不是纯 beta，但行业择时是负贡献。
详见 `docs/current_issues.md` 问题 5 的阶段 15 结果。

### 10. 行业中性版的滚动样本外验证（阶段 16，已完成）

代码：`neutralization.build_rolling_neutral_comparison`，以及 `robustness.build_rolling_validation`
新增的 `sector_neutral` / `sector_map` 开关。输出 `results/reports/rolling_neutral_comparison.csv`。

做法：用现有滚动框架逐年对比原策略 vs 行业中性版（每个测试年在训练期选动量窗口）。

核心结论：中性版每年的 Sharpe 都不差于原版（2021: 2.19>1.93；2022: ≈打平；2023: 2.01>0.91），
跑赢等权池从 1/3 年提升到 2/3 年，跑赢 SPY 从 2/3 提升到 3/3。说明阶段 15 的样本外改善是
稳定的、不是单窗口偶然。但 2022 仍是双双亏损年，策略没做到全面碾压等权池。

结论：行业中性可作为往后的默认 baseline。详见 `docs/stage_reports/stage16_rolling_neutral.md`。

### 11. 因子诊断（阶段 17，已完成）

代码：`src/quant_factor/diagnostics.py`。多 horizon IC（1/5/21 天）+ 因子相关性矩阵。
输出 `results/reports/factor_ic_by_horizon.csv`、`factor_correlation.csv`。

核心结论（剧情反转）：`momentum` 在所有 horizon 都是负 IC（21 天 -0.041），20 天属短期反转区间，
买赢家在截面上略微亏本；`momentum` 与 `ma_deviation` 相关 0.83（冗余）；`volatility` 与其它因子
独立、21 天 IC 正，是最好的分散化苗子。所有 IR ≤ 0.20，弱信号。

这解释了"策略跑输等权池"的最底层原因：核心选股信号在截面上是负贡献，全靠股票池上涨的 beta 撑住。
详见 `docs/stage_reports/stage17_factor_diagnostics.md`。

### 12. 多因子组合（阶段 18，已完成）

代码：`src/quant_factor/multi_factor.py`。按阶段 17 诊断搭方向对齐的综合分
（-momentum + reversal + volatility，剔除 ma_deviation），综合分作为新列塞进行业中性回测。
输出 `multi_factor_comparison.csv`、`multi_factor_yearly.csv`。

核心结论：多因子中性版样本外（2022-2023）第一次同时跑赢 SPY 和等权股票池
（Sharpe 0.490 > 单因子 0.394 > 等权 0.304），2022 从 -13.9% 改善到 -10.5%。
但完整样本回撤更大、Sharpe 与单因子打平、仍略低于等权池。符合弱因子改善有限的预期。
详见 `docs/stage_reports/stage18_multi_factor.md`。

### 13. 严格版滚动验证（阶段 19，已完成）

代码：`multi_factor.derive_factor_signs` + `build_rolling_multi_factor`。堵住阶段 18 的符号泄漏——
每个测试年只用自己的训练期推导因子符号（IC 正 +1、负 -1），再搭综合分、只读测试年表现。
输出 `rolling_multi_factor_comparison.csv`。

核心结论：因子方向非常稳定（三个不重叠训练期推出的符号分毫不差：momentum -1、reversal +1、
volatility +1）；堵住符号泄漏后多因子优势仍在，3/3 窗口跑赢等权池、3/3 不差于单因子，连 2022
也是四者中亏得最少的。含金量高于阶段 18 的单窗口结果。但漏点②（因子选择仍用全样本）还在，
只有 3 个重叠窗口，2022 仍亏，最终干净检验需真新数据。详见 `docs/stage_reports/stage19_strict_rolling_multi_factor.md`。

### 14. 文档

已有文档：

- `docs/development_log.md`：完整开发记录
- `docs/phase2_expanded_universe.md`：第二阶段股票池扩大和机器学习门槛
- `docs/current_issues.md`：当前问题与风险清单
- `docs/reproducibility_checklist.md`：复现检查清单
- `docs/project_summary.md`：项目总结

注意：

- `docs/量化项目分步指南.md` 是最早的本地指南，只应保留本地，不要提交到公开仓库。

## 当前关键结果

当前研究版使用 100 只美股，时间区间为 2018-01-01 到 2023-12-31。

完整样本：

| series | total_return | annualized_return | sharpe_ratio | max_drawdown |
|---|---:|---:|---:|---:|
| strategy | 1.1966 | 0.1404 | 0.7167 | -0.3003 |
| SPY | 0.9554 | 0.1185 | 0.6519 | -0.3372 |
| equal_weight_universe | 1.4780 | 0.1636 | 0.8148 | -0.3267 |

固定样本内 / 样本外：

| sample | total_return | annualized_return | sharpe_ratio | max_drawdown |
|---|---:|---:|---:|---:|
| 2018-2021 in-sample | 1.2759 | 0.2283 | 1.0169 | -0.3003 |
| 2022-2023 out-of-sample | -0.0349 | -0.0177 | 0.0011 | -0.2919 |

滚动样本外：

| test_year | selected_momentum_window | test_total_return | test_sharpe_ratio | beat_spy | beat_equal_weight |
|---:|---:|---:|---:|---|---|
| 2021 | 60 | 0.4057 | 1.9321 | True | True |
| 2022 | 20 | -0.1810 | -0.8004 | True | False |
| 2023 | 60 | 0.1474 | 0.9113 | False | False |

## 当前发现的问题

完整问题清单见：

```text
docs/current_issues.md
```

核心问题如下。

### 1. 策略跑输等权股票池

100 只股票池下，策略小幅跑赢 SPY，但跑输当前股票池等权买入并持有。这说明收益可能主要来自股票池本身，而不是因子选股。

### 2. 固定样本外基本失效

2022-2023 样本外总收益为负，Sharpe 接近 0。策略存在过拟合风险，或者至少存在明显市场环境依赖。

### 3. 滚动样本外不稳定

2021 年表现好，2022 年只略跑赢 SPY，2023 年跑输 SPY 和等权股票池。训练期选出来的参数不能稳定迁移到测试期。

### 4. 股票池仍有幸存者偏差

当前 100 只股票是手动整理的大盘股。它不包含退市、被并购、长期衰退或历史上掉出指数的股票。

### 5. 缺少行业、市值和风格中性化

当前策略可能隐含偏向科技、成长或大市值股票。还不能确认收益来自 momentum 因子本身。

### 6. 当前因子较基础

当前主策略只用 `momentum`。其他因子虽然已计算，但还没有形成真正的多因子组合。

### 7. 成交模型仍然简化

当前使用日频 close-to-close 近似，没有建模真实盘口冲击、成交量容量、融资成本等。

### 8. 暂时不适合把机器学习作为主线

因为样本外不稳定、股票池有偏差、风险暴露未拆解。如果现在直接上机器学习，很可能只是更复杂的过拟合。

## 下一步建议

阶段 14（风险暴露分析）、阶段 15（行业中性化对照）、阶段 16（中性版滚动验证）都已完成。
当前最新结论：行业中性是真实、稳健的风险调整改进（逐年 Sharpe 都不差于原版），可定为默认 baseline；
但策略仍有坏年份（2022），也没做到全面碾压等权股票池。

### 推荐下一步：阶段 20，堵漏点② + 初步风控

阶段 19 严格版已完成（符号窗口内重推，多因子优势扛住了）。剩下的方向：

- **进一步堵漏点②**：因子的"选择"（用哪几个、剔谁）目前仍用全样本诊断。可在每个训练窗口内
  重新做因子筛选（相关性 + IC 门槛），让"选哪些因子"也不偷看测试年。
- **初步风控**：多因子回撤偏大（-0.387），尝试单票权重上限 / 波动率目标 / 最大回撤控制，
  看能否保住收益的同时压回撤。每次都要保留 SPY 和等权池对比、跑固定 + 滚动样本外。
- **真新数据检验**：把策略锁死，用研究期之外的数据（如 2024+）做最终、彻底干净的检验。
- 在这些稳定后，才进入最基础的机器学习：因子作为特征，让模型学组合权重（替代当前手工等权），
  但要用同样的窗口内纪律检验。

### 第二优先级：其他风险控制

可以尝试：

- 行业权重上限（比完全中性更温和的半中性，作为阶段 15 的补充对照）
- 单票权重上限
- 波动率目标
- 最大回撤控制

注意：

- 每次新增控制后，都必须保留 SPY 和等权股票池对比
- 必须继续跑固定样本外和滚动样本外

### 第三优先级：股票池改进

方向：

- 扩展到 300-500 只美股
- 接入 S&P 500 当前成分股
- 如果能获取数据，再进一步做历史成分股

### 暂缓事项

暂时不要优先做：

- 复杂机器学习模型
- 大量堆新因子
- 只为了提高回测收益而反复调参

这些事情应该放在风险暴露和样本问题处理之后。

## 常用命令

安装依赖：

```bash
uv python install 3.11
uv venv --python 3.11
source .venv/bin/activate
uv pip install -r requirements-dev.txt
```

运行测试：

```bash
uv run pytest -q
```

运行 ruff：

```bash
uv run ruff check .
```

小样本 smoke run：

```bash
uv run python -m quant_factor.pipeline --limit 3
```

完整 pipeline：

```bash
uv run python -m quant_factor.pipeline
```

只跑稳健性和滚动验证：

```bash
uv run python -m quant_factor.robustness
```

查看 Git 状态：

```bash
git status --short
```

## 交接注意事项

- 当前研究版目录是 `quant_research_project`，不要误改 `quant_interview_project`。
- `quant_interview_project` 是已经分离出去的第一阶段展示版，README 已经去掉了“面试项目”痕迹。
- 原始指南文件 `docs/量化项目分步指南.md` 不应上传公开仓库。
- `data/raw/`、`data/processed/`、`results/reports/`、`results/figures/` 是运行产物，通常不提交。
- 如果改策略，一定同步更新 `docs/development_log.md` 和 `docs/current_issues.md`。
- 当前最重要的原则仍然是：不要只追求更高回测收益，要优先解释策略为什么有效、什么时候失效。
