import http from './http'

export interface EvaluationOut {
  id: string
  student_id: string
  student_name: string | null
  student_campus: string | null
  teacher_id: string
  teacher_name: string | null
  period_start: string
  period_end: string
  title: string | null
  content: Record<string, unknown>
  stats: Record<string, unknown> | null
  ai_draft: Record<string, unknown> | null
  ppt_url: string | null
  status: string
  published_at: string | null
  created_at: string
  updated_at: string
}

export interface EvaluationCreateIn {
  student_id: string
  period_start: string
  period_end: string
  title?: string | null
  content?: Record<string, unknown>
  stats?: Record<string, unknown> | null
}

export interface EvaluationUpdateIn {
  title?: string | null
  content?: Record<string, unknown>
  stats?: Record<string, unknown> | null
}

export interface EvaluationStatsOut {
  attended: number
  leave: number
  attendance_rate: number
  consumed_lessons: number
  feedback_count: number
  homework_count: number
  homework_score_rate: number | null
}

export interface EvaluationFeedbackItem {
  date: string
  class_name: string | null
  topic: string | null
  content: string | null
  performance: string | null
  evaluation: string | null
  homework: string | null
}

export interface EvaluationMaterialOut {
  student_id: string
  student_name: string
  classes: Array<{ name: string; subject: string; teacher_name: string | null }>
  start: string
  end: string
  stats: EvaluationStatsOut
  feedbacks: EvaluationFeedbackItem[]
}

export interface EvaluationPptOut {
  ppt_url: string
  title: string | null
}

export interface ClassPptTaskOut {
  id: string
  owner_id: string
  kind: string
  summary: string
  status: string
  stage: string | null
  result: Record<string, unknown> | null
  model: string | null
  error: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export async function generateClassPpt(payload: {
  class_id: string
  period_start: string
  period_end: string
  extra_note?: string | null
  /** 素材无变化时强制重提炼（需二次确认后才传 true） */
  force?: boolean
}): Promise<ClassPptTaskOut> {
  const { data } = await http.post<ClassPptTaskOut>('/evaluations/class-ppt', payload)
  return data
}

/** 重提炼去重预检：素材无变化 / 任务进行中 提示（regen-dedup）。 */
export interface ClassPptFingerprintOut {
  has_record: boolean
  record_id: string | null
  unchanged: boolean
  running: boolean
  running_stage: string | null
  evaluated_count: number
}

export async function getClassPptFingerprint(params: {
  class_id: string
  period_start: string
  period_end: string
}): Promise<ClassPptFingerprintOut> {
  const { data } = await http.get<ClassPptFingerprintOut>('/evaluations/class-ppt/fingerprint', {
    params,
  })
  return data
}

/** 班级家长会 PPT 落库记录（latest 接口返回：db 记录可编辑，task 历史仅可下载）。 */
export interface ClassPptRecordOut {
  source: 'db' | 'task'
  record_id: string | null
  task_id: string | null
  class_id: string
  class_name: string | null
  subject: string | null
  teacher_name: string | null
  period_start: string
  period_end: string
  title: string | null
  content: Record<string, unknown>
  stats: Record<string, unknown> | null
  averages: Array<[string, number]> | null
  honor_roll: Array<[string, string]> | null
  ppt_url: string | null
  material_hash: string | null
  updated_at: string | null
}

export async function getClassPptLatest(classId: string): Promise<ClassPptRecordOut> {
  const { data } = await http.get<ClassPptRecordOut>('/evaluations/class-ppt/latest', {
    params: { class_id: classId },
  })
  return data
}

/** PATCH 保存后的落库记录（结构同后端 ClassPptOut）。 */
export interface ClassPptSavedOut {
  id: string
  class_id: string
  teacher_id: string
  period_start: string
  period_end: string
  title: string | null
  content: Record<string, unknown>
  stats: Record<string, unknown> | null
  averages: Array<[string, number]> | null
  honor_roll: Array<[string, string]> | null
  ppt_url: string | null
  created_at: string
  updated_at: string
}

export async function updateClassPpt(
  recordId: string,
  payload: Partial<{
    title: string | null
    class_summary: string | null
    ability_comment: string | null
    highlights: string | null
    to_improve: string | null
    next_plan: string | null
    home_suggestions: string | null
  }>,
): Promise<ClassPptSavedOut> {
  const { data } = await http.patch<ClassPptSavedOut>(
    `/evaluations/class-ppt/${recordId}`,
    payload,
  )
  return data
}

// ---------------------------------------------------------------------------
// 班级家长会 PPT · Agent 对话式定制（7 步向导，ABCD 点选 + E 自定义输入）
// ---------------------------------------------------------------------------

export interface PptAgentOutlineItem {
  key: string
  title: string
  kicker: string
  enabled: boolean
  order: number
}

export interface PptAgentInitOut {
  session_id: string
  class_name: string
  subject: string | null
  stats: Record<string, unknown> | null
  averages: Array<[string, number]> | null
  honor_roll: Array<[string, string]> | null
  evaluated_count: number
  style_options: Array<{ id: string; label: string; desc: string; palette: string }>
  focus_options: Array<{ id: string; label: string; hint: string }>
  suggestion_options: Array<{ id: string; label: string; hint: string }>
  outline_presets: PptAgentOutlineItem[]
}

export interface PptAgentTitlesOut {
  titles: string[]
  is_custom: boolean
}

export interface PptAgentOutlinePreviewItem {
  key: string
  title: string
  kicker: string
  desc: string
}

export interface PptAgentOutlineOut {
  preview: PptAgentOutlinePreviewItem[]
  total: number
}

export async function initPptAgent(payload: {
  class_id: string
  period_start: string
  period_end: string
  extra_note?: string | null
}): Promise<PptAgentInitOut> {
  const { data } = await http.post<PptAgentInitOut>('/evaluations/class-ppt/agent/init', payload)
  return data
}

export async function getPptAgentTitles(payload: {
  session_id: string
  style: string
}): Promise<PptAgentTitlesOut> {
  const { data } = await http.post<PptAgentTitlesOut>('/evaluations/class-ppt/agent/titles', payload, {
    // 同步标题接口：LLM 偶发慢（实测 ~40s），放宽避免 15s 默认超时误杀
    timeout: 90000,
  })
  return data
}

export async function submitPptAgentOutline(payload: {
  session_id: string
  title?: string
  outline: PptAgentOutlineItem[]
}): Promise<PptAgentOutlineOut> {
  const { data } = await http.post<PptAgentOutlineOut>('/evaluations/class-ppt/agent/outline', payload)
  return data
}

export async function buildPptAgent(payload: {
  session_id: string
  title: string
  outline: PptAgentOutlineItem[]
  focus?: string | null
  suggestion_pref?: string | null
}): Promise<ClassPptTaskOut> {
  const { data } = await http.post<ClassPptTaskOut>('/evaluations/class-ppt/agent/build', payload)
  return data
}

export async function refinePptAgent(payload: {
  record_id: string
  instruction: string
}): Promise<ClassPptTaskOut> {
  const { data } = await http.post<ClassPptTaskOut>('/evaluations/class-ppt/agent/refine', null, {
    params: { record_id: payload.record_id, instruction: payload.instruction },
  })
  return data
}

export interface ClassRosterEvaluationOut {
  id: string
  title: string | null
  status: string
  published_at: string | null
}

export interface ClassRosterStudentOut {
  student_id: string
  name: string
  campus: string | null
  lesson_balance: number
  evaluation: ClassRosterEvaluationOut | null
}

export interface ClassRosterOut {
  class_id: string
  class_name: string
  subject: string
  teacher_name: string | null
  period_start: string
  period_end: string
  total: number
  generated: number
  published: number
  students: ClassRosterStudentOut[]
}

export async function getClassRoster(params: {
  class_id: string
  period_start: string
  period_end: string
}): Promise<ClassRosterOut> {
  const { data } = await http.get<ClassRosterOut>('/evaluations/class-roster', { params })
  return data
}

export interface EvaluationAiDraftOut {
  id: string
  owner_id: string
  kind: string
  summary: string
  status: string
  stage: string | null
  result: Record<string, unknown> | null
  model: string | null
  error: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export async function listEvaluations(params: {
  student_id?: string
  status?: string
  keyword?: string
  limit?: number
  offset?: number
} = {}): Promise<{ items: EvaluationOut[]; total: number; limit: number; offset: number }> {
  const { data } = await http.get('/evaluations', { params })
  return data
}

export async function createEvaluation(payload: EvaluationCreateIn): Promise<EvaluationOut> {
  const { data } = await http.post<EvaluationOut>('/evaluations', payload)
  return data
}

export async function updateEvaluation(id: string, payload: EvaluationUpdateIn): Promise<EvaluationOut> {
  const { data } = await http.patch<EvaluationOut>(`/evaluations/${id}`, payload)
  return data
}

export async function publishEvaluation(id: string): Promise<EvaluationOut> {
  const { data } = await http.post<EvaluationOut>(`/evaluations/${id}/publish`)
  return data
}

export async function unpublishEvaluation(id: string): Promise<EvaluationOut> {
  const { data } = await http.post<EvaluationOut>(`/evaluations/${id}/unpublish`)
  return data
}

export async function getEvaluation(id: string): Promise<EvaluationOut> {
  const { data } = await http.get<EvaluationOut>(`/evaluations/${id}`)
  return data
}

export async function getEvaluationMaterial(params: {
  student_id: string
  start: string
  end: string
}): Promise<EvaluationMaterialOut> {
  const { data } = await http.get<EvaluationMaterialOut>('/evaluations/material/preview', { params })
  return data
}

export async function aiDraftEvaluation(id: string, payload: { extra_note?: string | null; style_guide?: string | null }): Promise<EvaluationAiDraftOut> {
  const { data } = await http.post<EvaluationAiDraftOut>(`/evaluations/${id}/ai-draft`, payload)
  return data
}

export async function aiRefineEvaluation(id: string, payload: { instruction: string }): Promise<EvaluationAiDraftOut> {
  const { data } = await http.post<EvaluationAiDraftOut>(`/evaluations/${id}/ai-refine`, payload)
  return data
}

export async function getEvaluationAiTask(id: string): Promise<EvaluationAiDraftOut> {
  const { data } = await http.get<EvaluationAiDraftOut>(`/evaluations/ai-tasks/${id}`)
  return data
}

/** 取消评估/PPT 任务：排队中直接取消，生成中标记后收敛（task-cancel-recover） */
export async function cancelEvaluationAiTask(id: string): Promise<EvaluationAiDraftOut> {
  const { data } = await http.post<EvaluationAiDraftOut>(`/evaluations/ai-tasks/${id}/cancel`)
  return data
}

/** 任务是否已终态（done/failed/cancelled）：终态不再轮询，可重试或关闭 */
export function isEvaluationTaskTerminal(t: Pick<EvaluationAiDraftOut, 'status'>): boolean {
  return t.status === 'done' || t.status === 'failed' || t.status === 'cancelled'
}

export async function listEvaluationAiTasks(limit = 20): Promise<EvaluationAiDraftOut[]> {
  const { data } = await http.get<EvaluationAiDraftOut[]>('/evaluations/ai-tasks', { params: { limit } })
  return data
}

export async function generateEvaluationPpt(id: string): Promise<EvaluationPptOut> {
  const { data } = await http.post<EvaluationPptOut>(`/evaluations/${id}/ppt`)
  return data
}

export async function deleteEvaluation(id: string): Promise<void> {
  await http.delete(`/evaluations/${id}`)
}

export function pptDownloadUrl(pptUrl: string): string {
  return `/uploads/${pptUrl}`
}

/** 导出评估报告 PDF（管理端：教师自己的 / admin·staff 全部，含草稿预览）。 */
export async function exportEvaluationPdf(id: string): Promise<Blob> {
  const { data } = await http.get(`/evaluations/${id}/pdf`, {
    responseType: 'blob',
    timeout: 30000,
  })
  return data
}

/** 导出评估报告 PDF（家长/学员端：仅本人名下学员的已发布评估）。 */
export async function exportClientEvaluationPdf(
  studentId: string,
  evaluationId: string,
): Promise<Blob> {
  const { data } = await http.get(
    `/client/students/${studentId}/evaluations/${evaluationId}/pdf`,
    { responseType: 'blob', timeout: 30000 },
  )
  return data
}

/** 把 Blob 响应中的后端错误（JSON detail）解析出来；非错误响应返回空串。 */
export async function blobErrorMessage(e: unknown): Promise<string> {
  const resp = (e as { response?: { data?: unknown } })?.response
  if (resp?.data instanceof Blob) {
    try {
      const json = JSON.parse(await resp.data.text()) as { detail?: string }
      if (json.detail) return json.detail
    } catch {
      // 非 JSON（如网络中断），返回空串走兜底文案
    }
  }
  return ''
}

/** 触发浏览器下载（用于后端生成的 PDF/PPT 等 Blob 文件）。 */
export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

/** 家长/学员端看到的精简评估视图（不含内部字段 ai_draft 等） */
export interface ClientEvaluationOut {
  id: string
  title: string | null
  teacher_name: string | null
  period_start: string
  period_end: string
  content: Record<string, unknown>
  stats: Record<string, unknown> | null
  ppt_url: string | null
  status: string
  published_at: string | null
}

export async function listClientEvaluations(
  studentId: string,
  params: { limit?: number; offset?: number } = {},
): Promise<{ items: ClientEvaluationOut[]; total: number; limit: number; offset: number }> {
  const { data } = await http.get(`/client/students/${studentId}/evaluations`, { params })
  return data
}
