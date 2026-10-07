<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import PageHead from '@/components/PageHead.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import PromptTemplateManager from '@/components/PromptTemplateManager.vue'
import EvaluationDetailDialog from '@/components/EvaluationDetailDialog.vue'
import PptAgentDialog from '@/views/evaluations/components/PptAgentDialog.vue'
import SearchableSelect from '@/components/SearchableSelect.vue'
import StudentFilter, { type StudentFilterValue } from '@/components/StudentFilter.vue'
import { listCampusesApi, listTeachersApi, type UserOut } from '@/api/auth'
import {
  getStudent,
  listClasses,
  listStudents,
  type ClassOut,
  type StudentOut,
} from '@/api/enrollment'
import {
  aiDraftEvaluation,
  aiRefineEvaluation,
  createEvaluation,
  deleteEvaluation,
  generateClassPpt,
  getClassPptFingerprint,
  getClassPptLatest,
  getClassRoster,
  getEvaluation,
  getEvaluationMaterial,
  listEvaluations,
  publishEvaluation,
  pptDownloadUrl,
  updateClassPpt,
  type ClassPptRecordOut,
  type ClassPptTaskOut,
  type ClassRosterOut,
  type ClassRosterStudentOut,
  type EvaluationAiDraftOut,
  type EvaluationMaterialOut,
  type EvaluationOut,
  type EvaluationUpdateIn,
  unpublishEvaluation,
  updateEvaluation,
} from '@/api/evaluation'
import { toastApiError } from '@/stores/toast'
import { listPromptTemplates, type PromptTemplateOut } from '@/api/prompt'
import { useAiTasksStore, type UnifiedAiTask } from '@/stores/aiTasks'
import { useAuthStore } from '@/stores/auth'
import { cleanListishText } from '@/utils/text'
import { fmtCnDateKey, fmtCnPeriod } from '@/utils/date'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const aiTasks = useAiTasksStore()

const students = ref<StudentOut[]>([])
// 学员缓存：即使当前筛选结果不含已选学员，仍能展示其信息（筛选不误删选择）
const studentCache = ref<Record<string, StudentOut>>({})
const studentId = ref('')
const periodStart = ref('')
const periodEnd = ref('')

// —— 编辑器：学员快速筛选（校区 / 教师 / 班级 / 姓名，跨端复用组件） ——
const stuFilter = ref<StudentFilterValue>({
  campus: '',
  teacherId: '',
  classId: '',
  keyword: '',
  account: '',
})
const title = ref('')
const summary = ref('')
const subjects = ref<Array<{ name: string; level: number; comment: string }>>([])
const progress = ref('')
const toImprove = ref('')
const suggestions = ref('')
const current = ref<EvaluationOut | null>(null)
const material = ref<EvaluationMaterialOut | null>(null)
const list = ref<EvaluationOut[]>([])
const listLoading = ref(false)
const loading = ref(false)
const saving = ref(false)
const message = ref('')
const error = ref('')
const aiNote = ref('')
const aiInstruction = ref('')
// 评估提示词模板（系统自带 + 个人/全校）：所选模板正文作为写作风格要求
const aiTemplates = ref<PromptTemplateOut[]>([])
const aiTemplateId = ref('')
const showTplManage = ref(false)
async function loadAiTemplates() {
  try {
    aiTemplates.value = await listPromptTemplates('evaluation')
    if (!aiTemplateId.value || !aiTemplates.value.some((t) => t.id === aiTemplateId.value)) {
      aiTemplateId.value = aiTemplates.value[0]?.id ?? ''
    }
  } catch {
    aiTemplates.value = []
  }
}
const detailEv = ref<EvaluationOut | null>(null)
const showDelete = ref(false)
const myTaskIds = ref<string[]>([])
const historyStatus = ref<'' | 'draft' | 'published'>('')

const isPublished = computed(() => current.value?.status === 'published')
/** 学员下拉候选 = 当前筛选结果 + 已选学员缓存（保证当前选择始终可见） */
const studentOptions = computed(() => {
  const seen = new Set(students.value.map((s) => s.id))
  const cached = Object.values(studentCache.value).filter((s) => !seen.has(s.id))
  return [...students.value, ...cached].map((s) => ({
    id: s.id,
    label: s.campus ? `${s.name}（${s.campus}）` : s.name,
  }))
})
const activeStudent = computed(
  () =>
    studentCache.value[studentId.value] ??
    students.value.find((s) => s.id === studentId.value) ??
    null,
)
/** 本页提交的 AI 任务还在排队/生成中 */
const aiBusy = computed(() => myTaskIds.value.length > 0)

function cacheStudent(s: StudentOut) {
  studentCache.value = { ...studentCache.value, [s.id]: s }
}

async function fetchStudents() {
  try {
    const p = await listStudents({
      keyword: stuFilter.value.keyword || undefined,
      campus:
        stuFilter.value.campus && stuFilter.value.campus !== '__unassigned__'
          ? stuFilter.value.campus
          : undefined,
      campus_unassigned: stuFilter.value.campus === '__unassigned__' || undefined,
      teacher_id:
        stuFilter.value.teacherId && stuFilter.value.teacherId !== '__unassigned__'
          ? stuFilter.value.teacherId
          : undefined,
      teacher_unassigned: stuFilter.value.teacherId === '__unassigned__' || undefined,
      class_id:
        stuFilter.value.classId && stuFilter.value.classId !== '__unassigned__'
          ? stuFilter.value.classId
          : undefined,
      class_unassigned: stuFilter.value.classId === '__unassigned__' || undefined,
      account: stuFilter.value.account || undefined,
      limit: 300,
    })
    for (const s of p.items) cacheStudent(s)
    students.value = p.items
  } catch {
    // 筛选加载失败不阻塞编辑器（保留原候选）
  }
}

// 筛选变化 → 刷新学员候选（联动收敛由复用组件内部完成）
watch(stuFilter, async () => {
  await fetchStudents()
}, { deep: true })

// ---------- 班级家长会 PPT（校区/教师筛选 → 班级 → 名单 → 生成） ----------
const classes = ref<ClassOut[]>([])
const classPptOpen = ref(false)
const pptCampus = ref('')
const pptTeacherId = ref('')
const classPptClassId = ref('')
const classPptStart = ref('')
const classPptEnd = ref('')
const classPptNote = ref('')
const classPptBusy = ref(false)
const classPptError = ref('')
const roster = ref<ClassRosterOut | null>(null)
const rosterLoading = ref(false)
const rosterError = ref('')
const classPptResult = ref<Record<string, unknown> | null>(null)
const classPptRecord = ref<ClassPptRecordOut | null>(null)
const classPptEdit = ref({
  title: '',
  class_summary: '',
  ability_comment: '',
  highlights: '',
  to_improve: '',
  next_plan: '',
  home_suggestions: '',
})
const classPptEditBusy = ref(false)
const classPptEditMsg = ref('')
const classPptEditErr = ref('')
/** 重提炼二次确认（regen-dedup）：素材无变化时先提示，再由用户确认是否强制重提 */
const showRegenConfirm = ref(false)
const classPptTip = ref('')
const pptAgentRef = ref<InstanceType<typeof PptAgentDialog> | null>(null)
/** 班级面板内生成方式：一键生成 / Agent 定制（合并为单流程，先选班级周期再选方式） */
const pptGenMode = ref<'quick' | 'agent'>('quick')

function openAgentPpt() {
  if (!classPptClassId.value || !classPptStart.value || !classPptEnd.value) {
    // Agent 入口已并入班级面板：缺班级/周期时先打开面板引导选择
    if (!classPptClassId.value) {
      setErr('请先在下方选择班级与周期，再开始 Agent 定制')
      pptGenMode.value = 'agent'
      classPptOpen.value = true
      return
    }
    if (!classPptStart.value || !classPptEnd.value) {
      setErr('请先选择评估周期，再开始 Agent 定制')
      pptGenMode.value = 'agent'
      classPptOpen.value = true
      return
    }
  }
  if (roster.value && roster.value.generated === 0) {
    setErr('该班该周期还没有学员评估，请先为学员生成评估')
    return
  }
  const ctx = {
    kind: 'class_ppt',
    class_id: classPptClassId.value,
    period_start: classPptStart.value,
    period_end: classPptEnd.value,
    title: activeClass.value?.name || '家长会 PPT',
  }
  router.push({ name: 'agents', query: { agent: 'class_parent_ppt', context: JSON.stringify(ctx) } })
}
/** 班级 PPT 任务：以 AI 任务 store 为唯一状态源（避免两套轮询不同步） */
const classPptTaskId = ref('')
const classPptTaskIdByClass = ref<Record<string, string>>({})
const nowTick = ref(Date.now())
const classPptTask = computed<ClassPptTaskOut | null>(() => {
  if (!classPptTaskId.value) return null
  return (aiTasks.tasks.find((t) => t.id === classPptTaskId.value) as ClassPptTaskOut | undefined) ?? null
})
/** 任务进度阶段序号：0 排队 / 1 AI 提炼 / 2 排版生成 / 3 完成 */
const classPptStageIndex = computed(() => {
  const t = classPptTask.value
  if (!t) return -1
  if (t.status === 'done') return 3
  if (t.status === 'failed') return -1
  const stage = t.stage || ''
  if (stage.includes('排队')) return 0
  if (stage.includes('排版')) return 2
  return 1
})
const classPptElapsed = computed(() => {
  const t = classPptTask.value
  if (!t || (t.status !== 'pending' && t.status !== 'running')) return ''
  const startMs = Date.parse(t.started_at || t.created_at)
  if (Number.isNaN(startMs)) return ''
  const sec = Math.max(0, Math.floor((nowTick.value - startMs) / 1000))
  return sec >= 60 ? `${Math.floor(sec / 60)} 分 ${sec % 60} 秒` : `${sec} 秒`
})

const pptTeachers = ref<UserOut[]>([])
const pptCampuses = ref<string[]>([])

const pptTeacherOptions = computed(() =>
  pptTeachers.value
    .filter((t) =>
      pptCampus.value && pptCampus.value !== '__unassigned__' ? t.campus === pptCampus.value : true,
    )
    .map((t) => ({ id: t.id, label: t.campus ? `${t.name}（${t.campus}）` : t.name })),
)
const classOptions = computed(() =>
  classes.value.map((c) => ({
    id: c.id,
    label: `${c.name}${c.subject ? `（${c.subject}）` : ''}${c.teacher_name ? ` · ${c.teacher_name}` : ''}`,
  })),
)
const activeClass = computed(() => classes.value.find((c) => c.id === classPptClassId.value) ?? null)
const rosterCounts = computed(() => {
  const r = roster.value
  if (!r) return null
  const draft = Math.max(0, r.generated - r.published)
  return { total: r.total, published: r.published, draft, missing: r.total - r.generated }
})
/** 可生成班级 PPT：该班该周期至少 1 名学员已生成评估（草稿/已发布均可） */
const canGenClassPpt = computed(() => {
  if (!classPptClassId.value || !classPptStart.value || !classPptEnd.value) return false
  if (roster.value === null) return false
  return roster.value.generated > 0
})

const classPptClassOptions = computed(() => classOptions.value)

/** 打开面板/切换班级时接管任务：优先用记住的 task id，其次从任务列表恢复（刷新页面后也能接上） */
function reconnectClassPptTask() {
  const clsId = classPptClassId.value
  if (!clsId) {
    classPptTaskId.value = ''
    return
  }
  const remembered = classPptTaskIdByClass.value[clsId]
  if (remembered && aiTasks.tasks.some((t) => t.id === remembered)) {
    classPptTaskId.value = remembered
    return
  }
  const mine = aiTasks.tasks.filter((t) => { const k = (t as { kind?: string }).kind; return k === 'class_parent_ppt' || k === 'class_parent_ppt_refine' })
  const clsName = classes.value.find((c) => c.id === clsId)?.name
  const running = mine.find(
    (t) =>
      (t.status === 'pending' || t.status === 'running') &&
      !!clsName &&
      (t.summary || '').includes(clsName),
  )
  if (running) {
    classPptTaskId.value = running.id
    classPptTaskIdByClass.value = { ...classPptTaskIdByClass.value, [clsId]: running.id }
    return
  }
  const done = mine.find(
    (t) =>
      t.status === 'done' &&
      (t.result as Record<string, unknown> | null)?.class_id === clsId &&
      !!(t.result as Record<string, unknown> | null)?.ppt_url,
  )
  if (done) {
    classPptTaskId.value = done.id
    classPptTaskIdByClass.value = { ...classPptTaskIdByClass.value, [clsId]: done.id }
    classPptResult.value = done.result as Record<string, unknown>
  }
}

async function loadPptClasses() {
  try {
    const p = await listClasses({
      teacher_id: pptTeacherId.value || undefined,
      campus: pptCampus.value && pptCampus.value !== '__unassigned__' ? pptCampus.value : undefined,
      campus_unassigned: pptCampus.value === '__unassigned__' || undefined,
      limit: 500,
    })
    classes.value = p.items
  } catch {
    classes.value = []
  }
  if (classPptClassId.value && !classes.value.some((c) => c.id === classPptClassId.value)) {
    classPptClassId.value = ''
    roster.value = null
    classPptResult.value = null
  }
}

async function loadRoster() {
  if (!classPptClassId.value || !classPptStart.value || !classPptEnd.value) {
    roster.value = null
    return
  }
  rosterLoading.value = true
  rosterError.value = ''
  try {
    roster.value = await getClassRoster({
      class_id: classPptClassId.value,
      period_start: classPptStart.value,
      period_end: classPptEnd.value,
    })
  } catch (e: unknown) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    rosterError.value = detail || '学员名单加载失败'
    roster.value = null
  } finally {
    rosterLoading.value = false
  }
}

/** 拉取该班最近一次 PPT 落库记录（有则展示下载入口 + 预览编辑表单） */
async function loadClassPptRecord() {
  if (!classPptClassId.value) {
    classPptRecord.value = null
    return
  }
  try {
    const r = await getClassPptLatest(classPptClassId.value)
    classPptRecord.value = r
    if (r.source === 'db') syncPptEdit(r)
  } catch {
    classPptRecord.value = null
  }
}

function syncPptEdit(r: ClassPptRecordOut) {
  const c = r.content || {}
  classPptEdit.value = {
    title: str(c.title ?? r.title ?? ''),
    class_summary: str(c.class_summary ?? ''),
    ability_comment: str(c.ability_comment ?? ''),
    highlights: str(c.highlights ?? ''),
    to_improve: str(c.to_improve ?? ''),
    next_plan: str(c.next_plan ?? ''),
    home_suggestions: str(c.home_suggestions ?? ''),
  }
}

/** 保存编辑后的文案：PATCH 用存量素材快照秒级重排版（不调 LLM），刷新下载链接 */
async function saveClassPptEdit() {
  const rec = classPptRecord.value
  if (!rec?.record_id) return
  if (!classPptEdit.value.class_summary.trim() && !classPptEdit.value.highlights.trim()) {
    classPptEditErr.value = '「班级整体情况」和「班级亮点」不能同时为空，否则 PPT 没有正文内容'
    return
  }
  classPptEditBusy.value = true
  classPptEditErr.value = ''
  try {
    const saved = await updateClassPpt(rec.record_id, { ...classPptEdit.value })
    classPptRecord.value = {
      ...rec,
      title: saved.title,
      content: saved.content,
      ppt_url: saved.ppt_url,
      updated_at: saved.updated_at,
    }
    if (classPptResult.value) {
      classPptResult.value = { ...classPptResult.value, ppt_url: saved.ppt_url, title: saved.title }
    }
    classPptEditMsg.value = '文案已保存，PPT 已按新内容重新排版，可直接下载'
    setMsg('班级家长会 PPT 已按新文案重新生成')
  } catch (e: unknown) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    classPptEditErr.value = detail || '保存失败，请重试'
  } finally {
    classPptEditBusy.value = false
  }
}

function openClassPpt() {
  classPptOpen.value = true
  classPptError.value = ''
  if (!classPptStart.value || !classPptEnd.value) {
    const end = new Date()
    const start = new Date()
    start.setMonth(start.getMonth() - 3)
    const pad = (n: number) => String(n).padStart(2, '0')
    classPptStart.value = `${start.getFullYear()}-${pad(start.getMonth() + 1)}-${pad(start.getDate())}`
    classPptEnd.value = `${end.getFullYear()}-${pad(end.getMonth() + 1)}-${pad(end.getDate())}`
  }
  // 教师默认只筛自己的班级：未显式筛选过时，默认选中自己（校区 + 本人）
  if (!auth.user) void auth.fetchMe()
  const u = auth.user
  if (u?.role === 'teacher') {
    if (pptTeacherId.value === '') pptTeacherId.value = u.id
    if (!pptCampus.value && u.campus) pptCampus.value = u.campus
  }
  void loadPptMeta()
  void loadPptClasses().then(() => reconnectClassPptTask())
  void loadRoster()
  void loadClassPptRecord()
  if (classPptResult.value && classPptResult.value.class_id !== classPptClassId.value) {
    classPptResult.value = null
  }
}

/** 班级面板元数据（校区/教师下拉，打开面板时加载，与学员筛选组件互不干扰） */
async function loadPptMeta() {
  try {
    pptCampuses.value = await listCampusesApi()
  } catch {
    pptCampuses.value = []
  }
  try {
    const t = await listTeachersApi({ limit: 500 })
    pptTeachers.value = t.items
  } catch {
    pptTeachers.value = []
  }
}

function clearPptFilters() {
  pptCampus.value = ''
  pptTeacherId.value = ''
  classPptClassId.value = ''
  roster.value = null
  classPptResult.value = null
  classPptRecord.value = null
  void loadPptClasses()
}

// 面板内改选校区/教师 → 班级下拉即时联动收敛（失效班级自动清空）
watch([pptCampus, pptTeacherId], async () => {
  if (!classPptOpen.value) return
  if (pptCampus.value && pptCampus.value !== '__unassigned__') {
    const t = pptTeachers.value.find((x) => x.id === pptTeacherId.value)
    if (t && t.campus !== pptCampus.value) pptTeacherId.value = ''
  }
  await loadPptClasses()
})

// 面板内选班级/改周期 → 名册（学员评估状态）+ 最近一次 PPT 记录 即时加载显示
watch([classPptClassId, classPptStart, classPptEnd], () => {
  if (!classPptOpen.value) return
  classPptResult.value = null
  classPptRecord.value = null
  classPptEditMsg.value = ''
  classPptEditErr.value = ''
  showRegenConfirm.value = false
  void loadRoster()
  void loadClassPptRecord()
})

/** 查看某学员已生成的评估（复用页面详情弹窗） */
async function viewRosterEval(student: ClassRosterStudentOut) {
  const evId = student.evaluation?.id
  if (!evId) return
  // 先收起班级面板，避免与详情弹窗叠层
  classPptOpen.value = false
  try {
    detailEv.value = await getEvaluation(evId)
  } catch (e: unknown) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    setErr(detail || '评估加载失败')
  }
}

/** 去生成/重新生成评估：关闭面板并把 学员 + 周期 带到编辑器自动选中。
 * 已有评估的学员按该评估自身的周期载入（草稿内容会回填到编辑器）；未生成则用面板所选周期。 */
async function goGenerateForStudent(student: ClassRosterStudentOut) {
  classPptOpen.value = false
  if (student.evaluation) {
    // 重新生成：载入已有评估自身的周期，编辑器会自动回填该评估内容
    try {
      const ev = await getEvaluation(student.evaluation.id)
      periodStart.value = ev.period_start.slice(0, 10)
      periodEnd.value = ev.period_end.slice(0, 10)
      current.value = ev
      syncForm(ev)
    } catch {
      // 拉取失败则退回面板周期（保存时按 学员+周期 幂等创建）
      periodStart.value = classPptStart.value
      periodEnd.value = classPptEnd.value
    }
  } else {
    periodStart.value = classPptStart.value
    periodEnd.value = classPptEnd.value
  }
  // 同步把筛选带回编辑器：校区 / 教师 / 班级 / 学员，方便快速继续生成其他同班评估
  stuFilter.value = {
    campus: pptCampus.value && pptCampus.value !== '__unassigned__' ? pptCampus.value : '',
    teacherId: pptTeacherId.value || '',
    classId: classPptClassId.value || '',
    keyword: stuFilter.value.keyword,
    account: stuFilter.value.account,
  }
  studentId.value = student.student_id
  try {
    const st = await getStudent(student.student_id)
    cacheStudent(st)
    if (!students.value.some((x) => x.id === st.id)) students.value = [st, ...students.value]
  } catch {
    // 拉取失败不阻塞：名单里已有姓名/校区信息
  }
  await fetchStudents()
  await router.replace({
    query: {
      ...route.query,
      student_id: student.student_id,
      period_start: periodStart.value,
      period_end: periodEnd.value,
      campus: stuFilter.value.campus || undefined,
      teacher_id: stuFilter.value.teacherId || undefined,
      class_id: stuFilter.value.classId || undefined,
    },
  })
  const verb = student.evaluation ? '已载入该学员现有评估，可修改后重新保存/发布' : '可直接填写生成'
  setMsg(`已定位「${student.name}」，${verb} ${periodStart.value} ~ ${periodEnd.value} 的评估`)
  await new Promise((r) => setTimeout(r, 30))
  document.querySelector('.editor-card')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

async function genClassPpt(force = false) {
  if (!classPptClassId.value) {
    classPptError.value = '请先选择班级'
    return
  }
  if (!classPptStart.value || !classPptEnd.value) {
    classPptError.value = '请选择评估周期'
    return
  }
  if (roster.value && roster.value.generated === 0) {
    classPptError.value = '该班该周期还没有学员评估：请先为学员生成评估（草稿也可生成班级 PPT）'
    return
  }
  // 重提炼去重预检（regen-dedup）：有落库记录且非强制重提时，先问后端素材是否有变化
  if (classPptRecord.value?.source === 'db' && !force) {
    try {
      const fp = await getClassPptFingerprint({
        class_id: classPptClassId.value,
        period_start: classPptStart.value,
        period_end: classPptEnd.value,
      })
      if (fp.running) {
        classPptError.value = `该班级本周期已有生成任务在进行中（${fp.running_stage || '排队中'}），请稍候再试`
        return
      }
      if (fp.unchanged) {
        // 素材无变化：不直接提交，先给提示并弹二次确认（确认后 force=true 重提）
        classPptTip.value = '全班学员评估与课堂数据自上次生成后无变化，重新提炼会得到相同文案并覆盖手工编辑内容。'
        showRegenConfirm.value = true
        return
      }
    } catch (e: unknown) {
      // 预检失败不阻塞：走提交流程，后端 409 同样会给出可读提示
      // （404/400=无记录或无评估可直接生成；409 running=预检自身返回，无需当错误抛）
      const status = (e as { response?: { status?: number } })?.response?.status
      if (status === 409) {
        const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        classPptError.value = detail || '提交班级 PPT 任务失败'
        return
      }
      if (status && status !== 404 && status !== 400) {
        const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        classPptError.value = detail || '提交班级 PPT 任务失败'
        return
      }
    }
  }
  classPptBusy.value = true
  classPptError.value = ''
  classPptResult.value = null
  try {
    const task = await generateClassPpt({
      class_id: classPptClassId.value,
      period_start: classPptStart.value,
      period_end: classPptEnd.value,
      extra_note: classPptNote.value || null,
      force,
    })
    classPptTaskId.value = task.id
    classPptTaskIdByClass.value = {
      ...classPptTaskIdByClass.value,
      [classPptClassId.value]: task.id,
    }
    aiTasks.register(task, 'evaluation')
    setMsg('班级家长会 PPT 任务已提交，进度请在下方查看，完成后可直接下载')
  } catch (e: unknown) {
    const status = (e as { response?: { status?: number } })?.response?.status
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    if (status === 409 && detail?.includes('无变化')) {
      // 后端兜底拦截（并发窗口/指纹漂移）：同样给提示并弹二次确认，可一键强制重提
      classPptTip.value = detail
      showRegenConfirm.value = true
    } else {
      classPptError.value = detail || '提交班级 PPT 任务失败'
    }
  } finally {
    classPptBusy.value = false
  }
}

/** 任务完成/失败时同步结果（轮询由 aiTasks store 统一负责）；完成后拉取落库记录进入可编辑态 */
watch(
  () => classPptTask.value,
  (t) => {
    if (!t) return
    if (t.status === 'done' && t.result) {
      classPptResult.value = t.result
      setMsg(`「${String((t.result as Record<string, unknown>).class_name || activeClass.value?.name || '')}」家长会 PPT 已生成`)
      void loadClassPptRecord()
    } else if (t.status === 'failed') {
      classPptError.value = t.error || '班级 PPT 生成失败'
    }
  },
)

// 面板打开期间每秒跳动一次，用于展示任务已进行时长
let classPptElapsedTimer: number | null = null
watch(classPptOpen, (open) => {
  if (open) {
    nowTick.value = Date.now()
    if (classPptElapsedTimer === null) {
      classPptElapsedTimer = window.setInterval(() => {
        nowTick.value = Date.now()
      }, 1000)
    }
  } else if (classPptElapsedTimer !== null) {
    window.clearInterval(classPptElapsedTimer)
    classPptElapsedTimer = null
  }
})

const LEVEL_LABELS: Record<number, string> = {
  5: '非常优秀',
  4: '优秀',
  3: '良好',
  2: '需加强',
  1: '待观察',
}

function levelLabel(level: number): string {
  const lv = Math.min(5, Math.max(1, Math.round(level) || 1))
  return LEVEL_LABELS[lv] ?? '良好'
}

function setMsg(m: string) {
  message.value = m
  error.value = ''
}

function setErr(m: string) {
  error.value = m
  message.value = ''
}

function str(v: unknown): string {
  return typeof v === 'string' ? v : v == null ? '' : String(v)
}

function fmtDateKey(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

function syncForm(ev: EvaluationOut | null) {
  if (!ev) {
    title.value = ''
    summary.value = ''
    subjects.value = []
    progress.value = ''
    toImprove.value = ''
    suggestions.value = ''
    return
  }
  title.value = ev.title || ''
  summary.value = cleanListishText(ev.content.summary)
  subjects.value = Array.isArray(ev.content.subjects)
    ? ev.content.subjects.map((s: unknown) => {
        const it = (s ?? {}) as Record<string, unknown>
        return {
          name: String(it.name || ''),
          level: Math.min(5, Math.max(1, Number(it.level) || 3)),
          comment: String(it.comment || ''),
        }
      })
    : []
  progress.value = cleanListishText(ev.content.progress)
  toImprove.value = cleanListishText(ev.content.to_improve)
  suggestions.value = cleanListishText(ev.content.suggestions)
}

async function loadList() {
  listLoading.value = true
  try {
    const p = await listEvaluations({
      student_id: studentId.value || undefined,
      status: historyStatus.value || undefined,
      limit: 20,
    })
    list.value = p.items
  } catch {
    list.value = []
  } finally {
    listLoading.value = false
  }
}

async function loadCurrent() {
  if (!studentId.value || !periodStart.value || !periodEnd.value) return
  loading.value = true
  try {
    const p = await listEvaluations({ student_id: studentId.value, limit: 50 })
    const found =
      p.items.find(
        (e) => e.period_start.startsWith(periodStart.value) && e.period_end.startsWith(periodEnd.value),
      ) ?? null
    current.value = found
    syncForm(found)
    // 素材预览只依赖学员 + 周期：未保存草稿也即时可见（辅助教师判断数据口径）
    const mat = await getEvaluationMaterial({
      student_id: studentId.value,
      start: periodStart.value,
      end: periodEnd.value,
    })
    material.value = mat
  } catch (e: unknown) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    setErr(detail || '加载评估失败')
  } finally {
    loading.value = false
  }
  await loadList()
}

async function save() {
  if (!studentId.value) {
    setErr('请选择学员')
    return false
  }
  if (!periodStart.value || !periodEnd.value) {
    setErr('请选择评估周期')
    return false
  }
  saving.value = true
  try {
    const payload = {
      student_id: studentId.value,
      period_start: periodStart.value,
      period_end: periodEnd.value,
      title: title.value || null,
      content: {
        summary: summary.value,
        subjects: subjects.value,
        progress: progress.value,
        to_improve: toImprove.value,
        suggestions: suggestions.value,
      },
    }
    current.value = current.value
      ? await updateEvaluation(current.value.id, payload as EvaluationUpdateIn)
      : await createEvaluation(payload)
    syncForm(current.value)
    setMsg('已保存')
    await loadList()
    return true
  } catch (e: unknown) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    setErr(detail || '保存失败')
    return false
  } finally {
    saving.value = false
  }
}

async function publish() {
  const missing = validateRequired('content')
  if (missing) {
    setErr(missing)
    return
  }
  // 表单有未保存改动时先落盘，确保发布的是编辑器当前内容
  if (!(await save())) return
  if (!current.value) return
  try {
    current.value = await publishEvaluation(current.value.id)
    syncForm(current.value)
    setMsg('已发布，家长/学员账号已收到通知')
    await loadList()
  } catch (e: unknown) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    setErr(detail || '发布失败')
  }
}

async function unpublish() {
  if (!current.value) return
  try {
    current.value = await unpublishEvaluation(current.value.id)
    syncForm(current.value)
    setMsg('已撤回为草稿')
    await loadList()
  } catch (e: unknown) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    setErr(detail || '撤回失败')
  }
}

async function doDelete() {
  if (!current.value) return
  try {
    await deleteEvaluation(current.value.id)
    showDelete.value = false
    current.value = null
    material.value = null
    syncForm(null)
    setMsg('评估已删除')
    await loadList()
  } catch (e: unknown) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    showDelete.value = false
    setErr(detail || '删除失败')
  }
}

function openDetail(ev: EvaluationOut | null) {
  if (!ev) {
    if (!current.value) {
      setErr('请先保存评估后预览')
      return
    }
    detailEv.value = current.value
  } else {
    detailEv.value = ev
  }
}

function loadIntoEditor(ev: EvaluationOut) {
  current.value = ev
  syncForm(ev)
  periodStart.value = ev.period_start.slice(0, 10)
  periodEnd.value = ev.period_end.slice(0, 10)
  studentId.value = ev.student_id
  setMsg(`已载入「${ev.title || '学习评估'}」，可继续编辑`)
}

function setPresetMonths(months: number) {
  const end = new Date()
  const start = new Date()
  start.setMonth(start.getMonth() - months)
  periodStart.value = fmtDateKey(start)
  periodEnd.value = fmtDateKey(end)
}

function onGlobalKeydown(e: KeyboardEvent) {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
    e.preventDefault()
    if (!saving.value) save()
  }
}

/**
 * 必要内容校验：返回缺失提示（null = 通过）。
 * base = 学员 + 周期（AI 生成草稿的最低要求）；content 额外要求综合总结
 * （对话优化要有可优化内容，发布不能是空表）。
 */
function validateRequired(level: 'base' | 'content'): string | null {
  if (!studentId.value) return '请先选择学员'
  if (!periodStart.value || !periodEnd.value) return '请先选择评估周期'
  if (level === 'content' && !summary.value.trim()) {
    return '请先填写「综合总结」内容，或使用「AI 生成草稿」'
  }
  return null
}

async function runAiDraft() {
  const missing = validateRequired('base')
  if (missing) {
    setErr(missing)
    return
  }
  // 未落盘也能直接用 AI：自动保存草稿后提交任务
  if (!(await save())) return
  if (!current.value) return
  try {
    const style = aiTemplates.value.find((t) => t.id === aiTemplateId.value)?.content || null
    const task = await aiDraftEvaluation(current.value.id, { extra_note: aiNote.value || null, style_guide: style })
    myTaskIds.value.push(task.id)
    aiTasks.register(task, 'evaluation')
    setMsg('AI 生成任务已提交，完成后自动回填')
  } catch (e: unknown) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    setErr(detail || '提交 AI 任务失败')
    toastApiError(e)
  }
}

async function runAiRefine() {
  const missing = validateRequired('content')
  if (missing) {
    setErr(missing)
    return
  }
  if (!(await save())) return
  if (!current.value) return
  try {
    const task = await aiRefineEvaluation(
      current.value.id,
      { instruction: aiInstruction.value || '请优化表达' },
    )
    myTaskIds.value.push(task.id)
    aiTasks.register(task, 'evaluation')
    setMsg('优化任务已提交，完成后自动回填')
  } catch (e: unknown) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    setErr(detail || '提交优化任务失败')
    toastApiError(e)
  }
}

function applyAiContent(data: Record<string, unknown>) {
  if (!data.summary) {
    setErr('AI 未返回有效内容，请重试')
    return
  }
  if (str(data.title)) title.value = str(data.title)
  summary.value = cleanListishText(data.summary)
  if (Array.isArray(data.subjects)) {
    subjects.value = (data.subjects as Array<Record<string, unknown>>).map((s) => ({
      name: String(s?.name ?? ''),
      level: Math.min(5, Math.max(1, Number(s?.level) || 3)),
      comment: String(s?.comment ?? ''),
    }))
  }
  progress.value = cleanListishText(data.progress)
  toImprove.value = cleanListishText(data.to_improve)
  suggestions.value = cleanListishText(data.suggestions)
}

watch(
  () =>
    aiTasks.tasks
      .filter((t) => myTaskIds.value.includes(t.id))
      .map((t) => `${t.id}:${t.status}`)
      .join('|'),
  async () => {
    const finished = aiTasks.tasks.filter(
      (t) => myTaskIds.value.includes(t.id) && (t.status === 'done' || t.status === 'failed'),
    )
    for (const t of finished) {
      myTaskIds.value = myTaskIds.value.filter((id) => id !== t.id)
      if (t.status === 'failed') {
        setErr(`AI 任务失败：${(t as EvaluationAiDraftOut).error || '请稍后重试'}`)
        continue
      }
      const data = (t as EvaluationAiDraftOut).result
      if (data && typeof data === 'object') {
        applyAiContent(data)
        await save()
        setMsg('AI 内容已生成并自动保存，可继续编辑或预览')
      } else {
        setErr('AI 未返回有效内容，请重试')
      }
    }
  },
)

function addSubject() {
  subjects.value.push({ name: '', level: 3, comment: '' })
}

function removeSubject(i: number) {
  subjects.value.splice(i, 1)
}

const materialChips = computed(() => {
  if (!material.value) return []
  const s = material.value.stats
  const chips: Array<{ label: string; value: string; cls?: string }> = [
    { label: '到课', value: `${s.attended} 次` },
    { label: '请假', value: `${s.leave} 次` },
    { label: '出勤率', value: `${(s.attendance_rate * 100).toFixed(0)}%`, cls: 'cyan' },
    { label: '课时消耗', value: `${s.consumed_lessons} 节` },
    { label: '课后反馈', value: `${s.feedback_count} 篇` },
    { label: '已批改作业', value: `${s.homework_count} 份` },
  ]
  if (s.homework_score_rate != null) {
    chips.push({
      label: '作业得分率',
      value: `${(s.homework_score_rate * 100).toFixed(0)}%`,
      cls: 'green',
    })
  }
  return chips
})

const evalTasks = computed(() => aiTasks.tasks.filter((t) => t.taskKind === 'evaluation'))

function isClassPptTask(t: UnifiedAiTask): boolean {
  const k = (t as { kind?: string }).kind
  return k === 'class_parent_ppt' || k === 'class_parent_ppt_refine'
}

watch(historyStatus, () => {
  loadList()
})

// 全局浮窗/toast 分流跳转：已在评估页时同样响应 openClassPpt 打开班级面板
watch(
  () => route.query.openClassPpt,
  (v) => {
    if (v !== '1') return
    const q = route.query as Record<string, string | undefined>
    if (typeof q.ppt_class_id === 'string' && q.ppt_class_id) classPptClassId.value = q.ppt_class_id
    if (typeof q.ppt_start === 'string' && q.ppt_start) classPptStart.value = q.ppt_start.slice(0, 10)
    if (typeof q.ppt_end === 'string' && q.ppt_end) classPptEnd.value = q.ppt_end.slice(0, 10)
    openClassPpt()
  },
)

watch(studentId, async (id) => {
  if (id && route.name === 'student-evaluations') {
    router.replace({ name: 'evaluations' })
  }
  await loadCurrent()
})

watch([periodStart, periodEnd], async () => {
  await loadCurrent()
})

onMounted(async () => {
  window.addEventListener('keydown', onGlobalKeydown)
  await aiTasks.bootstrap()
  void loadAiTemplates()
  if (!auth.user) await auth.fetchMe()
  const me = auth.user
  if (me?.role === 'teacher') {
    // 教师默认只筛自己的班级与学员
    stuFilter.value = { ...stuFilter.value, teacherId: me.id }
    pptTeacherId.value = me.id
  }
  try {
    await fetchStudents()
    await loadPptClasses()
  } catch {
    // 学员/班级列表加载失败不阻塞页面
  }
  const rid = route.params.id
  const query = route.query as Record<string, string | undefined>
  if (query.campus || query.teacher_id || query.class_id) {
    stuFilter.value = {
      ...stuFilter.value,
      campus: query.campus ?? stuFilter.value.campus,
      teacherId: query.teacher_id ?? stuFilter.value.teacherId,
      classId: query.class_id ?? stuFilter.value.classId,
    }
  }
  if (query.ppt_campus) pptCampus.value = query.ppt_campus
  if (query.ppt_teacher_id) pptTeacherId.value = query.ppt_teacher_id
  if (query.ppt_class_id) classPptClassId.value = query.ppt_class_id
  if (query.ppt_start) classPptStart.value = String(query.ppt_start).slice(0, 10)
  if (query.ppt_end) classPptEnd.value = String(query.ppt_end).slice(0, 10)
  if (typeof rid === 'string' && rid) {
    studentId.value = rid
  } else if (query.student_id) {
    studentId.value = query.student_id
  } else if (!studentId.value) {
    studentId.value = students.value[0]?.id ?? ''
  }
  if (query.period_start) periodStart.value = query.period_start.slice(0, 10)
  if (query.period_end) periodEnd.value = query.period_end.slice(0, 10)
  if (studentId.value) {
    try {
      const st = await getStudent(studentId.value)
      cacheStudent(st)
      if (!students.value.some((x) => x.id === st.id)) students.value = [st, ...students.value]
    } catch {
      // 兜底失败不阻塞
    }
  }
  await loadList()
  // 全局浮窗/toast 按类型分流跳转而来时自动打开班级面板接管任务
  if (query.openClassPpt === '1') {
    openClassPpt()
  }
})

onBeforeUnmount(() => {
  if (classPptElapsedTimer !== null) {
    window.clearInterval(classPptElapsedTimer)
    classPptElapsedTimer = null
  }
  window.removeEventListener('keydown', onGlobalKeydown)
})
</script>

<template>
  <div class="eval-page">
    <PageHead title="学员评估工作台" eyebrow="EVALUATIONS" sub="基于评估周期内的课后反馈与课程数据，生成家长会综合评估表">
      <template #actions>
      <span v-if="current" class="status-pill head-pill" :class="isPublished ? 'published' : 'draft'">
        <span class="pill-dot" />
        {{ isPublished ? '已发布' : '草稿' }}
      </span>
      <div class="ops">
        <button class="op-btn ghost" :disabled="saving || loading" @click="save">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2zM17 21v-8H7v8M7 3v5h8" /></svg>
          {{ saving ? '保存中…' : '保存草稿' }}
        </button>
        <button class="op-btn primary" :disabled="isPublished || saving || loading" @click="publish">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m22 2-7 20-4-9-9-4zM22 2 11 13" /></svg>
          发布
        </button>
        <button v-if="isPublished" class="op-btn ghost" @click="unpublish">撤回</button>
        <button class="op-btn ghost" :disabled="!current" @click="openDetail(null)">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" /><circle cx="12" cy="12" r="3" /></svg>
          预览详情
        </button>
        <button class="op-btn ai" @click="openClassPpt()">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19V5a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v14M8 5v14M16 5v14M4 9h16M4 13h16" /></svg>
          班级家长会 PPT
        </button>
        <a v-if="current?.ppt_url" class="op-btn download" :href="pptDownloadUrl(current.ppt_url)" target="_blank">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3" /></svg>
          查看 PPT
        </a>
        <button v-if="current && !isPublished" class="op-btn danger-ghost" @click="showDelete = true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m3 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" /></svg>
          删除
        </button>
      </div>
      </template>
    </PageHead>

    <Transition name="banner-fade">
      <p v-if="error" class="banner error">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 9v4M12 17h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" /></svg>
        {{ error }}
      </p>
    </Transition>
    <Transition name="banner-fade">
      <p v-if="message" class="banner ok">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5" /></svg>
        {{ message }}
      </p>
    </Transition>

    <div v-if="loading" class="loading-tip">加载中…</div>

    <div class="work-grid">
      <!-- 左：评估编辑器 -->
      <section class="card editor-card">
        <div class="card-head">
          <h2>评估内容</h2>
          <div class="preset-row">
            <span class="preset-label">快捷周期</span>
            <button class="mini-btn ghost" type="button" @click="setPresetMonths(1)">近 1 个月</button>
            <button class="mini-btn ghost" type="button" @click="setPresetMonths(3)">近 3 个月</button>
            <button class="mini-btn ghost" type="button" @click="setPresetMonths(6)">近 6 个月</button>
          </div>
        </div>

        <div class="field-row">
          <div class="field grow">
            <label>学员</label>
            <SearchableSelect
              v-model="studentId"
              :options="studentOptions"
              placeholder="搜索并选择学员"
            />
          </div>
          <div class="field">
            <label>周期起</label>
            <input v-model="periodStart" type="date" />
          </div>
          <div class="field">
            <label>周期止</label>
            <input v-model="periodEnd" type="date" />
          </div>
        </div>

        <!-- 学员快速筛选（校区 → 教师 → 班级 → 学员姓名，与学员管理/发布学员选择同一套联动） -->
        <StudentFilter
          v-model="stuFilter"
          show-account-filter
          campus-placeholder="全部校区"
          teacher-placeholder="全部教师"
          class-placeholder="全部班级"
          search-placeholder="搜索学员姓名…"
          compact
        >
          <span class="qk-count" :title="`已加载 ${studentOptions.length} 名学员候选`">
            {{ studentOptions.length }} 名学员
          </span>
        </StudentFilter>

        <div v-if="activeStudent" class="student-brief">
          <span v-if="activeStudent.campus" class="brief-chip">{{ activeStudent.campus }}</span>
          <span
            v-for="c in activeStudent.classes"
            :key="c.id"
            class="brief-chip cls"
            :title="`${c.subject}${c.teacher_name ? ` · ${c.teacher_name}` : ''}`"
          >
            {{ c.name }}
          </span>
          <span v-if="activeStudent.classes.length === 0" class="brief-chip muted">未分班</span>
          <span class="brief-chip" :class="{ warn: activeStudent.low_balance }">
            剩余 {{ activeStudent.lesson_balance }} 课时
          </span>
        </div>

        <div class="field">
          <label>评估标题</label>
          <input v-model="title" type="text" placeholder="如：王小明 2026 年第三季度学习评估" />
        </div>

        <div class="field">
          <label>综合总结 <em class="field-hint">写给家长看的综合表现总结</em></label>
          <textarea v-autogrow v-model="summary" rows="4" placeholder="孩子在这段时间的整体表现、学习状态、课堂参与度……" />
        </div>

        <div class="subject-block">
          <div class="subject-head">
            <label>学科能力 <em class="field-hint">点击星级打分（1-5）</em></label>
            <button class="mini-btn" type="button" @click="addSubject">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14M5 12h14" /></svg>
              添加条目
            </button>
          </div>
          <div v-if="subjects.length === 0" class="subject-empty">
            还没有能力项，点击「添加条目」新增（如：编程思维 / 代码实践 / 逻辑表达）
          </div>
          <TransitionGroup name="row" tag="div" class="subject-list">
            <div v-for="(s, i) in subjects" :key="i" class="subject-row">
              <input v-model="s.name" class="sr-name" placeholder="能力项" />
              <div class="star-edit">
                <button
                  v-for="n in 5"
                  :key="n"
                  type="button"
                  class="star-btn"
                  :class="{ on: n <= s.level }"
                  :title="`${n} 星 · ${levelLabel(n)}`"
                  @click="s.level = n"
                >★</button>
                <span class="level-label">{{ levelLabel(s.level) }}</span>
              </div>
              <input v-model="s.comment" class="sr-comment" placeholder="一句话点评" />
              <button class="row-del" type="button" title="删除该条目" @click="removeSubject(i)">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18M6 6l12 12" /></svg>
              </button>
            </div>
          </TransitionGroup>
        </div>

        <div class="field">
          <label>进步亮点</label>
          <textarea v-autogrow v-model="progress" rows="3" placeholder="用「；」分隔多条，如：能独立完成循环结构编程；主动帮同学排查代码错误" />
        </div>
        <div class="field">
          <label>待提升项</label>
          <textarea v-autogrow v-model="toImprove" rows="3" placeholder="客观温和地指出，并给出可操作的方向" />
        </div>
        <div class="field">
          <label>家长建议</label>
          <textarea v-autogrow v-model="suggestions" rows="3" placeholder="家庭练习 / 学习习惯等建议" />
        </div>

        <!-- AI 工作台 -->
        <div class="ai-panel">
          <div class="ai-panel-head">
            <span class="ai-spark">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M13 2 3 14h7l-1 8 10-12h-7l1-8z" /></svg>
            </span>
            <div>
              <h3>AI 助手</h3>
              <p>基于周期内已发布反馈与统计数据起草 / 润色评估，完成后自动回填</p>
            </div>
          </div>
          <div class="ai-row">
            <textarea v-autogrow v-model="aiNote" rows="2" placeholder="补充说明 / 想强调的重点（可选），如：更突出编程思维和自信心的成长" />
            <button class="op-btn ai-solid" :disabled="aiBusy" @click="runAiDraft">
              {{ aiBusy ? '生成中…' : 'AI 生成草稿' }}
            </button>
          </div>
          <div v-if="aiTemplates.length" class="ai-row tpl-row">
            <select v-model="aiTemplateId" class="tpl-select">
              <option v-for="t in aiTemplates" :key="t.id" :value="t.id">
                {{ t.name }}{{ t.scope === 'system' ? '（系统）' : t.scope === 'published' ? '（全校）' : '（我的）' }}
              </option>
            </select>
            <button class="link-btn" type="button" @click="showTplManage = true">管理评估模板</button>
          </div>
          <div class="ai-row">
            <textarea v-autogrow v-model="aiInstruction" rows="2" placeholder="对话式优化指令，如：把语气更亲切，突出逻辑思维的进步" />
            <button class="op-btn ai-solid" :disabled="aiBusy" @click="runAiRefine">
              {{ aiBusy ? '优化中…' : '对话优化' }}
            </button>
          </div>
          <p v-if="aiBusy" class="ai-hint">AI 任务进行中，完成后将自动回填并保存；期间可关闭页面去处理其他事务</p>
          <p v-else class="ai-hint">选好学员与周期即可生成；对话优化前请先填写或生成「综合总结」内容</p>
        </div>
      </section>

      <!-- 右：素材 + 历史 -->
      <div class="side-col">
        <section class="card">
          <div class="card-head">
            <h2>素材预览</h2>
            <span v-if="activeStudent" class="card-tag">{{ activeStudent.name }}</span>
          </div>
          <p v-if="!periodStart || !periodEnd" class="empty-tip">选择评估周期后展示该学员的反馈与统计素材</p>
          <template v-else-if="material">
            <div class="stat-grid">
              <div v-for="c in materialChips" :key="c.label" class="stat-cell" :class="c.cls">
                <strong>{{ c.value }}</strong>
                <span>{{ c.label }}</span>
              </div>
            </div>
            <div v-if="material.feedbacks.length" class="fb-list">
              <p class="side-sub">已发布反馈（{{ material.feedbacks.length }} 篇）</p>
              <article v-for="f in material.feedbacks" :key="`${f.date}-${f.topic}`" class="fb-item">
                <div class="fb-item-head">
                  <strong>{{ f.date }} · {{ f.class_name || '未知班级' }}</strong>
                </div>
                <p v-if="f.topic" class="fb-topic">{{ f.topic }}</p>
                <p class="fb-text">{{ f.evaluation || f.performance || f.content || '（无内容）' }}</p>
              </article>
            </div>
            <p v-else class="empty-tip small">本周期内暂无已发布反馈，AI 将仅基于统计数据生成</p>
          </template>
          <p v-else class="empty-tip small">正在加载素材，请稍候…</p>
        </section>

        <section class="card">
          <div class="card-head">
            <h2>历史评估</h2>
            <span v-if="activeStudent" class="card-tag">{{ list.length }} 份</span>
          </div>
          <div class="hist-filter">
            <button
              v-for="opt in [
                { value: '', label: '全部' },
                { value: 'draft', label: '草稿' },
                { value: 'published', label: '已发布' },
              ]"
              :key="opt.value"
              class="hist-chip"
              :class="{ on: historyStatus === opt.value }"
              type="button"
              @click="historyStatus = opt.value as '' | 'draft' | 'published'"
            >
              {{ opt.label }}
            </button>
          </div>
          <div v-if="listLoading" class="empty-tip small">加载中…</div>
          <div v-else-if="list.length === 0" class="empty-tip small">
            该学员还没有评估记录，选择周期后保存第一份吧
          </div>
          <div v-else class="hist-list">
            <article v-for="e in list" :key="e.id" class="hist-item" :class="{ active: current?.id === e.id }">
              <div class="hist-main" @click="openDetail(e)">
                <div class="hist-title-row">
                  <strong>{{ e.title || '学习评估' }}</strong>
                  <span class="hist-tags">
                    <span v-if="e.ppt_url" class="hist-ppt" title="已生成家长会 PPT">PPT</span>
                    <span class="hist-status" :class="e.status">{{ e.status === 'published' ? '已发布' : '草稿' }}</span>
                  </span>
                </div>
                <p class="hist-period">{{ fmtCnPeriod(e.period_start, e.period_end) }} · {{ e.teacher_name || '教师' }}</p>
                <p class="hist-summary">{{ str(e.content?.summary) || '暂无摘要' }}</p>
              </div>
              <div class="hist-ops">
                <button class="mini-btn" type="button" @click.stop="loadIntoEditor(e)">载入编辑</button>
                <button class="mini-btn ghost" type="button" @click.stop="openDetail(e)">详情</button>
              </div>
            </article>
          </div>
        </section>

        <section v-if="evalTasks.length" class="card">
          <div class="card-head">
            <h2>AI 任务</h2>
            <span class="card-tag">{{ evalTasks.length }}</span>
          </div>
          <div class="task-list">
            <div v-for="t in evalTasks" :key="t.id" class="task-item" :class="{ clickable: isClassPptTask(t) }" @click="isClassPptTask(t) && openClassPpt()">
              <span class="task-dot" :class="t.status" />
              <div class="task-main">
                <strong>{{ t.summary }}</strong>
                <p>{{ t.stage }}</p>
                <button v-if="isClassPptTask(t) && t.status === 'done'" class="mini-btn" type="button" @click.stop="openClassPpt()">
                  查看 / 下载 PPT
                </button>
              </div>
            </div>
          </div>
        </section>
      </div>
    </div>

    <!-- 班级家长会 PPT 面板（以班级为单位，结合全班学员评估生成） -->
    <Teleport to="body">
      <Transition name="confirm-fade">
        <div v-if="classPptOpen" class="class-ppt-overlay" @click.self="classPptOpen = false">
          <div class="class-ppt-panel" role="dialog" aria-modal="true">
            <div class="class-ppt-head">
              <h3>班级家长会 PPT</h3>
              <p>先按校区/教师/班级筛选，再看本班名册中每位学员当前周期的评估完成情况</p>
              <button class="class-ppt-close" title="关闭" @click="classPptOpen = false">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18M6 6l12 12" /></svg>
              </button>
            </div>
            <div class="class-ppt-body">
              <div class="ppt-filter-row">
                <select v-model="pptCampus" class="qk-select">
                  <option value="">全部校区</option>
                  <option value="__unassigned__">未分配</option>
                  <option v-for="c in pptCampuses" :key="c" :value="c">{{ c }}</option>
                </select>
                <SearchableSelect
                  v-model="pptTeacherId"
                  :options="pptTeacherOptions"
                  placeholder="全部教师"
                  group="ppt-teacher"
                />
                <button class="qk-clear" type="button" :disabled="!pptCampus && !pptTeacherId" @click="clearPptFilters">
                  重置筛选
                </button>
                <span class="qk-count">可生成班级 {{ classes.length }} 个</span>
              </div>
              <div class="field">
                <label>选择班级</label>
                <SearchableSelect v-model="classPptClassId" :options="classPptClassOptions" placeholder="从筛选结果中选择班级" />
              </div>
              <div class="field-row">
                <div class="field grow">
                  <label>评估周期起</label>
                  <input v-model="classPptStart" type="date" />
                </div>
                <div class="field grow">
                  <label>评估周期止</label>
                  <input v-model="classPptEnd" type="date" />
                </div>
              </div>
              <div v-if="roster" class="roster-card">
                <div class="roster-head">
                  <strong>本班学员评估（{{ roster.class_name }}）</strong>
                  <div class="roster-stats">
                    <span class="rs-chip total">{{ rosterCounts?.total ?? 0 }} 名学员</span>
                    <span class="rs-chip published">已发布 {{ rosterCounts?.published ?? 0 }}</span>
                    <span class="rs-chip draft">{{ rosterCounts?.draft ?? 0 }} 草稿</span>
                    <span class="rs-chip missing">{{ rosterCounts?.missing ?? 0 }} 未生成</span>
                  </div>
                </div>
                <div v-if="rosterLoading" class="roster-empty">名单加载中…</div>
                <div v-else-if="roster.students.length === 0" class="roster-empty">该班暂无在册学员</div>
                <ul v-else class="roster-list">
                  <li v-for="s in roster.students" :key="s.student_id" class="roster-item">
                    <span class="rv-name">{{ s.name }}</span>
                    <span v-if="s.campus" class="rv-campus">{{ s.campus }}</span>
                    <span class="rv-badge" :class="s.evaluation ? (s.evaluation.status === 'published' ? 'ok' : 'draft') : 'none'">
                      {{ s.evaluation ? (s.evaluation.status === 'published' ? '已生成·已发布' : '已生成·草稿') : '未生成' }}
                    </span>
                    <span class="rv-ops">
                      <button
                        v-if="s.evaluation"
                        type="button"
                        class="rv-btn"
                        title="查看该学员已生成的评估"
                        @click="viewRosterEval(s)"
                      >
                        查看
                      </button>
                      <button
                        v-if="s.evaluation"
                        type="button"
                        class="rv-btn"
                        title="重新生成该学员的本周期评估（学员与周期会自动带过去）"
                        @click="goGenerateForStudent(s)"
                      >
                        重新生成
                      </button>
                      <button
                        v-else
                        type="button"
                        class="rv-btn primary"
                        title="去生成该学员的本周期评估（学员与周期会自动带过去）"
                        @click="goGenerateForStudent(s)"
                      >
                        去生成
                      </button>
                    </span>
                  </li>
                </ul>
              </div>
              <p v-if="rosterError" class="class-ppt-error">{{ rosterError }}</p>
              <div class="field">
                <label>教师补充说明（可选）</label>
                <textarea v-autogrow v-model="classPptNote" rows="3" placeholder="例如：请重点突出编程思维的成长、下阶段的项目展示安排" />
              </div>
              <div v-if="classPptTask && (classPptTask.status === 'pending' || classPptTask.status === 'running')" class="class-ppt-progress">
                <div class="progress-steps">
                  <div
                    v-for="(label, i) in ['排队等待', 'AI 提炼汇报内容', '排版生成 PPT', '完成']"
                    :key="label"
                    class="p-step"
                    :class="{ active: i === classPptStageIndex, done: classPptStageIndex > i }"
                  >
                    <span class="p-dot">{{ classPptStageIndex > i ? '✓' : i + 1 }}</span>
                    <span class="p-label">{{ label }}</span>
                    <span v-if="i < 3" class="p-line" />
                  </div>
                </div>
                <p class="progress-desc">
                  <span class="task-dot" />
                  <template v-if="classPptStageIndex === 0">
                    正在排队：前面还有 AI 任务在执行，完成后自动开始（已等待 {{ classPptElapsed }}）
                  </template>
                  <template v-else>{{ classPptTask.stage }}（已进行 {{ classPptElapsed }}）</template>
                </p>
                <div class="progress-ops">
                  <button class="c-btn" type="button" @click="aiTasks.cancel(classPptTask.id)">取消任务</button>
                  <span class="progress-ops-hint">排队中可秒取消；生成中取消后当前步骤完成即停止</span>
                </div>
              </div>
              <p v-else-if="classPptTask && classPptTask.status === 'failed'" class="class-ppt-error">
                班级 PPT 生成失败：{{ classPptTask.error || '请重试' }}
                <button class="rv-btn primary" type="button" @click="genClassPpt(false)">重新生成</button>
              </p>
              <p v-else-if="classPptTask && classPptTask.status === 'cancelled'" class="class-ppt-tip">
                任务已取消，文案和历史记录未被覆盖，可随时重新生成。
                <button class="rv-btn primary" type="button" @click="genClassPpt(false)">重新生成</button>
              </p>
              <p v-else-if="roster && roster.generated === 0" class="class-ppt-tip warn">
                当前班级在所选周期内还没有学员评估：点学员右侧「去生成」为学员生成评估后，才能结合全员评估生成班级 PPT。
              </p>
              <p v-else-if="roster && roster.published < roster.generated" class="class-ppt-tip warn">
                本班还有 {{ roster.generated - roster.published }} 份评估处于草稿状态：草稿评估也会纳入班级 PPT，建议生成前先发布，确保家长看到的内容已确认。
              </p>
              <p v-else class="class-ppt-tip">
                选好班级与周期后，名单会标出每位学员的评估生成情况；已生成的可在下方逐份查看。
              </p>
              <p v-if="classPptError" class="class-ppt-error">{{ classPptError }}</p>
              <div v-if="classPptResult && classPptResult.ppt_url" class="class-ppt-result">
                <span class="result-badge">已生成</span>
                <div class="result-info">
                  <strong>{{ String(classPptResult.title || '班级家长会 PPT') }}</strong>
                  <span v-if="classPptResult.student_count">含 {{ classPptResult.student_count }} 名学员数据</span>
                </div>
                <a class="result-download" :href="pptDownloadUrl(String(classPptResult.ppt_url))" target="_blank">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3" /></svg>
                  下载 PPT
                </a>
              </div>
              <div v-else-if="classPptRecord && classPptRecord.ppt_url" class="class-ppt-result">
                <span class="result-badge">已生成</span>
                <div class="result-info">
                  <strong>{{ classPptRecord.title || '班级家长会 PPT' }}</strong>
                  <span>
                    {{ fmtCnPeriod(classPptRecord.period_start, classPptRecord.period_end) }}
                    <template v-if="classPptRecord.updated_at"> · 更新于 {{ fmtCnDateKey(classPptRecord.updated_at) }}</template>
                  </span>
                </div>
                <a class="result-download" :href="pptDownloadUrl(classPptRecord.ppt_url)" target="_blank">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3" /></svg>
                  下载 PPT
                </a>
              </div>

              <!-- 预览与编辑：文案落库后可逐字段修改，保存即按新内容秒级重排版 -->
              <div v-if="classPptRecord && classPptRecord.source === 'db' && classPptRecord.record_id" class="ppt-edit-card">
                <div class="ppt-edit-head">
                  <div>
                    <strong>PPT 文案预览与编辑</strong>
                    <p>按幻灯片顺序展示全部文案；修改后保存，PPT 将按新内容重新排版（无需重新调 AI）</p>
                  </div>
                  <span class="ppt-edit-tag">可编辑</span>
                </div>

                <div v-if="classPptRecord.stats" class="ppt-edit-stats">
                  <span class="pe-chip">在读 {{ String(classPptRecord.stats.active_count ?? 0) }}/{{ String(classPptRecord.stats.student_count ?? 0) }} 人</span>
                  <span class="pe-chip">上课 {{ String(classPptRecord.stats.total_lessons ?? 0) }} 人次·节</span>
                  <span class="pe-chip cyan">出勤率 {{ (Number(classPptRecord.stats.avg_attendance_rate ?? 0) * 100).toFixed(0) }}%</span>
                  <span class="pe-chip">反馈 {{ String(classPptRecord.stats.total_feedbacks ?? 0) }} 篇</span>
                  <span class="pe-chip">作业 {{ String(classPptRecord.stats.total_homework ?? 0) }} 份</span>
                  <span v-if="classPptRecord.stats.avg_homework_score_rate != null" class="pe-chip green">
                    得分率 {{ (Number(classPptRecord.stats.avg_homework_score_rate) * 100).toFixed(0) }}%
                  </span>
                </div>

                <div v-if="(classPptRecord.averages || []).length" class="ppt-edit-averages">
                  <span
                    v-for="[name, avg] in (classPptRecord.averages as Array<[string, number]>).slice(0, 6)"
                    :key="name"
                    class="pe-avg"
                  >
                    {{ name }} {{ Number(avg).toFixed(1) }}/5
                  </span>
                </div>

                <div class="pe-field">
                  <label>封面标题（第 1 页）</label>
                  <input v-model="classPptEdit.title" type="text" placeholder="如：Scratch 启蒙班 阶段学习汇报家长会" />
                </div>
                <div class="pe-field">
                  <label>班级整体情况（第 3 页）</label>
                  <textarea v-autogrow v-model="classPptEdit.class_summary" rows="3" placeholder="面向全体家长的整体表现总结（建议 200-350 字）" />
                </div>
                <div class="pe-field">
                  <label>能力培养点评（第 4 页）</label>
                  <textarea v-autogrow v-model="classPptEdit.ability_comment" rows="2" placeholder="结合各能力项班级平均分给出点评（建议 100-180 字）" />
                </div>
                <div class="pe-field">
                  <label>班级亮点（第 5 页）<em>多条用「；」分隔</em></label>
                  <textarea v-autogrow v-model="classPptEdit.highlights" rows="2" placeholder="2-4 条班级亮点，可点名表扬进步突出的学员" />
                </div>
                <div class="pe-field">
                  <label>共性问题与改进（第 7 页）<em>多条用「；」分隔</em></label>
                  <textarea v-autogrow v-model="classPptEdit.to_improve" rows="2" placeholder="2-3 条共性问题与改进措施" />
                </div>
                <div class="pe-field">
                  <label>下阶段教学安排（第 8 页）<em>多条用「；」分隔</em></label>
                  <textarea v-autogrow v-model="classPptEdit.next_plan" rows="2" placeholder="2-4 条：教学内容 / 目标 / 活动" />
                </div>
                <div class="pe-field">
                  <label>给家长的建议（第 9 页）<em>多条用「；」分隔</em></label>
                  <textarea v-autogrow v-model="classPptEdit.home_suggestions" rows="2" placeholder="2-3 条家庭配合建议" />
                </div>

                <p v-if="classPptEditErr" class="class-ppt-error">{{ classPptEditErr }}</p>
                <p v-else-if="classPptEditMsg" class="ppt-edit-ok">{{ classPptEditMsg }}</p>

                <div class="ppt-edit-actions">
                  <button class="pe-btn" type="button" :disabled="classPptEditBusy" @click="syncPptEdit(classPptRecord)">
                    撤销修改
                  </button>
                  <button class="pe-btn primary" type="button" :disabled="classPptEditBusy" @click="saveClassPptEdit">
                    {{ classPptEditBusy ? '保存并重排版中…' : '保存并重新生成 PPT' }}
                  </button>
                </div>
              </div>
            </div>
            <div class="ppt-gen-mode">
              <span class="ppt-gen-mode-label">生成方式</span>
              <button class="gen-mode-btn" :class="{ on: pptGenMode === 'quick' }" type="button" @click="pptGenMode = 'quick'">一键生成</button>
              <button class="gen-mode-btn" :class="{ on: pptGenMode === 'agent' }" type="button" @click="pptGenMode = 'agent'">Agent 定制</button>
              <span class="ppt-gen-mode-hint">{{ pptGenMode === 'quick' ? '结合全班评估一键提炼并排版' : '7 步对话：风格 / 标题 / 大纲 / 重点 / 建议，可自定义' }}</span>
            </div>
            <div class="class-ppt-actions">
              <button class="c-btn" @click="classPptOpen = false">关闭</button>
              <button
                v-if="pptGenMode === 'quick'"
                class="c-btn brand"
                :disabled="classPptBusy || !canGenClassPpt"
                :title="classPptRecord?.source === 'db' ? '将重新调 AI 提炼全班文案并覆盖当前编辑内容' : '结合全班学员评估，AI 提炼班级汇报文案后排版生成'"
                @click="genClassPpt(false)"
              >
                {{ classPptBusy ? '提交中…' : (classPptRecord?.source === 'db' ? 'AI 重新提炼并生成' : '生成班级 PPT') }}
              </button>
              <button
                v-else
                class="c-btn brand"
                :disabled="!canGenClassPpt"
                title="按当前班级与周期进入 Agent 定制流程（7 步向导，可自定义）"
                @click="openAgentPpt"
              >
                下一步：Agent 定制
              </button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- 评估详情弹窗 -->
    <EvaluationDetailDialog
      :visible="detailEv !== null"
      :evaluation="detailEv"
      show-ppt
      @close="detailEv = null"
    />

    <!-- 删除确认 -->
    <ConfirmDialog
      :visible="showDelete"
      title="删除评估"
      :message="`确认删除「${current?.title || '学习评估'}」？删除后不可恢复。`"
      confirm-text="删除"
      danger
      @confirm="doDelete"
      @cancel="showDelete = false"
    />

    <!-- 重提炼二次确认（regen-dedup）：素材无变化时强制重提会覆盖手工编辑，需明确确认 -->
    <ConfirmDialog
      :visible="showRegenConfirm"
      title="素材无变化，仍要重新提炼？"
      :message="`${classPptTip || '全班学员评估与课堂数据自上次生成后无变化。'}强制重提炼将重新调用 AI 生成文案，并覆盖你在「PPT 文案预览与编辑」中的手工修改。`"
      confirm-text="仍要重提炼"
      danger
      @confirm="showRegenConfirm = false; genClassPpt(true)"
      @cancel="showRegenConfirm = false"
    />

    <PptAgentDialog ref="pptAgentRef" />
  </div>
</template>

<style scoped>
.class-ppt-overlay {
  position: fixed;
  inset: 0;
  z-index: 120;
  background: rgba(15, 23, 42, 0.55);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
}

.class-ppt-panel {
  width: 780px;
  max-width: 100%;
  max-height: calc(100vh - 48px);
  display: flex;
  flex-direction: column;
  border-radius: 18px;
  background: var(--surface);
  box-shadow: var(--shadow-lg);
  overflow: hidden;
}

.class-ppt-head {
  position: relative;
  padding: 20px 24px 18px;
  background: linear-gradient(135deg, #312e81, #0e7490);
  color: #fff;
}

.class-ppt-head h3 {
  font-size: 18px;
  margin-bottom: 6px;
}

.class-ppt-head p {
  font-size: 12px;
  color: rgba(241, 245, 249, 0.82);
  line-height: 1.5;
}

.class-ppt-close {
  position: absolute;
  top: 14px;
  right: 14px;
  width: 32px;
  height: 32px;
  border: none;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.14);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
}

.class-ppt-close svg {
  width: 14px;
  height: 14px;
}

.class-ppt-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 18px 24px 10px;
}

/* —— 班级/学员快速筛选 —— */
.quick-filter-bar,
.ppt-filter-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding: 9px 10px;
  margin: 2px 0 12px;
  border-radius: 10px;
  background: #f6f8fc;
  border: 1px solid var(--line);
}

.ppt-filter-row {
  margin-bottom: 14px;
}

.qk-select {
  padding: 8px 11px;
  min-width: 130px;
  max-width: 180px;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: var(--surface);
  font-size: 13px;
  color: var(--ink-2);
}

.qk-clear {
  border: none;
  background: none;
  color: var(--ink-3);
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
  padding: 4px 6px;
}
.qk-clear:hover:not(:disabled) {
  color: var(--brand-strong);
}
.qk-clear:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.qk-count {
  margin-left: auto;
  font-size: 12px;
  color: var(--ink-3);
  white-space: nowrap;
}

/* —— 班级名单（评估生成情况） —— */
.roster-card {
  margin: 4px 0 14px;
  border: 1px solid var(--line);
  border-radius: 12px;
  overflow: hidden;
}

.roster-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
  padding: 10px 12px;
  background: #f8fafc;
  border-bottom: 1px solid var(--line);
}

.roster-head strong {
  font-size: 13px;
  color: var(--ink);
}

.roster-stats {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.rs-chip {
  padding: 3px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
}
.rs-chip.total {
  background: var(--brand-soft);
  color: var(--brand-strong);
}
.rs-chip.published {
  background: var(--success-soft);
  color: #047857;
}
.rs-chip.draft {
  background: var(--warning-soft);
  color: #b45309;
}
.rs-chip.missing {
  background: var(--danger-soft);
  color: var(--danger);
}

.roster-list {
  list-style: none;
  margin: 0;
  padding: 0;
  max-height: 252px;
  overflow-y: auto;
}

.roster-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 12px;
  border-bottom: 1px solid #f1f5f9;
}
.roster-item:last-child {
  border-bottom: none;
}
.roster-item:hover {
  background: #f8fafc;
}

.rv-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--ink);
  min-width: 64px;
}

.rv-campus {
  font-size: 11.5px;
  color: var(--ink-3);
  background: #eef2f7;
  border-radius: 6px;
  padding: 2px 7px;
}

.rv-badge {
  font-size: 11.5px;
  font-weight: 700;
  padding: 3px 9px;
  border-radius: 999px;
}
.rv-badge.ok {
  background: var(--success-soft);
  color: #047857;
}
.rv-badge.draft {
  background: var(--warning-soft);
  color: #b45309;
}
.rv-badge.none {
  background: var(--line);
  color: var(--ink-3);
}

.rv-ops {
  margin-left: auto;
  display: flex;
  gap: 6px;
}

.rv-btn {
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--ink-2);
  font-size: 12px;
  font-weight: 600;
  padding: 4px 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.15s;
}
.rv-btn:hover {
  border-color: var(--brand);
  color: var(--brand-strong);
}
.rv-btn.primary {
  border-color: transparent;
  background: linear-gradient(135deg, #6366f1, #06b6d4);
  color: #fff;
}
.rv-btn.primary:hover {
  filter: brightness(1.05);
}

.roster-empty {
  padding: 16px;
  text-align: center;
  font-size: 12.5px;
  color: var(--ink-3);
}

.class-ppt-tip.warn {
  color: #b45309;
}

.class-ppt-tip {
  font-size: 12px;
  color: var(--ink-3);
  line-height: 1.6;
  margin-top: 4px;
}

.class-ppt-status {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-radius: 999px;
  background: var(--accent-soft);
  border: 1px solid #bae6fd;
  color: #0e7490;
  font-size: 12px;
  font-weight: 600;
  margin: 4px 0 10px;
}

/* —— 班级 PPT 生成进度步骤条 —— */
.class-ppt-progress {
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 14px 16px 12px;
  background: var(--bg);
  margin: 4px 0 10px;
}

.progress-steps {
  display: flex;
  align-items: flex-start;
}

.p-step {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  position: relative;
  gap: 6px;
  min-width: 0;
}

.p-dot {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11.5px;
  font-weight: 700;
  background: #e2e8f0;
  color: var(--ink-3);
  z-index: 1;
}

.p-step.done .p-dot {
  background: var(--success-soft);
  color: #047857;
}

.p-step.active .p-dot {
  background: linear-gradient(135deg, #6366f1, #06b6d4);
  color: #fff;
  box-shadow: 0 0 0 4px rgba(99, 102, 241, 0.15);
}

.p-label {
  font-size: 11.5px;
  color: var(--ink-3);
  white-space: nowrap;
}

.p-step.active .p-label {
  color: var(--brand-strong);
  font-weight: 700;
}

.p-step.done .p-label {
  color: #047857;
}

.p-line {
  position: absolute;
  top: 10px;
  left: calc(50% + 16px);
  right: calc(-50% + 16px);
  height: 2px;
  background: #e2e8f0;
  border-radius: 1px;
}

.p-step.done .p-line {
  background: #34d399;
}

.progress-desc {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 12px 0 0;
  padding-top: 10px;
  border-top: 1px dashed var(--line);
  font-size: 12.5px;
  color: var(--ink-2);
  line-height: 1.5;
}

.progress-desc .task-dot {
  margin-top: 0;
  flex-shrink: 0;
}

.task-item.clickable {
  cursor: pointer;
  border-radius: 10px;
  transition: background 0.15s;
}

.task-item.clickable:hover {
  background: var(--brand-soft);
}

.class-ppt-error {
  margin-top: 6px;
  color: var(--danger);
  font-size: 12.5px;
  background: var(--danger-soft);
  border-radius: 10px;
  padding: 8px 12px;
}

.class-ppt-result {
  display: flex;
  align-items: center;
  gap: 10px;
  justify-content: space-between;
  margin-top: 14px;
  padding: 12px 14px;
  border-radius: 12px;
  border: 1px solid #dbeafe;
  background: #eff6ff;
}

.result-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 4px 8px;
  border-radius: 999px;
  background: #dbeafe;
  color: #1d4ed8;
  font-size: 11px;
  font-weight: 700;
  flex-shrink: 0;
}

.result-info {
  flex: 1;
  min-width: 0;
}

.result-info strong {
  display: block;
  font-size: 13.5px;
  color: var(--ink);
}

.result-info span {
  display: block;
  margin-top: 2px;
  font-size: 12px;
  color: var(--ink-3);
}

.result-download {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  border-radius: 10px;
  background: linear-gradient(135deg, #6366f1, #06b6d4);
  color: #fff;
  font-size: 12.5px;
  font-weight: 600;
  text-decoration: none;
}

.result-download svg {
  width: 14px;
  height: 14px;
}

.class-ppt-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 12px 24px 20px;
}

/* —— PPT 文案预览与编辑 —— */
.ppt-edit-card {
  margin-top: 14px;
  border: 1px solid #c7d2fe;
  border-radius: 14px;
  background: #f8faff;
  padding: 14px 16px 16px;
}

.ppt-edit-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 12px;
}

.ppt-edit-head strong {
  font-size: 13.5px;
  color: var(--ink);
}

.ppt-edit-head p {
  font-size: 11.5px;
  color: var(--ink-3);
  margin-top: 3px;
  line-height: 1.5;
}

.ppt-edit-tag {
  flex-shrink: 0;
  font-size: 11px;
  font-weight: 700;
  padding: 3px 10px;
  border-radius: 999px;
  background: var(--brand-soft);
  color: var(--brand-strong);
  border: 1px solid #c7d2fe;
}

.ppt-edit-stats {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}

.pe-chip {
  font-size: 11.5px;
  font-weight: 600;
  color: var(--ink-2);
  background: var(--surface);
  border: 1px solid var(--line);
  padding: 3px 10px;
  border-radius: 999px;
}

.pe-chip.cyan {
  background: var(--accent-soft);
  border-color: #bae6fd;
  color: #0e7490;
}

.pe-chip.green {
  background: var(--success-soft);
  border-color: #a7f3d0;
  color: #047857;
}

.ppt-edit-averages {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.pe-avg {
  font-size: 11.5px;
  font-weight: 700;
  color: var(--brand-strong);
  background: var(--brand-soft);
  border-radius: 8px;
  padding: 3px 9px;
}

.pe-field {
  display: flex;
  flex-direction: column;
  gap: 5px;
  margin-bottom: 11px;
}

.pe-field label {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--ink-2);
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.pe-field em {
  font-style: normal;
  font-weight: 400;
  font-size: 11px;
  color: var(--ink-3);
}

.pe-field input,
.pe-field textarea {
  border: 1px solid var(--line);
  border-radius: 9px;
  padding: 8px 11px;
  font-size: 13px;
  font-family: inherit;
  background: var(--surface);
  color: var(--ink);
  resize: vertical;
  transition: border-color 0.15s, box-shadow 0.15s;
}

.pe-field input:focus,
.pe-field textarea:focus {
  outline: none;
  border-color: var(--brand);
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.12);
}

.progress-ops {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 10px;
}
.progress-ops-hint {
  font-size: 11.5px;
  color: var(--ink-3);
}
.ppt-edit-ok {
  font-size: 12px;
  color: #047857;
  background: var(--success-soft);
  border-radius: 9px;
  padding: 7px 11px;
  margin-top: 2px;
}

.ppt-edit-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 10px;
}

.pe-btn {
  padding: 8px 14px;
  border-radius: 9px;
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--ink-2);
  font-size: 12.5px;
  font-weight: 600;
  font-family: inherit;
  cursor: pointer;
  transition: all 0.15s;
}

.pe-btn:hover:not(:disabled) {
  border-color: var(--brand);
  color: var(--brand-strong);
}

.pe-btn.primary {
  background: linear-gradient(135deg, #6366f1, #06b6d4);
  border-color: transparent;
  color: #fff;
}

.pe-btn.primary:hover:not(:disabled) {
  filter: brightness(1.05);
  color: #fff;
}

.pe-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.ppt-gen-mode {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin: 12px 0 4px;
  padding: 10px 12px;
  border-radius: 12px;
  background: #f8faff;
  border: 1px solid #c7d2fe;
}
.ppt-gen-mode-label {
  font-size: 12.5px;
  font-weight: 700;
  color: var(--brand-strong);
}
.gen-mode-btn {
  padding: 6px 14px;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--ink-2);
  font-size: 12.5px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.15s;
}
.gen-mode-btn:hover {
  border-color: var(--brand);
  color: var(--brand-strong);
}
.gen-mode-btn.on {
  background: linear-gradient(135deg, #6366f1, #06b6d4);
  border-color: transparent;
  color: #fff;
}
.ppt-gen-mode-hint {
  font-size: 11.5px;
  color: var(--ink-3);
}

.c-btn {
  min-width: 90px;
  padding: 9px 18px;
  border-radius: 10px;
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--ink-2);
  font-size: 13px;
  font-weight: 600;
  font-family: inherit;
  cursor: pointer;
  transition: all 0.15s;
}

.c-btn:hover {
  border-color: var(--brand);
  color: var(--brand-strong);
}

.c-btn.brand {
  background: linear-gradient(135deg, #6366f1, #06b6d4);
  color: #fff;
  border-color: transparent;
}

.c-btn.brand:hover {
  filter: brightness(1.05);
}

.c-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.eval-page {
  max-width: 1280px;
}

/* —— 页头 —— */
.page-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 18px;
}

.head-title-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.page-head h1 {
  font-size: 22px;
  margin: 0;
}

.sub {
  color: var(--ink-3);
  font-size: 13px;
  margin-top: 4px;
}

.status-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
}

.status-pill .pill-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}

.status-pill.draft {
  background: var(--warning-soft);
  color: #b45309;
}

.status-pill.published {
  background: var(--success-soft);
  color: #047857;
}

.ops {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.op-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  border-radius: 10px;
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--ink-2);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}

.op-btn svg {
  width: 14px;
  height: 14px;
}

.op-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.op-btn.ghost:hover:not(:disabled) {
  border-color: var(--brand);
  color: var(--brand-strong);
}

.op-btn.primary {
  background: linear-gradient(135deg, #6366f1, #06b6d4);
  border-color: transparent;
  color: #fff;
  box-shadow: 0 3px 12px rgba(99, 102, 241, 0.3);
}

.op-btn.primary:hover:not(:disabled) {
  filter: brightness(1.06);
}

.op-btn.ai {
  background: var(--brand-soft);
  border-color: #c7d2fe;
  color: var(--brand-strong);
}

.op-btn.ai:hover:not(:disabled) {
  filter: brightness(0.98);
  box-shadow: 0 3px 10px rgba(99, 102, 241, 0.2);
}

.op-btn.ai-solid {
  background: linear-gradient(135deg, #6366f1, #06b6d4);
  border: none;
  color: #fff;
  flex-shrink: 0;
  align-self: flex-end;
}

.op-btn.download {
  background: var(--accent-soft);
  border-color: #bae6fd;
  color: #0e7490;
  text-decoration: none;
}

.op-btn.download:hover {
  filter: brightness(0.99);
  box-shadow: 0 3px 10px rgba(6, 182, 212, 0.2);
}

.op-btn.danger-ghost {
  color: var(--danger);
}

.op-btn.danger-ghost:hover:not(:disabled) {
  border-color: var(--danger);
  background: var(--danger-soft);
}

/* —— 提示条 —— */
.banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  border-radius: 10px;
  font-size: 13px;
  margin-bottom: 14px;
}

.banner svg {
  width: 15px;
  height: 15px;
  flex-shrink: 0;
}

.banner.error {
  background: var(--danger-soft);
  color: #b91c1c;
}

.banner.ok {
  background: var(--success-soft);
  color: #047857;
}

.banner-fade-enter-active,
.banner-fade-leave-active {
  transition: all 0.2s ease;
}

.banner-fade-enter-from,
.banner-fade-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}

.loading-tip {
  text-align: center;
  color: var(--ink-3);
  font-size: 13px;
  padding: 24px 0;
}

/* —— 布局 —— */
.work-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.55fr) minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}

.side-col {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.card {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 16px;
  padding: 20px 22px;
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 16px;
}

.card-head h2 {
  font-size: 15.5px;
}

.card-tag {
  font-size: 12px;
  color: var(--ink-3);
  background: var(--bg);
  border: 1px solid var(--line);
  padding: 3px 10px;
  border-radius: 999px;
}

.mini-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 12px;
  border-radius: 8px;
  border: 1px solid #c7d2fe;
  background: var(--brand-soft);
  color: var(--brand-strong);
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}

.mini-btn svg {
  width: 13px;
  height: 13px;
}

.mini-btn:hover {
  filter: brightness(0.98);
  box-shadow: 0 2px 8px rgba(99, 102, 241, 0.18);
}

.mini-btn.ghost {
  background: var(--surface);
  border-color: var(--line);
  color: var(--ink-2);
}

.mini-btn.ghost:hover {
  border-color: var(--brand);
  color: var(--brand-strong);
  box-shadow: none;
}

/* 快捷周期预设组 */
.preset-row {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.preset-label {
  font-size: 11.5px;
  color: var(--ink-3);
  margin-right: 2px;
}

/* 学员信息条 */
.student-brief {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin: -6px 0 14px;
}

.brief-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11.5px;
  font-weight: 600;
  color: var(--ink-2);
  background: var(--bg);
  border: 1px solid var(--line);
  padding: 3px 11px;
  border-radius: 999px;
}

.brief-chip.warn {
  background: var(--warning-soft);
  border-color: #fde68a;
  color: #b45309;
}
.brief-chip.cls {
  background: var(--brand-soft);
  border-color: transparent;
  color: var(--brand-strong);
}
.brief-chip.muted {
  color: var(--ink-3);
}

/* 历史评估筛选 */
.hist-filter {
  display: flex;
  gap: 6px;
  margin-bottom: 12px;
}

.hist-chip {
  padding: 4px 13px;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--ink-3);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}

.hist-chip:hover {
  border-color: var(--brand);
  color: var(--brand-strong);
}

.hist-chip.on {
  background: var(--brand-soft);
  border-color: #c7d2fe;
  color: var(--brand-strong);
}

.hist-tags {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  flex-shrink: 0;
}

.hist-ppt {
  font-size: 10.5px;
  font-weight: 800;
  letter-spacing: 0.04em;
  padding: 2px 8px;
  border-radius: 999px;
  background: var(--accent-soft);
  border: 1px solid #bae6fd;
  color: #0e7490;
}

/* —— 表单 —— */
.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 14px;
}

.field label {
  font-size: 13px;
  font-weight: 600;
  color: var(--ink-2);
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.field-hint {
  font-style: normal;
  font-weight: 400;
  font-size: 11.5px;
  color: var(--ink-3);
}

.field input,
.field textarea {
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 9px 12px;
  font-size: 13.5px;
  font-family: inherit;
  background: var(--surface);
  color: var(--ink);
  transition: border-color 0.15s, box-shadow 0.15s;
  resize: vertical;
}

.field input:focus,
.field textarea:focus {
  outline: none;
  border-color: var(--brand);
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.12);
}

.field-row {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.field-row .field {
  margin-bottom: 14px;
}

.field-row .grow {
  flex: 1;
  min-width: 200px;
}

.field-row .field:not(.grow) {
  width: 168px;
}

/* —— 学科能力 —— */
.subject-block {
  margin-bottom: 14px;
}

.subject-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 8px;
}

.subject-head label {
  font-size: 13px;
  font-weight: 600;
  color: var(--ink-2);
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.subject-empty {
  border: 1px dashed var(--line);
  border-radius: 10px;
  padding: 14px;
  font-size: 12.5px;
  color: var(--ink-3);
  text-align: center;
}

.subject-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.subject-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--bg);
  transition: border-color 0.15s;
}

.subject-row:focus-within {
  border-color: #c7d2fe;
  background: var(--surface);
}

.subject-row input {
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 6px 10px;
  font-size: 13px;
  font-family: inherit;
  background: var(--surface);
}

.subject-row input:focus {
  outline: none;
  border-color: var(--brand);
}

.sr-name {
  width: 130px;
  flex-shrink: 0;
}

.sr-comment {
  flex: 1;
  min-width: 0;
}

.star-edit {
  display: flex;
  align-items: center;
  gap: 1px;
  flex-shrink: 0;
}

.star-btn {
  border: none;
  background: transparent;
  font-size: 17px;
  line-height: 1;
  color: #e2e8f0;
  cursor: pointer;
  padding: 1px;
  transition: color 0.12s, transform 0.12s;
}

.star-btn.on {
  color: #f59e0b;
}

.star-btn:hover {
  transform: scale(1.15);
}

.level-label {
  font-size: 11px;
  color: var(--ink-3);
  margin-left: 6px;
  width: 48px;
}

.row-del {
  width: 26px;
  height: 26px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: var(--ink-3);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  flex-shrink: 0;
  transition: all 0.15s;
}

.row-del svg {
  width: 13px;
  height: 13px;
}

.row-del:hover {
  background: var(--danger-soft);
  color: var(--danger);
}

.row-enter-active,
.row-leave-active {
  transition: all 0.18s ease;
}

.row-enter-from,
.row-leave-to {
  opacity: 0;
  transform: translateX(-8px);
}

/* —— AI 面板 —— */
.ai-panel {
  margin-top: 6px;
  border-radius: 14px;
  padding: 16px 18px;
  background:
    radial-gradient(420px 160px at 110% -30%, rgba(255, 255, 255, 0.22), transparent 60%),
    linear-gradient(135deg, #312e81, #0e7490);
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.ai-panel-head {
  display: flex;
  align-items: center;
  gap: 10px;
}

.ai-spark {
  width: 34px;
  height: 34px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.16);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.ai-spark svg {
  width: 17px;
  height: 17px;
}

.ai-panel-head h3 {
  color: #fff;
  font-size: 14.5px;
}

.ai-panel-head p {
  color: rgba(241, 245, 249, 0.72);
  font-size: 12px;
  margin-top: 2px;
}

.ai-row {
  display: flex;
  gap: 10px;
  align-items: flex-end;
}

.ai-row textarea {
  flex: 1;
  border: 1px solid rgba(255, 255, 255, 0.25);
  border-radius: 10px;
  padding: 9px 12px;
  font-size: 13px;
  font-family: inherit;
  background: rgba(255, 255, 255, 0.1);
  color: #f1f5f9;
  resize: vertical;
}

.ai-row textarea::placeholder {
  color: rgba(241, 245, 249, 0.55);
}

.ai-row textarea:focus {
  outline: none;
  border-color: rgba(255, 255, 255, 0.55);
  background: rgba(255, 255, 255, 0.14);
}

.ai-hint {
  font-size: 12px;
  color: rgba(241, 245, 249, 0.7);
}

/* —— 素材预览 —— */
.stat-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
  margin-bottom: 14px;
}

.stat-cell {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  padding: 10px 6px;
  border-radius: 12px;
  background: var(--bg);
  border: 1px solid var(--line);
}

.stat-cell strong {
  font-size: 16px;
  font-weight: 800;
  color: var(--ink);
  letter-spacing: -0.01em;
}

.stat-cell span {
  font-size: 11px;
  color: var(--ink-3);
}

.stat-cell.cyan {
  background: var(--accent-soft);
  border-color: #bae6fd;
}

.stat-cell.cyan strong {
  color: #0e7490;
}

.stat-cell.green {
  background: var(--success-soft);
  border-color: #a7f3d0;
}

.stat-cell.green strong {
  color: #047857;
}

.side-sub {
  font-size: 12px;
  font-weight: 600;
  color: var(--ink-3);
  margin-bottom: 8px;
}

.fb-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.fb-item {
  border: 1px solid #eef2f7;
  border-radius: 12px;
  padding: 10px 12px;
  background: var(--surface);
  transition: border-color 0.15s;
}

.fb-item:hover {
  border-color: #c7d2fe;
}

.fb-item-head strong {
  font-size: 12.5px;
  color: var(--ink);
}

.fb-topic {
  font-size: 12px;
  color: var(--brand-strong);
  margin-top: 3px;
  font-weight: 600;
}

.fb-text {
  font-size: 12.5px;
  line-height: 1.65;
  color: var(--ink-2);
  margin-top: 4px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* —— 历史评估 —— */
.hist-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.hist-item {
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 12px 14px;
  transition: border-color 0.15s, box-shadow 0.15s;
}

.hist-item:hover {
  border-color: #c7d2fe;
  box-shadow: var(--shadow-sm);
}

.hist-item.active {
  border-color: var(--brand);
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.1);
}

.hist-main {
  cursor: pointer;
}

.hist-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.hist-title-row strong {
  font-size: 13.5px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.hist-status {
  flex-shrink: 0;
  font-size: 11px;
  font-weight: 700;
  padding: 2px 9px;
  border-radius: 999px;
}

.hist-status.published {
  background: var(--success-soft);
  color: #047857;
}

.hist-status.draft {
  background: var(--warning-soft);
  color: #b45309;
}

.hist-period {
  font-size: 11.5px;
  color: var(--ink-3);
  margin-top: 4px;
}

.hist-summary {
  font-size: 12.5px;
  color: var(--ink-2);
  margin-top: 6px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.hist-ops {
  display: flex;
  gap: 8px;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed #eef2f7;
}

/* —— AI 任务 —— */
.task-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.task-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}

.task-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-top: 6px;
  flex-shrink: 0;
  background: var(--warning);
  animation: task-pulse 1.2s infinite;
}

.task-dot.done {
  background: var(--success);
  animation: none;
}

.task-dot.failed {
  background: var(--danger);
  animation: none;
}

@keyframes task-pulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.35;
  }
}

.task-main strong {
  font-size: 13px;
}

.task-main p {
  font-size: 12px;
  color: var(--ink-3);
  margin-top: 2px;
}

/* —— 空态 —— */
.empty-tip {
  text-align: center;
  color: var(--ink-3);
  font-size: 13px;
  padding: 22px 12px;
  background: var(--bg);
  border: 1px dashed var(--line);
  border-radius: 12px;
}

.empty-tip.small {
  padding: 14px 10px;
  font-size: 12.5px;
}

/* —— 响应式 —— */
@media (max-width: 1080px) {
  .work-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 640px) {
  .subject-row {
    flex-wrap: wrap;
  }
  .sr-name {
    width: 100%;
  }
  .star-edit {
    width: 100%;
    justify-content: flex-start;
  }
  .field-row .field:not(.grow) {
    width: calc(50% - 6px);
  }
  .ops {
    width: 100%;
  }
}
</style>
