<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import {
  getSubmission,
  getSubmissionStats,
  gradeSubmission,
  listSubmissions,
  type SubmissionDetail,
  type SubmissionListItem,
  type SubmissionStats,
} from '@/api/client'
import { createMakeupAssignment, getAssignment } from '@/api/assignment'

const route = useRoute()
const router = useRouter()

const assignmentId = String(route.params.id)

const stats = ref<SubmissionStats | null>(null)
const submissions = ref<SubmissionListItem[]>([])
// 作业元信息（用于应作答口径说明：定向发布=定向学员数，常规=发布班级学员去重）
const assignmentMeta = ref<{ mode: string; targetCount: number; classNames: string[] } | null>(null)

/** 应作答口径说明：定向作业=定向学员数；常规班级作业=发布班级学员去重数 */
const statsScopeText = computed(() => {
  if (!assignmentMeta.value) return '定向作业按定向学员数统计，常规作业按发布班级学员去重统计'
  const m = assignmentMeta.value
  if (m.targetCount > 0) return `定向发布的 ${m.targetCount} 名学员`
  if (m.classNames.length > 0) return `发布班级（${m.classNames.join('、')}）学员去重`
  return '未发布到班级/学员'
})
const loading = ref(false)
const error = ref('')

// 批改弹窗状态
const gradingVisible = ref(false)
const grading = ref<SubmissionDetail | null>(null)
const scores = ref<Record<string, number>>({})
const comment = ref('')
const submitting = ref(false)
const msg = ref('')
// 已批改提交默认只读查看；需要改分时点「重新批改」进入编辑态
const gradeReadonly = ref(true)

/** 当前弹窗是否为只读查看态（已批改且未进入重新批改） */
const isGradeView = computed(
  () => gradeReadonly.value && grading.value?.status === 'graded',
)
/** 人工批改过的题号（judged=true 且有人工给分痕迹的题） */
const manualQs = computed(() => {
  const results = (grading.value?.judge_results ?? {}) as Record<string, any>
  return (grading.value?.questions ?? []).filter((q) => {
    const r = results[String(q.order_no)]
    return !!r && r.judged === true
  })
})
/** 已保存的批改评语（后端存在 judge_results._comment） */
const savedComment = computed(() => {
  const results = (grading.value?.judge_results ?? {}) as Record<string, any>
  const c = results._comment
  return typeof c === 'string' ? c : ''
})
/** 当前弹窗内需要人工打分的题（仅待批改态使用） */
const pendingManualQs = computed(() =>
  (grading.value?.questions ?? []).filter((q) => judgeInfo(q)?.cls === 'manual'),
)

const typeLabels: Record<string, string> = {
  single_choice: '单选题',
  multiple_choice: '多选题',
  judgement: '判断题',
  code_fill: '代码填空',
  programming: '编程题',
}

const statusMap: Record<string, { label: string; cls: string }> = {
  submitted: { label: '待批改', cls: 'submitted' },
  graded: { label: '已批改', cls: 'graded' },
  not_submitted: { label: '未提交', cls: 'not-submitted' },
}

// ---------- 提交列表筛选（校区/班级/状态，便于从大量提交中定位学员） ----------
const gradingCampus = ref('')
const gradingClass = ref('')
const gradingStatus = ref<'' | 'submitted' | 'graded'>('')

const gradingCampusOptions = computed(() => {
  const set = new Set<string>()
  for (const s of submissions.value) if (s.campus) set.add(s.campus)
  return [...set].sort()
})
const gradingClassOptions = computed(() => {
  const set = new Set<string>()
  for (const s of submissions.value) {
    const pool = gradingCampus.value ? (s.campus === gradingCampus.value ? s.class_names : []) : s.class_names
    for (const c of pool ?? []) set.add(c)
  }
  return [...set].sort()
})
const filteredSubmissions = computed(() => {
  return submissions.value.filter((s) => {
    if (gradingCampus.value && s.campus !== gradingCampus.value) return false
    if (gradingClass.value && !(s.class_names ?? []).includes(gradingClass.value)) return false
    if (gradingStatus.value && s.status !== gradingStatus.value) return false
    return true
  })
})

// ---------- 展示辅助 ----------

function answerText(q: any): string {
  const answers = grading.value?.answers ?? {}
  const v = answers[String(q.order_no)]
  if (v === undefined || v === null) return '（未作答）'
  if (q.type === 'single_choice' && typeof v === 'number') return q.options?.[v] ?? String(v)
  if (q.type === 'multiple_choice' && Array.isArray(v))
    return v.map((i: number) => q.options?.[i] ?? String(i)).join('、')
  if (typeof v === 'boolean') return v ? '√' : '×'
  return String(v)
}

function unescapeCode(text: string): string {
  return text.replace(/\\n/g, '\n').replace(/\\t/g, '\t')
}

function refText(q: any): string {
  const v = q.answer
  if (v === undefined || v === null) return '（无）'
  if (q.type === 'single_choice' && typeof v === 'number') return q.options?.[v] ?? String(v)
  if (q.type === 'multiple_choice' && Array.isArray(v))
    return v.map((i: number) => q.options?.[i] ?? String(i)).join('、')
  if (typeof v === 'boolean') return v ? '√' : '×'
  const s = String(v)
  return q.type === 'code_fill' || q.type === 'programming' ? unescapeCode(s) : s
}

function judgeInfo(q: any): { cls: string; label: string } | null {
  const r = (grading.value?.judge_results ?? {})[String(q.order_no)] as any
  if (!r) return null
  if (r.judged === true) {
    return r.correct ? { cls: 'ok', label: '✓ 正确' } : { cls: 'no', label: '✗ 错误' }
  }
  return { cls: 'manual', label: '待批改' }
}

function manualMax(q: any): number {
  const r = (grading.value?.judge_results ?? {})[String(q.order_no)] as any
  return Number(r?.max_score) > 0 ? Number(r.max_score) : 1
}

function scoreText(q: any): number {
  const r = (grading.value?.judge_results ?? {})[String(q.order_no)] as any
  const v = Number(r?.score)
  return Number.isFinite(v) && v >= 0 ? v : 0
}

function gradeTitle(): string {
  if (!grading.value) return '批改'
  return grading.value.status === 'graded' && gradeReadonly.value
    ? `查看批改：${grading.value.student_name || '学员'}`
    : `批改：${grading.value.student_name || '学员'}`
}

// ---------- 数据加载 ----------

async function loadStats() {
  try {
    stats.value = await getSubmissionStats(assignmentId)
  } catch {
    // 忽略统计失败
  }
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const data = await listSubmissions(assignmentId)
    submissions.value = data
    await loadStats()
    // 作业元信息：应作答口径说明用
    try {
      const a = await getAssignment(assignmentId)
      assignmentMeta.value = {
        mode: a.mode,
        targetCount: a.target_student_ids?.length ?? 0,
        classNames: a.published_class_names ?? [],
      }
    } catch {
      assignmentMeta.value = null
    }
    // 从通知跳转而来（?submission=xxx&student=xxx）：精确定位到该学生并自动打开其提交
    await openFromNotification()
  } catch {
    error.value = '加载提交失败'
  } finally {
    loading.value = false
  }
}

/** 通知跳转定位：按 submission_id（优先）或 student_id 找到提交并打开批改弹窗 */
async function openFromNotification() {
  const submissionId = typeof route.query.submission === 'string' ? route.query.submission : ''
  const studentId = typeof route.query.student === 'string' ? route.query.student : ''
  if (!submissionId && !studentId) return
  const target =
    (submissionId ? submissions.value.find((s) => s.id === submissionId) : undefined) ??
    (studentId ? submissions.value.find((s) => s.student_id === studentId) : undefined)
  if (!target) {
    // 该通知对应的提交已不在列表（如作业已撤回/提交被删）：提示并清理 URL 参数，避免反复报错
    msg.value = '该通知对应的提交已处理或不存在，已为你打开最新提交列表'
    setTimeout(() => (msg.value = ''), 4000)
    router.replace({ path: route.path, query: {} })
    return
  }
  if (target.status === 'not_submitted') {
    // 学员尚未提交（通知可能是误触或学员撤回）：同样清理参数，避免批改弹窗报「加载提交失败」
    msg.value = `「${target.student_name || '该学员'}」尚未提交，暂无可批改内容`
    setTimeout(() => (msg.value = ''), 4000)
    router.replace({ path: route.path, query: {} })
    return
  }
  await openGrade(target)
  // 消费掉一次性参数：第二次点击同一通知/刷新页面不再重复弹批改窗
  router.replace({ path: route.path, query: {} })
}

function savedCommentOf(detail: SubmissionDetail | null): string {
  const c = ((detail?.judge_results ?? {}) as Record<string, any>)._comment
  return typeof c === 'string' ? c : ''
}

function fmt(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getMonth() + 1}月${d.getDate()}日 ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

async function openGrade(item: SubmissionListItem) {
  // 未提交学员没有 submission 行，不可打开批改弹窗
  if (item.status === 'not_submitted' || !item.id) {
    return
  }
  try {
    grading.value = await getSubmission(assignmentId, item.id)
    scores.value = {}
    for (const q of grading.value?.questions ?? []) {
      const r = (grading.value?.judge_results ?? {})[String(q.order_no)] as any
      if (r && r.judged === false) {
        scores.value[String(q.order_no)] = r.score ?? 0
      }
    }
    comment.value = savedCommentOf(grading.value)
    // 已批改默认只读查看；待批改直接进入编辑态
    gradeReadonly.value = grading.value?.status === 'graded'
    gradingVisible.value = true
  } catch (e: any) {
    // 已批改/被删除等情况下给出明确提示，避免「加载提交失败」误导
    const status = e?.response?.status
    const detail = e?.response?.data?.detail as string | undefined
    if (status === 404) {
      alert(detail || '该提交已不存在（可能已被删除或作业已撤回），请刷新列表')
      await load()
    } else {
      alert(detail || '加载提交失败')
    }
  }
}

async function submitGrade() {
  if (!grading.value) return
  submitting.value = true
  try {
    await gradeSubmission(assignmentId, grading.value.id, {
      scores: scores.value,
      comment: comment.value || null,
    })
    msg.value = '批改完成，学员端已可查看成绩'
    setTimeout(() => (msg.value = ''), 3000)
    gradingVisible.value = false
    await load()
  } catch (e: any) {
    alert(e?.response?.data?.detail || '批改失败')
  } finally {
    submitting.value = false
  }
}

// ---------- 未达标学员 → 一键生成补练 ----------

const makeupVisible = ref(false)
const makeupSubmitting = ref(false)
const makeupError = ref('')

/** 已批改且未达标的学员（补练对象） */
const failedStudents = computed(() =>
  submissions.value.filter((s) => s.status === 'graded' && s.passed === false),
)

function openMakeup() {
  makeupError.value = ''
  makeupSubmitting.value = false
  if (failedStudents.value.length === 0) {
    makeupError.value = '当前没有未达标的学员'
  }
  makeupVisible.value = true
}

async function confirmMakeup() {
  if (failedStudents.value.length === 0) {
    makeupError.value = '当前没有未达标的学员'
    return
  }
  makeupSubmitting.value = true
  makeupError.value = ''
  try {
    const draft = await createMakeupAssignment(
      assignmentId,
      failedStudents.value.map((s) => s.student_id),
    )
    makeupVisible.value = false
    window.alert(
      `已生成补练草稿《${draft.title}》，仅 ${draft.target_student_names.length} 名学员可见。可在 AI 习题页用 AI 出题后发布。`,
    )
    router.push({ name: 'assignments', query: { draft: draft.id } })
  } catch (e: any) {
    makeupError.value = e?.response?.data?.detail || '生成补练作业失败'
  } finally {
    makeupSubmitting.value = false
  }
}

onMounted(load)

/** 通知跳转定位是作用于当前作业的：同页切换作业（params.id 变更）或 query 变更时重新定位 */
watch(
  () => String(route.params.id),
  () => {
    gradingVisible.value = false
    grading.value = null
    void load()
  },
)
watch(
  () => [route.query.submission, route.query.student],
  () => {
    void openFromNotification()
  },
)
</script>

<template>
  <div>
    <button class="back-btn" @click="router.push({ name: 'assignments' })">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m15 18-6-6 6-6" /></svg>
      返回作业管理
    </button>

    <header class="page-head">
      <div>
        <h1>作业批改</h1>
        <p class="page-sub">客观题已自动判分 · 编程题教师人工批改（FR-CL-18）</p>
        <p v-if="stats" class="stats-scope">
          应作答口径：{{ statsScopeText }}
        </p>
      </div>
      <div class="head-right">
        <div v-if="stats" class="stats-row">
          <div class="stat-chip"><span>应作答</span><strong>{{ stats.total_students }}</strong></div>
          <div class="stat-chip"><span>已提交</span><strong>{{ stats.submitted }}</strong></div>
          <div class="stat-chip"><span>待批改</span><strong>{{ stats.pending_review }}</strong></div>
          <div class="stat-chip"><span>已批改</span><strong>{{ stats.graded }}</strong></div>
          <div class="stat-chip"><span>未提交</span><strong>{{ stats.not_submitted }}</strong></div>
          <div class="stat-chip"><span>平均分</span><strong>{{ stats.avg_score ?? '—' }}</strong></div>
          <div class="stat-chip" v-if="stats.passing_score !== null"><span>达标线</span><strong>{{ stats.passing_score }}</strong></div>
          <div class="stat-chip" v-if="stats.passing_score !== null"><span>未达标</span><strong>{{ stats.below_pass }}</strong></div>
        </div>
        <button
          class="makeup-btn"
          :disabled="!failedStudents.length"
          title="为未达标学员生成同类型补练作业（仅这些学员可见）"
          @click="openMakeup"
        >
          一键生成补练作业（{{ failedStudents.length }}）
        </button>
      </div>
    </header>

    <p v-if="error" class="error-banner">{{ error }}</p>
    <p v-if="msg" class="success-banner">{{ msg }}</p>

    <div v-if="loading" class="loading-tip">加载中…</div>

    <div v-else-if="submissions.length === 0" class="empty-tip">
      该作业暂无应作答学员（请确认已发布到班级或学员）
    </div>

    <div v-else>
      <div class="grading-filters">
        <select v-model="gradingCampus" class="filter-input" title="按学员校区筛选">
          <option value="">全部校区</option>
          <option v-for="c in gradingCampusOptions" :key="c" :value="c">{{ c }}</option>
        </select>
        <select v-model="gradingClass" class="filter-input" title="按学员班级筛选">
          <option value="">全部班级</option>
          <option v-for="c in gradingClassOptions" :key="c" :value="c">{{ c }}</option>
        </select>
        <select v-model="gradingStatus" class="filter-input" title="按提交状态筛选">
          <option value="">全部状态</option>
          <option value="submitted">待批改</option>
          <option value="graded">已批改</option>
          <option value="not_submitted">未提交</option>
        </select>
        <span class="filter-count">共 {{ filteredSubmissions.length }} / {{ submissions.length }} 份</span>
      </div>
      <div v-if="filteredSubmissions.length === 0" class="empty-tip">当前筛选无匹配提交</div>
      <div v-else class="submission-list">
      <div v-for="s in filteredSubmissions" :key="s.id" class="submission-card">
        <div class="s-main">
          <div class="s-top">
            <strong>{{ s.student_name || '学员' }}</strong>
            <span v-if="s.campus" class="campus-tag">{{ s.campus }}</span>
            <span v-for="c in (s.class_names ?? [])" :key="c" class="class-tag">{{ c }}</span>
            <span class="status-pill" :class="statusMap[s.status]?.cls || 'submitted'">
              {{ statusMap[s.status]?.label || s.status }}
            </span>
            <span
              v-if="s.passed === true"
              class="pass-pill pass"
            >
              达标
            </span>
            <span
              v-else-if="s.passed === false"
              class="pass-pill fail"
            >
              未达标
            </span>
          </div>
          <div class="s-meta">
            <span v-if="s.submitted_at">提交于 {{ fmt(s.submitted_at) }}</span>
            <span v-if="s.score !== null">· 得分 {{ s.score }}/{{ s.total }}</span>
            <span v-if="s.pending_manual > 0">· {{ s.pending_manual }} 题待人工批改</span>
          </div>
        </div>
        <button
          v-if="s.status !== 'not_submitted'"
          class="grade-btn"
          :class="{ graded: s.status === 'graded' }"
          @click="openGrade(s)"
        >
          {{ s.status === 'graded' ? '查看' : '去批改' }}
        </button>
        <span v-else class="no-submission">未提交</span>
      </div>
      </div>
    </div>

    <!-- 一键生成补练作业 -->
    <div v-if="makeupVisible" class="overlay" @click.self="makeupVisible = false">
      <div class="modal grade-modal">
        <div class="modal-head">
          <h2>生成补练作业</h2>
          <button class="close-btn" @click="makeupVisible = false">✕</button>
        </div>
        <div class="grade-body">
          <p class="page-sub">
            将基于当前作业生成同类型补练草稿，并仅对 {{ failedStudents.length }} 名未达标学员可见。
          </p>
          <ul class="failed-list">
            <li v-for="s in failedStudents" :key="s.id">
              {{ s.student_name || '学员' }} · {{ s.score }}/{{ s.total }}
            </li>
          </ul>
          <p v-if="makeupError" class="error-banner">{{ makeupError }}</p>
        </div>
        <div class="modal-actions">
          <button class="m-btn ghost" @click="makeupVisible = false">取消</button>
          <button class="m-btn brand" :disabled="makeupSubmitting" @click="confirmMakeup">
            {{ makeupSubmitting ? '生成中…' : '生成补练草稿' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 批改弹窗 -->
    <div v-if="gradingVisible && grading" class="overlay" @click.self="gradingVisible = false">
      <div class="modal grade-modal">
        <div class="modal-head">
          <h2>{{ gradeTitle() }}</h2>
          <button class="close-btn" @click="gradingVisible = false">✕</button>
        </div>

        <div class="grade-body">
          <p v-if="isGradeView" class="view-tip">
            该提交已批改完成，以下为批改结果（只读）。如需改分请点「重新批改」。
          </p>
          <div v-for="q in grading.questions" :key="q.order_no" class="g-question">
            <div class="g-q-head">
              <span class="q-type">{{ typeLabels[q.type] || q.type }}</span>
              <span class="q-no">第 {{ q.order_no }} 题</span>
              <span v-if="judgeInfo(q)" class="judge-pill" :class="judgeInfo(q)!.cls">
                {{ judgeInfo(q)!.label }}
              </span>
            </div>
            <p class="g-stem">{{ q.stem }}</p>

            <!-- 选择题选项展示 -->
            <div v-if="q.options?.length" class="g-options">
              <div
                v-for="(opt, oi) in q.options"
                :key="oi"
                class="g-option"
                :class="{ correct: q.type === 'single_choice' && q.answer === oi }"
              >
                <span class="opt-letter">{{ 'ABCDEFGH'[oi] }}</span>
                <span>{{ opt }}</span>
              </div>
            </div>

            <!-- 学员答案 -->
            <div class="g-answer">
              <span class="label">学员答案</span>
              <pre class="answer-pre">{{ answerText(q) }}</pre>
            </div>

            <!-- 参考答案 -->
            <div class="g-ref">
              <span class="label">参考答案</span>
              <pre class="ref-pre">{{ refText(q) }}</pre>
            </div>
          </div>

          <!-- 只读查看态：展示已给分数与已保存评语，不可改 -->
          <template v-if="isGradeView">
            <div v-if="manualQs.length > 0" class="g-review">
              <span class="label">人工批改得分</span>
              <ul class="review-list">
                <li v-for="q in manualQs" :key="q.order_no">
                  第 {{ q.order_no }} 题 · {{ typeLabels[q.type] || q.type }} ·
                  {{ scoreText(q) }} / {{ manualMax(q) }} 分
                </li>
              </ul>
            </div>
            <div class="g-review">
              <span class="label">批改评语</span>
              <p class="review-comment">{{ savedComment || '（无评语）' }}</p>
            </div>
          </template>

          <!-- 待批改态：人工打分 + 评语输入 -->
          <template v-else>
            <!-- 编程题人工打分（满分 = 该题型分值） -->
            <div v-for="q in pendingManualQs" :key="q.order_no" class="g-score">
              <span>第 {{ q.order_no }} 题得分（满分 {{ manualMax(q) }} 分）</span>
              <div class="score-btns">
                <button
                  class="score-btn"
                  :class="{ active: scores[String(q.order_no)] === 0 }"
                  @click="scores[String(q.order_no)] = 0"
                >
                  0 分
                </button>
                <button
                  class="score-btn"
                  :class="{ active: scores[String(q.order_no)] === manualMax(q) }"
                  @click="scores[String(q.order_no)] = manualMax(q)"
                >
                  {{ manualMax(q) }} 分
                </button>
              </div>
            </div>

            <label class="comment-field">
              <span>批改评语（可选）</span>
              <textarea v-model="comment" rows="3" placeholder="如：整体不错，注意变量命名…" />
            </label>
          </template>
        </div>

        <div class="modal-actions">
          <button class="m-btn ghost" @click="gradingVisible = false">
            {{ isGradeView ? '返回' : '取消' }}
          </button>
          <button
            v-if="isGradeView"
            class="m-btn ghost"
            @click="gradeReadonly = false"
          >
            重新批改
          </button>
          <button
            v-else
            class="m-btn brand"
            :disabled="submitting"
            @click="submitGrade"
          >
            {{ submitting ? '提交中…' : '确认批改' }}
          </button>
        </div>
      </div>
    </div>
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

.page-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
}

.head-right {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 10px;
}
h1 {
  font-size: 22px;
}
.page-sub {
  color: var(--ink-3);
  font-size: 13px;
  margin-top: 4px;
}
.stats-scope {
  color: var(--ink-3);
  font-size: 12px;
  margin-top: 4px;
}

.stats-row {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.stat-chip {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  padding: 8px 16px;
  border-radius: 12px;
  background: var(--surface);
  border: 1px solid var(--line);
}

.stat-chip span {
  font-size: 11.5px;
  color: var(--ink-3);
}

.stat-chip strong {
  font-size: 18px;
  font-weight: 800;
}

.error-banner {
  background: var(--danger-soft);
  color: var(--danger);
  padding: 10px 14px;
  border-radius: 10px;
  margin-bottom: 14px;
  font-size: 13px;
}

.success-banner {
  background: var(--success-soft);
  color: var(--success);
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

.empty-tip {
  text-align: center;
  color: var(--ink-3);
  padding: 40px 0;
  font-size: 14px;
  background: var(--surface);
  border: 1px dashed var(--line);
  border-radius: 16px;
}

.submission-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

/* 提交列表筛选行（校区/班级/状态） */
.grading-filters {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.grading-filters .filter-input {
  padding: 7px 10px;
  border: 1px solid var(--line);
  border-radius: 9px;
  font-size: 12.5px;
  background: var(--surface);
  color: var(--ink-2);
}
.grading-filters .filter-input:focus {
  outline: none;
  border-color: var(--brand);
  box-shadow: 0 0 0 3px var(--brand-soft);
}
.filter-count {
  font-size: 12px;
  color: var(--ink-3);
  margin-left: auto;
}

/* 学员归属徽标：校区 + 班级 */
.campus-tag,
.class-tag {
  font-size: 11px;
  padding: 1px 8px;
  border-radius: 999px;
  line-height: 1.6;
  white-space: nowrap;
}
.campus-tag {
  background: #eef2ff;
  color: #4f46e5;
}
.class-tag {
  background: #f1f5f9;
  color: var(--ink-2);
}

.submission-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 16px 18px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 14px;
  transition: all 0.15s;
}

.submission-card:hover {
  border-color: #c7d2fe;
  box-shadow: var(--shadow-sm);
}

.s-top {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 4px;
}

.s-top strong {
  font-size: 15px;
}

.s-meta {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  font-size: 12.5px;
  color: var(--ink-3);
}

.status-pill {
  font-size: 11.5px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 999px;
}

.status-pill.submitted {
  background: var(--warning-soft);
  color: #b45309;
}

.pass-pill {
  font-size: 11.5px;
  font-weight: 700;
  padding: 2px 9px;
  border-radius: 999px;
}
.pass-pill.pass {
  background: var(--success-soft);
  color: var(--success);
}
.pass-pill.fail {
  background: var(--danger-soft);
  color: var(--danger);
}

.makeup-btn {
  padding: 8px 16px;
  border-radius: 999px;
  border: 1px solid #c7d2fe;
  background: linear-gradient(135deg, #6366f1, #06b6d4);
  color: #fff;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}
.makeup-btn:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 6px 14px rgba(99, 102, 241, 0.3);
}
.makeup-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.failed-list {
  margin: 10px 0 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.failed-list li {
  font-size: 13px;
  padding: 7px 12px;
  border-radius: 8px;
  background: var(--danger-soft);
  color: var(--danger);
  font-weight: 600;
}

.status-pill.graded {
  background: var(--success-soft);
  color: var(--success);
}

.status-pill.not-submitted {
  background: var(--line);
  color: var(--ink-3);
}

.grade-btn.not-submitted {
  background: var(--surface);
  color: var(--ink-3);
  border: 1px solid var(--line);
  cursor: default;
}

.grade-btn.not-submitted:hover {
  transform: none;
  box-shadow: none;
}

.grade-btn {
  flex-shrink: 0;
  padding: 9px 20px;
  border-radius: 12px;
  border: none;
  background: linear-gradient(135deg, #6366f1, #06b6d4);
  color: #fff;
  font-size: 13.5px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.15s;
}

.grade-btn.graded {
  background: var(--surface);
  color: var(--ink-2);
  border: 1px solid var(--line);
}

.no-submission {
  flex-shrink: 0;
  font-size: 12.5px;
  color: var(--ink-3);
  padding: 0 8px;
}

.grade-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 6px 16px rgba(99, 102, 241, 0.3);
}

/* 弹窗 */
.overlay {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.5);
  backdrop-filter: blur(3px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 90;
  padding: 20px;
}

.modal {
  background: var(--surface);
  border-radius: 18px;
  box-shadow: var(--shadow-lg);
  display: flex;
  flex-direction: column;
  max-height: 92vh;
  overflow: hidden;
}

.grade-modal {
  width: 640px;
  max-width: 100%;
}

.modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px 22px 0;
}

.modal-head h2 {
  font-size: 17px;
}

.close-btn {
  background: none;
  border: none;
  font-size: 16px;
  color: var(--ink-3);
  cursor: pointer;
  padding: 4px;
}

.grade-body {
  padding: 16px 22px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.g-question {
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 14px;
}

.g-q-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.q-type {
  font-size: 11px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 999px;
  background: var(--brand-soft);
  color: var(--brand-strong);
}

.q-no {
  font-size: 12px;
  color: var(--ink-3);
}

.judge-pill {
  margin-left: auto;
  font-size: 11.5px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 999px;
}

.judge-pill.ok {
  background: var(--success-soft);
  color: var(--success);
}

.judge-pill.no {
  background: var(--danger-soft);
  color: var(--danger);
}

.judge-pill.manual {
  background: var(--warning-soft);
  color: #b45309;
}

.g-stem {
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 10px;
  white-space: pre-wrap;
}

.g-options {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 10px;
}

.g-option {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 10px;
  border-radius: 8px;
  background: var(--bg);
  font-size: 13px;
}

.g-option.correct {
  background: var(--success-soft);
}

.opt-letter {
  width: 22px;
  height: 22px;
  flex-shrink: 0;
  border-radius: 50%;
  background: var(--surface);
  border: 1px solid var(--line);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 700;
  color: var(--ink-3);
}

.g-answer,
.g-ref {
  margin-top: 8px;
}

.label {
  display: block;
  font-size: 11.5px;
  font-weight: 600;
  color: var(--ink-3);
  margin-bottom: 4px;
}

.answer-pre,
.ref-pre {
  white-space: pre-wrap;
  font-size: 12.5px;
  line-height: 1.6;
  padding: 10px 12px;
  border-radius: 10px;
  margin: 0;
}

.answer-pre {
  background: #0f172a;
  color: #e2e8f0;
  font-family: 'Cascadia Code', 'JetBrains Mono', Consolas, monospace;
}

.ref-pre {
  background: var(--bg);
  color: var(--ink-2);
}

.g-score {
  margin-top: 10px;
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 13px;
  font-weight: 600;
}

.score-btns {
  display: flex;
  gap: 8px;
}

.score-btn {
  padding: 6px 18px;
  border-radius: 10px;
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--ink-2);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.15s;
}

.score-btn.active {
  background: linear-gradient(135deg, #6366f1, #06b6d4);
  color: #fff;
  border-color: transparent;
  font-weight: 600;
}

.comment-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
}

.comment-field textarea {
  padding: 10px 12px;
  border-radius: 10px;
  border: 1.5px solid var(--line);
  font-size: 13px;
  font-family: inherit;
  resize: vertical;
}

.comment-field textarea:focus {
  outline: none;
  border-color: var(--brand);
}

.view-tip {
  margin: 0 0 12px;
  padding: 9px 12px;
  border-radius: 10px;
  background: var(--brand-soft);
  color: var(--brand-strong);
  font-size: 12.5px;
  line-height: 1.6;
}

.g-review {
  margin-top: 12px;
}

.review-list {
  margin: 6px 0 0;
  padding-left: 18px;
  font-size: 13px;
  color: var(--ink-2);
  line-height: 1.8;
}

.review-comment {
  margin: 6px 0 0;
  padding: 10px 12px;
  border-radius: 10px;
  background: var(--bg);
  color: var(--ink-2);
  font-size: 13px;
  line-height: 1.7;
  white-space: pre-wrap;
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 16px 22px 18px;
  border-top: 1px solid var(--line);
}

.m-btn {
  padding: 9px 20px;
  border-radius: 10px;
  border: none;
  font-size: 13.5px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}

.m-btn.ghost {
  background: var(--surface);
  color: var(--ink-2);
  border: 1px solid var(--line);
}

.m-btn.brand {
  background: linear-gradient(135deg, #6366f1, #06b6d4);
  color: #fff;
}

.m-btn:disabled {
  opacity: 0.6;
}
</style>
