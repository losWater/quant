# 阶段 16 报告：行业中性版的滚动样本外验证

- 日期：2026-07-08
- 状态：已完成，已提交
- 相关代码：`src/quant_factor/neutralization.py`、`src/quant_factor/robustness.py`
- 相关文档：`docs/development_log.md`（阶段 16）、`docs/current_issues.md`（问题 3）

---

## 1. 这一阶段要回答的问题

阶段 15 发现行业中性版在样本外（2022–2023）明显更强，但那只是**一个固定的 2 年窗口**。
一个窗口的好结果可能只是运气。阶段 16 要回答：

> 把行业中性版放进滚动样本外框架、逐年重复检验，它相对原策略的优势是**稳定存在**的，还是**单窗口偶然**？

## 2. 做法

复用现有滚动验证框架（`build_rolling_validation`）：每个测试年用过去 3 年做训练期、
在训练期里选 Sharpe 最高的动量窗口，再用选出的参数测试下一整年。
给这套框架加一个 `sector_neutral` 开关，原策略和行业中性版各跑一遍，逐年对比。
两条线唯一的差别就是"选股时是否做行业中性"。

## 3. 代码改动

| 文件 | 改动 |
|---|---|
| `src/quant_factor/robustness.py` | `_run_configured_backtest` 和 `build_rolling_validation` 增加 `sector_neutral` / `sector_map` 参数 |
| `src/quant_factor/neutralization.py` | 新增 `build_rolling_neutral_comparison`（跑两遍滚动、合并对比表） |
| `src/quant_factor/pipeline.py` | 新增 `rolling_neutral` 步骤 |
| `tests/test_neutralization.py` | 新增合成数据测试，验证滚动框架接受 `sector_neutral` |
| `tests/test_pipeline.py` | 同步更新 |

产出文件：`results/reports/rolling_neutral_comparison.csv`

质量门槛：全套 66 个测试通过，`ruff check .` 无警告。原有 `build_robustness_report`
未传 `sector_neutral`，默认 False，行为完全不变，无回归。

## 4. 结果

| 测试年 | 选中窗口(原/中性) | 原策略收益 | 中性版收益 | 原策略 Sharpe | 中性版 Sharpe | 原赢等权池 | 中性赢等权池 |
|---:|---|---:|---:|---:|---:|---|---|
| 2021 | 60 / 60 | 0.4057 | 0.3860 | 1.93 | 2.19 | 是 | 是 |
| 2022 | 20 / 60 | -0.1810 | -0.1712 | -0.80 | -0.81 | 否 | 否 |
| 2023 | 60 / 20 | 0.1474 | 0.2967 | 0.91 | 2.01 | 否 | 是 |

## 5. 结论

- **改善是稳定的，不是单窗口偶然**：中性版每一年的 Sharpe 都不差于原版
  （2021 更高、2022 基本打平、2023 明显更高）。
- **战胜基准的战绩变好**：跑赢等权池从 1/3 年提升到 2/3 年，跑赢 SPY 从 2/3 提升到 3/3。
- **2023 是最有力的证据**：原策略同时跑输 SPY 和等权池，中性版把两个基准都反超了。
- **但不是万能药**：2022 仍是双双亏损年，中性化没把它救成正的；策略还没做到全面碾压等权池。

综合阶段 14–16：行业中性是**真实、稳健的风险调整改进**，足以定为往后的默认 baseline，
但策略仍有明显坏年份，收益的稳定性还不够，离"可上 ML"仍有距离。

## 6. 风险与保留

- 只有 3 个测试年，样本仍然有限。
- 每年训练期选出的动量窗口会变（中性版和原版某些年选的窗口不同），这本身也是一种不稳定信号。
- 2022 的失败说明：即使剥掉行业择时，动量在急速下跌 + 风格剧烈轮动的年份仍然脆弱。

## 7. 下一步（阶段 17）

把行业中性设为默认 baseline，然后转向**多因子**：先查 4 个因子的相关性，
再尝试最简单的多因子等权打分（z-score 相加），看能否在中性框架上进一步稳定样本外、
尤其改善 2022 这样的坏年份。仍不直接上 ML。

## 8. 复现命令

```bash
uv run pytest -q
uv run ruff check .
uv run python -m quant_factor.pipeline --steps rolling_neutral
```
