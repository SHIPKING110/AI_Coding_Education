import http from './http'
import type { RetrievalConfigIn, RetrievalConfigOut, RetrievalProvider } from './retrievalConfig'

export interface ParentThread {
  id: string
  status: string
  risk_flag: boolean
  parent_name?: string
  student_name?: string
  student_label?: string
  phone?: string
  campus_label?: string
  campuses?: string[]
  user_msg_count?: number
  created_at: string | null
  updated_at: string | null
}

export interface CitationRef {
  title: string
  doc_id?: string
  excerpt?: string
  similarity?: number | null
}

export interface ParentMessage {
  id: string
  role: string
  content: string
  created_at: string | null
  refs?: CitationRef[]
}

export interface ParentChatResult {
  thread: ParentThread
  answer: string | null
  refs: CitationRef[]
  citations?: { refs: CitationRef[]; summary: string }
  escalated: boolean
  kind?: string
  risk_word?: string
  guard?: string
  retrieval?: string
}

/** 家长问答（匿名需带 anon_key；登录家长带 JWT 即可） */
export async function parentChat(content: string, opts?: { thread_id?: string; anon_key?: string }): Promise<ParentChatResult> {
  const { data } = await http.post<ParentChatResult>('/parent-service/chat', {
    content,
    thread_id: opts?.thread_id ?? null,
    anon_key: opts?.anon_key ?? '',
  })
  return data
}

export async function parentEscalate(threadId: string): Promise<ParentChatResult['thread']> {
  const { data } = await http.post(`/parent-service/threads/${threadId}/escalate`)
  return data.thread
}

export async function parentMessages(threadId: string): Promise<{ thread: ParentThread; items: ParentMessage[] }> {
  const { data } = await http.get(`/parent-service/threads/${threadId}/messages`)
  return data
}

/** 教师接待列表（escalated 置顶；可按校区过滤） */
export async function staffServiceThreads(campus?: string): Promise<{ items: ParentThread[]; campuses: string[] }> {
  const { data } = await http.get<{ items: ParentThread[]; campuses: string[] }>('/teacher/service/threads', {
    params: campus ? { campus } : {},
  })
  return data
}

export async function staffServiceMessages(threadId: string): Promise<{ thread: ParentThread; items: ParentMessage[] }> {
  const { data } = await http.get(`/teacher/service/threads/${threadId}/messages`)
  return data
}

export async function staffServiceReply(threadId: string, content: string): Promise<void> {
  await http.post(`/teacher/service/threads/${threadId}/reply`, { content })
}

export async function staffServiceClose(threadId: string): Promise<void> {
  await http.post(`/teacher/service/threads/${threadId}/close`)
}

export interface QuickReply {
  id: string
  title: string
  content: string
  category: string
  enabled: boolean
  usage_count: number
  sort_order: number
  created_at: string | null
}

export interface ParentServiceConfigStatus {
  llm: { configured: boolean; module_bound: boolean; name: string; model: string }
  embedding: { configured: boolean; dedicated?: boolean; model: string; provider: string }
  rerank: { configured: boolean; model: string; provider: string }
  parent_visible_docs: number
  parent_index?: ParentIndexStatus
}

export async function staffQuickReplies(): Promise<QuickReply[]> {
  const { data } = await http.get<{ items: QuickReply[] }>('/teacher/service/quick-replies')
  return data.items
}

export async function createQuickReply(payload: { title?: string; content: string; category?: string }): Promise<QuickReply> {
  const { data } = await http.post<{ item: QuickReply }>('/teacher/service/quick-replies', payload)
  return data.item
}

export async function updateQuickReply(
  id: string,
  payload: { title?: string; content?: string; category?: string; enabled?: boolean },
): Promise<QuickReply> {
  const { data } = await http.patch<{ item: QuickReply }>(`/teacher/service/quick-replies/${id}`, payload)
  return data.item
}

export async function deleteQuickReply(id: string): Promise<void> {
  await http.delete(`/teacher/service/quick-replies/${id}`)
}

export async function useQuickReply(id: string): Promise<void> {
  await http.post(`/teacher/service/quick-replies/${id}/use`)
}

export async function parentServiceConfigStatus(): Promise<ParentServiceConfigStatus> {
  const { data } = await http.get<ParentServiceConfigStatus>('/teacher/service/config-status')
  return data
}

export interface ParentLLMConfigOut {
  config_id: string | null
  name: string
  model: string
  resolved_name: string
  resolved_model: string
}

export async function getParentLLMConfig(): Promise<ParentLLMConfigOut> {
  const { data } = await http.get<ParentLLMConfigOut>('/teacher/service/parent-llm-config')
  return data
}

export async function setParentLLMConfig(configId: string | null): Promise<void> {
  await http.post('/teacher/service/parent-llm-config', { config_id: configId })
}

export async function deleteParentLLMConfig(): Promise<void> {
  await http.delete('/teacher/service/parent-llm-config')
}

/** 家长客服共享 Rerank（管理员） */
export async function getParentRerankConfig(): Promise<RetrievalConfigOut | null> {
  const { data } = await http.get<{ configured: boolean } & Partial<RetrievalConfigOut>>('/teacher/service/parent-rerank-config')
  if (!data.configured) return null
  return data as RetrievalConfigOut
}

export async function saveParentRerankConfig(payload: RetrievalConfigIn): Promise<RetrievalConfigOut> {
  const { data } = await http.post<RetrievalConfigOut>('/teacher/service/parent-rerank-config', payload)
  return data
}

export async function deleteParentRerankConfig(): Promise<void> {
  await http.delete('/teacher/service/parent-rerank-config')
}

export async function testParentRerankConfig(): Promise<{
  ok: boolean
  latency_ms?: number
  error?: string
  note?: string
}> {
  const { data } = await http.post('/teacher/service/parent-rerank-config/test')
  return data
}

export interface ParentEmbeddingConfigOut {
  configured: boolean
  provider: RetrievalProvider
  base_url: string
  api_key_masked: string
  model: string
  model_path: string
  enabled: boolean
}

export interface ParentIndexStatus {
  configured: boolean
  dedicated: boolean
  fingerprint: string
  collection: string
  documents: number
  indexed: number
  pending: number
  running: boolean
  last_result?: Record<string, unknown> | null
}

const EMPTY_PARENT_EMBEDDING: ParentEmbeddingConfigOut = {
  configured: false,
  provider: 'remote',
  base_url: '',
  api_key_masked: '',
  model: '',
  model_path: '',
  enabled: true,
}

/** 家长客服专属 Embedding（管理员）；未配置时回退系统级 Embedding */
export async function getParentEmbeddingConfig(): Promise<ParentEmbeddingConfigOut> {
  const { data } = await http.get<{ item: ParentEmbeddingConfigOut }>('/teacher/service/parent-embedding-config')
  return data.item ?? EMPTY_PARENT_EMBEDDING
}

export async function saveParentEmbeddingConfig(
  payload: RetrievalConfigIn,
): Promise<{ item: ParentEmbeddingConfigOut; indexing_started: boolean }> {
  const { data } = await http.post<{ item: ParentEmbeddingConfigOut; indexing_started: boolean }>(
    '/teacher/service/parent-embedding-config',
    payload,
  )
  return data
}

export async function deleteParentEmbeddingConfig(): Promise<void> {
  await http.delete('/teacher/service/parent-embedding-config')
}

export async function testParentEmbeddingConfig(): Promise<{
  ok: boolean
  latency_ms?: number
  dim?: number
  error?: string
}> {
  const { data } = await http.post('/teacher/service/parent-embedding-config/test')
  return data
}

/** 家长索引状态：可见文档数 / 已按当前家长 Embedding 建索引数 */
export async function getParentIndexStatus(): Promise<ParentIndexStatus> {
  const { data } = await http.get<ParentIndexStatus>('/teacher/service/parent-embedding-index')
  return data
}

export async function rebuildParentIndex(): Promise<{ started: boolean } & ParentIndexStatus> {
  const { data } = await http.post<{ started: boolean } & ParentIndexStatus>('/teacher/service/parent-embedding-index/rebuild')
  return data
}

