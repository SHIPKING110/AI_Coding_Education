import http from './http'

export type BankQuestionType =
  | 'single_choice'
  | 'multiple_choice'
  | 'judgement'
  | 'code_fill'
  | 'programming'

export interface BankMedia {
  scope: string
  url: string
}

export interface BankQuestion {
  id: string
  order_no: number
  type: BankQuestionType
  stem: string
  options: string[] | null
  answer: unknown
  analysis: string | null
  difficulty: number
  score: number
  language: string | null
  reference_code: string | null
  test_cases: unknown[] | null
  media: BankMedia[] | null
  knowledge_points: string[] | null
  source_excerpt: string | null
  status: 'draft' | 'reviewed' | 'published' | 'archived'
  review_note: string | null
}

export interface BankImportOut {
  source_id: string
  set_id: string
  question_count: number
  warnings: string[]
  issues: BankIssue[]
}

export interface BankIssue {
  code: string
  level: string
  message: string
  question_no?: number | null
}

export interface BankSet {
  id: string
  source_id: string
  name: string
  institution: string | null
  exam_year: number | null
  exam_month: string | null
  subject: string | null
  level: string | null
  total_score: number | null
  status: 'draft' | 'reviewed' | 'published' | 'archived'
  question_count: number | null
  import_meta: {
    sections?: { name: string; count: number; score: number; type: string | null }[]
    warnings?: string[]
    issues?: BankIssue[]
    parser?: string
  } | null
  created_at: string
  questions?: BankQuestion[]
}

export async function importBankDocx(
  file: File,
  meta: { name?: string; institution?: string; exam_year?: number | string; subject?: string; level?: string } = {},
): Promise<BankImportOut> {
  const form = new FormData()
  form.append('file', file)
  Object.entries(meta).forEach(([k, v]) => {
    if (v === undefined || v === null) return
    const text = String(v).trim()
    if (!text || text === 'NaN') return
    form.append(k, text)
  })
  const { data } = await http.post('/question-bank/imports', form, { timeout: 120000 })
  return data
}

export async function listBankSets(params: {
  institution?: string
  subject?: string
  level?: string
  exam_year?: number
  exam_month?: string
  status?: string
} = {}): Promise<{ items: BankSet[]; total: number }> {
  const { data } = await http.get('/question-bank/sets', { params })
  return data
}

export async function getBankSet(id: string): Promise<BankSet> {
  const { data } = await http.get(`/question-bank/sets/${id}`)
  return data
}

export async function updateBankSet(
  id: string,
  payload: Partial<Pick<BankSet, 'name' | 'institution' | 'exam_year' | 'exam_month' | 'subject' | 'level'>>,
): Promise<BankSet> {
  const { data } = await http.patch(`/question-bank/sets/${id}`, payload)
  return data
}

export async function updateBankQuestion(
  setId: string,
  questionId: string,
  payload: Partial<BankQuestion>,
): Promise<BankQuestion> {
  const { data } = await http.patch(`/question-bank/sets/${setId}/questions/${questionId}`, payload)
  return data
}

export async function reviewAllQuestions(setId: string): Promise<{ reviewed: number }> {
  const { data } = await http.post(`/question-bank/sets/${setId}/review-all`)
  return data
}

export async function publishBankSet(setId: string): Promise<BankSet> {
  const { data } = await http.post(`/question-bank/sets/${setId}/publish`)
  return data
}

export async function archiveBankSet(setId: string): Promise<BankSet> {
  const { data } = await http.post(`/question-bank/sets/${setId}/archive`)
  return data
}

export async function getBankSetValidation(setId: string): Promise<{ issues: BankIssue[]; total: number }> {
  const { data } = await http.get(`/question-bank/sets/${setId}/validation`)
  return data
}

export async function aiCleanQuestion(questionId: string): Promise<BankQuestion> {
  const { data } = await http.post(`/question-bank/questions/${questionId}/ai-clean`, null, { timeout: 120000 })
  return data
}

export async function getBankStats(): Promise<BankStats> {
  const { data } = await http.get('/question-bank/stats')
  return data
}

export async function listBankBlueprints(): Promise<BankBlueprint[]> {
  const { data } = await http.get('/question-bank/blueprints')
  return data
}

export async function createBankBlueprint(payload: {
  name: string
  subject?: string | null
  level?: string | null
  rules: Record<string, number>
}): Promise<BankBlueprint> {
  const { data } = await http.post('/question-bank/blueprints', payload)
  return data
}

export async function deleteBankBlueprint(id: string): Promise<void> {
  await http.delete(`/question-bank/blueprints/${id}`)
}

export async function composeBankQuestions(payload: {
  rules: Record<string, number>
  subject?: string
  level?: string
  institution?: string
  exam_year?: number
}): Promise<{ questions: AttemptQuestion[] }> {
  const { data } = await http.post('/question-bank/compose', payload)
  return data
}

export async function getComposeAvailability(
  params: { subject?: string; level?: string; institution?: string; exam_year?: number } = {},
): Promise<Record<string, number>> {
  const { data } = await http.get('/question-bank/compose/availability', { params })
  return data
}

export async function aggregateSubjects(): Promise<{ subjects: string[]; levels: string[] }> {
  const { data } = await http.get('/question-bank/aggregates/subjects')
  return data
}

export async function aggregatePractice(payload: AggregatePracticeIn): Promise<AggregateQuestionOut[]> {
  const { data } = await http.post('/question-bank/aggregates/practice', payload)
  return data
}

export async function toggleAggregateMark(
  questionId: string,
  kind: 'favorite' | 'wrong',
  enabled: boolean,
): Promise<{ saved: boolean; kind: string; enabled: boolean }> {
  const { data } = await http.post(`/question-bank/aggregates/${questionId}/mark`, { kind, enabled })
  return data
}

export async function listAggregateMarks(kind?: 'favorite' | 'wrong'): Promise<AggregateMark[]> {
  const { data } = await http.get('/question-bank/aggregates/marks', { params: kind ? { kind } : undefined })
  return data
}

export async function checkAggregateAnswer(
  questionId: string,
  answer: unknown,
): Promise<AggregateCheckOut> {
  const { data } = await http.post('/question-bank/aggregates/check', { question_id: questionId, answer })
  return data
}

export type AttemptKind = 'quick' | 'aggregate' | 'marked' | 'set_practice' | 'exam_set' | 'exam_random'

export async function startPracticeAttempt(payload: {
  student_id?: string
  mode?: 'practice' | 'exam'
  kind?: AttemptKind
  set_id?: string
  blueprint_id?: string
  rules?: Record<string, number>
  subject?: string
  level?: string
  institution?: string
  exam_year?: number
  mark_kind?: 'favorite' | 'wrong'
}): Promise<PracticeAttemptOut> {
  const { data } = await http.post('/question-bank/attempts', payload)
  return data
}

export async function listPracticeAttempts(
  studentId?: string,
  params: { limit?: number; offset?: number; kind?: string; status?: string } = {},
): Promise<{ items: AttemptSummary[]; total: number }> {
  const query = { ...params, ...(studentId ? { student_id: studentId } : {}) }
  const { data } = await http.get('/question-bank/attempts', { params: query })
  return data
}

export interface AttemptTrendWeek {
  week_start: string
  avg_score: number
  attempts: number
}

export async function getAttemptTrend(
  studentId?: string,
  days = 56,
): Promise<{ weeks: AttemptTrendWeek[] }> {
  const { data } = await http.get('/question-bank/attempts/trend', {
    params: { ...(studentId ? { student_id: studentId } : {}), days },
  })
  return data
}

export async function closePracticeAttempt(id: string): Promise<PracticeAttemptOut> {
  const { data } = await http.post(`/question-bank/attempts/${id}/close`)
  return data
}

export async function getPracticeAttempt(id: string): Promise<PracticeAttemptOut> {
  const { data } = await http.get(`/question-bank/attempts/${id}`)
  return data
}

export async function saveAttemptAnswer(
  attemptId: string,
  questionId: string,
  answer: unknown,
): Promise<{
  saved: boolean
  is_correct?: boolean | null
  correct_answer?: unknown
  analysis?: string | null
  reference_code?: string | null
  score?: number
  max_score?: number
}> {
  const { data } = await http.post(`/question-bank/attempts/${attemptId}/answers`, {
    question_id: questionId,
    answer,
  })
  return data
}

export async function selfEvaluateQuestion(attemptId: string, questionId: string, correct: boolean) {
  const { data } = await http.post(`/question-bank/attempts/${attemptId}/self-evaluate`, {
    question_id: questionId,
    correct,
  })
  return data
}

export async function submitPracticeAttempt(attemptId: string): Promise<PracticeAttemptOut> {
  const { data } = await http.post(`/question-bank/attempts/${attemptId}/submit`)
  return data
}

export async function getLearningStats(studentId: string, days = 30): Promise<LearningStatsOut> {
  const { data } = await http.get('/question-bank/learning-stats', {
    params: { student_id: studentId, days },
  })
  return data
}

export async function bankSetToAssignment(
  setId: string,
  payload: { title?: string; class_id?: string; question_ids?: string[] } = {},
): Promise<{ assignment_id: string; title: string; question_count: number }> {
  const { data } = await http.post(`/question-bank/sets/${setId}/to-assignment`, payload)
  return data
}

export interface BankStats {
  sets: number
  questions: number
  pending_review: number
}

export interface BankBlueprint {
  id: string
  name: string
  subject: string | null
  level: string | null
  rules: Record<string, number>
  created_at?: string
}

export interface AttemptQuestion {
  id: string
  order_no: number
  type: BankQuestionType
  stem: string
  options: string[] | null
  difficulty: number
  score: number
  language: string | null
  media: BankMedia[] | null
  knowledge_points: string[] | null
  answer?: unknown
  analysis?: string | null
  reference_code?: string | null
  favorite?: boolean
  wrong?: boolean
  marked?: boolean
}

export interface AttemptItemResult {
  id: string
  order_no: number
  type: BankQuestionType
  user_answer: unknown
  correct_answer: unknown
  analysis: string | null
  reference_code: string | null
  is_correct: boolean | null
  score: number
  max_score: number
  knowledge_points: string[]
}

export interface AttemptTypeStat {
  total: number
  correct: number
  correct_rate?: number
  score?: number
  max_score?: number
}

export interface PracticeAttemptOut {
  id: string
  user_id?: string | null
  student_id: string | null
  bank_set_id: string | null
  mode: 'practice' | 'exam'
  kind?: AttemptKind
  paper_title?: string | null
  paper_meta?: Record<string, unknown> | null
  status: 'in_progress' | 'submitted' | 'evaluated'
  score: number | null
  total_score: number | null
  started_at: string
  submitted_at: string | null
  result: {
    items: AttemptItemResult[]
    score: number
    total_score: number
    normalized_score?: number
    rating?: string | null
    correct_count: number
    question_count: number
    type_stats: Record<string, AttemptTypeStat>
  } | null
  answers: Record<string, unknown>
  question_results: Record<string, { is_correct?: boolean | null; score?: number; max_score?: number }>
  questions: AttemptQuestion[]
}

export interface AggregateQuestionOut {
  id: string
  order_no: number
  type: BankQuestionType
  stem: string
  options: string[] | null
  difficulty: number
  score: number
  language: string | null
  media: BankMedia[] | null
  knowledge_points: string[] | null
  favorite: boolean
  wrong: boolean
}

/** 练习面板使用的轻量题目；试卷题目与聚合抽取题目均可兼容 */
export interface PracticeQuestion {
  id: string
  order_no: number
  type: BankQuestionType
  stem: string
  options: string[] | null
  difficulty: number
  score: number
  language: string | null
  media: BankMedia[] | null
  knowledge_points: string[] | null
  answer?: unknown
  favorite?: boolean
  wrong?: boolean
  analysis?: string | null
  reference_code?: string | null
  test_cases?: unknown[] | null
  source_excerpt?: string | null
  status?: BankQuestion['status']
  review_note?: string | null
  marked?: boolean
}

export interface AggregatePracticeIn {
  subject?: string | null
  level?: string | null
  institution?: string | null
  exam_year?: number | null
  mark_kind?: 'favorite' | 'wrong' | null
  rules?: Record<string, number>
  exclude_ids?: string[]
}

export interface AggregateMark {
  kind: 'favorite' | 'wrong'
  question_id: string
}

export interface AggregateCheckOut {
  is_correct: boolean | null
  correct_answer: unknown
  analysis: string | null
  reference_code: string | null
  score: number
  max_score: number
}

export interface AttemptSummary {
  id: string
  mode: string
  kind?: AttemptKind
  paper_title?: string | null
  status: string
  score: number | null
  total_score: number | null
  normalized_score?: number | null
  rating?: string | null
  correct_count: number | null
  question_count: number | null
  correct_rate?: number | null
  started_at: string
  submitted_at: string | null
}

export interface LearningStatsOut {
  attempts: number
  submitted: number
  total_questions: number
  correct_rate: number
  avg_score_rate: number
  best_score_rate: number
  type_stats: Record<string, { total: number; correct: number; correct_rate: number }>
  knowledge_stats?: { name: string; total: number; correct: number; correct_rate: number }[]
  radar?: { name: string; total: number; correct: number; correct_rate: number }[]
  weak_points: { name: string; wrong: number }[]
  streak_days: number
  recent: {
    id: string
    mode: string
    kind?: AttemptKind
    paper_title?: string | null
    score: number | null
    total_score: number | null
    normalized_score?: number | null
    rating?: string | null
    submitted_at: string | null
  }[]
}

export interface AiStatusOut {
  module: string
  configured: boolean
  model: string | null
  config_name: string | null
  is_platform: boolean
  source?: 'module' | 'default' | 'env' | null
}

export interface AiReviewOut {
  id: string
  question_id: string
  kind: string
  status: string
  model: string | null
  confidence: number | null
  issues: BankIssue[] | null
  before: Record<string, unknown> | null
  after: Record<string, unknown> | null
  reasons: string[] | null
  cached?: boolean
  applied?: boolean
}

export async function getQuestionBankAiStatus(): Promise<AiStatusOut> {
  const { data } = await http.get('/question-bank/ai-status')
  return data
}

export async function aiValidateQuestion(
  questionId: string,
  apply = true,
): Promise<{ review: AiReviewOut; question: BankQuestion; applied: boolean; cached?: boolean }> {
  const { data } = await http.post(
    `/question-bank/questions/${questionId}/ai-validate`,
    { apply },
    { timeout: 120000 },
  )
  return data
}

export async function revertAiReview(questionId: string): Promise<BankQuestion> {
  const { data } = await http.post(`/question-bank/questions/${questionId}/ai-validate/revert`)
  return data
}

export async function aiTagBankSet(
  setId: string,
  questionIds?: string[],
): Promise<{ tagged: number; skipped: number; failed: number; items: { question_id: string; knowledge_points: string[] }[] }> {
  const { data } = await http.post(
    `/question-bank/sets/${setId}/ai-tag`,
    { question_ids: questionIds ?? null },
    { timeout: 180000 },
  )
  return data
}

export async function getAbilityComment(studentId?: string, days = 30): Promise<{ content: string; model: string | null; cached: boolean }> {
  const { data } = await http.post('/question-bank/ability-comment', {
    student_id: studentId ?? null,
    days,
  })
  return data
}

