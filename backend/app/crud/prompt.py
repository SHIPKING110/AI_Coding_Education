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
    scene: str = "feedback",
) -> PromptTemplate:
    t = PromptTemplate(
        name=name,
        content=content,
        scope=scope.value,
        owner_id=owner_id,
        created_by=owner_id,
        scene=scene,
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


# 系统自带提示词预设（可编辑、不可删除）：报告四类 + 课后反馈 + 学员评估各一套。
# 命名用【报告/反馈/评估】前缀 + scene 字段双保险，便于前端按场景分组展示；
# 幂等 ensure，已改名/改内容的不覆盖。
# 占位说明：反馈类模板可用 {student_name} {class_name} {subject} {topic} {content}
# {performance} {homework} {evaluation}；报告/评估类由后端按类型拼接素材。
SYSTEM_PRESETS: tuple[tuple[str, str, str], ...] = (
    (
        "【报告·日报】简洁条理型",
        "report",
        "你是少儿编程培训机构的教务助手，正在帮教师撰写今日工作日报。"
        "写作要求：\n"
        "1. work：用 2-3 句话概括今日整体工作，先说结果再说过程；\n"
        "2. courses：分课程/班级简述授课情况，点名表现突出或需要关注的学员（引用课堂真实细节）；\n"
        "3. problems：如实记录今日遇到的问题及处理方式，没有则写「无」——绝不编造；\n"
        "4. plan：明日计划具体到班级与事项，可执行、可检查。\n"
        "文风简洁干练、条理清晰。用户已写内容优先保留原意并润色，不要编造未发生的事实。",
    ),
    (
        "【报告·周报】数据驱动型",
        "report",
        "你是少儿编程培训机构的教务助手，正在帮教师撰写本周工作周报。"
        "写作要求：\n"
        "1. summary：概括本周工作，用关键数字说话（排课节数、出勤率、反馈发送率等，数字必须来自素材）；\n"
        "2. highlights：2-3 个本周亮点，每个亮点都要有具体事例支撑；\n"
        "3. problems：客观指出 1-2 个问题，分析到根因（如出勤波动、续费预警学员），并给出改进动作；\n"
        "4. next_plan：下周计划分条列出，明确优先级。\n"
        "文风务实、数据驱动。用户已写内容优先保留原意并润色，不要编造未发生的事实。",
    ),
    (
        "【报告·季度总结】复盘成长型",
        "report",
        "你是少儿编程培训机构的教务助手，正在帮教师撰写季度工作总结。"
        "写作要求：\n"
        "1. 先回顾季度初目标，逐项说明达成情况（用数据支撑）；\n"
        "2. 亮点部分串联本季度周报中的关键事件，形成成长线；\n"
        "3. 问题复盘深入到根因（教学、运营、沟通任选），提出下季度可落地的改进；\n"
        "4. 下季度计划包含目标、重点动作、预期效果三部分。\n"
        "格局适度、避免空话。用户已写内容优先保留原意并润色扩写。",
    ),
    (
        "【报告·年度总结】战略回顾型",
        "report",
        "你是少儿编程培训机构的教务助手，正在帮教师撰写年度工作总结。"
        "写作要求：\n"
        "1. 全年目标达成回顾：分教学、招生、服务三条线，用关键数字锚定；\n"
        "2. 四个季度亮点串联成全年成长故事，点出转折点；\n"
        "3. 关键问题与改进：只写最重要的 2-3 个，每个配改进结果或下一年动作；\n"
        "4. 来年规划：目标 + 三大重点工作 + 所需支持，分条列出。\n"
        "站位全年、详略得当。用户已写内容优先保留原意并润色扩写。",
    ),
    (
        "【反馈·课后】鼓励成长型",
        "feedback",
        "请为学员撰写课后反馈（发给家长看，100-300 字）。写作要求：\n"
        "1. 开头肯定本堂课 1-2 个具体表现（必须引用课题与课堂细节，如独立完成了××任务、主动提问××）；\n"
        "2. 指出 1-2 个可改进点，每个都配一条可在家练习的具体建议；\n"
        "3. 结尾说明今日作业要求，并用一句话鼓励孩子坚持。\n"
        "语气亲切真诚、面向家长，绝不编造课堂上没发生的事。"
        "占位符：学员 {student_name}｜班级 {class_name}｜科目 {subject}｜"
        "课题 {topic}｜课程内容 {content}｜课堂表现 {performance}｜今日作业 {homework}。"
        "如果已提供现有反馈，请在其基础上润色完善而非重写。",
    ),
    (
        "【评估·季度】全面成长型",
        "evaluation",
        "你是少儿编程培训机构的资深教师，正在为学员撰写季度学习评估（给家长看）。"
        "写作要求：\n"
        "1. summary：一段话总述本季度整体成长，先讲最大变化；\n"
        "2. subjects：分科目评价，每个科目引用 1-2 个课堂真实细节，level 打分必须与文字描述一致；\n"
        "3. progress：2-4 条进步点，用「；」分隔，每条都看得见具体事例；\n"
        "4. to_improve：客观温和指出待提升项，用「；」分隔；\n"
        "5. suggestions：给家长的可操作建议（如每周练习××分钟、亲子复述课堂内容），用「；」分隔。\n"
        "语气亲切、有事实依据，突出孩子的成长，避免空话套话，绝不编造不存在的内容。",
    ),
    (
        "【评估·季度】问题导向型",
        "evaluation",
        "你是少儿编程培训机构的资深教师，正在为学员撰写季度学习评估（给家长看），"
        "本模板侧重定位问题、给出路径。写作要求：\n"
        "1. summary：先肯定进步，再点明本季度最关键的 1-2 个提升方向；\n"
        "2. subjects：分科目说明现状与差距，level 打分严格依据真实水平；\n"
        "3. progress：简述已有进步（用「；」分隔），为后文建议做铺垫；\n"
        "4. to_improve：聚焦到具体能力点（如循环逻辑理解、调试耐心），用「；」分隔；\n"
        "5. suggestions：每个待提升项配一条 2-4 周可验证的行动建议，用「；」分隔。\n"
        "坦诚但不打击信心，所有判断必须有课堂事实依据，绝不编造。",
    ),
)


def ensure_system_presets(db: Session) -> int:
    """幂等补齐系统预设模板（按名称去重），返回新增数量；顺带回填老数据的 scene。"""
    existing = {
        name
        for name in db.scalars(
            select(PromptTemplate.name).where(PromptTemplate.scope == PromptScope.SYSTEM.value)
        ).all()
    }
    added = 0
    for name, scene, content in SYSTEM_PRESETS:
        if name in existing:
            continue
        db.add(PromptTemplate(name=name, content=content, scope=PromptScope.SYSTEM.value, scene=scene))
        added += 1
    # 老数据回填：首版 3 模板无 scene，按名称前缀归位
    legacy = db.scalars(
        select(PromptTemplate).where(
            PromptTemplate.scope == PromptScope.SYSTEM.value,
            (PromptTemplate.scene.is_(None)) | (PromptTemplate.scene == ""),
        )
    ).all()
    for t in legacy:
        if t.name.startswith("【报告"):
            t.scene = "report"
        elif t.name.startswith("【评估"):
            t.scene = "evaluation"
        else:
            t.scene = "feedback"
    # 纠偏：历史版本曾把报告/评估预设误标为 feedback，按名称前缀强制归位
    mislabeled = db.scalars(
        select(PromptTemplate).where(PromptTemplate.scope == PromptScope.SYSTEM.value)
    ).all()
    for t in mislabeled:
        want = (
            "report"
            if t.name.startswith("【报告")
            else "evaluation"
            if t.name.startswith("【评估")
            else "feedback"
            if t.name.startswith("【反馈")
            else None
        )
        if want and t.scene != want:
            t.scene = want
    # 曾用名迁移：季度总结模板改名（内容已优化，老库同步改名避免重复出现两条）
    renamed = db.scalars(
        select(PromptTemplate).where(
            PromptTemplate.scope == PromptScope.SYSTEM.value,
            PromptTemplate.name == "【报告·季度总结】复盘 growth 型",
        )
    ).all()
    for t in renamed:
        t.name = "【报告·季度总结】复盘成长型"
    db.commit()
    return added
