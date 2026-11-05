import http from './http'

export interface UsageSeriesPoint {
  day: string
  input_tokens: number
  output_tokens: number
  cost: number
  cost_platform: number
  cost_teacher: number
  events: number
}

export interface UsageGroupRow {
  module?: string
  kind?: string
  model?: string
  cost: number
  input_tokens: number
  output_tokens: number
  events: number
}

export interface UsageOwnerRow {
  owner_id: string | null
  owner_name: string
  cost: number
  input_tokens: number
  output_tokens: number
  events: number
}

export interface UsageStats {
  days: number
  events: number
  provider_events: number
  estimated_events: number
  provider_ratio: number | null
  estimated_ratio: number | null
  error_events: number
  unpriced_events: number
  input_tokens: number
  output_tokens: number
  cost_estimate: number
  cost_platform: number
  cost_teacher: number
  currency: string
  series: UsageSeriesPoint[]
  by_module: UsageGroupRow[]
  by_kind: UsageGroupRow[]
  by_model: UsageGroupRow[]
  by_owner: UsageOwnerRow[]
  unpriced: { provider_host: string; model: string; events: number }[]
}

export interface UsageEvent {
  id: string
  created_at: string | null
  kind: string
  module: string
  owner_id: string | null
  owner_name: string
  is_platform: boolean
  provider_host: string
  model: string
  input_tokens: number
  output_tokens: number
  cached_tokens: number
  source: string
  cost: number
  currency: string
  priced_status: string
  latency_ms: number
  status: string
  run_id: string | null
  price_snapshot: Record<string, unknown>
  meta: Record<string, unknown>
}

export async function getUsageStats(days = 30): Promise<UsageStats> {
  const { data } = await http.get<UsageStats>('/admin/usage/stats', { params: { days } })
  return data
}

export async function listUsageEvents(
  params: Record<string, unknown> = {},
): Promise<{ total: number; page: number; page_size: number; items: UsageEvent[] }> {
  const { data } = await http.get('/admin/usage/events', { params })
  return data
}

export async function exportUsageCsv(params: Record<string, unknown> = {}): Promise<void> {
  const res = await http.get('/admin/usage/export', { params, responseType: 'blob' })
  const blob = new Blob([res.data], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `llm-usage-${new Date().toISOString().slice(0, 10)}.csv`
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

export interface ModelPrice {
  id: string
  provider_host: string
  model_pattern: string
  currency: string
  input_per_1m: number
  output_per_1m: number
  cache_read_per_1m: number
  cache_write_per_1m: number
  tiers: Record<string, unknown>[]
  time_windows: Record<string, unknown>[]
  effective_from: string | null
  source_note: string
  created_at: string | null
}

export type PricePayload = Omit<ModelPrice, 'id' | 'created_at'>

export async function listPrices(): Promise<ModelPrice[]> {
  const { data } = await http.get<{ items: ModelPrice[] }>('/admin/usage/prices')
  return data.items
}

export async function createPrice(payload: Partial<PricePayload>): Promise<ModelPrice> {
  const { data } = await http.post<ModelPrice>('/admin/usage/prices', payload)
  return data
}

export async function updatePrice(id: string, payload: Partial<PricePayload>): Promise<ModelPrice> {
  const { data } = await http.put<ModelPrice>(`/admin/usage/prices/${id}`, payload)
  return data
}

export async function deletePrice(id: string): Promise<void> {
  await http.delete(`/admin/usage/prices/${id}`)
}

export interface UsageBudget {
  monthly_budget: number
  alert_ratio: number
}

export async function getUsageSettings(): Promise<UsageBudget> {
  const { data } = await http.get<UsageBudget>('/admin/usage/settings')
  return data
}

export async function updateUsageSettings(payload: UsageBudget): Promise<UsageBudget> {
  const { data } = await http.put<UsageBudget>('/admin/usage/settings', payload)
  return data
}

export interface ReconciliationRow {
  id: string
  month: string
  provider: string
  billed_amount: number
  currency: string
  note: string
  ledger_cost: number
  diff: number
  diff_ratio: number | null
  updated_at: string | null
}

export interface LedgerProvider {
  provider_host: string
  currency: string
  cost: number
  input_tokens: number
  output_tokens: number
  events: number
}

export async function listReconciliations(
  month?: string,
): Promise<{ items: ReconciliationRow[]; ledger: { month: string; providers: LedgerProvider[] } }> {
  const { data } = await http.get('/admin/usage/reconciliations', { params: month ? { month } : {} })
  return data
}

export async function upsertReconciliation(payload: {
  month: string
  provider: string
  billed_amount: number
  currency?: string
  note?: string
}): Promise<ReconciliationRow> {
  const { data } = await http.post<ReconciliationRow>('/admin/usage/reconciliations', payload)
  return data
}

export async function deleteReconciliation(id: string): Promise<void> {
  await http.delete(`/admin/usage/reconciliations/${id}`)
}
