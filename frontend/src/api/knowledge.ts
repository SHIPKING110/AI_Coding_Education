import http from './http'

export interface KnowledgeProgress {
  stage: string
  percent: number
  detail: string
}

export interface KnowledgeDoc {
  id: string
  title: string
  description: string
  visibility: string
  file_name: string
  status: string
  error: string | null
  chunk_count: number
  enabled?: boolean
  progress?: KnowledgeProgress | null
  collected?: boolean
  mine?: boolean
  created_at: string | null
}

export async function listMyDocs(): Promise<KnowledgeDoc[]> {
  const { data } = await http.get<{ items: KnowledgeDoc[] }>('/knowledge/documents')
  return data.items
}

export async function uploadDoc(file: File, title: string, description: string): Promise<KnowledgeDoc> {
  const fd = new FormData()
  fd.append('file', file)
  fd.append('title', title)
  fd.append('description', description)
  const { data } = await http.post('/knowledge/documents', fd, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return data
}

export async function publishDoc(id: string): Promise<KnowledgeDoc> {
  const { data } = await http.post(`/knowledge/documents/${id}/publish`)
  return data
}

export async function unpublishDoc(id: string): Promise<KnowledgeDoc> {
  const { data } = await http.post(`/knowledge/documents/${id}/unpublish`)
  return data
}

export async function deleteDoc(id: string): Promise<void> {
  await http.delete(`/knowledge/documents/${id}`)
}

export async function retryDoc(id: string): Promise<KnowledgeDoc> {
  const { data } = await http.post(`/knowledge/documents/${id}/retry`)
  return data
}

export async function toggleDocSearch(id: string): Promise<KnowledgeDoc> {
  const { data } = await http.post(`/knowledge/documents/${id}/toggle-search`)
  return data
}

export async function listPlaza(): Promise<KnowledgeDoc[]> {
  const { data } = await http.get<{ items: KnowledgeDoc[] }>('/knowledge/plaza')
  return data.items
}

export async function collectDoc(id: string): Promise<void> {
  await http.post(`/knowledge/plaza/${id}/collect`)
}

export async function uncollectDoc(id: string): Promise<void> {
  await http.delete(`/knowledge/plaza/${id}/collect`)
}
