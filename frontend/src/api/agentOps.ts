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
  rag_status?: string
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
  rag_status_counts: { used: number; skipped: number; error: number; needed: number; not_needed: number }
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
  task_kinds: { task_kind: string; runs: number }[]
  component_synergy: {
    rag_used: number
    tool_runs: number
    skill_runs: number
    mcp_runs: number
    pure_rag: number
    pure_tool: number
    rag_plus_tool: number
  }
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

export interface AgentSessionSummary {
  conversation_id: string
  title: string
  agent_id: string
  owner_id: string | null
  rag_enabled: boolean
  stage: string
  created_at: string | null
  updated_at: string | null
  message_count: number
  run_count: number
  ok_runs: number
  error_runs: number
  needs_rag: number
  rag_used: number
  intents: { intent: string; runs: number }[]
  last_run_at: string | null
}

export async function listAgentSessions(params: Record<string, unknown> = {}): Promise<{
  total: number
  page: number
  page_size: number
  items: AgentSessionSummary[]
}> {
  const { data } = await http.get('/admin/agent-ops/sessions', { params })
  return data
}

export async function getAgentSession(conversationId: string): Promise<{
  conversation: Record<string, unknown>
  messages: { id: string; role: string; content: string; created_at: string | null; run_id: string | null }[]
  runs: AgentRun[]
}> {
  const { data } = await http.get(`/admin/agent-ops/sessions/${conversationId}`)
  return data
}
