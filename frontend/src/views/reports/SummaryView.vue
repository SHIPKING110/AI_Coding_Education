<script setup lang="ts">
import * as echarts from 'echarts/core'
import { BarChart, LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import PaginationBar from '@/components/PaginationBar.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import PromptTemplateManager from '@/components/PromptTemplateManager.vue'
import PptBuilderDrawer from './PptBuilderDrawer.vue'
import {
  createAiDraftJob,
  createReport,
  deleteReport,
  generateReportPpt,
  getAiDraftJob,
  getReport,
  listBoardReports,
  listReports,
  periodStatsComparison,
  periodStatsMonthly,
  periodStatsPreview,
  pptDownloadUrl,
  publishReport,
  unpublishReport,
  updateReport,
  type PeriodComparison,
  type PeriodMonthlyPoint,
  type PeriodStatsOut,
  type ReportBoardItemOut,
  type ReportOut,
} from '@/api/report'
import { useAuthStore } from '@/stores/auth'
import { listPromptTemplates, type PromptTemplateOut } from '@/api/prompt'
import { dayKeyFromIso, parseServerTime } from '@/utils/date'

echarts.use([LineChart, BarChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])

const auth = useAuthStore()
const router = useRouter()

// 嵌入模式（被 ReportsView 以 季度总结/年度总结 Tab 内嵌时）：
// 由父级 Tab 驱动 initialTab，隐藏自身页头避免双标题/双 Tab
const props = withDefaults(
  defineProps<{ embedded?: boolean; initialTab?: 'quarterly' | 'yearly' }>(),
  { embedded: false, initialTab: 'quarterly' },
)

// —— Tab: 季度 / 年度 ——
const activeTab = ref<'quarterly' | 'yearly'>(props.initialTab)
const periodStart = ref('')
const periodEnd = ref('')

/** 默认标题：季度 “2026年第三季度 季度总结 张三”；年度 “2026年 年度总结 张三” */
function quarterLabel(d: Date): string {
  const q = Math.floor(d.getMonth() / 3) + 1
  return `${d.getFullYear()}年${['一', '二', '三', '四'][q - 1]}季度`
}
function defaultSummaryTitle(): string {
  const name = auth.user?.name?.trim() ? ` ${auth.user.name.trim()}` : ''
  if (activeTab.value === 'quarterly') {
    return `${quarterLabel(parseServerTime(periodStartIso()))} 季度总结${name}`
  }
  return `${new Date(periodStartIso()).getFullYear()}年 年度总结${name}`
}

function pad2(n: number): string {
  return String(n).padStart(2, '0')
}

function toNaive(d: Date): string {
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`
}

function currentQuarterRange(): string[] {
  const now = new Date()
  const q = Math.floor(now.getMonth() / 3)
  const start = new Date(now.getFullYear(), q * 3, 1)
  const end = new Date(now.getFullYear(), q * 3 + 3, 0)
  return [toNaive(start), toNaive(end)]
}

function defaultRange() {
  if (activeTab.value === 'quarterly') {
    const [s, e] = currentQuarterRange()
    periodStart.value = s
    periodEnd.value = e
  } else {
    periodStart.value = `${new Date().getFullYear()}-01-01`
    periodEnd.value = `${new Date().getFullYear()}-12-31`
  }
}

// —— 报告 + 统计 ——
const report = ref<ReportOut | null>(null)
const form = ref<{ title: string; fields: Record<string, string> }>({ title: '', fields: {} })
const stats = ref<PeriodStatsOut | null>(null)
const loading = ref(false)
const statsLoading = ref(false)
const saving = ref(false)
const publishing = ref(false)
const pptGenerating = ref(false)
const pptUrl = ref('')
const showPptBuilder = ref(false)
const FIELD_MAP: Record<'quarterly' | 'yearly', { key: string; label: string; placeholder: string }[]> = {
  quarterly: [
    { key: 'summary', label: '季度总体情况', placeholder: '概括本季度整体教学、管理情况…' },
    { key: 'highlights', label: '主要亮点', placeholder: '学员进步、优秀成果、家长反馈等…' },
    { key: 'problems', label: '问题与改进方向', placeholder: '客观指出问题并给改进方向…' },
    { key: 'next_plan', label: '下阶段计划', placeholder: '下季度的教学/管理重点…' },
    { key: 'stats_notes', label: '数据说明', placeholder: '结合统计数据的教学情况说明…' },
  ],
  yearly: [
    { key: 'summary', label: '年度总体情况', placeholder: '概括本年度整体教学、管理情况…' },
    { key: 'highlights', label: '主要亮点', placeholder: '年度成就、里程碑、学员成长…' },
    { key: 'problems', label: '问题与改进方向', placeholder: '客观指出问题并给改进方向…' },
    { key: 'next_plan', label: '下年度计划', placeholder: '下一年度的规划与目标…' },
    { key: 'stats_notes', label: '数据说明', placeholder: '结合统计数据的教学情况说明…' },
  ],
}
const fields = computed(() => FIELD_MAP[activeTab.value])

// —— 历史列表 ——
const history = ref<ReportOut[]>([])
const historyTotal = ref(0)
const historyOffset = ref(0)
const historyLimit = 10

const showAiModal = ref(false)
const showTplManage = ref(false)
const aiNote = ref('')
const aiError = ref('')
// 提示词模板（报告类系统预设 + 个人模板）：所选模板内容作为写作风格要求
const aiTemplates = ref<PromptTemplateOut[]>([])
const aiTemplateId = ref('')
const aiQuarters = ref<ReportOut[]>([])
const aiQuartersLoading = ref(false)
const aiQuarterIds = ref<string[]>([])
const aiQuartersFromYear = ref('')
// AI 后台任务：提交后即可关弹窗/切页面，顶部任务条轮询取回结果
const aiJobId = ref('')
const aiJobReportId = ref('')
const aiJobElapsed = ref(0)
const aiJobStatus = ref<'idle' | 'pending' | 'running' | 'succeeded' | 'failed'>('idle')
const aiJobError = ref('')
let aiPollTimer: ReturnType<typeof setInterval> | null = null
let aiElapsedTimer: ReturnType<typeof setInterval> | null = null

const AI_JOB_KEY = 'summary-ai-job'
const aiJobActive = computed(() => aiJobStatus.value === 'pending' || aiJobStatus.value === 'running')

function stopAiPoll() {
  if (aiPollTimer) {
    clearInterval(aiPollTimer)
    aiPollTimer = null
  }
  if (aiElapsedTimer) {
    clearInterval(aiElapsedTimer)
    aiElapsedTimer = null
  }
}

function clearAiJobState() {
  stopAiPoll()
  aiJobId.value = ''
  aiJobReportId.value = ''
  aiJobElapsed.value = 0
  aiJobStatus.value = 'idle'
  aiJobError.value = ''
  try {
    localStorage.removeItem(AI_JOB_KEY)
  } catch { /* 忽略存储异常 */ }
}

function persistAiJob() {
  try {
    localStorage.setItem(
      AI_JOB_KEY,
      JSON.stringify({ jobId: aiJobId.value, reportId: aiJobReportId.value }),
    )
  } catch { /* 忽略存储异常 */ }
}

/** 回填 AI 草稿到表单（任务成功后调用，与原来同步逻辑一致） */
function applyAiDraft(draft: { title?: string | null; content?: Record<string, string | null> }) {
  if (draft.title) form.value.title = draft.title
  const c = draft.content ?? {}
  for (const f of fields.value) {
    const v = c[f.key]
    if (v) form.value.fields[f.key] = v
  }
}

async function pollAiJob() {
  if (!aiJobId.value || !aiJobReportId.value) {
    clearAiJobState()
    return
  }
  try {
    const st = await getAiDraftJob(aiJobReportId.value, aiJobId.value)
    aiJobStatus.value = st.status
    aiJobElapsed.value = Math.floor(st.elapsed_seconds ?? aiJobElapsed.value)
    if (st.status === 'succeeded') {
      // 仅当任务对应的报告仍是当前编辑器中的报告时才回填，避免切周期后串稿
      if (report.value && report.value.id === aiJobReportId.value) {
        applyAiDraft({ title: st.title, content: st.content ?? {} })
        showAiDone.value = true
        aiDoneMsg.value = 'AI 总结草稿已生成，已自动回填到编辑器，请检查编辑后保存。'
      } else {
        showAiDone.value = true
        aiDoneMsg.value = 'AI 总结草稿已生成，请在历史记录中打开对应报告查看（已回填到该报告的编辑器需重新打开）。'
      }
      clearAiJobState()
    } else if (st.status === 'failed') {
      aiJobError.value = st.error || 'AI 总结生成失败'
      showError(st.error || 'AI 总结生成失败')
      stopAiPoll()
      aiJobStatus.value = 'failed'
    }
  } catch {
    // 轮询失败不打断：可能是任务过期，停轮询并提示
    stopAiPoll()
    aiJobError.value = 'AI 任务已过期或查询失败，请重新生成'
  }
}

function startAiPoll() {
  stopAiPoll()
  aiElapsedTimer = setInterval(() => {
    aiJobElapsed.value += 1
  }, 1000)
  aiPollTimer = setInterval(pollAiJob, 3000)
  void pollAiJob()
}

/** 提交 AI 后台任务：立即返回，可关弹窗继续做别的事 */
async function submitAiJob() {
  if (!report.value) return
  if (aiJobActive.value) {
    aiError.value = '已有 AI 任务在后台生成中，请等待完成后再提交'
    return
  }
  aiError.value = ''
  // AI 生成门禁（与 PPT 同口径，避免空内容浪费 token）：年度已选季度总结时放行
  if (!(activeTab.value === 'yearly' && aiQuarterIds.value.length > 0)) {
    const reason = summaryEmptyReason()
    if (reason) {
      aiError.value = 'AI 生成需要实质内容：正文为空且期间统计全零，请先填写总结内容或确认周期内有数据后再生成（避免浪费 token 生成无意义内容）'
      return
    }
  }
  try {
    const job = await createAiDraftJob(report.value.id, {
      extra_note: aiNote.value || null,
      ...(activeTab.value === 'yearly' ? { source_quarter_ids: aiQuarterIds.value } : {}),
      template_id: aiTemplateId.value || null,
    })
    aiJobId.value = job.job_id
    aiJobReportId.value = report.value.id
    aiJobElapsed.value = 0
    aiJobError.value = ''
    aiJobStatus.value = 'pending'
    persistAiJob()
    showAiModal.value = false
    document.querySelector('.summary-view .ai-job-bar')?.classList.remove('hidden')
    showNotice('AI 正在后台生成（约 20-60 秒），可继续编辑，完成后自动回填')
    startAiPoll()
  } catch (e: any) {
    aiError.value = e?.response?.data?.detail || 'AI 任务提交失败'
  }
}

/** 恢复未完成的 AI 任务（刷新/切页面回来继续等结果） */
function restoreAiJob() {
  try {
    const raw = localStorage.getItem(AI_JOB_KEY)
    if (!raw) return
    const { jobId, reportId } = JSON.parse(raw)
    if (!jobId || !reportId) return
    aiJobId.value = jobId
    aiJobReportId.value = reportId
    aiJobStatus.value = 'pending'
    aiJobElapsed.value = 0
    aiJobError.value = ''
    startAiPoll()
  } catch { /* 忽略损坏的本地任务 */ }
}

const isAdminStaff = computed(() => ['admin', 'staff'].includes(auth.user?.role || ''))

function goReports() {
  router.push({ path: '/reports', query: { tab: 'quarterly' } })
}

function showError(m: string) {
  pushToast('error', m)
}
function showNotice(m: string) {
  pushToast('ok', m)
}

/** 右下角 Toast 栈：成功/提示 4s 自动消失，错误常驻手动关闭 */
interface ToastItem { id: number; kind: 'ok' | 'error' | 'warn'; msg: string }
const toasts = ref<ToastItem[]>([])
let toastSeq = 0
function pushToast(kind: ToastItem['kind'], msg: string) {
  const text = (msg || '').trim()
  if (!text) return
  const id = ++toastSeq
  // 同类相同文案不重复堆叠
  if (toasts.value.some((t) => t.kind === kind && t.msg === text)) return
  toasts.value.push({ id, kind, msg: text })
  // 最多保留 3 条，超出的最早成功提示先出栈（错误保留）
  const extras = toasts.value.filter((t) => t.kind !== 'error').slice(0, Math.max(0, toasts.value.length - 3))
  for (const t of extras) dismissToast(t.id)
  if (kind !== 'error') {
    window.setTimeout(() => dismissToast(id), 4000)
  }
}
function dismissToast(id: number) {
  toasts.value = toasts.value.filter((t) => t.id !== id)
}

function resetForm() {
  form.value = { title: '', fields: {} }
}

function periodStartIso(): string {
  return `${periodStart.value}T00:00:00`
}
function periodEndIso(): string {
  return `${periodEnd.value}T23:59:59`
}

let loadSeq = 0
// 按 id 点选历史时，loadCurrent 内会同步 periodStart/End；用该标记告诉
// watch 这次周期变化来自点选，只刷新图表/公栏，不再触发区间查询覆盖已载入的内容
let periodSyncFromPick = false
// “新建草稿”会重置周期；用该标记抑制周期 watch 的自动回填，保证文本框真正空白
let suppressPeriodReload = false

async function loadCurrent(reportId?: string) {
  const seq = ++loadSeq
  loading.value = true
  try {
    if (reportId) {
      const r = await getReport(reportId)
      if (seq !== loadSeq) return
      report.value = r
      periodSyncFromPick = true
      periodStart.value = dayKeyFromIso(r.period_start)
      periodEnd.value = dayKeyFromIso(r.period_end)
    } else {
      const page = await listReports({
        type: activeTab.value,
        start: periodStart.value,
        end: periodEnd.value,
        limit: 1,
      })
      if (seq !== loadSeq) return
      report.value = page.items[0] ?? null
    }
    pptUrl.value = report.value?.ppt_url ?? ''
    if (report.value) {
      const c = report.value.content ?? {}
      form.value = {
        // 存量无标题的老数据：展示时也按默认规则补齐，保存即落库
        title: report.value.title?.trim() ? report.value.title : defaultSummaryTitle(),
        fields: Object.fromEntries(fields.value.map((f) => [f.key, (c[f.key] as string) ?? ''])),
      }
    } else {
      // 新期间无总结：标题按 “日期 + 类型 + 教师姓名” 预填
      resetForm()
      form.value.title = defaultSummaryTitle()
    }
  } catch {
    showError('加载总结失败')
  } finally {
    loading.value = false
  }
  loadHistory()
  loadStats()
}

async function loadStats() {
  statsLoading.value = true
  try {
    stats.value = await periodStatsPreview({ start: periodStart.value, end: periodEnd.value, report_type: activeTab.value })
  } catch {
    stats.value = null
  } finally {
    statsLoading.value = false
  }
}

// —— 图表数据（月度折线图 + 期间对比柱状图） ——
const monthlyData = ref<PeriodMonthlyPoint[]>([])
const comparisonData = ref<PeriodComparison | null>(null)
const lineChartEl = ref<HTMLDivElement | null>(null)
const barChartEl = ref<HTMLDivElement | null>(null)
let lineChart: echarts.ECharts | null = null
let barChart: echarts.ECharts | null = null

async function loadCharts() {
  const params = { start: periodStart.value, end: periodEnd.value }
  try {
    monthlyData.value = await periodStatsMonthly(params)
  } catch {
    monthlyData.value = []
  }
  try {
    comparisonData.value = await periodStatsComparison(params)
  } catch {
    comparisonData.value = null
  }
  await nextTick()
  renderLineChart()
  renderBarChart()
}

function renderLineChart() {
  if (!lineChartEl.value) return
  if (!lineChart) lineChart = echarts.init(lineChartEl.value)
  const labels = monthlyData.value.map((m) => m.month)
  lineChart.setOption({
    color: ['#6366f1', '#06b6d4', '#f59e0b', '#10b981'],
    tooltip: { trigger: 'axis' },
    legend: { data: ['应耗课时', '消耗课时', '新增学员', '上课人次'], bottom: 0 },
    grid: { left: 40, right: 20, top: 30, bottom: 45 },
    xAxis: { type: 'category', data: labels, boundaryGap: false },
    yAxis: { type: 'value', minInterval: 1 },
    series: [
      { name: '应耗课时', type: 'line', smooth: true, data: monthlyData.value.map((m) => m.expected_lessons), areaStyle: { opacity: 0.08 } },
      { name: '消耗课时', type: 'line', smooth: true, data: monthlyData.value.map((m) => m.consumed_lessons), areaStyle: { opacity: 0.08 } },
      { name: '新增学员', type: 'line', smooth: true, data: monthlyData.value.map((m) => m.new_students) },
      { name: '上课人次', type: 'line', smooth: true, data: monthlyData.value.map((m) => m.attendance) },
    ],
  })
}

function renderBarChart() {
  if (!barChartEl.value) return
  if (!barChart) barChart = echarts.init(barChartEl.value)
  const c = comparisonData.value
  const prevLabel = activeTab.value === 'quarterly' ? '上季度' : '上一年'
  barChart.setOption({
    color: ['#6366f1', '#c7d2fe'],
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { data: [`本${activeTab.value === 'quarterly' ? '季度' : '年度'}`, prevLabel], bottom: 0 },
    grid: { left: 40, right: 20, top: 30, bottom: 45 },
    xAxis: { type: 'category', data: c?.labels || [] },
    yAxis: { type: 'value', minInterval: 1 },
    series: [
      { name: `本${activeTab.value === 'quarterly' ? '季度' : '年度'}`, type: 'bar', data: c?.current || [], barGap: '20%' },
      { name: prevLabel, type: 'bar', data: c?.previous || [] },
    ],
  })
}

// —— PPT 公栏：全部教师已发布季度/年度总结（含 PPT） ——
const pptBoard = ref<ReportBoardItemOut[]>([])
const pptBoardTotal = ref(0)
const pptBoardLoading = ref(false)
const pptBoardPage = ref(1)
const pptBoardLimit = 8

async function loadPptBoard() {
  pptBoardLoading.value = true
  try {
    const p = await listBoardReports({
      type: activeTab.value,
      limit: pptBoardLimit,
      offset: (pptBoardPage.value - 1) * pptBoardLimit,
    })
    pptBoard.value = p.items
    pptBoardTotal.value = p.total
  } catch {
    pptBoard.value = []
    pptBoardTotal.value = 0
  } finally {
    pptBoardLoading.value = false
  }
}

function pagerVisible() {
  return pptBoardTotal.value > 0
}

/** 从 PPT 公栏跳转到编辑器编辑自己的总结：按 id 直接载入该条报告 */
function openOwnSummary(item: ReportBoardItemOut) {
  activeTab.value = item.type as 'quarterly' | 'yearly'
  loadCurrent(item.id)
}

/** 历史记录是否正载入在编辑器中 */
const editingHistoryId = computed(() => report.value?.id ?? '')

/** 新建草稿：清空编辑器回到“当前期间”的空白表单。
 * 两步走：先同步清空表单给用户即时反馈，再重置周期并抑制自动回填，
 * 保证文本框真正空白（不再把当前期间已有报告的内容回填进来）。
 * 若当前期间已有同类型总结（同类型同周期唯一），仅提示“保存将覆盖”，不静默回填。 */
async function newBlankDraft() {
  suppressPeriodReload = true
  resetForm()
  form.value.title = defaultSummaryTitle()
  pptUrl.value = ''
  report.value = null
  defaultRange()
  requestAnimationFrame(() => {
    document.querySelector('.summary-view .editor-card')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  })
  // 等周期 watch 跑完（消费 suppressPeriodReload），再解除抑制
  await nextTick()
  suppressPeriodReload = false
  loadStats()
  loadCharts()
  loadPptBoard()
  // 探测当前期间是否已有总结，仅用于提示，不回填内容
  let existing: ReportOut | null = null
  try {
    const page = await listReports({
      type: activeTab.value,
      start: periodStart.value,
      end: periodEnd.value,
      limit: 1,
    })
    existing = page.items[0] ?? null
  } catch {
    existing = null
  }
  if (existing) {
    pushToast(
      'warn',
      existing.status === 'published'
        ? '当前期间已有已提交总结，保存将覆盖原内容；如需保留请先撤回或调整周期'
        : '当前期间已有草稿，保存将覆盖原内容',
    )
  } else {
    showNotice('已新建空白草稿（当前期间），填写后保存')
  }
}

/** 新建草稿二次确认：编辑器有未保存改动时先提示，避免误清空 */
const showNewDraftConfirm = ref(false)

function requestNewBlankDraft() {
  if (formDirty.value) {
    showNewDraftConfirm.value = true
    return
  }
  newBlankDraft()
}

/** 当前表单相对已载入报告是否有未保存改动 */
const formDirty = computed(() => {
  const c = report.value?.content ?? {}
  if ((form.value.title ?? '').trim() !== ((report.value?.title ?? '').trim())) {
    // 新期间空白表单的默认标题不算改动
    if (report.value || (form.value.title ?? '').trim() !== defaultSummaryTitle()) return true
  }
  return fields.value.some((f) => (form.value.fields[f.key] ?? '') !== ((c[f.key] as string) ?? ''))
})

/** 点击历史总结：按 id 直接载入该条报告，不再按周期推测（避免周期重叠/查询取首条错位） */
function openHistorySummary(r: ReportOut) {
  loadCurrent(r.id)
  requestAnimationFrame(() => {
    document.querySelector('.editor-card')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  })
}

const historyPage = computed(() => Math.floor(historyOffset.value / historyLimit) + 1)

async function loadHistory() {
  try {
    // mine=true：历史记录只看本人报告（任何角色），他人报告仅通过公栏查看已发布内容
    const p = await listReports({ type: activeTab.value, mine: true, limit: historyLimit, offset: historyOffset.value })
    history.value = p.items
    historyTotal.value = p.total
  } catch {
    history.value = []
    historyTotal.value = 0
  }
}

/** 删除报告（本人或管理员/教务）：确认后调用后端并刷新历史/公栏 */
const deletingId = ref('')
async function removeReport(r: { id: string; title?: string | null }) {
  const name = r.title?.trim() || '该报告'
  if (!window.confirm(`确认删除「${name}」？删除后不可恢复（含已生成 PPT）。`)) return
  deletingId.value = r.id
  try {
    await deleteReport(r.id)
    if (report.value?.id === r.id) {
      // 删除的正是编辑器当前载入的报告：清空编辑器
      report.value = null
      pptUrl.value = ''
      resetForm()
      form.value.title = defaultSummaryTitle()
    }
    showNotice('已删除')
    loadHistory()
    loadPptBoard()
  } catch (e: any) {
    showError(e?.response?.data?.detail || '删除失败')
  } finally {
    deletingId.value = ''
  }
}

async function save() {
  const title = form.value.title.trim() || defaultSummaryTitle()
  const content = Object.fromEntries(fields.value.map((f) => [f.key, (form.value.fields[f.key] ?? '').trim()]))
  // PPT 明细表快照与统计一起落库：季度=逐月明细，年度=季度对照，保证 PPT 数据与页面一致
  const breakdown =
    activeTab.value === 'quarterly'
      ? monthlyData.value.map((m) => ({
          month: m.month,
          consumed_lessons: m.consumed_lessons,
          expected_lessons: m.expected_lessons,
          attendance: m.attendance,
          new_students: m.new_students,
        }))
      : aiQuarters.value.map((q, i) => ({
          label: `Q${i + 1} ${(q.title || '').trim()}`.trim(),
          consumed_lessons: Number((q.stats as any)?.consumed_lessons ?? 0),
          expected_lessons: Number((q.stats as any)?.expected_lessons ?? 0),
          attendance_rate: Number((q.stats as any)?.attendance_rate ?? 0),
          summary: String((q.content as any)?.summary ?? ''),
        }))
  const contentWithSnapshot = { ...content, ppt_breakdown: breakdown }
  saving.value = true
  try {
    let r: ReportOut
    if (report.value) {
      r = await updateReport(report.value.id, { title, content: contentWithSnapshot, stats: stats.value ?? undefined })
    } else {
      r = await createReport({
        type: activeTab.value,
        period_start: periodStartIso(),
        period_end: periodEndIso(),
        title,
        content: contentWithSnapshot,
        stats: stats.value ?? undefined,
      })
    }
    report.value = r
    pptUrl.value = r.ppt_url ?? ''
    // 空标题保存时已用默认标题落库，同步回表单
    form.value.title = r.title ?? title
    showNotice('已保存草稿')
    loadHistory()
  } catch (e: any) {
    showError(e?.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
  }
}

async function publish() {
  if (!report.value) {
    showError('请先保存草稿，再提交总结')
    return
  }
  publishing.value = true
  try {
    report.value = await publishReport(report.value.id)
    showNotice('总结已提交')
    loadHistory()
  } catch (e: any) {
    showError(e?.response?.data?.detail || '发布失败')
  } finally {
    publishing.value = false
  }
}

async function unpublish() {
  if (!report.value) return
  if (!window.confirm('确认撤回该总结为草稿？撤回后可重新编辑并生成 PPT。')) return
  try {
    report.value = await unpublishReport(report.value.id)
    showNotice('已撤回为草稿')
    loadHistory()
  } catch (e: any) {
    showError(e?.response?.data?.detail || '撤回失败')
  }
}

/** 空数据预检（与后端 generate_report_ppt 门禁同口径）：正文 5 字段全空且统计全零则拦截 */
function summaryEmptyReason(): string {
  const c = form.value.fields
  const hasText = ['summary', 'highlights', 'problems', 'next_plan', 'stats_notes'].some(
    (k) => (c[k] ?? '').trim(),
  )
  if (hasText) return ''
  const s = stats.value
  const allZero =
    !s ||
    [s.schedules, s.attended, s.consumed_lessons, s.current_students].every((v) => (v ?? 0) === 0)
  if (!allZero) return ''
  if (activeTab.value === 'yearly') {
    return '年度总结暂无实质内容：正文为空、统计全零且未选用已发布季度总结，请先勾选季度总结生成 AI 年总结并保存后再生成 PPT'
  }
  return '总结暂无实质内容：正文为空且期间统计全零，请先完善总结内容或确认周期内有排课/周报数据后再生成 PPT'
}

const pptBlockedReason = computed(() => summaryEmptyReason())

/** 打开对话式 PPT 定制：跳转统一 Agent 工作台（报告 Agent，带业务上下文） */
async function openPptBuilder() {
  await save()
  if (!report.value) {
    showError('请先保存总结内容，再定制 PPT')
    return
  }
  const ctx = { kind: 'report', id: report.value.id, title: form.value.title || report.value.title || '工作总结' }
  router.push({ name: 'agents', query: { agent: 'report_ppt', context: JSON.stringify(ctx) } })
}

function onPptBuilt(url: string) {
  pptUrl.value = url
  if (report.value) report.value.ppt_url = url
  loadPptBoard()
}

/** 生成 PPT：未保存时先自动保存当前草稿（含快照）；空数据先拦截，不发请求 */
async function genPpt() {
  await save()
  if (!report.value) {
    showError('请先保存总结内容，再生成 PPT')
    return
  }
  const reason = summaryEmptyReason()
  if (reason) {
    showError(reason)
    return
  }
  // 打开要点勾选弹窗：默认全选，可取消不入页的条目
  pptPick.value = buildPptPick()
  showPptModal.value = true
}

/** 要点勾选弹窗：要点类字段按条目勾选入页（散文/数字类不参与，始终整段或走表图） */
const showPptModal = ref(false)
const pptPick = ref<{ key: string; label: string; items: { idx: number; text: string; checked: boolean }[] }[]>([])

function splitPickItems(text: string): string[] {
  const out: string[] = []
  for (const para of String(text ?? '').split(/\n+/)) {
    const t = para.trim()
    if (!t) continue
    for (const piece of t.split(/(?<=[；;])/)) {
      const p = piece.trim().replace(/^[·•\-\d.\s、，,]+/, '').replace(/[。；;]+$/, '').trim()
      if (p) out.push(p)
    }
  }
  return out
}

function buildPptPick() {
  const labels: Record<string, string> = {
    highlights: '主要亮点',
    problems: '问题与改进方向',
    next_plan: '下阶段计划',
  }
  return Object.keys(labels).map((key) => ({
    key,
    label: labels[key],
    items: splitPickItems(form.value.fields[key] ?? '').map((text, idx) => ({
      idx,
      text,
      checked: true,
    })),
  }))
}

function togglePptPick(key: string, idx: number) {
  const g = pptPick.value.find((x) => x.key === key)
  const it = g?.items.find((x) => x.idx === idx)
  if (it) it.checked = !it.checked
}

function setPptPickAll(key: string, checked: boolean) {
  const g = pptPick.value.find((x) => x.key === key)
  g?.items.forEach((x) => { x.checked = checked })
}

async function confirmGenPpt() {
  if (!report.value) return
  const include_sections: Record<string, number[]> = {}
  for (const g of pptPick.value) {
    include_sections[g.key] = g.items.filter((x) => x.checked).map((x) => x.idx)
  }
  showPptModal.value = false
  pptGenerating.value = true
  pptResult.value = null
  showPptResult.value = false
  try {
    const r = await generateReportPpt(report.value.id, { include_sections })
    pptUrl.value = r.ppt_url
    if (r.title) form.value.title = r.title
    pptResult.value = { ok: true, message: 'PPT 草稿已生成，可下载预览。如需调整内容可修改后重新生成。' }
  } catch (e: any) {
    pptResult.value = { ok: false, message: e?.response?.data?.detail || 'PPT 生成失败，请稍后重试' }
  } finally {
    pptGenerating.value = false
    showPptResult.value = true
  }
}

/** PPT 生成结果弹窗：成功 / 失败都有明确提示（之前只靠顶部横幅，容易错过） */
const showPptResult = ref(false)
const pptResult = ref<{ ok: boolean; message: string } | null>(null)

/** AI 草稿生成成功弹窗（替代顶部横幅/toast，避免用户注意不到） */
const showAiDone = ref(false)
const aiDoneMsg = ref('')

/** 结果弹窗确认：成功时直接打开下载/预览，失败时关闭 */
function confirmPptResult() {
  showPptResult.value = false
  if (pptResult.value?.ok && pptUrl.value) {
    window.open(pptDownloadUrl(pptUrl.value), '_blank', 'noopener')
  }
}

async function openAI() {
  if (!report.value) {
    showError('请先保存草稿，再生成 AI 总结')
    return
  }
  aiNote.value = ''
  aiError.value = ''
  aiQuarterIds.value = []
  aiQuarters.value = []
  await loadAiTemplates()
  showAiModal.value = true
  if (activeTab.value === 'yearly') {
    loadAiQuarters()
  }
}

/** 加载报告类提示词模板，默认选中当前总结类型对应的系统预设（模板管理弹窗变更后复用刷新） */
async function loadAiTemplates() {
  try {
    const all = await listPromptTemplates('report')
    aiTemplates.value = all
    const want = activeTab.value === 'quarterly' ? '【报告·季度总结】' : '【报告·年度总结】'
    aiTemplateId.value = aiTemplates.value.find((t) => t.name.startsWith(want))?.id ?? aiTemplates.value[0]?.id ?? ''
  } catch {
    aiTemplates.value = []
    aiTemplateId.value = ''
  }
}

/** 年度 AI：自动带出本年度已发布季度总结（默认全选，可手动勾选） */
async function loadAiQuarters() {
  aiQuartersLoading.value = true
  try {
    const year = new Date(periodStartIso()).getFullYear()
    const p = await listReports({
      type: 'quarterly',
      // 用带时间的 naive 串，避免仅日期串被后端按 UTC 解析产生边界偏移
      start: `${year}-01-01T00:00:00`,
      end: `${year}-12-31T23:59:59`,
      limit: 100,
    })
    // 后端按 period_start 倒序返回，这里按季度正序 Q1→Q4 展示。
    // 年份判断按“北京时间的日”换算，并容忍边界 1 天：Q1（01-01）在浏览器本地时区
    // 下可能被解析成上一年，直接比较年份会把 Q1 过滤掉——年度只剩 3 篇的根因之一。
    const startMs = Date.parse(`${year}-01-01T00:00:00+08:00`) - 24 * 3600_000
    const endMs = Date.parse(`${year}-12-31T23:59:59+08:00`) + 24 * 3600_000
    const published = p.items
      .filter((q) => q.status === 'published')
      .filter((q) => {
        const t = parseServerTime(q.period_start).getTime()
        return t >= startMs && t <= endMs
      })
      .sort((a, b) => +parseServerTime(a.period_start) - +parseServerTime(b.period_start))
    aiQuarters.value = published
    aiQuartersFromYear.value = String(year)
    aiQuarterIds.value = published.map((q) => q.id)
  } catch {
    aiQuarters.value = []
    aiQuarterIds.value = []
  } finally {
    aiQuartersLoading.value = false
  }
}

function selectAllAiQuarters() {
  aiQuarterIds.value = aiQuarters.value.map((q) => q.id)
}

function clearAiQuarters() {
  aiQuarterIds.value = []
}

/** 关闭任务条显示（失败态则清除任务；运行态仅隐藏，轮询继续结果照常回填） */
function dismissAiJob() {
  if (aiJobStatus.value === 'failed') {
    clearAiJobState()
    return
  }
  document.querySelector('.summary-view .ai-job-bar')?.classList.add('hidden')
}

function toggleAiQuarter(id: string) {
  const i = aiQuarterIds.value.indexOf(id)
  if (i >= 0) aiQuarterIds.value.splice(i, 1)
  else aiQuarterIds.value.push(id)
}

async function generateAI() {
  // 新版走后台任务：提交即关弹窗，可继续操作，完成后顶部任务条回填
  await submitAiJob()
}

/** 旧的关闭确认已不再需要：后台任务支持随时关闭弹窗 */
function closeAiModal() {
  showAiModal.value = false
}

function fmtRange(s: string, e: string): string {
  return `${dayKeyFromIso(`${s}T00:00:00`)} ~ ${dayKeyFromIso(`${e}T00:00:00`)}`
}

/** 上一期 / 下一期 */
function shiftRange(delta: number) {
  const start = parseServerTime(periodStartIso())
  if (activeTab.value === 'quarterly') {
    start.setMonth(start.getMonth() + delta * 3)
    const q = Math.floor((start.getMonth() + 1) / 3) // 1=Jan-Mar
    const begin = new Date(start.getFullYear(), q * 3, 1)
    const stop = new Date(start.getFullYear(), q * 3 + 3, 0)
    periodStart.value = toNaive(begin)
    periodEnd.value = toNaive(stop)
  } else {
    start.setFullYear(start.getFullYear() + delta)
    periodStart.value = `${start.getFullYear()}-01-01`
    periodEnd.value = `${start.getFullYear()}-12-31`
  }
}

watch(activeTab, () => {
  defaultRange()
  loadCurrent()
  loadCharts()
  loadPptBoard()
})

watch(
  () => props.initialTab,
  (t) => {
    if (props.embedded && t && t !== activeTab.value) {
      activeTab.value = t as 'quarterly' | 'yearly'
    }
  },
)

watch([periodStart, periodEnd], () => {
  // 点选历史同步周期时只刷新图表/公栏，不再重复区间查询覆盖已载入的点选内容
  if (periodSyncFromPick) {
    periodSyncFromPick = false
    loadCharts()
    loadPptBoard()
    return
  }
  // 新建草稿重置周期：只刷新图表/公栏，保持空白表单不被回填
  if (suppressPeriodReload) {
    loadCharts()
    loadPptBoard()
    return
  }
  if (loading.value) return
  loadCurrent()
  loadCharts()
  loadPptBoard()
})

onMounted(() => {
  defaultRange()
  loadCurrent()
  loadCharts()
  loadPptBoard()
  restoreAiJob()
})

onBeforeUnmount(() => {
  stopAiPoll()
  lineChart?.dispose()
  barChart?.dispose()
})
</script>

<template>
  <div class="summary-view">
    <header v-if="!embedded" class="page-head">
      <div>
        <h1>季度 · 年度总结</h1>
        <p class="sub">基于周报数据聚合 + AI 生成总结，人工审核后生成 PPT 草稿导出</p>
      </div>
      <div class="tabs">
        <button class="tab-btn ghost-tab" @click="goReports">← 日报·周报</button>
        <button class="tab-btn" :class="{ active: activeTab === 'quarterly' }" @click="activeTab = 'quarterly'">季度总结</button>
        <button class="tab-btn" :class="{ active: activeTab === 'yearly' }" @click="activeTab = 'yearly'">年度总结</button>
      </div>
    </header>

    <!-- 右下角 Toast 栈：保存/AI/PPT/提交等操作反馈就近可见，无需回滚到页顶 -->
    <div class="toast-stack" aria-live="polite">
      <TransitionGroup name="toast">
        <div v-for="t in toasts" :key="t.id" class="toast" :class="t.kind">
          <span class="toast-icon">{{ t.kind === 'ok' ? '✓' : t.kind === 'warn' ? '!' : '×' }}</span>
          <span class="toast-msg">{{ t.msg }}</span>
          <button class="toast-close" @click="dismissToast(t.id)" title="关闭">×</button>
        </div>
      </TransitionGroup>
    </div>

    <!-- AI 后台任务条：提交后可关弹窗/切页面，完成后自动回填 -->
    <div v-if="aiJobActive || aiJobStatus === 'failed'" class="ai-job-bar" :class="aiJobStatus">
      <div class="ai-job-main">
        <span class="ai-job-dot" />
        <span v-if="aiJobActive">
          AI 正在后台生成总结草稿，已用时 {{ aiJobElapsed }} 秒（通常 20-60 秒），可继续编辑其他内容…
        </span>
        <span v-else>AI 生成失败：{{ aiJobError || '未知错误' }}</span>
      </div>
      <div class="ai-job-actions">
        <button v-if="aiJobStatus === 'failed'" class="btn ghost small" @click="dismissAiJob">关闭</button>
        <button v-else class="btn ghost small" @click="dismissAiJob">后台运行中，可忽略</button>
      </div>
    </div>

    <section class="card control-row">
      <div class="ctl-group">
        <label class="ctl-label">报告期间</label>
        <div class="period-nav">
          <button class="btn ghost" @click="shiftRange(-1)">‹ 上一期</button>
          <span class="period-label">{{ fmtRange(periodStart, periodEnd) }}</span>
          <button class="btn ghost" @click="shiftRange(1)">下一期 ›</button>
          <button class="btn ghost small" @click="defaultRange">当前期</button>
        </div>
      </div>
      <div v-if="loading" class="inline-loading">加载中…</div>
    </section>

    <!-- 统计卡 -->
    <section class="card stats-card">
      <h3>期间数据自动统计</h3>
      <div v-if="statsLoading" class="inline-loading">统计中…</div>
      <div v-else-if="stats" class="stats-grid">
        <div class="stat-box"><b>{{ stats.current_students }}</b><span>当前学员</span></div>
        <div class="stat-box"><b>{{ stats.expected_lessons }}</b><span>应耗课时</span></div>
        <div class="stat-box"><b>{{ stats.consumed_lessons }}</b><span>消耗课时</span></div>
        <div class="stat-box"><b>{{ (stats.achievement_rate * 100).toFixed(1) }}%</b><span>达标率</span></div>
        <div class="stat-box"><b>{{ stats.attended }}</b><span>上课人次</span></div>
        <div class="stat-box"><b>{{ stats.leave }}</b><span>缺课人次</span></div>
        <div class="stat-box"><b>{{ (stats.attendance_rate * 100).toFixed(1) }}%</b><span>出勤率</span></div>
        <div class="stat-box"><b>{{ stats.schedules }}</b><span>已完成排课</span></div>
        <div class="stat-box"><b>{{ stats.new_students }}</b><span>新增学员</span></div>
        <div class="stat-box"><b>{{ stats.weekly_count }}</b><span>已发布周报</span></div>
        <div v-if="activeTab === 'yearly'" class="stat-box"><b>{{ stats.quarterly_count ?? 0 }}</b><span>已纳入季度总结</span></div>
      </div>
      <p v-if="!statsLoading && stats && activeTab === 'yearly' && (stats.quarterly_count ?? 0) > 0" class="hint">年度统计已优先聚合 {{ stats.quarterly_count }} 篇已发布季度总结</p>
      <p v-if="!statsLoading && stats && activeTab === 'yearly' && (stats.quarterly_count ?? 0) === 0" class="hint">本年度暂无已发布季度总结，已回退为排课明细 / 周报口径</p>
      <p v-if="!statsLoading && !stats" class="hint">暂无统计数据（可能期间内无已完成排课）</p>
    </section>

    <!-- 折线图：每月应耗/消耗课时、新增学员、上课人次 -->
    <section class="card chart-card">
      <h3>月度趋势</h3>
      <p class="chart-tip">应耗课时 / 消耗课时 / 新增学员 / 上课人次 逐月变化</p>
      <div ref="lineChartEl" class="chart"></div>
      <p v-if="!monthlyData.length" class="hint">期间内暂无按月的排课数据</p>
    </section>

    <!-- 柱状图：当前期间 vs 上一对等期间课时消耗对比 -->
    <section class="card chart-card">
      <h3>课时消耗对比</h3>
      <p class="chart-tip">
        本{{ activeTab === 'quarterly' ? '季度' : '年度' }} 与
        {{ activeTab === 'quarterly' ? '上季度' : '上一年' }} 各月消耗课时对比
      </p>
      <div ref="barChartEl" class="chart"></div>
      <p v-if="!comparisonData?.labels?.length" class="hint">暂无对比数据</p>
    </section>

    <!-- 编辑表单 -->
    <section class="card editor-card">
      <div class="editor-head">
        <h3>{{ activeTab === 'quarterly' ? '季度' : '年度' }}总结内容</h3>
        <div v-if="report" class="status">
          <span class="status-pill" :class="report.status === 'published' ? 'done' : 'draft'">
            {{ report.status === 'published' ? '已提交' : '草稿' }}
          </span>
        </div>
        <button class="btn ghost small" @click="requestNewBlankDraft" title="回到当前期间，新建空白草稿">
          新建草稿
        </button>
      </div>

      <label class="field">
        标题
        <input v-model="form.title" type="text" placeholder="如：2026年第三季度 工作总结" maxlength="160" />
      </label>
      <label v-for="f in fields" :key="f.key" class="field">
        {{ f.label }}
        <textarea v-autogrow v-model="form.fields[f.key]" rows="4" :placeholder="f.placeholder" />
      </label>

      <div class="actions">
        <button class="btn ghost" @click="save" :disabled="saving || loading">
          {{ saving ? '保存中…' : '保存草稿' }}
        </button>
        <button class="btn ai" @click="openAI">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2l1.9 5.1L19 9l-5.1 1.9L12 16l-1.9-5.1L5 9l5.1-1.9L12 2zM19 16l.9 2.1L22 19l-2.1.9L19 22l-.9-2.1L16 19l2.1-.9L19 16z" /></svg>
          AI 总结草稿
        </button>
        <button
          class="btn ppt"
          @click="genPpt"
          :disabled="pptGenerating || !!pptBlockedReason"
          :title="pptBlockedReason || '基于已保存内容与统计生成 PPT'"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6M8 13h8M8 17h8" /></svg>
          {{ pptGenerating ? '生成中…' : '生成 PPT 草稿' }}
        </button>
        <button
          class="btn ai"
          @click="openPptBuilder"
          :disabled="!!pptBlockedReason"
          :title="pptBlockedReason || '与 AI 对话定制个性化 PPT（大纲→文案→排版→导出）'"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8z" /></svg>
          AI 定制 PPT
        </button>
        <button v-if="pptUrl" class="btn primary download">
          <a :href="pptDownloadUrl(pptUrl)" target="_blank" rel="noopener">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3" /></svg>
            下载/预览 PPT
          </a>
        </button>
        <button class="btn primary" @click="publish" :disabled="publishing || report?.status === 'published'">
          {{ report?.status === 'published' ? '已提交' : '提交总结' }}
        </button>
        <button v-if="report?.status === 'published'" class="btn ghost" @click="unpublish">撤回重新编辑</button>
      </div>
    </section>

    <!-- 历史列表 -->
    <section v-if="history.length" class="card history-card">
      <h3>历史记录</h3>
      <div class="history-list">
        <div
          v-for="r in history"
          :key="r.id"
          class="history-item clickable"
          :class="{ current: editingHistoryId === r.id }"
          @click="openHistorySummary(r)"
          title="点击载入编辑器查看 / 继续编辑"
        >
          <div class="history-title">
            {{ r.title || (r.type === 'quarterly' ? '季度总结' : '年度总结') }}
            <span class="status-pill" :class="r.status === 'published' ? 'done' : 'draft'">
              {{ r.status === 'published' ? '已提交' : '草稿' }}
            </span>
            <span v-if="editingHistoryId === r.id" class="status-pill editing">编辑中</span>
          </div>
          <div class="history-meta">{{ fmtRange(dayKeyFromIso(r.period_start), dayKeyFromIso(r.period_end)) }} · {{ r.teacher_name }}</div>
          <button
            class="history-del"
            title="删除该报告"
            :disabled="deletingId === r.id"
            @click.stop="removeReport(r)"
          >
            {{ deletingId === r.id ? '删除中…' : '删除' }}
          </button>
        </div>
      </div>
      <PaginationBar
        v-if="historyTotal > historyLimit"
        :total="historyTotal"
        :page="historyPage"
        :page-size="historyLimit"
        @update:page="(p: number) => { historyOffset = (p - 1) * historyLimit; loadHistory(); }"
      />
    </section>

    <!-- PPT 公栏：全部教师已提交发布的季度/年度总结（含 PPT） -->
    <section class="card ppt-board-card">
      <h3>PPT 公栏</h3>
      <p class="chart-tip">全体教师已提交发布的{{ activeTab === 'quarterly' ? '季度' : '年度' }}总结（PPT），教师只可编辑自己的，其余仅可查看。</p>
      <div v-if="pptBoardLoading" class="inline-loading">加载中…</div>
      <div v-else-if="pptBoard.length" class="history-list">
        <div v-for="r in pptBoard" :key="r.id" class="history-item ppt-item">
          <div class="history-main">
            <div class="history-title">
              <svg class="ppt-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6M8 13h8M8 17h8" /></svg>
              {{ r.title || (r.type === 'quarterly' ? '季度总结' : '年度总结') }}
              <span class="status-pill done">已提交</span>
            </div>
            <div class="history-meta">
              {{ fmtRange(dayKeyFromIso(r.period_start), dayKeyFromIso(r.period_end)) }}
              · {{ r.teacher_name }}
              <template v-if="r.campus"> · {{ r.campus }}</template>
            </div>
          </div>
          <div class="ppt-actions">
            <a
              v-if="r.ppt_url"
              class="btn download ppt-dl"
              :href="pptDownloadUrl(r.ppt_url)"
              target="_blank"
              rel="noopener"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3" /></svg>
              查看 PPT
            </a>
            <span v-else class="hint">未生成 PPT</span>
            <button
              v-if="r.teacher_id === auth.user?.id"
              class="btn ghost small"
              @click="openOwnSummary(r)"
            >
              编辑我的总结
            </button>
            <button
              v-if="r.teacher_id === auth.user?.id || isAdminStaff"
              class="btn ghost small danger-ghost"
              :disabled="deletingId === r.id"
              @click="removeReport(r)"
            >
              {{ deletingId === r.id ? '删除中…' : '删除' }}
            </button>
          </div>
        </div>
      </div>
      <p v-else-if="!pptBoardLoading" class="hint">暂无已提交发布的总结 PPT</p>
      <PaginationBar
        v-if="pagerVisible()"
        :total="pptBoardTotal"
        :page="pptBoardPage"
        :page-size="pptBoardLimit"
        @update:page="(p: number) => { pptBoardPage = p; loadPptBoard(); }"
      />
    </section>

    <!-- AI 弹窗：提交即进后台任务，可随时关闭 -->
    <div v-if="showAiModal" class="overlay" @click.self="closeAiModal">
      <div class="modal ai-modal">
        <h2>AI 生成{{ activeTab === 'quarterly' ? '季度' : '年度' }}总结</h2>
        <p class="batch-hint">
          {{ activeTab === 'yearly'
            ? 'AI 将基于所选季度总结综合提炼年度草稿，回填表单，请审核修改后保存。'
            : 'AI 将基于期间统计数据与已发布周报摘要生成总结草稿，回填表单，请审核修改后保存。' }}
          提交后可在后台生成（约 20-60 秒），关闭弹窗不影响，可继续处理其他工作。
        </p>
        <div v-if="activeTab === 'yearly'" class="quarter-pick">
          <div class="quarter-pick-head">
            <span>选用季度总结（{{ aiQuartersFromYear }}年已发布，默认全选 · 已选 {{ aiQuarterIds.length }}/{{ aiQuarters.length }}）</span>
            <span v-if="aiQuartersLoading" class="hint">加载中…</span>
            <span v-else-if="aiQuarters.length" class="quarter-batch">
              <button class="link-btn" @click="selectAllAiQuarters">全选</button>
              <button class="link-btn" @click="clearAiQuarters">清空</button>
            </span>
          </div>
          <div v-if="!aiQuartersLoading && aiQuarters.length" class="quarter-list">
            <label v-for="q in aiQuarters" :key="q.id" class="quarter-item">
              <input
                type="checkbox"
                :checked="aiQuarterIds.includes(q.id)"
                @change="toggleAiQuarter(q.id)"
              />
              <span class="quarter-check" :class="{ on: aiQuarterIds.includes(q.id) }">✓</span>
              <span class="quarter-main">
                <span class="quarter-title">{{ q.title || '季度总结' }}</span>
                <span class="quarter-meta">{{ fmtRange(dayKeyFromIso(q.period_start), dayKeyFromIso(q.period_end)) }}</span>
              </span>
              <span v-if="q.status !== 'published'" class="status-pill draft">草稿</span>
            </label>
          </div>
          <p v-else-if="!aiQuartersLoading" class="hint">
            本年度暂无已发布季度总结，将回退为周报口径生成，建议先完善各季度总结。
          </p>
        </div>
        <label v-if="aiTemplates.length" class="ai-tpl-label">
          提示词模板（日报 / 周报 / 季度 / 年度共用库）
          <span class="ai-tpl-row">
            <select v-model="aiTemplateId">
              <option v-for="t in aiTemplates" :key="t.id" :value="t.id">
                {{ t.name }}{{ t.scope === 'system' ? '（系统）' : t.scope === 'published' ? '（全校）' : '（我的）' }}
              </option>
            </select>
            <button class="tpl-manage-btn" type="button" @click="showTplManage = true" title="新建 / 编辑总结模板（含季度·年度预设）">⚙ 管理模板</button>
          </span>
        </label>
        <button v-else class="tpl-manage-btn" type="button" @click="showTplManage = true">⚙ 管理总结模板（季度 / 年度预设在此）</button>
        <label>
          补充说明（可选）
          <textarea v-autogrow v-model="aiNote" rows="3" placeholder="想强调的重点、遗漏事项等…" />
        </label>
        <p v-if="aiError" class="banner error">{{ aiError }}</p>
        <div class="modal-actions">
          <button class="btn ghost" @click="closeAiModal">取消</button>
          <button class="btn primary" @click="generateAI">
            生成总结草稿
          </button>
        </div>
      </div>
    </div>

    <!-- PPT 要点勾选弹窗：只选要入页的条目（数字类自动走表/图，不在此勾选） -->
    <div v-if="showPptModal" class="overlay" @click.self="showPptModal = false">
      <div class="modal ppt-modal">
        <h2>选择 PPT 入页要点</h2>
        <p class="batch-hint">
          勾选要放进 PPT 的条目（默认全选）。数字类内容自动进表格与图表，无需勾选；
          总体情况与数据说明整段入页，也不在此勾选。
        </p>
        <div v-for="g in pptPick" :key="g.key" class="ppt-pick-group">
          <div class="ppt-pick-head">
            <span>{{ g.label }}（已选 {{ g.items.filter((x) => x.checked).length }}/{{ g.items.length }}）</span>
            <span class="quarter-batch">
              <button class="link-btn" @click="setPptPickAll(g.key, true)">全选</button>
              <button class="link-btn" @click="setPptPickAll(g.key, false)">清空</button>
            </span>
          </div>
          <p v-if="!g.items.length" class="hint">该字段为空，不会生成对应页</p>
          <div v-else class="quarter-list">
            <label v-for="it in g.items" :key="it.idx" class="quarter-item">
              <input type="checkbox" :checked="it.checked" @change="togglePptPick(g.key, it.idx)" />
              <span class="quarter-main">
                <span class="quarter-title">{{ it.text }}</span>
              </span>
            </label>
          </div>
        </div>
        <div class="modal-actions">
          <button class="btn ghost" @click="showPptModal = false">取消</button>
          <button class="btn primary" @click="confirmGenPpt" :disabled="pptGenerating">
            {{ pptGenerating ? '生成中…' : '确认生成 PPT' }}
          </button>
        </div>
      </div>
    </div>

    <!-- PPT 生成结果弹窗：成功 / 失败都有明确提示 -->
    <ConfirmDialog
      :visible="showPptResult"
      :title="pptResult?.ok ? 'PPT 生成成功' : 'PPT 生成失败'"
      :message="pptResult?.message ?? ''"
      :confirm-text="pptResult?.ok ? '去下载/预览' : '知道了'"
      :cancel-text="pptResult?.ok ? '稍后' : undefined"
      @confirm="confirmPptResult"
      @cancel="showPptResult = false"
    />

    <!-- AI 草稿生成成功弹窗 -->
    <ConfirmDialog
      :visible="showAiDone"
      title="AI 草稿已生成"
      :message="aiDoneMsg"
      confirm-text="知道了"
      @confirm="showAiDone = false"
      @cancel="showAiDone = false"
    />

    <!-- 新建草稿二次确认：编辑器有未保存改动时提示 -->
    <ConfirmDialog
      :visible="showNewDraftConfirm"
      title="新建空白草稿？"
      message="当前编辑器有未保存的改动，新建草稿会清空这些内容。确认继续吗？"
      confirm-text="新建草稿"
      danger
      @confirm="showNewDraftConfirm = false; newBlankDraft()"
      @cancel="showNewDraftConfirm = false"
    />

    <!-- 对话式 PPT 定制抽屉：大纲 → 文案 → 排版 → 导出 -->
    <PptBuilderDrawer
      :visible="showPptBuilder"
      :report-id="report?.id ?? ''"
      :report-title="form.title || report?.title || '工作总结'"
      :period-label="fmtRange(periodStart, periodEnd)"
      @close="showPptBuilder = false"
      @built="onPptBuilt"
    />
    <PromptTemplateManager
      :visible="showTplManage"
      scene="report"
      title="总结提示词模板管理"
      @close="showTplManage = false"
      @changed="loadAiTemplates"
    />
  </div>
</template>

<style scoped>
.page-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
  flex-wrap: wrap;
}
.page-head h1 {
  font-size: 22px;
  margin: 0 0 4px;
}
.sub {
  color: var(--ink-3);
  font-size: 13px;
  margin: 0;
}
.tabs {
  display: flex;
  gap: 6px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 4px;
}
.tab-btn {
  border: none;
  background: transparent;
  padding: 7px 18px;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 600;
  color: var(--ink-2);
  cursor: pointer;
}
.tab-btn.ghost-tab {
  border: 1px dashed var(--line);
}
.tab-btn.active {
  background: linear-gradient(135deg, #6366f1, #06b6d4);
  color: #fff;
  box-shadow: 0 3px 12px rgba(99, 102, 241, 0.35);
}
.card {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 16px;
  padding: 20px 22px;
  margin-bottom: 16px;
}
.control-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}
.ctl-group {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.ctl-label {
  font-weight: 600;
  font-size: 13.5px;
  color: var(--ink-2);
}
.period-nav {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.period-label {
  font-size: 14px;
  font-weight: 600;
  min-width: 220px;
  text-align: center;
  white-space: nowrap;
}
.inline-loading {
  color: var(--ink-3);
  font-size: 13px;
}
.toast-stack {
  position: fixed;
  right: 20px;
  bottom: 20px;
  z-index: 1200;
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-width: min(420px, calc(100vw - 40px));
}
.toast {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px 12px 12px 14px;
  border-radius: 12px;
  font-size: 13.5px;
  line-height: 1.5;
  background: #fff;
  box-shadow: 0 12px 32px rgba(15, 23, 42, 0.18);
  border: 1px solid var(--line);
  border-left-width: 4px;
}
.toast.ok { border-left-color: var(--success); }
.toast.warn { border-left-color: #f59e0b; }
.toast.error { border-left-color: var(--danger); }
.toast-icon {
  flex: none;
  width: 22px;
  height: 22px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 700;
  margin-top: 1px;
}
.toast.ok .toast-icon { background: var(--success-soft); color: var(--success); }
.toast.warn .toast-icon { background: #fef3c7; color: #b45309; }
.toast.error .toast-icon { background: var(--danger-soft); color: var(--danger); }
.toast-msg { flex: 1; color: var(--ink); word-break: break-word; }
.toast-close {
  flex: none;
  border: none;
  background: transparent;
  color: var(--ink-3);
  font-size: 16px;
  line-height: 1;
  cursor: pointer;
  padding: 2px 4px;
  border-radius: 6px;
}
.toast-close:hover { background: var(--bg-soft, #f1f5f9); color: var(--ink); }
.toast-enter-active, .toast-leave-active { transition: all 0.25s ease; }
.toast-enter-from, .toast-leave-to { opacity: 0; transform: translateY(12px) scale(0.98); }
.banner {
  padding: 10px 14px;
  border-radius: 10px;
  font-size: 13px;
  margin: 0 0 14px;
}
.banner.error {
  background: var(--danger-soft);
  color: var(--danger);
  border: 1px solid #fecaca;
}
.banner.ok {
  background: var(--success-soft);
  color: var(--success);
  border: 1px solid #a7f3d0;
}
.stats-card h3,
.editor-card h3,
.history-card h3 {
  font-size: 15px;
  margin: 0 0 14px;
}
.history-del {
  position: absolute;
  right: 14px;
  top: 50%;
  transform: translateY(-50%);
  border: 1px solid #fecaca;
  background: #fff;
  color: var(--danger, #dc2626);
  border-radius: 8px;
  padding: 4px 10px;
  font-size: 12.5px;
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.15s;
}
.history-item:hover .history-del { opacity: 1; }
.history-del:disabled { opacity: 1; cursor: default; color: var(--ink-3); border-color: var(--line); }
.danger-ghost { color: var(--danger, #dc2626); border-color: #fecaca; }
.stats-grid {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 12px;
}
.stat-box {
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  background: var(--surface);
}
.stat-box b {
  font-size: 20px;
  color: var(--brand-strong);
}
.stat-box span {
  font-size: 12px;
  color: var(--ink-3);
}
.stat-box.wide {
  grid-column: span 2;
}
.hint {
  color: var(--ink-3);
  font-size: 13px;
}
.editor-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.status-pill {
  font-size: 11.5px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 999px;
}
.status-pill.done {
  background: var(--success-soft);
  color: var(--success);
}
.status-pill.draft {
  background: #fef3c7;
  color: #b45309;
}
.field {
  display: block;
  margin-bottom: 14px;
  font-size: 13px;
  color: var(--ink-2);
  font-weight: 500;
}
.field input,
.field textarea {
  display: block;
  width: 100%;
  box-sizing: border-box;
  margin-top: 6px;
  padding: 9px 11px;
  border: 1px solid var(--line);
  border-radius: 10px;
  font-size: 14px;
  font-family: inherit;
  transition: all 0.15s;
}
.field input:focus,
.field textarea:focus {
  outline: none;
  border-color: var(--brand);
  box-shadow: 0 0 0 3px var(--brand-soft);
}
.field textarea {
  resize: vertical;
}
.actions {
  display: flex;
  gap: 10px;
  justify-content: flex-end;
  margin-top: 20px;
  flex-wrap: wrap;
}
.history-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.history-item {
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 12px 14px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  position: relative;
}
.history-item.clickable {
  cursor: pointer;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.history-item.clickable:hover {
  border-color: var(--brand);
  box-shadow: 0 2px 10px rgba(99, 102, 241, 0.15);
}
.history-item.current {
  border-color: var(--brand);
  box-shadow: 0 0 0 3px var(--brand-soft);
}
.status-pill.editing {
  background: #ede9fe;
  color: #7c3aed;
}
.history-title {
  font-weight: 600;
  font-size: 13.5px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.history-meta {
  color: var(--ink-3);
  font-size: 12.5px;
}
.overlay {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.5);
  backdrop-filter: blur(3px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 50;
}
.modal {
  background: var(--surface);
  border-radius: 16px;
  padding: 26px;
  box-shadow: var(--shadow-lg);
  width: 460px;
  max-width: calc(100vw - 40px);
}
.modal h2 {
  font-size: 18px;
  margin-bottom: 8px;
}
.batch-hint {
  color: var(--ink-3);
  font-size: 12.5px;
  margin-bottom: 16px;
}
.modal label {
  display: block;
  margin-bottom: 14px;
  font-size: 13px;
  color: var(--ink-2);
  font-weight: 500;
}
.modal textarea {
  display: block;
  width: 100%;
  box-sizing: border-box;
  margin-top: 6px;
  padding: 9px 11px;
  border: 1px solid var(--line);
  border-radius: 10px;
  font-size: 14px;
  font-family: inherit;
  resize: vertical;
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 20px;
}
.ai-job-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 14px;
  border-radius: 10px;
  font-size: 13px;
  margin: 0 0 14px;
  background: #eef2ff;
  border: 1px solid #c7d2fe;
  color: #4338ca;
}
.ai-job-bar.failed {
  background: var(--danger-soft);
  border-color: #fecaca;
  color: var(--danger);
}
.ai-job-bar.hidden {
  display: none;
}
.ai-job-main {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
}
.ai-job-dot {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: #6366f1;
  animation: ai-pulse 1.2s ease-in-out infinite;
  flex-shrink: 0;
}
.ai-job-bar.failed .ai-job-dot {
  background: var(--danger);
  animation: none;
}
@keyframes ai-pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.4; transform: scale(0.8); }
}
.ai-job-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}
.ppt-modal {
  width: 560px;
}
.ppt-pick-group {
  margin-bottom: 14px;
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 10px 12px;
  background: #fafaff;
}
.ppt-pick-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--ink-2);
  margin-bottom: 8px;
  flex-wrap: wrap;
}
.quarter-pick {
  margin-bottom: 14px;
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 10px 12px;
  background: #fafaff;
}
.quarter-pick-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--ink-2);
  margin-bottom: 8px;
  flex-wrap: wrap;
}
.quarter-batch {
  display: inline-flex;
  gap: 6px;
}
.link-btn {
  border: none;
  background: none;
  color: #6366f1;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  padding: 0 2px;
}
.ai-tpl-label {
  display: block;
}
.ai-tpl-row {
  display: flex;
  gap: 8px;
  margin-top: 6px;
}
.ai-tpl-row select {
  flex: 1;
  min-width: 0;
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 8px 10px;
  font-size: 13px;
  font-family: inherit;
}
.tpl-manage-btn {
  flex-shrink: 0;
  border: none;
  border-radius: 999px;
  padding: 8px 14px;
  font-size: 12.5px;
  font-weight: 700;
  color: #fff;
  background: linear-gradient(135deg, #6366f1, #06b6d4);
  cursor: pointer;
  white-space: nowrap;
}
.tpl-manage-btn:hover {
  filter: brightness(1.06);
}
.link-btn:hover {
  text-decoration: underline;
}
.quarter-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 240px;
  overflow-y: auto;
}
.quarter-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  cursor: pointer;
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 7px 10px;
  background: var(--surface);
}
.quarter-item input {
  width: 15px;
  height: 15px;
  accent-color: #6366f1;
  flex-shrink: 0;
}
.quarter-check {
  display: none;
  width: 16px;
  color: #6366f1;
  font-weight: 700;
  flex-shrink: 0;
}
.quarter-main {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.quarter-title {
  font-weight: 600;
  color: var(--ink-1);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.quarter-meta {
  color: var(--ink-3);
  font-size: 12px;
}
.btn {
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--ink-2);
  font-size: 13.5px;
  font-weight: 600;
  padding: 9px 16px;
  border-radius: 10px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  transition: all 0.15s;
}
.btn svg {
  width: 14px;
  height: 14px;
}
.btn:hover {
  border-color: var(--brand);
  color: var(--brand-strong);
}
.btn.primary {
  background: linear-gradient(135deg, #6366f1, #06b6d4);
  color: #fff;
  border-color: transparent;
}
.btn.primary:hover {
  filter: brightness(1.05);
}
.btn.ai {
  background: #f5f3ff;
  border-color: #c4b5fd;
  color: #7c3aed;
}
.btn.ai:hover {
  background: #ede9fe;
}
.btn.ppt {
  background: #ecfeff;
  border-color: #67e8f9;
  color: #0e7490;
}
.btn.ppt:hover {
  background: #cffafe;
}
.btn.small {
  padding: 7px 12px;
  font-size: 12.5px;
}
.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.btn.download a {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: inherit;
  text-decoration: none;
}
.chart-card h3,
.ppt-board-card h3 {
  font-size: 15px;
  margin: 0 0 4px;
}
.chart-tip {
  color: var(--ink-3);
  font-size: 12.5px;
  margin: 0 0 12px;
}
.chart {
  width: 100%;
  height: 300px;
}
.ppt-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.ppt-item .history-main {
  min-width: 0;
}
.ppt-icon {
  width: 15px;
  height: 15px;
  color: #0e7490;
  flex-shrink: 0;
}
.ppt-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
.ppt-dl {
  text-decoration: none;
  color: #0e7490;
  border-color: #67e8f9;
  background: #ecfeff;
  white-space: nowrap;
}
.ppt-dl:hover {
  background: #cffafe;
  border-color: #22d3ee;
}
@media (max-width: 1100px) {
  .stats-grid {
    grid-template-columns: repeat(3, 1fr);
  }
  .stat-box.wide {
    grid-column: span 3;
  }
}
</style>