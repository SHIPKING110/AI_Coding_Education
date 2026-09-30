# ADR-0007：报告链路数据源与轻量年度种子

日期：2026-09-19
状态：已接受

## 背景

教师端报告链路为 周报 → 季度总结 → 年度总结。全量造一年 `Schedule + Attendance`
明细非常庞大（单教师约 2080 考勤行；20 教师约 4 万考勤行 + 附属表 ≈ 6~10 万行），
SQLite 演示机写入慢，且季度/年度 AI 素材拼接会超时。

## 决策

1. **周报是唯一的事实来源入口**：周报 `stats` 由该教师本周数据生成
   （排课/应到/实到/缺课/出勤率/课时/新增/缺课名单），文本是对这份数据的解读。
2. **季度总结只读对应时间范围的已发布周报**：指标用
   `rollup_weekly_to_period` 聚合（求和 + 按总量重算出勤率/达标率），
   文本由周报 `summary/highlights/problems/next_plan` 提炼。季度不直接扫原始考勤。
3. **年度总结只读季度总结**：指标用 `rollup_period_to_annual` 聚合，
   不直接读 52 周。`current_students` 取期末值（最后一篇非零季度），
   无有效值时回退调用方传入值；`weekly_count` 累加。
4. **种子采用“稠密报告 + 稀疏明细”**：52 周报 + 4 季报 + 1 年报 = 57 行/教师；
   仅最近 K 周（默认 3）写真实 `Class/Schedule/Attendance` 明细（热窗口），
   其余 49 周冷窗口不写明细，只读 `Report.stats`。
5. **期间预览 auto 回退**：有已完成排课明细则重算（线上真实口径）；
   无明细但有已发布周报时回退到周报聚合，避免冷窗口显示全 0。
   月度折线与课时对比同样支持 `source=auto|raw|rollup`。
6. **种子确定性**：`random.Random(f"{year}-{seed}-weeks")` + 模板文本，不调 LLM，
   可重复、可 diff。刻意包含成长趋势（+15%）、寒暑假波峰（×1.25）、
   期末回落（×0.85）、2 个异常低出勤周，否则图表是直线、演示无效。

## 否决的备选

- 全量造一年明细：写入量大、AI 素材拼接超时，否决。
- 季度重算原始考勤：演示库冷窗口无明细会得全 0，且与“周报是事实入口”冲突，否决。
- 种子文本调 LLM 生成：不可重复、跑一次几分钟，否决；LLM 只在教师真实写报告时调。

## 2026-09-19 复核补记（grill-with-docs 第二遍）

1. 周归属键统一为 `week_start` 落点（与 `list_published_weeklies` 的 SQL 过滤
   `qs <= period_start <= qe` 一致）；种子此前用的“周四归属月”与 SQL 差 1 周边界，
   已改为季度自然日起止区间归集，跨年首周自动归入上一年。
2. 月度 rollup 允许 ±1 跨月周边界差异（整周归属 `period_start` 月 vs 线上自然月切分
   `_month_bounds`），“口径一致”仅指总量与字段结构，不含跨月周拆分。
3. 年度 `current_students` 由“取季度 max”改为期末值（Q4 优先），退费场景不再虚高。
4. 热窗口请假分布与周报 `absent_names` 名单已知不一致（总量一致即可联调），不修。

## 后果

- 新增 `backend/scripts/seed_report_year.py`（upsert 幂等，可 `--reset` 重建）。
- 新增 `app/crud/report.py`：`list_published_weeklies`、`rollup_weekly_to_period`、
  `rollup_period_to_annual`、`rollup_weekly_monthly`、
  `compute_period_comparison_from_weeklies`、`_prev_equal_window`（复用，原内联逻辑收敛到此）。
- `GET /reports/period-stats/{preview,monthly,comparison}` 新增 `source` 查询参数，
  默认 `auto`，前端无需改动（默认行为即回退）。
- 热窗口与冷窗口的周报 `stats` 口径一致（同为 周报 stats 结构），`compute_weekly_stats`
  重算热窗口时数值吻合（允许 ±请假分布差异，种子按周总量标记请假）。
