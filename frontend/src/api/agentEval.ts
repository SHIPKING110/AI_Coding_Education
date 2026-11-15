/**
 * Agent 行为评测 API：评测集 / 用例 / 运行 / 结果 / 对比 / 人工复核。
 * 与检索评测（ragAdmin）同一权限域，独立数据模型（agent_eval_*）。
 */

import http from './http'

export interface AgentEvalSet {
  id: string
  name: string
  description: string
  agent_scope: string
  case_count?: number
  created_at: string | null
  updated_at: string | null
}

export interface AgentEvalCase {
  id: string
  set_id: string
  query: string
  messages: { role: string; content: string }[] | null
  expected_tools: string[]
  allowed_extra_tools: string[]
  forbidden_tools: string[]
  expect_abstain: boolean
  expected_facts: string[]
  split: string
  business_criticality: string
  notes: string
  source: string
  created_at: string | null
}

export interface AgentEvalMetrics {
  cases?: number
  tool_recall?: number | null
  tool_precision?: number | null
  seq_score?: number | null
  first_tool_hit?: number | null
  forbidden_rate?: number | null
  abstention_rate?: number | null
  abstention_cases?: number
  fact_coverage?: number | null
  pass_rate?: number | null
  errors?: number
  cost?: number
  latency_ms_avg?: number
}

export interface AgentEvalRun {
  id: string
  set_id: string
  status: string
  stage: string
  progress: number
  total_cases: number
  processed_cases: number
  agent_id: string
  model_config_id: string | null
  model_name: string
  metrics: { overall?: AgentEvalMetrics; splits?: Record<string, AgentEvalMetrics> } | null
  gate: { gate?: string; reasons?: string[]; frozen_cases?: number } | null
  error: string | null
  created_at: string | null
  finished_at: string | null
}

export interface AgentEvalToolCall {
  name: string
  type: string
  status: string
  latency_ms: number
  error: string
}

export interface AgentEvalResult {
  id: string
  run_id: string
  case_id: string | null
  query: string
  trace_run_id: string
  final_text: string
  expected_tools: string[]
  tool_calls: AgentEvalToolCall[]
  metrics: (Record<string, unknown> & {
    tool_recall?: number | null
    tool_precision?: number | null
    seq_score?: number | null
    first_tool_hit?: boolean | null
    forbidden_hit?: boolean
    abstained?: boolean
    expect_abstain?: boolean
    fact_coverage?: number | null
    bad_case_type?: string
    passed?: boolean
    cost?: number
    latency_ms?: number
  }) | null
  error: string | null
  human_score: number | null
  human_judge: string | null
  human_at: string | null
  human_reason: string | null
}

export interface Paged<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface AgentEvalModel {
  id: string
  name: string
  model: string
  is_default?: boolean
}

// —— 评测集 ——
export async function listSets(): Promise<AgentEvalSet[]> {
  const { data } = await http.get<{ items: AgentEvalSet[] }>('/admin/agent-eval/sets')
  return data.items
}

export async function createSet(payload: { name: string; description?: string }): Promise<AgentEvalSet> {
  const { data } = await http.post<AgentEvalSet>('/admin/agent-eval/sets', payload)
  return data
}

export async function deleteSet(id: string): Promise<void> {
  await http.delete(`/admin/agent-eval/sets/${id}`)
}

export async function seedDefault(): Promise<{ created: number; skipped: number; set_id: string | null }> {
  const { data } = await http.post('/admin/agent-eval/seed-default')
  return data
}

// —— 用例 ——
export async function listCases(
  setId: string,
  params: { page?: number; page_size?: number; split?: string } = {},
): Promise<Paged<AgentEvalCase>> {
  const { data } = await http.get<Paged<AgentEvalCase>>(`/admin/agent-eval/sets/${setId}/cases`, { params })
  return data
}

export async function addCase(setId: string, payload: Partial<AgentEvalCase>): Promise<AgentEvalCase> {
  const { data } = await http.post<AgentEvalCase>(`/admin/agent-eval/sets/${setId}/cases`, payload)
  return data
}

export async function addCasesBulk(
  setId: string,
  cases: Record<string, unknown>[],
): Promise<{ created: number; skipped: number; errors: { line: number; error: string }[] }> {
  const { data } = await http.post(`/admin/agent-eval/sets/${setId}/cases/bulk`, { cases })
  return data
}

export async function updateCase(caseId: string, payload: Partial<AgentEvalCase>): Promise<AgentEvalCase> {
  const { data } = await http.put<AgentEvalCase>(`/admin/agent-eval/cases/${caseId}`, payload)
  return data
}

export async function deleteCase(caseId: string): Promise<void> {
  await http.delete(`/admin/agent-eval/cases/${caseId}`)
}

// —— 运行 ——
export async function createRun(
  setId: string,
  payload: { agent_id?: string; model_config_id?: string | null } = {},
): Promise<AgentEvalRun> {
  const { data } = await http.post<AgentEvalRun>(`/admin/agent-eval/sets/${setId}/runs`, payload)
  return data
}

export async function listRuns(setId?: string, params: { page?: number; page_size?: number } = {}): Promise<Paged<AgentEvalRun>> {
  const { data } = await http.get<Paged<AgentEvalRun>>('/admin/agent-eval/runs', {
    params: { set_id: setId, ...params },
  })
  return data
}

export async function getRun(runId: string): Promise<{ run: AgentEvalRun }> {
  const { data } = await http.get<{ run: AgentEvalRun }>(`/admin/agent-eval/runs/${runId}`)
  return data
}

export async function listResults(
  runId: string,
  params: { page?: number; page_size?: number; only_bad?: boolean } = {},
): Promise<Paged<AgentEvalResult>> {
  const { data } = await http.get<Paged<AgentEvalResult>>(`/admin/agent-eval/runs/${runId}/results`, { params })
  return data
}

export interface AgentEvalCompare {
  run: AgentEvalRun
  base: AgentEvalRun
  overall_diff: Record<string, { base: number; now: number; delta: number }>
  frozen_diff: Record<string, { base: number; now: number; delta: number }>
  changes: { case_id: string; query: string; was: string; now: string; old_type?: string; new_type?: string }[]
}

export async function compareRuns(runId: string, baseId: string): Promise<AgentEvalCompare> {
  const { data } = await http.get<AgentEvalCompare>(`/admin/agent-eval/runs/${runId}/compare`, {
    params: { base_id: baseId },
  })
  return data
}

export async function setHumanScore(
  resultId: string,
  payload: { score: number; judge?: string; reason?: string },
): Promise<AgentEvalResult> {
  const { data } = await http.post<AgentEvalResult>(`/admin/agent-eval/results/${resultId}/human-score`, payload)
  return data
}
