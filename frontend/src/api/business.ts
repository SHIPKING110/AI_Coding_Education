import http from './http'

// ---------- 类型 ----------

export interface CampusOut {
  id: string
  name: string
  active: boolean
  sort: number
}

export interface SubjectOut {
  id: string
  name: string
  per_session: string
  commission_rate: string | null
  active: boolean
  sort: number
}

export interface FinanceSettingOut {
  commission_default: string
  overdraft_max: string
  note: string | null
  formula?: {
    revenue: string
    commission: string
    net: string
  }
}

// ---------- 校区 ----------

export async function listCampuses(includeInactive = false): Promise<CampusOut[]> {
  const { data } = await http.get<{ items: CampusOut[] }>('/business/campuses', {
    params: includeInactive ? { include_inactive: true } : {},
  })
  return data.items
}

export async function createCampus(name: string): Promise<CampusOut> {
  const { data } = await http.post<CampusOut>('/business/campuses', { name })
  return data
}

export async function updateCampus(
  id: string,
  payload: { name?: string; active?: boolean },
): Promise<CampusOut> {
  const { data } = await http.patch<CampusOut>(`/business/campuses/${id}`, payload)
  return data
}

export async function reorderCampuses(ids: string[]): Promise<CampusOut[]> {
  const { data } = await http.post<{ items: CampusOut[] }>('/business/campuses/reorder', { ids })
  return data.items
}

// ---------- 科目 ----------

export async function listSubjects(includeInactive = false): Promise<SubjectOut[]> {
  const { data } = await http.get<{ items: SubjectOut[] }>('/business/subjects', {
    params: includeInactive ? { include_inactive: true } : {},
  })
  return data.items
}

export async function createSubject(payload: {
  name: string
  per_session: string
  commission_rate?: string | null
}): Promise<SubjectOut> {
  const { data } = await http.post<SubjectOut>('/business/subjects', payload)
  return data
}

export async function updateSubject(
  id: string,
  payload: {
    name?: string
    per_session?: string
    commission_rate?: string | null
    commission_rate_set?: boolean
    active?: boolean
  },
): Promise<SubjectOut> {
  const { data } = await http.patch<SubjectOut>(`/business/subjects/${id}`, payload)
  return data
}

// ---------- 财务参数 ----------

export async function getFinanceSetting(): Promise<FinanceSettingOut> {
  const { data } = await http.get<FinanceSettingOut>('/business/finance-setting')
  return data
}

export async function updateFinanceSetting(payload: {
  commission_default?: string
  overdraft_max?: string
  note?: string | null
}): Promise<FinanceSettingOut> {
  const { data } = await http.put<FinanceSettingOut>('/business/finance-setting', payload)
  return data
}
