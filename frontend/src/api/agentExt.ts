import http from './http'

export interface CustomAgent {
  agent_id: string
  name: string
  description: string
  system_prompt: string
  supports_rag: boolean
  icon: string
  stages: { key: string; label: string; desc: string; prompt_stage: string }[]
  mcp_ids: string[]
  skill_ids: string[]
  custom: boolean
}

export interface AgentMcp {
  id: string
  name: string
  kind: string
  endpoint: string
  description: string
  config: Record<string, unknown>
  enabled: boolean
}

export interface AgentSkill {
  id: string
  name: string
  description: string
  content: string
  enabled: boolean
}

export async function listCustomAgents(): Promise<CustomAgent[]> {
  const { data } = await http.get('/agents/ext/agents')
  return data.items
}
export async function createCustomAgent(payload: Record<string, unknown>): Promise<CustomAgent> {
  const { data } = await http.post('/agents/ext/agents', payload)
  return data
}
export async function patchCustomAgent(id: string, payload: Record<string, unknown>): Promise<CustomAgent> {
  const { data } = await http.patch(`/agents/ext/agents/${id}`, payload)
  return data
}
export async function deleteCustomAgent(id: string): Promise<void> {
  await http.delete(`/agents/ext/agents/${id}`)
}

export async function listMcps(): Promise<AgentMcp[]> {
  const { data } = await http.get('/agents/ext/mcps')
  return data.items
}
export async function createMcp(payload: Record<string, unknown>): Promise<AgentMcp> {
  const { data } = await http.post('/agents/ext/mcps', payload)
  return data
}
export async function patchMcp(id: string, payload: Record<string, unknown>): Promise<AgentMcp> {
  const { data } = await http.patch(`/agents/ext/mcps/${id}`, payload)
  return data
}
export async function deleteMcp(id: string): Promise<void> {
  await http.delete(`/agents/ext/mcps/${id}`)
}

export async function listSkills(): Promise<AgentSkill[]> {
  const { data } = await http.get('/agents/ext/skills')
  return data.items
}
export async function createSkill(payload: Record<string, unknown>): Promise<AgentSkill> {
  const { data } = await http.post('/agents/ext/skills', payload)
  return data
}
export async function patchSkill(id: string, payload: Record<string, unknown>): Promise<AgentSkill> {
  const { data } = await http.patch(`/agents/ext/skills/${id}`, payload)
  return data
}
export async function deleteSkill(id: string): Promise<void> {
  await http.delete(`/agents/ext/skills/${id}`)
}

export async function getAgentGlobal(): Promise<{ default_mcp_ids: string[]; default_skill_ids: string[] }> {
  const { data } = await http.get('/agents/ext/global')
  return data
}
export async function putAgentGlobal(payload: { default_mcp_ids: string[]; default_skill_ids: string[] }): Promise<void> {
  await http.put('/agents/ext/global', payload)
}
