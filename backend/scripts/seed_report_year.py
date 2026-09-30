"""年度演示数据种子：稠密周报/季报/年报 + 稀疏原始明细。

链路（与线上口径一致）：
    WeekDatum(内存, 确定性随机) -> weekly Report -> quarterly Report -> yearly Report
    - 周报 stats/文本：由该教师本周内存数据生成（排课/应到/实到/缺课/出勤/课时/新增/缺课名单）
    - 季度 stats：聚合对应时间范围的已发布周报（app.crud.report.rollup_weekly_to_period）
    - 年度 stats：聚合 4 篇季度总结（app.crud.report.rollup_period_to_annual），不直接读周
    - 冷周：不写 Schedule/Attendance 明细，只读 Report.stats（期间预览 auto 回退到聚合）
    - 热窗口（默认最近 3 周）：写真实 Class/Schedule/Attendance 明细，供日报/本周统计联调

量级：单教师 52 周报 + 4 季 + 1 年 = 57 行报告 + 热窗口约 schedules*per_class 考勤行，
全量明细（52周×5节×8人=2080行/教师）的零头。幂等：按 (type, teacher, period) upsert，
重复跑同一参数只更新不新增；热窗口已存在排课的周跳过。

运行（cwd=backend）：
    uv run python scripts/seed_report_year.py --username teacher01 --year 2026 --seed 42
    uv run python scripts/seed_report_year.py --username teacher01 --year 2026 --seed 42 --dry-run
    uv run python scripts/seed_report_year.py --username teacher01 --year 2026 --seed 42 --reset
"""

from __future__ import annotations

import argparse
import random
import sys
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from types import SimpleNamespace
from typing import Any

sys.path.insert(0, ".")

from sqlalchemy import delete, func, select  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.crud import attendance as attendance_crud  # noqa: E402
from app.crud import classroom as classroom_crud  # noqa: E402
from app.crud import report as report_crud  # noqa: E402
from app.crud import schedule as schedule_crud  # noqa: E402
from app.crud import student as student_crud  # noqa: E402
from app.crud import user as user_crud  # noqa: E402
from app.models.enrollment import Class as ClassModel  # noqa: E402
from app.models.enrollment import Student, StudentClass, StudentStatus  # noqa: E402
from app.models.report import Report, ReportStatus, ReportType  # noqa: E402
from app.models.schedule import Attendance, AttendanceStatus, Schedule, ScheduleStatus  # noqa: E402

CN_NUM = ["一", "二", "三", "四"]
SURNAME = "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张"
GIVEN = "子涵阳悦晨睿泽楷瑞轩诺一帆思远浩宇欣怡雨泽俊豪天翊"


# ------------------------------------------------------------------ 内存周数据
@dataclass
class WeekDatum:
    week_start: date
    week_end: date
    schedules: int
    expected: int
    attended: int
    leave: int
    new_students: int
    absent_names: list[str]

    @property
    def attendance_rate(self) -> float:
        return round(self.attended / self.expected, 4) if self.expected else 0.0

    @property
    def expected_lessons(self) -> int:
        return self.expected * 2

    @property
    def consumed_lessons(self) -> int:
        return self.attended * 2

    @property
    def achievement_rate(self) -> float:
        e = self.expected_lessons
        return round(self.consumed_lessons / e, 4) if e else 0.0

    def to_stats(self) -> dict[str, Any]:
        return {
            "schedules": self.schedules,
            "expected_attendance": self.expected,
            "attended": self.attended,
            "leave": self.leave,
            "attendance_rate": self.attendance_rate,
            "absent_students": self.absent_names,
            "new_students": self.new_students,
            "expected_lessons": self.expected_lessons,
            "consumed_lessons": self.consumed_lessons,
            "achievement_rate": self.achievement_rate,
        }


def _pick_name(rng: random.Random) -> str:
    return f"{rng.choice(SURNAME)}{rng.choice(GIVEN)}{rng.choice(GIVEN)}"


def gen_year_weeks(
    year: int,
    seed: int,
    base_load: int = 5,
    per_class: int = 8,
    growth: float = 0.15,
) -> list[WeekDatum]:
    """生成全年 52 周内存数据：成长趋势 + 寒暑假波峰 + 噪声 + 2 个异常周。"""
    rng = random.Random(f"{year}-{seed}-weeks")
    jan1 = date(year, 1, 1)
    monday0 = jan1 - timedelta(days=jan1.weekday())
    bad_weeks = set(rng.sample(range(52), k=2))
    pool = [_pick_name(rng) for _ in range(40)]
    out: list[WeekDatum] = []
    for i in range(52):
        ws = monday0 + timedelta(weeks=i)
        we = ws + timedelta(days=6)
        m = (ws + timedelta(days=3)).month  # 按周四归属月份
        seasonal = 1.25 if m in (1, 2, 7, 8) else (0.85 if m in (6, 12) else 1.0)
        trend = 1.0 + growth * (i / 51)
        noise = rng.uniform(0.85, 1.15)
        schedules = max(2, round(base_load * seasonal * trend * noise))
        expected = schedules * per_class
        leave_rate = rng.uniform(0.04, 0.10)
        if i in bad_weeks:  # 流感周 / 调课周：出勤明显掉一截
            leave_rate = rng.uniform(0.22, 0.30)
        leave = min(expected, round(expected * leave_rate))
        attended = expected - leave
        new_students = rng.choices([0, 0, 0, 1, 1, 2, 3], k=1)[0]
        if m in (3, 9):  # 春秋招生季
            new_students += 1
        absent_names = (
            rng.sample(pool, k=min(5, leave, len(pool))) if leave > 0 else []
        )
        out.append(
            WeekDatum(
                week_start=ws,
                week_end=we,
                schedules=schedules,
                expected=expected,
                attended=attended,
                leave=leave,
                new_students=new_students,
                absent_names=absent_names,
            )
        )
    return out


# ------------------------------------------------------------------ 文本模板（确定性，不调 LLM）
def weekly_content(d: WeekDatum) -> dict[str, str]:
    rate = d.attendance_rate * 100
    ach = d.achievement_rate * 100
    absent = "、".join(d.absent_names) if d.absent_names else "无"
    summary = (
        f"本周共排课 {d.schedules} 节，应到 {d.expected} 人次，"
        f"实到 {d.attended} 人次，缺课 {d.leave} 人次，出勤率 {rate:.1f}%；"
        f"应耗课时 {d.expected_lessons} 节，实耗 {d.consumed_lessons} 节，"
        f"达标率 {ach:.1f}%；新增学员 {d.new_students} 人。"
    )
    hi = []
    if d.achievement_rate >= 0.95:
        hi.append(f"出勤达标（{rate:.1f}%），课堂秩序稳定")
    if d.new_students:
        hi.append(f"新增学员 {d.new_students} 人，招生转化顺利")
    if d.schedules >= 6:
        hi.append(f"排课量饱满（{d.schedules} 节），教学节奏紧凑")
    highlights = "；".join(hi) or "常规教学周，各项指标平稳"
    if d.leave >= max(4, d.expected * 0.15):
        problems = f"缺课偏多（{d.leave} 人次：{absent}），需逐一跟进补课"
    elif d.leave:
        problems = f"个别缺课（{absent}），已安排补课"
    else:
        problems = "无，全员到课"
    next_plan = (
        f"按课表推进下周 {d.schedules} 节左右排课"
        + (f"；重点跟进缺课学员（{absent}）补课" if d.leave else "")
        + ("；做好新增学员的入学衔接" if d.new_students else "")
    )
    return {
        "summary": summary,
        "highlights": highlights,
        "problems": problems,
        "next_plan": next_plan,
    }


def quarterly_content(year: int, q: int, weeks: list[WeekDatum], stats: dict) -> dict[str, str]:
    best = max(weeks, key=lambda w: (w.attendance_rate, w.week_start.toordinal()))
    worst = min(weeks, key=lambda w: (w.attendance_rate, w.week_start.toordinal()))
    label = f"{year}年{CN_NUM[q - 1]}季度"
    summary = (
        f"{label}共 {len(weeks)} 周，排课 {stats['schedules']} 节，"
        f"上课 {stats['attended']} 人次，缺课 {stats['leave']} 人次，"
        f"出勤率 {stats['attendance_rate'] * 100:.1f}%；"
        f"应耗课时 {stats['expected_lessons']} 节，实耗 {stats['consumed_lessons']} 节，"
        f"达标率 {stats['achievement_rate'] * 100:.1f}%；"
        f"新增学员 {stats['new_students']} 人。"
    )
    highlights = (
        f"最佳单周为 {best.week_start.month}月{best.week_start.day} 日当周"
        f"（出勤率 {best.attendance_rate * 100:.1f}%）；"
        f"本季度新增 {stats['new_students']} 人，规模稳步扩大"
    )
    absent = "、".join(stats["absent_students"]) if stats["absent_students"] else "无"
    problems = (
        f"{worst.week_start.month}月{worst.week_start.day} 日当周出勤偏低"
        f"（{worst.attendance_rate * 100:.1f}%），需加强考勤跟进；"
        f"高频缺课学员（{absent}）需重点补课"
        if stats["leave"]
        else "本季度全勤情况良好"
    )
    next_plan = "下季度保持排课节奏，重点提升出勤率至 95% 以上并跟进缺课学员补课"
    return {
        "summary": summary,
        "highlights": highlights,
        "problems": problems,
        "next_plan": next_plan,
        "stats_notes": (
            f"课时达标率 {stats['achievement_rate'] * 100:.1f}%"
            f"（应耗 {stats['expected_lessons']} / 实耗 {stats['consumed_lessons']}），"
            f"教学交付稳定"
        ),
    }


def yearly_content(year: int, qstats: list[dict], stats: dict) -> dict[str, str]:
    best_q = max(range(4), key=lambda i: qstats[i]["achievement_rate"])
    summary = (
        f"{year}年共排课 {stats['schedules']} 节，上课 {stats['attended']} 人次，"
        f"缺课 {stats['leave']} 人次，出勤率 {stats['attendance_rate'] * 100:.1f}%；"
        f"应耗课时 {stats['expected_lessons']} 节，实耗 {stats['consumed_lessons']} 节，"
        f"达标率 {stats['achievement_rate'] * 100:.1f}%；"
        f"全年新增学员 {stats['new_students']} 人，沉淀周报 {stats['weekly_count']} 篇。"
    )
    highlights = (
        f"第{CN_NUM[best_q]}季度交付最佳"
        f"（达标率 {qstats[best_q]['achievement_rate'] * 100:.1f}%）；"
        f"全年新增 {stats['new_students']} 人，寒暑假为招生与排课双高峰"
    )
    absent = "、".join(stats["absent_students"]) if stats["absent_students"] else "无"
    problems = (
        f"全年缺课 {stats['leave']} 人次，高频缺课（{absent}）需在新一年建档跟进；"
        f"期末月份（6/12月）排课量自然回落，需提前做续费沟通"
    )
    next_plan = "新一年保持排课节奏，目标出勤率 95%+、达标率 95%+，重点抓续费与新增转化"
    return {
        "summary": summary,
        "highlights": highlights,
        "problems": problems,
        "next_plan": next_plan,
        "stats_notes": (
            f"全年课时达标率 {stats['achievement_rate'] * 100:.1f}%"
            f"（应耗 {stats['expected_lessons']} / 实耗 {stats['consumed_lessons']}），"
            f"四个季度交付均衡"
        ),
    }


# ------------------------------------------------------------------ 落库
def _dt(d: date, end: bool = False) -> datetime:
    return datetime.combine(d, time.max if end else time.min)


def upsert_published(
    db,
    *,
    type: str,
    teacher_id,
    start: date,
    end: date,
    title: str,
    content: dict,
    stats: dict,
    dry_run: bool,
    plan: list[str],
) -> None:
    if dry_run:
        plan.append(f"  [dry] {type} {start}~{end} {title}")
        return
    rep = report_crud.upsert(
        db,
        type=type,
        teacher_id=teacher_id,
        period_start=_dt(start),
        period_end=_dt(end, end=True),
        title=title,
        content=content,
        stats=stats,
    )
    if rep.status != ReportStatus.PUBLISHED.value:
        report_crud.publish(db, rep)


def ensure_hot_window(
    db,
    *,
    teacher,
    hot: list[WeekDatum],
    per_class: int,
    dry_run: bool,
    plan: list[str],
) -> None:
    """热窗口真实明细：1 个演示班 + 每周 N 节排课 + 全量考勤标记。"""
    if dry_run:
        n_att = sum(w.schedules * per_class for w in hot)
        plan.append(
            f"  [dry] hot-window {len(hot)} 周："
            f"{sum(w.schedules for w in hot)} 节排课 / 约 {n_att} 条考勤"
        )
        return
    cls = db.scalar(
        select(ClassModel).where(
            ClassModel.teacher_id == teacher.id,
            ClassModel.name == f"演示班-{teacher.username}",
            ClassModel.status == StudentStatus.ACTIVE.value,
        )
    )
    if cls is None:
        cls = classroom_crud.create(
            db,
            name=f"演示班-{teacher.username}",
            subject="Python",
            teacher_id=teacher.id,
            start_date=date.today().replace(month=1, day=1),
        )
    students = list(
        db.scalars(
            select(Student)
            .join(StudentClass, Student.id == StudentClass.student_id)
            .where(
                Student.status == StudentStatus.ACTIVE.value,
                StudentClass.class_id == cls.id,
            )
            .order_by(Student.created_at)
        )
    )
    need = per_class - len(students)
    for i in range(max(0, need)):
        students.append(
            student_crud.create(
                db,
                name=f"演示学员{i + 1:02d}",
                phone=None,
                campus=teacher.campus,
                lesson_balance=20,
                parent_user_id=None,
                student_user_id=None,
                class_ids=[cls.id],
            )
        )
    students = students[:per_class]
    sids = [s.id for s in students]

    for w in hot:
        exists = db.scalar(
            select(func.count(Schedule.id)).where(
                Schedule.teacher_id == teacher.id,
                Schedule.start_time >= _dt(w.week_start),
                Schedule.start_time <= _dt(w.week_end, end=True),
                Schedule.status != ScheduleStatus.CANCELLED.value,
            )
        )
        if exists:
            plan.append(f"  skip 热窗口 {w.week_start}（已有 {exists} 节排课）")
            continue
        leave_total = w.schedules * per_class - w.attended  # 本周应标记请假总数
        marked_leave = 0
        for n in range(w.schedules):
            day = w.week_start + timedelta(days=(n * 2) % 5)  # 摊到周一~周五
            start = datetime.combine(day, time(18, 0))
            s = schedule_crud.create(
                db,
                class_id=cls.id,
                teacher_id=teacher.id,
                start_time=start,
                end_time=start + timedelta(hours=2),
            )
            s.status = ScheduleStatus.COMPLETED.value
            rows = attendance_crud.ensure_for_students(db, s.id, sids)
            for sid in sids:
                if marked_leave < leave_total:
                    rows[sid].status = AttendanceStatus.LEAVE.value
                    marked_leave += 1
                else:
                    rows[sid].status = AttendanceStatus.ATTENDED.value
        db.commit()
        plan.append(f"  ok 热窗口 {w.week_start}~{w.week_end}：{w.schedules} 节已落明细")


def main() -> None:
    ap = argparse.ArgumentParser(description="年度报告演示数据种子（轻量：57行报告+热窗口明细）")
    ap.add_argument("--username", required=True, help="教师用户名")
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--base-load", type=int, default=5, help="每周基准排课节数")
    ap.add_argument("--per-class", type=int, default=8, help="每节课学员数")
    ap.add_argument("--growth", type=float, default=0.15, help="年内成长率")
    ap.add_argument("--hot-weeks", type=int, default=3, help="热窗口周数（写真实明细）")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--reset", action="store_true", help="先删除该教师该年周/季/年报再重建")
    args = ap.parse_args()

    weeks = gen_year_weeks(args.year, args.seed, args.base_load, args.per_class, args.growth)
    hot = weeks[-args.hot_weeks :] if args.hot_weeks else []
    cold = weeks[: len(weeks) - len(hot)]

    db = SessionLocal()
    try:
        # 模型注册：确保 Attendance/Class 等表映射已加载（report/schedule/enrollment/user）
        import app.models as _models  # noqa: F401
        teacher = user_crud.get_by_username(db, args.username)
        if teacher is None:
            raise SystemExit(f"用户不存在：{args.username}")
        tname = teacher.name or teacher.username
        plan: list[str] = [
            f"teacher={args.username} year={args.year} seed={args.seed}",
            f"52 周报 + 4 季报 + 1 年报 = 57 行；热窗口 {len(hot)} 周写明细，冷窗口 {len(cold)} 周只读聚合",
            f"全年内存总量：排课 {sum(w.schedules for w in weeks)} 节 / "
            f"应到 {sum(w.expected for w in weeks)} 人次 / "
            f"实到 {sum(w.attended for w in weeks)} 人次 / "
            f"新增 {sum(w.new_students for w in weeks)} 人",
        ]

        if args.reset and not args.dry_run:
            n = 0
            for r in db.scalars(
                select(Report).where(
                    Report.teacher_id == teacher.id,
                    Report.type.in_(
                        [
                            ReportType.WEEKLY.value,
                            ReportType.QUARTERLY.value,
                            ReportType.YEARLY.value,
                        ]
                    ),
                    Report.period_start >= datetime(args.year, 1, 1),
                    Report.period_start < datetime(args.year + 1, 1, 1),
                )
            ):
                db.delete(r)
                n += 1
            # 热窗口排课（演示班）一并清理，避免重复
            for s in db.scalars(
                select(Schedule).where(
                    Schedule.teacher_id == teacher.id,
                    Schedule.start_time >= datetime(args.year, 1, 1),
                    Schedule.start_time < datetime(args.year + 1, 1, 1),
                )
            ):
                db.execute(delete(Attendance).where(Attendance.schedule_id == s.id))
                db.delete(s)
            db.commit()
            plan.append(f"  reset：已删除 {n} 篇旧报告 + 全年演示排课")

        # 1) 52 篇周报
        for w in weeks:
            s, e = w.week_start, w.week_end
            title = (
                f"{s.month}月{s.day}日~{e.month}月{e.day}日 周报 {tname}"
                if s.month != e.month
                else f"{s.month}月{s.day}日~{e.day}日 周报 {tname}"
            )
            upsert_published(
                db,
                type=ReportType.WEEKLY.value,
                teacher_id=teacher.id,
                start=s,
                end=e,
                title=title,
                content=weekly_content(w),
                stats=w.to_stats(),
                dry_run=args.dry_run,
                plan=plan,
            )

        # 2) 4 篇季度总结（周归属键 = week_start 落点，与 list_published_weeklies 的
        #    SQL 过滤一致：qs <= week_start <= qe；跨年首周自动归入上一年，不计入本年 Q1）
        qstats: list[dict] = []
        quarters: dict[int, list[WeekDatum]] = {1: [], 2: [], 3: [], 4: []}
        bounds = {
            q: (
                date(args.year, (q - 1) * 3 + 1, 1),
                (date(args.year, q * 3 + 1, 1) - timedelta(days=1) if q < 4 else date(args.year, 12, 31)),
            )
            for q in (1, 2, 3, 4)
        }
        for w in weeks:
            for q, (qs_, qe_) in bounds.items():
                if qs_ <= w.week_start <= qe_:
                    quarters[q].append(w)
                    break
        for q in (1, 2, 3, 4):
            ws = quarters[q]
            stats = report_crud.rollup_weekly_to_period(
                [SimpleNamespace(stats=w.to_stats()) for w in ws],  # type: ignore[list-item]
                current_students=args.per_class,
            )
            qstats.append(stats)
            qs, qe = bounds[q]
            upsert_published(
                db,
                type=ReportType.QUARTERLY.value,
                teacher_id=teacher.id,
                start=qs,
                end=qe,
                title=f"{args.year}年{CN_NUM[q - 1]}季度 季度总结 {tname}",
                content=quarterly_content(args.year, q, ws, stats),
                stats=stats,
                dry_run=args.dry_run,
                plan=plan,
            )

        # 3) 1 篇年度总结（只读 4 篇季度，不直接读周）
        ystats = report_crud.rollup_period_to_annual(
            [SimpleNamespace(stats=s) for s in qstats],  # type: ignore[list-item]
            current_students=args.per_class,
        )
        upsert_published(
            db,
            type=ReportType.YEARLY.value,
            teacher_id=teacher.id,
            start=date(args.year, 1, 1),
            end=date(args.year, 12, 31),
            title=f"{args.year}年 年度总结 {tname}",
            content=yearly_content(args.year, qstats, ystats),
            stats=ystats,
            dry_run=args.dry_run,
            plan=plan,
        )

        # 4) 热窗口真实明细
        ensure_hot_window(
            db, teacher=teacher, hot=hot, per_class=args.per_class,
            dry_run=args.dry_run, plan=plan,
        )
        print("\n".join(plan))
    finally:
        db.close()


if __name__ == "__main__":
    main()
