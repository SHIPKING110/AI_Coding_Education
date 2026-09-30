# 自定义 Skill 工具库

将可复用的能力封装为 skill，作为本项目可插拔的扩展点（见 `.claude/rules/11-project-arch.mdc` 扩展点）。

## 目录结构

```
skill/
  <skill-name>/
    SKILL.md        # 说明：用途、触发条件、输入输出、步骤
    <辅助文件>       # 模板/脚本/prompt，按需放置
```

## 如何新增一个 skill

1. 创建 `skill/<skill-name>/SKILL.md`
2. SKILL.md 包含：**用途**（一句话）、**适用场景/触发条件**、**输入与输出**、**执行步骤**、**依赖与约束**
3. 若涉及代码/模板/动作，放入同一目录并在 SKILL.md 引用相对路径
4. 命名小写 kebab-case，如 `ppt-template`, `question-generator`

## 如何调用 / 被引用

- 在 `agent.md` §4 文档路径表中登记新 skill（如确实是跨会话复用的核心能力）
- 会话中直接以文件名调用；复杂流程可拆成串行步骤

## 规划中的 skill（随里程碑沉淀）

| 名称 | 预期能力 | 里程碑 |
| --- | --- | --- |
| `feedback-writer` | 课后反馈/日报 AI 草稿 | M3 |
| `report-ppt` | 季度/年度总结 PPT 模板生成（python-pptx） | M3 |
| `evaluation-writer` | 基于 3 个月反馈的综合学员评估表 | M6 |
| `question-generator` | 举一反三 / 作业模式习题生成 | M4 |

> 未沉淀前，先以 `spec/design.md` 的 AI 编排约定为准，避免重复造轮子。