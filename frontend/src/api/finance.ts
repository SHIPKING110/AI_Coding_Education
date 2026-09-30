import http from './http'

// ---------- finance types ----------

export interface FinanceBucket {
  label: string
  revenue: string
  commission: string
  refunds: string
  net: string
}

export interface FinanceTotals {
  revenue: string
  commission: string
  refunds: string
  net: string
}

export interface SubjectStat {
  subject: string
  lessons: string
  revenue: string
  commission: string
  sessions: number
}

export interface TeacherStat {
  teacher_id: string | null
  teacher_name: string
  lessons: string
  revenue: string
  commission: string
  sessions: number
}

export interface OrderStatBucket {
  label: string
  orders: number
  order_amount: string
  paid: number
  unpaid: number
  refunded_count: number
  paid_amount: string
  refunds: string
}

export interface OrderStatsSummary {
  orders: number
  paid: number
  unpaid: number
  refunded_count: number
  pay_rate: number
  order_amount: string
  paid_amount: string
  refunds: string
}

export interface LessonStats {
  planned_lessons: string
  consumed_lessons: string
  consume_rate: number
  revenue: string
  commission: string
  profit: string
  sessions: number
  daily: { label: string; lessons: string }[]
}

export interface FinanceQuery {
  granularity?: 'day' | 'month' | 'quarter' | 'year'
  date_from?: string
  date_to?: string
  campus?: string
}

// ---------- API ----------

export async function getFinanceOverview(
  params: FinanceQuery = {},
): Promise<{ granularity: string; items: FinanceBucket[]; totals: FinanceTotals }> {
  const { data } = await http.get('/finance/overview', { params })
  return data
}

export async function getFinanceBySubject(
  params: FinanceQuery = {},
): Promise<{ items: SubjectStat[] }> {
  const { data } = await http.get('/finance/by-subject', { params })
  return data
}

export async function getFinanceByTeacher(
  params: FinanceQuery = {},
): Promise<{ items: TeacherStat[] }> {
  const { data } = await http.get('/finance/by-teacher', { params })
  return data
}

export async function getOrderStats(
  params: FinanceQuery = {},
): Promise<{ items: OrderStatBucket[]; summary: OrderStatsSummary }> {
  const { data } = await http.get('/finance/order-stats', { params })
  return data
}

export async function getLessonStats(params: FinanceQuery = {}): Promise<LessonStats> {
  const { data } = await http.get('/finance/lesson-stats', { params })
  return data
}
