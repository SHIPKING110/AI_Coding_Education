"""智能助手「数据库查询工具」：只读 SQL 工具，支持多步推理取数。

设计见 docs/adr/adr-0003-assistant-sql-tool.md。安全第一：
- **只读**：连接级只读事务（`default_transaction_read_only`）+ 语句超时；杜绝任何写操作；
- **白名单**：仅允许查询已登记的业务表；非白名单表直接拒绝；
- **列脱敏**：`password_hash` / `share_token` 等敏感列禁止查询；
- **行数 / 超时**：强制 LIMIT（默认 50 行）与 `statement_timeout`，防止拖垮库；
- **教师作用域**：教师查询带 `teacher_id` 的表时，必须显式带上自己的 `teacher_id` 过滤，
  否则拒绝并提示——避免越权看到他人数据。

三个工具：sql_list_tables（有哪些表）、sql_describe_table（表结构）、sql_query（执行 SELECT）。
配合规划层多轮循环，即可完成「列表→看结构→写 SQL→执行→再修正」的多步取数。
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.models.user import Role, User

# 允许查询的表 → 一句话用途（同时作为给模型的目录说明，保持精简省 token）
# 注意：枚举列在数据库里存的是**大写英文名**（如 ATTENDED / COMPLETED），写 SQL 过滤时须用大写。
TABLE_CATALOG: dict[str, str] = {
    "schedules": "排课（id, class_id, teacher_id, start_time, end_time, status: SCHEDULED/COMPLETED/CANCELLED）",
    "attendances": "考勤（id, schedule_id, student_id, status: ATTENDED/LEAVE/UNMARKED）",
    "classes": "班级（id, name, subject, teacher_id, start_date, status: ACTIVE/STOPPED/ARCHIVED）",
    "students": (
        "学员（id, name, campus, lesson_balance, "
        "status: ACTIVE/STOPPED/ARCHIVED, follow_up_status: PENDING/RENEWED/STOPPED）"
    ),
    "student_classes": "学员-班级关联（student_id, class_id）",
    "reports": (
        "报告（id, teacher_id, type: DAILY/WEEKLY/QUARTERLY/YEARLY, "
        "title, period_start, period_end, status: DRAFT/PUBLISHED）"
    ),
    "evaluations": "学员评估（id, student_id, teacher_id, period_start, period_end, title, status: DRAFT/PUBLISHED）",
    "class_ppts": "班级家长会 PPT（id, class_id, teacher_id, period_start, period_end, title）",
    "feedbacks": "课后反馈（id, student_id, schedule_id, teacher_id, ...）",
    "lesson_records": (
        "课时流水（id, student_id, record_type: RECHARGE/CONSUME/ADJUST/REFUND, "
        "delta, balance_after, created_at）"
    ),
    "lesson_packages": "课时包（id, name, price, total_lessons, status: ACTIVE/INACTIVE）",
    "orders": "订单（id, student_id, package_id, amount, status: PENDING/PAID/CONFIRMED/CANCELLED/REFUNDED, paid_at）",
    "users": "用户（id, role: ADMIN/STAFF/TEACHER/PARENT/STUDENT, username, name, campus；不含密码）",
}

# 含教师归属（直接或经班级关联）、教师只能看自己数据的表
SCOPED_TABLES = {
    "schedules", "classes", "reports", "evaluations", "class_ppts", "feedbacks",
    "students", "attendances", "student_classes", "lesson_records", "orders",
}

# 敏感列：任何查询都禁止出现
SENSITIVE_COLUMNS = {"password_hash", "share_token", "ai_draft", "phone"}

# 禁止语句关键字（只读护栏，双保险）
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|copy|vacuum|"
    r"reindex|refresh|comment|call|do|merge|into\s+outfile|pg_sleep|pg_read_file|"
    r"dblink|lo_import|lo_export|set\s+role|set\s+session)\b",
    re.IGNORECASE,
)
_TABLE_REF = re.compile(r"\b(?:from|join)\s+([a-zA-Z_][a-zA-Z0-9_]*)", re.IGNORECASE)

DEFAULT_MAX_ROWS = 50
STATEMENT_TIMEOUT_MS = 5000


@lru_cache
def _readonly_engine() -> Engine:
    """专用只读引擎（按 DATABASE_URL 构造并缓存）。"""
    return _build_readonly_engine(get_settings().DATABASE_URL)


def _build_readonly_engine(url: str) -> Engine:
    """构造只读引擎：连接建立即置为只读事务，且禁止长查询。测试可复用本函数。"""
    engine = create_engine(url, poolclass=NullPool, future=True)

    @event.listens_for(engine, "connect")
    def _set_readonly(dbapi_conn, _record):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
        cur.execute(f"SET statement_timeout = {STATEMENT_TIMEOUT_MS}")
        cur.close()

    return engine


def _normalize(sql: str) -> str:
    # 去注释，压空白，便于校验与匹配
    sql = re.sub(r"/\*.*?\*/", " ", sql or "", flags=re.DOTALL)
    sql = re.sub(r"--[^\n]*", " ", sql)
    return sql.strip()


def validate_sql(sql: str, user: User) -> tuple[bool, str]:
    """校验只读与作用域；返回 (是否通过, 拒绝原因)。"""
    norm = _normalize(sql)
    if not norm:
        return False, "SQL 为空"
    low = norm.lower()
    if not (low.startswith("select") or low.startswith("with")):
        return False, "只允许 SELECT / WITH 查询"
    # 多语句（内部出现分号）一律拒绝，防注入/写操作
    body = norm.rstrip().rstrip(";")
    if ";" in body:
        return False, "只允许单条查询语句（不允许分号分隔的多语句）"
    if _FORBIDDEN.search(norm):
        return False, "查询包含被禁止的关键字（只读系统，禁止写/危险操作）"
    for col in SENSITIVE_COLUMNS:
        if col in low:
            return False, f"禁止查询敏感列 {col}"
    tables = {t.lower() for t in _TABLE_REF.findall(low)}
    unknown = tables - set(TABLE_CATALOG)
    if unknown:
        return False, f"存在未授权/不存在的表：{', '.join(sorted(unknown))}；可用表见 sql_list_tables"
    if user.role == Role.TEACHER and (tables & SCOPED_TABLES):
        if str(user.id) not in low:
            return False, (
                f"表 {', '.join(sorted(tables & SCOPED_TABLES))} 含教师归属，"
                f"教师查询必须显式加过滤（如 teacher_id = '{user.id}'，或经 classes/student_classes 关联过滤）"
            )
    return True, ""


def _ensure_limit(sql: str, max_rows: int) -> str:
    norm = sql.rstrip().rstrip(";").strip()
    if re.search(r"\blimit\b", norm, re.IGNORECASE):
        return norm
    return f"{norm} LIMIT {max_rows}"


def run_query(db: Session, user: User, sql: str, *, max_rows: int = DEFAULT_MAX_ROWS) -> dict:
    """执行只读查询，返回 {columns, rows, row_count, truncated}。异常与拒绝都从结果返回。"""
    ok, reason = validate_sql(sql, user)
    if not ok:
        return {"错误": reason}
    safe = _ensure_limit(sql, max_rows)
    try:
        with _readonly_engine().connect() as conn:
            result = conn.execute(text(safe))
            cols = list(result.keys())
            rows = result.fetchmany(max_rows)
    except Exception as e:  # noqa: BLE001 —— 语法/超时/权限错误都回给模型，让它改写
        return {"错误": f"查询执行失败：{str(e).splitlines()[0][:200]}"}
    return {
        "columns": cols,
        "rows": [[_cell(v) for v in row] for row in rows],
        "row_count": len(rows),
        "truncated": len(rows) >= max_rows,
    }


def _cell(value: Any) -> Any:
    if value is None or isinstance(value, (int, float, bool, str)):
        return value
    return str(value)


def list_tables(user: User) -> dict:
    """列出可查询的表与用途，并告知当前用户的作用域 id。"""
    out: dict = {
        "可查表": [f"{t}：{desc}" for t, desc in TABLE_CATALOG.items()],
        "提示": "枚举列（status/type/role 等）在库中存大写英文名，过滤时用大写，例如 status = 'ATTENDED'",
    }
    if user.role == Role.TEACHER:
        tid = str(user.id)
        out["作用域"] = f"你只能查询含教师归属的表，且必须显式加过滤：teacher_id = '{tid}'"
        out["示例"] = [
            f"select id, name from classes where teacher_id = '{tid}'",
            (
                "select s.name, s.lesson_balance from students s "
                "join student_classes sc on sc.student_id = s.id "
                "join classes c on c.id = sc.class_id "
                f"where c.teacher_id = '{tid}'"
            ),
        ]
    return out


def describe_table(db: Session, user: User, table: str) -> dict:
    """返回表的列/类型（用于写 SQL 前了解结构）。"""
    name = (table or "").strip().lower()
    if name not in TABLE_CATALOG:
        return {"错误": f"表 {table} 不在可查清单；可用表见 sql_list_tables"}
    from app.core.database import Base

    tbl = Base.metadata.tables.get(name)
    if tbl is None:
        return {"错误": f"未找到表结构：{name}"}
    cols = []
    for c in tbl.columns:
        if c.name in SENSITIVE_COLUMNS:
            continue
        cols.append({"列": c.name, "类型": str(c.type), "主键": bool(c.primary_key)})
    return {"表": name, "用途": TABLE_CATALOG[name], "列": cols}


__all__ = ["run_query", "list_tables", "describe_table", "validate_sql", "TABLE_CATALOG"]
