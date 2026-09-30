import http from './http'

export type QuestionType =
  | 'single_choice'
  | 'multiple_choice'
  | 'judgement'
  | 'code_fill'
  | 'programming'

export interface QuestionIn {
  type: QuestionType
  stem: string
  options?: string[] | null
  answer?: unknown
  analysis?: string | null
  difficulty?: number
  test_cases?: { input: string; output: string }[] | null
  language?: string | null
}

export interface QuestionOut extends QuestionIn {
  id: string
  order_no: number
  created_at: string
  updated_at: string
}

export interface AssignmentOut {
  id: string
  teacher_id: string
  teacher_name: string | null
  class_id: string | null
  class_name: string | null
  title: string
  mode: 'classwork' | 'homework'
  description: string | null
  deadline: string | null
  status: 'draft' | 'published'
  published_at: string | null
  created_at: string
  updated_at: string
  question_count: number
  type_scores: Record<string, number> | null
  passing_score: number | null
  total_score: number | null
  published_class_ids: string[]
  published_class_names: string[]
  target_student_ids: string[]
  target_student_names: string[]
  pending_review: number
  folder_id: string | null
  folder_name: string | null
  questions: QuestionOut[]
}

export interface AssignmentFolderOut {
  id: string
  owner_id: string
  name: string
  sort_no: number
  assignment_count: number
  created_at: string
}

export interface AssignmentCreateIn {
  title: string
  mode?: 'classwork' | 'homework'
  description?: string | null
  class_id?: string | null
  deadline?: string | null
  type_scores?: Record<string, number> | null
  passing_score?: number | null
  target_student_ids?: string[] | null
  questions?: QuestionIn[]
}

export interface AiGenerateIn {
  mode: 'similar' | 'homework'
  count: number
  difficulty: number
  source_question?: string | null
  source_answer?: string | null
  hint?: string | null
  types?: QuestionType[] | null
}

export interface AiRefineIn {
  question: QuestionIn
  instruction: string
}

export interface PageOut<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export async function listAssignments(params: {
  teacher_id?: string
  class_id?: string
  status?: string
  mode?: 'classwork' | 'homework'
  keyword?: string
  limit?: number
  folder_id?: string
  ungrouped?: boolean
  offset?: number
} = {}): Promise<PageOut<AssignmentOut>> {
  const { data } = await http.get<PageOut<AssignmentOut>>('/assignments', { params })
  return data
}

/** 分组视图：一次拉全量（前端按分组折叠展示，limit 固定 500 覆盖常规规模） */
export async function listAssignmentsGrouped(params: {
  status?: string
  mode?: 'classwork' | 'homework'
  keyword?: string
} = {}): Promise<AssignmentOut[]> {
  const { data } = await http.get<PageOut<AssignmentOut>>('/assignments', {
    params: { ...params, limit: 500, offset: 0 },
  })
  return data.items
}

export async function listAssignmentFolders(): Promise<AssignmentFolderOut[]> {
  const { data } = await http.get<AssignmentFolderOut[]>('/assignments/folders')
  return data
}

export async function createAssignmentFolder(payload: { name: string; sort_no?: number }): Promise<AssignmentFolderOut> {
  const { data } = await http.post<AssignmentFolderOut>('/assignments/folders', payload)
  return data
}

export async function updateAssignmentFolder(id: string, payload: { name?: string; sort_no?: number }): Promise<AssignmentFolderOut> {
  const { data } = await http.patch<AssignmentFolderOut>(`/assignments/folders/${id}`, payload)
  return data
}

export async function deleteAssignmentFolder(id: string): Promise<void> {
  await http.delete(`/assignments/folders/${id}`)
}

export async function moveAssignmentsToFolder(folderId: string, assignmentIds: string[]): Promise<void> {
  await http.post(`/assignments/folders/${folderId}/assignments`, { assignment_ids: assignmentIds })
}

export async function removeAssignmentsFromFolder(assignmentIds: string[]): Promise<void> {
  await http.post('/assignments/folders/ungrouped/assignments', { assignment_ids: assignmentIds })
}

/** 批改中心条目（跨作业聚合）：一份作业的提交/批改进度 */
export interface GradingCenterItem {
  assignment_id: string
  title: string
  mode: string
  teacher_id: string | null
  teacher_name: string | null
  class_names: string[]
  deadline: string | null
  published_at: string | null
  total_students: number
  submitted: number
  pending_review: number
  graded: number
  latest_submitted_at: string | null
}

/** 批改中心（跨作业聚合，默认仅返回有待批改的作业） */
export async function listGradingCenter(
  params: { pending_only?: boolean; limit?: number; offset?: number } = {},
): Promise<PageOut<GradingCenterItem>> {
  const { data } = await http.get<PageOut<GradingCenterItem>>('/assignments/grading-center', { params })
  return data
}

export async function getAssignment(id: string): Promise<AssignmentOut> {
  const { data } = await http.get<AssignmentOut>(`/assignments/${id}`)
  return data
}

export async function createAssignment(payload: AssignmentCreateIn): Promise<AssignmentOut> {
  const { data } = await http.post<AssignmentOut>('/assignments', payload)
  return data
}

export async function updateAssignment(
  id: string,
  payload: Partial<
    Pick<AssignmentCreateIn, 'title' | 'mode' | 'description' | 'class_id' | 'deadline' | 'type_scores' | 'passing_score'>
  >,
): Promise<AssignmentOut> {
  const { data } = await http.patch<AssignmentOut>(`/assignments/${id}`, payload)
  return data
}

export async function deleteAssignment(id: string): Promise<void> {
  await http.delete(`/assignments/${id}`)
}

export async function publishAssignment(
  id: string,
  payload: {
    class_ids: string[]
    deadline?: string | null
    type_scores?: Record<string, number> | null
    passing_score?: number | null
    target_student_ids?: string[] | null
    notify_parents?: boolean
  },
): Promise<AssignmentOut> {
  const { data } = await http.post<AssignmentOut>(`/assignments/${id}/publish`, payload)
  return data
}

export async function unpublishAssignment(id: string): Promise<AssignmentOut> {
  const { data } = await http.post<AssignmentOut>(`/assignments/${id}/unpublish`)
  return data
}

export async function createMakeupAssignment(
  id: string,
  studentIds: string[],
): Promise<AssignmentOut> {
  const { data } = await http.post<AssignmentOut>(`/assignments/${id}/makeup`, studentIds)
  return data
}

/** AI 出题/优化异步任务（提交立即返回，轮询进度与结果；task-cancel-recover 支持取消/自恢复） */
export interface AiTaskOut {
  id: string
  owner_id: string
  kind: 'generate' | 'refine'
  summary: string
  status: 'pending' | 'running' | 'done' | 'failed' | 'cancelled'
  stage: string | null
  result: QuestionIn[] | QuestionIn | null
  model: string | null
  error: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
}

/** 提交 AI 出题任务（举一反三 / 作业模式），立即返回任务（后台执行，轮询查看进度） */
export async function aiGenerate(payload: AiGenerateIn): Promise<AiTaskOut> {
  const { data } = await http.post<AiTaskOut>('/assignments/ai-generate', payload)
  return data
}

/** 提交对话优化单题任务 */
export async function aiRefine(payload: AiRefineIn): Promise<AiTaskOut> {
  const { data } = await http.post<AiTaskOut>('/assignments/ai-refine', payload)
  return data
}

/** 轮询任务状态/进度/结果 */
export async function getAiTask(id: string): Promise<AiTaskOut> {
  const { data } = await http.get<AiTaskOut>(`/assignments/ai-tasks/${id}`)
  return data
}

/** 最近 AI 生成任务（新在前）——刷新页面后恢复进行中任务 */
export async function listAiTasks(limit = 20): Promise<AiTaskOut[]> {
  const { data } = await http.get<AiTaskOut[]>('/assignments/ai-tasks', { params: { limit } })
  return data
}

export function isTaskRunning(t: AiTaskOut): boolean {
  return t.status === 'pending' || t.status === 'running'
}

export function isTaskTerminal(t: Pick<AiTaskOut, 'status'>): boolean {
  return t.status === 'done' || t.status === 'failed' || t.status === 'cancelled'
}

/** 取消 AI 任务：排队中直接取消，生成中标记后收敛（task-cancel-recover） */
export async function cancelAiTask(id: string): Promise<AiTaskOut> {
  const { data } = await http.post<AiTaskOut>(`/assignments/ai-tasks/${id}/cancel`)
  return data
}

/** 追加题目（返回更新后的作业） */
export async function addQuestions(id: string, questions: QuestionIn[]): Promise<AssignmentOut> {
  const { data } = await http.post<AssignmentOut>(`/assignments/${id}/questions`, questions)
  return data
}

/** 编辑单题 */
export async function updateQuestion(
  assignmentId: string,
  questionId: string,
  payload: Partial<QuestionIn>,
): Promise<QuestionOut> {
  const { data } = await http.patch<QuestionOut>(
    `/assignments/${assignmentId}/questions/${questionId}`,
    payload,
  )
  return data
}

/** 删除单题 */
export async function deleteQuestion(assignmentId: string, questionId: string): Promise<void> {
  await http.delete(`/assignments/${assignmentId}/questions/${questionId}`)
}

/** 题目排序（按 id 顺序） */
export async function reorderQuestions(
  id: string,
  questionIds: string[],
): Promise<AssignmentOut> {
  const { data } = await http.put<AssignmentOut>(`/assignments/${id}/questions/reorder`, {
    question_ids: questionIds,
  })
  return data
}

/** 题型中文名 */
export const QUESTION_TYPE_LABELS: Record<QuestionType, string> = {
  single_choice: '单选题',
  multiple_choice: '多选题',
  judgement: '判断题',
  code_fill: '代码填空',
  programming: '编程题',
}

/** 历史题目池条目：已发布作业中的一道题（含所属作业标题） */
export interface QuestionsPoolItem {
  id: string
  assignment_id: string
  assignment_title: string
  order_no: number
  type: QuestionType
  stem: string
  options?: string[] | null
  answer?: unknown
  analysis?: string | null
  difficulty: number
  test_cases?: { input: string; output: string }[] | null
  language?: string | null
  created_at: string
  updated_at: string
}

/** 历史题目池：查询已发布作业中的题目（按作业标题/题型/难度筛选，分页） */
export async function listQuestionsPool(params: {
  keyword?: string
  /** 多个题型用英文逗号分隔 */
  types?: string
  difficulty_min?: number
  difficulty_max?: number
  limit?: number
  offset?: number
} = {}): Promise<PageOut<QuestionsPoolItem>> {
  const { data } = await http.get<PageOut<QuestionsPoolItem>>('/assignments/questions/pool', { params })
  return data
}
