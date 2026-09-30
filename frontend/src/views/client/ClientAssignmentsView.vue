<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'

import PaginationBar from '@/components/PaginationBar.vue'
import { listClientAssignments, type ClientAssignmentListItem } from '@/api/client'
import { useClientStore } from '@/stores/client'

const store = useClientStore()
const router = useRouter()
const route = useRoute()

const student = computed(() => store.activeStudent)
const items = ref<ClientAssignmentListItem[]>([])
const loading = ref(false)
const error = ref('')

// 筛选 Tab
const filter = ref<'all' | 'pending' | 'submitted' | 'graded'>('all')
const modeTab = ref<'all' | 'classwork' | 'homework'>('all')
const page = ref(1)
const pageSize = 10
const total = ref(0)

const filtered = computed(() => {
  let list = items.value
  if (modeTab.value !== 'all') list = list.filter((a) => a.mode === modeTab.value)
  if (filter.value === 'all') return list
  return list.filter((a) => a.my_status === filter.value)
})

const filterTabs = [
  { key: 'all', label: '全部' },
  { key: 'pending', label: '未完成' },
  { key: 'submitted', label: '待批改' },
  { key: 'graded', label: '已批改' },
] as const

function deadlineText(a: ClientAssignmentListItem): string {
  if (!a.deadline) return '无截止时间'
  const d = new Date(a.deadline)
  const now = new Date()
  const over = now > d
  const pad = (n: number) => String(n).padStart(2, '0')
  const text = `${d.getMonth() + 1}月${d.getDate()}日 ${pad(d.getHours())}:${pad(d.getMinutes())} 截止`
  return over ? `${text}（已截止）` : text
}

function isOverdue(a: ClientAssignmentListItem): boolean {
  return !!a.deadline && new Date(a.deadline) < new Date() && a.my_status === 'not_submitted'
}

function statusPill(a: ClientAssignmentListItem): { cls: string; label: string } {
  if (a.my_status === 'graded') {
    if (a.my_passed === true) return { cls: 'passed', label: `达标 ${a.my_score}/${a.my_total}` }
    if (a.my_passed === false) return { cls: 'failed', label: `未达标 ${a.my_score}/${a.my_total}` }
    return { cls: 'graded', label: `已批改 ${a.my_score}/${a.my_total}` }
  }
  if (a.my_status === 'submitted') return { cls: 'submitted', label: '待批改' }
  if (isOverdue(a)) return { cls: 'overdue', label: '已截止未提交' }
  return { cls: 'pending', label: '未完成' }
}

async function load() {
  if (!store.me) await store.loadMe(true)
  if (!student.value) return
  loading.value = true
  error.value = ''
  try {
    const pageData = await listClientAssignments(student.value.id, {
      limit: pageSize,
      offset: (page.value - 1) * pageSize,
    })
    items.value = pageData.items
    total.value = pageData.total
  } catch {
    error.value = '加载作业失败'
  } finally {
    loading.value = false
  }
}

function onPageChange(p: number) {
  page.value = p
  load()
}

function openAssignment(a: ClientAssignmentListItem) {
  router.push({
    name: 'client-assignment-detail',
    params: { id: a.id },
    query: student.value ? { student_id: student.value.id } : undefined,
  })
}

function applyStudentFromRoute() {
  const sid = route.query.student_id
  if (typeof sid === 'string' && sid && sid !== store.activeStudentId) {
    store.setActiveStudent(sid)
  }
}

onMounted(() => {
  applyStudentFromRoute()
  load()
})

// 切换学员后自动刷新作业列表
watch(
  () => store.activeStudentId,
  () => {
    page.value = 1
    load()
  },
)

watch(
  () => route.query.student_id,
  () => {
    applyStudentFromRoute()
    load()
  },
)
</script>

<template>
  <div>
    <header class="page-head">
      <div>
        <h1>在线作业</h1>
        <p class="page-sub" v-if="student">{{ student.name }} · 共 {{ total }} 份作业</p>
      </div>
    </header>

    <p v-if="error" class="error-banner">{{ error }}</p>

    <div class="tabs">
      <button
        v-for="t in filterTabs"
        :key="t.key"
        class="tab"
        :class="{ active: filter === t.key }"
        @click="filter = t.key"
      >
        {{ t.label }}
      </button>
      <span class="tab-sep" />
      <button class="tab mode" :class="{ active: modeTab === 'all' }" @click="modeTab = 'all'">全部模式</button>
      <button class="tab mode" :class="{ active: modeTab === 'classwork' }" @click="modeTab = 'classwork'">课堂作业</button>
      <button class="tab mode" :class="{ active: modeTab === 'homework' }" @click="modeTab = 'homework'">课后作业</button>
    </div>

    <div v-if="loading" class="loading-tip">加载中…</div>

    <div v-else-if="filtered.length === 0" class="empty-tip">暂无作业</div>

    <div v-else class="assignment-list">
      <div
        v-for="a in filtered"
        :key="a.id"
        class="assignment-card"
        :class="{ overdue: isOverdue(a) }"
        @click="openAssignment(a)"
      >
        <div class="card-main">
          <div class="card-top">
            <h3>{{ a.title }}</h3>
            <span class="status-pill" :class="statusPill(a).cls">{{ statusPill(a).label }}</span>
          </div>
          <p v-if="a.description" class="desc">{{ a.description }}</p>
          <div class="meta-row">
            <span class="mode-pill" :class="a.mode === 'classwork' ? 'classwork' : 'homework'">{{ a.mode === 'classwork' ? '课堂' : '课后' }}</span>
            <span>{{ a.question_count }} 题</span>
            <span v-if="a.class_names.length">· {{ a.class_names.join('、') }}</span>
            <span v-if="a.teacher_name">· {{ a.teacher_name }} 老师</span>
            <span>· {{ deadlineText(a) }}</span>
            <span v-if="student?.name">· {{ student.name }}</span>
          </div>
          <div class="progress-row">
            <span class="progress-text">已完成 {{ a.answered_count }}/{{ a.question_count }}</span>
            <div class="progress-bar">
              <div
                class="progress-fill"
                :style="{ width: `${a.question_count ? Math.round((a.answered_count / a.question_count) * 100) : 0}%` }"
              />
            </div>
          </div>
        </div>
        <div class="card-arrow">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m9 18 6-6-6-6" /></svg>
        </div>
      </div>
    </div>

    <PaginationBar :total="total" :page="page" :page-size="pageSize" @update:page="onPageChange" />
  </div>
</template>

<style scoped>
.page-head {
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

.error-banner {
  background: var(--danger-soft);
  color: var(--danger);
  padding: 10px 14px;
  border-radius: 10px;
  margin-bottom: 14px;
  font-size: 13px;
}

.tabs {
  display: flex;
  gap: 8px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}

.tab {
  padding: 7px 16px;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--ink-3);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.15s;
}

.tab.active {
  background: linear-gradient(135deg, #6366f1, #06b6d4);
  color: #fff;
  border-color: transparent;
  font-weight: 600;
}

.assignment-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.assignment-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px 18px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 14px;
  cursor: pointer;
  transition: all 0.15s;
}

.assignment-card:hover {
  border-color: #c7d2fe;
  box-shadow: var(--shadow-sm);
  transform: translateY(-2px);
}

.assignment-card.overdue {
  border-left: 3px solid var(--danger);
}

.card-main {
  flex: 1;
  min-width: 0;
}

.card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 6px;
}

.card-top h3 {
  font-size: 15px;
}

.status-pill {
  font-size: 11.5px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 999px;
  flex-shrink: 0;
}

.status-pill.pending {
  background: var(--warning-soft);
  color: #b45309;
}

.status-pill.submitted {
  background: var(--brand-soft);
  color: var(--brand-strong);
}

.status-pill.graded {
  background: var(--success-soft);
  color: var(--success);
}

.status-pill.passed {
  background: var(--success-soft);
  color: var(--success);
}

.status-pill.failed {
  background: var(--danger-soft);
  color: var(--danger);
}

.status-pill.overdue {
  background: var(--danger-soft);
  color: var(--danger);
}

.desc {
  font-size: 13px;
  color: var(--ink-2);
  margin-bottom: 8px;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 1;
  -webkit-box-orient: vertical;
}

.meta-row {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  font-size: 12px;
  color: var(--ink-3);
  margin-bottom: 10px;
  align-items: center;
}

.mode-pill {
  font-size: 11px;
  font-weight: 700;
  padding: 2px 9px;
  border-radius: 999px;
}
.mode-pill.classwork {
  background: #fef3c7;
  color: #b45309;
}
.mode-pill.homework {
  background: #e0e7ff;
  color: #4338ca;
}

.tab-sep {
  width: 1px;
  align-self: stretch;
  background: var(--line);
  margin: 2px 4px;
}
.tab.mode.active {
  background: linear-gradient(135deg, #f59e0b, #ef4444);
  border-color: transparent;
}

.progress-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.progress-text {
  font-size: 12px;
  color: var(--ink-3);
  flex-shrink: 0;
}

.progress-bar {
  flex: 1;
  height: 6px;
  border-radius: 3px;
  background: #eef2f7;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  border-radius: 3px;
  background: linear-gradient(90deg, #6366f1, #06b6d4);
  transition: width 0.3s;
}

.card-arrow {
  color: var(--ink-3);
  flex-shrink: 0;
}

.card-arrow svg {
  width: 20px;
  height: 20px;
}

.empty-tip {
  text-align: center;
  color: var(--ink-3);
  padding: 40px 0;
  font-size: 14px;
}

.loading-tip {
  text-align: center;
  color: var(--ink-3);
  font-size: 13px;
  padding: 20px 0;
}
</style>
