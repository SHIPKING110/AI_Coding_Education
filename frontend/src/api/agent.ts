import http from './http'

export interface AgentStage {
  key: string
  label: string
  desc: string
  prompt_stage: string
}

export interface AgentInfo {
  id: string
  name: string
  description: string
  context_types: string[]
  supports_rag: boolean
  icon: string
  stages: AgentStage[]
}

export interface ConversationOut {
  id: string
  agent_id: string
  context_ref: Record<string, unknown>
  title: string
  rag_enabled: boolean
  stage: string
  pinned?: boolean
  created_at: string | null
  updated_at: string | null
}

export interface ChatOption {
  id: string
  label: string
  recommended?: boolean
  action?: { type?: string; stage?: string; [k: string]: unknown }
}

export interface ChatMessage {
  id: string
  role: string
  content: string
  citations: Record<string, unknown> | null
  options?: ChatOption[] | null
  spec?: {
    outline?: { id?: string; title?: string; kind?: string; note?: string }[]
    sections?: { id?: string; title?: string; body?: unknown }[]
    theme?: string
    slides?: unknown[]
  } | null
}

export interface MaterialItem {
  kind: string
  id: string
  title: string
  type?: string
  period?: string
  stat_keys?: string[]
  stat_count?: number
}

export async function getConversationMaterial(id: string): Promise<{
  agent_id: string
  context_ref: Record<string, unknown>
  items: MaterialItem[]
}> {
  const { data } = await http.get(`/agents/conversations/${id}/material`)
  return data
}

export async function buildConversationPpt(
  id: string,
  payload: { title?: string; theme?: string; outline?: Record<string, unknown>[]; sections?: Record<string, unknown>[] },
): Promise<{ ppt_url: string; download: string; pages: number; theme: string }> {
  const { data } = await http.post(`/agents/conversations/${id}/build-ppt`, payload)
  return data
}

export async function listAgents(): Promise<AgentInfo[]> {
  const { data } = await http.get<{ items: AgentInfo[] }>('/agents')
  return data.items
}

export async function listConversations(): Promise<ConversationOut[]> {
  const { data } = await http.get<{ items: ConversationOut[] }>('/agents/conversations')
  return data.items
}

export async function createConversation(payload: {
  agent_id: string
  context_ref?: Record<string, unknown>
  title?: string
}): Promise<{ id: string; agent_id: string; title: string }> {
  const { data } = await http.post('/agents/conversations', payload)
  return data
}

export async function getConversationMessages(id: string): Promise<{
  conversation: {
    id: string
    agent_id: string
    title: string
    context_ref: Record<string, unknown>
    stage: string
  }
  items: ChatMessage[]
}> {
  const { data } = await http.get(`/agents/conversations/${id}/messages`)
  return data
}

export async function deleteConversation(id: string): Promise<void> {
  await http.delete(`/agents/conversations/${id}`)
}

export async function patchConversation(
  id: string,
  payload: { title?: string; rag_enabled?: boolean; stage?: string; pinned?: boolean; context_ref?: Record<string, unknown> },
): Promise<void> {
  await http.patch(`/agents/conversations/${id}`, payload)
}

/** 生成只读分享链接，返回相对路径 /share/{token} */
export async function shareConversation(id: string): Promise<{ token: string; path: string }> {
  const { data } = await http.post<{ token: string; path: string }>(`/agents/conversations/${id}/share`)
  return data
}

export interface SharedConversation {
  title: string
  agent_id: string
  created_at: string | null
  items: { role: string; content: string }[]
}

/** 公开只读分享页数据（无需登录） */
export async function getSharedConversation(token: string): Promise<SharedConversation> {
  const { data } = await http.get<SharedConversation>(`/agents/share/${token}`)
  return data
}

export async function listMemories(agentId: string): Promise<{ id: string; key: string; value: string }[]> {
  const { data } = await http.get<{ items: { id: string; key: string; value: string }[] }>('/agents/memories', {
    params: { agent_id: agentId },
  })
  return data.items
}

export async function deleteMemory(id: string): Promise<void> {
  await http.delete(`/agents/memories/${id}`)
}

export interface AgentPhase {
  key: string
  label: string
}

export interface ToolTraceStep {
  seq: number
  tool: string
  args: Record<string, unknown>
  ok: boolean
  summary: string
  error?: string | null
}

/** 统一流式对话：SSE，回调 delta；onPhase 回调阶段；onDone 回调完成帧（含 stage/options/工具轨迹） */
export async function agentChatStream(
  convId: string,
  payload: { stage: string; message: string; state: Record<string, unknown>; use_rag?: boolean; config_id?: string | null },
  onDelta: (text: string) => void,
  signal?: AbortSignal,
  onPhase?: (phase: AgentPhase) => void,
  onDone?: (info: {
    stage?: string; options?: ChatOption[]; has_spec?: boolean; title?: string;
    tool_trace?: ToolTraceStep[]; tool_rounds?: number; tool_degraded?: boolean;
  }) => void,
  opts?: { idleTimeoutMs?: number; onTimeout?: () => void },
): Promise<void> {
  const token = localStorage.getItem('access_token')
  const resp = await fetch(`/api/agents/conversations/${convId}/chat`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(payload),
    signal,
  })
  if (!resp.ok || !resp.body) {
    let msg = 'AI 对话失败'
    try {
      const j = await resp.json()
      msg = j?.detail || msg
    } catch {
      /* ignore */
    }
    throw new Error(msg)
  }
  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  // 空闲超时兜底：后端中途僵死/半开连接时，前端不再无限卡"接收中"
  const idleMs = opts?.idleTimeoutMs ?? 90000
  let lastActive = Date.now()
  let finished = false
  const watchdog = setInterval(() => {
    if (finished || Date.now() - lastActive < idleMs) return
    finished = true
    clearInterval(watchdog)
    try {
      void reader.cancel()
    } catch {
      /* ignore */
    }
    opts?.onTimeout?.()
  }, 5000)
  const touch = () => {
    lastActive = Date.now()
  }
  try {
    for (;;) {
      const { value, done } = await reader.read()
      if (done) break
      touch()
      buf += decoder.decode(value, { stream: true })
      const frames = buf.split('\n\n')
      buf = frames.pop() || ''
      for (const frame of frames) {
        const line = frame.split('\n').find((l) => l.startsWith('data:'))
        if (!line) continue
        let data: {
          delta?: string
          done?: boolean
          stage?: string
          options?: ChatOption[]
          has_spec?: boolean
          title?: string
          error?: string
          phase?: AgentPhase
          tool_trace?: ToolTraceStep[]
          tool_rounds?: number
          tool_degraded?: boolean
        }
        try {
          data = JSON.parse(line.slice(5).trim())
        } catch {
          continue
        }
        if (data.error) throw new Error(data.error)
        if (data.phase && onPhase) onPhase(data.phase)
        if (data.delta) onDelta(data.delta)
        if (data.done) {
          if (onDone) {
            onDone({
              stage: data.stage, options: data.options, has_spec: data.has_spec, title: data.title,
              tool_trace: data.tool_trace, tool_rounds: data.tool_rounds, tool_degraded: data.tool_degraded,
            })
          }
          return
        }
      }
    }
  } finally {
    finished = true
    clearInterval(watchdog)
  }
}
