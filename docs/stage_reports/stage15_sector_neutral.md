# 阶段 15 报告：行业中性化对照实验

- 日期：2026-07-08
- 状态：已完成，已提交
- 相关代码：`src/quant_factor/neutralization.py`、`src/quant_factor/backtest.py`
- 相关文档：`docs/development_log.md`（阶段 15）、`docs/current_issues.md`（问题 5）

---

## 1. 这一阶段要回答的问题

阶段 14 已经证实：策略长期超配信息技术（IT）行业 +6.5%，IT 贡献了约 40% 的毛收益。
于是留下一个关键疑问——

> 如果把"超配科技"这个行业赌注（beta）剥掉，策略相对等权股票池的表现，是变干净了、还是直接消失了？

阶段 15 就是做这个**控制变量实验**来回答它。

## 2. 做法

**行业中性选股**：不再全市场选动量前 20%，而是

- 在每个行业**内部**各选动量前 20%；
- 每个行业的总权重，强制等于等权股票池里该行业的占比（如 IT 固定配 21%）。

这样组合的行业配置被锁死在基准上，所有行业的主动偏离(active_tilt)压到 0，
策略只剩"在每个行业里挑谁"的能力。

**对照口径**：两次回测只差 `sector_neutral` 一个开关，其余假设（成本、调仓频率、动量窗口）完全相同，
并排比较**原策略 / 行业中性策略 / SPY / 等权股票池**，同时报告完整样本、样本内、样本外三个窗口。

## 3. 代码改动

| 文件 | 改动 |
|---|---|
| `src/quant_factor/backtest.py` | 新增 `select_sector_neutral`；`run_long_only_backtest` 增加 `sector_neutral` / `sector_map` 参数 |
| `src/quant_factor/neutralization.py` | 新建：跑双策略对照、四方绩效表、中性化验证、净值对比图 |
| `src/quant_factor/exposure.py` | `_prepare_holdings` 提升为公开 `prepare_holdings`，供本阶段复用 |
| `src/quant_factor/pipeline.py` | 新增 `neutralization` 步骤 |
| `tests/test_neutralization.py` | 新建，4 个测试 |
| `tests/test_pipeline.py`、`tests/test_exposure.py` | 同步更新 |

产出文件：

- `results/reports/sector_neutral_comparison.csv`
- `results/reports/sector_neutral_exposure.csv`
- `results/figures/sector_neutral_comparison.png`

质量门槛：全套 65 个测试通过，`ruff check .` 无警告。

## 4. 结果

**中性化生效验证**：中性版所有行业 `active_tilt` 精确为 0，IT 从超配 +6.5% 压到 0。

**四方对照（Sharpe / 总收益）**：

| 窗口 | 原策略 | 行业中性 | SPY | 等权股票池 |
|---|---|---|---|---|
| 完整样本 | 0.717 / 1.197 | **0.769 / 1.274** | 0.652 / 0.955 | 0.815 / 1.478 |
| 样本内 2018–2021 | **1.017 / 1.276** | 0.929 / 1.038 | 0.872 / 0.894 | 1.050 / 1.283 |
| 样本外 2022–2023 | 0.001 / -0.035 | **0.394 / +0.116** | 0.180 / 0.032 | 0.304 / 0.085 |

## 5. 结论

- **原策略样本外崩盘的主因是行业择时，不是选股无效**：动量追涨把仓位堆到 IT，正好撞上 2022 崩盘，
  再滞后割在底部。一旦用行业中性禁掉这个择时，样本外 Sharpe 从 0.001 救到 0.394。
- **收益不是纯 beta**：剥掉行业赌注后，剩下的"行业内动量选股"在样本外反而跑赢 SPY 和等权池，
  暗示存在微弱的行业内 alpha。
- **样本内中性化吃亏**：科技牛市里超配 IT 是顺风，去掉它自然变差——这本身也印证了原收益里行业 beta 的比重。
- 这个结果**修正了阶段 14 偏悲观的初步判断**（"可能是纯 beta"），给出了更精确的画像：
  **行业择时是负贡献，行业内选股可能是微弱正贡献**。

## 6. 风险与保留

样本外的漂亮结果**只来自 2022–2023 一个窗口**，不能据此下定论——很可能只是这两年恰好适合分散化动量。
必须用更多样本外窗口去证伪。

## 7. 下一步（阶段 16）

把行业中性版接入现有滚动样本外框架（`robustness.build_rolling_validation`，给它传 `sector_neutral=True`），
在多个滚动窗口里检验样本外的改善是否稳健。只有多窗口都成立，才敢把"行业中性"当成可靠改进。

## 8. 复现命令

```bash
uv run pytest -q
uv run ruff check .
uv run python -m quant_factor.neutralization
```
