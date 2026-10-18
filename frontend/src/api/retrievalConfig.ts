import http from './http'

/** provider：remote=云端 API，local=本地模型（预留接口，后续接入不改表结构） */
export type RetrievalProvider = 'remote' | 'local'

export interface RetrievalConfigOut {
  id: string
  provider: RetrievalProvider
  base_url: string
  api_key_masked: string
  model: string
  model_path: string | null
  enabled: boolean
  updated_at: string | null
}

export interface RetrievalConfigIn {
  provider: RetrievalProvider
  base_url: string
  api_key: string
  model: string
  model_path?: string
  enabled?: boolean
}

/** 系统级 Embedding（管理员）——全校共用一套，决定向量空间 */
export async function getEmbeddingConfig(): Promise<RetrievalConfigOut | null> {
  const { data } = await http.get<{ item: RetrievalConfigOut | null }>('/retrieval-configs/embedding')
  return data.item
}

export async function saveEmbeddingConfig(payload: RetrievalConfigIn): Promise<RetrievalConfigOut> {
  const { data } = await http.put<{ item: RetrievalConfigOut }>('/retrieval-configs/embedding', payload)
  return data.item
}

export async function deleteEmbeddingConfig(): Promise<void> {
  await http.delete('/retrieval-configs/embedding')
}

export async function testEmbeddingConfig(): Promise<{
  ok: boolean
  latency_ms?: number
  dim?: number
  error?: string
}> {
  const { data } = await http.post('/retrieval-configs/embedding/test')
  return data
}

/** 教师级 Rerank（可选）——未配置则检索退化为单层向量召回 */
export async function getRerankConfig(): Promise<RetrievalConfigOut | null> {
  const { data } = await http.get<{ item: RetrievalConfigOut | null }>('/retrieval-configs/rerank')
  return data.item
}

export async function saveRerankConfig(payload: RetrievalConfigIn): Promise<RetrievalConfigOut> {
  const { data } = await http.put<{ item: RetrievalConfigOut }>('/retrieval-configs/rerank', payload)
  return data.item
}

export async function deleteRerankConfig(): Promise<void> {
  await http.delete('/retrieval-configs/rerank')
}

export async function testRerankConfig(): Promise<{ ok: boolean; latency_ms?: number; error?: string; note?: string }> {
  const { data } = await http.post('/retrieval-configs/rerank/test')
  return data
}