<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import EvaluationDetailDialog from '@/components/EvaluationDetailDialog.vue'
import PaginationBar from '@/components/PaginationBar.vue'
import {
  listClientEvaluations,
  type ClientEvaluationOut,
} from '@/api/evaluation'
import { useClientStore } from '@/stores/client'

const store = useClientStore()
const route = useRoute()
const student = computed(() => store.activeStudent)

const allItems = ref<ClientEvaluationOut[]>([])
const page = ref(1)
const pageSize = 6
const loading = ref(false)
const error = ref('')
const detail = ref<ClientEvaluationOut | null>(null)
const yearFilter = ref('')

const LEVEL_LABELS: Record<number, string> = {
  5: '非常优秀',
  4: '优秀',
  3: '良好',
  2: '需加强',
  1: '待观察',
}

interface SubjectItem {
  name: string
  level: number
  comment: string
}

function contentOf(ev: ClientEvaluationOut | null | undefined): Record<string, unknown> {
  return (ev?.content ?? {}) as Record<string, unknown>
}

function subjectsOf(ev: ClientEvaluationOut | null | undefined): SubjectItem[] {
  const raw = contentOf(ev).subjects
  if (!Array.isArray(raw)) return []
  return (raw as Array<Record<string, unknown>>).map((s) => ({
    name: String(s?.name ?? ''),
    level: Math.min(5, Math.max(1, Number(s?.level) || 3)),
    comment: String(s?.comment ?? ''),
  }))
}

function summaryOf(ev: ClientEvaluationOut | null | undefined): string {
  const s = contentOf(ev)
  return typeof s.summary === 'string' ? s.summary : ''
}

function num(v: unknown, fallback = 0): number {
  const n = Number(v)
  return Number.isFinite(n) ? n : fallback
}

function statNum(ev: ClientEvaluationOut | null | undefined, key: string): number | null {
  const s = (ev?.stats ?? null) as Record<string, unknown> | null
  if (!s || s[key] == null) return null
  return num(s[key])
}

function fmtDate(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

function publishedKey(ev: ClientEvaluationOut | null | undefined): string {
  if (!ev) return ''
  if (ev.published_at) return ev.published_at.slice(0, 10)
  return String(ev.period_end || '').slice(0, 10)
}

/** 按发布时间倒序（最新在前） */
const sortedAll = computed(() =>
  [...allItems.value].sort((a, b) => publishedKey(b).localeCompare(publishedKey(a))),
)

const latest = computed(() => sortedAll.value[0] ?? null)
const previous = computed(() => sortedAll.value[1] ?? null)

const years = computed(() => {
  const set = new Set<string>()
  for (const ev of sortedAll.value) {
    set.add(publishedKey(ev).slice(0, 4))
  }
  return [...set].sort((a, b) => b.localeCompare(a))
})

/** 年份筛选后的列表 */
const filtered = computed(() =>
  yearFilter.value ? sortedAll.value.filter((e) => publishedKey(e).startsWith(yearFilter.value)) : sortedAll.value,
)

const items = computed(() =>
  filtered.value.slice((page.value - 1) * pageSize, page.value * pageSize),
)

const total = computed(() => filtered.value.length)

/** 成长概览：以最近一次评估的统计为主 */
const overview = computed(() => {
  const ev = latest.value
  if (!ev) return null
  const rate = statNum(ev, 'attendance_rate')
  const score = statNum(ev, 'homework_score_rate')
  return {
    rate: rate != null ? `${Math.round(rate * 100)}%` : '—',
    attended: num((ev.stats as Record<string, unknown> | null)?.attended),
    leave: num((ev.stats as Record<string, unknown> | null)?.leave),
    lessons: num((ev.stats as Record<string, unknown> | null)?.consumed_lessons),
    feedbacks: num((ev.stats as Record<string, unknown> | null)?.feedback_count),
    score: score != null ? `${Math.round(score * 100)}%` : null,
    period: `${String(ev.period_start).slice(0, 10)} ~ ${String(ev.period_end).slice(0, 10)}`,
    count: sortedAll.value.length,
  }
})

/** 能力成长轨迹：对比最近两次评估同名能力项的星级变化 */
const growth = computed(() => {
  const cur = latest.value
  if (!cur) return []
  const curSubs = subjectsOf(cur)
  if (!curSubs.length) return []
  const prevMap = new Map<string, number>()
  for (const s of subjectsOf(previous.value)) {
    prevMap.set(s.name, s.level)
  }
  return curSubs
    .filter((s) => s.name.trim())
    .map((s) => {
      const prevLevel = prevMap.get(s.name)
      const delta = prevLevel != null ? s.level - prevLevel : null
      return { ...s, prevLevel, delta }
    })
})

function applyStudentFromRoute() {
  const sid = route.query.student_id
  if (typeof sid === 'string' && sid && sid !== store.activeStudentId) {
    store.setActiveStudent(sid)
  }
}

function onPageChange(p: number) {
  page.value = p
}

watch(yearFilter, () => {
  page.value = 1
})

async function load() {
  try {
    if (!store.me) await store.loadMe(true)
  } catch {
    // 账号信息加载失败（如令牌过期/网络断开）——下方按 me 状态兜底提示，可手动重试
  }
  if (!student.value) {
    loading.value = false
    error.value = store.me ? '未找到关联学员，请联系机构老师确认账号绑定' : '账号信息加载失败，请重新进入或下拉刷新重试'
    return
  }
  loading.value = true
  error.value = ''
  try {
    const data = await listClientEvaluations(student.value.id, { limit: 50 })
    allItems.value = data.items
  } catch {
    error.value = '加载评估失败，请重试'
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  applyStudentFromRoute()
  load()
})

watch(() => store.activeStudentId, () => {
  yearFilter.value = ''
  page.value = 1
  load()
})

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
    <!-- 顶部说明卡 -->
    <div class="eval-hero">
      <div class="hero-deco" />
      <div class="hero-text">
        <h1>学习评估</h1>
        <p class="hero-sub">
          老师为孩子撰写的阶段性综合评估，包含课堂表现、能力成长与家庭建议
        </p>
      </div>
      <div v-if="student" class="hero-chip">{{ student.name }}</div>
    </div>

    <p v-if="error" class="error-banner">
      {{ error }}
      <button class="retry-btn" @click="load">重新加载</button>
    </p>

    <!-- 骨架屏 -->
    <template v-if="loading">
      <div class="ov-grid">
        <div v-for="i in 4" :key="i" class="ov-card skeleton">
          <div class="sk-line w40" />
          <div class="sk-line strong w60" />
          <div class="sk-line w30" />
        </div>
      </div>
      <div v-for="i in 2" :key="`sk-${i}`" class="eval-card skeleton-card">
        <div class="sk-line w30" />
        <div class="sk-line w70" />
        <div class="sk-line w90" />
      </div>
    </template>

    <template v-else>
      <div v-if="!student" class="empty-tip">
        还没有关联学员，请联系机构老师绑定后再查看评估
      </div>

      <template v-else-if="latest">
        <!-- 成长概览 -->
        <section class="ov-grid">
          <div class="ov-card">
            <p class="ov-label">出勤情况</p>
            <strong class="ov-value">{{ overview?.rate }}</strong>
            <span class="ov-sub">到课 {{ overview?.attended }} 次 · 请假 {{ overview?.leave }} 次</span>
          </div>
          <div class="ov-card cyan">
            <p class="ov-label">课时消耗</p>
            <strong class="ov-value">{{ overview?.lessons }}<em>节</em></strong>
            <span class="ov-sub">{{ overview?.period }}</span>
          </div>
          <div v-if="overview?.score" class="ov-card green">
            <p class="ov-label">作业得分率</p>
            <strong class="ov-value">{{ overview.score }}</strong>
            <span class="ov-sub">最近评估周期平均</span>
          </div>
          <div class="ov-card amber">
            <p class="ov-label">累计评估</p>
            <strong class="ov-value">{{ overview?.count }}<em>份</em></strong>
            <span class="ov-sub">课后反馈 {{ overview?.feedbacks }} 篇</span>
          </div>
        </section>

        <!-- 能力成长轨迹 -->
        <section v-if="growth.length" class="panel growth-panel">
          <div class="panel-head">
            <h2>能力成长轨迹</h2>
            <span class="panel-sub">
              {{ previous ? `${publishedKey(previous)} → ${publishedKey(latest)}` : '最近一次评估' }}
            </span>
          </div>
          <div class="growth-list">
            <div v-for="g in growth" :key="g.name" class="growth-item">
              <div class="growth-name">
                <strong>{{ g.name }}</strong>
                <span v-if="g.comment" class="growth-comment">{{ g.comment }}</span>
              </div>
              <div class="growth-stars" :aria-label="`当前 ${g.level} / 5`">
                <span v-for="n in 5" :key="n" class="star" :class="{ on: n <= g.level }">★</span>
              </div>
              <span v-if="g.prevLevel != null" class="growth-delta" :class="{ up: (g.delta ?? 0) > 0, down: (g.delta ?? 0) < 0 }">
                <template v-if="(g.delta ?? 0) > 0">↑ 上升 {{ g.delta }} 级</template>
                <template v-else-if="(g.delta ?? 0) < 0">↓ 下滑 {{ -(g.delta ?? 0) }} 级</template>
                <template v-else>· 与上期持平</template>
              </span>
              <span v-else class="growth-delta new">本期新增</span>
              <span class="growth-level" :class="`lv${g.level}`">{{ LEVEL_LABELS[g.level] }}</span>
            </div>
          </div>
        </section>

        <!-- 评估列表 -->
        <section class="panel list-panel">
          <div class="panel-head">
            <h2>全部评估</h2>
            <div v-if="years.length > 1" class="year-chips">
              <button class="year-chip" :class="{ active: yearFilter === '' }" @click="yearFilter = ''">全部</button>
              <button
                v-for="y in years"
                :key="y"
                class="year-chip"
                :class="{ active: yearFilter === y }"
                @click="yearFilter = y"
              >{{ y }} 年</button>
            </div>
          </div>
          <div class="eval-list">
            <article v-for="ev in items" :key="ev.id" class="eval-card" @click="detail = ev">
              <div class="card-top">
                <span class="card-badge">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2 15 8.6 22 9.3 17 14 18.2 21 12 17.6 5.8 21 7 14 2 9.3 9 8.6z" /></svg>
                  学习评估
                </span>
                <span class="card-date">{{ publishedKey(ev) }} 发布</span>
              </div>
              <h2 class="card-title">{{ ev.title || `${student.name} 学习评估` }}</h2>
              <p class="card-meta">
                {{ String(ev.period_start).slice(0, 10) }} ~ {{ String(ev.period_end).slice(0, 10) }} ·
                {{ ev.teacher_name || '教师' }}
                <template v-if="subjectsOf(ev).length"> · {{ subjectsOf(ev).length }} 项能力评估</template>
                <template v-if="ev.ppt_url"> · 含家长会 PPT</template>
              </p>
              <p class="card-summary">{{ summaryOf(ev) || '查看完整评估内容' }}</p>
              <div class="card-subjects">
                <span v-for="s in subjectsOf(ev).slice(0, 4)" :key="s.name" class="subject-chip" :class="`lv${s.level}`">
                  {{ s.name }}
                </span>
                <span v-if="subjectsOf(ev).length > 4" class="subject-chip more">+{{ subjectsOf(ev).length - 4 }}</span>
              </div>
              <div class="card-foot">
                <span class="read-link">
                  查看完整评估
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M12 5l7 7-7 7" /></svg>
                </span>
              </div>
            </article>
          </div>
          <PaginationBar :total="total" :page="page" :page-size="pageSize" @update:page="onPageChange" />
        </section>
      </template>

      <div v-else class="empty-tip">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M7 3h10a2 2 0 0 1 2 2v16H5V5a2 2 0 0 1 2-2zM8 8h8M8 12h8M8 16h5" /></svg>
        <p>暂无已发布的学习评估</p>
        <span>老师在每个评估周期结束后会发布评估，届时可在通知中查看</span>
      </div>
    </template>

    <!-- 评估详情 -->
    <EvaluationDetailDialog
      :visible="detail !== null"
      :evaluation="detail"
      :client-student-id="student?.id"
      show-ppt
      @close="detail = null"
    />
  </div>
</template>

<style scoped>
/* 顶部说明卡 */
.eval-hero {
  position: relative;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 24px 26px;
  border-radius: 20px;
  margin-bottom: 18px;
  background:
    radial-gradient(560px 220px at -12% -28%, rgba(124, 134, 255, 0.28), transparent 62%),
    radial-gradient(420px 180px at 92% 0%, rgba(0, 184, 219, 0.22), transparent 65%),
    linear-gradient(135deg, #1e1b4b 0%, #312e81 52%, #0e7490 100%);
  color: #f1f5f9;
  box-shadow: 0 10px 30px rgba(14, 116, 144, 0.22);
}

.hero-deco {
  position: absolute;
  right: -50px;
  top: -70px;
  width: 220px;
  height: 220px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(99, 102, 241, 0.55), transparent 70%);
  pointer-events: none;
}

.hero-text h1 {
  font-size: 21px;
  margin-bottom: 6px;
}

.hero-sub {
  font-size: 12.5px;
  color: rgba(241, 245, 249, 0.75);
  line-height: 1.6;
  max-width: 520px;
}

.hero-chip {
  flex-shrink: 0;
  padding: 8px 18px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.14);
  font-size: 14px;
  font-weight: 700;
}

.error-banner {
  background: var(--danger-soft);
  color: var(--danger);
  padding: 10px 14px;
  border-radius: 10px;
  margin-bottom: 14px;
  font-size: 13px;
}

.retry-btn {
  margin-left: 10px;
  padding: 3px 12px;
  border: 1px solid var(--danger);
  border-radius: 999px;
  background: transparent;
  color: var(--danger);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}

.retry-btn:hover {
  background: var(--danger);
  color: #fff;
}

.empty-tip {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  text-align: center;
  color: var(--ink-3);
  padding: 48px 20px;
  font-size: 14px;
  background: var(--surface);
  border: 1px dashed var(--line);
  border-radius: 16px;
}

.empty-tip svg {
  width: 34px;
  height: 34px;
  color: #cbd5e1;
}

.empty-tip p {
  font-weight: 600;
  color: var(--ink-2);
}

.empty-tip span {
  font-size: 12.5px;
}

/* —— 成长概览 —— */
.ov-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 16px;
}

.ov-card {
  position: relative;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 16px 17px;
  border-radius: 16px;
  background: var(--surface);
  border: 1px solid var(--line);
  box-shadow: var(--shadow-xs);
}
.ov-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 3px;
  background: var(--brand-gradient);
  opacity: 0.9;
}
.ov-card.cyan::before {
  background: linear-gradient(90deg, #00b8db, #615fff);
}
.ov-card.green::before {
  background: linear-gradient(90deg, #0e9f6e, #00b8db);
}
.ov-card.amber::before {
  background: linear-gradient(90deg, #f59e0b, #615fff);
}

.ov-label {
  font-size: 11.5px;
  color: var(--ink-3);
}

.ov-value {
  font-size: 24px;
  font-weight: 800;
  letter-spacing: -0.02em;
  color: var(--ink);
  line-height: 1.2;
}

.ov-value em {
  font-style: normal;
  font-size: 12px;
  font-weight: 600;
  color: var(--ink-3);
  margin-left: 3px;
}

.ov-sub {
  font-size: 11px;
  color: var(--ink-3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ov-card.cyan {
  background: linear-gradient(180deg, #ecfeff, var(--surface));
  border-color: #bae6fd;
}

.ov-card.cyan .ov-value {
  color: #0e7490;
}

.ov-card.green {
  background: linear-gradient(180deg, #ecfdf5, var(--surface));
  border-color: #a7f3d0;
}

.ov-card.green .ov-value {
  color: #047857;
}

.ov-card.amber {
  background: linear-gradient(180deg, #fffbeb, var(--surface));
  border-color: #fde68a;
}

.ov-card.amber .ov-value {
  color: #b45309;
}

/* —— 面板 —— */
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
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}

.panel-head h2 {
  font-size: 16px;
}

.panel-sub {
  font-size: 12px;
  color: var(--ink-3);
}

/* —— 能力成长轨迹 —— */
.growth-panel {
  border-color: #c7d2fe;
  background: linear-gradient(180deg, #eef2ff 0%, var(--surface) 62%);
  box-shadow: var(--shadow-sm);
}

.growth-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.growth-item {
  position: relative;
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 12px 14px 12px 16px;
  border-radius: 14px;
  background: var(--surface);
  border: 1px solid var(--line);
  box-shadow: var(--shadow-xs);
  flex-wrap: wrap;
}
.growth-item::before {
  content: '';
  position: absolute;
  left: 0;
  top: 12px;
  bottom: 12px;
  width: 3px;
  border-radius: 0 999px 999px 0;
  background: var(--brand-gradient);
  opacity: 0.8;
}

.growth-name {
  flex: 1;
  min-width: 130px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.growth-name strong {
  font-size: 13.5px;
  color: var(--ink);
}

.growth-comment {
  font-size: 11.5px;
  color: var(--ink-3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 220px;
}

.growth-stars {
  display: flex;
  gap: 2px;
  flex-shrink: 0;
}

.star {
  font-size: 15px;
  line-height: 1;
  color: #e2e8f0;
}

.star.on {
  color: #f59e0b;
}

.growth-delta {
  flex-shrink: 0;
  font-size: 11.5px;
  font-weight: 700;
  padding: 3px 10px;
  border-radius: 999px;
  background: #f1f5f9;
  color: var(--ink-3);
}

.growth-delta.up {
  background: var(--success-soft);
  color: #047857;
}

.growth-delta.down {
  background: var(--warning-soft);
  color: #b45309;
}

.growth-delta.new {
  background: var(--brand-soft);
  color: var(--brand-strong);
}

.growth-level {
  flex-shrink: 0;
  font-size: 11px;
  font-weight: 700;
  padding: 3px 10px;
  border-radius: 999px;
}

.growth-level.lv5 {
  background: var(--success-soft);
  color: #047857;
}

.growth-level.lv4 {
  background: #d1fae5;
  color: #059669;
}

.growth-level.lv3 {
  background: var(--accent-soft);
  color: #0e7490;
}

.growth-level.lv2 {
  background: var(--warning-soft);
  color: #b45309;
}

.growth-level.lv1 {
  background: var(--danger-soft);
  color: #b91c1c;
}

/* —— 评估列表 —— */
.year-chips {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.year-chip {
  padding: 5px 13px;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--ink-2);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}

.year-chip:hover {
  border-color: var(--brand);
  color: var(--brand-strong);
}

.year-chip.active {
  background: linear-gradient(135deg, #6366f1, #06b6d4);
  border-color: transparent;
  color: #fff;
  box-shadow: 0 3px 10px rgba(99, 102, 241, 0.28);
}

.eval-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.eval-card {
  position: relative;
  overflow: hidden;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 16px;
  padding: 16px 18px 14px 19px;
  cursor: pointer;
  transition:
    border-color 0.16s,
    box-shadow 0.16s,
    transform 0.16s;
}
.eval-card::before {
  content: '';
  position: absolute;
  left: 0;
  top: 14px;
  bottom: 14px;
  width: 3px;
  border-radius: 0 999px 999px 0;
  background: var(--brand-gradient);
  opacity: 0.85;
}

.eval-card:hover {
  border-color: #a5b4fc;
  box-shadow: var(--shadow-md);
  transform: translateY(-2px);
}

.card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 10px;
}

.card-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  font-weight: 700;
  padding: 4px 11px;
  border-radius: 999px;
  background: var(--brand-soft);
  color: var(--brand-strong);
}

.card-badge svg {
  width: 12px;
  height: 12px;
}

.card-date {
  font-size: 11.5px;
  color: var(--ink-3);
}

.card-title {
  font-size: 16px;
  font-weight: 700;
  color: var(--ink);
  margin-bottom: 6px;
}

.card-meta {
  font-size: 12px;
  color: var(--ink-3);
  margin-bottom: 10px;
}

.card-summary {
  font-size: 13px;
  line-height: 1.7;
  color: var(--ink-2);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.card-subjects {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 10px;
}

.subject-chip {
  font-size: 11px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 999px;
  background: var(--bg);
  border: 1px solid var(--line);
  color: var(--ink-2);
  transition: border-color 0.12s;
}
.subject-chip:hover {
  border-color: var(--brand);
}

.subject-chip.lv5 {
  background: var(--success-soft);
  border-color: #a7f3d0;
  color: #047857;
}

.subject-chip.lv4 {
  background: #d1fae5;
  border-color: #a7f3d0;
  color: #059669;
}

.subject-chip.lv3 {
  background: var(--accent-soft);
  border-color: #bae6fd;
  color: #0e7490;
}

.subject-chip.lv2 {
  background: var(--warning-soft);
  border-color: #fde68a;
  color: #b45309;
}

.subject-chip.lv1 {
  background: var(--danger-soft);
  border-color: #fecaca;
  color: #b91c1c;
}

.subject-chip.more {
  background: var(--brand-soft);
  border-color: #c7d2fe;
  color: var(--brand-strong);
}

.card-foot {
  display: flex;
  justify-content: flex-end;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed #eef2f7;
}

.read-link {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--brand);
}

.read-link svg {
  width: 13px;
  height: 13px;
}

/* —— 骨架屏 —— */
.skeleton,
.skeleton-card {
  position: relative;
  overflow: hidden;
}

.skeleton-card {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 16px;
  padding: 18px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-bottom: 12px;
}

.sk-line {
  height: 12px;
  border-radius: 6px;
  background: #eef2f7;
}

.sk-line.strong {
  height: 20px;
  border-radius: 8px;
}

.w30 {
  width: 30%;
}

.w40 {
  width: 40%;
}

.w60 {
  width: 60%;
}

.w70 {
  width: 70%;
}

.w90 {
  width: 90%;
}

.skeleton .sk-line::after,
.skeleton-card .sk-line::after {
  content: '';
  position: absolute;
  inset: 0;
  transform: translateX(-100%);
  background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.7), transparent);
  animation: sk-shimmer 1.4s infinite;
}

@keyframes sk-shimmer {
  100% {
    transform: translateX(100%);
  }
}

@media (max-width: 640px) {
  .eval-hero {
    flex-direction: column;
    align-items: flex-start;
  }
  .ov-grid {
    grid-template-columns: repeat(2, 1fr);
  }
  .growth-item {
    gap: 8px;
  }
  .growth-name {
    min-width: 100%;
  }
}
</style>
