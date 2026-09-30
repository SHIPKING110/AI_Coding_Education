import http from './http'

export type ReportType = 'daily' | 'weekly' | 'quarterly' | 'yearly'

export interface ReportOut {
  id: string
  type: string
  teacher_id: string
  teacher_name: string | null
  period_start: string
  period_end: string
  title: string | null
  content: Record<string, string | null>
  stats: Record<string, unknown> | null
  ppt_url: string | null
  status: string
  published_at: string | null
  created_at: string
  updated_at: string
}

export interface ReportIn {
  type: ReportType
  period_start: string
  period_end: string
  title?: string | null
  content?: Record<string, unknown>
  stats?: Record<string, unknown> | null
}

export interface WeeklyStatsOut {
  schedules: number
  expected_attendance: number
  attended: number
  leave: number
  attendance_rate: number
  absent_students: string[]
  new_students: number
  expected_lessons: number
  consumed_lessons: number
  achievement_rate: number
}

export interface DailyStatsOut {
  schedules: number
  expected_attendance: number
  attended: number
  leave: number
  attendance_rate: number
  expected_lessons: number
  consumed_lessons: number
  achievement_rate: number
}

export interface PeriodStatsOut {
  schedules: number
  attended: number
  leave: number
  attendance_rate: number
  absent_students: string[]
  new_students: number
  weekly_count: number
  current_students: number
  expected_lessons: number
  consumed_lessons: number
  achievement_rate: number
  quarterly_count: number
}

export interface PeriodMonthlyPoint {
  month: string
  expected_lessons: number
  consumed_lessons: number
  new_students: number
  attendance: number
}

export interface PeriodComparison {
  labels: string[]
  current: number[]
  previous_labels: string[]
  previous: number[]
}

export interface ReportBoardItemOut {
  id: string
  type: string
  teacher_id: string
  teacher_name: string | null
  campus: string | null
  period_start: string
  period_end: string
  title: string | null
  content: Record<string, string | null>
  stats: Record<string, unknown> | null
  ppt_url: string | null
  published_at: string | null
}

export interface ReportBoardStatsOut {
  teacher_count: number
  daily_due: number
  daily_submitted: number
  weekly_due: number
  weekly_submitted: number
}

export interface ReportPptOut {
  ppt_url: string
  title: string | null
}

export interface PageOut<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export interface ReportAiDraftOut {
  title: string | null
  content: Record<string, string | null>
  model: string | null
}

export interface AiDraftJobOut {
  job_id: string
  status: string
}

export interface AiDraftJobStatusOut {
  job_id: string
  report_id: string
  report_type: string
  status: 'pending' | 'running' | 'succeeded' | 'failed'
  title: string | null
  content: Record<string, string | null> | null
  model: string | null
  error: string | null
  created_at: number
  finished_at: number | null
  elapsed_seconds: number
}

export async function listReports(params: {
  type?: ReportType
  teacher_id?: string
  mine?: boolean
  start?: string
  end?: string
  limit?: number
  offset?: number
} = {}): Promise<PageOut<ReportOut>> {
  const { data } = await http.get<PageOut<ReportOut>>('/reports', { params })
  return data
}

export async function getReport(id: string): Promise<ReportOut> {
  const { data } = await http.get<ReportOut>(`/reports/${id}`)
  return data
}

export async function createReport(payload: ReportIn): Promise<ReportOut> {
  const { data } = await http.post<ReportOut>('/reports', payload)
  return data
}

export async function updateReport(
  id: string,
  payload: Partial<Pick<ReportIn, 'title' | 'content' | 'stats'>>,
): Promise<ReportOut> {
  const { data } = await http.patch<ReportOut>(`/reports/${id}`, payload)
  return data
}

export async function publishReport(id: string): Promise<ReportOut> {
  const { data } = await http.post<ReportOut>(`/reports/${id}/publish`)
  return data
}

export async function unpublishReport(id: string): Promise<ReportOut> {
  const { data } = await http.post<ReportOut>(`/reports/${id}/unpublish`)
  return data
}

/** 删除报告（含已发布/公栏）：本人可删自己的，管理员/教务可删全部 */
export async function deleteReport(id: string): Promise<void> {
  await http.delete(`/reports/${id}`)
}

export async function weeklyStatsPreview(params: {
  teacher_id?: string
  start: string
  end: string
}): Promise<WeeklyStatsOut> {
  const { data } = await http.get<WeeklyStatsOut>('/reports/weekly-stats/preview', { params })
  return data
}

export async function dailyStatsPreview(params: {
  teacher_id?: string
  day: string
}): Promise<DailyStatsOut> {
  const { data } = await http.get<DailyStatsOut>('/reports/daily-stats/preview', { params })
  return data
}

export async function periodStatsPreview(params: {
  teacher_id?: string
  start: string
  end: string
  report_type?: 'quarterly' | 'yearly'
}): Promise<PeriodStatsOut> {
  const { data } = await http.get<PeriodStatsOut>('/reports/period-stats/preview', { params })
  return data
}

export async function periodStatsMonthly(params: {
  teacher_id?: string
  start: string
  end: string
}): Promise<PeriodMonthlyPoint[]> {
  const { data } = await http.get<PeriodMonthlyPoint[]>('/reports/period-stats/monthly', { params })
  return data
}

export async function periodStatsComparison(params: {
  teacher_id?: string
  start: string
  end: string
}): Promise<PeriodComparison> {
  const { data } = await http.get<PeriodComparison>('/reports/period-stats/comparison', { params })
  return data
}

/** 公栏：全部教师已发布报告列表（分页，可筛选校区/教师/类型/周期） */
export async function listBoardReports(params: {
  type?: ReportType
  teacher_id?: string
  campus?: string
  start?: string
  end?: string
  limit?: number
  offset?: number
} = {}): Promise<PageOut<ReportBoardItemOut>> {
  const { data } = await http.get<PageOut<ReportBoardItemOut>>('/reports/board', { params })
  return data
}

/** 公栏统计：按在职教师统计日报/周报应提交与已提交数量 */
export async function boardStats(params: {
  campus?: string
  start?: string
  end?: string
} = {}): Promise<ReportBoardStatsOut> {
  const { data } = await http.get<ReportBoardStatsOut>('/reports/board/stats', { params })
  return data
}

export async function generateReportPpt(
  id: string,
  payload?: { include_sections?: Record<string, number[]> },
): Promise<ReportPptOut> {
  const { data } = await http.post<ReportPptOut>(`/reports/${id}/ppt`, payload ?? {})
  return data
}

export function pptDownloadUrl(pptUrl: string): string {
  // UPLOAD_DIR 静态服务挂载在 /uploads
  return `/uploads/${pptUrl}`
}

export type PptChatStage = 'outline' | 'copy' | 'layout' | 'chat'

export interface PptPhase {
  key: string
  label: string
}

/** 对话式 PPT 定制：SSE 流式，逐段回调 delta 文本；onPhase 回调思考阶段 */
export async function pptChatStream(
  id: string,
  payload: { stage: PptChatStage; message: string; outline: unknown[]; sections: unknown[] },
  onDelta: (text: string) => void,
  signal?: AbortSignal,
  onPhase?: (phase: PptPhase) => void,
): Promise<void> {
  const token = localStorage.getItem('access_token')
  const resp = await fetch(`/api/reports/${id}/ppt-chat`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(payload),
    signal,
  })
  if (!resp.ok || !resp.body) {
    let msg = 'AI 定制失败'
    try {
      const j = await resp.json()
      msg = j?.detail || msg
    } catch {
      /* ignore */
    }
    throw new Error(msg)
  }
  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    const frames = buf.split('\n\n')
    buf = frames.pop() || ''
    for (const frame of frames) {
      const line = frame.split('\n').find((l) => l.startsWith('data:'))
      if (!line) continue
      let data: { delta?: string; done?: boolean; error?: string; phase?: PptPhase }
      try {
        data = JSON.parse(line.slice(5).trim())
      } catch {
        continue
      }
      if (data.error) throw new Error(data.error)
      if (data.phase && onPhase) onPhase(data.phase)
      if (data.delta) onDelta(data.delta)
      if (data.done) return
    }
  }
}

/** 按对话确认的 slides 规格构建定制 PPT */
export async function buildPpt(
  id: string,
  payload: { title?: string | null; theme?: 'brand' | 'cyan' | 'deep'; slides: unknown[] },
): Promise<ReportPptOut> {
  const { data } = await http.post<ReportPptOut>(`/reports/${id}/ppt-build`, payload, {
    timeout: 60000,
  })
  return data
}

export async function reportAiDraft(
  id: string,
  payload: { extra_note?: string | null; source_quarter_ids?: string[] },
): Promise<ReportAiDraftOut> {
  // 同步入口保留给旧客户端与测试；新版 SummaryView 走异步任务（可关弹窗）。
  // AI 生成通常需要 20-60 秒（后端 LLM timeout 60s），此处单独放宽超时，
  // 避免被全局 15s 超时提前中断导致“AI生成失败”
  const { data } = await http.post<ReportAiDraftOut>(`/reports/${id}/ai-draft`, payload, {
    timeout: 90000,
  })
  return data
}

/** 提交 AI 草稿异步任务：立即返回 job_id，可关弹窗/切页面后轮询取结果 */
export async function createAiDraftJob(
  id: string,
  payload: { extra_note?: string | null; source_quarter_ids?: string[] },
): Promise<AiDraftJobOut> {
  const { data } = await http.post<AiDraftJobOut>(`/reports/${id}/ai-draft-jobs`, payload, {
    timeout: 15000,
  })
  return data
}

/** 查询 AI 草稿任务状态：pending/running/succeeded/failed */
export async function getAiDraftJob(
  id: string,
  jobId: string,
): Promise<AiDraftJobStatusOut> {
  const { data } = await http.get<AiDraftJobStatusOut>(
    `/reports/${id}/ai-draft-jobs/${jobId}`,
  )
  return data
}