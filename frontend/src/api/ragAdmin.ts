import http from './http'

export interface RagAssetStats {
  documents: number
  ready: number
  indexing: number
  failed: number
  chunks: number
  enabled: number
  parent_visible: number
  plaza: number
  last_updated: string | null
}

export interface RagTraceStats {
  queries: number
  zero_results: number
  errors: number
  hits?: number
  hit_rate: number | null
  hit_rate_excl_errors?: number | null
  zero_result_rate: number | null
  error_rate?: number | null
  avg_latency_ms: number | null
  p95_latency_ms?: number | null
  avg_candidates?: number | null
  vector_fail: number
  vector_success_rate?: number | null
  keyword_used: number
  keyword_rate?: number | null
  rerank_fail: number
  rerank_attempts?: number
  rerank_success_rate?: number | null
  rag_status_counts?: { hit: number; no_hit: number; error: number }
}

export interface RagDomainStats {
  domain: string
  queries: number
  zero_results: number
  zero_result_rate: number | null
  avg_latency_ms: number | null
}

export interface RagCollectionStat {
  name: string
  count: number
  active: boolean
}

export interface RagOverview {
  assets: RagAssetStats
  retrieval_24h: RagTraceStats
  retrieval_7d: RagTraceStats
  domains_7d: RagDomainStats[]
  collections: { active: string; collections: RagCollectionStat[] }
  risks: { level: string; title: string; detail: string }[]
  recent_errors: RagTrace[]
  latest_eval?: {
    id: string
    status: string
    top_k: number
    rerank: boolean
    answer_eval: boolean
    generation_model?: string
    judge_model?: string
    metrics: Record<string, any> | null
    compare: Record<string, any> | null
    created_at: string | null
    finished_at: string | null
  } | null
}

export interface RagStorageProfile {
  collection: string
  parent_dedicated?: boolean | null
  embedding: {
    provider: string
    model: string
    base_url: string
    fingerprint: string
  }
  vector_dim: number | null
  vector_sample: number[]
  chunk_count: number
  char_count: number
  tokens_est: number
  chunk_chars: { min: number; max: number; avg: number }
  chunk_config: { chunk_size: number; chunk_overlap: number; parent_chunk_size: number }
  source: { file_name: string; file_size: number; file_hash: string }
  indexed_at: string | null
  profile_snapshot: Record<string, unknown> | null
  live: boolean
}

export interface RagDoc {
  id: string
  title: string
  description: string
  owner_id: string
  owner_name: string
  visibility: string
  enabled: boolean
  visible_to_parents: boolean
  file_name: string
  status: string
  error: string | null
  chunk_count: number
  progress?: { stage: string; percent: number; detail: string } | null
  indexed_hash?: string | null
  created_at: string | null
  updated_at: string | null
  storage?: RagStorageProfile
  parent_storage?: RagStorageProfile | null
}

export interface RagChunk {
  id: string
  chunk_no: number | null
  title: string
  chars: number
  tokens_est?: number
  preview: string
  has_parent: boolean
  parent_chars?: number
}

export interface RagTraceHit {
  doc_id: string
  title: string
  similarity: number | null
  rerank_score: number | null
  rrf_score: number | null
  preview: string
}

export interface RagTrace {
  id: string
  trace_id: string
  domain: string
  user_id: string | null
  owner_id: string | null
  conversation_id: string | null
  message_id: string | null
  route: string
  query: string
  rewritten_query: string
  filters: Record<string, unknown> | null
  embedding_fingerprint: string
  vector_candidates: number
  keyword_candidates: number
  rerank_candidates: number
  gated_out: number
  vector_ok: boolean
  keyword_used: boolean
  rerank_ok: boolean
  rerank_model: string
  zero_result: boolean
  is_error: boolean
  rag_status: string
  error: string | null
  latency_ms: number
  stage_timings: Record<string, number> | null
  hits: RagTraceHit[] | null
  feedback: string | null
  related_runs?: { run_id: string; agent_id: string; intent: string; task_kind: string; status: string; needs_rag: boolean; rag_decision: string; latency_ms: number; created_at: string | null }[]
  created_at: string | null
}

export interface RagConfig {
  [key: string]: unknown
}

export interface RagConfigVersion {
  version: number
  config: RagConfig
  diff: Record<string, { old: unknown; new: unknown }> | null
  note: string
  updated_by: string | null
  created_at: string | null
}

export async function getRagOverview(): Promise<RagOverview> {
  const { data } = await http.get<RagOverview>('/admin/rag/overview')
  return data
}

export async function listRagDocuments(params: Record<string, unknown> = {}): Promise<{ total: number; items: RagDoc[] }> {
  const { data } = await http.get('/admin/rag/documents', { params })
  return data
}

export async function getRagDocument(id: string): Promise<RagDoc & { extra?: Record<string, unknown> }> {
  const { data } = await http.get(`/admin/rag/documents/${id}`)
  return data
}

export async function getRagDocumentChunks(id: string): Promise<RagChunk[]> {
  const { data } = await http.get<{ items: RagChunk[] }>(`/admin/rag/documents/${id}/chunks`)
  return data.items
}

export async function reindexRagDocument(id: string): Promise<RagDoc> {
  const { data } = await http.post(`/admin/rag/documents/${id}/reindex`)
  return data
}

export async function toggleRagDocument(id: string, enabled?: boolean): Promise<RagDoc> {
  const { data } = await http.post(`/admin/rag/documents/${id}/toggle`, null, { params: { enabled } })
  return data
}

export async function toggleRagParentVisible(id: string, visible?: boolean): Promise<RagDoc> {
  const { data } = await http.post(`/admin/rag/documents/${id}/parent-visible`, null, { params: { visible } })
  return data
}

export async function deleteRagDocument(id: string): Promise<void> {
  await http.delete(`/admin/rag/documents/${id}`)
}

export async function listKnowledgeBases(): Promise<{ items: any[] }> {
  const { data } = await http.get('/admin/rag/knowledge-bases')
  return data
}

export async function listRagCollections(): Promise<{ active: string; collections: RagCollectionStat[] }> {
  const { data } = await http.get('/admin/rag/collections')
  return data
}

export async function sweepRagCollections(dryRun = false): Promise<any> {
  const { data } = await http.post('/admin/rag/collections/sweep', null, { params: { dry_run: dryRun } })
  return data
}

export async function triggerRagSync(limit = 50): Promise<any> {
  const { data } = await http.post('/admin/rag/maintenance/sync', null, { params: { limit } })
  return data
}

export async function listRagRoutes(): Promise<{ items: any[] }> {
  const { data } = await http.get('/admin/rag/routes')
  return data
}

export async function updateRagRoute(routeKey: string, payload: Record<string, unknown>): Promise<any> {
  const { data } = await http.put(`/admin/rag/routes/${routeKey}`, payload)
  return data
}

export async function testRagRoute(payload: Record<string, unknown>): Promise<any> {
  const { data } = await http.post('/admin/rag/routes/test', payload)
  return data
}

export async function listRagTraces(params: Record<string, unknown> = {}): Promise<{ total: number; items: RagTrace[] }> {
  const { data } = await http.get('/admin/rag/traces', { params })
  return data
}

export async function getRagTrace(traceId: string): Promise<RagTrace> {
  const { data } = await http.get(`/admin/rag/traces/${traceId}`)
  return data
}

export async function listParentSessions(params: Record<string, unknown> = {}): Promise<{ total: number; page: number; page_size: number; items: any[] }> {
  const { data } = await http.get('/admin/rag/parent-sessions', { params })
  return data
}

export async function getParentSession(threadId: string): Promise<{ thread: any; messages: any[]; traces: RagTrace[] }> {
  const { data } = await http.get(`/admin/rag/parent-sessions/${threadId}`)
  return data
}

export async function setRagTraceFeedback(traceId: string, feedback: string): Promise<void> {
  await http.post(`/admin/rag/traces/${traceId}/feedback`, { feedback })
}

export async function getRagConfig(): Promise<{ config: RagConfig; defaults: RagConfig }> {
  const { data } = await http.get('/admin/rag/config')
  return data
}

export async function updateRagConfig(config: RagConfig, note = ''): Promise<any> {
  const { data } = await http.put('/admin/rag/config', { config, note })
  return data
}

export async function listRagConfigVersions(): Promise<RagConfigVersion[]> {
  const { data } = await http.get<{ items: RagConfigVersion[] }>('/admin/rag/config/versions')
  return data.items
}

export async function rollbackRagConfig(version: number): Promise<any> {
  const { data } = await http.post(`/admin/rag/config/rollback/${version}`)
  return data
}

export async function listRagAudit(limit = 100): Promise<any[]> {
  const { data } = await http.get<{ items: any[] }>('/admin/rag/audit', { params: { limit } })
  return data.items
}

// —— 评测 ——

export interface RagEvalSet {
  id: string
  name: string
  description: string
  domain: string
  owner_id: string | null
  created_by: string | null
  created_at: string | null
  updated_at: string | null
}

export interface RagEvalCase {
  id: string
  set_id: string
  query: string
  relevant: string[]
  answerability: 'answerable' | 'unanswerable' | 'unlabeled'
  split: 'tuning' | 'regression' | 'frozen'
  business_criticality: 'critical' | 'important' | 'normal'
  gt_answer: string
  gt_keywords: string[]
  query_type: string
  difficulty: string
  notes: string
  source: string
  created_at: string | null
}

export interface RagEvalRun {
  id: string
  set_id: string
  status: string
  total_cases: number
  processed_cases: number
  stage: string
  progress: number
  owner_id: string | null
  top_k: number
  rerank: boolean
  retrieval_mode: string
  answer_eval: boolean
  generation_config_id: string | null
  judge_config_id: string | null
  generation_model: string
  judge_model: string
  config_version: number | null
  metrics: any
  compare: any
  error: string | null
  created_at: string | null
  finished_at: string | null
}

export interface RagEvalModel {
  id: string
  name: string
  model: string
  base_url: string
  is_default: boolean
}

export interface RagEvalCasePage {
  items: RagEvalCase[]
  total: number
  page: number
  page_size: number
}

export interface RagEvalResult {
  id: string
  run_id: string
  case_id: string | null
  query: string
  ranked: string[]
  relevant: string[]
  hits: RagTraceHit[]
  metrics: any
  retrieval_summary: string
  bad_case_type: string
  human_score: number | null
  human_judge: string | null
  human_at: string | null
  human_reason: string | null
  created_at: string | null
}

export async function listEvalSets(): Promise<RagEvalSet[]> {
  const { data } = await http.get<{ items: RagEvalSet[] }>('/admin/rag/eval/sets')
  return data.items
}

export async function createEvalSet(payload: Record<string, unknown>): Promise<RagEvalSet> {
  const { data } = await http.post('/admin/rag/eval/sets', payload)
  return data
}

export async function deleteEvalSet(id: string): Promise<void> {
  await http.delete(`/admin/rag/eval/sets/${id}`)
}

export async function listEvalModels(ownerId?: string | null): Promise<RagEvalModel[]> {
  const { data } = await http.get<{ items: RagEvalModel[] }>('/admin/rag/eval/models', {
    params: ownerId ? { owner_id: ownerId } : undefined,
  })
  return data.items
}

export async function listEvalCases(
  setId: string,
  params: { page?: number; page_size?: number } = {},
): Promise<RagEvalCasePage> {
  const { data } = await http.get<RagEvalCasePage>(`/admin/rag/eval/sets/${setId}/cases`, {
    params,
  })
  return data
}

export async function addEvalCase(setId: string, payload: Record<string, unknown>): Promise<RagEvalCase> {
  const { data } = await http.post(`/admin/rag/eval/sets/${setId}/cases`, payload)
  return data
}

export async function addEvalCasesBulk(
  setId: string,
  payload: { cases: Record<string, unknown>[]; skip_duplicates?: boolean },
): Promise<{
  created: number
  failed: number
  skipped_duplicates: number
  items: RagEvalCase[]
  errors: { index: number; error: string }[]
}> {
  const { data } = await http.post(`/admin/rag/eval/sets/${setId}/cases/bulk`, payload)
  return data
}

export async function deleteEvalCase(caseId: string): Promise<void> {
  await http.delete(`/admin/rag/eval/cases/${caseId}`)
}

export async function updateEvalCase(
  caseId: string, payload: {
    query?: string
    relevant?: string[]
    answerability?: string
    split?: string
    business_criticality?: string
    gt_answer?: string
    gt_keywords?: string[]
    query_type?: string
    difficulty?: string
    notes?: string
  },
): Promise<RagEvalCase> {
  const { data } = await http.put(`/admin/rag/eval/cases/${caseId}`, payload)
  return data
}

export async function generateEvalCases(setId: string, payload: Record<string, unknown>): Promise<any> {
  const { data } = await http.post(`/admin/rag/eval/sets/${setId}/generate`, payload)
  return data
}

export async function createEvalCaseFromTrace(
  setId: string, payload: { trace_id: string; relevant?: string[]; answerability?: string; split?: string; business_criticality?: string; query_type?: string; difficulty?: string; notes?: string },
): Promise<RagEvalCase> {
  const { data } = await http.post(`/admin/rag/eval/sets/${setId}/cases/from-trace`, payload)
  return data
}

export async function createEvalRun(setId: string, payload: Record<string, unknown>): Promise<RagEvalRun> {
  const { data } = await http.post(`/admin/rag/eval/sets/${setId}/runs`, payload)
  return data
}

export async function listEvalRuns(setId?: string): Promise<RagEvalRun[]> {
  const { data } = await http.get<{ items: RagEvalRun[] }>('/admin/rag/eval/runs', { params: { set_id: setId } })
  return data.items
}

export async function getEvalRun(runId: string): Promise<{ run: RagEvalRun; results: RagEvalResult[] }> {
  const { data } = await http.get(`/admin/rag/eval/runs/${runId}`)
  return data
}

export async function setEvalResultHumanScore(
  resultId: string, payload: { score: number; judge?: string; reason?: string },
): Promise<{ result_id: string; run_id: string; human_score: number; calibration: any }> {
  const { data } = await http.post(`/admin/rag/eval/results/${resultId}/human-score`, payload)
  return data
}
