# 报告链路词汇表（ADR-0007）

| 术语 | 定义 |
|---|---|
| WeekDatum | 单教师单周的内存数据单元：排课/应到/实到/缺课/新增/缺课名单；种子脚本的生成起点，不落库 |
| 周报 stats | 落在 `reports.stats` 的周粒度事实：`schedules/expected_attendance/attended/leave/attendance_rate/absent_students/new_students/expected_lessons/consumed_lessons/achievement_rate` |
| Rollup（聚合） | 把 N 篇周报 stats 求和并按总量重算比率，得到季度/年度 stats；出勤率与达标率禁止对百分比取平均 |
| 热窗口 | 最近 K 周（默认 3）：写真实 `Schedule/Attendance` 明细，供日报与本周统计联调 |
| 冷窗口 | 热窗口之外的周：无明细，只读 `Report.stats`；期间预览 auto 回退到聚合 |
| 季度总结 | 读对应时间范围已发布周报聚合 + 文本提炼；落 1 行 `quarterly` |
| 年度总结 | 只读季度总结聚合 + 文本提炼；落 1 行 `yearly`，不直接读周；`current_students` 取期末值 |
| 周归属键 | 周属于哪个季度/月份，以 `week_start` 落点为准，与 `list_published_weeklies` 的 SQL 过滤一致 |
| source 参数 | 期间统计接口的口径开关：`auto`（默认，有明细重算否则聚合）、`raw`（只重算）、`rollup`（只聚合） |
| 种子幂等 | `seed_report_year.py` 按 `(type, teacher, period)` upsert；重复跑同参数只更新；`--reset` 先删该年旧报告与演示排课 |
