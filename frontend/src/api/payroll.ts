import http from './http'

// ---------- 教师级别 ----------

export interface TeacherLevelOut {
  id: string
  name: string
  ratio: string
  ratio_pct: string
  active: boolean
  sort: number
}

export async function listTeacherLevels(includeInactive = false): Promise<TeacherLevelOut[]> {
  const { data } = await http.get<{ items: TeacherLevelOut[] }>('/business/teacher-levels', {
    params: includeInactive ? { include_inactive: true } : {},
  })
  return data.items
}

export async function createTeacherLevel(payload: {
  name: string
  ratio: string
}): Promise<TeacherLevelOut> {
  const { data } = await http.post<TeacherLevelOut>('/business/teacher-levels', payload)
  return data
}

export async function updateTeacherLevel(
  id: string,
  payload: { name?: string; ratio?: string; active?: boolean },
): Promise<TeacherLevelOut> {
  const { data } = await http.patch<TeacherLevelOut>(`/business/teacher-levels/${id}`, payload)
  return data
}

export async function deleteTeacherLevel(id: string): Promise<void> {
  await http.delete(`/business/teacher-levels/${id}`)
}

// ---------- 提成规则 ----------

export interface CommissionRuleOut {
  id?: string
  key: string
  label: string
  amount: string
  unit: string
  active?: boolean
}

export async function listCommissionRules(): Promise<CommissionRuleOut[]> {
  const { data } = await http.get<{ items: CommissionRuleOut[] }>(
    '/business/commission-rules',
  )
  return data.items
}

export async function updateCommissionRules(
  payload: { key: string; label?: string; amount: string; unit?: string }[],
): Promise<CommissionRuleOut[]> {
  const { data } = await http.put<{ items: CommissionRuleOut[] }>(
    '/business/commission-rules',
    payload,
  )
  return data.items
}

// ---------- 职务工资（与权限职务预设同源） ----------

export interface PostOut {
  id: string
  name: string
  base_salary: string
  hint?: string
}

export async function listPosts(): Promise<PostOut[]> {
  const { data } = await http.get<{ items: PostOut[] }>('/business/posts')
  return data.items
}

export async function createPost(payload: {
  name: string
  base_salary: string
}): Promise<PostOut> {
  const { data } = await http.post<PostOut>('/business/posts', payload)
  return data
}

export async function updatePost(
  id: string,
  payload: { name: string; base_salary: string },
): Promise<PostOut> {
  const { data } = await http.patch<PostOut>(`/business/posts/${id}`, payload)
  return data
}

// ---------- 薪资核算 / 教务工作台 ----------

export interface PayrollComputeIn {
  user_id: string
  month: string
  invite_count?: number
  trial_count?: number
  convert_count?: number
  renew_count?: number
  refer_count?: number
  trial_lesson_count?: number
  lesson_commission?: string
}

export async function computePayroll(payload: PayrollComputeIn): Promise<Record<string, string>> {
  const { data } = await http.post('/business/payroll/compute', payload)
  return data
}

export async function listPayroll(month?: string): Promise<{ items: Record<string, unknown>[] }> {
  const { data } = await http.get('/business/payroll', { params: month ? { month } : {} })
  return data
}

export interface WorkbenchItem {
  user_id: string
  name: string
  role: string
  title: string | null
  campus: string | null
  level: string | null
  base_salary: string
  total: string
  has_entry: boolean
}

export async function getWorkbench(month?: string): Promise<{
  month: string
  rules: Record<string, string>
  items: WorkbenchItem[]
}> {
  const { data } = await http.get('/business/workbench', {
    params: month ? { month } : {},
  })
  return data
}
