<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import {
  staffServiceClose,
  staffServiceMessages,
  staffServiceReply,
  staffServiceThreads,
  type ParentMessage,
  type ParentThread,
} from '@/api/parentService'

const threads = ref<ParentThread[]>([])
const activeId = ref('')
const active = ref<ParentThread | null>(null)
const messages = ref<ParentMessage[]>([])
const reply = ref('')
const loading = ref(false)
const error = ref('')
const filter = ref<'all' | 'escalated' | 'open'>('all')

const filtered = computed(() => {
  if (filter.value === 'all') return threads.value
  return threads.value.filter((t) => t.status === filter.value)
})
const activeMessages = computed(() => messages.value)
const escalatedCount = computed(() => threads.value.filter((t) => t.status === 'escalated').length)

async function loadThreads() {
  try {
    threads.value = await staffServiceThreads()
    if (!activeId.value && threads.value.length) await openThread(threads.value[0].id)
  } catch (e: any) {
    error.value = e?.response?.data?.detail || '加载会话失败'
  }
}

async function openThread(id: string) {
  activeId.value = id
  loading.value = true
  error.value = ''
  try {
    const r = await staffServiceMessages(id)
    active.value = r.thread
    messages.value = r.items
  } catch (e: any) {
    error.value = e?.response?.data?.detail || '加载消息失败'
  } finally {
    loading.value = false
  }
}

async function sendReply() {
  const text = reply.value.trim()
  if (!text || !activeId.value) return
  try {
    await staffServiceReply(activeId.value, text)
    reply.value = ''
    await openThread(activeId.value)
    await loadThreadsSilent()
  } catch (e: any) {
    error.value = e?.response?.data?.detail || '回复失败'
  }
}

async function closeThread() {
  if (!activeId.value) return
  try {
    await staffServiceClose(activeId.value)
    await openThread(activeId.value)
    await loadThreadsSilent()
  } catch (e: any) {
    error.value = e?.response?.data?.detail || '关闭失败'
  }
}

async function loadThreadsSilent() {
  try {
    threads.value = await staffServiceThreads()
  } catch { /* 忽略静默刷新失败 */ }
}

function statusText(t: ParentThread): string {
  if (t.status === 'escalated') return '待接待'
  if (t.status === 'closed') return '已解决'
  return '进行中'
}

onMounted(loadThreads)
</script>

<template>
  <div class="service">
    <div class="page-head">
      <div>
        <h1>教学服务</h1>
        <p>家长客服转人工会话接待 · 待接待 {{ escalatedCount }} 个</p>
      </div>
      <div class="seg">
        <button :class="{ on: filter === 'all' }" @click="filter = 'all'">全部</button>
        <button :class="{ on: filter === 'escalated' }" @click="filter = 'escalated'">待接待</button>
        <button :class="{ on: filter === 'open' }" @click="filter = 'open'">进行中</button>
      </div>
    </div>
    <p v-if="error" class="error">{{ error }}</p>
    <div class="cols">
      <aside class="threads">
        <button
          v-for="t in filtered"
          :key="t.id"
          class="thread-card"
          :class="{ active: t.id === activeId, risk: t.status === 'escalated' }"
          @click="openThread(t.id)"
        >
          <span class="status" :class="t.status">{{ statusText(t) }}</span>
          <b>{{ t.parent_name || '家长会话' }}</b>
          <span class="meta">{{ t.user_msg_count ?? '' }} 条家长消息</span>
        </button>
        <p v-if="!filtered.length" class="empty">暂无会话</p>
      </aside>
      <section class="chat">
        <div v-if="loading" class="empty">加载中…</div>
        <template v-else-if="active">
          <div v-if="active.risk_flag" class="risk-bar">该会话涉及敏感话题（退费/收费/安全类），请谨慎回复，必要时升级处理。</div>
          <div class="msgs">
            <div v-for="m in activeMessages" :key="m.id" class="msg" :class="m.role">
              <div class="bubble">{{ m.content }}</div>
            </div>
          </div>
          <div class="composer">
            <input v-model="reply" type="text" placeholder="输入回复…" @keyup.enter="sendReply" />
            <button class="btn primary" @click="sendReply">回复</button>
            <button class="ghost-btn" @click="closeThread">设为已解决</button>
          </div>
        </template>
        <p v-else class="empty">左侧选择一个会话开始接待</p>
      </section>
      <aside class="profile">
        <h3>接待提示</h3>
        <ul>
          <li>待接待会话由 AI 按高风险词自动转入，请优先处理。</li>
          <li>回复会即时同步到家长端会话。</li>
          <li>解决后点击「设为已解决」归档。</li>
        </ul>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.service { display: flex; flex-direction: column; gap: 14px; }
.page-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.page-head h1 { font-size: 22px; margin: 0; letter-spacing: -0.01em; }
.page-head p { color: var(--ink-3); font-size: 13px; margin: 4px 0 0; }
.seg { display: flex; background: #f1f5f9; border-radius: 999px; padding: 3px; gap: 2px; }
.seg button { border: none; background: transparent; border-radius: 999px; padding: 7px 16px; cursor: pointer; font-size: 13px; color: #64748b; }
.seg button.on { background: #fff; color: #0f172a; font-weight: 600; box-shadow: 0 1px 4px rgba(15,23,42,.12); }
.error { color: #dc2626; font-size: 13px; }
.cols { display: grid; grid-template-columns: 280px 1fr 240px; gap: 14px; align-items: start; }
.threads, .chat, .profile { background: #fff; border: 1px solid var(--line); border-radius: 16px; padding: 14px; box-shadow: 0 4px 16px rgba(15,23,42,.05); }
.threads { display: flex; flex-direction: column; gap: 10px; max-height: 640px; overflow: auto; }
.thread-card { text-align: left; border: 1px solid var(--line); border-radius: 12px; padding: 10px 12px; background: #fff; cursor: pointer; display: flex; flex-direction: column; gap: 4px; transition: all .15s; }
.thread-card:hover { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(15,23,42,.08); }
.thread-card.active { border-color: #6366f1; box-shadow: 0 0 0 2px rgba(99,102,241,.15); }
.thread-card.risk { border-left: 4px solid #ef4444; }
.status { font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 999px; width: fit-content; background: #e0e7ff; color: #3730a3; }
.status.escalated { background: #fee2e2; color: #b91c1c; }
.status.closed { background: #f1f5f9; color: #64748b; }
.thread-card b { font-size: 14px; }
.meta { font-size: 12px; color: var(--ink-3); }
.chat { min-height: 480px; display: flex; flex-direction: column; gap: 12px; }
.risk-bar { background: #fef3c7; border: 1px solid #fcd34d; color: #92400e; border-radius: 12px; padding: 10px 14px; font-size: 13px; }
.msgs { flex: 1; display: flex; flex-direction: column; gap: 10px; max-height: 480px; overflow: auto; }
.msg { display: flex; }
.msg.user { justify-content: flex-start; }
.msg.assistant { justify-content: flex-start; }
.msg.assistant .bubble { background: #f1f5f9; }
.msg.staff { justify-content: flex-end; }
.msg.staff .bubble { background: linear-gradient(135deg, #6366f1, #06b6d4); color: #fff; }
.msg.user .bubble { background: #fff7ed; border: 1px solid #fed7aa; color: #0f172a; }
.bubble { max-width: 80%; padding: 10px 14px; border-radius: 14px; font-size: 14px; line-height: 1.6; white-space: pre-wrap; }
.composer { display: flex; gap: 10px; }
.composer input { flex: 1; border: 1px solid var(--line); border-radius: 999px; padding: 11px 18px; font-size: 14px; outline: none; }
.ghost-btn { border: 1px solid var(--line); background: #fff; border-radius: 999px; padding: 9px 16px; cursor: pointer; white-space: nowrap; }
.profile h3 { font-size: 15px; margin: 0 0 10px; }
.profile ul { margin: 0; padding-left: 18px; font-size: 13px; color: var(--ink-3); display: flex; flex-direction: column; gap: 8px; }
.empty { color: var(--ink-3); text-align: center; padding: 40px 0; }
@media (max-width: 1100px) { .cols { grid-template-columns: 240px 1fr; } .profile { display: none; } }
</style>
