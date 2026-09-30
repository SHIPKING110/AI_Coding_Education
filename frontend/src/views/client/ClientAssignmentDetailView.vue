<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import ConfirmDialog from '@/components/ConfirmDialog.vue'
import {
  getClientAssignment,
  saveClientAnswers,
  submitClientAssignment,
  type ClientAssignmentDetail,
  type ClientQuestionOut,
  type ClientSubmissionOut,
} from '@/api/client'
import { useClientStore } from '@/stores/client'

const store = useClientStore()
const route = useRoute()
const router = useRouter()

const assignmentId = String(route.params.id)
const routeStudentId = computed(() => (typeof route.query.student_id === 'string' ? route.query.student_id : ''))

const assignment = ref<ClientAssignmentDetail | null>(null)
const loading = ref(true)
const loadError = ref('')
const saving = ref(false)
const submitting = ref(false)
const saveTip = ref('')

// 当前题索引（0 基）
const activeIdx = ref(0)
// 答案映射：order_no(数字) -> 答案
const answers = reactive<Record<number, unknown>>({})
// 题目是否已作答（用于题号颜色）
const answeredSet = reactive<Set<number>>(new Set())

const questions = computed<ClientQuestionOut[]>(() => assignment.value?.questions ?? [])
const activeQ = computed<ClientQuestionOut | null>(() => questions.value[activeIdx.value] ?? null)
const student = computed(() => store.activeStudent)

// 解析展开/收起（课堂作业默认收起，课后作业默认展开；切题时按模式重置）
const analysisOpen = ref(true)
function resetAnalysisOpen() {
  analysisOpen.value = assignment.value?.mode === 'classwork' ? false : true
}
watch(activeIdx, () => {
  resetAnalysisOpen()
})

const locked = computed(() => {
  // 已截止且未提交 -> 锁定作答
  const a = assignment.value
  if (!a) return false
  if (!a.deadline) return false
  if (new Date(a.deadline) < new Date()) {
    return a.submission?.status !== 'submitted' && a.submission?.status !== 'graded'
  }
  return false
})

// —— 提交流程弹窗状态 ——
const showSubmitConfirm = ref(false)
const showTipDialog = ref(false)
const tipDialog = reactive({ title: '', message: '', confirmText: '知道了', kind: 'warn' as 'warn' | 'error' })
const showSubmitResult = ref(false)
const submitResult = reactive<{
  title: string
  message: string
  passed: boolean | null
  judgedCount: number
  pendingManual: number
  score: number | null
  total: number | null
}>({
  title: '',
  message: '',
  passed: null,
  judgedCount: 0,
  pendingManual: 0,
  score: null,
  total: null,
})

const resultHeadline = computed(() => {
  if (submitResult.passed === true) return '提交成功，达标！'
  if (submitResult.passed === false) return '提交成功，未达标'
  return '提交成功'
})

const submitted = computed(() => {
  const st = assignment.value?.submission?.status
  return st === 'submitted' || st === 'graded'
})

const allAnswered = computed(() => {
  if (questions.value.length === 0) return false
  return questions.value.every((q) => {
    const v = answers[q.order_no]
    if (v === undefined || v === null) return false
    if (typeof v === 'string' && !v.trim()) return false
    if (Array.isArray(v) && v.length === 0) return false
    return true
  })
})

/** 客观题数量（提交后立即自动判分） */
const objectiveCount = computed(
  () => questions.value.filter((q) => q.type !== 'programming').length,
)
/** 编程题数量（提交后由老师人工批改） */
const manualCount = computed(
  () => questions.value.filter((q) => q.type === 'programming').length,
)

// ---------- 题号状态 ----------
function isAnswered(orderNo: number): boolean {
  return answeredSet.has(orderNo)
}

function isWrong(orderNo: number): boolean {
  const r = judgeResult(orderNo)
  return submitted.value && r?.correct === false
}

function isCurrent(orderNo: number): boolean {
  return activeQ.value?.order_no === orderNo
}

// ---------- 答案读写 ----------
function currentAnswer() {
  if (!activeQ.value) return undefined
  return answers[activeQ.value.order_no]
}

function onAnswerChange() {
  if (!activeQ.value) return
  const no = activeQ.value.order_no
  const v = answers[no]
  const filled =
    v !== undefined && v !== null && !(typeof v === 'string' && !v.trim()) && !(Array.isArray(v) && v.length === 0)
  if (filled) answeredSet.add(no)
  else answeredSet.delete(no)
}

// ---------- 导航 ----------
function goPrev() {
  if (activeIdx.value > 0) activeIdx.value--
}
function goNext() {
  if (activeIdx.value < questions.value.length - 1) activeIdx.value++
}
function goTo(idx: number) {
  activeIdx.value = idx
}

// ---------- 保存 / 提交 ----------
function buildAnswersPayload(): Record<string, unknown> {
  const payload: Record<string, unknown> = {}
  for (const q of questions.value) {
    const v = answers[q.order_no]
    if (v !== undefined) payload[String(q.order_no)] = v
  }
  return payload
}

async function save(manual = false) {
  if (!student.value || locked.value) return
  saving.value = true
  try {
    const payload = buildAnswersPayload()
    await saveClientAnswers(assignmentId, student.value.id, payload)
    saveTip.value = manual ? '已手动保存' : '已自动保存'
    if (manual) {
      setTimeout(() => (saveTip.value = ''), 2000)
    }
  } catch (e: any) {
    if (e?.response?.status === 400) {
      saveTip.value = e.response.data.detail || '保存失败（可能已截止）'
    } else {
      saveTip.value = '保存失败，请重试'
    }
    setTimeout(() => (saveTip.value = ''), 2500)
  } finally {
    saving.value = false
  }
}

function collectEmptyQuestions(): number[] {
  const empty: number[] = []
  for (const q of questions.value) {
    const v = answers[q.order_no]
    if (
      v === undefined ||
      v === null ||
      (typeof v === 'string' && !v.trim()) ||
      (Array.isArray(v) && v.length === 0)
    ) {
      empty.push(q.order_no)
    }
  }
  return empty
}

async function onSaveClick() {
  await save(true)
}

async function onSubmit() {
  if (!student.value) return
  const empty = collectEmptyQuestions()
  if (empty.length > 0) {
    // 空题校验：跳转到数值最小的题号（FR-CL-15）
    const minNo = Math.min(...empty)
    const idx = questions.value.findIndex((q) => q.order_no === minNo)
    if (idx >= 0) goTo(idx)
    tipDialog.title = '还有题目未作答'
    tipDialog.message = `还有 ${empty.length} 道题未作答（第 ${empty.join('、')} 题），请先把这些题补完再提交。`
    tipDialog.confirmText = '继续作答'
    tipDialog.kind = 'warn'
    showTipDialog.value = true
    return
  }
  showSubmitConfirm.value = true
}

async function doSubmit() {
  if (!student.value) return
  showSubmitConfirm.value = false
  submitting.value = true
  try {
    const payload = buildAnswersPayload()
    const result = await submitClientAssignment(assignmentId, student.value.id, payload)
    if (result.empty_questions.length > 0) {
      const idx = questions.value.findIndex(
        (q) => q.order_no === Math.min(...result.empty_questions),
      )
      if (idx >= 0) goTo(idx)
      tipDialog.title = '还有题目未完成'
      tipDialog.message = `还有 ${result.empty_questions.length} 道题未完成，请先作答。`
      tipDialog.confirmText = '继续作答'
      tipDialog.kind = 'warn'
      showTipDialog.value = true
      return
    }
    // 提交成功：刷新详情获取判题结果
    await loadDetail()
    const passed = result.submission.passed
    submitResult.title = '提交成功'
    submitResult.message =
      passed === true
        ? `${result.message || '作业已提交'}，本次达标。`
        : passed === false
          ? `${result.message || '作业已提交'}，本次未达标，再看看讲解继续加油。`
          : result.message || '作业已提交'
    submitResult.passed = passed
    submitResult.judgedCount = result.judged_count
    submitResult.pendingManual = result.pending_manual
    submitResult.score = result.submission.score
    submitResult.total = result.submission.total
    showSubmitResult.value = true
  } catch (e: any) {
    tipDialog.title = '提交失败'
    tipDialog.message = e?.response?.data?.detail || '提交失败，请重试'
    tipDialog.confirmText = '知道了'
    tipDialog.kind = 'error'
    showTipDialog.value = true
  } finally {
    submitting.value = false
  }
}

// ---------- 判题结果展示 ----------
function judgeResult(orderNo: number) {
  const results = assignment.value?.submission?.judge_results
  if (!results) return null
  return (results as Record<string, any>)[String(orderNo)] ?? null
}

/** 把被转义成 \n 字面量的换行还原为真实换行，避免代码挤成一行 */
function unescapeCode(text: string): string {
  return text.replace(/\\n/g, '\n').replace(/\\t/g, '\t')
}

/** 参考答案转可读文本（兼容旧数据：judge_results.expected 可能是下标/数组；新数据后端已转好文字） */
function expectedText(q: ClientQuestionOut): string {
  const jr = judgeResult(q.order_no)
  const raw = jr?.expected
  if (raw === undefined || raw === null || raw === '') return '（老师未提供参考答案）'
  const s = String(raw)
  // 旧格式：单选/多选存的是数字下标或下标数组
  if (q.type === 'single_choice' && /^[0-7]$/.test(s) && q.options) {
    return q.options[Number(s)] ?? s
  }
  if (q.type === 'multiple_choice' && /^\[[\d,\s]*\]$/.test(s) && q.options) {
    try {
      const idxs = JSON.parse(s) as number[]
      return idxs.map((i) => q.options?.[i] ?? String(i)).join('、')
    } catch {
      return s
    }
  }
  return q.type === 'code_fill' || q.type === 'programming' ? unescapeCode(s) : s
}

/** 我的答案转可读文本 */
function formatAnswerForJudge(orderNo: number, type: string): string {
  const jr = judgeResult(orderNo)
  // 新格式 actual 已是文字；旧格式回退到本地答案映射
  if (jr && typeof jr.actual === 'string' && jr.actual) {
    const s = jr.actual
    return type === 'code_fill' || type === 'programming' ? unescapeCode(s) : s
  }
  const v = answers[orderNo]
  const q = questions.value.find((x) => x.order_no === orderNo)
  if (q && q.type === 'single_choice' && typeof v === 'number') {
    return q.options?.[v] ?? String(v)
  }
  if (q && q.type === 'multiple_choice' && Array.isArray(v)) {
    return v.map((i) => q.options?.[Number(i)] ?? String(i)).join('、')
  }
  if (typeof v === 'boolean') return v ? '√ 正确' : '× 错误'
  return String(v ?? '')
}

// ---------- 初始化 ----------
function syncRouteStudent() {
  if (routeStudentId.value && routeStudentId.value !== store.activeStudentId) {
    store.setActiveStudent(routeStudentId.value)
  }
}

async function loadDetail() {
  if (!store.me) await store.loadMe(true)
  syncRouteStudent()
  if (!student.value) {
    loadError.value = '未选择学员'
    loading.value = false
    return
  }
  loading.value = true
  loadError.value = ''
  try {
    assignment.value = await getClientAssignment(assignmentId, student.value.id)
    // 回填已有进度（断点续做）
    const sub = assignment.value.submission
    if (sub?.answers) {
      for (const [k, v] of Object.entries(sub.answers)) {
        const no = Number(k)
        answers[no] = v
        if (v !== undefined && v !== null && !(typeof v === 'string' && !v.trim()) && !(Array.isArray(v) && v.length === 0)) {
          answeredSet.add(no)
        }
      }
    }
    // 若已提交/批改，激活第一题供查看
    activeIdx.value = 0
    // 课堂作业答案默认收起，课后作业默认展开
    resetAnalysisOpen()
  } catch {
    loadError.value = '加载作业失败'
  } finally {
    loading.value = false
  }
}

// 自动保存节流：每 8 秒如果有未保存变更就保存
let saveTimer: number | null = null
function scheduleAutoSave() {
  if (saveTimer !== null) window.clearTimeout(saveTimer)
  saveTimer = window.setTimeout(() => {
    if (!locked.value && !submitted.value) save(false)
  }, 8000)
}

onMounted(async () => {
  await loadDetail()
  // 监听答案变更的节流自动保存：在 onAnswerChange 中统一 scheduleAutoSave
})

onBeforeUnmount(() => {
  if (saveTimer !== null) window.clearTimeout(saveTimer)
})

// 切换学员时重新加载
watch(
  () => route.query.student_id,
  async () => {
    await loadDetail()
  },
)

function formatDate(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

const typeLabels: Record<string, string> = {
  single_choice: '单选题',
  multiple_choice: '多选题',
  judgement: '判断题',
  code_fill: '代码填空',
  programming: '编程题',
}

// 多选 toggle
function toggleMulti(oi: number) {
  if (!activeQ.value) return
  const no = activeQ.value.order_no
  const arr: number[] = Array.isArray(answers[no]) ? [...(answers[no] as number[])] : []
  const i = arr.indexOf(oi)
  if (i >= 0) arr.splice(i, 1)
  else arr.push(oi)
  answers[no] = arr
  onAnswerChange()
  scheduleAutoSave()
}
</script>

<template>
  <div>
    <!-- 返回 -->
    <button class="back-btn" @click="router.push({ name: 'client-assignments' })">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m15 18-6-6 6-6" /></svg>
      返回作业列表
    </button>

    <p v-if="loadError" class="error-banner">{{ loadError }}</p>

    <div v-if="loading" class="loading-tip">加载中…</div>

    <template v-else-if="assignment">
      <!-- 作业头 -->
      <header class="assignment-head">
        <div>
          <h1>{{ assignment.title }}</h1>
          <p v-if="assignment.description" class="desc">{{ assignment.description }}</p>
          <div class="meta">
            <span class="mode-pill" :class="assignment.mode === 'classwork' ? 'classwork' : 'homework'">
              {{ assignment.mode === 'classwork' ? '课堂作业' : '课后作业' }}
            </span>
            <span>{{ questions.length }} 题</span>
            <span v-if="assignment.class_names.length">· {{ assignment.class_names.join('、') }}</span>
            <span v-if="assignment.teacher_name">· {{ assignment.teacher_name }} 老师</span>
            <span v-if="assignment.deadline">· {{ formatDate(assignment.deadline) }} 截止</span>
          </div>
        </div>
        <div class="head-status">
          <span v-if="locked" class="locked-tag">已截止，不可作答</span>
          <span v-else-if="submitted && assignment.submission?.passed === true" class="passed-tag">已提交 · 达标 {{ assignment.submission?.score }}/{{ assignment.submission?.total }}</span>
          <span v-else-if="submitted && assignment.submission?.passed === false" class="failed-tag">已提交 · 未达标 {{ assignment.submission?.score }}/{{ assignment.submission?.total }}</span>
          <span v-else-if="submitted" class="submitted-tag">已提交{{ assignment.submission?.status === 'graded' ? ` · 得分 ${assignment.submission?.score}/${assignment.submission?.total}` : ' · 待批改' }}</span>
          <span v-else class="doing-tag">作答中</span>
        </div>
      </header>

      <!-- 题号导航 -->
      <div class="nav-strip">
        <button
          v-for="(q, i) in questions"
          :key="q.order_no"
          class="q-nav"
          :class="{ answered: isAnswered(q.order_no), wrong: isWrong(q.order_no), current: isCurrent(q.order_no) }"
          @click="goTo(i)"
        >
          {{ q.order_no }}
        </button>
      </div>

      <div class="save-row">
        <span class="save-tip">{{ saveTip }}</span>
        <span class="save-hint">答案将自动保存 · {{ allAnswered ? '全部完成，可提交' : `还剩 ${questions.filter((q) => !isAnswered(q.order_no)).length} 题未完成` }}</span>
        <button v-if="!locked && !submitted" class="save-btn" :disabled="saving" @click="onSaveClick">
          {{ saving ? '保存中…' : '手动保存' }}
        </button>
      </div>

      <!-- 当前题目 -->
      <section v-if="activeQ" class="question-card">
        <div class="q-head">
          <span class="q-type">{{ typeLabels[activeQ.type] || activeQ.type }}</span>
          <span class="q-diff" :title="`难度 ${activeQ.difficulty}/10`">{{ '★'.repeat(Math.min(activeQ.difficulty, 5)) }}</span>
        </div>

        <p class="q-stem">{{ activeQ.stem }}</p>

        <!-- 单选题 -->
        <div v-if="activeQ.type === 'single_choice' && activeQ.options" class="options">
          <button
            v-for="(opt, oi) in activeQ.options"
            :key="oi"
            class="option"
            :class="{ selected: answers[activeQ.order_no] === oi }"
            :disabled="locked || submitted"
            @click="answers[activeQ.order_no] = oi; onAnswerChange(); scheduleAutoSave()"
          >
            <span class="opt-letter">{{ 'ABCDEFGH'[oi] }}</span>
            <span>{{ opt }}</span>
          </button>
        </div>

        <!-- 多选题 -->
        <div v-if="activeQ.type === 'multiple_choice' && activeQ.options" class="options">
          <button
            v-for="(opt, oi) in activeQ.options"
            :key="oi"
            class="option"
            :class="{ selected: (answers[activeQ.order_no] as number[] | undefined)?.includes(oi) }"
            :disabled="locked || submitted"
            @click="toggleMulti(oi)"
          >
            <span class="opt-letter">{{ 'ABCDEFGH'[oi] }}</span>
            <span>{{ opt }}</span>
          </button>
        </div>

        <!-- 判断题 -->
        <div v-if="activeQ.type === 'judgement'" class="options">
          <button
            class="option"
            :class="{ selected: answers[activeQ.order_no] === true }"
            :disabled="locked || submitted"
            @click="answers[activeQ.order_no] = true; onAnswerChange(); scheduleAutoSave()"
          >
            <span class="opt-letter">√</span>
            <span>正确</span>
          </button>
          <button
            class="option"
            :class="{ selected: answers[activeQ.order_no] === false }"
            :disabled="locked || submitted"
            @click="answers[activeQ.order_no] = false; onAnswerChange(); scheduleAutoSave()"
          >
            <span class="opt-letter">×</span>
            <span>错误</span>
          </button>
        </div>

        <!-- 代码填空 / 编程题 -->
        <div v-if="activeQ.type === 'code_fill' || activeQ.type === 'programming'" class="code-area">
          <div v-if="activeQ.type === 'programming'" class="code-hint">
            {{ activeQ.language === 'cpp' ? 'C++' : 'Python' }} 编程题 · 提交后由教师批改
          </div>
          <textarea
            :value="String(answers[activeQ.order_no] ?? '')"
            class="code-input"
            :class="{ mono: activeQ.type === 'programming' }"
            :rows="activeQ.type === 'programming' ? 10 : 3"
            :disabled="locked || submitted"
            :placeholder="activeQ.type === 'programming' ? '# 在这里编写代码…' : '请输入代码…'"
            spellcheck="false"
            @input="answers[activeQ.order_no] = ($event.target as HTMLTextAreaElement).value; onAnswerChange(); scheduleAutoSave()"
          />
        </div>

        <!-- 判题结果（提交后展示） -->
        <div v-if="submitted && judgeResult(activeQ.order_no)" class="judge-box" :class="judgeResult(activeQ.order_no).correct ? 'correct' : judgeResult(activeQ.order_no).correct === false ? 'wrong' : 'manual'">
          <div class="judge-head">
            <span v-if="judgeResult(activeQ.order_no).correct === true">✓ 回答正确</span>
            <span v-else-if="judgeResult(activeQ.order_no).correct === false">✗ 回答错误</span>
            <span v-else>⏳ 待教师批改</span>
            <span class="judge-score">
              得分 {{ judgeResult(activeQ.order_no).score ?? '—' }} / {{ judgeResult(activeQ.order_no).max_score ?? 1 }}
            </span>
          </div>

          <!-- 参考答案（所有题型都展示） -->
          <div class="judge-expected">
            <span class="label">参考答案：</span>
            <pre class="answer-pre">{{ activeQ.reference_answer ?? expectedText(activeQ) }}</pre>
          </div>

          <!-- 我的答案（答错时对比展示） -->
          <div v-if="judgeResult(activeQ.order_no).correct === false" class="judge-actual">
            <span class="label">我的答案：</span>
            <span>{{ formatAnswerForJudge(activeQ.order_no, activeQ.type) }}</span>
          </div>

          <!-- 通俗解析：默认展开，可收起（面对少儿，语言通俗易懂） -->
          <div v-if="activeQ.reference_analysis" class="analysis-box">
            <button class="analysis-toggle" @click="analysisOpen = !analysisOpen">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="chev" :class="{ open: analysisOpen }"><path d="m6 9 6 6 6-6" /></svg>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" class="bulb"><path d="M9 18h6M10 22h4M12 2a7 7 0 0 0-4 12.7c.6.5 1 1.4 1 2.3h6c0-.9.4-1.8 1-2.3A7 7 0 0 0 12 2z" /></svg>
              <span>讲解给你听</span>
              <small>{{ analysisOpen ? '收起' : '展开' }}</small>
            </button>
            <p v-show="analysisOpen" class="analysis-text">{{ activeQ.reference_analysis }}</p>
          </div>
        </div>
      </section>

      <!-- 底部操作 -->
      <div class="bottom-ops">
        <button class="nav-op" :disabled="activeIdx === 0" @click="goPrev">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m15 18-6-6 6-6" /></svg>
          上一题
        </button>
        <button
          v-if="activeIdx < questions.length - 1"
          class="nav-op next"
          @click="goNext"
        >
          下一题
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m9 18 6-6-6-6" /></svg>
        </button>
        <button
          v-else-if="!locked && !submitted"
          class="nav-op submit"
          :disabled="submitting"
          @click="onSubmit"
        >
          {{ submitting ? '提交中…' : '提交作业' }}
        </button>
      </div>
    </template>

    <!-- 提交前确认 -->
    <Teleport to="body">
      <Transition name="submit-fade">
        <div v-if="showSubmitConfirm" class="submit-overlay" @click.self="showSubmitConfirm = false">
          <div class="submit-modal" role="dialog" aria-modal="true">
            <div class="submit-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 2 11 13M22 2l-7 20-4-9-9-4 20-7z" /></svg>
            </div>
            <h3>确认提交作业？</h3>
            <p class="submit-desc">
              已完成 <strong>{{ answeredSet.size }}</strong> / {{ questions.length }} 题
              <template v-if="objectiveCount > 0">，其中 {{ objectiveCount }} 道客观题提交后立即出分</template>
              <template v-if="manualCount > 0">，{{ manualCount }} 道编程题由老师批改</template>
            </p>
            <p class="submit-warn">提交后将无法修改答案，请确认无误</p>
            <div class="submit-actions">
              <button class="s-btn" @click="showSubmitConfirm = false">再检查一下</button>
              <button class="s-btn brand" :disabled="submitting" @click="doSubmit">
                {{ submitting ? '提交中…' : '确认提交' }}
              </button>
            </div>
          </div>
        </div>
      </Transition>

      <!-- 提交结果 -->
      <Transition name="submit-fade">
        <div v-if="showSubmitResult" class="submit-overlay" @click.self="showSubmitResult = false">
          <div class="submit-modal" role="dialog" aria-modal="true">
            <div class="result-badge" :class="submitResult.passed === false ? 'fail' : 'pass'">
              <svg v-if="submitResult.passed !== false" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5" /></svg>
              <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M12 9v4M12 17h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" /></svg>
            </div>
            <h3>{{ resultHeadline }}</h3>
            <p class="submit-desc">{{ submitResult.message }}</p>
            <div class="result-stats">
              <div v-if="submitResult.judgedCount > 0" class="r-stat">
                <strong>{{ submitResult.judgedCount }}</strong>
                <span>题自动判分</span>
              </div>
              <div v-if="submitResult.pendingManual > 0" class="r-stat amber">
                <strong>{{ submitResult.pendingManual }}</strong>
                <span>题待老师批改</span>
              </div>
              <div v-if="submitResult.score != null && submitResult.total" class="r-stat" :class="submitResult.passed === false ? 'amber' : 'green'">
                <strong>{{ submitResult.score }}/{{ submitResult.total }}</strong>
                <span>当前得分</span>
              </div>
            </div>
            <div class="submit-actions">
              <button class="s-btn brand" @click="showSubmitResult = false">查看判题结果</button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- 通用提示（空题/失败） -->
    <ConfirmDialog
      :visible="showTipDialog"
      :title="tipDialog.title"
      :message="tipDialog.message"
      :confirm-text="tipDialog.confirmText"
      :danger="tipDialog.kind === 'error'"
      @confirm="showTipDialog = false"
      @cancel="showTipDialog = false"
    />
  </div>
</template>

<style scoped>
.back-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: none;
  border: none;
  color: var(--ink-3);
  font-size: 13px;
  cursor: pointer;
  padding: 6px 8px;
  border-radius: 8px;
  margin-bottom: 10px;
  transition: all 0.15s;
}
.back-btn:hover {
  color: var(--brand-strong);
  background: var(--brand-soft);
}
.back-btn svg {
  width: 16px;
  height: 16px;
}

.error-banner {
  background: var(--danger-soft);
  color: var(--danger);
  padding: 10px 14px;
  border-radius: 10px;
  margin-bottom: 14px;
  font-size: 13px;
}

.loading-tip {
  text-align: center;
  color: var(--ink-3);
  font-size: 13px;
  padding: 20px 0;
}

.assignment-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 16px;
  padding: 18px 20px;
  margin-bottom: 14px;
}

.assignment-head h1 {
  font-size: 19px;
}

.desc {
  font-size: 13px;
  color: var(--ink-2);
  margin-top: 4px;
}

.meta {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  font-size: 12px;
  color: var(--ink-3);
  margin-top: 8px;
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

.head-status {
  flex-shrink: 0;
}

.locked-tag {
  font-size: 12px;
  font-weight: 600;
  padding: 5px 12px;
  border-radius: 999px;
  background: var(--danger-soft);
  color: var(--danger);
}

.submitted-tag {
  font-size: 12px;
  font-weight: 600;
  padding: 5px 12px;
  border-radius: 999px;
  background: var(--success-soft);
  color: var(--success);
}

.passed-tag {
  font-size: 12px;
  font-weight: 600;
  padding: 5px 12px;
  border-radius: 999px;
  background: var(--success-soft);
  color: var(--success);
}

.failed-tag {
  font-size: 12px;
  font-weight: 600;
  padding: 5px 12px;
  border-radius: 999px;
  background: var(--danger-soft);
  color: var(--danger);
}

.doing-tag {
  font-size: 12px;
  font-weight: 600;
  padding: 5px 12px;
  border-radius: 999px;
  background: var(--brand-soft);
  color: var(--brand-strong);
}

.nav-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}

.q-nav {
  width: 38px;
  height: 38px;
  border-radius: 10px;
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--ink-2);
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}

.q-nav.answered {
  background: var(--success-soft);
  border-color: #a7f3d0;
  color: var(--success);
}

/* 答错的题号标红（提交/批改后） */
.q-nav.wrong {
  background: var(--danger-soft);
  border-color: #fecaca;
  color: var(--danger);
}

.q-nav.current {
  background: linear-gradient(135deg, #6366f1, #06b6d4);
  color: #fff;
  border-color: transparent;
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);
}

.save-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}

.save-tip {
  font-size: 12px;
  color: var(--success);
  min-width: 0;
}

.save-hint {
  flex: 1;
  font-size: 12px;
  color: var(--ink-3);
  text-align: right;
}

.save-btn {
  padding: 6px 14px;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--ink-2);
  font-size: 12.5px;
  cursor: pointer;
  transition: all 0.15s;
}

.save-btn:hover {
  border-color: var(--brand);
  color: var(--brand-strong);
}

.question-card {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 16px;
  padding: 20px;
  margin-bottom: 14px;
}

.q-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.q-type {
  font-size: 12px;
  font-weight: 600;
  padding: 4px 12px;
  border-radius: 999px;
  background: var(--brand-soft);
  color: var(--brand-strong);
}

.q-diff {
  color: #f59e0b;
  font-size: 13px;
}

.q-stem {
  font-size: 16px;
  font-weight: 600;
  line-height: 1.6;
  margin-bottom: 18px;
  white-space: pre-wrap;
}

.options {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.option {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  border-radius: 12px;
  border: 1.5px solid var(--line);
  background: var(--surface);
  color: var(--ink-2);
  font-size: 14px;
  text-align: left;
  cursor: pointer;
  transition: all 0.15s;
}

.option:hover:not(:disabled) {
  border-color: #c7d2fe;
}

.option.selected {
  border-color: var(--brand);
  background: var(--brand-soft);
  color: var(--brand-strong);
  font-weight: 600;
}

.option:disabled {
  cursor: not-allowed;
  opacity: 0.85;
}

.opt-letter {
  width: 26px;
  height: 26px;
  flex-shrink: 0;
  border-radius: 50%;
  background: var(--bg);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 700;
  color: var(--ink-3);
  border: 1px solid var(--line);
}

.option.selected .opt-letter {
  background: var(--brand);
  color: #fff;
  border-color: var(--brand);
}

.code-area {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.code-hint {
  font-size: 12px;
  color: var(--ink-3);
}

.code-input {
  width: 100%;
  padding: 12px 14px;
  border: 1.5px solid var(--line);
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.6;
  resize: vertical;
  background: #0f172a;
  color: #e2e8f0;
  font-family: 'Cascadia Code', 'JetBrains Mono', Consolas, monospace;
  transition: border-color 0.15s;
}

.code-input.mono {
  font-family: 'Cascadia Code', 'JetBrains Mono', Consolas, monospace;
}

.code-input:focus {
  outline: none;
  border-color: var(--brand);
}

.judge-box {
  margin-top: 16px;
  padding: 12px 14px;
  border-radius: 12px;
  font-size: 13px;
}

.judge-box.correct {
  background: var(--success-soft);
  color: #047857;
}

.judge-box.wrong {
  background: var(--danger-soft);
  color: #b91c1c;
}

.judge-box.manual {
  background: var(--warning-soft);
  color: #b45309;
}

.judge-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: 600;
  margin-bottom: 6px;
}

.judge-score {
  font-size: 12px;
}

.judge-expected,
.judge-actual {
  font-size: 12.5px;
  margin-top: 4px;
}

/* 参考答案/我的答案代码块式展示（多行代码不再挤成一行） */
.answer-pre {
  display: block;
  white-space: pre-wrap;
  word-break: break-word;
  margin: 6px 0 0;
  padding: 10px 12px;
  border-radius: 10px;
  background: rgba(15, 23, 42, 0.92);
  color: #e2e8f0;
  font-family: 'Cascadia Code', 'JetBrains Mono', Consolas, monospace;
  font-size: 12.5px;
  line-height: 1.7;
}

/* 通俗解析（默认展开可收起） */
.analysis-box {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed rgba(0, 0, 0, 0.12);
}

.analysis-toggle {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  background: none;
  border: none;
  padding: 2px 4px;
  font-size: 12.5px;
  font-weight: 700;
  color: inherit;
  cursor: pointer;
  border-radius: 6px;
}

.analysis-toggle:hover {
  background: rgba(0, 0, 0, 0.05);
}

.analysis-toggle .chev {
  width: 14px;
  height: 14px;
  transition: transform 0.2s;
}

.analysis-toggle .chev.open {
  transform: rotate(180deg);
}

.analysis-toggle .bulb {
  width: 15px;
  height: 15px;
  flex-shrink: 0;
}

.analysis-toggle small {
  font-weight: 500;
  opacity: 0.75;
}

.analysis-text {
  margin: 8px 0 0;
  font-size: 13px;
  line-height: 1.8;
  white-space: pre-wrap;
}

.label {
  font-weight: 600;
  margin-right: 4px;
}

.bottom-ops {
  display: flex;
  gap: 10px;
  margin-top: 14px;
}

.nav-op {
  flex: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 11px 0;
  border-radius: 12px;
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--ink-2);
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}

.nav-op svg {
  width: 16px;
  height: 16px;
}

.nav-op:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.nav-op.next,
.nav-op.submit {
  background: linear-gradient(135deg, #6366f1, #06b6d4);
  color: #fff;
  border-color: transparent;
}

.nav-op.submit {
  background: linear-gradient(135deg, #10b981, #059669);
}

/* —— 提交确认 / 结果弹窗 —— */
.submit-overlay {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.55);
  backdrop-filter: blur(3px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
  padding: 20px;
}

.submit-modal {
  width: 380px;
  max-width: 100%;
  background: var(--surface);
  border-radius: 20px;
  padding: 28px 24px 22px;
  box-shadow: 0 24px 60px rgba(15, 23, 42, 0.25);
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.submit-icon,
.result-badge {
  width: 56px;
  height: 56px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 14px;
}

.submit-icon {
  background: var(--brand-soft);
  color: var(--brand-strong);
}

.result-badge.pass {
  background: var(--success-soft);
  color: var(--success);
  animation: pop-in 0.35s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.result-badge.fail {
  background: var(--warning-soft);
  color: #b45309;
  animation: pop-in 0.35s cubic-bezier(0.34, 1.56, 0.64, 1);
}

@keyframes pop-in {
  0% {
    transform: scale(0.5);
    opacity: 0;
  }
  100% {
    transform: scale(1);
    opacity: 1;
  }
}

.submit-icon svg,
.result-badge svg {
  width: 26px;
  height: 26px;
}

.submit-modal h3 {
  font-size: 17px;
  font-weight: 700;
  color: var(--ink);
  margin-bottom: 8px;
}

.submit-desc {
  font-size: 13.5px;
  color: var(--ink-2);
  line-height: 1.7;
  margin-bottom: 6px;
}

.submit-desc strong {
  color: var(--brand-strong);
  font-size: 15px;
}

.submit-warn {
  font-size: 12.5px;
  color: #b45309;
  background: var(--warning-soft);
  border-radius: 8px;
  padding: 6px 12px;
  margin-bottom: 4px;
}

.result-stats {
  display: flex;
  gap: 8px;
  justify-content: center;
  flex-wrap: wrap;
  margin: 10px 0 6px;
}

.r-stat {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  min-width: 92px;
  padding: 10px 12px;
  border-radius: 12px;
  background: var(--brand-soft);
  color: var(--brand-strong);
}

.r-stat strong {
  font-size: 18px;
  font-weight: 800;
}

.r-stat span {
  font-size: 11px;
  opacity: 0.85;
}

.r-stat.amber {
  background: var(--warning-soft);
  color: #b45309;
}

.r-stat.green {
  background: var(--success-soft);
  color: var(--success);
}

.submit-actions {
  display: flex;
  gap: 10px;
  justify-content: center;
  margin-top: 14px;
  width: 100%;
}

.s-btn {
  flex: 1;
  padding: 10px 0;
  border-radius: 12px;
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--ink-2);
  font-size: 13.5px;
  font-weight: 600;
  font-family: inherit;
  cursor: pointer;
  transition: all 0.15s;
}

.s-btn:hover {
  border-color: var(--brand);
  color: var(--brand-strong);
}

.s-btn.brand {
  background: linear-gradient(135deg, #10b981, #059669);
  border-color: transparent;
  color: #fff;
}

.s-btn.brand:hover {
  filter: brightness(1.05);
  color: #fff;
}

.s-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.submit-fade-enter-active,
.submit-fade-leave-active {
  transition: opacity 0.2s ease;
}

.submit-fade-enter-active .submit-modal,
.submit-fade-leave-active .submit-modal {
  transition: transform 0.2s ease;
}

.submit-fade-enter-from,
.submit-fade-leave-to {
  opacity: 0;
}

.submit-fade-enter-from .submit-modal,
.submit-fade-leave-to .submit-modal {
  transform: scale(0.94) translateY(8px);
}
</style>
