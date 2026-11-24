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

export interface BankSet {
  id: string
  source_id: string
  name: string
  institution: string | null
  exam_year: number | null
  subject: string | null
  level: string | null
  total_score: number | null
  status: 'draft' | 'reviewed' | 'published' | 'archived'
  question_count: number | null
  import_meta: {
    sections?: { name: string; count: number; score: number; type: string | null }[]
    warnings?: string[]
    parser?: string
  } | null
  created_at: string
  questions?: BankQuestion[]
}

export async function importBankDocx(
  file: File,
  meta: { name?: string; institution?: string; exam_year?: number | string; subject?: string; level?: string } = {},
): Promise<{ source_id: string; set_id: string; question_count: number; warnings: string[] }> {
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
  payload: Partial<Pick<BankSet, 'name' | 'institution' | 'exam_year' | 'subject' | 'level'>>,
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

export async function startPracticeAttempt(payload: {
  student_id: string
  mode: 'practice' | 'exam'
  set_id?: string
  blueprint_id?: string
  rules?: Record<string, number>
  subject?: string
  level?: string
  institution?: string
  exam_year?: number
}): Promise<PracticeAttemptOut> {
  const { data } = await http.post('/question-bank/attempts', payload)
  return data
}

export async function listPracticeAttempts(
  studentId: string,
  params: { limit?: number; offset?: number } = {},
): Promise<{ items: AttemptSummary[]; total: number }> {
  const { data } = await http.get('/question-bank/attempts', { params: { student_id: studentId, ...params } })
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

export interface PracticeAttemptOut {
  id: string
  student_id: string
  bank_set_id: string | null
  mode: 'practice' | 'exam'
  status: 'in_progress' | 'submitted' | 'evaluated'
  score: number | null
  total_score: number | null
  started_at: string
  submitted_at: string | null
  result: {
    items: AttemptItemResult[]
    score: number
    total_score: number
    correct_count: number
    question_count: number
    type_stats: Record<string, { total: number; correct: number }>
  } | null
  answers: Record<string, unknown>
  questions: AttemptQuestion[]
}

export interface AttemptSummary {
  id: string
  mode: string
  status: string
  score: number | null
  total_score: number | null
  correct_count: number | null
  question_count: number | null
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
  weak_points: { name: string; wrong: number }[]
  streak_days: number
  recent: { id: string; mode: string; score: number | null; total_score: number | null; submitted_at: string | null }[]
}

