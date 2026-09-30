<script setup lang="ts">
/**
 * 批改中心（跨作业聚合）：教师一眼看到哪些作业有学员提交、分别多少份待批改，
 * 点进去即批改，不再需要一个作业一个作业点开看。
 *
 * 数据源：GET /assignments/grading-center（后端聚合：应作答/已提交/待批改/已批改/最新提交时间，
 * 默认仅返回有待批改的作业，按待批改数 + 最新提交时间排序）。
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { listGradingCenter, type GradingCenterItem } from '@/api/assignment'
import PaginationBar from '@/components/PaginationBar.vue'
import { fmtDateTimeFromIso } from '@/utils/date'

const router = useRouter()

const items = ref<GradingCenterItem[]>([])
const total = ref(0)
const page = ref(1)
const limit = 15
const pendingOnly = ref(true)
const loading = ref(false)
const error = ref('')

const pendingTotal = computed(() => items.value.reduce((s, i) => s + (i.pending_review || 0), 0))

async function load() {
  loading.value = true
  error.value = ''
  try {
    const r = await listGradingCenter({
      pending_only: pendingOnly.value,
      limit,
      offset: (page.value - 1) * limit,
    })
    items.value = r.items
    total.value = r.total
  } catch (e: any) {
    error.value = e?.response?.data?.detail || '加载批改中心失败'
  } finally {
    loading.value = false
  }
}

function onPageChange(p: number) {
  page.value = p
  load()
}

function onPendingOnlyChange() {
  page.value = 1
  load()
}

function goGrade(id: string) {
  router.push(`/assignments/${id}/submissions`)
}

function progressText(i: GradingCenterItem): string {
  return `已提交 ${i.submitted}/${i.total_students}`
}

function progressPct(i: GradingCenterItem): number {
  if (!i.total_students) return 0
  return Math.min(100, Math.round((i.submitted / i.total_students) * 100))
}

onMounted(load)
</script>

<template>
  <div class="grading-view">
    <header class="page-head">
      <div>
        <h1>批改中心</h1>
        <p class="page-sub">
          {{ pendingOnly ? `共 ${pendingTotal} 份待批改 · 跨作业聚合，不用逐个点开看` : '全部已发布作业的提交进度' }}
        </p>
      </div>
      <label class="pending-check">
        <input v-model="pendingOnly" type="checkbox" @change="onPendingOnlyChange" />
        <span>只看有待批改</span>
      </label>
    </header>

    <p v-if="error" class="error-banner">{{ error }}</p>
    <div v-if="loading" class="loading-tip">加载中…</div>
    <div v-else-if="items.length === 0" class="empty-tip">
      {{ pendingOnly ? '太棒了，当前没有待批改的提交' : '暂无已发布作业' }}
    </div>

    <div v-else class="grade-list">
      <div
        v-for="i in items"
        :key="i.assignment_id"
        class="grade-card"
        @click="goGrade(i.assignment_id)"
      >
        <div class="g-main">
          <div class="g-top">
            <strong class="g-title">{{ i.title }}</strong>
            <span class="pill" :class="i.mode === 'classwork' ? 'classwork' : 'homework'">
              {{ i.mode === 'classwork' ? '课堂' : '课后' }}
            </span>
            <span v-if="i.pending_review > 0" class="pending-badge">{{ i.pending_review }} 待批改</span>
            <span v-else class="done-badge">已批完</span>
          </div>
          <div class="g-meta">
            <span v-if="i.teacher_name">出题：{{ i.teacher_name }}</span>
            <span v-if="i.class_names.length"> · {{ i.class_names.join('、') }}</span>
            <span v-if="i.latest_submitted_at"> · 最新提交 {{ fmtDateTimeFromIso(i.latest_submitted_at) }}</span>
          </div>
          <div class="g-progress">
            <div class="g-bar"><div class="g-fill" :style="{ width: `${progressPct(i)}%` }" /></div>
            <span class="g-progress-text">{{ progressText(i) }} · 已批改 {{ i.graded }}</span>
          </div>
        </div>
        <button class="grade-btn" @click.stop="goGrade(i.assignment_id)">
          {{ i.pending_review > 0 ? '去批改' : '查看' }}
        </button>
      </div>
    </div>

    <PaginationBar v-if="total > limit" :total="total" :page-size="limit" :page="page" @update:page="onPageChange" />
  </div>
</template>

<style scoped>
.grading-view {
  max-width: 960px;
  margin: 0 auto;
}
.page-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
}
.page-head h1 {
  font-size: 24px;
}
.page-sub {
  color: var(--ink-3);
  font-size: 13px;
  margin-top: 4px;
}
.pending-check {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--ink-2);
  cursor: pointer;
  padding-top: 6px;
}
.pending-check input[type='checkbox'] {
  width: 15px;
  height: 15px;
  accent-color: #6366f1;
}
.error-banner {
  color: var(--danger);
  background: var(--danger-soft);
  border-radius: 10px;
  padding: 10px 14px;
  font-size: 13px;
  margin-bottom: 12px;
}
.loading-tip,
.empty-tip {
  text-align: center;
  color: var(--ink-3);
  font-size: 13px;
  padding: 36px 0;
}
.grade-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.grade-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 16px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--surface);
  cursor: pointer;
  transition: border-color 0.15s ease;
}
.grade-card:hover {
  border-color: var(--brand);
}
.g-main {
  flex: 1;
  min-width: 0;
}
.g-top {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.g-title {
  font-size: 14.5px;
  color: var(--ink);
}
.pill {
  font-size: 11px;
  padding: 3px 9px;
  border-radius: 999px;
  font-weight: 600;
  white-space: nowrap;
}
.pill.classwork {
  background: #fef3c7;
  color: #b45309;
}
.pill.homework {
  background: #e0e7ff;
  color: #4338ca;
}
.pending-badge {
  background: #fef3c7;
  color: #b45309;
  font-weight: 700;
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 999px;
  white-space: nowrap;
}
.done-badge {
  background: var(--success-soft);
  color: #047857;
  font-weight: 700;
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 999px;
  white-space: nowrap;
}
.g-meta {
  font-size: 12px;
  color: var(--ink-3);
  margin-top: 4px;
}
.g-progress {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 8px;
}
.g-bar {
  flex: 1;
  height: 6px;
  border-radius: 999px;
  background: var(--line);
  overflow: hidden;
}
.g-fill {
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(135deg, #6366f1, #06b6d4);
}
.g-progress-text {
  font-size: 12px;
  color: var(--ink-2);
  white-space: nowrap;
}
.grade-btn {
  flex-shrink: 0;
  padding: 8px 16px;
  border: none;
  border-radius: 9px;
  background: linear-gradient(135deg, #6366f1, #06b6d4);
  color: #fff;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
}
.grade-btn:hover {
  filter: brightness(1.05);
}
</style>
