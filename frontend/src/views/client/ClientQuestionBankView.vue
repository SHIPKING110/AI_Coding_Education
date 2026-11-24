<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import TeacherPracticeDialog from '@/components/TeacherPracticeDialog.vue'
import SearchableSelect from '@/components/SearchableSelect.vue'
import {
  aggregatePractice,
  aggregateSubjects,
  getLearningStats,
  listBankSets,
  listPracticeAttempts,
  startPracticeAttempt,
  type AttemptSummary,
  type AggregatePracticeIn,
  type BankSet,
  type LearningStatsOut,
  type PracticeQuestion,
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
const loading = ref(false)
const starting = ref(false)
const filterSubject = ref('')
const filterLevel = ref('')
const filterMonth = ref('')

const aggregateOpen = ref(false)
const aggregateQuestions = ref<PracticeQuestion[]>([])
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
const examForm = reactive({
  subject: '',
  level: '',
  single_choice: 10,
  judgement: 5,
  programming: 1,
})

function pct(v: number): string {
  return `${Math.round(v * 100)}%`
}

function fmtDate(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  return `${d.getMonth() + 1}月${d.getDate()}日 ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

async function load() {
  if (!store.me) await store.loadMe(true)
  if (!student.value) return
  loading.value = true
  try {
    const [setData, statData, attemptData] = await Promise.all([
      listBankSets(),
      getLearningStats(student.value.id).catch(() => null),
      listPracticeAttempts(student.value.id, { limit: 10 }).catch(() => ({ items: [], total: 0 })),
    ])
    sets.value = setData.items
    stats.value = statData
    attempts.value = attemptData.items
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

async function startMarkedPractice(kind: 'favorite' | 'wrong') {
  if (aggregateLoading.value) return
  aggregateLoading.value = true
  try {
    const qs = await aggregatePractice({ mark_kind: kind })
    if (!qs.length) {
      toast.error(kind === 'wrong' ? '错题本还是空的' : '还没有收藏题目')
      return
    }
    aggregateQuestions.value = qs
    aggregateOpen.value = true
  } catch (e: unknown) {
    toast.error((e as Error).message || '读取标记题目失败')
  } finally {
    aggregateLoading.value = false
  }
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
    const payload: AggregatePracticeIn = {
      subject: aggregateForm.subject || undefined,
      level: aggregateForm.level || undefined,
      rules: {
        single_choice: aggregateForm.single_choice,
        multiple_choice: aggregateForm.multiple_choice,
        judgement: aggregateForm.judgement,
        programming: aggregateForm.programming,
      },
      exclude_ids: [],
    }
    const qs = await aggregatePractice(payload)
    aggregateQuestions.value = qs
    aggregateOpen.value = true
  } catch (e: unknown) {
    const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
    if (detail && typeof detail === 'object' && 'gaps' in detail) {
      const gaps = (detail as { gaps: Record<string, string> }).gaps
      toast.error(Object.values(gaps).join('；') || '题库库存不足')
    } else {
      toast.error((e as Error).message || '开始综合练习失败')
    }
  } finally {
    aggregateLoading.value = false
  }
}

function openExam() {
  examForm.subject = filterSubject.value || subjects.value[0] || ''
  examForm.level = filterLevel.value || levels.value[0] || ''
  examOpen.value = true
}

async function startExam() {
  if (!student.value || starting.value) return
  starting.value = true
  try {
    const rules: Record<string, number> = {
      single_choice: Number(examForm.single_choice) || 0,
      judgement: Number(examForm.judgement) || 0,
      programming: Number(examForm.programming) || 0,
    }
    const attempt = await startPracticeAttempt({
      student_id: student.value.id,
      mode: 'exam',
      rules,
      subject: examForm.subject || undefined,
      level: examForm.level || undefined,
    })
    examOpen.value = false
    router.push({ name: 'client-practice', params: { id: attempt.id } })
  } catch (e: unknown) {
    const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
    if (detail && typeof detail === 'object' && 'gaps' in detail) {
      const gaps = (detail as { gaps: Record<string, string> }).gaps
      toast.error(Object.values(gaps).join('；') || '题库库存不足')
    } else {
      toast.error((e as Error).message || '开始模考失败')
    }
  } finally {
    starting.value = false
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

    <section v-if="attempts.length" class="history-section">
      <div class="section-head"><h2>最近练习</h2></div>
      <div class="history-list">
        <button v-for="a in attempts" :key="a.id" class="history-row" @click="openAttempt(a)">
          <span class="h-mode">{{ a.mode === 'exam' ? '模拟考试' : '套卷练习' }}</span>
          <span class="h-date">{{ fmtDate(a.started_at) }}</span>
          <span class="h-score" :class="{ done: a.status === 'evaluated' }">
            {{ a.status === 'evaluated' ? `${a.score ?? 0}/${a.total_score ?? 0}` : '进行中' }}
          </span>
        </button>
      </div>
    </section>

    <div v-if="examOpen" class="modal-mask" @click.self="examOpen = false">
      <div class="exam-modal">
        <h3>开始模拟考试</h3>
        <p class="modal-sub">按题型数量从已发布题库随机抽题。交卷后统一公布分数、答案与解析。</p>
        <div class="exam-grid">
          <label>科目<input v-model="examForm.subject" placeholder="留空不限" /></label>
          <label>等级<input v-model="examForm.level" placeholder="留空不限" /></label>
          <label>单选题<input v-model.number="examForm.single_choice" type="number" min="0" /></label>
          <label>判断题<input v-model.number="examForm.judgement" type="number" min="0" /></label>
          <label>编程题<input v-model.number="examForm.programming" type="number" min="0" /></label>
        </div>
        <div class="modal-actions">
          <button class="btn" @click="examOpen = false">取消</button>
          <button class="btn primary" :disabled="starting" @click="startExam">开始考试</button>
        </div>
      </div>
    </div>
    <TeacherPracticeDialog
      v-if="aggregateOpen"
      :questions="aggregateQuestions"
      title="综合练习"
      eyebrow="客户端综合练习"
      :meta="`${aggregateForm.subject || '不限科目'} · ${aggregateForm.level || '不限等级'}`"
      @close="aggregateOpen = false"
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
.sets-section,
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

