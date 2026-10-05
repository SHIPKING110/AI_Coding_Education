<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { listCampusesApi, listTeachersApi, type UserOut } from '@/api/auth'
import {
  boardStats,
  createAiDraftJob,
  createReport,
  dailyStatsPreview,
  getAiDraftJob,
  getReport,
  listBoardReports,
  listReports,
  publishReport,
  unpublishReport,
  updateReport,
  weeklyStatsPreview,
  type DailyStatsOut,
  type ReportBoardItemOut,
  type ReportBoardStatsOut,
  type ReportOut,
  type ReportType,
  type WeeklyStatsOut,
} from '@/api/report'
import { toastApiError } from '@/stores/toast'
import { useAuthStore } from '@/stores/auth'
import PageHead from '@/components/PageHead.vue'
import SearchableSelect from '@/components/SearchableSelect.vue'
import PaginationBar from '@/components/PaginationBar.vue'
import SummaryView from '@/views/reports/SummaryView.vue'
import {
  addDays,
  dayKey,
  fmtDateTimeFromIso,
  mondayOf,
  toLocalNaiveIso,
} from '@/utils/date'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

// —— Tab 切换：日报 / 周报 / 季度总结 / 年度总结 / 公栏 ——
type Tab = ReportType | 'board'
type SummaryTab = 'quarterly' | 'yearly'
function parseInitialTab(): Tab | SummaryTab {
  const t = route.query.tab
  // 兼容老链接 ?tab=summary（上一版聚合 Tab）→ 季度总结
  if (t === 'quarterly' || t === 'yearly' || t === 'summary') return t === 'summary' ? 'quarterly' : t
  if (t === 'board' || t === 'weekly') return t
  return 'daily'
}
const activeTab = ref<Tab | SummaryTab>(parseInitialTab())
const isSummaryTab = computed(
  () => activeTab.value === 'quarterly' || activeTab.value === 'yearly',
)

// 当前登录教师姓名（用于默认标题 “日期 + 类型 + 姓名”）
const teacherName = computed(() => auth.user?.name?.trim() ?? '')

/** 默认标题：日报 “9月18日 日报 张三”；周报 “9月15日~21日 周报 张三”（同月省略后段月份） */
function defaultReportTitle(): string {
  const name = teacherName.value ? ` ${teacherName.value}` : ''
  if (activeTab.value === 'daily') {
    const d = day.value
    return `${d.getMonth() + 1}月${d.getDate()}日 日报${name}`
  }
  if (activeTab.value === 'weekly') {
    const s = weekStart.value
    const e = addDays(s, 6)
    const range =
      s.getMonth() === e.getMonth()
        ? `${s.getMonth() + 1}月${s.getDate()}日~${e.getDate()}日`
        : `${s.getMonth() + 1}月${s.getDate()}日~${e.getMonth() + 1}月${e.getDate()}日`
    return `${range} 周报${name}`
  }
  return ''
}

// —— 周期选择 ——
const day = ref(new Date())
const weekStart = ref(mondayOf(new Date()))
const periodStart = computed(() =>
  activeTab.value === 'daily' ? toLocalNaiveIso(day.value) : toLocalNaiveIso(weekStart.value),
)
const periodEnd = computed(() =>
  activeTab.value === 'daily'
    ? toLocalNaiveIso(day.value)
    : toLocalNaiveIso(addDays(weekStart.value, 6)),
)

// —— 当前周期报告（幂等创建=更新） ——
const report = ref<ReportOut | null>(null)
const form = ref<{ title: string; fields: Record<string, string> }>({
  title: '',
  fields: {},
})
const loading = ref(false)
const saving = ref(false)
const publishing = ref(false)
const error = ref('')
const notice = ref('')

// 不同报告类型的表单字段与标签
const FIELD_MAP: Record<ReportType, { key: string; label: string; placeholder: string }[]> = {
  daily: [
    { key: 'work', label: '今日工作', placeholder: '概括今天完成的工作…' },
    { key: 'courses', label: '授课情况', placeholder: '今天上了哪些课、学员表现、进度…' },
    { key: 'problems', label: '问题与处理', placeholder: '遇到的问题及解决办法（没有填“无”）…' },
    { key: 'plan', label: '明日计划', placeholder: '明天的安排 / 待办…' },
  ],
  weekly: [
    { key: 'summary', label: '本周总结', placeholder: '概括本周整体工作情况…' },
    { key: 'highlights', label: '本周亮点', placeholder: '值得记录的亮点、进步…' },
    { key: 'problems', label: '问题与改进', placeholder: '客观指出问题并给改进建议…' },
    { key: 'next_plan', label: '下周计划', placeholder: '下周的安排 / 目标…' },
  ],
  quarterly: [],
  yearly: [],
}
const fields = computed<{ key: string; label: string; placeholder: string }[]>(() => {
  if (activeTab.value === 'board' || isSummaryTab.value) return []
  return FIELD_MAP[activeTab.value as ReportType]
})

// —— 周报/日报自动统计预览 ——
const weeklyStats = ref<WeeklyStatsOut | null>(null)
const dailyStats = ref<DailyStatsOut | null>(null)
const statsLoading = ref(false)

// —— 历史列表 ——
const history = ref<ReportOut[]>([])
const historyTotal = ref(0)
const historyOffset = ref(0)
const historyLimit = 10

// —— AI 草稿弹窗（后台任务：提交即关弹窗，完成后顶部任务条回填，不锁页面） ——
const showAiModal = ref(false)
const aiNote = ref('')
const aiError = ref('')
const aiJobStatus = ref<'idle' | 'pending' | 'running' | 'succeeded' | 'failed'>('idle')
const aiJobElapsed = ref(0)
const aiJobError = ref('')
const aiJobActive = computed(() => aiJobStatus.value === 'pending' || aiJobStatus.value === 'running')
const aiJobTimer = { poll: null as ReturnType<typeof setInterval> | null, tick: null as ReturnType<typeof setInterval> | null }
const AI_JOB_KEY = 'reports-ai-job'

function stopAiJobTimers() {
  if (aiJobTimer.poll) clearInterval(aiJobTimer.poll)
  if (aiJobTimer.tick) clearInterval(aiJobTimer.tick)
  aiJobTimer.poll = null
  aiJobTimer.tick = null
}

function persistAiJob(jobId: string, reportId: string) {
  try {
    localStorage.setItem(AI_JOB_KEY, JSON.stringify({ jobId, reportId, tab: activeTab.value }))
  } catch { /* 忽略存储异常 */ }
}

function clearAiJobState() {
  stopAiJobTimers()
  aiJobStatus.value = 'idle'
  aiJobElapsed.value = 0
  aiJobError.value = ''
  try {
    localStorage.removeItem(AI_JOB_KEY)
  } catch { /* 忽略存储异常 */ }
}

/** 轮询任务状态：成功且仍是当前报告时回填，否则提示去历史记录查看 */
async function pollDailyWeeklyAiJob() {
  let raw: string | null = null
  try {
    raw = localStorage.getItem(AI_JOB_KEY)
  } catch { /* 忽略 */ }
  if (!raw) {
    clearAiJobState()
    return
  }
  let jobId = ''
  let reportId = ''
  try {
    ({ jobId, reportId } = JSON.parse(raw))
  } catch {
    clearAiJobState()
    return
  }
  if (!jobId || !reportId) {
    clearAiJobState()
    return
  }
  try {
    const st = await getAiDraftJob(reportId, jobId)
    aiJobStatus.value = st.status
    aiJobElapsed.value = Math.floor(st.elapsed_seconds ?? aiJobElapsed.value)
    if (st.status === 'succeeded') {
      if (report.value && report.value.id === reportId) {
        if (st.title) form.value.title = st.title
        const c = st.content ?? {}
        for (const f of fields.value) {
          const v = c[f.key]
          if (v) form.value.fields[f.key] = v
        }
        showNotice('AI 报告草稿已生成，请编辑后保存')
      } else {
        showNotice('AI 报告草稿已生成，请在历史记录中打开对应报告查看')
      }
      clearAiJobState()
    } else if (st.status === 'failed') {
      aiJobError.value = st.error || 'AI 报告生成失败'
      showError(st.error || 'AI 报告生成失败')
      stopAiJobTimers()
      aiJobStatus.value = 'failed'
    }
  } catch {
    stopAiJobTimers()
    aiJobError.value = 'AI 任务已过期或查询失败，请重新生成'
  }
}

function startAiJobTimers() {
  stopAiJobTimers()
  aiJobTimer.tick = setInterval(() => {
    aiJobElapsed.value += 1
  }, 1000)
  aiJobTimer.poll = setInterval(pollDailyWeeklyAiJob, 3000)
  void pollDailyWeeklyAiJob()
}

/** 恢复未完成的 AI 任务（刷新/切页面回来继续等结果） */
function restoreDailyWeeklyAiJob() {
  let raw: string | null = null
  try {
    raw = localStorage.getItem(AI_JOB_KEY)
  } catch { return }
  if (!raw) return
  try {
    const { jobId, reportId } = JSON.parse(raw)
    if (!jobId || !reportId) return
    aiJobStatus.value = 'pending'
    aiJobElapsed.value = 0
    aiJobError.value = ''
    startAiJobTimers()
  } catch { clearAiJobState() }
}

/** 关闭任务条显示（失败态则清除任务；运行态仅隐藏，轮询继续结果照常回填） */
function dismissDailyWeeklyAiJob() {
  if (aiJobStatus.value === 'failed') {
    clearAiJobState()
    return
  }
  document.querySelector('.reports-view .ai-job-bar')?.classList.add('hidden')
}

function showError(msg: string) {
  error.value = msg
  notice.value = ''
}
function showNotice(msg: string) {
  notice.value = msg
  error.value = ''
}

const isCurrentWeek = computed(() => {
  if (activeTab.value !== 'weekly') return false
  return dayKey(weekStart.value) === dayKey(mondayOf(new Date()))
})

// 周期选择变化（或 tab 切换）后加载对应报告与周报统计
let loadSeq = 0
// 按 id 点选历史时，loadCurrent 内会同步 day/weekStart；用该标记告诉 watch
// 这次周期变化来自点选，不再触发区间查询覆盖已载入的内容
let periodSyncFromPick = false

async function loadCurrent(reportId?: string) {
  const seq = ++loadSeq
  if (activeTab.value === 'board' || isSummaryTab.value) return
  error.value = ''
  loading.value = true
  try {
    if (reportId) {
      const r = await getReport(reportId)
      if (seq !== loadSeq) return
      report.value = r
      if (r.type === 'daily') {
        periodSyncFromPick = true
        day.value = parseLocal(dayKeyFromIso(r.period_start))
      } else if (r.type === 'weekly') {
        periodSyncFromPick = true
        weekStart.value = mondayOf(parseLocal(dayKeyFromIso(r.period_start)))
      }
    } else {
      const page = await listReports({
        type: activeTab.value as ReportType,
        start: dayKey(parseLocal(periodStart.value)),
        end: dayKey(parseLocal(periodEnd.value)),
        limit: 1,
      })
      if (seq !== loadSeq) return
      report.value = page.items[0] ?? null
    }
    if (report.value) {
      const c = report.value.content ?? {}
      form.value = {
        // 存量无标题的老数据：展示时也按默认规则补齐，保存即落库
        title: report.value.title?.trim() ? report.value.title : defaultReportTitle(),
        fields: Object.fromEntries(
          FIELD_MAP[activeTab.value as ReportType].map((f) => [f.key, (c[f.key] as string) ?? '']),
        ),
      }
    } else {
      // 新周期无报告：标题按 “日期 + 类型 + 教师姓名” 预填，教师可再改
      resetForm()
      form.value.title = defaultReportTitle()
    }
  } catch {
    showError('加载报告失败')
  } finally {
    loading.value = false
  }
  loadHistory()
  if (activeTab.value === 'daily') loadDailyStats()
  if (activeTab.value === 'weekly') loadWeeklyStats()
}

function parseLocal(iso: string): Date {
  return new Date(iso.replace('T', ' '))
}

function resetForm() {
  form.value = { title: '', fields: {} }
}

// 日报统计预览
async function loadDailyStats() {
  statsLoading.value = true
  try {
    dailyStats.value = await dailyStatsPreview({
      day: dayKey(parseLocal(periodStart.value)),
    })
  } catch {
    dailyStats.value = null
  } finally {
    statsLoading.value = false
  }
}

// 周报统计预览
async function loadWeeklyStats() {
  statsLoading.value = true
  try {
    weeklyStats.value = await weeklyStatsPreview({
      start: dayKey(parseLocal(periodStart.value)),
      end: dayKey(parseLocal(periodEnd.value)),
    })
  } catch {
    weeklyStats.value = null
  } finally {
    statsLoading.value = false
  }
}

// 历史列表
async function loadHistory() {
  if (activeTab.value === 'board' || isSummaryTab.value) return
  try {
    const page = await listReports({
      type: activeTab.value as ReportType,
      limit: historyLimit,
      offset: historyOffset.value,
    })
    history.value = page.items
    historyTotal.value = page.total
  } catch {
    history.value = []
  }
}

const historyPage = computed(() => Math.floor(historyOffset.value / historyLimit) + 1)

/** 历史记录是否正载入在编辑器中 */
function isActiveHistory(r: ReportOut): boolean {
  return report.value?.id === r.id
}

/** 点击历史记录：按 id 直接载入该条报告（避免周期查询取首条错位） */
function openHistory(r: ReportOut) {
  loadCurrent(r.id)
  requestAnimationFrame(() => {
    document.querySelector('.editor-card')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  })
}

/** 保存当前表单（幂等创建/更新），并将自动统计快照写入报告 stats */
async function save() {
  if (activeTab.value === 'board' || isSummaryTab.value) return
  const type = activeTab.value as ReportType
  const title = form.value.title.trim() || defaultReportTitle()
  const content = Object.fromEntries(
    fields.value.map((f) => [f.key, (form.value.fields[f.key] ?? '').trim()]),
  )
  saving.value = true
  error.value = ''
  try {
    // 保存前重新拉取当日/本周统计，确保提交到公栏的数据是最新的
    let stats: Record<string, unknown> | null = null
    if (type === 'daily') {
      const s = await dailyStatsPreview({ day: dayKey(parseLocal(periodStart.value)) })
      dailyStats.value = s
      stats = s as unknown as Record<string, unknown>
    } else if (type === 'weekly') {
      const s = await weeklyStatsPreview({
        start: dayKey(parseLocal(periodStart.value)),
        end: dayKey(parseLocal(periodEnd.value)),
      })
      weeklyStats.value = s
      stats = s as unknown as Record<string, unknown>
    }

    const payload = { type, period_start: periodStart.value, period_end: periodEnd.value }
    let r: ReportOut
    if (report.value) {
      r = await updateReport(report.value.id, { title, content, stats })
    } else {
      r = await createReport({ ...payload, title, content, stats })
    }
    report.value = r
    // 标题回显：空标题保存时已用默认标题落库，同步回表单
    form.value.title = r.title ?? title
    showNotice('已保存草稿（含最新统计数据）')
    loadHistory()
  } catch (e: any) {
    showError(e?.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
  }
}

async function publish() {
  if (!report.value) {
    showError('请先保存草稿，再提交报告')
    return
  }
  publishing.value = true
  error.value = ''
  try {
    report.value = await publishReport(report.value.id)
    showNotice('报告已提交/发布')
    loadHistory()
  } catch (e: any) {
    showError(e?.response?.data?.detail || '发布失败')
  } finally {
    publishing.value = false
  }
}

async function unpublish() {
  if (!report.value) return
  if (!window.confirm('确认撤回该报告为草稿？撤回后可重新编辑并再次提交。')) return
  try {
    report.value = await unpublishReport(report.value.id)
    showNotice('已撤回为草稿')
    loadHistory()
  } catch (e: any) {
    showError(e?.response?.data?.detail || '撤回失败')
  }
}

// —— AI 草稿（后台任务：提交即关弹窗，完成后顶部任务条回填，不锁页面） ——
async function openAI() {
  if (!report.value) {
    showError('请先保存草稿，再生成 AI 报告')
    return
  }
  aiNote.value = ''
  aiError.value = ''
  showAiModal.value = true
}

/** 提交 AI 后台任务：立即返回，可关弹窗/切页面，完成后轮询回填 */
async function generateAI() {
  if (!report.value) return
  if (aiJobActive.value) {
    aiError.value = '已有 AI 任务在后台生成中，请等待完成后再提交'
    return
  }
  aiError.value = ''
  try {
    const job = await createAiDraftJob(report.value.id, { extra_note: aiNote.value || null })
    aiJobStatus.value = 'pending'
    aiJobElapsed.value = 0
    aiJobError.value = ''
    persistAiJob(job.job_id, report.value.id)
    showAiModal.value = false
    document.querySelector('.reports-view .ai-job-bar')?.classList.remove('hidden')
    showNotice('AI 正在后台生成（约 20-60 秒），可继续编辑，完成后自动回填')
    startAiJobTimers()
  } catch (e: any) {
    aiError.value = e?.response?.data?.detail || 'AI 任务提交失败'
    toastApiError(e)
  }
}

// —— 公栏（全部教师已发布报告） ——
const boardItems = ref<ReportBoardItemOut[]>([])
const boardTotal = ref(0)
const boardPage = ref(1)
const boardLimit = 10
const boardLoading = ref(false)
const boardError = ref('')

// 公栏筛选：校区 / 教师（可搜索）/ 报告类型 / 日期范围（默认今天）
const boardCampuses = ref<string[]>([])
const boardCampus = ref('')
const boardTeacherOptions = ref<{ id: string; label: string }[]>([])
const boardTeacherId = ref('')
const boardType = ref<'' | 'daily' | 'weekly'>('')
const boardDateStart = ref(dayKey(new Date()))
const boardDateEnd = ref(dayKey(new Date()))

const boardStatsData = ref<ReportBoardStatsOut | null>(null)

// 公栏详情弹窗
const boardDetail = ref<ReportBoardItemOut | null>(null)
const showBoardDetail = ref(false)

async function loadBoardCampuses() {
  try {
    boardCampuses.value = await listCampusesApi()
  } catch {
    boardCampuses.value = []
  }
}

async function loadBoardTeachers() {
  try {
    const p = await listTeachersApi({ campus: boardCampus.value || undefined, limit: 500 })
    boardTeacherOptions.value = p.items.map((t: UserOut) => ({
      id: t.id,
      label: t.campus ? `${t.name}（${t.campus}）` : t.name,
    }))
    if (boardTeacherId.value && !boardTeacherOptions.value.some((o) => o.id === boardTeacherId.value)) {
      boardTeacherId.value = ''
    }
  } catch {
    boardTeacherOptions.value = []
  }
}

async function loadBoard() {
  boardLoading.value = true
  boardError.value = ''
  try {
    const q = {
      type: boardType.value || undefined,
      teacher_id: boardTeacherId.value || undefined,
      campus: boardCampus.value || undefined,
      start: boardDateStart.value ? dayKey(parseLocal(boardDateStart.value)) : undefined,
      end: boardDateEnd.value ? dayKey(parseLocal(boardDateEnd.value)) : undefined,
      limit: boardLimit,
      offset: (boardPage.value - 1) * boardLimit,
    }
    const page = await listBoardReports(q)
    boardItems.value = page.items
    boardTotal.value = page.total
  } catch {
    boardError.value = '加载公栏失败'
  } finally {
    boardLoading.value = false
  }
}

async function loadBoardStats() {
  try {
    boardStatsData.value = await boardStats({
      campus: boardCampus.value || undefined,
      start: boardDateStart.value ? dayKey(parseLocal(boardDateStart.value)) : undefined,
      end: boardDateEnd.value ? dayKey(parseLocal(boardDateEnd.value)) : undefined,
    })
  } catch {
    boardStatsData.value = null
  }
}

function boardFilterChanged() {
  boardPage.value = 1
  loadBoard()
  loadBoardStats()
}

/** 校区变化时联动刷新教师下拉（只显示该校区的教师） */
function boardCampusChanged() {
  boardTeacherId.value = ''
  loadBoardTeachers()
  boardFilterChanged()
}

function openBoardDetail(item: ReportBoardItemOut) {
  boardDetail.value = item
  showBoardDetail.value = true
}

/** 跳转到「我的日报/周报」编辑：自己的报告按 id 直接载入；他人仅查看详情 */
function editFromBoard(item: ReportBoardItemOut) {
  if (item.teacher_id !== auth.user?.id) return
  activeTab.value = item.type as 'daily' | 'weekly'
  showBoardDetail.value = false
  loadCurrent(item.id)
}

const boardTypeLabel = (t: string) => (t === 'daily' ? '日报' : t === 'weekly' ? '周报' : t === 'quarterly' ? '季度总结' : t === 'yearly' ? '年度总结' : '总结')

function dayKeyFromIso(iso: string): string {
  const d = new Date(iso.replace('T', ' '))
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

// 周导航
function shiftWeek(n: number) {
  weekStart.value = addDays(weekStart.value, n * 7)
}
function toThisWeek() {
  weekStart.value = mondayOf(new Date())
}
function onDayChange(e: Event) {
  const v = (e.target as HTMLInputElement).value
  if (v) day.value = new Date(v)
}

const historyVisible = computed(() => history.value.length > 0 || historyTotal.value > 0)

function pad2(n: number): string {
  return String(n).padStart(2, '0')
}
function fmtRange(startIso: string, endIso: string): string {
  const s = new Date(startIso.replace('T', ' '))
  const e = new Date(endIso.replace('T', ' '))
  const fmt = (d: Date) => `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`
  return s.getTime() === e.getTime() ? fmt(s) : `${fmt(s)} ~ ${fmt(e)}`
}

function syncTabQuery(t: Tab | SummaryTab) {
  const q = { ...route.query }
  if (t === 'daily') delete q.tab
  else q.tab = t
  router.replace({ query: q })
}
watch(activeTab, (t) => {
  syncTabQuery(t)
  if (t === 'board') {
    loadBoard()
    loadBoardStats()
  } else if (t === 'quarterly' || t === 'yearly') {
    // 季度/年度总结页内嵌 SummaryView（编辑器+图表+PPT 生成/公栏全功能），无需父级加载
  } else {
    loadCurrent()
  }
})
watch(periodStart, () => {
  // 点选历史同步周期时不再重复区间查询，避免覆盖已按 id 载入的内容
  if (periodSyncFromPick) {
    periodSyncFromPick = false
    return
  }
  if (activeTab.value === 'daily' || activeTab.value === 'weekly') loadCurrent()
})
onMounted(() => {
  loadBoardCampuses()
  loadBoardTeachers()
  if (activeTab.value !== 'board' && !isSummaryTab.value) loadCurrent()
  restoreDailyWeeklyAiJob()
})

onBeforeUnmount(() => {
  stopAiJobTimers()
})
</script>

<template>
  <div class="reports-view">
    <PageHead title="报告·总结" eyebrow="REPORTS" sub="日报周报与季年总结·PPT —— AI 辅助生成，人工审核后提交">
      <template #actions>
      <div class="tabs">
        <button
          class="tab-btn"
          :class="{ active: activeTab === 'daily' }"
          @click="activeTab = 'daily'"
        >
          日报
        </button>
        <button
          class="tab-btn"
          :class="{ active: activeTab === 'weekly' }"
          @click="activeTab = 'weekly'"
        >
          周报
        </button>
        <button
          class="tab-btn"
          :class="{ active: activeTab === 'quarterly' }"
          @click="activeTab = 'quarterly'"
        >
          季度总结
        </button>
        <button
          class="tab-btn"
          :class="{ active: activeTab === 'yearly' }"
          @click="activeTab = 'yearly'"
        >
          年度总结
        </button>
        <button
          class="tab-btn"
          :class="{ active: activeTab === 'board' }"
          @click="activeTab = 'board'"
        >
          公栏
        </button>
      </div>
      </template>
    </PageHead>

    <p v-if="error" class="banner error">{{ error }}</p>
    <p v-if="notice" class="banner ok">{{ notice }}</p>

    <!-- AI 后台任务条（日报/周报）：提交后可关弹窗/切页面，完成后自动回填 -->
    <div v-if="aiJobActive || aiJobStatus === 'failed'" class="ai-job-bar" :class="aiJobStatus">
      <div class="ai-job-main">
        <span class="ai-job-dot" />
        <span v-if="aiJobActive">
          AI 正在后台生成报告草稿，已用时 {{ aiJobElapsed }} 秒（通常 20-60 秒），可继续编辑其他内容…
        </span>
        <span v-else>AI 生成失败：{{ aiJobError || '未知错误' }}</span>
      </div>
      <div class="ai-job-actions">
        <button v-if="aiJobStatus === 'failed'" class="btn ghost small" @click="dismissDailyWeeklyAiJob">关闭</button>
        <button v-else class="btn ghost small" @click="dismissDailyWeeklyAiJob">后台运行中，可忽略</button>
      </div>
    </div>

    <!-- 公栏：全部教师已发布报告统一展示 -->
    <template v-if="activeTab === 'board'">
      <section class="card control-row">
        <div class="board-filters">
          <div class="filter-group">
            <label>校区</label>
            <select v-model="boardCampus" class="ctl-input" @change="boardCampusChanged">
              <option value="">全部校区</option>
              <option v-for="c in boardCampuses" :key="c" :value="c">{{ c }}</option>
            </select>
          </div>
          <div class="filter-group">
            <label>教师</label>
            <SearchableSelect
              v-model="boardTeacherId"
              :options="boardTeacherOptions"
              placeholder="全部教师"
              @update:model-value="boardFilterChanged"
            />
          </div>
          <div class="filter-group">
            <label>报告类型</label>
            <select v-model="boardType" class="ctl-input" @change="boardFilterChanged">
              <option value="">日报+周报</option>
              <option value="daily">日报</option>
              <option value="weekly">周报</option>
            </select>
          </div>
          <div class="filter-group">
            <label>日期范围</label>
            <div class="date-range">
              <input v-model="boardDateStart" type="date" @change="boardFilterChanged" />
              <span>至</span>
              <input v-model="boardDateEnd" type="date" @change="boardFilterChanged" />
            </div>
          </div>
          <div class="filter-group">
            <label>&nbsp;</label>
            <button class="btn ghost" @click="boardFilterChanged">查询</button>
          </div>
        </div>
      </section>

      <!-- 公栏统计 -->
      <section class="card stats-card">
        <h3>公栏数据统计（在职教师 · 所选日期范围）</h3>
        <div v-if="boardStatsData" class="stats-grid board-stats">
          <div class="stat-box">
            <b>{{ boardStatsData.teacher_count }}</b>
            <span>在职教师</span>
          </div>
          <div class="stat-box">
            <b>{{ boardStatsData.daily_due }}</b>
            <span>日报应提交</span>
          </div>
          <div class="stat-box">
            <b>{{ boardStatsData.daily_submitted }}</b>
            <span>日报已提交</span>
          </div>
          <div class="stat-box">
            <b>{{ boardStatsData.weekly_due }}</b>
            <span>周报应提交</span>
          </div>
          <div class="stat-box">
            <b>{{ boardStatsData.weekly_submitted }}</b>
            <span>周报已提交</span>
          </div>
        </div>
        <p v-if="!boardStatsData" class="hint">暂无统计数据</p>
      </section>

      <p v-if="boardError" class="banner error">{{ boardError }}</p>

      <!-- 公栏列表 -->
      <section class="card history-card">
        <h3>已提交报告（{{ boardTotal }} 条）</h3>
        <div v-if="boardLoading" class="inline-loading">加载中…</div>
        <div v-else-if="boardItems.length" class="history-list">
          <div v-for="r in boardItems" :key="r.id" class="board-item" @click="openBoardDetail(r)">
            <div class="history-main">
              <div class="history-title">
                {{ r.title || boardTypeLabel(r.type) }}
                <span class="status-pill done">已提交</span>
                <span class="board-type-pill" :class="r.type">{{ boardTypeLabel(r.type) }}</span>
              </div>
              <div class="history-meta">
                {{ fmtRange(r.period_start, r.period_end) }} ·
                {{ r.teacher_name }}
                <template v-if="r.campus"> · {{ r.campus }}</template>
                <template v-if="r.published_at"> · {{ fmtDateTimeFromIso(r.published_at) }} 提交</template>
              </div>
            </div>
            <div class="board-actions">
              <button
                v-if="r.teacher_id === auth.user?.id"
                class="btn ghost small"
                @click.stop="editFromBoard(r)"
              >
                编辑我的报告
              </button>
              <button class="btn ghost small" @click.stop="openBoardDetail(r)">查看</button>
            </div>
          </div>
        </div>
        <div v-else-if="!boardLoading" class="hint">该条件下暂无已提交报告</div>
      </section>

      <PaginationBar
        :total="boardTotal"
        :page="boardPage"
        :page-size="boardLimit"
        @update:page="(p: number) => { boardPage = p; loadBoard(); }"
      />

      <!-- 公栏详情弹窗 -->
      <div v-if="showBoardDetail && boardDetail" class="overlay" @click.self="showBoardDetail = false">
        <div class="modal board-modal">
          <h2>{{ boardDetail.title || boardTypeLabel(boardDetail.type) }}</h2>
          <p class="batch-hint">
            {{ boardTypeLabel(boardDetail.type) }} · {{ fmtRange(boardDetail.period_start, boardDetail.period_end) }}
            · {{ boardDetail.teacher_name }}
            <template v-if="boardDetail.campus"> · {{ boardDetail.campus }}</template>
            <template v-if="boardDetail.published_at"> · {{ fmtDateTimeFromIso(boardDetail.published_at) }} 提交</template>
          </p>
          <!-- 公栏：代入提交时的统计数据快照 -->
          <div v-if="boardDetail.stats" class="board-stats-block">
            <h4>{{ boardDetail.type === 'daily' ? '今日数据' : '本周数据' }}（提交时快照）</h4>
            <div class="stats-grid board-detail-stats">
              <div class="stat-box"><b>{{ (boardDetail.stats as any)?.schedules ?? 0 }}</b><span>排课节数</span></div>
              <div class="stat-box"><b>{{ (boardDetail.stats as any)?.expected_attendance ?? 0 }}</b><span>{{ boardDetail.type === 'daily' ? '应到学员' : '应到人次' }}</span></div>
              <div class="stat-box"><b>{{ (boardDetail.stats as any)?.attended ?? 0 }}</b><span>上课{{ boardDetail.type === 'daily' ? '学员' : '人次' }}</span></div>
              <div class="stat-box"><b>{{ (boardDetail.stats as any)?.leave ?? 0 }}</b><span>缺课人次</span></div>
              <div class="stat-box"><b>{{ (((boardDetail.stats as any)?.attendance_rate ?? 0) * 100).toFixed(1) }}%</b><span>出勤率</span></div>
              <div class="stat-box"><b>{{ (boardDetail.stats as any)?.expected_lessons ?? 0 }}</b><span>应消耗课时</span></div>
              <div class="stat-box"><b>{{ (boardDetail.stats as any)?.consumed_lessons ?? 0 }}</b><span>实际消耗课时</span></div>
              <div class="stat-box"><b>{{ (((boardDetail.stats as any)?.achievement_rate ?? 0) * 100).toFixed(1) }}%</b><span>达标率</span></div>
            </div>
            <div v-if="boardDetail.type === 'weekly'" class="board-fields compact">
              <label><span>新增学员</span><div class="readonly-field">{{ (boardDetail.stats as any)?.new_students ?? 0 }} 人</div></label>
              <label><span>缺课学员</span><div class="readonly-field">{{ (boardDetail.stats as any)?.absent_students?.length ? (boardDetail.stats as any).absent_students.join('、') : '无' }}</div></label>
            </div>
          </div>
          <div v-if="boardDetail.type === 'daily'" class="board-fields">
            <label><span>今日工作</span><div class="readonly-field">{{ (boardDetail.content as any)?.work || '—' }}</div></label>
            <label><span>授课情况</span><div class="readonly-field">{{ (boardDetail.content as any)?.courses || '—' }}</div></label>
            <label><span>问题与处理</span><div class="readonly-field">{{ (boardDetail.content as any)?.problems || '—' }}</div></label>
            <label><span>明日计划</span><div class="readonly-field">{{ (boardDetail.content as any)?.plan || '—' }}</div></label>
          </div>
          <div v-else class="board-fields">
            <label><span>本周总结</span><div class="readonly-field">{{ (boardDetail.content as any)?.summary || '—' }}</div></label>
            <label><span>本周亮点</span><div class="readonly-field">{{ (boardDetail.content as any)?.highlights || '—' }}</div></label>
            <label><span>问题与改进</span><div class="readonly-field">{{ (boardDetail.content as any)?.problems || '—' }}</div></label>
            <label><span>下周计划</span><div class="readonly-field">{{ (boardDetail.content as any)?.next_plan || '—' }}</div></label>
          </div>
          <div class="modal-actions">
            <button class="btn ghost" @click="showBoardDetail = false">关闭</button>
            <button
              v-if="boardDetail.teacher_id === auth.user?.id"
              class="btn primary"
              @click="editFromBoard(boardDetail)"
            >
              编辑我的报告
            </button>
          </div>
        </div>
      </div>
    </template>
    <!-- 季度/年度总结：内嵌 SummaryView 全功能（统计+图表+编辑器+PPT 生成/公栏，原图标与功能完整保留） -->
    <SummaryView
      v-else-if="activeTab === 'quarterly' || activeTab === 'yearly'"
      :key="activeTab"
      embedded
      :initial-tab="activeTab"
    />

    <template v-else-if="activeTab === 'daily' || activeTab === 'weekly'">
    <section class="card control-row">
      <!-- 日报：日期选择 -->
      <div v-if="activeTab === 'daily'" class="ctl-group">
        <label class="ctl-label">报告日期</label>
        <input type="date" :value="dayKey(day)" class="ctl-input" @input="onDayChange" />
        <button class="btn ghost" @click="day = new Date()">今天</button>
      </div>
      <!-- 周报：周导航 -->
      <div v-else class="ctl-group">
        <label class="ctl-label">报告周</label>
        <div class="week-nav">
          <button class="btn ghost" @click="shiftWeek(-1)">‹ 上一周</button>
          <span class="week-label">
            {{ fmtRange(periodStart, periodEnd) }}
            <template v-if="isCurrentWeek">（本周）</template>
          </span>
          <button class="btn ghost" @click="shiftWeek(1)">下一周 ›</button>
          <button class="btn ghost small" @click="toThisWeek">回到本周</button>
        </div>
      </div>
      <div v-if="loading" class="inline-loading">加载中…</div>
    </section>

    <!-- 日报自动统计（今日数据） -->
    <section v-if="activeTab === 'daily'" class="card stats-card">
      <h3>今日数据自动统计</h3>
      <div v-if="statsLoading" class="inline-loading">统计中…</div>
      <div v-else-if="dailyStats" class="stats-grid">
        <div class="stat-box"><b>{{ dailyStats.schedules }}</b><span>今日排课节数</span></div>
        <div class="stat-box"><b>{{ dailyStats.expected_attendance }}</b><span>应到学员</span></div>
        <div class="stat-box"><b>{{ dailyStats.attended }}</b><span>上课学员</span></div>
        <div class="stat-box"><b>{{ dailyStats.leave }}</b><span>缺课人次</span></div>
        <div class="stat-box"><b>{{ (dailyStats.attendance_rate * 100).toFixed(1) }}%</b><span>出勤率</span></div>
        <div class="stat-box"><b>{{ dailyStats.expected_lessons }}</b><span>应消耗课时</span></div>
        <div class="stat-box"><b>{{ dailyStats.consumed_lessons }}</b><span>实际消耗课时</span></div>
        <div class="stat-box"><b>{{ (dailyStats.achievement_rate * 100).toFixed(1) }}%</b><span>达标率</span></div>
      </div>
      <p v-if="!statsLoading && !dailyStats" class="hint">暂无统计数据</p>
    </section>

    <!-- 周报自动统计卡（FR-WR-02） -->
    <section v-if="activeTab === 'weekly'" class="card stats-card">
      <h3>本周数据自动统计</h3>
      <div v-if="statsLoading" class="inline-loading">统计中…</div>
      <div v-else-if="weeklyStats" class="stats-grid">
        <div class="stat-box"><b>{{ weeklyStats.schedules }}</b><span>本周排课节数</span></div>
        <div class="stat-box"><b>{{ weeklyStats.expected_attendance }}</b><span>应到人次</span></div>
        <div class="stat-box"><b>{{ weeklyStats.attended }}</b><span>上课人次</span></div>
        <div class="stat-box"><b>{{ weeklyStats.leave }}</b><span>缺课人次</span></div>
        <div class="stat-box"><b>{{ (weeklyStats.attendance_rate * 100).toFixed(1) }}%</b><span>出勤率</span></div>
        <div class="stat-box"><b>{{ weeklyStats.expected_lessons }}</b><span>应消耗课时</span></div>
        <div class="stat-box"><b>{{ weeklyStats.consumed_lessons }}</b><span>实际消耗课时</span></div>
        <div class="stat-box"><b>{{ (weeklyStats.achievement_rate * 100).toFixed(1) }}%</b><span>达标率</span></div>
        <div class="stat-box"><b>{{ weeklyStats.new_students }}</b><span>新增学员</span></div>
        <div class="stat-box wide">
          <b>{{ weeklyStats.absent_students.length ? weeklyStats.absent_students.join('、') : '无' }}</b>
          <span>缺课学员</span>
        </div>
      </div>
      <p v-if="!statsLoading && !weeklyStats" class="hint">暂无统计数据</p>
    </section>

    <!-- 编辑表单 -->
    <section class="card editor-card">
      <div class="editor-head">
        <h3>{{ activeTab === 'daily' ? '日报' : '周报' }}内容</h3>
        <div class="status" v-if="report">
          <span class="status-pill" :class="report.status === 'published' ? 'done' : 'draft'">
            {{ report.status === 'published' ? '已提交' : '草稿' }}
          </span>
          <span v-if="report.published_at" class="time">· {{ fmtDateTimeFromIso(report.published_at) }} 提交</span>
        </div>
      </div>

      <label class="field">
        标题
        <input v-model="form.title" type="text" placeholder="如：8月31日 工作日报 / 第35周 工作周报" maxlength="160" />
      </label>
      <label v-for="f in fields" :key="f.key" class="field">
        {{ f.label }}
        <textarea v-autogrow v-model="form.fields[f.key]" rows="4" :placeholder="f.placeholder"></textarea>
      </label>

      <div class="actions">
        <button class="btn ghost" @click="save" :disabled="saving || loading">
          {{ saving ? '保存中…' : '保存草稿' }}
        </button>
        <button class="btn ai" @click="openAI" :disabled="report === null">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2l1.9 5.1L19 9l-5.1 1.9L12 16l-1.9-5.1L5 9l5.1-1.9L12 2zM19 16l.9 2.1L22 19l-2.1.9L19 22l-.9-2.1L16 19l2.1-.9L19 16z" /></svg>
          AI 草稿
        </button>
        <button class="btn primary" @click="publish" :disabled="publishing || report?.status === 'published'">
          {{ report?.status === 'published' ? '已提交' : '提交报告' }}
        </button>
        <button
          v-if="report?.status === 'published'"
          class="btn ghost"
          @click="unpublish"
        >
          撤回重新编辑
        </button>
      </div>
    </section>

    <!-- 历史列表 -->
    <section v-if="historyVisible" class="card history-card">
      <h3>历史记录</h3>
      <div class="history-list">
        <div
          v-for="r in history"
          :key="r.id"
          class="history-item clickable"
          :class="{ current: isActiveHistory(r) }"
          @click="openHistory(r)"
          title="点击载入编辑器查看 / 继续编辑"
        >
          <div class="history-main">
            <div class="history-title">
              {{ r.title || (r.type === 'daily' ? '日报' : '周报') }}
              <span class="status-pill" :class="r.status === 'published' ? 'done' : 'draft'">
                {{ r.status === 'published' ? '已提交' : '草稿' }}
              </span>
              <span v-if="isActiveHistory(r)" class="status-pill editing">编辑中</span>
            </div>
            <div class="history-meta">
              {{ fmtRange(r.period_start, r.period_end) }} · {{ r.teacher_name }}
            </div>
          </div>
          <div class="board-actions">
            <button class="btn ghost small" @click.stop="openHistory(r)">查看 / 编辑</button>
          </div>
        </div>
      </div>
      <PaginationBar
        v-if="historyTotal > historyLimit"
        :total="historyTotal"
        :page="historyPage"
        :page-size="historyLimit"
        @update:page="(p: number) => { historyOffset = (p - 1) * historyLimit; loadHistory(); }"
      />
      <div v-if="historyTotal === 0" class="hint">暂无历史记录</div>
    </section>

    <!-- AI 草稿弹窗 -->
    <div v-if="showAiModal" class="overlay" @click.self="showAiModal = false">
      <div class="modal ai-modal">
        <h2>AI 生成{{ activeTab === 'daily' ? '日报' : '周报' }}</h2>
        <p class="batch-hint">AI 将基于{{ activeTab === 'daily' ? '今日排课/考勤' : '本周统计数据与日报' }}生成草稿，回填到表单，请审核修改后保存、提交。</p>
        <label>
          补充说明（可选）
          <textarea v-autogrow v-model="aiNote" rows="3" placeholder="想强调的重点、遗漏事项等…"></textarea>
        </label>
        <p v-if="aiError" class="banner error">{{ aiError }}</p>
        <div class="modal-actions">
          <button class="btn ghost" @click="showAiModal = false">取消</button>
          <button class="btn primary" @click="generateAI" :disabled="aiJobActive">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2l1.9 5.1L19 9l-5.1 1.9L12 16l-1.9-5.1L5 9l5.1-1.9L12 2zM19 16l.9 2.1L22 19l-2.1.9L19 22l-.9-2.1L16 19l2.1-.9L19 16z" /></svg>
            {{ aiJobActive ? `后台生成中 ${aiJobElapsed}s…` : '提交后台生成' }}
          </button>
        </div>
      </div>
    </div>
    </template>
  </div>
</template>

<style scoped>
.page-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
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
.control-row block {
  display: flex;
  align-items: center;
  gap: 10px;
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
.ctl-input {
  border: 1px solid var(--line);
  border-radius: 9px;
  padding: 8px 10px;
  font-size: 14px;
  background: var(--surface);
}
.week-nav {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.week-label {
  font-size: 14px;
  font-weight: 600;
  min-width: 180px;
  text-align: center;
}

/* —— 公栏 —— */
.board-filters {
  display: flex;
  align-items: flex-end;
  gap: 14px;
  flex-wrap: wrap;
}
.filter-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.filter-group label {
  font-size: 12px;
  color: var(--ink-3);
  font-weight: 500;
}
.date-range {
  display: flex;
  align-items: center;
  gap: 6px;
}
.date-range input {
  padding: 8px 11px;
  border: 1px solid var(--line);
  border-radius: 9px;
  font-size: 13px;
  background: var(--surface);
}
.date-range span {
  color: var(--ink-3);
  font-size: 13px;
}
.board-stats {
  grid-template-columns: repeat(5, 1fr);
}
.board-type-pill {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 999px;
  background: #e0f2fe;
  color: #0369a1;
}
.board-type-pill.weekly {
  background: #f3e8ff;
  color: #7e22ce;
}
.board-item {
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 12px 14px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  cursor: pointer;
  transition: all 0.15s;
}
.board-item:hover {
  border-color: #c7d2fe;
  box-shadow: var(--shadow-sm);
}
.board-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}
.board-fields label {
  display: block;
  margin-bottom: 12px;
  font-size: 13px;
  color: var(--ink-2);
  font-weight: 500;
}
.board-fields label > span {
  display: block;
  margin-bottom: 4px;
}
.board-fields.compact {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0 12px;
  margin-top: 4px;
}
.readonly-field {
  background: #f8fafc;
  border: 1px solid var(--line);
  border-radius: 9px;
  padding: 9px 11px;
  font-size: 13.5px;
  color: var(--ink);
  white-space: pre-wrap;
  line-height: 1.6;
}
.board-modal {
  width: 640px;
  max-width: calc(100vw - 40px);
  max-height: 86vh;
  overflow: auto;
}
.board-stats-block {
  margin: 4px 0 16px;
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 12px 14px;
  background: #f8fafc;
}
.board-stats-block h4 {
  font-size: 13px;
  margin: 0 0 10px;
  color: var(--ink-2);
}
.stats-grid.board-detail-stats {
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
}
.board-detail-stats .stat-box {
  padding: 10px;
  gap: 4px;
  background: var(--surface);
}
.board-detail-stats .stat-box b {
  font-size: 16px;
}

.inline-loading {
  color: var(--ink-3);
  font-size: 13px;
}

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
.editor-head h3 {
  margin-bottom: 6px;
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
.time {
  color: var(--ink-3);
  font-size: 12px;
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
  margin-top: 3px;
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
.btn.small {
  padding: 7px 12px;
  font-size: 12.5px;
}
.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* —— AI 后台任务条（与 SummaryView 一致） —— */
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

@media (max-width: 900px) {
  .stats-grid {
    grid-template-columns: repeat(3, 1fr);
  }
  .stat-box.wide {
    grid-column: span 3;
  }
}
</style>