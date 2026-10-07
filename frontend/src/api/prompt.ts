import http from './http'

export interface PromptTemplateOut {
  id: string
  name: string
  content: string
  scope: string // system | personal | published
  scene: string // feedback | report | evaluation
  owner_id: string | null
  owner_name: string | null
  created_at: string
  updated_at: string
}

export interface PromptTemplateIn {
  name: string
  content: string
  scene?: string // feedback | report | evaluation（默认 feedback）
}

export async function listPromptTemplates(scene?: string): Promise<PromptTemplateOut[]> {
  const { data } = await http.get<PromptTemplateOut[]>('/prompt-templates', {
    params: scene ? { scene } : {},
  })
  return data
}

export async function createPromptTemplate(payload: PromptTemplateIn): Promise<PromptTemplateOut> {
  const { data } = await http.post<PromptTemplateOut>('/prompt-templates', payload)
  return data
}

export async function updatePromptTemplate(
  id: string,
  payload: Partial<PromptTemplateIn>,
): Promise<PromptTemplateOut> {
  const { data } = await http.patch<PromptTemplateOut>(`/prompt-templates/${id}`, payload)
  return data
}

export async function deletePromptTemplate(id: string): Promise<void> {
  await http.delete(`/prompt-templates/${id}`)
}

export async function publishPromptTemplate(id: string): Promise<PromptTemplateOut> {
  const { data } = await http.post<PromptTemplateOut>(`/prompt-templates/${id}/publish`)
  return data
}

export async function unpublishPromptTemplate(id: string): Promise<PromptTemplateOut> {
  const { data } = await http.post<PromptTemplateOut>(`/prompt-templates/${id}/unpublish`)
  return data
}
