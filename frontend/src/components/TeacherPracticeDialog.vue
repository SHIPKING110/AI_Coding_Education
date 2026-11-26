<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import ExamResultPanel from '@/components/ExamResultPanel.vue'
import { QUESTION_TYPE_LABELS } from '@/api/assignment'
import {
  checkAggregateAnswer,
  closePracticeAttempt,
  saveAttemptAnswer,
  selfEvaluateQuestion,
  startPracticeAttempt,
  submitPracticeAttempt,
  toggleAggregateMark,
  type AttemptKind,
  type BankSet,
  type PracticeAttemptOut,
  type PracticeQuestion,
} from '@/api/questionBank'

const props = defineProps<{
  bankSet?: BankSet
  questions?: PracticeQuestion[]
  startIndex?: number
  title?: string
  eyebrow?: string
  meta?: string
  mode?: 'practice' | 'exam'
  attempt?: PracticeAttemptOut | null
  session?: {
    kind: AttemptKind
    set_id?: string
    rules?: Record<string, number>
    subject?: string
    level?: string
    institution?: string
    exam_year?: number
    mark_kind?: 'favorite' | 'wrong'
    student_id?: string
    exam_minutes?: number
  } | null
}>()
const emit = defineEmits<{
  (e: 'close'): void
  (e: 'retry'): void
}>()

type Feedback = {
  is_correct: boolean | null
  correct_answer?: unknown
  analysis?: string | null
  reference_code?: string | null
}

const loading = ref(false)
const loadError = ref('')
const saving = ref(false)
const submitting = ref(false)
const showResult = ref(false)
const sessionAttempt = ref<PracticeAttemptOut | null>(props.attempt ?? null)
const index = ref(props.startIndex ?? 0)
const picked = ref<Record<string, unknown>>({})
const feedbackMap = ref<Record<string, Feedback>>({})
const selfEvalMap = ref<Record<string, boolean>>({})
const wrongSet = ref<Set<string>>(new Set())
const favoriteSet = ref<Set<string>>(new Set())
const remainingSeconds = ref<number | null>(null)
let examTimer: ReturnType<typeof setInterval> | undefined
const examExpired = ref(false)
const examClock = computed(() => {
  if (remainingSeconds.value == null) return ''
  const mm = Math.floor(remainingSeconds.value / 60).toString().padStart(2, '0')
  const ss = (remainingSeconds.value % 60).toString().padStart(2, '0')
  return `${mm}:${ss}`
})

const questionList = computed<PracticeQuestion[]>(() => {
  if (sessionAttempt.value) return sessionAttempt.value.questions.map((q) => ({ ...q }))
  if (props.questions?.length) return props.questions
  return props.bankSet?.questions ?? []
})
const question = computed<PracticeQuestion | null>(() => questionList.value[index.value] ?? null)
const isExam = computed(() => sessionAttempt.value?.mode === 'exam' || props.mode === 'exam')
const isEvaluated = computed(() => sessionAttempt.value?.status === 'evaluated')
const feedback = computed<Feedback | null>(() => (question.value ? feedbackMap.value[question.value.id] ?? null : null))
const answeredCount = computed(() => questionList.value.filter(hasAnswer).length)
const unansweredCount = computed(() => questionList.value.filter((q) => !hasAnswer(q)).length)
const title = computed(() => props.title ?? sessionAttempt.value?.paper_title ?? props.bankSet?.name ?? (isExam.value ? '考试模拟' : '综合练习'))
const eyebrow = computed(() => props.eyebrow ?? (isExam.value ? '考试模拟 · 交卷后统一评分' : '教师试做 · 自动保存做题记录'))
const metaLine = computed(() => {
  if (props.meta) return props.meta
  const b = props.bankSet
  if (!b) return ''
  return [b.institution, b.subject, b.level, b.exam_year ? `${b.exam_year} 年` : ''].filter(Boolean).join(' · ')
})

function clampIndex(value: number): number {
  return Math.min(Math.max(value, 0), Math.max(0, questionList.value.length - 1))
}

function hasAnswer(q: PracticeQuestion): boolean {
  const value = picked.value[q.id]
  if (Array.isArray(value)) return value.length > 0
  return value !== undefined && value !== null && value !== ''
}

function textValue(q: PracticeQuestion): string {
  const value = picked.value[q.id]
  return typeof value === 'string' ? value : ''
}

function setText(q: PracticeQuestion, value: string) {
  picked.value[q.id] = value
  if (isExam.value) void persistExamAnswer(q)
}

function optionSelected(q: PracticeQuestion, optionIndex: number): boolean {
  const value = picked.value[q.id]
  if (q.type === 'multiple_choice') return Array.isArray(value) && value.includes(optionIndex)
  return value === optionIndex
}

function toggleOption(q: PracticeQuestion, optionIndex: number) {
  if (q.type === 'multiple_choice') {
    const current = Array.isArray(picked.value[q.id]) ? [...(picked.value[q.id] as number[])] : []
    const pos = current.indexOf(optionIndex)
    if (pos >= 0) current.splice(pos, 1)
    else current.push(optionIndex)
    picked.value[q.id] = current.sort((a, b) => a - b)
  } else {
    picked.value[q.id] = optionIndex
  }
  if (isExam.value) void persistExamAnswer(q)
  else void judgeCurrent()
}

function judge(q: PracticeQuestion, value: boolean) {
  picked.value[q.id] = value
  if (isExam.value) void persistExamAnswer(q)
  else void judgeCurrent()
}

function hydrateFromAttempt() {
  const attempt = sessionAttempt.value
  if (!attempt) return
  const nextPicked: Record<string, unknown> = {}
  const nextFeedback: Record<string, Feedback> = {}
  const nextSelf: Record<string, boolean> = {}
  const wrong = new Set<string>()
  const favorite = new Set<string>()
  for (const q of attempt.questions) {
    if (attempt.answers?.[q.id] !== undefined) nextPicked[q.id] = attempt.answers[q.id]
    if (attempt.answers?.[`__self__:${q.id}`] !== undefined) nextSelf[q.id] = Boolean(attempt.answers[`__self__:${q.id}`])
    const resultItem = attempt.result?.items.find((item) => item.id === q.id)
    const resultState = attempt.question_results?.[q.id]
    if (resultItem) {
      nextFeedback[q.id] = {
        is_correct: resultItem.is_correct,
        correct_answer: resultItem.correct_answer,
        analysis: resultItem.analysis,
        reference_code: resultItem.reference_code,
      }
      if (resultItem.is_correct === false) wrong.add(q.id)
    } else if (resultState) {
      nextFeedback[q.id] = {
        is_correct: resultState.is_correct ?? null,
        correct_answer: q.answer,
        analysis: q.analysis,
        reference_code: q.reference_code,
      }
      if (resultState.is_correct === false) wrong.add(q.id)
    }
    if (q.favorite) favorite.add(q.id)
  }
  picked.value = nextPicked
  feedbackMap.value = nextFeedback
  selfEvalMap.value = nextSelf
  wrongSet.value = wrong
  favoriteSet.value = favorite
  if (attempt.status === 'evaluated') showResult.value = true
}

async function ensureSession() {
  if (sessionAttempt.value || !props.session) {
    hydrateFromAttempt()
    return
  }
  loading.value = true
  loadError.value = ''
  try {
    sessionAttempt.value = await startPracticeAttempt({
      ...props.session,
      mode: props.mode ?? (props.session.kind.startsWith('exam') ? 'exam' : 'practice'),
    })
    hydrateFromAttempt()
  } catch (e: unknown) {
    const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
    loadError.value = typeof detail === 'string' ? detail : (e as Error).message || '创建练习失败'
  } finally {
    loading.value = false
  }
}

function applyLocalResult(q: PracticeQuestion, res: {
  is_correct?: boolean | null
  correct_answer?: unknown
  analysis?: string | null
  reference_code?: string | null
}) {
  feedbackMap.value[q.id] = {
    is_correct: res.is_correct ?? null,
    correct_answer: res.correct_answer,
    analysis: res.analysis,
    reference_code: res.reference_code,
  }
  if (res.is_correct === false) wrongSet.value.add(q.id)
  else if (res.is_correct === true) wrongSet.value.delete(q.id)
}

async function judgeCurrent() {
  const q = question.value
  if (!q || isExam.value) return
  if (!hasAnswer(q)) return
  const value = picked.value[q.id]
  saving.value = true
  try {
    if (sessionAttempt.value) {
      const res = await saveAttemptAnswer(sessionAttempt.value.id, q.id, value)
      applyLocalResult(q, res)
      if (!sessionAttempt.value.answers) sessionAttempt.value.answers = {}
      sessionAttempt.value.answers[q.id] = value
      if (!sessionAttempt.value.question_results) sessionAttempt.value.question_results = {}
      sessionAttempt.value.question_results[q.id] = {
        is_correct: res.is_correct ?? null,
        score: res.score,
        max_score: res.max_score,
      }
    } else {
      const res = await checkAggregateAnswer(q.id, value)
      applyLocalResult(q, res)
      if (res.is_correct === false) await toggleAggregateMark(q.id, 'wrong', true).catch(() => null)
      else if (res.is_correct === true) await toggleAggregateMark(q.id, 'wrong', false).catch(() => null)
    }
  } catch {
    /* 保留当前作答，用户可重试 */
  } finally {
    saving.value = false
  }
}

async function persistExamAnswer(q: PracticeQuestion) {
  const attempt = sessionAttempt.value
  if (!attempt || attempt.status !== 'in_progress') return
  try {
    await saveAttemptAnswer(attempt.id, q.id, picked.value[q.id])
    if (!attempt.answers) attempt.answers = {}
    attempt.answers[q.id] = picked.value[q.id]
  } catch {
    /* 自动保存失败时允许交卷前重试 */
  }
}

async function markSelf(correct: boolean) {
  const q = question.value
  if (!q) return
  if (sessionAttempt.value) {
    try {
      await selfEvaluateQuestion(sessionAttempt.value.id, q.id, correct)
      if (!sessionAttempt.value.answers) sessionAttempt.value.answers = {}
      sessionAttempt.value.answers[`__self__:${q.id}`] = correct
      if (isExam.value) {
        selfEvalMap.value[q.id] = correct
        return
      }
      feedbackMap.value[q.id] = {
        is_correct: correct,
        correct_answer: q.answer,
        analysis: q.analysis,
        reference_code: q.reference_code,
      }
      if (correct) wrongSet.value.delete(q.id)
      else wrongSet.value.add(q.id)
    } catch {
      /* 自评失败保留当前状态 */
    }
    return
  }
  if (correct) {
    wrongSet.value.delete(q.id)
    await toggleAggregateMark(q.id, 'wrong', false).catch(() => null)
    feedbackMap.value[q.id] = { is_correct: true, correct_answer: q.answer, analysis: q.analysis, reference_code: q.reference_code }
  } else {
    wrongSet.value.add(q.id)
    await toggleAggregateMark(q.id, 'wrong', true).catch(() => null)
    feedbackMap.value[q.id] = { is_correct: false, correct_answer: q.answer, analysis: q.analysis, reference_code: q.reference_code }
  }
}

async function toggleFavorite() {
  const q = question.value
  if (!q) return
  const enabled = !favoriteSet.value.has(q.id)
  try {
    await toggleAggregateMark(q.id, 'favorite', enabled)
    if (enabled) favoriteSet.value.add(q.id)
    else favoriteSet.value.delete(q.id)
  } catch {
    /* 收藏失败不改变本地状态 */
  }
}

async function clearFeedback() {
  const q = question.value
  if (!q) return
  if (sessionAttempt.value?.mode === 'practice' && sessionAttempt.value.status === 'in_progress') {
    try {
      await saveAttemptAnswer(sessionAttempt.value.id, q.id, null)
    } catch {
      return
    }
  }
  delete feedbackMap.value[q.id]
  delete picked.value[q.id]
  if (sessionAttempt.value?.answers) delete sessionAttempt.value.answers[q.id]
  if (sessionAttempt.value?.question_results) delete sessionAttempt.value.question_results[q.id]
  wrongSet.value.delete(q.id)
}

async function submitExam(auto = false) {
  const attempt = sessionAttempt.value
  if (!attempt || submitting.value) return
  if (!auto && unansweredCount.value > 0) {
    const ok = window.confirm(`还有 ${unansweredCount.value} 题未作答，确定交卷吗？`)
    if (!ok) return
  }
  submitting.value = true
  stopExamCountdown()
  if (auto) window.alert('考试时间已到，系统已自动交卷。')
  try {
    sessionAttempt.value = await submitPracticeAttempt(attempt.id)
    hydrateFromAttempt()
    showResult.value = true
  } catch {
    /* 交卷失败允许重试 */
  } finally {
    submitting.value = false
  }
}

function go(step: number) {
  index.value = clampIndex(index.value + step)
}

function stopExamCountdown() {
  if (examTimer) {
    clearInterval(examTimer)
    examTimer = undefined
  }
}

function startExamCountdown() {
  const attempt = sessionAttempt.value
  if (!attempt || attempt.mode !== 'exam' || attempt.status !== 'in_progress') return
  const meta = (attempt.paper_meta ?? {}) as { exam_minutes?: number }
  const minutes = Math.min(300, Math.max(5, Number(meta.exam_minutes ?? 120)))
  const deadline = new Date(attempt.started_at).getTime() + minutes * 60_000
  const tick = () => {
    const left = Math.round((deadline - Date.now()) / 1000)
    remainingSeconds.value = Math.max(0, left)
    if (left <= 0) {
      stopExamCountdown()
      if (!examExpired.value) {
        examExpired.value = true
        void submitExam(true)
      }
    }
  }
  stopExamCountdown()
  tick()
  if (remainingSeconds.value && remainingSeconds.value > 0) {
    examTimer = setInterval(tick, 1000)
  }
}

function selectQuestion(target: number) {
  index.value = clampIndex(target)
}

async function requestClose() {
  const attempt = sessionAttempt.value
  if (attempt && attempt.mode === 'practice' && attempt.status === 'in_progress') {
    try {
      await closePracticeAttempt(attempt.id)
    } catch {
      /* 关闭失败不阻塞退出 */
    }
  }
  emit('close')
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') void requestClose()
}

watch(
  () => props.startIndex,
  (value) => {
    if (value !== undefined) index.value = clampIndex(value)
  },
)
watch(questionList, () => {
  index.value = clampIndex(index.value)
})

onMounted(async () => {
  window.addEventListener('keydown', onKeydown)
  await ensureSession()
  startExamCountdown()
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  stopExamCountdown()
})

function mediaFor(q: PracticeQuestion, scope: string) {
  return (q.media ?? []).filter((item) => item.scope === scope).map((item) => item.url)
}

function answerText(value: unknown): string {
  if (Array.isArray(value)) {
    return value.length ? value.map((item) => (typeof item === 'number' ? String.fromCharCode(65 + item) : String(item))).join('、') : '未作答'
  }
  if (typeof value === 'number') return String.fromCharCode(65 + value)
  if (typeof value === 'boolean') return value ? '正确' : '错误'
  if (value === null || value === undefined || value === '') return '未作答'
  return String(value)
}

function referenceAnswer(q: PracticeQuestion): string {
  if (q.type === 'programming' || q.type === 'code_fill') {
    if (q.reference_code) return q.reference_code
    return typeof q.answer === 'string' ? q.answer : ''
  }
  return answerText(q.answer)
}
</script>

<template>
  <Teleport to="body">
    <div class="practice-overlay" @click.self="requestClose">
      <section class="practice-modal" role="dialog" aria-modal="true" aria-labelledby="teacher-practice-title">
        <header class="practice-head">
          <div class="head-copy">
            <span class="eyebrow">{{ eyebrow }}</span>
            <h2 id="teacher-practice-title">{{ title }}</h2>
            <p v-if="metaLine" class="meta">{{ metaLine }}</p>
          </div>
          <div class="head-side">
            <span v-if="isExam && !isEvaluated && remainingSeconds !== null" class="exam-clock" :class="{ urgent: remainingSeconds <= 300 }">剩余 {{ examClock }}</span>
            <span v-if="isExam && !isEvaluated" class="exam-hint">交卷后统一公布分数与解析</span>
            <button v-if="isExam && !isEvaluated" type="button" class="btn primary" :disabled="submitting" @click="submitExam()">
              {{ submitting ? '交卷中…' : '交卷' }}
            </button>
            <button type="button" class="close-btn" aria-label="关闭" @click="requestClose">×</button>
          </div>
        </header>

        <div v-if="loading" class="state">加载题目…</div>
        <div v-else-if="loadError" class="state error">{{ loadError }}</div>
        <ExamResultPanel
          v-else-if="showResult && sessionAttempt"
          :attempt="sessionAttempt"
          :title="title"
          @close="requestClose"
          @retry="emit('retry')"
        />
        <template v-else>
          <div class="practice-toolbar">
            <span class="toolbar-label">答题卡</span>
            <nav class="answer-card" aria-label="答题卡">
              <button
                v-for="(q, idx) in questionList"
                :key="q.id"
                type="button"
                class="answer-no"
                :class="{ active: idx === index, answered: hasAnswer(q), wrong: wrongSet.has(q.id) }"
                :aria-current="idx === index ? 'true' : undefined"
                @click="selectQuestion(idx)"
              >
                {{ idx + 1 }}
              </button>
            </nav>
            <span class="progress">已答 {{ answeredCount }} / {{ questionList.length }}</span>
            <div class="quick-nav">
              <button type="button" class="mini-btn" :disabled="index === 0" @click="go(-1)">‹</button>
              <button type="button" class="mini-btn" :disabled="index >= questionList.length - 1" @click="go(1)">›</button>
            </div>
          </div>

          <div class="practice-body">
            <div v-if="!question" class="state">这套题库暂无可试做的题目</div>
            <article v-else class="question-sheet">
              <div class="q-head">
                <span class="q-no">第 {{ index + 1 }} 题</span>
                <span class="q-type">{{ QUESTION_TYPE_LABELS[question.type] }}</span>
                <span class="q-score">{{ question.score }} 分</span>
                <button
                  type="button"
                  class="favorite-btn"
                  :class="{ active: favoriteSet.has(question.id) }"
                  :title="favoriteSet.has(question.id) ? '取消收藏' : '收藏本题'"
                  @click="toggleFavorite"
                >
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M12 3.6l2.63 5.33 5.88.86-4.25 4.14 1 5.86L12 17.02l-5.26 2.77 1-5.86L3.49 9.79l5.88-.86z" />
                  </svg>
                  <span>{{ favoriteSet.has(question.id) ? '已收藏' : '收藏' }}</span>
                </button>
              </div>

              <pre class="stem">{{ question.stem }}</pre>

              <div v-if="mediaFor(question, 'stem').length" class="media-row">
                <img v-for="url in mediaFor(question, 'stem')" :key="url" :src="url" alt="" />
              </div>

              <div v-if="['single_choice', 'multiple_choice'].includes(question.type)" class="options">
                <button
                  v-for="(option, optIdx) in question.options ?? []"
                  :key="optIdx"
                  type="button"
                  class="option"
                  :class="{ selected: optionSelected(question, optIdx) }"
                  @click="toggleOption(question, optIdx)"
                >
                  <span class="opt-mark">{{ String.fromCharCode(65 + optIdx) }}</span>
                  <span class="opt-text">{{ option || '（图片选项）' }}</span>
                  <img
                    v-for="url in mediaFor(question, `option:${String.fromCharCode(65 + optIdx)}`)"
                    :key="url"
                    :src="url"
                    class="opt-img"
                    alt=""
                  />
                </button>
              </div>

              <div v-else-if="question.type === 'judgement'" class="judge-options">
                <button type="button" class="judge-btn" :class="{ selected: picked[question.id] === true }" @click="judge(question, true)">正确</button>
                <button type="button" class="judge-btn" :class="{ selected: picked[question.id] === false }" @click="judge(question, false)">错误</button>
              </div>

              <textarea
                v-else
                :value="textValue(question)"
                class="code-input"
                rows="7"
                :placeholder="question.type === 'programming' ? '在此编写代码' : '填写答案'"
                @input="setText(question, ($event.target as HTMLTextAreaElement).value)"
                @blur="isExam ? persistExamAnswer(question) : judgeCurrent()"
              ></textarea>

              <div v-if="isExam && question.type === 'programming' && !isEvaluated" class="exam-self">
                <span>参考程序请自行对照后自评（未自评按 0 分）：</span>
                <button type="button" class="judge-btn" :class="{ selected: selfEvalMap[question.id] === true }" @click="markSelf(true)">我写对了</button>
                <button type="button" class="judge-btn" :class="{ selected: selfEvalMap[question.id] === false }" @click="markSelf(false)">还需练习</button>
              </div>

              <div v-if="feedback" class="feedback" :class="{ wrong: feedback.is_correct === false }">
                <strong>
                  {{ feedback.is_correct === null ? '参考答案' : feedback.is_correct ? '回答正确' : '回答错误' }}
                </strong>
                <p v-if="question.type !== 'programming' && question.type !== 'code_fill'" class="feedback-line">
                  正确答案：{{ answerText(feedback.correct_answer ?? question.answer) }}
                </p>
                <template v-else>
                  <p class="feedback-line">参考{{ question.type === 'programming' ? '代码' : '答案' }}：</p>
                  <pre class="ref-code">{{ referenceAnswer(question) }}</pre>
                </template>
                <p v-if="feedback.analysis || question.analysis" class="feedback-line">解析：{{ feedback.analysis || question.analysis }}</p>
                <p v-else class="feedback-line muted">暂无解析，可联系教师补充。</p>
                <div v-if="feedback.is_correct === null && question.type === 'programming'" class="self-mark">
                  <button type="button" class="btn" @click="markSelf(true)">我做对了</button>
                  <button type="button" class="btn danger" @click="markSelf(false)">标记错误</button>
                </div>
              </div>

              <footer class="q-actions">
                <button type="button" class="btn" :disabled="index === 0" @click="go(-1)">上一题</button>
                <button
                  v-if="!feedback && !isExam"
                  type="button"
                  class="btn primary"
                  :disabled="!hasAnswer(question) || saving"
                  @click="judgeCurrent"
                >
                  {{ saving ? '判定中…' : '判定答案' }}
                </button>
                <button v-if="feedback" type="button" class="btn" @click="clearFeedback">再做一次</button>
                <button
                  v-if="isExam && index === questionList.length - 1"
                  type="button"
                  class="btn primary"
                  :disabled="submitting"
                  @click="submitExam()"
                >
                  {{ submitting ? '交卷中…' : '交卷' }}
                </button>
                <button
                  v-else
                  type="button"
                  class="btn primary"
                  :disabled="index >= questionList.length - 1"
                  @click="go(1)"
                >
                  下一题
                </button>
              </footer>
            </article>
          </div>
        </template>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.practice-overlay {
  position: fixed;
  inset: 0;
  z-index: 120;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 18px;
  background: rgba(15, 23, 42, 0.6);
  backdrop-filter: blur(3px);
}
.practice-modal {
  width: min(1000px, 100%);
  max-height: calc(100vh - 36px);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid #e7dcc6;
  border-radius: 18px;
  background: #fffdf7;
  box-shadow: 0 24px 80px rgba(15, 23, 42, 0.28);
}
.practice-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 18px 22px 14px;
  border-bottom: 1px solid #f0e6d3;
  background: #fff;
}
.head-copy {
  min-width: 0;
}
.eyebrow {
  color: #0f766e;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.12em;
}
h2 {
  margin: 4px 0 3px;
  color: var(--ink);
  font-size: 19px;
  line-height: 1.35;
}
.meta {
  color: var(--ink-3);
  font-size: 12px;
}
.head-side {
  display: flex;
  align-items: center;
  gap: 10px;
}
.exam-clock {
  padding: 7px 10px;
  border: 1px solid #99f6e4;
  border-radius: 999px;
  background: #f0fdfa;
  color: #0f766e;
  font-variant-numeric: tabular-nums;
  font-weight: 700;
  white-space: nowrap;
}
.exam-clock.urgent {
  border-color: #fca5a5;
  background: #fff1f2;
  color: #be123c;
}
.exam-hint {
  color: #92400e;
  font-size: 11.5px;
}
.close-btn {
  width: 34px;
  height: 34px;
  flex-shrink: 0;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: #fff;
  color: var(--ink-3);
  font-size: 20px;
  line-height: 1;
  cursor: pointer;
}
.close-btn:hover {
  border-color: #0f766e;
  color: #0f766e;
}
.practice-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 22px;
  border-bottom: 1px solid #f0e6d3;
  background: #fff;
}
.toolbar-label {
  color: var(--ink-3);
  font-size: 12px;
  white-space: nowrap;
}
.answer-card {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  max-height: 86px;
  overflow-y: auto;
  flex: 1;
}
.answer-no {
  width: 32px;
  height: 32px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
  color: var(--ink-3);
  font-size: 12px;
  cursor: pointer;
}
.answer-no.answered {
  border-color: #0f766e;
  color: #0f766e;
  background: #ecfdf5;
}
.answer-no.wrong {
  border-color: #fca5a5;
  color: #b91c1c;
  background: #fef2f2;
}
.answer-no.active {
  border-color: #172554;
  background: #172554;
  color: #fff;
}
.progress {
  color: var(--ink-3);
  font-size: 12px;
  white-space: nowrap;
}
.quick-nav {
  display: flex;
  gap: 4px;
}
.mini-btn {
  width: 28px;
  height: 28px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
  color: var(--ink-3);
  cursor: pointer;
}
.mini-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.practice-body {
  flex: 1;
  overflow-y: auto;
  padding: 18px 22px 22px;
}
.state {
  padding: 40px 20px;
  text-align: center;
  color: var(--ink-3);
  font-size: 13px;
}
.state.error {
  color: #b91c1c;
}
.question-sheet {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.q-head {
  display: flex;
  align-items: center;
  gap: 10px;
}
.q-no {
  font-weight: 700;
  color: var(--ink);
  font-size: 14px;
}
.q-type {
  padding: 2px 8px;
  border-radius: 999px;
  background: #eef2f7;
  color: #475569;
  font-size: 11px;
}
.q-score {
  color: var(--ink-3);
  font-size: 12px;
}
.favorite-btn {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 10px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
  color: var(--ink-3);
  font-size: 11.5px;
  cursor: pointer;
}
.favorite-btn svg {
  width: 15px;
  height: 15px;
}
.favorite-btn.active {
  border-color: #e7b75b;
  color: #a16207;
  background: #fffbeb;
}
.stem {
  margin: 0;
  padding: 14px 16px;
  border-radius: 12px;
  background: #fff;
  border: 1px solid var(--line);
  color: var(--ink);
  font-family: inherit;
  font-size: 14px;
  line-height: 1.7;
  white-space: pre-wrap;
}
.media-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}
.media-row img {
  max-width: 240px;
  border-radius: 8px;
  border: 1px solid var(--line);
}
.options {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.option {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: #fff;
  text-align: left;
  cursor: pointer;
  font-size: 13.5px;
  color: var(--ink);
}
.option.selected {
  border-color: #0f766e;
  background: #ecfdf5;
}
.opt-mark {
  width: 24px;
  height: 24px;
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: #f1f5f9;
  color: #475569;
  font-size: 11.5px;
  font-weight: 700;
}
.option.selected .opt-mark {
  background: #0f766e;
  color: #fff;
}
.opt-text {
  flex: 1;
}
.opt-img {
  max-height: 70px;
  border-radius: 6px;
}
.judge-options {
  display: flex;
  gap: 10px;
}
.judge-btn {
  padding: 9px 26px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: #fff;
  cursor: pointer;
  font-size: 13px;
}
.judge-btn.selected {
  border-color: #0f766e;
  background: #ecfdf5;
  color: #0f766e;
  font-weight: 700;
}
.code-input {
  width: 100%;
  padding: 12px 14px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: #fff;
  font-family: ui-monospace, Consolas, monospace;
  font-size: 12.5px;
  resize: vertical;
}
.feedback {
  padding: 12px 14px;
  border-radius: 10px;
  border: 1px solid #bbf7d0;
  background: #f0fdf4;
  color: #166534;
  font-size: 13px;
}
.feedback.wrong {
  border-color: #fecaca;
  background: #fef2f2;
  color: #991b1b;
}
.feedback-line {
  margin-top: 6px;
  line-height: 1.65;
  white-space: pre-wrap;
}
.feedback-line.muted {
  color: var(--ink-3);
}
.ref-code {
  margin-top: 8px;
  padding: 10px 12px;
  border-radius: 8px;
  background: #0f172a;
  color: #e2e8f0;
  font-size: 12px;
  overflow: auto;
}
.self-mark {
  display: flex;
  gap: 8px;
  margin-top: 10px;
}
.exam-self {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  padding: 10px 12px;
  border: 1px dashed #e7dcc6;
  border-radius: 10px;
  background: #fffbeb;
  color: #92400e;
  font-size: 12px;
}
.q-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 6px;
}
</style>
