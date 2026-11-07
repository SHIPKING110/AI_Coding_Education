import http from './http'

export interface LLMConfigOut {
  id: string
  name: string
  base_url: string
  api_key_masked: string
  model: string
  embed_model: string | null
  is_default: boolean
  updated_at: string | null
}

export interface LLMConfigIn {
  name: string
  base_url: string
  api_key: string
  model: string
  embed_model?: string | null
  make_default?: boolean
}

export const LLM_MODULES = [
  { key: 'agent', label: 'Agent 工作台' },
  { key: 'report', label: '报告总结' },
  { key: 'evaluation', label: '学员评估' },
  { key: 'assignment', label: 'AI 习题' },
  { key: 'feedback', label: '客户反馈' },
] as const

export type LLMModuleKey = (typeof LLM_MODULES)[number]['key']

export async function listLLMConfigs(): Promise<{ items: LLMConfigOut[]; modules: string[] }> {
  const { data } = await http.get('/llm-configs')
  return data
}

export async function createLLMConfig(payload: LLMConfigIn): Promise<LLMConfigOut> {
  const { data } = await http.post('/llm-configs', payload)
  return data
}

export async function updateLLMConfig(
  id: string,
  payload: Partial<LLMConfigIn> & { make_default?: boolean },
): Promise<LLMConfigOut> {
  const { data } = await http.patch(`/llm-configs/${id}`, payload)
  return data
}

export async function deleteLLMConfig(id: string): Promise<void> {
  await http.delete(`/llm-configs/${id}`)
}

export async function testLLMConfig(
  id: string,
): Promise<{ ok: boolean; latency_ms?: number; reply?: string; error?: string }> {
  const { data } = await http.post(`/llm-configs/${id}/test`)
  return data
}

export async function getModuleMapping(): Promise<{ mapping: Record<string, string | null> }> {
  const { data } = await http.get('/llm-configs/modules/mapping')
  return data
}

export async function setModuleMapping(
  mapping: Record<string, string | null>,
): Promise<{ mapping: Record<string, string | null> }> {
  const { data } = await http.put('/llm-configs/modules/mapping', { mapping })
  return data
}
