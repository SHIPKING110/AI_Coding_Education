"""班级家长会 PPT Agent 会话与选项配置。

全程点选：每步给 A-D 固定选项 + E 自定义输入（E=展开输入框后执行）。
会话内存存储（无DB），配合 ai_tasks 做异步构建。
"""

from __future__ import annotations

import uuid

STYLE_OPTIONS = [
    {"id": "A", "label": "温馨亲切", "desc": "暖色·圆角卡片·故事感", "palette": "warm"},
    {"id": "B", "label": "专业严谨", "desc": "深色顶条·数据驱动", "palette": "pro"},
    {"id": "C", "label": "活泼童趣", "desc": "大标题·多色彩", "palette": "playful"},
    {"id": "D", "label": "简约现代", "desc": "留白·细线条", "palette": "minimal"},
]

FOCUS_OPTIONS = [
    {"id": "A", "label": "编程思维成长", "hint": "突出逻辑与作品"},
    {"id": "B", "label": "课堂参与度", "hint": "突出互动与表达"},
    {"id": "C", "label": "作业习惯", "hint": "突出练习与巩固"},
    {"id": "D", "label": "自信心与合作", "hint": "突出展示与互助"},
]

SUGGESTION_OPTIONS = [
    {"id": "A", "label": "家庭陪练技巧", "hint": "每天15分钟怎么陪"},
    {"id": "B", "label": "时间管理", "hint": "固定练习时段"},
    {"id": "C", "label": "表达展示", "hint": "让孩子讲给家长听"},
    {"id": "D", "label": "续课与规划", "hint": "下阶段衔接与续费"},
]

# 大纲预置项：key 与 build_class_meeting_ppt_dynamic 的章节一一对应
OUTLINE_PRESETS: list[dict] = [
    {"key": "cover", "title": "封面", "kicker": "COVER",
     "enabled": True, "order": 0},
    {"key": "data", "title": "班级学习数据", "kicker": "CLASS DATA",
     "enabled": True, "order": 1},
    {"key": "overview", "title": "班级整体情况", "kicker": "OVERVIEW",
     "enabled": True, "order": 2},
    {"key": "abilities", "title": "能力培养情况", "kicker": "ABILITIES",
     "enabled": True, "order": 3},
    {"key": "highlights", "title": "班级亮点", "kicker": "HIGHLIGHTS",
     "enabled": True, "order": 4},
    {"key": "honor", "title": "进步之星", "kicker": "STAR STUDENTS",
     "enabled": True, "order": 5},
    {"key": "works", "title": "作品展示", "kicker": "WORKS",
     "enabled": False, "order": 6},
    {"key": "to_improve", "title": "共性问题与改进", "kicker": "TO IMPROVE",
     "enabled": True, "order": 7},
    {"key": "next_plan", "title": "下阶段教学安排", "kicker": "NEXT PLAN",
     "enabled": True, "order": 8},
    {"key": "suggestions", "title": "给家长的建议", "kicker": "FOR PARENTS",
     "enabled": True, "order": 9},
    {"key": "ending", "title": "结尾致谢", "kicker": "THANKS",
     "enabled": True, "order": 10},
]

SESSIONS: dict[str, dict] = {}


def create_session(class_id, material: dict) -> str:
    sid = uuid.uuid4().hex
    SESSIONS[sid] = {
        "class_id": str(class_id),
        "material": material,
        "style": "A",
        "title": None,
        "outline": [dict(x) for x in OUTLINE_PRESETS],
    }
    return sid
