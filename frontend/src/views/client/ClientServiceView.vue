<script setup lang="ts">
import { nextTick, onMounted, ref } from 'vue'

import {
  parentChat,
  parentEscalate,
  parentMessages,
  type ParentMessage,
  type ParentThread,
} from '@/api/parentService'

const thread = ref<ParentThread | null>(null)
const items = ref<ParentMessage[]>([])
const input = ref('')
const sending = ref(false)
const error = ref('')
const escalatedNote = ref('')
const threadEl = ref<HTMLElement | null>(null)

const QUICK_ASK = ['这学期有哪些课？', '怎么请假？', '课时还剩多少去哪查？', '校区最近有什么活动？']

function anonKey(): string {
  let k = localStorage.getItem('parent_anon_key') || ''
  if (!k) {
    k = `web-${Math.random().toString(36).slice(2, 10)}`
    localStorage.setItem('parent_anon_key', k)
  }
  return k
}

const THREAD_KEY = 'parent_service_thread_id'

function saveThreadId(id: string) {
  localStorage.setItem(THREAD_KEY, id)
}

/** 刷新恢复：有上次 thread_id 则拉历史消息（后端账本为准，不存前端副本）。 */
async function restore() {
  const tid = localStorage.getItem(THREAD_KEY)
  if (!tid) return
  try {
    const r = await parentMessages(tid)
    thread.value = r.thread
    items.value = r.items
    if (r.thread.status === 'escalated') escalatedNote.value = '已转接人工老师，老师回复后会同步到本页。'
    await scrollBottom()
  } catch {
    localStorage.removeItem(THREAD_KEY) // 会话已清理/无权访问：静默开新会话
  }
}

async function scrollBottom() {
  await nextTick()
  threadEl.value?.scrollTo({ top: threadEl.value.scrollHeight, behavior: 'smooth' })
}

async function sendText(text: string) {
  const t = text.trim()
  if (!t || sending.value) return
  sending.value = true
  error.value = ''
  escalatedNote.value = ''
  items.value.push({ id: `local-${Date.now()}`, role: 'user', content: t, created_at: null })
  input.value = ''
  await scrollBottom()
  try {
    const r = await parentChat(t, { thread_id: thread.value?.id, anon_key: anonKey() })
    thread.value = r.thread
    saveThreadId(r.thread.id)
    if (r.escalated || r.kind === 'smalltalk' || r.answer) {
      if (r.escalated) escalatedNote.value = '已为您转接人工老师，请稍候，老师会尽快回复。'
      if (r.answer) {
        const refs = r.citations?.refs ?? r.refs ?? []
        items.value.push({
          id: `a-${Date.now()}`,
          role: 'assistant',
          content: r.answer,
          created_at: null,
          refs: refs.length ? refs : undefined,
        })
      } else if (r.escalated) {
        items.value.push({ id: `a-${Date.now()}`, role: 'assistant', content: '这个问题需要老师人工确认，已为您转接人工老师，请稍候。', created_at: null })
      }
    }
  } catch (e: any) {
    const detail = e?.response?.data?.detail || '发送失败，请稍后重试'
    error.value = typeof detail === 'string' ? detail : '发送失败，请稍后重试'
  } finally {
    sending.value = false
    await scrollBottom()
  }
}

function send() {
  void sendText(input.value)
}

async function toHuman() {
  if (!thread.value) {
    escalatedNote.value = '请先发送一条消息，再转人工。'
    return
  }
  try {
    await parentEscalate(thread.value.id)
    escalatedNote.value = '已为您转接人工老师，请稍候。'
  } catch (e: any) {
    error.value = e?.response?.data?.detail || '转人工失败'
  }
}

function fmtTime(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

onMounted(restore)
</script>

<template>
  <div class="svc">
    <div class="hero">
      <div class="hero-avatar">智</div>
      <div class="hero-text">
        <h1>课程小助手</h1>
        <p><span class="dot" />在线 · 课程 / 课时 / 请假 / 活动，有问必答</p>
      </div>
      <button class="human-btn" @click="toHuman">转人工</button>
    </div>

    <div ref="threadEl" class="thread">
      <div v-if="!items.length" class="empty">
        <div class="empty-avatar">智</div>
        <p class="empty-hi">您好，我是课程小助手～</p>
        <p class="muted">试试这样问我：</p>
        <div class="chips">
          <button v-for="q in QUICK_ASK" :key="q" class="chip" @click="sendText(q)">{{ q }}</button>
        </div>
      </div>
      <div v-for="m in items" :key="m.id" class="msg" :class="m.role">
        <div v-if="m.role !== 'user'" class="mini-avatar">智</div>
        <div class="bubble-wrap">
          <div class="bubble">{{ m.content }}</div>
          <details v-if="m.refs && m.refs.length" class="cite">
            <summary>检索依据（{{ m.refs.length }}）· 展开查看</summary>
            <div v-for="(r, i) in m.refs" :key="i" class="cite-item">
              <b class="cite-title">《{{ r.title }}》</b>
              <span v-if="r.similarity != null" class="cite-score">相似度 {{ Number(r.similarity).toFixed(3) }}</span>
              <p v-if="r.excerpt" class="cite-excerpt">{{ r.excerpt }}</p>
            </div>
          </details>
          <span v-if="m.created_at" class="time">{{ fmtTime(m.created_at) }}</span>
        </div>
      </div>
      <div v-if="sending" class="msg assistant">
        <div class="mini-avatar">智</div>
        <div class="bubble typing"><span /><span /><span /></div>
      </div>
      <p v-if="escalatedNote" class="escalated">已转人工 · {{ escalatedNote }}</p>
      <p v-if="error" class="error">{{ error }}</p>
    </div>

    <div class="composer">
      <input v-model="input" type="text" placeholder="请输入您的问题…" @keyup.enter="send" />
      <button class="send-btn" :disabled="sending" @click="send">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m22 2-7 20-4-9-9-4Z" /><path d="M22 2 11 13" /></svg>
      </button>
    </div>
    <p class="guard-note">回答依据知识库政策资料；费用 / 退费 / 安全类问题将自动转人工确认。</p>
  </div>
</template>

<style scoped>
.svc { display: flex; flex-direction: column; gap: 12px; max-width: 860px; margin: 0 auto; }
.hero { display: flex; align-items: center; gap: 12px; background: linear-gradient(135deg, #312e81, #0e7490 70%, #0891b2); border-radius: 20px; padding: 16px 18px; color: #fff; box-shadow: 0 8px 24px rgba(49, 46, 129, 0.28); }
.hero-avatar { width: 46px; height: 46px; border-radius: 14px; background: rgba(255, 255, 255, 0.18); border: 1px solid rgba(255, 255, 255, 0.35); display: flex; align-items: center; justify-content: center; font-size: 22px; font-weight: 800; flex-shrink: 0; }
.hero-text { flex: 1; }
.hero-text h1 { font-size: 18px; margin: 0; letter-spacing: 0.01em; }
.hero-text p { margin: 4px 0 0; font-size: 12.5px; color: rgba(255, 255, 255, 0.85); display: flex; align-items: center; gap: 6px; }
.dot { width: 7px; height: 7px; border-radius: 50%; background: #4ade80; box-shadow: 0 0 6px #4ade80; display: inline-block; }
.human-btn { border: 1px solid rgba(255, 255, 255, 0.5); background: rgba(255, 255, 255, 0.14); color: #fff; border-radius: 999px; padding: 8px 18px; font-size: 13px; cursor: pointer; white-space: nowrap; }
.human-btn:hover { background: rgba(255, 255, 255, 0.28); }
.thread { background: #fff; border: 1px solid var(--line); border-radius: 20px; padding: 18px; height: min(58vh, 520px); overflow-y: auto; display: flex; flex-direction: column; gap: 12px; box-shadow: 0 4px 16px rgba(15, 23, 42, 0.05); }
.empty { text-align: center; padding: 36px 12px; }
.empty-avatar { width: 56px; height: 56px; margin: 0 auto 12px; border-radius: 18px; background: linear-gradient(135deg, #6366f1, #06b6d4); color: #fff; font-size: 26px; font-weight: 800; display: flex; align-items: center; justify-content: center; }
.empty-hi { font-size: 16px; font-weight: 700; color: #0f172a; margin: 0; }
.empty .muted { font-size: 13px; color: var(--ink-3); margin: 8px 0 12px; }
.chips { display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; }
.chip { border: 1px solid #c7d2fe; background: #eef2ff; color: #3730a3; border-radius: 999px; padding: 7px 14px; font-size: 12.5px; cursor: pointer; }
.chip:hover { background: #e0e7ff; }
.msg { display: flex; gap: 8px; align-items: flex-end; }
.msg.user { justify-content: flex-end; }
.mini-avatar { width: 28px; height: 28px; border-radius: 9px; background: linear-gradient(135deg, #6366f1, #06b6d4); color: #fff; font-size: 14px; font-weight: 800; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
.bubble-wrap { display: flex; flex-direction: column; gap: 3px; max-width: 80%; }
.msg.user .bubble-wrap { align-items: flex-end; }
.bubble { padding: 11px 15px; border-radius: 16px; font-size: 14px; line-height: 1.65; white-space: pre-wrap; }
.msg.user .bubble { background: linear-gradient(135deg, #6366f1, #06b6d4); color: #fff; border-bottom-right-radius: 6px; }
.msg.assistant .bubble, .msg.staff .bubble { background: #f1f5f9; color: #0f172a; border-bottom-left-radius: 6px; }
.time { font-size: 11px; color: #94a3b8; }
.cite { width: 100%; background: #f8fafc; border: 1px solid var(--line); border-radius: 12px; padding: 8px 12px; }
.cite summary { font-size: 12px; color: #4338ca; cursor: pointer; user-select: none; }
.cite-item { margin-top: 8px; padding-top: 8px; border-top: 1px dashed #e2e8f0; }
.cite-title { font-size: 12.5px; color: #0f172a; }
.cite-score { margin-left: 8px; font-size: 11px; color: #64748b; }
.cite-excerpt { margin: 4px 0 0; font-size: 12px; color: #64748b; line-height: 1.55; }
.typing { display: flex; gap: 5px; padding: 14px 16px; }
.typing span { width: 7px; height: 7px; border-radius: 50%; background: #94a3b8; animation: blink 1.2s infinite; }
.typing span:nth-child(2) { animation-delay: 0.2s; }
.typing span:nth-child(3) { animation-delay: 0.4s; }
@keyframes blink { 0%, 80%, 100% { opacity: 0.25; } 40% { opacity: 1; } }
.escalated { background: #fef3c7; border: 1px solid #fcd34d; color: #92400e; border-radius: 12px; padding: 10px 14px; font-size: 13px; margin: 0; }
.error { color: #dc2626; font-size: 13px; margin: 0; }
.composer { display: flex; gap: 10px; align-items: center; }
.composer input { flex: 1; border: 1px solid var(--line); border-radius: 999px; padding: 13px 20px; font-size: 14px; outline: none; background: #fff; box-shadow: 0 2px 8px rgba(15, 23, 42, 0.05); }
.composer input:focus { border-color: #6366f1; box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.15); }
.send-btn { width: 46px; height: 46px; border-radius: 50%; border: none; background: linear-gradient(135deg, #6366f1, #06b6d4); color: #fff; cursor: pointer; display: flex; align-items: center; justify-content: center; flex-shrink: 0; box-shadow: 0 4px 12px rgba(99, 102, 241, 0.4); }
.send-btn:disabled { opacity: 0.55; }
.send-btn svg { width: 20px; height: 20px; }
.guard-note { font-size: 11.5px; color: #94a3b8; text-align: center; margin: 0; }
</style>
