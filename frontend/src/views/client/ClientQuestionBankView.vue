<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import AbilityRadar from '@/components/AbilityRadar.vue'
import ExamStartDialog from '@/components/ExamStartDialog.vue'
import SearchableSelect from '@/components/SearchableSelect.vue'
import {
  aggregateSubjects,
  getAbilityComment,
  getAttemptTrend,
  getLearningStats,
  listBankSets,
  listPracticeAttempts,
  startPracticeAttempt,
  type AttemptSummary,
  type AttemptTrendWeek,
  type BankSet,
  type LearningStatsOut,
} from '@/api/questionBank'
import { useClientStore } from '@/stores/client'
import { useToastStore } from '@/stores/toast'

const store = useClientStore()
const router = useRouter()
const toast = useToastStore()

const student = computed(() => store.activeStudent)
const sets = ref<BankSet[]>([])
const stats = ref<LearningStatsOut | null>(null)
const attempts = ref<AttemptSummary[]>([])
const recordKind = ref('')
const recordStatus = ref('')
const trendWeeks = ref<AttemptTrendWeek[]>([])
const loading = ref(false)
const starting = ref(false)
const filterSubject = ref('')
const filterLevel = ref('')
const filterMonth = ref('')

const aggregateLoading = ref(false)
const aggregateForm = reactive({ subject: '', level: '', single_choice: 5, multiple_choice: 3, judgement: 5, programming: 1 })
const aggregateSubjectsList = ref<string[]>([])
const aggregateLevels = ref<string[]>([])
const aggregateSubjectOptions = computed(() =>
  aggregateSubjectsList.value.map((value) => ({ id: value, label: value })),
)
const aggregateLevelOptions = computed(() =>
  aggregateLevels.value.map((value) => ({ id: value, label: value })),
)
const abilityComment = ref('')
const commentLoading = ref(false)

const subjects = computed(() => [...new Set(sets.value.map((s) => s.subject).filter(Boolean))] as string[])
const levels = computed(() => [...new Set(sets.value.map((s) => s.level).filter(Boolean))] as string[])
const months = computed(() => [...new Set(sets.value.map((s) => s.exam_month || (s.exam_year ? String(s.exam_year) : '')).filter(Boolean))] as string[])
const filteredSets = computed(() =>
  sets.value.filter(
    (s) =>
      (!filterSubject.value || s.subject === filterSubject.value) &&
      (!filterLevel.value || s.level === filterLevel.value) &&
      (!filterMonth.value || (s.exam_month || String(s.exam_year || '')) === filterMonth.value),
  ),
)
const inProgress = computed(() => attempts.value.find((a) => a.status === 'in_progress'))
const examOpen = ref(false)

function kindLabel(kind?: string): string {
  const map: Record<string, string> = {
    quick: '刷题练习',
    aggregate: '综合练习',
    marked: '错题/收藏',
    exam_set: '套卷考试',
    exam_random: '随机考试',
    set_practice: '套卷练习',
  }
  return kind ? map[kind] ?? kind : ''
}

function pct(v: number): string {
  return `${Math.round(v * 100)}%`
}

function fmtDate(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  return `${d.getMonth() + 1}月${d.getDate()}日 ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

function attemptQuery() {
  return {
    limit: 20,
    ...(recordKind.value ? { kind: recordKind.value } : {}),
    ...(recordStatus.value ? { status: recordStatus.value } : {}),
  }
}

const trendChart = computed(() => {
  const weeks = trendWeeks.value
  if (weeks.length < 2) return null
  const w = 560
  const h = 130
  const pad = 18
  const xs = weeks.map((_, i) => pad + (i * (w - pad * 2)) / (weeks.length - 1))
  const ys = weeks.map(
    (wk) => h - pad - (Math.min(100, Math.max(0, wk.avg_score)) / 100) * (h - pad * 2),
  )
  return {
    w,
    h,
    pad,
    points: xs.map((x, i) => `${x.toFixed(1)},${ys[i].toFixed(1)}`).join(' '),
    dots: weeks.map((wk, i) => ({
      x: xs[i],
      y: ys[i],
      label: `${wk.week_start.slice(5).replace('-', '/')} 周 · ${wk.avg_score} 分（${wk.attempts} 次）`,
    })),
  }
})

watch([recordKind, recordStatus], async () => {
  if (!student.value) return
  const data = await listPracticeAttempts(student.value.id, attemptQuery()).catch(() => ({
    items: [] as AttemptSummary[],
    total: 0,
  }))
  attempts.value = data.items
})

async function load() {
  if (!store.me) await store.loadMe(true)
  if (!student.value) return
  loading.value = true
  try {
    const [setData, statData, attemptData, trendData] = await Promise.all([
      listBankSets(),
      getLearningStats(student.value.id).catch(() => null),
      listPracticeAttempts(student.value.id, attemptQuery()).catch(() => ({ items: [], total: 0 })),
      getAttemptTrend(student.value.id).catch(() => ({ weeks: [] as AttemptTrendWeek[] })),
    ])
    sets.value = setData.items
    stats.value = statData
    attempts.value = attemptData.items
    trendWeeks.value = trendData.weeks
  } catch {
    toast.error('题库加载失败')
  } finally {
    loading.value = false
  }
  await loadAggregateFilters()
}

async function startPractice(s: BankSet) {
  if (!student.value || starting.value) return
  starting.value = true
  try {
    const attempt = await startPracticeAttempt({
      student_id: student.value.id,
      mode: 'practice',
      set_id: s.id,
    })
    router.push({ name: 'client-practice', params: { id: attempt.id } })
  } catch (e: unknown) {
    toast.error((e as Error).message || '开始练习失败')
  } finally {
    starting.value = false
  }
}

async function beginAttempt(payload: Parameters<typeof startPracticeAttempt>[0]) {
  if (!student.value || starting.value) return
  starting.value = true
  try {
    const attempt = await startPracticeAttempt({ student_id: student.value.id, ...payload })
    router.push({ name: 'client-practice', params: { id: attempt.id } })
  } catch (e: unknown) {
    const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
    if (detail && typeof detail === 'object' && 'gaps' in detail) {
      const gaps = (detail as { gaps: Record<string, string> }).gaps
      toast.error(Object.values(gaps).join('；') || '题库库存不足')
    } else if (typeof detail === 'string') {
      toast.error(detail)
    } else {
      toast.error((e as Error).message || '开始练习失败')
    }
  } finally {
    starting.value = false
  }
}

async function startMarkedPractice(kind: 'favorite' | 'wrong') {
  await beginAttempt({ mode: 'practice', kind: 'marked', mark_kind: kind })
}

async function loadAggregateFilters() {
  try {
    const { subjects, levels } = await aggregateSubjects()
    aggregateSubjectsList.value = subjects
    aggregateLevels.value = levels
  } catch {
    /* 筛选器非必填，失败可忽略 */
  }
}

async function startAggregatePractice() {
  if (aggregateLoading.value) return
  aggregateLoading.value = true
  try {
    await beginAttempt({
      mode: 'practice',
      kind: 'aggregate',
      subject: aggregateForm.subject || undefined,
      level: aggregateForm.level || undefined,
      rules: {
        single_choice: aggregateForm.single_choice,
        multiple_choice: aggregateForm.multiple_choice,
        judgement: aggregateForm.judgement,
        programming: aggregateForm.programming,
      },
    })
  } finally {
    aggregateLoading.value = false
  }
}

function openExam() {
  examOpen.value = true
}

async function startExam(payload: {
  kind: 'exam_set' | 'exam_random'
  set_id?: string
  rules?: Record<string, number>
  subject?: string
  level?: string
}) {
  examOpen.value = false
  await beginAttempt({
    mode: 'exam',
    kind: payload.kind,
    set_id: payload.set_id,
    rules: payload.rules,
    subject: payload.subject,
    level: payload.level,
  })
}

async function loadAbilityComment() {
  if (!student.value || commentLoading.value) return
  commentLoading.value = true
  try {
    const res = await getAbilityComment(student.value.id)
    abilityComment.value = res.content
  } catch (e: unknown) {
    const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
    toast.error(typeof detail === 'string' ? detail : '生成学习建议失败，请稍后再试')
  } finally {
    commentLoading.value = false
  }
}

function openAttempt(a: AttemptSummary) {
  router.push({ name: 'client-practice', params: { id: a.id } })
}

onMounted(load)
watch(() => store.activeStudentId, load)
</script>

<template>
  <div class="cqb">
    <header class="qb-hero">
      <div>
        <div class="hero-eyebrow">QUESTION BANK</div>
        <h1>题库练习</h1>
        <p>{{ student?.name || '学员' }} · 真题练习与模拟考试，交卷后查看成绩与解析</p>
      </div>
      <button class="hero-btn" :disabled="starting" @click="openExam">开始模拟考试</button>
      <div class="hero-tools">
        <button class="hero-btn secondary" @click="startMarkedPractice('wrong')">错题本</button>
        <button class="hero-btn secondary" @click="startMarkedPractice('favorite')">我的收藏</button>
      </div>
    </header>

    <div v-if="inProgress" class="resume-card" @click="openAttempt(inProgress)">
      <div>
        <strong>继续上次练习</strong>
        <span>{{ inProgress.mode === 'exam' ? '模拟考试' : '套卷练习' }} · {{ fmtDate(inProgress.started_at) }}</span>
      </div>
      <span class="resume-arrow">继续 →</span>
    </div>

    <div v-if="stats" class="stat-grid">
      <div class="stat-tile">
        <span>练习次数</span>
        <strong>{{ stats.submitted }}</strong>
      </div>
      <div class="stat-tile">
        <span>题目正确率</span>
        <strong>{{ pct(stats.correct_rate) }}</strong>
      </div>
      <div class="stat-tile">
        <span>模考平均得分率</span>
        <strong>{{ pct(stats.avg_score_rate) }}</strong>
      </div>
      <div class="stat-tile">
        <span>连续学习</span>
        <strong>{{ stats.streak_days }} 天</strong>
      </div>
    </div>

    <section v-if="stats && stats.weak_points.length" class="weak-card">
      <h3>最需要复习</h3>
      <div class="weak-list">
        <span v-for="w in stats.weak_points" :key="w.name">{{ w.name }} · 错 {{ w.wrong }} 次</span>
      </div>
    </section>

    <section v-if="stats" class="ability-card">
      <div class="ability-head">
        <div>
          <h3>知识点能力雷达</h3>
          <p>按练习/考试中答对率统计，越靠外掌握越好。</p>
        </div>
        <button class="btn" :disabled="commentLoading" @click="loadAbilityComment">
          {{ commentLoading ? '生成中…' : 'AI 学习建议' }}
        </button>
      </div>
      <AbilityRadar :items="stats.radar ?? []" />
      <div v-if="stats.knowledge_stats?.length" class="kp-strip">
        <span
          v-for="kp in stats.knowledge_stats.slice(0, 12)"
          :key="kp.name"
          class="kp-chip"
          :class="{ low: kp.total >= 3 && kp.correct_rate < 0.6, thin: kp.total < 3 }"
        >
          {{ kp.name }} {{ pct(kp.correct_rate) }}
          <em>答对 {{ kp.correct }}/{{ kp.total }}{{ kp.total < 3 ? ' · 样本少' : '' }}</em>
        </span>
      </div>
      <p class="kp-note">样本少于 3 题的知识点仅作参考，多练几题后掌握度更准确。</p>
      <div v-if="abilityComment" class="ai-comment">
        <strong>AI 学习建议</strong>
        <p>{{ abilityComment }}</p>
      </div>
    </section>

    <section class="aggregate-section">
      <h2>综合练习</h2>
      <p>按科目、等级和题型从已发布题库抽题；作答即时判断，做错自动加入错题本。</p>
      <div class="aggregate-controls">
        <div class="aggregate-select">
          <span class="select-label">科目</span>
          <SearchableSelect
            v-model="aggregateForm.subject"
            :options="aggregateSubjectOptions"
            placeholder="全部科目"
            group="client-aggregate-subject"
          />
        </div>
        <div class="aggregate-select">
          <span class="select-label">等级</span>
          <SearchableSelect
            v-model="aggregateForm.level"
            :options="aggregateLevelOptions"
            placeholder="全部等级"
            group="client-aggregate-level"
          />
        </div>
        <div class="type-counts">
          <label>单选<input v-model.number="aggregateForm.single_choice" type="number" min="0" /></label>
          <label>多选<input v-model.number="aggregateForm.multiple_choice" type="number" min="0" /></label>
          <label>判断<input v-model.number="aggregateForm.judgement" type="number" min="0" /></label>
          <label>编程<input v-model.number="aggregateForm.programming" type="number" min="0" /></label>
        </div>
        <button class="btn primary" :disabled="aggregateLoading" @click="startAggregatePractice">
          {{ aggregateLoading ? '抽题中…' : '开始综合练习' }}
        </button>
      </div>
    </section>

    <section class="sets-section">
      <div class="section-head">
        <h2>可用真题套卷</h2>
        <div class="client-filters">
          <select v-model="filterSubject">
            <option value="">全部科目</option>
            <option v-for="v in subjects" :key="v" :value="v">{{ v }}</option>
          </select>
          <select v-model="filterLevel">
            <option value="">全部等级</option>
            <option v-for="v in levels" :key="v" :value="v">{{ v }}</option>
          </select>
          <select v-model="filterMonth">
            <option value="">全部年月</option>
            <option v-for="v in months" :key="v" :value="v">{{ v }}</option>
          </select>
        </div>
      </div>
      <div v-if="loading" class="empty">加载中…</div>
      <div v-else-if="filteredSets.length === 0" class="empty">暂无可练习的题库套卷</div>
      <div v-else class="set-grid">
        <article v-for="s in filteredSets" :key="s.id" class="set-card">
          <div class="set-top">
            <h3>{{ s.name }}</h3>
            <span class="set-badge">{{ s.question_count }} 题</span>
          </div>
          <p class="set-meta">
            <span v-if="s.institution">{{ s.institution }}</span>
            <span v-if="s.subject">{{ s.subject }}</span>
            <span v-if="s.level">{{ s.level }}</span>
            <span v-if="s.exam_month">{{ s.exam_month }}</span>
            <span v-else-if="s.exam_year">{{ s.exam_year }} 年</span>
          </p>
          <button class="start-btn" :disabled="starting" @click="startPractice(s)">开始练习</button>
        </article>
      </div>
    </section>

    <section v-if="trendChart" class="trend-section">
      <div class="history-head">
        <h2>近 8 周正确率趋势</h2>
        <span class="history-total">{{ trendWeeks.length }} 个有效周</span>
      </div>
      <svg
        class="trend-svg"
        :viewBox="`0 0 ${trendChart.w} ${trendChart.h}`"
        role="img"
        aria-label="近 8 周平均正确率趋势"
      >
        <line
          v-for="line in [50, 100]"
          :key="line"
          :x1="trendChart.pad"
          :x2="trendChart.w - trendChart.pad"
          :y1="trendChart.h - trendChart.pad - (line / 100) * (trendChart.h - trendChart.pad * 2)"
          :y2="trendChart.h - trendChart.pad - (line / 100) * (trendChart.h - trendChart.pad * 2)"
          class="trend-grid"
        />
        <polyline :points="trendChart.points" class="trend-line" />
        <circle
          v-for="d in trendChart.dots"
          :key="d.label"
          :cx="d.x"
          :cy="d.y"
          r="3.5"
          class="trend-dot"
        >
          <title>{{ d.label }}</title>
        </circle>
      </svg>
    </section>
    <section v-if="attempts.length" class="history-section">
      <div class="section-head">
        <h2>做题记录</h2>
        <div class="history-filters">
          <span class="history-total">最近 {{ attempts.length }} 条</span>
          <select v-model="recordKind" class="history-select">
            <option value="">全部模式</option>
            <option value="quick">刷题练习</option>
            <option value="aggregate">综合练习</option>
            <option value="marked">错题/收藏</option>
            <option value="set_practice">套卷练习</option>
            <option value="exam_set">套卷考试</option>
            <option value="exam_random">随机考试</option>
          </select>
          <select v-model="recordStatus" class="history-select">
            <option value="">全部状态</option>
            <option value="in_progress">进行中</option>
            <option value="evaluated">已完成</option>
          </select>
        </div>
      </div>
      <div class="history-list">
        <button v-for="a in attempts" :key="a.id" class="history-row" @click="openAttempt(a)">
          <span class="h-mode">{{ kindLabel(a.kind) || (a.mode === 'exam' ? '模拟考试' : '套卷练习') }}</span>
          <span class="h-date">{{ fmtDate(a.started_at) }}</span>
          <span class="h-score" :class="{ done: a.status === 'evaluated' }">
            <template v-if="a.status === 'evaluated' && a.mode === 'exam'">
              {{ a.normalized_score ?? 0 }} 分 · {{ a.rating }}
            </template>
            <template v-else-if="a.status === 'evaluated'">
              正确率 {{ pct(a.correct_rate ?? 0) }}
            </template>
            <template v-else>进行中 · 继续</template>
          </span>
        </button>
      </div>
    </section>

    <ExamStartDialog
      v-if="examOpen"
      :sets="sets"
      :subjects="subjects"
      :levels="levels"
      :default-subject="filterSubject || ''"
      :default-level="filterLevel || ''"
      @close="examOpen = false"
      @start="startExam"
    />
  </div>
</template>

<style scoped>
.cqb {
  max-width: 1080px;
  margin: 0 auto;
  padding: 18px 16px 90px;
}
.qb-hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 20px;
  border-radius: 18px;
  background: linear-gradient(135deg, #172554, #2f6f73);
  color: #f8fafc;
  box-shadow: 0 10px 30px rgba(15, 23, 42, 0.18);
}
.hero-eyebrow {
  font-size: 10.5px;
  letter-spacing: 0.28em;
  color: #e7b75b;
  font-weight: 700;
}
.qb-hero h1 {
  font-size: 24px;
  margin: 4px 0;
  font-family: 'Songti SC', 'Noto Serif SC', serif;
}
.qb-hero p {
  font-size: 12.5px;
  color: #cbd5e1;
}
.hero-btn {
  padding: 10px 16px;
  border-radius: 10px;
  border: 1px solid rgba(231, 183, 91, 0.6);
  background: rgba(231, 183, 91, 0.16);
  color: #fde68a;
  font-weight: 700;
  font-size: 13px;
  cursor: pointer;
  white-space: nowrap;
}
.resume-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 14px;
  padding: 12px 16px;
  border-radius: 12px;
  background: #fffbeb;
  border: 1px solid #fde68a;
  color: #92400e;
  cursor: pointer;
}
.resume-card strong {
  display: block;
  font-size: 13.5px;
}
.resume-card span {
  font-size: 11.5px;
  color: #b45309;
}
.resume-arrow {
  font-weight: 700;
}
.stat-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin-top: 14px;
}
.stat-tile {
  padding: 12px 14px;
  border-radius: 12px;
  background: var(--surface);
  border: 1px solid var(--line);
  box-shadow: var(--shadow-xs);
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.stat-tile span {
  font-size: 11.5px;
  color: var(--ink-3);
}
.stat-tile strong {
  font-size: 20px;
  color: #172554;
  font-family: ui-monospace, Consolas, monospace;
}
.weak-card {
  margin-top: 12px;
  padding: 12px 14px;
  border-radius: 12px;
  background: #fffaf0;
  border: 1px solid #e7dcc6;
}
.weak-card h3 {
  font-size: 13px;
  color: #7c5a1e;
  margin-bottom: 6px;
}
.weak-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.weak-list span {
  padding: 4px 9px;
  border-radius: 999px;
  background: #f1e7d2;
  color: #7c5a1e;
  font-size: 11.5px;
}
.ability-card {
  margin-top: 12px;
  padding: 14px 16px;
  border-radius: 14px;
  background: var(--surface);
  border: 1px solid var(--line);
  box-shadow: var(--shadow-xs);
}
.ability-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.ability-head h3 {
  font-size: 14px;
  color: var(--ink);
}
.ability-head p {
  margin-top: 3px;
  color: var(--ink-3);
  font-size: 11.5px;
}
.ai-comment {
  margin-top: 8px;
  padding: 12px 14px;
  border-radius: 10px;
  background: #f0fdfa;
  border: 1px solid #99f6e4;
}
.ai-comment strong {
  color: #0f766e;
  font-size: 12.5px;
}
.ai-comment p {
  margin-top: 5px;
  color: #115e59;
  font-size: 12.5px;
  line-height: 1.7;
  white-space: pre-wrap;
}
.kp-strip {
  margin-top: 10px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.kp-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 9px;
  border-radius: 999px;
  background: #f1f5f9;
  color: #475569;
  font-size: 11.5px;
}
.kp-chip.low {
  background: #fef2f2;
  color: #991b1b;
  border: 1px solid #fecaca;
}
.kp-chip.thin {
  color: #64748b;
}
.kp-chip em {
  margin-left: 4px;
  font-style: normal;
  font-size: 10.5px;
  color: #94a3b8;
}
.kp-note {
  margin-top: 8px;
  font-size: 11px;
  color: var(--ink-3);
}
.history-total {
  color: var(--ink-3);
  font-size: 11.5px;
}
.sets-section,
.trend-section {
  margin-top: 26px;
  padding: 16px 18px;
  border-radius: 16px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
}
.trend-svg {
  width: 100%;
  height: auto;
  margin-top: 6px;
}
.trend-grid {
  stroke: #e2e8f0;
  stroke-dasharray: 4 4;
  stroke-width: 1;
}
.trend-line {
  fill: none;
  stroke: #0d9488;
  stroke-width: 2.5;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.trend-dot {
  fill: #0d9488;
  stroke: #ffffff;
  stroke-width: 1.5;
}
.history-filters {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.history-select {
  padding: 5px 8px;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
  background: #ffffff;
  font-size: 12px;
  color: #334155;
}
.history-section {
  margin-top: 20px;
}
.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 10px;
}
.section-head h2 {
  font-size: 16px;
  color: var(--ink);
}
.client-filters {
  display: flex;
  gap: 8px;
}
.aggregate-section {
  margin-top: 16px;
  padding: 14px 16px;
  border-radius: 14px;
  background: #f0fdfa;
  border: 1px solid #99f6e4;
}
.aggregate-section h2 {
  margin: 0 0 6px;
  font-size: 16px;
  color: #0f766e;
}
.aggregate-section p {
  margin: 0 0 10px;
  font-size: 12px;
  color: #115e59;
}
.aggregate-controls {
  display: grid;
  grid-template-columns: repeat(2, minmax(160px, 1fr));
  gap: 10px;
  align-items: end;
}
.aggregate-select {
  display: flex;
  flex-direction: column;
  gap: 5px;
  min-width: 0;
}
.select-label {
  color: #0f766e;
  font-size: 11px;
  font-weight: 700;
}
.aggregate-select :deep(.ssel-trigger) {
  width: 100%;
  min-height: 38px;
  border: 1px solid #99f6e4;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.88);
  box-shadow: 0 1px 2px rgba(15, 118, 110, 0.06);
}
.aggregate-select :deep(.ssel-trigger:hover),
.aggregate-select :deep(.ssel-trigger.active) {
  border-color: #2dd4bf;
  box-shadow: 0 0 0 3px rgba(45, 212, 191, 0.13);
}
.type-counts {
  grid-column: 1 / -1;
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  font-size: 12px;
  color: #115e59;
}
.type-counts label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-weight: 700;
}
.type-counts input {
  width: 100%;
  box-sizing: border-box;
  min-height: 38px;
  padding: 7px 10px;
  border: 1px solid #bfe9df;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.88);
  color: #134e4a;
  font: inherit;
  transition: border-color 0.18s, box-shadow 0.18s;
}
.type-counts input:focus {
  outline: none;
  border-color: #0d9488;
  box-shadow: 0 0 0 3px rgba(13, 148, 136, 0.13);
}
.client-filters select {
  padding: 6px 9px;
  border-radius: 8px;
  border: 1px solid var(--line);
  background: var(--surface);
  font-size: 12px;
}
.set-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 12px;
}
.set-card {
  padding: 14px;
  border-radius: 14px;
  background: #fffdf8;
  border: 1px solid #e7dcc6;
  box-shadow: var(--shadow-xs);
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.set-top {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}
.set-card h3 {
  flex: 1;
  font-size: 14px;
  line-height: 1.4;
  color: #3f2f14;
}
.set-badge {
  flex-shrink: 0;
  padding: 2px 8px;
  border-radius: 999px;
  background: #f1e7d2;
  color: #7c5a1e;
  font-size: 10.5px;
  font-weight: 700;
}
.set-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 10px;
  font-size: 11.5px;
  color: var(--ink-3);
}
.start-btn {
  margin-top: auto;
  padding: 8px 12px;
  border-radius: 9px;
  border: none;
  background: #172554;
  color: #fff;
  font-size: 12.5px;
  font-weight: 700;
  cursor: pointer;
}
.start-btn:disabled {
  opacity: 0.6;
}
.history-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.history-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 11px 14px;
  border-radius: 10px;
  background: var(--surface);
  border: 1px solid var(--line);
  cursor: pointer;
  text-align: left;
}
.h-mode {
  font-weight: 700;
  font-size: 12.5px;
  color: var(--ink);
  min-width: 66px;
}
.h-date {
  flex: 1;
  font-size: 11.5px;
  color: var(--ink-3);
}
.h-score {
  font-family: ui-monospace, Consolas, monospace;
  font-size: 12px;
  color: #b45309;
}
.h-score.done {
  color: #166534;
}
.empty {
  padding: 30px;
  text-align: center;
  color: var(--ink-3);
  font-size: 13px;
  background: var(--surface);
  border-radius: 12px;
  border: 1px dashed var(--line);
}
.modal-mask {
  position: fixed;
  inset: 0;
  z-index: 70;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 18px;
}
.exam-modal {
  width: min(500px, 100%);
  background: #fffdf8;
  border-radius: 16px;
  padding: 20px;
  border: 1px solid #e7dcc6;
}
.exam-modal h3 {
  font-size: 18px;
  color: #3f2f14;
}
.modal-sub {
  margin: 6px 0 12px;
  font-size: 12px;
  color: var(--ink-3);
  line-height: 1.6;
}
.exam-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 9px;
}
.exam-grid label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 11.5px;
  color: #7c6a4a;
  font-weight: 600;
}
.exam-grid input {
  padding: 7px 9px;
  border: 1px solid #e2d5bb;
  border-radius: 8px;
  font-size: 13px;
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 14px;
}
@media (max-width: 640px) {
  .qb-hero {
    flex-direction: column;
    align-items: flex-start;
  }
  .stat-grid {
    grid-template-columns: 1fr 1fr;
  }
  .exam-grid {
    grid-template-columns: 1fr;
  }
}
</style>

