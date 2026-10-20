import http from './http'

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

export interface ParentMessage {
  id: string
  role: string
  content: string
  created_at: string | null
}

export interface ParentChatResult {
  thread: ParentThread
  answer: string | null
  refs: { title: string; doc_id: string }[]
  escalated: boolean
  risk_word?: string
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
