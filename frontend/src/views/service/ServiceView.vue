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
const campuses = ref<string[]>([])
const activeId = ref('')
const active = ref<ParentThread | null>(null)
const messages = ref<ParentMessage[]>([])
const reply = ref('')
const loading = ref(false)
const error = ref('')
const filter = ref<'all' | 'escalated' | 'open'>('all')
const campusFilter = ref('')

const filtered = computed(() => {
  if (filter.value === 'all') return threads.value
  return threads.value.filter((t) => t.status === filter.value)
})
const escalatedCount = computed(() => threads.value.filter((t) => t.status === 'escalated').length)

async function loadThreads() {
  try {
    const r = await staffServiceThreads(campusFilter.value || undefined)
    threads.value = r.items
    campuses.value = r.campuses || []
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
    await refreshSilent()
  } catch (e: any) {
    error.value = e?.response?.data?.detail || '回复失败'
  }
}

async function closeThread() {
  if (!activeId.value) return
  try {
    await staffServiceClose(activeId.value)
    await openThread(activeId.value)
    await refreshSilent()
  } catch (e: any) {
    error.value = e?.response?.data?.detail || '关闭失败'
  }
}

async function refreshSilent() {
  try {
    const r = await staffServiceThreads(campusFilter.value || undefined)
    threads.value = r.items
    campuses.value = r.campuses || []
  } catch { /* 忽略静默刷新失败 */ }
}

function onCampusChange() {
  activeId.value = ''
  active.value = null
  messages.value = []
  void loadThreads()
}

function statusText(t: ParentThread): string {
  if (t.status === 'escalated') return '待接待'
  if (t.status === 'closed') return '已解决'
  return '进行中'
}

function fmtTime(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  const m = d.getMonth() + 1
  return `${m}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

onMounted(loadThreads)
</script>

<template>
  <div class="service">
    <div class="page-head">
      <div class="title-wrap">
        <div class="title-badge">服</div>
        <div>
          <h1>教学服务</h1>
          <p>家长客服转人工会话接待 · <b class="hl">{{ escalatedCount }}</b> 个待接待</p>
        </div>
      </div>
      <div class="head-filters">
        <select v-model="campusFilter" class="campus-select" @change="onCampusChange">
          <option value="">全部校区</option>
          <option v-for="c in campuses" :key="c" :value="c">{{ c }}</option>
        </select>
        <div class="seg">
          <button :class="{ on: filter === 'all' }" @click="filter = 'all'">全部</button>
          <button :class="{ on: filter === 'escalated' }" @click="filter = 'escalated'">待接待</button>
          <button :class="{ on: filter === 'open' }" @click="filter = 'open'">进行中</button>
        </div>
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
          <div class="tc-top">
            <span class="status" :class="t.status">{{ statusText(t) }}</span>
            <span v-if="t.campus_label" class="campus-tag">{{ t.campus_label }}</span>
          </div>
          <b class="tc-name">{{ t.parent_name || '家长会话' }}</b>
          <span class="tc-student">{{ t.student_label || '' }}</span>
          <span class="tc-meta">{{ fmtTime(t.updated_at) }} · {{ t.user_msg_count ?? 0 }} 条家长消息</span>
        </button>
        <p v-if="!filtered.length" class="empty">暂无会话</p>
      </aside>
      <section class="chat">
        <div v-if="loading" class="empty">加载中…</div>
        <template v-else-if="active">
          <div class="chat-head">
            <div class="who">
              <div class="who-avatar">{{ (active.parent_name || '客')[0] }}</div>
              <div>
                <b>{{ active.parent_name || '家长会话' }}</b>
                <span>{{ active.student_label || '' }}</span>
              </div>
            </div>
            <div class="who-side">
              <span v-if="active.phone" class="phone">☎ {{ active.phone }}</span>
              <span v-if="active.campus_label" class="campus-tag">{{ active.campus_label }}</span>
            </div>
          </div>
          <div v-if="active.risk_flag" class="risk-bar">该会话涉及敏感话题（退费 / 收费 / 安全类），请谨慎回复，必要时升级处理。</div>
          <div class="msgs">
            <div v-for="m in messages" :key="m.id" class="msg" :class="m.role">
              <div class="bubble">{{ m.content }}</div>
            </div>
          </div>
          <div class="composer">
            <input v-model="reply" type="text" placeholder="输入回复，家长端即时可见…" @keyup.enter="sendReply" />
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
          <li>列表显示「家长姓名 · 学员与班级」，右上角可按校区过滤。</li>
          <li>回复会即时同步到家长端会话。</li>
          <li>解决后点击「设为已解决」归档。</li>
        </ul>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.service { display: flex; flex-direction: column; gap: 14px; }
.page-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; background: linear-gradient(135deg, #312e81, #0e7490 70%, #0891b2); border-radius: 20px; padding: 16px 20px; color: #fff; box-shadow: 0 8px 24px rgba(49, 46, 129, 0.25); }
.title-wrap { display: flex; align-items: center; gap: 12px; }
.title-badge { width: 44px; height: 44px; border-radius: 14px; background: rgba(255, 255, 255, 0.18); border: 1px solid rgba(255, 255, 255, 0.35); display: flex; align-items: center; justify-content: center; font-size: 22px; font-weight: 800; }
.page-head h1 { font-size: 20px; margin: 0; }
.page-head p { margin: 3px 0 0; font-size: 12.5px; color: rgba(255, 255, 255, 0.85); }
.hl { color: #fde68a; }
.head-filters { display: flex; align-items: center; gap: 10px; }
.campus-select { border: 1px solid rgba(255, 255, 255, 0.4); background: rgba(255, 255, 255, 0.14); color: #fff; border-radius: 999px; padding: 8px 14px; font-size: 13px; outline: none; }
.campus-select option { color: #0f172a; }
.seg { display: flex; background: rgba(255, 255, 255, 0.16); border-radius: 999px; padding: 3px; gap: 2px; }
.seg button { border: none; background: transparent; border-radius: 999px; padding: 7px 15px; cursor: pointer; font-size: 13px; color: rgba(255, 255, 255, 0.8); }
.seg button.on { background: #fff; color: #0f172a; font-weight: 600; }
.error { color: #dc2626; font-size: 13px; margin: 0; }
.cols { display: grid; grid-template-columns: 300px 1fr 240px; gap: 14px; align-items: start; }
.threads, .chat, .profile { background: #fff; border: 1px solid var(--line); border-radius: 18px; padding: 14px; box-shadow: 0 4px 16px rgba(15, 23, 42, 0.05); }
.threads { display: flex; flex-direction: column; gap: 10px; max-height: 660px; overflow: auto; }
.thread-card { text-align: left; border: 1px solid var(--line); border-radius: 14px; padding: 11px 13px; background: #fff; cursor: pointer; display: flex; flex-direction: column; gap: 5px; transition: all 0.15s; }
.thread-card:hover { transform: translateY(-1px); box-shadow: 0 6px 14px rgba(15, 23, 42, 0.09); }
.thread-card.active { border-color: #6366f1; box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.15); }
.thread-card.risk { border-left: 4px solid #ef4444; }
.tc-top { display: flex; align-items: center; gap: 6px; }
.status { font-size: 11px; font-weight: 700; padding: 2px 9px; border-radius: 999px; background: #e0e7ff; color: #3730a3; }
.status.escalated { background: #fee2e2; color: #b91c1c; }
.status.closed { background: #f1f5f9; color: #64748b; }
.campus-tag { font-size: 11px; padding: 2px 9px; border-radius: 999px; background: #ecfdf5; color: #047857; border: 1px solid #a7f3d0; }
.tc-name { font-size: 14.5px; }
.tc-student { font-size: 12.5px; color: #334155; }
.tc-meta { font-size: 11.5px; color: #94a3b8; }
.chat { min-height: 500px; display: flex; flex-direction: column; gap: 12px; }
.chat-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; background: #f8fafc; border: 1px solid var(--line); border-radius: 14px; padding: 10px 14px; }
.who { display: flex; align-items: center; gap: 10px; }
.who-avatar { width: 38px; height: 38px; border-radius: 12px; background: linear-gradient(135deg, #6366f1, #06b6d4); color: #fff; font-weight: 800; font-size: 17px; display: flex; align-items: center; justify-content: center; }
.who b { font-size: 15px; display: block; }
.who span { font-size: 12.5px; color: #64748b; }
.who-side { display: flex; align-items: center; gap: 8px; }
.phone { font-size: 12.5px; color: #0e7490; background: #ecfeff; border: 1px solid #a5f3fc; padding: 3px 10px; border-radius: 999px; }
.risk-bar { background: #fef3c7; border: 1px solid #fcd34d; color: #92400e; border-radius: 12px; padding: 10px 14px; font-size: 13px; }
.msgs { flex: 1; display: flex; flex-direction: column; gap: 10px; max-height: 460px; overflow: auto; }
.msg { display: flex; }
.msg.user { justify-content: flex-start; }
.msg.user .bubble { background: #fff7ed; border: 1px solid #fed7aa; color: #0f172a; }
.msg.assistant { justify-content: flex-start; }
.msg.assistant .bubble { background: #f1f5f9; color: #0f172a; }
.msg.staff { justify-content: flex-end; }
.msg.staff .bubble { background: linear-gradient(135deg, #6366f1, #06b6d4); color: #fff; }
.bubble { max-width: 80%; padding: 10px 14px; border-radius: 14px; font-size: 14px; line-height: 1.6; white-space: pre-wrap; }
.composer { display: flex; gap: 10px; }
.composer input { flex: 1; border: 1px solid var(--line); border-radius: 999px; padding: 11px 18px; font-size: 14px; outline: none; }
.composer input:focus { border-color: #6366f1; box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.15); }
.ghost-btn { border: 1px solid var(--line); background: #fff; border-radius: 999px; padding: 9px 16px; cursor: pointer; white-space: nowrap; }
.profile h3 { font-size: 15px; margin: 0 0 10px; }
.profile ul { margin: 0; padding-left: 18px; font-size: 13px; color: var(--ink-3); display: flex; flex-direction: column; gap: 8px; }
.empty { color: var(--ink-3); text-align: center; padding: 40px 0; }
@media (max-width: 1100px) { .cols { grid-template-columns: 250px 1fr; } .profile { display: none; } }
</style>
