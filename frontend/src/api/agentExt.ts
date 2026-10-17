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
  visibility: string
  collected?: boolean
  mine?: boolean
  endpoint_hidden?: boolean
  collected_from_plaza?: boolean
}

export interface AgentSkill {
  id: string
  name: string
  description: string
  content: string
  files: string[]
  enabled: boolean
  visibility: string
  collected?: boolean
  mine?: boolean
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

export async function testMcp(id: string): Promise<{ ok: boolean; tools: { name: string; description: string }[]; trace: { step: string; ok: boolean; ms: number; detail: string }[] }> {
  const { data } = await http.post(`/agents/ext/mcps/${id}/test`)
  return data
}

export async function publishMcp(id: string): Promise<AgentMcp> {
  const { data } = await http.post(`/agents/ext/mcps/${id}/publish`)
  return data
}

export async function unpublishMcp(id: string): Promise<AgentMcp> {
  const { data } = await http.post(`/agents/ext/mcps/${id}/unpublish`)
  return data
}

export async function listPlazaMcps(): Promise<AgentMcp[]> {
  const { data } = await http.get('/agents/ext/mcps/plaza')
  return data.items
}

export async function collectMcp(id: string): Promise<void> {
  await http.post(`/agents/ext/mcps/plaza/${id}/collect`)
}

export async function uncollectMcp(id: string): Promise<void> {
  await http.delete(`/agents/ext/mcps/plaza/${id}/collect`)
}

export async function uploadSkillBundle(id: string, file: File): Promise<AgentSkill> {
  const form = new FormData()
  form.append('file', file)
  const { data } = await http.post(`/agents/ext/skills/${id}/upload`, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return data
}

export async function importSkillBundle(file: File): Promise<AgentSkill> {
  const form = new FormData()
  form.append('file', file)
  const { data } = await http.post('/agents/ext/skills/import', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return data
}

export async function runSkillScript(id: string, path: string, args: string[] = []): Promise<{ ok: boolean; code: number; stdout: string; stderr: string; provider?: string }> {
  const { data } = await http.post(`/agents/ext/skills/${id}/run`, { path, args })
  return data
}

export async function previewSkillFile(id: string, path: string): Promise<{ path: string; text: string }> {
  const { data } = await http.get(`/agents/ext/skills/${id}/files/preview`, { params: { path } })
  return data
}

export async function publishSkill(id: string): Promise<AgentSkill> {
  const { data } = await http.post(`/agents/ext/skills/${id}/publish`)
  return data
}

export async function unpublishSkill(id: string): Promise<AgentSkill> {
  const { data } = await http.post(`/agents/ext/skills/${id}/unpublish`)
  return data
}

export async function listPlazaSkills(): Promise<AgentSkill[]> {
  const { data } = await http.get('/agents/ext/skills/plaza')
  return data.items
}

export async function collectSkill(id: string): Promise<void> {
  await http.post(`/agents/ext/skills/plaza/${id}/collect`)
}

export async function uncollectSkill(id: string): Promise<void> {
  await http.delete(`/agents/ext/skills/plaza/${id}/collect`)
}

export interface SandboxSetting {
  provider: string
  endpoint: string
  has_token: boolean
  timeout_s: number
  enabled: boolean
  workspace_id: string
  region: string
  template_code: string
}

export async function getSandbox(): Promise<SandboxSetting> {
  const { data } = await http.get('/agents/ext/sandbox')
  return data
}

export async function putSandbox(payload: { provider: string; endpoint: string; token?: string; timeout_s: number; enabled: boolean; workspace_id: string; region: string; template_code: string }): Promise<SandboxSetting> {
  const { data } = await http.put('/agents/ext/sandbox', payload)
  return data
}

export async function testSandbox(payload: { provider: string; endpoint: string; token?: string; timeout_s: number; workspace_id: string; region: string; template_code: string }): Promise<{ ok: boolean; detail: string }> {
  const { data } = await http.post('/agents/ext/sandbox/test', payload)
  return data
}
