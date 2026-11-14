import http from './http'

/** 联网搜索配置（系统级单例，管理员）——驱动 Agent 的 web_search 工具 */
export interface SearchConfigOut {
  id: string
  provider: string
  base_url: string
  api_key_masked: string
  enabled: boolean
  search_depth: string
  max_results: number
  language: string
  updated_at: string | null
}

export interface SearchConfigIn {
  base_url?: string
  api_key: string
  enabled?: boolean
  search_depth?: string
  max_results?: number
  language?: string
}

export async function getSearchConfig(): Promise<SearchConfigOut | null> {
  const { data } = await http.get<{ item: SearchConfigOut | null }>('/search-configs')
  return data.item
}

export async function saveSearchConfig(payload: SearchConfigIn): Promise<SearchConfigOut> {
  const { data } = await http.put<{ item: SearchConfigOut }>('/search-configs', payload)
  return data.item
}

export async function deleteSearchConfig(): Promise<void> {
  await http.delete('/search-configs')
}

export async function testSearchConfig(): Promise<{
  ok: boolean
  latency_ms?: number
  count?: number
  error?: string
}> {
  const { data } = await http.post('/search-configs/test')
  return data
}
