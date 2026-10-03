"""存量库轻量自迁移（无 alembic 时期的过渡方案，幂等）：

- 新表：campuses / subjects / revenue_ledger / finance_settings（create_all 已覆盖新建库）
- 存量表补列/改型：students.lesson_balance、lesson_records.delta/balance_after 改数值型；
  lesson_packages 加 subject_id/tag/sale_start/sale_end/published_at；
  orders 加 expires_at；teacher_permissions 加 settings_manage/finance_view 及 nav_* 导航可见键。
"""

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


def _cols(engine: Engine, table: str) -> set[str]:
    with engine.connect() as conn:
        return {c["name"] for c in inspect(conn).get_columns(table)}


def _col_type(engine: Engine, table: str, col: str) -> str:
    with engine.connect() as conn:
        for c in inspect(conn).get_columns(table):
            if c["name"] == col:
                return str(c["type"]).upper()
    return ""


def ensure_business_schema(engine: Engine) -> None:
    from app.core.database import Base

    # 新表（已存在的跳过）
    Base.metadata.create_all(
        engine,
        tables=[
            Base.metadata.tables["campuses"],
            Base.metadata.tables["subjects"],
            Base.metadata.tables["revenue_ledger"],
            Base.metadata.tables["finance_settings"],
            Base.metadata.tables["teacher_levels"],
            Base.metadata.tables["commission_rules"],
            Base.metadata.tables["payroll_entries"],
            Base.metadata.tables["invitations"],
        ],
        checkfirst=True,
    )

    stmts: list[str] = []

    def addcol(table: str, ddl: str, col: str) -> None:
        if col not in _cols(engine, table):
            stmts.append(f"ALTER TABLE {table} ADD COLUMN {ddl}")

    # 课时包扩展
    addcol("lesson_packages", "subject_id UUID REFERENCES subjects(id)", "subject_id")
    addcol("lesson_packages", "tag VARCHAR(16) NOT NULL DEFAULT 'regular'", "tag")
    addcol("lesson_packages", "sale_start TIMESTAMPTZ", "sale_start")
    addcol("lesson_packages", "sale_end TIMESTAMPTZ", "sale_end")
    addcol("lesson_packages", "published_at TIMESTAMPTZ", "published_at")
    # 订单过期
    addcol("orders", "expires_at TIMESTAMPTZ", "expires_at")
    # 透支上限（欠费继续上课）
    addcol("finance_settings", "overdraft_max NUMERIC(6,1) DEFAULT 10", "overdraft_max")
    # 欠费消耗标记（计入创收但挂应收）
    addcol("revenue_ledger", "is_overdraft BOOLEAN DEFAULT FALSE", "is_overdraft")
    # 排课班级可空（体验课可排教师空余时段不绑班级）
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE schedules ALTER COLUMN class_id DROP NOT NULL"))
    # 课时流水计价（人工调整带单价入账本）
    addcol("lesson_records", "unit_price NUMERIC(10,4)", "unit_price")
    addcol("lesson_records", "amount NUMERIC(10,2)", "amount")
    # 体验域：学员体验标记/生源 + 邀约记录 + 排课/考勤体验标记
    addcol("students", "trial_status VARCHAR(16) DEFAULT 'none'", "trial_status")
    addcol("students", "source VARCHAR(16) DEFAULT 'normal'", "source")
    addcol("students", "referrer VARCHAR(64)", "referrer")
    addcol("schedules", "is_trial BOOLEAN DEFAULT FALSE", "is_trial")
    addcol("attendances", "is_trial BOOLEAN DEFAULT FALSE", "is_trial")
    # 职务基本工资 + 教师级别/基本工资
    addcol("job_titles", "base_salary NUMERIC(10,2) NOT NULL DEFAULT 0", "base_salary")
    addcol("users", "teacher_level_id VARCHAR(64)", "teacher_level_id")
    addcol("users", "teacher_level_name VARCHAR(64)", "teacher_level_name")
    addcol("users", "base_salary NUMERIC(10,2)", "base_salary")
    # 教师权限新键
    addcol(
        "teacher_permissions",
        "settings_manage BOOLEAN NOT NULL DEFAULT FALSE",
        "settings_manage",
    )
    addcol(
        "teacher_permissions",
        "finance_view BOOLEAN NOT NULL DEFAULT FALSE",
        "finance_view",
    )
    # 教师端导航可见开关（默认全开，保持现有行为）
    for _nav_col in (
        "nav_students",
        "nav_invitations",
        "nav_classes",
        "nav_teachers",
        "nav_schedules",
        "nav_packages",
        "nav_feedbacks",
        "nav_reports",
        "nav_evaluations",
        "nav_agents",
        "nav_assignments",
    ):
        addcol(
            "teacher_permissions",
            f"{_nav_col} BOOLEAN NOT NULL DEFAULT TRUE",
            _nav_col,
        )
    # 敏感模块导航（默认关闭，需管理员显式授予）
    for _nav_col in ("nav_finance", "nav_settings"):
        addcol(
            "teacher_permissions",
            f"{_nav_col} BOOLEAN NOT NULL DEFAULT FALSE",
            _nav_col,
        )
    # 整数余额 → 数值（支持半课时），仅当还是 INTEGER 时执行
    if _col_type(engine, "students", "lesson_balance").startswith("INTEGER"):
        stmts.append(
            "ALTER TABLE students ALTER COLUMN lesson_balance "
            "TYPE NUMERIC(10,1) USING lesson_balance::numeric"
        )
    if _col_type(engine, "lesson_records", "delta").startswith("INTEGER"):
        stmts.append(
            "ALTER TABLE lesson_records ALTER COLUMN delta "
            "TYPE NUMERIC(10,1) USING delta::numeric"
        )
    if _col_type(engine, "lesson_records", "balance_after").startswith("INTEGER"):
        stmts.append(
            "ALTER TABLE lesson_records ALTER COLUMN balance_after "
            "TYPE NUMERIC(10,1) USING balance_after::numeric"
        )

    if stmts:
        with engine.begin() as conn:
            for sql in stmts:
                conn.execute(text(sql))

    # 默认教师级别 + 提成规则种子（幂等）
    with engine.begin() as conn:
        if "teacher_levels" in inspect(conn).get_table_names():
            n = conn.execute(text("SELECT COUNT(*) FROM teacher_levels")).scalar() or 0
            if n == 0:
                conn.execute(
                    text(
                        "INSERT INTO teacher_levels (id, name, ratio, active, sort) VALUES "
                        "(:a,'P1',0.10,true,1),(:b,'P2',0.15,true,2),(:c,'P3',0.20,true,3)"
                    ),
                    {"a": str(__import__("uuid").uuid4()), "b": str(__import__("uuid").uuid4()), "c": str(__import__("uuid").uuid4())},
                )
        if "commission_rules" in inspect(conn).get_table_names():
            n = conn.execute(text("SELECT COUNT(*) FROM commission_rules")).scalar() or 0
            if n == 0:
                conn.execute(
                    text(
                        "INSERT INTO commission_rules (id, key, label, amount, unit, active) VALUES "
                        "(:a,'invite','电话意向人头奖',5,'元/人',true),"
                        "(:b,'trial','邀约到场体验课提成',30,'元/人',true),"
                        "(:c,'convert','体验课转化报名提成',100,'元/单',true),"
                        "(:d,'renew','续费提成',80,'元/单',true),"
                        "(:e,'refer','口碑转介绍奖',50,'元/人',true),"
                        "(:f,'trial_lesson','体验课课时提成',20,'元/人',true)"
                    ),
                    {k: str(__import__("uuid").uuid4()) for k in "abcdef"},
                )
