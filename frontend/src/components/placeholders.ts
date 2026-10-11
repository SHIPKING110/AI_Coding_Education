/** 提示词模板占位符定义（与后端 fill_template / FEEDBACK_PLACEHOLDERS 对应）。 */

export interface PlaceholderDef {
  key: string
  desc: string
}

/** 课后反馈场景可用占位符（后端真实替换，9 个）。 */
export const FEEDBACK_PLACEHOLDERS: PlaceholderDef[] = [
  { key: 'student_name', desc: '学员姓名' },
  { key: 'class_name', desc: '班级名称' },
  { key: 'subject', desc: '科目' },
  { key: 'title', desc: '反馈标题（教师填写）' },
  { key: 'topic', desc: '课题' },
  { key: 'content', desc: '课题内容' },
  { key: 'performance', desc: '课堂表现' },
  { key: 'evaluation', desc: '已有课堂评价（润色时用）' },
  { key: 'homework', desc: '今日作业' },
]

/** 报告总结场景可用占位符（随风格要求文本一起替换）。 */
export const REPORT_PLACEHOLDERS: PlaceholderDef[] = [
  { key: 'teacher_name', desc: '教师姓名（报告撰写人）' },
  { key: 'campus', desc: '所属校区' },
  { key: 'period', desc: '报告周期（如 2026年10月05日 ~ 2026年10月11日）' },
  { key: 'report_type', desc: '报告类型（日报 / 周报 / 季度总结 / 年度总结）' },
]

/** 学员评估场景可用占位符（随风格要求文本一起替换）。 */
export const EVALUATION_PLACEHOLDERS: PlaceholderDef[] = [
  { key: 'student_name', desc: '学员姓名' },
  { key: 'period', desc: '评估周期（如 2026年07月01日 ~ 2026年09月30日）' },
  { key: 'teacher_name', desc: '生成教师（撰写人）' },
]
