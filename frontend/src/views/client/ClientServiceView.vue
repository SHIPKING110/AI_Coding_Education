<script setup lang="ts">
import { onMounted, ref } from 'vue'

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

function anonKey(): string {
  let k = localStorage.getItem('parent_anon_key') || ''
  if (!k) {
    k = `web-${Math.random().toString(36).slice(2, 10)}`
    localStorage.setItem('parent_anon_key', k)
  }
  return k
}

async function send() {
  const text = input.value.trim()
  if (!text || sending.value) return
  sending.value = true
  error.value = ''
  escalatedNote.value = ''
  items.value.push({ id: `local-${Date.now()}`, role: 'user', content: text, created_at: null })
  input.value = ''
  try {
    const r = await parentChat(text, { thread_id: thread.value?.id, anon_key: anonKey() })
    thread.value = r.thread
    if (r.escalated) {
      escalatedNote.value = '已为您转接人工老师，请稍候，老师会尽快回复。'
      const m = await parentMessages(r.thread.id)
      items.value = m.items
    } else {
      items.value.push({ id: `a-${Date.now()}`, role: 'assistant', content: r.answer || '', created_at: null })
    }
  } catch (e: any) {
    const detail = e?.response?.data?.detail || '发送失败，请稍后重试'
    error.value = typeof detail === 'string' ? detail : '发送失败，请稍后重试'
  } finally {
    sending.value = false
  }
}

async function toHuman() {
  if (!thread.value) return
  try {
    await parentEscalate(thread.value.id)
    escalatedNote.value = '已为您转接人工老师，请稍候。'
  } catch (e: any) {
    error.value = e?.response?.data?.detail || '转人工失败'
  }
}

onMounted(() => {})
</script>

<template>
  <div class="svc">
    <div class="svc-head">
      <div>
        <h1>智能客服</h1>
        <p>课程 · 课时 · 请假 · 活动，有问必答；复杂问题可一键转人工老师。</p>
      </div>
      <button v-if="thread" class="ghost-btn" @click="toHuman">转人工</button>
    </div>
    <div class="thread">
      <div v-if="!items.length" class="empty">
        <p>您好，我是课程小助手～</p>
        <p class="muted">试试问：这学期有哪些课？怎么请假？课时还剩多少？</p>
      </div>
      <div v-for="m in items" :key="m.id" class="msg" :class="m.role">
        <div class="bubble">{{ m.content }}</div>
      </div>
      <p v-if="escalatedNote" class="escalated">{{ escalatedNote }}</p>
      <p v-if="error" class="error">{{ error }}</p>
    </div>
    <div class="composer">
      <input v-model="input" type="text" placeholder="请输入您的问题…" @keyup.enter="send" />
      <button class="btn primary" :disabled="sending" @click="send">{{ sending ? '发送中…' : '发送' }}</button>
    </div>
  </div>
</template>

<style scoped>
.svc { display: flex; flex-direction: column; gap: 12px; }
.svc-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.svc-head h1 { font-size: 20px; margin: 0; }
.svc-head p { color: var(--ink-3); font-size: 13px; margin: 4px 0 0; }
.ghost-btn { border: 1px solid var(--line); background: #fff; border-radius: 999px; padding: 7px 16px; cursor: pointer; }
.thread { background: #fff; border: 1px solid var(--line); border-radius: 16px; padding: 16px; min-height: 320px; display: flex; flex-direction: column; gap: 10px; }
.empty { color: var(--ink-3); text-align: center; padding: 48px 0; }
.empty .muted { font-size: 13px; margin-top: 8px; }
.msg { display: flex; }
.msg.user { justify-content: flex-end; }
.msg.assistant .bubble, .msg.staff .bubble { background: #f1f5f9; color: #0f172a; }
.msg.user .bubble { background: linear-gradient(135deg, #6366f1, #06b6d4); color: #fff; }
.bubble { max-width: 78%; padding: 10px 14px; border-radius: 14px; white-space: pre-wrap; font-size: 14px; line-height: 1.6; }
.escalated { background: #fef3c7; border: 1px solid #fcd34d; color: #92400e; border-radius: 12px; padding: 10px 14px; font-size: 13px; }
.error { color: #dc2626; font-size: 13px; }
.composer { display: flex; gap: 10px; }
.composer input { flex: 1; border: 1px solid var(--line); border-radius: 999px; padding: 11px 18px; font-size: 14px; outline: none; }
.composer input:focus { border-color: var(--brand-strong); }
</style>
