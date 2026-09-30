"""周报 -> 期间/月度 rollup 纯单元测试（不依赖数据库）。

覆盖 ADR-0007 的核心口径：
- 季度聚合 = 对应时间范围已发布周报 stats 求和，出勤率/达标率按总量重算
- 年度聚合 = 只读 4 篇季度总结，不直接读周
- 月度折线 = 按周报 period_start 落点月份归集
"""

from datetime import datetime
from types import SimpleNamespace

from app.crud import report as report_crud


def _weekly(
    start: str,
    *,
    schedules=5,
    expected=40,
    attended=36,
    leave=4,
    new=1,
    absent=None,
):
    return SimpleNamespace(
        period_start=datetime.fromisoformat(start),
        stats={
            "schedules": schedules,
            "expected_attendance": expected,
            "attended": attended,
            "leave": leave,
            "attendance_rate": round(attended / expected, 4) if expected else 0.0,
            "absent_students": absent or [],
            "new_students": new,
            "expected_lessons": expected * 2,
            "consumed_lessons": attended * 2,
            "achievement_rate": round(attended / expected, 4) if expected else 0.0,
        },
    )


def test_rollup_weekly_to_period_sums_and_recomputes_rates():
    weeks = [
        _weekly("2026-01-05T00:00:00", attended=36, leave=4, absent=["张三"]),
        _weekly("2026-01-12T00:00:00", attended=32, leave=8, absent=["张三", "李四"]),
    ]
    stats = report_crud.rollup_weekly_to_period(weeks, current_students=8)
    assert stats["schedules"] == 10
    assert stats["attended"] == 68
    assert stats["leave"] == 12
    # 出勤率按总量重算：68 / 80 = 0.85，而非两周平均值
    assert stats["attendance_rate"] == 0.85
    assert stats["expected_lessons"] == 160
    assert stats["consumed_lessons"] == 136
    assert stats["achievement_rate"] == 0.85
    assert stats["weekly_count"] == 2
    assert stats["new_students"] == 2
    assert stats["current_students"] == 8
    # 缺课名单按频次 Top：张三 2 次排第一
    assert stats["absent_students"][0] == "张三"


def test_rollup_weekly_to_period_empty():
    stats = report_crud.rollup_weekly_to_period([], current_students=0)
    assert stats["schedules"] == 0
    assert stats["attendance_rate"] == 0.0
    assert stats["achievement_rate"] == 0.0
    assert stats["weekly_count"] == 0


def test_rollup_period_to_annual_reads_quarters_only():
    quarters = [
        SimpleNamespace(
            stats={
                "schedules": 60,
                "attended": 400,
                "leave": 40,
                "new_students": 10,
                "weekly_count": 13,
                "current_students": 8,
                "expected_lessons": 880,
                "consumed_lessons": 800,
                "absent_students": ["张三"],
            }
        ),
        SimpleNamespace(
            stats={
                "schedules": 65,
                "attended": 420,
                "leave": 30,
                "new_students": 12,
                "weekly_count": 13,
                "current_students": 10,
                "expected_lessons": 900,
                "consumed_lessons": 840,
                "absent_students": ["李四"],
            }
        ),
    ]
    stats = report_crud.rollup_period_to_annual(quarters, current_students=0)
    assert stats["schedules"] == 125
    assert stats["attended"] == 820
    assert stats["leave"] == 70
    # 出勤率按总量重算：820 / 890
    assert stats["attendance_rate"] == round(820 / 890, 4)
    assert stats["expected_lessons"] == 1780
    assert stats["consumed_lessons"] == 1640
    assert stats["weekly_count"] == 26
    assert stats["new_students"] == 22
    # current_students 取期末值（最后一篇季度），而非年内峰值
    assert stats["current_students"] == 10


def test_rollup_period_to_annual_terminal_not_peak():
    """退费场景：Q1 规模 12，Q4 回落到 8，年度应记期末 8 而非峰值 12。"""
    quarters = [
        SimpleNamespace(stats={"current_students": 12}),
        SimpleNamespace(stats={"current_students": 10}),
        SimpleNamespace(stats={"current_students": 9}),
        SimpleNamespace(stats={"current_students": 8}),
    ]
    stats = report_crud.rollup_period_to_annual(quarters, current_students=0)
    assert stats["current_students"] == 8


def test_rollup_period_to_annual_fallback_when_no_quarter_value():
    """季度缺 current_students 时回退到调用方传入值。"""
    quarters = [SimpleNamespace(stats={}), SimpleNamespace(stats={})]
    stats = report_crud.rollup_period_to_annual(quarters, current_students=6)
    assert stats["current_students"] == 6


def test_rollup_weekly_monthly_groups_by_start_month():
    weeks = [
        _weekly("2026-01-26T00:00:00", attended=36, leave=4, new=1),
        _weekly("2026-02-02T00:00:00", attended=32, leave=8, new=2),
    ]
    pts = report_crud.rollup_weekly_monthly(weeks)
    assert [p["month"] for p in pts] == ["2026-01", "2026-02"]
    assert pts[0]["consumed_lessons"] == 72
    assert pts[1]["attendance"] == 32
    assert pts[1]["new_students"] == 2


def test_prev_equal_window_quarter():
    s = datetime(2026, 7, 1)
    e = datetime(2026, 9, 30, 23, 59, 59)
    ps, pe = report_crud._prev_equal_window(s, e)
    assert (ps.year, ps.month) == (2026, 4)
    assert (pe.year, pe.month, pe.day) == (2026, 6, 30)
