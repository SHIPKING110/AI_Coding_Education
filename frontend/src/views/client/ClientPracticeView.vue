<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import {
  getPracticeAttempt,
  saveAttemptAnswer,
  selfEvaluateQuestion,
  submitPracticeAttempt,
  type AttemptQuestion,
  type PracticeAttemptOut,
} from '@/api/questionBank'
import { useToastStore } from '@/stores/toast'

const route = useRoute()
const router = useRouter()
const toast = useToastStore()
const attempt = ref<PracticeAttemptOut | null>(null)
const loading = ref(true)
const submitting = ref(false)
const current = ref(0)
const answer = ref<unknown>(null)
const practiceFeedback = ref<{
  is_correct?: boolean | null
  correct_answer?: unknown
  analysis?: string | null
  reference_code?: string | null
} | null>(null)
const selfCorrect = ref<boolean | null>(null)

const questions = computed(() => attempt.value?.questions ?? [])
const question = computed<AttemptQuestion | null>(() => questions.value[current.value] ?? null)
const isDone = computed(() => attempt.value?.status === 'evaluated')
const isExam = computed(() => attempt.value?.mode === 'exam')
const remainingSeconds = ref<number | null>(null)
let examTimer: ReturnType<typeof setInterval> | undefined
const examClock = computed(() => {
  if (remainingSeconds.value == null) return ''
  const mm = Math.floor(remainingSeconds.value / 60).toString().padStart(2, '0')
  const ss = (remainingSeconds.value % 60).toString().padStart(2, '0')
  return `${mm}:${ss}`
})
const examExpired = ref(false)
const result = computed(() => attempt.value?.result)
const normalizedScore = computed(() => result.value?.normalized_score ?? (result.value?.total_score ? Math.round(((result.value.score ?? 0) / result.value.total_score) * 100) : 0))
const paperKindLabel = computed(() => {
  const kind = attempt.value?.kind ?? ''
  const map: Record<string, string> = {
    quick: '刷题练习',
    aggregate: '综合练习',
    marked: '错题/收藏',
    exam_set: '套卷考试',
    exam_random: '随机考试',
    set_practice: '套卷练习',
  }
  return map[kind] ?? (isExam.value ? '模拟考试' : '套卷练习')
})
const typeLabels: Record<string, string> = {
  single_choice: '单选题',
  multiple_choice: '多选题',
  judgement: '判断题',
  programming: '编程题',
  code_fill: '代码填空',
}

function answerText(value: unknown): string {
  if (Array.isArray(value)) return value.join(',')
  if (typeof value === 'boolean') return value ? '正确' : '错误'
  return value === null || value === undefined ? '' : String(value)
}

function setAnswer(value: unknown) {
  answer.value = value
}

function syncAnswer() {
  const q = question.value
  if (!q) return
  answer.value = attempt.value?.answers?.[q.id] ?? (q.type === 'multiple_choice' ? [] : null)
  const item = result.value?.items.find((i) => i.id === q.id)
  selfCorrect.value = attempt.value?.answers?.[`__self__:${q.id}`] === undefined
    ? item?.is_correct ?? null
    : Boolean(attempt.value.answers[`__self__:${q.id}`])
  if (item) {
    practiceFeedback.value = {
      is_correct: item.is_correct,
      correct_answer: item.correct_answer,
      analysis: item.analysis,
      reference_code: item.reference_code,
    }
    return
  }
  const persisted = attempt.value?.question_results?.[q.id]
  if (!isExam.value && persisted) {
    practiceFeedback.value = {
      is_correct: persisted.is_correct ?? null,
      correct_answer: q.answer,
      analysis: q.analysis,
      reference_code: q.reference_code,
    }
    return
  }
  practiceFeedback.value = null
}

async function load() {
  loading.value = true
  try {
    attempt.value = await getPracticeAttempt(String(route.params.id))
    syncAnswer()
  } catch {
    toast.error('练习记录不存在')
    router.back()
  } finally {
    loading.value = false
  }
}

async function save() {
  const a = attempt.value
  const q = question.value
  if (!a || !q || a.status !== 'in_progress') return
  try {
    const res = await saveAttemptAnswer(a.id, q.id, answer.value)
    practiceFeedback.value = {
      is_correct: res.is_correct ?? null,
      correct_answer: res.correct_answer,
      analysis: res.analysis,
      reference_code: res.reference_code,
    }
    a.answers[q.id] = answer.value
    if (!a.question_results) a.question_results = {}
    a.question_results[q.id] = { is_correct: res.is_correct ?? null, score: res.score, max_score: res.max_score }
  } catch {
    toast.error('保存答案失败')
  }
}

async function selfEval(value: boolean) {
  const a = attempt.value
  const q = question.value
  if (!a || !q) return
  try {
    await selfEvaluateQuestion(a.id, q.id, value)
    selfCorrect.value = value
    if (!a.answers) a.answers = {}
    a.answers[`__self__:${q.id}`] = value
    if (!a.question_results) a.question_results = {}
    a.question_results[q.id] = { is_correct: value, score: value ? q.score : 0, max_score: q.score }
  } catch {
    toast.error('保存自评失败')
  }
}

async function next() {
  if (!isDone.value) await save()
  if (current.value < questions.value.length - 1) {
    current.value += 1
    syncAnswer()
  }
}

function previous() {
  if (current.value > 0) {
    current.value -= 1
    syncAnswer()
  }
}

async function submit() {
  const a = attempt.value
  if (!a || submitting.value) return
  submitting.value = true
  try {
    attempt.value = await submitPracticeAttempt(a.id)
    current.value = 0
    syncAnswer()
  } catch {
    toast.error('交卷失败')
  } finally {
    submitting.value = false
  }
}

function leave() {
  router.push({ name: 'client-question-bank' })
}

function stopExamCountdown() {
  if (examTimer) {
    clearInterval(examTimer)
    examTimer = undefined
  }
}

async function autoSubmit() {
  if (submitting.value || isDone.value) return
  toast.error('考试时间已到，系统已自动交卷')
  try {
    await save()
  } catch {
    /* 忽略单题保存失败，交卷仍会带上已保存的答案 */
  }
  await submit()
}

function startExamCountdown() {
  const a = attempt.value
  if (!a || !isExam.value || a.status !== 'in_progress') return
  const meta = (a.paper_meta ?? {}) as { exam_minutes?: number }
  const minutes = Math.min(300, Math.max(5, Number(meta.exam_minutes ?? 120)))
  const started = new Date(a.started_at).getTime()
  const deadline = started + minutes * 60_000
  const tick = () => {
    const left = Math.round((deadline - Date.now()) / 1000)
    remainingSeconds.value = Math.max(0, left)
    if (left <= 0) {
      stopExamCountdown()
      if (!examExpired.value) {
        examExpired.value = true
        void autoSubmit()
      }
    }
  }
  stopExamCountdown()
  tick()
  if (remainingSeconds.value && remainingSeconds.value > 0) {
    examTimer = setInterval(tick, 1000)
  }
}

function choiceSelected(index: number): boolean {
  if (question.value?.type === 'multiple_choice') return Array.isArray(answer.value) && answer.value.includes(index)
  return answer.value === index
}

function toggleChoice(index: number) {
  if (question.value?.type === 'multiple_choice') {
    const currentValue = Array.isArray(answer.value) ? [...answer.value] : []
    const pos = currentValue.indexOf(index)
    if (pos >= 0) currentValue.splice(pos, 1)
    else currentValue.push(index)
    answer.value = currentValue.sort()
  } else {
    answer.value = index
  }
}

onMounted(async () => {
  await load()
  startExamCountdown()
})
onBeforeUnmount(stopExamCountdown)
</script>

<template>
  <div class="practice-page">
    <div v-if="loading" class="loading">加载练习…</div>
    <template v-else-if="attempt">
      <header class="practice-head">
        <button class="back-btn" @click="leave">← 题库</button>
        <div class="head-main">
          <h1>{{ attempt.paper_title || paperKindLabel }}</h1>
          <span class="progress">{{ current + 1 }} / {{ questions.length }}</span>
        </div>
        <div v-if="isExam && !isDone && remainingSeconds !== null" class="exam-clock" :class="{ urgent: remainingSeconds <= 300 }">
          剩余 {{ examClock }}
        </div>
        <div v-if="isDone && result" class="score-pill">
          {{ isExam ? `${normalizedScore} 分 · ${result.rating ?? ''}` : `${result.score} / ${result.total_score} 分` }}
        </div>
      </header>

      <div v-if="isDone && result" class="result-summary">
        <div class="score-card big">
          <strong>{{ normalizedScore }}</strong>
          <span>{{ isExam ? '满分 100' : '得分率' }}</span>
        </div>
        <div class="score-card">
          <strong>{{ result.correct_count }}/{{ result.question_count }}</strong>
          <span>答对题数</span>
        </div>
        <div v-if="isExam && result.rating" class="score-card">
          <strong :class="result.rating === '达标' ? 'pass-text' : 'fail-text'">{{ result.rating }}</strong>
          <span>评级</span>
        </div>
        <div v-for="(st, type) in result.type_stats" :key="type" class="score-card">
          <strong>{{ Math.round((st.correct_rate ?? (st.total ? st.correct / st.total : 0)) * 100) }}%</strong>
          <span>{{ typeLabels[type] ?? type }}</span>
        </div>
        <button class="btn primary" @click="leave">返回题库</button>
      </div>

      <div class="practice-layout">
        <nav class="q-nav" aria-label="题号">
          <button
            v-for="(q, idx) in questions"
            :key="q.id"
            class="q-dot"
            :class="{ active: idx === current, answered: attempt.answers?.[q.id] !== undefined }"
            @click="current = idx; syncAnswer()"
          >
            {{ idx + 1 }}
          </button>
        </nav>

        <main v-if="question" class="question-card">
          <div class="q-head">
            <span class="q-no">第 {{ current + 1 }} 题</span>
            <span class="q-type">{{ question.type === 'single_choice' ? '单选题' : question.type === 'multiple_choice' ? '多选题' : question.type === 'judgement' ? '判断题' : question.type === 'programming' ? '编程题' : '代码填空' }}</span>
            <span class="q-score">{{ question.score }} 分</span>
          </div>
          <pre class="stem">{{ question.stem }}</pre>

          <div v-if="question.media?.length" class="media-list">
            <img v-for="m in question.media" :key="m.url" :src="m.url" alt="" />
          </div>

          <div v-if="['single_choice', 'multiple_choice'].includes(question.type)" class="options">
            <button
              v-for="(opt, idx) in question.options ?? []"
              :key="idx"
              class="option-item"
              :class="{ selected: choiceSelected(idx), right: practiceFeedback?.is_correct && practiceFeedback?.correct_answer === idx, wrong: practiceFeedback?.is_correct === false && choiceSelected(idx) }"
              @click="toggleChoice(idx)"
            >
              <span class="opt-mark">{{ String.fromCharCode(65 + idx) }}</span>
              <span class="opt-text">{{ opt || '（图片选项）' }}</span>
              <img
                v-for="m in (question.media ?? []).filter((x) => x.scope === `option:${String.fromCharCode(65 + idx)}`)"
                :key="m.url"
                :src="m.url"
                class="opt-img"
                alt=""
              />
            </button>
          </div>

          <div v-else-if="question.type === 'judgement'" class="judge-options">
            <button class="judge-btn" :class="{ selected: answer === true }" @click="setAnswer(true)">正确</button>
            <button class="judge-btn" :class="{ selected: answer === false }" @click="setAnswer(false)">错误</button>
          </div>

          <textarea
            v-else
            :value="typeof answer === 'string' ? answer : ''"
            class="code-input"
            rows="8"
            :placeholder="question.type === 'programming' ? '在此编写代码' : '填写答案'"
            @input="setAnswer(($event.target as HTMLTextAreaElement).value)"
          ></textarea>

          <div v-if="practiceFeedback" class="feedback" :class="practiceFeedback.is_correct === false ? 'wrong' : 'right'">
            <strong>
              {{ practiceFeedback.is_correct === null ? '已保存' : practiceFeedback.is_correct ? '回答正确' : '回答错误' }}
            </strong>
            <p v-if="practiceFeedback.correct_answer !== undefined && practiceFeedback.correct_answer !== null" class="feedback-line">
              正确答案：{{ answerText(practiceFeedback.correct_answer) }}
            </p>
            <pre v-if="practiceFeedback.reference_code" class="ref-code">{{ practiceFeedback.reference_code }}</pre>
            <p v-if="practiceFeedback.analysis" class="feedback-line">解析：{{ practiceFeedback.analysis }}</p>
          </div>

          <div v-if="question.type === 'programming' && !isDone" class="self-eval">
            <span>参考程序对照后自评：</span>
            <button class="judge-btn" :class="{ selected: selfCorrect === true }" @click="selfEval(true)">我写对了</button>
            <button class="judge-btn" :class="{ selected: selfCorrect === false }" @click="selfEval(false)">还需要练习</button>
          </div>

          <div class="q-actions">
            <button class="btn" :disabled="current === 0" @click="previous">上一题</button>
            <button v-if="!isDone" class="btn" @click="save">保存本题</button>
            <button v-if="!isDone && current < questions.length - 1" class="btn primary" @click="next">下一题</button>
            <button v-if="!isDone && current === questions.length - 1" class="btn primary" :disabled="submitting" @click="submit">
              {{ submitting ? '交卷中…' : '交卷' }}
            </button>
            <button v-if="isDone" class="btn primary" @click="leave">完成</button>
          </div>
        </main>
      </div>

      <div v-if="isDone && result" class="review-list">
        <h2>答案解析</h2>
        <article v-for="item in result.items" :key="item.id" class="review-item">
          <div class="review-head">
            <span>第 {{ item.order_no }} 题</span>
            <span :class="item.is_correct === true ? 'ok' : item.is_correct === false ? 'bad' : 'neutral'">
              {{ item.is_correct === true ? '正确' : item.is_correct === false ? '错误' : '自评/未判' }} · {{ item.score }}/{{ item.max_score }} 分
            </span>
          </div>
          <p class="review-line">你的答案：{{ answerText(item.user_answer) || '未作答' }}</p>
          <p class="review-line">正确答案：{{ answerText(item.correct_answer) }}</p>
          <pre v-if="item.reference_code" class="ref-code">{{ item.reference_code }}</pre>
          <p v-if="item.analysis" class="review-line">解析：{{ item.analysis }}</p>
        </article>
      </div>
    </template>
  </div>
</template>

<style scoped>
.practice-page {
  max-width: 1080px;
  margin: 0 auto;
  padding: 16px 16px 100px;
}
.loading {
  padding: 60px;
  text-align: center;
  color: var(--ink-3);
  font-size: 13px;
}
.practice-head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}
.back-btn {
  padding: 6px 10px;
  border-radius: 8px;
  border: 1px solid var(--line);
  background: var(--surface);
  font-size: 12px;
  cursor: pointer;
}
.head-main {
  flex: 1;
  display: flex;
  align-items: baseline;
  gap: 10px;
}
.head-main h1 {
  font-size: 19px;
  color: var(--ink);
}
.progress {
  font-size: 12px;
  color: var(--ink-3);
  font-family: ui-monospace, Consolas, monospace;
}
.exam-clock {
  margin-left: auto;
  padding: 7px 12px;
  border: 1px solid #99f6e4;
  border-radius: 999px;
  background: #f0fdfa;
  color: #0f766e;
  font-variant-numeric: tabular-nums;
  font-weight: 700;
}
.exam-clock.urgent {
  border-color: #fca5a5;
  background: #fff1f2;
  color: #be123c;
}
.result-summary {
  display: flex;
  flex-wrap: wrap;
  align-items: stretch;
  gap: 10px;
  padding: 14px;
  margin-bottom: 14px;
  border-radius: 14px;
  background: #fffdf8;
  border: 1px solid #e7dcc6;
}
.score-card {
  min-width: 90px;
  padding: 10px 14px;
  border-radius: 10px;
  background: #fff;
  border: 1px solid #eee3ce;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.score-card.big {
  background: linear-gradient(135deg, #172554, #2f6f73);
  color: #fff;
  border: none;
}
.score-card strong {
  font-size: 20px;
  font-family: ui-monospace, Consolas, monospace;
}
.score-card span {
  font-size: 11px;
  opacity: 0.75;
}
.score-card .pass-text {
  color: #15803d;
}
.score-card .fail-text {
  color: #b91c1c;
}
.practice-layout {
  display: grid;
  grid-template-columns: 54px minmax(0, 1fr);
  gap: 12px;
}
.q-nav {
  display: grid;
  grid-template-columns: 1fr;
  gap: 5px;
  max-height: 70vh;
  overflow: auto;
}
.q-dot {
  width: 30px;
  height: 30px;
  border-radius: 8px;
  border: 1px solid var(--line);
  background: #fff;
  font-size: 11px;
  font-family: ui-monospace, Consolas, monospace;
  cursor: pointer;
}
.q-dot.answered {
  border-color: #bfdbfe;
  background: #eff6ff;
  color: #1d4ed8;
}
.q-dot.active {
  outline: 2px solid #2f6f73;
  outline-offset: 1px;
}
.question-card {
  padding: 18px;
  border-radius: 14px;
  background: #fffdf8;
  border: 1px solid #e7dcc6;
  box-shadow: var(--shadow-sm);
}
.q-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
  font-size: 12px;
}
.q-no {
  font-weight: 800;
  color: #3f2f14;
}
.q-type {
  padding: 2px 8px;
  border-radius: 6px;
  background: #f1e7d2;
  color: #7c5a1e;
  font-weight: 700;
}
.q-score {
  margin-left: auto;
  color: var(--ink-3);
}
.stem {
  margin: 0 0 14px;
  white-space: pre-wrap;
  font-family: inherit;
  font-size: 14px;
  line-height: 1.8;
  color: var(--ink);
}
.media-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}
.media-list img {
  max-width: 220px;
  max-height: 160px;
  object-fit: contain;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
}
.options {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 12px;
}
.option-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid #e2d5bb;
  border-radius: 10px;
  background: #fff;
  text-align: left;
  cursor: pointer;
  font-size: 13.5px;
}
.option-item.selected {
  border-color: #2f6f73;
  background: #f0fdfa;
}
.option-item.right {
  border-color: #22c55e;
  background: #f0fdf4;
}
.option-item.wrong {
  border-color: #ef4444;
  background: #fef2f2;
}
.opt-mark {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: #f1e7d2;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 800;
  font-size: 11.5px;
  color: #7c5a1e;
  flex-shrink: 0;
}
.opt-text {
  flex: 1;
}
.opt-img {
  width: 50px;
  height: 50px;
  object-fit: contain;
}
.judge-options {
  display: flex;
  gap: 10px;
  margin-bottom: 12px;
}
.judge-btn {
  padding: 9px 20px;
  border-radius: 9px;
  border: 1px solid #e2d5bb;
  background: #fff;
  font-size: 13px;
  cursor: pointer;
}
.judge-btn.selected {
  border-color: #2f6f73;
  background: #f0fdfa;
  color: #0f766e;
  font-weight: 700;
}
.code-input {
  width: 100%;
  padding: 12px;
  border-radius: 10px;
  border: 1px solid #1e293b;
  background: #0f172a;
  color: #e2e8f0;
  font-family: ui-monospace, Consolas, monospace;
  font-size: 13px;
  line-height: 1.7;
  resize: vertical;
}
.feedback {
  margin-top: 12px;
  padding: 11px 14px;
  border-radius: 10px;
  font-size: 12.5px;
}
.feedback.right {
  background: #f0fdf4;
  border: 1px solid #86efac;
  color: #166534;
}
.feedback.wrong {
  background: #fef2f2;
  border: 1px solid #fecaca;
  color: #b91c1c;
}
.feedback-line {
  margin: 5px 0 0;
  line-height: 1.6;
}
.ref-code {
  margin: 8px 0 0;
  padding: 10px;
  border-radius: 8px;
  background: #0f172a;
  color: #e2e8f0;
  font-family: ui-monospace, Consolas, monospace;
  font-size: 12px;
  white-space: pre-wrap;
}
.self-eval {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 12px;
  font-size: 12px;
  color: var(--ink-3);
}
.q-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 16px;
}
.review-list {
  margin-top: 20px;
}
.review-list h2 {
  font-size: 16px;
  margin-bottom: 10px;
}
.review-item {
  padding: 12px 14px;
  border-radius: 10px;
  background: #fffdf8;
  border: 1px solid #e7dcc6;
  margin-bottom: 9px;
  font-size: 12.5px;
}
.review-head {
  display: flex;
  justify-content: space-between;
  font-weight: 700;
  margin-bottom: 5px;
}
.review-head .ok {
  color: #166534;
}
.review-head .bad {
  color: #b91c1c;
}
.review-head .neutral {
  color: var(--ink-3);
}
.review-line {
  margin: 3px 0;
  color: var(--ink-2);
  line-height: 1.6;
}
@media (max-width: 640px) {
  .practice-layout {
    grid-template-columns: 1fr;
  }
  .q-nav {
    grid-template-columns: repeat(auto-fill, 32px);
    max-height: 110px;
  }
}
</style>

