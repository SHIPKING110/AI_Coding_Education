import http from './http'

export interface FeedbackOut {
  id: string
  schedule_id: string
  student_id: string
  student_name: string | null
  class_name: string | null
  schedule_time: string | null
  title: string | null
  topic: string | null
  content: string | null
  performance: string | null
  evaluation: string | null
  homework: string | null
  media_urls: string[]
  status: string
  published_at: string | null
  created_at: string
  updated_at: string
}

export interface FeedbackCreate {
  schedule_id: string
  student_id: string
  title?: string | null
  topic?: string | null
  content?: string | null
  performance?: string | null
  evaluation?: string | null
  homework?: string | null
  media_urls?: string[]
}

export interface PageOut<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export interface UploadOut {
  url: string
  filename: string
}

export interface FeedbackDraftOut {
  title: string | null
  topic: string | null
  content: string | null
  performance: string | null
  evaluation: string | null
  homework: string | null
  model: string | null
}

export interface FeedbackAIEnhanceIn {
  title?: string | null
  topic?: string | null
  content?: string | null
  performance?: string | null
  evaluation?: string | null
  homework?: string | null
  template_id?: string | null
}

export interface FeedbackEditorRow {
  student_id: string
  student_name: string | null
  attendance_status: string // attended | leave | unmarked
  feedback: FeedbackOut | null
}

export interface FeedbackStats {
  schedule_count: number
  expected: number
  attended: number
  leave: number
  feedback_done: number
  pending: number
}

export interface CompletedScheduleOut {
  id: string
  class_id: string
  class_name: string | null
  subject: string | null
  teacher_name: string | null
  campus: string | null
  start_time: string
  end_time: string
  attended: number
  feedback_done: number
  saved_draft: number
  all_done: boolean
}

export async function listFeedbacks(params: {
  student_id?: string
  schedule_id?: string
  keyword?: string
  limit?: number
  offset?: number
} = {}): Promise<PageOut<FeedbackOut>> {
  const { data } = await http.get<PageOut<FeedbackOut>>('/feedbacks', { params })
  return data
}

export async function listFeedbackBySchedule(scheduleId: string): Promise<FeedbackOut[]> {
  const { data } = await http.get<FeedbackOut[]>(`/feedbacks/schedule/${scheduleId}`)
  return data
}

export async function listFeedbackEditorRows(scheduleId: string): Promise<FeedbackEditorRow[]> {
  const { data } = await http.get<FeedbackEditorRow[]>(
    `/feedbacks/schedule/${scheduleId}/editor`,
  )
  return data
}

export async function getFeedbackStats(params: {
  campus?: string
  teacher_id?: string
  class_id?: string
  start?: string
  end?: string
} = {}): Promise<FeedbackStats> {
  const { data } = await http.get<FeedbackStats>('/feedbacks/stats', { params })
  return data
}

export async function listCompletedSchedules(params: {
  campus?: string
  teacher_id?: string
  class_id?: string
  start?: string
  end?: string
} = {}): Promise<CompletedScheduleOut[]> {
  const { data } = await http.get<CompletedScheduleOut[]>('/feedbacks/completed-schedules', {
    params,
  })
  return data
}

export async function createFeedback(payload: FeedbackCreate): Promise<FeedbackOut> {
  const { data } = await http.post<FeedbackOut>('/feedbacks', payload)
  return data
}

export async function updateFeedback(
  id: string,
  payload: Partial<FeedbackCreate>,
): Promise<FeedbackOut> {
  const { data } = await http.patch<FeedbackOut>(`/feedbacks/${id}`, payload)
  return data
}

export async function publishFeedback(id: string): Promise<FeedbackOut> {
  const { data } = await http.post<FeedbackOut>(`/feedbacks/${id}/publish`)
  return data
}

export async function unpublishFeedback(id: string): Promise<FeedbackOut> {
  const { data } = await http.post<FeedbackOut>(`/feedbacks/${id}/unpublish`)
  return data
}

export async function aiEnhanceFeedback(
  id: string,
  payload: FeedbackAIEnhanceIn,
): Promise<FeedbackDraftOut> {
  const { data } = await http.post<FeedbackDraftOut>(`/feedbacks/${id}/ai-enhance`, payload)
  return data
}

export async function uploadFeedbackMedia(file: File): Promise<UploadOut> {
  const form = new FormData()
  form.append('file', file)
  const { data } = await http.post<UploadOut>('/feedbacks/upload', form)
  return data
}
