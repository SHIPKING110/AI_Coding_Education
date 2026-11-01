import http from './http'

export interface AgentRun {
  id: string
  run_id: string
  conversation_id: string | null
  message_id: string | null
  agent_id: string
  user_id: string | null
  domain: string
  intent: string
  intent_confidence: number
  intent_source: string
  needs_rag: boolean
  rag_decision: string
  rag_skip_reason: string
  retrieval_trace_id: string | null
  task_kind: string
  status: string
  started_at: string | null
  finished_at: string | null
  latency_ms: number
  first_token_ms: number
  model_calls: number
  tool_calls: number
  rag_calls: number
  mcp_calls: number
  skill_calls: number
  input_tokens: number
  output_tokens: number
  cost_estimate: number
  ppt_target_pages: number
  ppt_current_pages: number
  ppt_aligned: boolean
  ppt_project_key: string
  artifact_url: string
  error_code: string
  error_message: string
  attributes: Record<string, unknown>
  created_at: string | null
}

export interface AgentRunSpan {
  id: string
  run_id: string
  span_id: string
  parent_span_id: string | null
  span_type: string
  name: string
  status: string
  started_at: string | null
  ended_at: string | null
  latency_ms: number
  model: string
  provider: string
  input_tokens: number
  output_tokens: number
  cost_estimate: number
  summary: string
  error: string
  attributes: Record<string, unknown>
}

export interface AgentOpsStats {
  total_runs: number
  ok_runs: number
  error_runs: number
  success_rate: number | null
  needs_rag: number
  rag_used: number
  rag_skipped: number
  rag_missed: number
  rag_miss_rate: number | null
  ppt_runs: number
  ppt_aligned: number
  ppt_alignment_rate: number | null
  avg_latency_ms: number | null
  p95_latency_ms: number | null
  input_tokens: number
  output_tokens: number
  cost_estimate: number
  intents: { intent: string; runs: number }[]
  rag_decisions: { decision: string; runs: number }[]
}

export async function listAgentRuns(params: Record<string, unknown> = {}): Promise<{
  total: number
  page: number
  page_size: number
  items: AgentRun[]
}> {
  const { data } = await http.get('/admin/agent-ops/runs', { params })
  return data
}

export async function getAgentOpsStats(days = 7): Promise<AgentOpsStats> {
  const { data } = await http.get('/admin/agent-ops/stats', { params: { days } })
  return data
}

export async function getAgentRun(runId: string): Promise<{ run: AgentRun; spans: AgentRunSpan[] }> {
  const { data } = await http.get(`/admin/agent-ops/runs/${runId}`)
  return data
}
