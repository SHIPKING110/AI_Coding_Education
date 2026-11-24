<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { QUESTION_TYPE_LABELS } from '@/api/assignment'
import {
  checkAggregateAnswer,
  toggleAggregateMark,
  type BankSet,
  type PracticeQuestion,
} from '@/api/questionBank'

const props = defineProps<{
  bankSet?: BankSet
  questions?: PracticeQuestion[]
  startIndex?: number
  title?: string
  eyebrow?: string
  meta?: string
}>()
const emit = defineEmits<{ (e: 'close'): void }>()

const questionList = computed<PracticeQuestion[]>(() => {
  if (props.questions?.length) return props.questions
  return props.bankSet?.questions ?? []
})
watch(
  questionList,
  () => {
    favoriteSet.value = new Set(questionList.value.filter((q) => q.favorite).map((q) => q.id))
    wrongSet.value = new Set(questionList.value.filter((q) => q.wrong).map((q) => q.id))
  },
  { immediate: true, deep: true },
)
const index = ref(startPosition(props.startIndex ?? 0))
const picked = ref<Record<string, unknown>>({})
const feedback = ref<{
  is_correct: boolean | null
  correct_answer?: unknown
  analysis?: string | null
  reference_code?: string | null
} | null>(null)
const wrongSet = ref<Set<string>>(new Set())
const favoriteSet = ref<Set<string>>(new Set())

const question = computed<PracticeQuestion | null>(() => questionList.value[index.value] ?? null)
const answeredCount = computed(() => questionList.value.filter(hasAnswer).length)
const title = computed(() => props.title ?? props.bankSet?.name ?? '综合练习')
const eyebrow = computed(() => props.eyebrow ?? '教师试做 · 不计入学习数据')
const metaLine = computed(() => {
  if (props.meta) return props.meta
  const b = props.bankSet
  if (!b) return ''
  return [b.institution, b.subject, b.level, b.exam_year ? `${b.exam_year} 年` : ''].filter(Boolean).join(' · ')
})

function startPosition(value: number): number {
  const max = Math.max(0, questionList.value.length - 1)
  return Math.min(Math.max(value, 0), max)
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
}

function judge(q: PracticeQuestion, value: boolean) {
  picked.value[q.id] = value
}

async function judgeCurrent() {
  const q = question.value
  if (!q) return
  const value = picked.value[q.id]
  if (!hasAnswer(q)) return
  feedback.value = null
  if (q.type === 'programming') {
    try {
      const res = await checkAggregateAnswer(q.id, value)
      feedback.value = {
        is_correct: null,
        correct_answer: res.correct_answer,
        analysis: res.analysis,
        reference_code: res.reference_code,
      }
    } catch {
      feedback.value = { is_correct: null }
    }
    return
  }
  try {
    const res = await checkAggregateAnswer(q.id, value)
    feedback.value = {
      is_correct: res.is_correct ?? null,
      correct_answer: res.correct_answer,
      analysis: res.analysis,
      reference_code: res.reference_code,
    }
    if (res.is_correct === false) {
      wrongSet.value.add(q.id)
      await toggleAggregateMark(q.id, 'wrong', true)
    } else if (res.is_correct === true) {
      wrongSet.value.delete(q.id)
      if (index.value < questionList.value.length - 1) go(1)
    }
  } catch {
    /* 网络失败时保留当前作答，交给宿主页面提示 */
  }
}

async function markSelf(correct: boolean) {
  const q = question.value
  if (!q) return
  if (correct) {
    wrongSet.value.delete(q.id)
    await toggleAggregateMark(q.id, 'wrong', false)
    feedback.value = { is_correct: true }
    if (index.value < questionList.value.length - 1) go(1)
  } else {
    wrongSet.value.add(q.id)
    await toggleAggregateMark(q.id, 'wrong', true)
    feedback.value = { is_correct: false }
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
    /* Mark state remains unchanged when persistence fails. */
  }
}
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
  if (q.type === 'programming') {
    if (q.reference_code) return q.reference_code
    return typeof q.answer === 'string' ? q.answer : ''
  }
  if (q.type === 'code_fill') return typeof q.answer === 'string' ? q.answer : ''
  return answerText(q.answer)
}

function go(step: number) {
  index.value = startPosition(index.value + step)
  feedback.value = null
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') emit('close')
}

onMounted(() => window.addEventListener('keydown', onKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <Teleport to="body">
    <div class="practice-overlay" @click.self="emit('close')">
      <section class="practice-modal" role="dialog" aria-modal="true" aria-labelledby="teacher-practice-title">
        <header class="practice-head">
          <div class="head-copy">
            <span class="eyebrow">{{ eyebrow }}</span>
            <h2 id="teacher-practice-title">{{ title }}</h2>
            <p v-if="metaLine" class="meta">{{ metaLine }}</p>
          </div>
          <button type="button" class="close-btn" aria-label="关闭试做" @click="emit('close')">×</button>
        </header>

        <div class="practice-toolbar">
          <nav class="answer-card" aria-label="答题卡">
            <button
              v-for="(q, idx) in questionList"
              :key="q.id"
              type="button"
              class="answer-no"
              :class="{ active: idx === index, answered: hasAnswer(q), wrong: wrongSet.has(q.id) }"
              :aria-current="idx === index ? 'true' : undefined"
              :title="`第 ${idx + 1} 题 · ${QUESTION_TYPE_LABELS[q.type]}${wrongSet.has(q.id) ? ' · 错题' : ''}`"
              @click="index = idx"
            >
              {{ idx + 1 }}
            </button>
          </nav>
          <span class="progress">已答 {{ answeredCount }} / {{ questionList.length }}</span>
        </div>

        <div class="practice-body">
          <div v-if="!question" class="empty">这套题库暂无可试做的题目</div>
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
                @click="toggleOption(question, optIdx); judgeCurrent()"
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
              <button type="button" class="judge-btn" :class="{ selected: picked[question.id] === true }" @click="judge(question, true); judgeCurrent()">正确</button>
              <button type="button" class="judge-btn" :class="{ selected: picked[question.id] === false }" @click="judge(question, false); judgeCurrent()">错误</button>
            </div>

            <textarea
              v-else
              :value="textValue(question)"
              class="code-input"
              rows="7"
              :placeholder="question.type === 'programming' ? '在此编写代码' : '填写答案'"
              @input="setText(question, ($event.target as HTMLTextAreaElement).value)"
              @blur="judgeCurrent()"
            ></textarea>

            <div v-if="feedback" class="feedback" :class="{ wrong: feedback.is_correct === false }">
              <strong>
                {{ feedback.is_correct === null ? '参考答案' : feedback.is_correct ? '回答正确' : '回答错误' }}
              </strong>
              <p v-if="question.type !== 'programming' && question.type !== 'code_fill'" class="feedback-line">
                正确答案：{{ answerText(feedback.correct_answer) }}
              </p>
              <template v-else>
                <p class="feedback-line">参考{{ question.type === 'programming' ? '代码' : '答案' }}：</p>
                <pre class="ref-code">{{ referenceAnswer(question) }}</pre>
              </template>
              <p v-if="feedback.analysis" class="feedback-line">解析：{{ feedback.analysis }}</p>
              <p v-else-if="feedback.is_correct !== null" class="feedback-line muted">暂无解析，可联系教师补充。</p>
              <div v-if="feedback.is_correct === null && question.type === 'programming'" class="self-mark">
                <button type="button" class="btn" @click="markSelf(true)">我做对了</button>
                <button type="button" class="btn danger" @click="markSelf(false)">标记错误</button>
              </div>
            </div>

            <footer class="q-actions">
              <button type="button" class="btn" :disabled="index === 0" @click="go(-1)">上一题</button>
              <button
                v-if="!feedback"
                type="button"
                class="btn primary"
                :disabled="!hasAnswer(question)"
                @click="judgeCurrent"
              >
                判断答案
              </button>
              <button
                v-if="feedback && feedback.is_correct !== true"
                type="button"
                class="btn"
                @click="feedback = null"
              >
                再作答
              </button>
              <button
                type="button"
                class="btn primary"
                :disabled="!!(index >= questionList.length - 1 || (feedback && feedback.is_correct === false))"
                @click="go(1)"
              >
                下一题
              </button>
            </footer>
          </article>
        </div>
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
  width: min(980px, 100%);
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
  align-items: flex-start;
  gap: 14px;
  padding: 12px 22px;
  border-bottom: 1px solid #f0e6d3;
  background: #fffdf7;
}
.answer-card {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.answer-no {
  width: 30px;
  height: 30px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
  color: var(--ink-2);
  font-family: ui-monospace, 'SFMono-Regular', Consolas, monospace;
  font-size: 12px;
  font-weight: 700;
  line-height: 1;
  cursor: pointer;
}
.answer-no.answered {
  border-color: #99f6e4;
  background: #f0fdfa;
  color: #0f766e;
}
.answer-no.active {
  outline: 2px solid #b8860b;
  outline-offset: 1px;
}
.answer-no.wrong {
  border-color: #fecaca;
  background: #fef2f2;
  color: #b91c1c;
}
.progress {
  flex-shrink: 0;
  padding-top: 8px;
  color: var(--ink-3);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}
.practice-body {
  overflow: auto;
  padding: 18px 22px 24px;
}
.empty {
  padding: 60px 20px;
  color: var(--ink-3);
  text-align: center;
  font-size: 13px;
}
.question-sheet {
  padding: 18px;
  border: 1px solid #eadfc9;
  border-radius: 14px;
  background: #fff;
  box-shadow: var(--shadow-sm);
}
.q-head {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--ink-3);
  font-size: 12px;
}
.q-head button {
  margin-left: auto;
}
.favorite-btn {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 14px;
  border: 1px solid #fde68a;
  border-radius: 999px;
  background: #fffbeb;
  color: #b45309;
  font-size: 12.5px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.18s ease;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
}
.favorite-btn svg {
  width: 15px;
  height: 15px;
}
.favorite-btn:hover {
  border-color: #f59e0b;
  background: #fef3c7;
  transform: translateY(-1px);
  box-shadow: 0 6px 14px rgba(245, 158, 11, 0.18);
}
.favorite-btn.active {
  border-color: #fbbf24;
  background: linear-gradient(135deg, #fef3c7, #fde68a);
  color: #92400e;
  box-shadow: 0 6px 16px rgba(245, 158, 11, 0.22);
}
.favorite-btn.active svg {
  fill: #f59e0b;
}
.q-no {
  color: var(--ink);
  font-size: 14px;
  font-weight: 800;
}
.q-type,
.q-score {
  padding: 2px 8px;
  border-radius: 999px;
  background: #f5f5f4;
  color: var(--ink-2);
}
.stem {
  margin: 14px 0;
  color: var(--ink);
  font-family: inherit;
  font-size: 14px;
  line-height: 1.75;
  white-space: pre-wrap;
  word-break: break-word;
}
.media-row {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 12px;
}
.media-row img,
.opt-img {
  max-width: 100%;
  border-radius: 10px;
  border: 1px solid var(--line);
}
.options {
  display: grid;
  gap: 8px;
}
.option {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: #fffdf7;
  color: var(--ink-2);
  font: inherit;
  font-size: 13.5px;
  line-height: 1.6;
  text-align: left;
  cursor: pointer;
}
.option:hover {
  border-color: #99f6e4;
}
.option.selected {
  border-color: #0f766e;
  background: #f0fdfa;
  color: #115e59;
}
.opt-mark {
  width: 22px;
  height: 22px;
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid currentColor;
  border-radius: 50%;
  font-size: 11px;
  font-weight: 700;
}
.opt-text {
  flex: 1;
  min-width: 0;
  white-space: pre-wrap;
}
.opt-img {
  max-width: 200px;
}
.judge-options {
  display: flex;
  gap: 10px;
}
.judge-btn {
  padding: 9px 22px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: #fffdf7;
  color: var(--ink-2);
  font: inherit;
  font-size: 13.5px;
  font-weight: 600;
  cursor: pointer;
}
.judge-btn.selected {
  border-color: #0f766e;
  background: #f0fdfa;
  color: #115e59;
}
.code-input {
  width: 100%;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: #fffdf7;
  color: var(--ink);
  font-family: ui-monospace, 'SFMono-Regular', Consolas, monospace;
  font-size: 13px;
  line-height: 1.65;
  resize: vertical;
}
.feedback {
  margin-top: 14px;
  padding: 12px 14px;
  border: 1px solid #99f6e4;
  border-radius: 10px;
  background: #f0fdfa;
  color: #115e59;
  font-size: 13px;
  line-height: 1.65;
}
.feedback.wrong {
  border-color: #fecaca;
  background: #fef2f2;
  color: #991b1b;
}
.feedback-line {
  margin: 6px 0 0;
}
.ref-code {
  margin: 8px 0 0;
  padding: 10px 12px;
  border-radius: 8px;
  background: rgba(15, 23, 42, 0.06);
  color: var(--ink);
  font-family: ui-monospace, 'SFMono-Regular', Consolas, monospace;
  font-size: 12.5px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}
.q-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 16px;
}
.self-mark {
  display: flex;
  gap: 8px;
  margin-top: 8px;
}
.btn.danger {
  border: 1px solid #fecaca;
  background: #fef2f2;
  color: #b91c1c;
}
.practice-modal :focus-visible {
  outline: 2px solid #b8860b;
  outline-offset: 2px;
}
@media (max-width: 640px) {
  .practice-overlay {
    padding: 0;
  }
  .practice-modal {
    width: 100%;
    max-height: 100vh;
    min-height: 100vh;
    border: none;
    border-radius: 0;
  }
  .practice-head,
  .practice-toolbar,
  .practice-body {
    padding-left: 16px;
    padding-right: 16px;
  }
  .practice-toolbar {
    flex-direction: column;
    gap: 8px;
  }
  .answer-no {
    width: 34px;
    height: 34px;
  }
  .progress {
    padding-top: 0;
  }
}
</style>
