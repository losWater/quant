# 阶段 17 报告：因子诊断（多 horizon IC + 相关性）

- 日期：2026-07-08
- 状态：已完成，已提交
- 相关代码：`src/quant_factor/diagnostics.py`、`tests/test_diagnostics.py`
- 相关文档：`docs/development_log.md`（阶段 17）、`docs/current_issues.md`（问题 6）

---

## 1. 这一阶段要回答的问题

多因子组合之前必须先体检，否则组合注定搭错。现有 IC 只在 1 天尺度算，而策略是月度调仓；
且 4 个因子不能无脑相加，得先知道各自方向和是否冗余。所以本阶段回答：

- 每个因子在**贴近月度策略的尺度**上，真实的方向（符号）和强度是多少？
- 4 个因子之间有没有冗余（高相关）？谁能提供独立信息？

## 2. 做法

- **多 horizon IC**：复用 `evaluation` 的 IC 计算，把 forward_days 换成 1 / 5 / 21 天分别跑，
  同一套 RankIC 口径，直接可比。
- **因子相关性**：每天在截面上算一次 Spearman 相关矩阵，再对所有交易日取平均
  （不是把所有 (日期, 股票) 混在一起，避免时间序列和截面混淆）。

## 3. 代码改动

| 文件 | 改动 |
|---|---|
| `src/quant_factor/diagnostics.py` | 新建：`build_multi_horizon_ic`、`build_factor_correlation`、`build_diagnostics_report` |
| `config.yaml` | 新增 `diagnostics` 段（ic_horizons、correlation_method） |
| `src/quant_factor/pipeline.py` | 新增 `diagnostics` 步骤（evaluation 之后、backtest 之前） |
| `tests/test_diagnostics.py` | 新建，4 个测试；同步更新 `test_pipeline.py` |

产出文件：`results/reports/factor_ic_by_horizon.csv`、`results/reports/factor_correlation.csv`

质量门槛：全套 69 个测试通过，`ruff check .` 无警告。

## 4. 结果

### 多 horizon IC（RankIC，正=因子越大未来收益越高）

| 因子 | IC@1天 | IC@5天 | IC@21天 | IR@21天 |
|---|---:|---:|---:|---:|
| momentum | -0.008 | -0.015 | **-0.041** | -0.20 |
| ma_deviation | -0.009 | -0.014 | -0.035 | -0.17 |
| reversal | +0.009 | +0.014 | +0.017 | +0.08 |
| volatility | +0.0001 | +0.019 | **+0.031** | +0.13 |

### 因子相关性（平均每日截面 Spearman）

| | momentum | reversal | volatility | ma_deviation |
|---|---:|---:|---:|---:|
| momentum | 1.00 | -0.44 | -0.04 | **0.83** |
| reversal | -0.44 | 1.00 | 0.00 | -0.71 |
| volatility | -0.04 | 0.00 | 1.00 | -0.02 |
| ma_deviation | 0.83 | -0.71 | -0.02 | 1.00 |

## 5. 结论

1. **IC 绝对值随 horizon 变大**：这些是中期信号，1 天尺度会把强度看没——印证了"必须匹配策略尺度"。
2. **剧情反转：`momentum` 在所有 horizon 都是负 IC（21 天 -0.041）**。20 天尺度属于"短期反转"区间，
   不是动量区间；买近期赢家在截面上是略微亏本的选择。`reversal` 是它的镜像，弱正。
3. **`momentum` 与 `ma_deviation` 相关 0.83，高度冗余**，一起用等于重复下注。
4. **`volatility` 与其它因子几乎不相关（≈0），21 天 IC 正且随 horizon 增强**，是最好的分散化苗子。

### 与阶段 14-16 的闭环

这个发现给"策略 6 年 +120% 却跑输等权池 +148%"提供了最底层的解释：
**策略的核心选股信号（20 天动量）在截面上是负的**，选股每一步都在轻微减分；
整个股票池上涨（beta）让它保持正收益，但选股本身拖后腿。这和阶段 14（收益来自 IT 行业 beta）、
阶段 15-16（剥掉行业 beta 后弱选股撑不住 2022）完全自洽。

## 6. 对阶段 18（多因子组合）的直接指导

- **剔除 `ma_deviation`**：和 momentum 冗余。
- **`momentum` 要么翻转符号当反转用（短期反转有学术依据，不是纯数据挖掘），要么直接改用 `reversal`。**
- **保留 `volatility`**：正 IC、且与其它因子独立，是主要的分散化来源。
- **诚实预期**：所有因子的 IR 都 ≤ 0.20，属于弱信号，多因子组合能带来的改善大概率有限。
  阶段 18 的核心问题是：这些弱因子的组合，能否在行业中性框架下比单因子更稳、尤其改善 2022。

## 7. 复现命令

```bash
uv run pytest -q
uv run ruff check .
uv run python -m quant_factor.diagnostics
```
