import uuid

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.prompt import PromptScope, PromptTemplate


def list_visible(
    db: Session, user_id: uuid.UUID, *, is_admin: bool = False
) -> list[PromptTemplate]:
    """当前用户可见模板。

    普通用户：system + published + 本人 personal（账号隔离）；
    管理员：额外可见全部 personal（便于管理/发布优秀模板）。
    """
    conditions = [
        (PromptTemplate.scope == PromptScope.SYSTEM.value)
        | (PromptTemplate.scope == PromptScope.PUBLISHED.value)
    ]
    if is_admin:
        conditions.append(PromptTemplate.scope == PromptScope.PERSONAL.value)
    else:
        conditions.append(
            (PromptTemplate.scope == PromptScope.PERSONAL.value)
            & (PromptTemplate.owner_id == user_id)
        )
    stmt = (
        select(PromptTemplate)
        .where(or_(*conditions))
        .order_by(
            PromptTemplate.scope.desc(),
            PromptTemplate.created_at.desc(),
        )
    )
    return list(db.scalars(stmt).unique().all())


def get(db: Session, template_id: uuid.UUID) -> PromptTemplate | None:
    return db.get(PromptTemplate, template_id)


def get_default_system(db: Session) -> PromptTemplate | None:
    """系统默认模板（优先「通用鼓励型」，其次任意 system 模板）。"""
    stmt = (
        select(PromptTemplate)
        .where(PromptTemplate.scope == PromptScope.SYSTEM.value)
        .order_by(PromptTemplate.created_at.asc())
        .limit(1)
    )
    return db.scalars(stmt).first()


def create(
    db: Session,
    *,
    name: str,
    content: str,
    scope: PromptScope,
    owner_id: uuid.UUID | None,
) -> PromptTemplate:
    t = PromptTemplate(
        name=name,
        content=content,
        scope=scope.value,
        owner_id=owner_id,
        created_by=owner_id,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def update(
    db: Session, t: PromptTemplate, *, name: str | None, content: str | None
) -> PromptTemplate:
    if name is not None:
        t.name = name
    if content is not None:
        t.content = content
    db.commit()
    db.refresh(t)
    return t


def set_scope(db: Session, t: PromptTemplate, scope: PromptScope) -> PromptTemplate:
    t.scope = scope.value
    db.commit()
    db.refresh(t)
    return t


def delete(db: Session, t: PromptTemplate) -> None:
    db.delete(t)
    db.commit()


# 系统自带提示词预设（可编辑、不可删除）：报告四类 + 课后反馈各一套。
# 命名用【报告/反馈】前缀，便于前端分组展示；幂等 ensure，已改名/改内容的不覆盖。
SYSTEM_PRESETS: tuple[tuple[str, str], ...] = (
    (
        "【报告·日报】简洁条理型",
        "你是少儿编程培训机构的教务助手，请根据今日排课/考勤素材撰写工作日报草稿。"
        "文风简洁、条理清晰：work 概括今日工作，courses 描述授课情况与学员表现，"
        "problems 如有问题则说明并给处理方式（没有就写无），plan 给出明日计划。"
        "用户已写内容优先保留原意并润色，不要编造未发生的事实。",
    ),
    (
        "【报告·周报】数据驱动型",
        "你是少儿编程培训机构的教务助手，请根据本周统计指标与日报摘要撰写工作周报草稿。"
        "文风简洁、数据驱动：summary 概括本周工作并引用关键数字，highlights 突出亮点，"
        "problems 客观指出问题并给改进建议，next_plan 给下周计划。"
        "用户已写内容优先保留原意并润色，不要编造未发生的事实。",
    ),
    (
        "【报告·季度总结】复盘 growth 型",
        "你是少儿编程培训机构的教务助手，请根据季度统计与已发布周报摘要撰写季度总结草稿。"
        "结构完整：总结回顾季度目标达成，亮点用数据支撑，问题复盘到根因，"
        "下季度计划具体可执行。用户已写内容优先保留原意并润色扩写。",
    ),
    (
        "【报告·年度总结】战略回顾型",
        "你是少儿编程培训机构的教务助手，请根据各季度总结摘要撰写年度总结草稿。"
        "格局适度拔高但不空话：全年目标达成回顾、各季度亮点串联、关键问题与改进、"
        "来年规划分条列出。用户已写内容优先保留原意并润色扩写。",
    ),
    (
        "【反馈·课后】鼓励成长型",
        "请为学员撰写课后反馈：先肯定本堂课的具体表现（引用课题与课堂细节），"
        "再指出 1-2 个可改进点并给练习建议，最后布置作业并鼓励坚持。"
        "语气亲切、面向家长，100-300 字。如果已提供现有反馈，请在其基础上润色完善。",
    ),
)


def ensure_system_presets(db: Session) -> int:
    """幂等补齐系统预设模板（按名称去重），返回新增数量。"""
    existing = {
        name
        for name in db.scalars(
            select(PromptTemplate.name).where(PromptTemplate.scope == PromptScope.SYSTEM.value)
        ).all()
    }
    added = 0
    for name, content in SYSTEM_PRESETS:
        if name in existing:
            continue
        db.add(PromptTemplate(name=name, content=content, scope=PromptScope.SYSTEM.value))
        added += 1
    if added:
        db.commit()
    return added
