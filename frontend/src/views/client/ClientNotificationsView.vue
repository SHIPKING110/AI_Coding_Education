<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRouter } from 'vue-router'

import EvaluationDetailDialog from '@/components/EvaluationDetailDialog.vue'
import PaginationBar from '@/components/PaginationBar.vue'
import {
  listNotifications,
  markAllNotificationsRead,
  markNotificationRead,
  type NotificationOut,
} from '@/api/client'
import {
  listClientEvaluations,
  type ClientEvaluationOut,
} from '@/api/evaluation'
import { useClientStore } from '@/stores/client'

const store = useClientStore()
const router = useRouter()

const items = ref<NotificationOut[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 15
const loading = ref(false)
const error = ref('')
const unreadOnly = ref(false)

const typeLabels: Record<string, string> = {
  schedule_reminder: '上课提醒',
  low_balance: '课时提醒',
  order_confirmed: '到账通知',
  refund: '退费通知',
  feedback_published: '课后反馈',
  assignment_published: '新作业',
  submission_graded: '作业批改',
  evaluation_published: '学习评估',
}

const typeCls: Record<string, string> = {
  schedule_reminder: 'cyan',
  low_balance: 'orange',
  order_confirmed: 'green',
  refund: 'red',
  feedback_published: 'blue',
  assignment_published: 'purple',
  submission_graded: 'green',
  evaluation_published: 'gold',
}

function normType(t: string | undefined | null): string {
  return String(t || '').toLowerCase()
}

const activeStudent = computed(() => store.activeStudent)
const evalItems = ref<ClientEvaluationOut[]>([])
const evalTotal = ref(0)
const evalPage = ref(1)
const evalPageSize = 8
const evalLoading = ref(false)
const detail = ref<ClientEvaluationOut | null>(null)

function fmt(iso: string): string {
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function evalSummary(ev: ClientEvaluationOut): string {
  const s = (ev.content ?? {}) as Record<string, unknown>
  return typeof s.summary === 'string' ? s.summary : ''
}

function evalPeriod(ev: ClientEvaluationOut): string {
  return `${ev.period_start.slice(0, 10)} ~ ${ev.period_end.slice(0, 10)}`
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const data = await listNotifications({
      unread_only: unreadOnly.value,
      limit: pageSize,
      offset: (page.value - 1) * pageSize,
    })
    items.value = data.items
    total.value = data.total
  } catch {
    error.value = '加载通知失败'
  } finally {
    loading.value = false
  }
}

async function loadEvaluations() {
  if (!activeStudent.value) return
  evalLoading.value = true
  try {
    const data = await listClientEvaluations(activeStudent.value.id, {
      limit: evalPageSize,
      offset: (evalPage.value - 1) * evalPageSize,
    })
    evalItems.value = data.items
    evalTotal.value = data.total
  } catch {
    evalItems.value = []
    evalTotal.value = 0
  } finally {
    evalLoading.value = false
  }
}

async function open(n: NotificationOut) {
  if (!n.read_at) {
    await markNotificationRead(n.id)
    n.read_at = new Date().toISOString()
    await store.refreshUnread()
  }
  const type = normType(n.type)
  const studentId = typeof n.data?.student_id === 'string' ? n.data.student_id : activeStudent.value?.id
  if (type === 'evaluation_published') {
    router.push({ name: 'client-evaluations', query: studentId ? { student_id: studentId } : undefined })
    return
  }
  const map: Record<string, string> = {
    schedule_reminder: '/client/home',
    low_balance: '/client/packages',
    order_confirmed: '/client/orders',
    refund: '/client/orders',
    feedback_published: '/client/feedbacks',
    assignment_published: '/client/assignments',
    submission_graded: '/client/assignments',
  }
  const target = map[type]
  if (target) {
    router.push(studentId ? { path: target, query: { student_id: studentId } } : target)
  }
}

async function readAll() {
  await markAllNotificationsRead()
  await store.refreshUnread()
  await load()
}

function onPageChange(p: number) {
  page.value = p
  load()
}

function toggleFilter() {
  page.value = 1
  unreadOnly.value = !unreadOnly.value
  load()
}

function onEvalPageChange(p: number) {
  evalPage.value = p
  loadEvaluations()
}

onMounted(async () => {
  if (!store.me) await store.loadMe(true)
  await load()
  await loadEvaluations()
})

watch(() => store.activeStudentId, async () => {
  evalPage.value = 1
  await loadEvaluations()
})
</script>

<template>
  <div>
    <header class="page-head">
      <div>
        <h1>消息通知</h1>
        <p class="page-sub">上课提醒 · 课时提醒 · 反馈/作业/评估通知</p>
      </div>
      <div class="head-ops">
        <button class="filter-btn" :class="{ active: unreadOnly }" @click="toggleFilter">
          {{ unreadOnly ? '只看未读' : '全部' }}
        </button>
        <button class="read-all-btn" @click="readAll">全部已读</button>
      </div>
    </header>

    <section class="panel">
      <div class="panel-head">
        <h2>通知列表</h2>
        <span class="panel-sub">{{ total }} 条</span>
      </div>
      <p v-if="error" class="error-banner">{{ error }}</p>
      <div v-if="loading" class="loading">加载中…</div>
      <div v-else class="notif-list">
        <article
          v-for="n in items"
          :key="n.id"
          class="notif-item"
          :class="{ unread: !n.read_at }"
          @click="open(n)"
        >
          <div class="notif-icon" :class="typeCls[normType(n.type)] || 'blue'">
            <span class="dot" />
          </div>
          <div class="notif-content">
            <div class="notif-title-row">
              <strong>{{ n.title }}</strong>
              <span class="type-pill" :class="typeCls[normType(n.type)] || 'blue'">{{ typeLabels[normType(n.type)] || n.type }}</span>
            </div>
            <p class="notif-body">{{ n.content }}</p>
            <div class="notif-meta">{{ fmt(n.created_at) }}</div>
          </div>
        </article>
        <p v-if="!items.length" class="empty">暂无通知</p>
      </div>
      <PaginationBar
        :total="total"
        :page="page"
        :page-size="pageSize"
        @update:page="onPageChange"
      />
    </section>

    <section class="panel">
      <div class="panel-head">
        <h2>学习评估</h2>
        <RouterLink to="/client/evaluations" class="more-link">查看全部</RouterLink>
      </div>
      <div v-if="evalLoading" class="loading">加载中…</div>
      <div v-else class="eval-list">
        <article v-for="e in evalItems" :key="e.id" class="eval-item" @click="detail = e">
          <div class="eval-title-row">
            <strong>{{ e.title || '学习评估' }}</strong>
            <span class="type-pill green">已发布</span>
          </div>
          <div class="eval-meta">
            {{ evalPeriod(e) }} · {{ e.teacher_name || '教师' }}
          </div>
          <p class="eval-summary">{{ evalSummary(e) || '点击查看完整评估内容' }}</p>
          <span class="eval-open">查看详情
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M12 5l7 7-7 7" /></svg>
          </span>
        </article>
        <p v-if="!evalItems.length" class="empty">暂无已发布评估</p>
      </div>
      <PaginationBar
        v-if="evalTotal > evalPageSize"
        :total="evalTotal"
        :page="evalPage"
        :page-size="evalPageSize"
        @update:page="onEvalPageChange"
      />
    </section>

    <EvaluationDetailDialog
      :visible="detail !== null"
      :evaluation="detail"
      :client-student-id="activeStudent?.id"
      show-ppt
      @close="detail = null"
    />
  </div>
</template>

<style scoped>
.page-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}

h1 {
  font-size: 22px;
}

.page-sub {
  color: var(--ink-3);
  font-size: 13px;
  margin-top: 4px;
}

.head-ops {
  display: flex;
  gap: 8px;
}

.filter-btn,
.read-all-btn {
  padding: 7px 14px;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--ink-2);
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}

.filter-btn.active {
  background: var(--brand-soft);
  border-color: #c7d2fe;
  color: var(--brand-strong);
}

.read-all-btn:hover {
  border-color: var(--brand);
  color: var(--brand-strong);
}

.panel {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 16px;
  padding: 18px 20px;
  margin-bottom: 16px;
}

.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}

.panel-head h2 {
  font-size: 16px;
}

.panel-sub {
  font-size: 12px;
  color: var(--ink-3);
}

.more-link {
  font-size: 13px;
  color: var(--brand);
  font-weight: 600;
}

.error-banner {
  background: var(--danger-soft);
  color: var(--danger);
  padding: 10px 14px;
  border-radius: 10px;
  margin-bottom: 12px;
  font-size: 13px;
}

.loading {
  text-align: center;
  color: var(--ink-3);
  font-size: 13px;
  padding: 20px 0;
}

.notif-list {
  display: flex;
  flex-direction: column;
}

.notif-item {
  display: flex;
  gap: 12px;
  padding: 13px 10px;
  border-radius: 12px;
  cursor: pointer;
  border-bottom: 1px solid #f1f5f9;
  transition: background 0.15s;
}

.notif-item:hover {
  background: var(--bg);
}

.notif-item.unread {
  background: #f8faff;
}

.notif-item.unread:hover {
  background: #f1f5ff;
}

.notif-icon {
  width: 34px;
  height: 34px;
  flex-shrink: 0;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
}

.notif-icon .dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
}

.notif-icon.cyan {
  background: var(--accent-soft);
}
.notif-icon.cyan .dot {
  background: #0e7490;
}

.notif-icon.orange {
  background: var(--warning-soft);
}
.notif-icon.orange .dot {
  background: #d97706;
}

.notif-icon.green {
  background: var(--success-soft);
}
.notif-icon.green .dot {
  background: #059669;
}

.notif-icon.red {
  background: var(--danger-soft);
}
.notif-icon.red .dot {
  background: #dc2626;
}

.notif-icon.blue {
  background: var(--brand-soft);
}
.notif-icon.blue .dot {
  background: var(--brand-strong);
}

.notif-icon.purple {
  background: #f3e8ff;
}
.notif-icon.purple .dot {
  background: #7e22ce;
}

.notif-icon.gold {
  background: var(--warning-soft);
}
.notif-icon.gold .dot {
  background: #f59e0b;
}

.notif-content {
  flex: 1;
  min-width: 0;
}

.notif-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.notif-title-row strong {
  font-size: 13.5px;
  color: var(--ink);
}

.type-pill {
  flex-shrink: 0;
  font-size: 11px;
  font-weight: 600;
  padding: 2px 9px;
  border-radius: 999px;
  background: var(--brand-soft);
  color: var(--brand-strong);
}

.type-pill.cyan {
  background: var(--accent-soft);
  color: #0e7490;
}

.type-pill.orange,
.type-pill.gold {
  background: var(--warning-soft);
  color: #b45309;
}

.type-pill.green {
  background: var(--success-soft);
  color: #047857;
}

.type-pill.red {
  background: var(--danger-soft);
  color: #b91c1c;
}

.type-pill.blue {
  background: var(--brand-soft);
  color: var(--brand-strong);
}

.type-pill.purple {
  background: #f3e8ff;
  color: #7e22ce;
}

.notif-body {
  font-size: 13px;
  color: var(--ink-2);
  line-height: 1.6;
  margin-top: 4px;
}

.notif-item.unread .notif-body {
  color: var(--ink);
}

.notif-meta {
  font-size: 11.5px;
  color: var(--ink-3);
  margin-top: 5px;
}

.empty {
  text-align: center;
  color: var(--ink-3);
  font-size: 13px;
  padding: 22px 0;
}

/* 学习评估区 */
.eval-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.eval-item {
  position: relative;
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 13px 14px;
  cursor: pointer;
  transition: all 0.15s;
}

.eval-item:hover {
  border-color: #c7d2fe;
  box-shadow: var(--shadow-sm);
}

.eval-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.eval-title-row strong {
  font-size: 13.5px;
}

.eval-meta {
  font-size: 11.5px;
  color: var(--ink-3);
  margin-top: 4px;
}

.eval-summary {
  font-size: 12.5px;
  color: var(--ink-2);
  line-height: 1.65;
  margin-top: 7px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.eval-open {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  font-weight: 600;
  color: var(--brand);
  margin-top: 9px;
}

.eval-open svg {
  width: 12px;
  height: 12px;
}
</style>
