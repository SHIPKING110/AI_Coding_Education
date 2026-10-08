<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { listCampusesApi, listTeachersApi, type UserOut } from '@/api/auth'
import { listClasses, type ClassOut } from '@/api/enrollment'
import {
  aiEnhanceFeedback,
  createFeedback,
  getFeedbackStats,
  listCompletedSchedules,
  listFeedbackEditorRows,
  publishFeedback,
  unpublishFeedback,
  updateFeedback,
  uploadFeedbackMedia,
  type CompletedScheduleOut,
  type FeedbackEditorRow,
  type FeedbackStats as Stats,
} from '@/api/feedback'
import {
  createPromptTemplate,
  deletePromptTemplate,
  listPromptTemplates,
  publishPromptTemplate,
  unpublishPromptTemplate,
  updatePromptTemplate,
  type PromptTemplateOut,
} from '@/api/prompt'
import { useAuthStore } from '@/stores/auth'
import PageHead from '@/components/PageHead.vue'
import SearchableSelect from '@/components/SearchableSelect.vue'
import { addDays, dayKey, fmtDateTimeFromIso, mondayOf, toLocalNaiveIso } from '@/utils/date'

// —— 筛选：校区 / 教师（可搜索）/ 班级（可选可搜索）/ 日期区间（默认本周） ——
const campuses = ref<string[]>([])
const campus = ref('')
const teacherOptions = ref<{ id: string; label: string }[]>([])
const teacherId = ref('')
const classOptions = ref<{ id: string; label: string }[]>([])
const classId = ref('')
const dateStart = ref(dayKey(mondayOf(new Date())))
const dateEnd = ref(dayKey(addDays(mondayOf(new Date()), 6)))
const filtersLoading = ref(false)

const stats = ref<Stats>({
  schedule_count: 0,
  expected: 0,
  attended: 0,
  leave: 0,
  feedback_done: 0,
  pending: 0,
})

// —— 已完成排课列表（只有上过的课才进入反馈模块） ——
const completedSchedules = ref<CompletedScheduleOut[]>([])
const selectedScheduleId = ref('')
const selectedSchedule = computed(() =>
  completedSchedules.value.find((s) => s.id === selectedScheduleId.value),
)

interface FbRow {
  student_id: string
  student_name: string
  attendance_status: string // attended | leave | unmarked
  feedback_id: string | null
  title: string
  topic: string
  content: string
  performance: string
  evaluation: string
  homework: string
  media_urls: string[]
  status: string // draft | published
  saving: boolean
  uploading: boolean
  aiLoading: boolean
}

const rows = ref<FbRow[]>([])
const loading = ref(false)
const error = ref('')
const notice = ref('')

const showBatch = ref(false)
const batch = ref({ title: '', topic: '', content: '', performance: '', evaluation: '', homework: '' })

// —— AI 生成弹窗（选择提示词模板 → 生成课堂评价） ——
const showAiModal = ref(false)
const aiRow = ref<FbRow | null>(null)
const aiTemplates = ref<PromptTemplateOut[]>([])
const aiTemplateId = ref('')
const aiGenerating = ref(false)
// 后台任务态：关闭弹窗后仍保留，顶部进度条持续展示直到完成
const aiTaskName = ref('')
const aiTaskFeedbackId = ref('')
const aiElapsed = ref(0)
let aiTimer: ReturnType<typeof setInterval> | null = null
function startAiTimer() {
  stopAiTimer()
  aiElapsed.value = 0
  aiTimer = setInterval(() => {
    aiElapsed.value += 1
  }, 1000)
}
function stopAiTimer() {
  if (aiTimer) {
    clearInterval(aiTimer)
    aiTimer = null
  }
}
const aiSelectedTemplate = computed(
  () => aiTemplates.value.find((t) => t.id === aiTemplateId.value) ?? null,
)
const aiTplError = ref('')
const aiUsedCount = ref(0)
// 是否已提示过「AI 需要先保存反馈」的引导
const aiSaveHintShown = ref(false)

// —— 提示词模板管理弹窗 ——
const showTplModal = ref(false)
const tplTemplates = ref<PromptTemplateOut[]>([])
const tplLoading = ref(false)
const tplError = ref('')
const tplNotice = ref('')
const tplForm = ref({ name: '', content: '' })
const tplEditing = ref<PromptTemplateOut | null>(null)

const auth = useAuthStore()
const isAdmin = computed(() => auth.user?.role === 'admin')

const mediaInput = ref<HTMLInputElement | null>(null)
const activeRow = ref<FbRow | null>(null)

function clearNotice() {
  notice.value = ''
}

function showError(msg: string) {
  error.value = msg
  setTimeout(() => (error.value = ''), 5000)
}
function showNotice(msg: string) {
  notice.value = msg
  setTimeout(clearNotice, 3000)
}

async function loadCampuses() {
  try {
    campuses.value = await listCampusesApi()
  } catch {
    campuses.value = []
  }
}

/** 反馈筛选区间：end 取结束日次日 00:00（闭开区间），确保包含结束日当天全天的排课 */
function feedbackQuery() {
  return {
    campus: campus.value || undefined,
    teacher_id: teacherId.value || undefined,
    class_id: classId.value || undefined,
    start: dateStart.value ? toLocalNaiveIso(new Date(`${dateStart.value}T00:00:00`)) : undefined,
    end: dateEnd.value
      ? toLocalNaiveIso(addDays(new Date(`${dateEnd.value}T00:00:00`), 1))
      : undefined,
  }
}

async function loadTeacherOptions() {
  // 教师下拉只显示所选校区的教师（未选校区则显示全部）
  try {
    const p = await listTeachersApi({ campus: campus.value || undefined, limit: 500 })
    teacherOptions.value = p.items.map((t: UserOut) => ({
      id: t.id,
      label: t.campus ? `${t.name}（${t.campus}）` : t.name,
    }))
    // 若当前选中的教师在新的校区教师列表里不存在，自动清空
    if (teacherId.value && !teacherOptions.value.some((o) => o.id === teacherId.value)) {
      teacherId.value = ''
    }
  } catch {
    teacherOptions.value = []
  }
}

async function loadClassOptions() {
  // 班级下拉：未选教师=按校区过滤（该校区教师的班级）；选了教师=仅该教师班级
  try {
    const p = await listClasses({
      campus: campus.value || undefined,
      teacher_id: teacherId.value || undefined,
      limit: 500,
    })
    classOptions.value = p.items.map((c: ClassOut) => ({
      id: c.id,
      label: c.name,
    }))
    if (classId.value && !classOptions.value.some((o) => o.id === classId.value)) {
      classId.value = ''
    }
  } catch {
    classOptions.value = []
  }
}

async function loadAll() {
  filtersLoading.value = true
  try {
    const q = feedbackQuery()
    ;[completedSchedules.value, stats.value] = await Promise.all([
      listCompletedSchedules(q),
      getFeedbackStats(q),
    ])
    // 保留之前选中的排课（若仍在该筛选结果中）
    if (
      selectedScheduleId.value &&
      !completedSchedules.value.some((s) => s.id === selectedScheduleId.value)
    ) {
      selectedScheduleId.value = ''
      rows.value = []
    }
  } catch {
    showError('加载失败')
  } finally {
    filtersLoading.value = false
  }
}

function selectSchedule(id: string) {
  selectedScheduleId.value = id
  loadRows(id)
}

async function loadRows(scheduleId: string) {
  loading.value = true
  error.value = ''
  try {
    const list = await listFeedbackEditorRows(scheduleId)
    rows.value = list.map((r: FeedbackEditorRow) => ({
      student_id: r.student_id,
      student_name: r.student_name || '',
      attendance_status: r.attendance_status,
      feedback_id: r.feedback?.id ?? null,
      title: r.feedback?.title ?? '',
      topic: r.feedback?.topic ?? '',
      content: r.feedback?.content ?? '',
      performance: r.feedback?.performance ?? '',
      evaluation: r.feedback?.evaluation ?? '',
      homework: r.feedback?.homework ?? '',
      media_urls: r.feedback?.media_urls ?? [],
      status: r.feedback?.status ?? 'draft',
      saving: false,
      uploading: false,
      aiLoading: false,
    }))
  } catch {
    showError('加载学员反馈失败')
  } finally {
    loading.value = false
  }
}

/** 待反馈的学员 = 签到(attended) 且未发布反馈 */
function isPending(r: FbRow): boolean {
  return r.attendance_status === 'attended' && r.status !== 'published'
}
const editableRows = computed(() => rows.value.filter((r) => r.attendance_status === 'attended'))
const absentRows = computed(() => rows.value.filter((r) => r.attendance_status === 'leave'))

function openBatch() {
  batch.value = { title: '', topic: '', content: '', performance: '', evaluation: '', homework: '' }
  showBatch.value = true
}

async function applyBatch() {
  rows.value.forEach((r) => {
    if (r.attendance_status !== 'attended') return // 请假/未标记不填反馈
    if (batch.value.title) r.title = batch.value.title
    if (batch.value.topic) r.topic = batch.value.topic
    if (batch.value.content) r.content = batch.value.content
    if (batch.value.performance) r.performance = batch.value.performance
    if (batch.value.evaluation) r.evaluation = batch.value.evaluation
    if (batch.value.homework) r.homework = batch.value.homework
  })
  showBatch.value = false
  showNotice(`已批量填入 ${editableRows.value.length} 名签到学员的反馈`)
}

/** 打开 AI 生成弹窗：未保存时先引导自动保存（生成需要 feedback_id） */
async function openAiModal(r: FbRow) {
  if (!r.feedback_id) {
    if (!aiSaveHintShown.value) {
      aiSaveHintShown.value = true
      showError(`「${r.student_name}」还没有反馈记录，AI 生成前需要先保存一次（将自动保存当前内容）`)
    }
    r.saving = true
    try {
      const s = selectedSchedule.value
      if (!s) return
      const f = await createFeedback({
        schedule_id: s.id,
        student_id: r.student_id,
        title: r.title || null,
        topic: r.topic || null,
        content: r.content || null,
        performance: r.performance || null,
        evaluation: r.evaluation || null,
        homework: r.homework || null,
        media_urls: r.media_urls,
      })
      r.feedback_id = f.id
      r.status = f.status
      showNotice(`「${r.student_name}」已自动保存，可以继续生成 AI 课堂评价`)
    } catch (e: any) {
      showError(e?.response?.data?.detail || '自动保存失败，请先手动保存')
      return
    } finally {
      r.saving = false
    }
  }
  // 加载可选模板并打开弹窗
  try {
    aiTemplates.value = await listPromptTemplates('feedback')
    aiTemplateId.value = aiTemplates.value[0]?.id ?? ''
    aiTplError.value = ''
  } catch {
    aiTemplates.value = []
    aiTemplateId.value = ''
    aiTplError.value = '提示词模板加载失败'
  }
  aiRow.value = r
  showAiModal.value = true
}

/** AI 生成/润色课堂评价（FR-FB-03）：提交后即进后台，关闭弹窗不中断，顶部进度条持续展示 */
async function aiEnhance() {
  const r = aiRow.value
  if (!r || !r.feedback_id) return
  if (!aiTemplateId.value) {
    aiTplError.value = '请选择提示词模板'
    return
  }
  if (aiGenerating.value) {
    aiTplError.value = '已有 AI 任务在后台生成中，请等待完成后再提交'
    return
  }
  // 快照提交参数：生成期间用户改表单不影响本次任务；完成后按 feedback_id 回填
  const fid = r.feedback_id
  const payload = {
    title: r.title || null,
    topic: r.topic || null,
    content: r.content || null,
    performance: r.performance || null,
    evaluation: r.evaluation || null,
    homework: r.homework || null,
    template_id: aiTemplateId.value,
  }
  aiGenerating.value = true
  aiTplError.value = ''
  aiTaskName.value = r.student_name
  aiTaskFeedbackId.value = fid
  startAiTimer()
  showAiModal.value = false
  showNotice(`AI 正在后台生成「${r.student_name}」的课堂评价（约 20-60 秒），完成后自动回填`)
  try {
    const draft = await aiEnhanceFeedback(fid, payload)
    const target = rows.value.find((x) => x.feedback_id === fid)
    if (target && draft.evaluation != null) target.evaluation = draft.evaluation
    if (aiRow.value && aiRow.value.feedback_id === fid && draft.evaluation != null) {
      aiRow.value.evaluation = draft.evaluation
    }
    aiUsedCount.value += 1
    showNotice(`「${aiTaskName.value}」AI 课堂评价已生成，已回填到课堂评价框，可继续编辑或再次润色`)
  } catch (e: any) {
    const msg = e?.response?.data?.detail || 'AI 课堂评价生成失败'
    aiTplError.value = msg
    showError(msg)
    // 失败时重新打开弹窗方便重试
    if (aiRow.value && aiRow.value.feedback_id === fid) showAiModal.value = true
  } finally {
    aiGenerating.value = false
    aiTaskName.value = ''
    aiTaskFeedbackId.value = ''
    stopAiTimer()
  }
}

// —— 提示词模板管理 ——
async function loadTplTemplates() {
  tplLoading.value = true
  tplError.value = ''
  try {
    tplTemplates.value = await listPromptTemplates('feedback')
  } catch {
    tplError.value = '提示词模板加载失败'
  } finally {
    tplLoading.value = false
  }
}

function openTplModal() {
  tplEditing.value = null
  tplForm.value = { name: '', content: '' }
  tplNotice.value = ''
  loadTplTemplates()
  showTplModal.value = true
}

function editTpl(t: PromptTemplateOut) {
  tplEditing.value = t
  tplForm.value = { name: t.name, content: t.content }
  tplNotice.value = ''
}

function tplCanEdit(t: PromptTemplateOut): boolean {
  if (t.scope === 'personal') return isAdmin.value || t.owner_id === auth.user?.id
  return isAdmin.value // system/published 仅管理员可编辑/删除
}

async function saveTpl() {
  if (!tplForm.value.name.trim() || !tplForm.value.content.trim()) {
    tplNotice.value = '请填写模板名称和内容'
    return
  }
  tplLoading.value = true
  tplNotice.value = ''
  try {
    if (tplEditing.value) {
      await updatePromptTemplate(tplEditing.value.id, {
        name: tplForm.value.name.trim(),
        content: tplForm.value.content.trim(),
      })
    } else {
      await createPromptTemplate({
        name: tplForm.value.name.trim(),
        content: tplForm.value.content.trim(),
        scene: 'feedback',
      })
    }
    tplEditing.value = null
    tplForm.value = { name: '', content: '' }
    await loadTplTemplates()
  } catch (e: any) {
    tplNotice.value = e?.response?.data?.detail || '保存失败'
  } finally {
    tplLoading.value = false
  }
}

async function removeTpl(t: PromptTemplateOut) {
  if (!window.confirm(`确认删除提示词模板「${t.name}」？`)) return
  try {
    await deletePromptTemplate(t.id)
    await loadTplTemplates()
  } catch (e: any) {
    tplNotice.value = e?.response?.data?.detail || '删除失败'
  }
}

async function publishTpl(t: PromptTemplateOut) {
  try {
    await publishPromptTemplate(t.id)
    await loadTplTemplates()
  } catch (e: any) {
    tplNotice.value = e?.response?.data?.detail || '发布失败'
  }
}

async function unpublishTpl(t: PromptTemplateOut) {
  try {
    await unpublishPromptTemplate(t.id)
    await loadTplTemplates()
  } catch (e: any) {
    tplNotice.value = e?.response?.data?.detail || '取消发布失败'
  }
}

const tplGroups = computed(() => ({
  system: tplTemplates.value.filter((t) => t.scope === 'system'),
  published: tplTemplates.value.filter((t) => t.scope === 'published'),
  personal: tplTemplates.value.filter((t) => t.scope === 'personal'),
}))

function tplScopeLabel(scope: string): string {
  if (scope === 'system') return '系统'
  if (scope === 'published') return '全校'
  return '我的'
}

async function saveRow(r: FbRow) {
  const s = selectedSchedule.value
  if (!s) return
  r.saving = true
  try {
    const base = {
      title: r.title || null,
      topic: r.topic || null,
      content: r.content || null,
      performance: r.performance || null,
      evaluation: r.evaluation || null,
      homework: r.homework || null,
      media_urls: r.media_urls,
    }
    if (r.feedback_id) {
      const f = await updateFeedback(r.feedback_id, base)
      r.feedback_id = f.id
      r.status = f.status
    } else {
      const f = await createFeedback({ schedule_id: s.id, student_id: r.student_id, ...base })
      r.feedback_id = f.id
      r.status = f.status
    }
    showNotice(`「${r.student_name}」反馈已保存`)
    refreshScheduleStatus()
  } catch (e: any) {
    showError(e?.response?.data?.detail || '保存失败')
  } finally {
    r.saving = false
  }
}

const savingAll = ref(false)
async function saveAll() {
  savingAll.value = true
  error.value = ''
  for (const r of editableRows.value) {
    if (r.status === 'published') continue
    await saveRow(r)
  }
  savingAll.value = false
  showNotice(`已保存 ${editableRows.value.length} 名学员反馈`)
  refreshScheduleStatus()
}

async function publishRow(r: FbRow) {
  if (!r.feedback_id) {
    showError(`「${r.student_name}」尚未保存，请先保存再发送给家长`)
    return
  }
  r.saving = true
  try {
    const f = await publishFeedback(r.feedback_id)
    r.status = f.status
    showNotice(`「${r.student_name}」反馈已发送给家长`)
    refreshScheduleStatus()
  } catch (e: any) {
    showError(e?.response?.data?.detail || '发送失败')
  } finally {
    r.saving = false
  }
}

/** 撤回已发送反馈为草稿（重新编辑后再次发送），防止发错/误发 */
async function unpublishRow(r: FbRow) {
  if (!r.feedback_id) {
    return
  }
  if (!window.confirm(`确认撤回「${r.student_name}」的反馈？撤回后可重新编辑并再次发送给家长。`)) return
  r.saving = true
  try {
    const f = await unpublishFeedback(r.feedback_id)
    r.status = f.status
    showNotice(`「${r.student_name}」已撤回，可编辑后重新发送`)
    refreshScheduleStatus()
  } catch (e: any) {
    showError(e?.response?.data?.detail || '撤回失败')
  } finally {
    r.saving = false
  }
}

async function publishAll() {
  error.value = ''
  for (const r of editableRows.value) {
    if (!r.feedback_id) {
      showError(`「${r.student_name}」未保存，跳过发送。请先保存或批量保存后再发送`)
      continue
    }
    if (r.status === 'published') continue
    await publishRow(r)
  }
  showNotice('批量发送完成')
  refreshScheduleStatus()
}

let statusRefresh = 0
function refreshScheduleStatus() {
  statusRefresh += 1
  const cur = statusRefresh
  setTimeout(async () => {
    if (cur !== statusRefresh) return
    try {
      const q = feedbackQuery()
      const [list, newStats] = await Promise.all([
        listCompletedSchedules(q),
        getFeedbackStats(q),
      ])
      completedSchedules.value = list
      stats.value = newStats
    } catch {
      /* 静默 */
    }
  }, 300)
}

function triggerUpload(r: FbRow) {
  activeRow.value = r
  mediaInput.value?.click()
}

async function onMediaSelected(e: Event) {
  const input = e.target as HTMLInputElement
  const r = activeRow.value
  if (!r || !input.files?.length) return
  r.uploading = true
  error.value = ''
  try {
    for (const file of Array.from(input.files)) {
      const res = await uploadFeedbackMedia(file)
      r.media_urls.push(res.url)
    }
    showNotice('素材上传成功')
  } catch (err: any) {
    showError(err?.response?.data?.detail || '上传失败')
  } finally {
    r.uploading = false
    input.value = ''
  }
}

function removeMedia(r: FbRow, url: string) {
  r.media_urls = r.media_urls.filter((u) => u !== url)
}

function mediaUrl(url: string): string {
  return url.startsWith('http') ? url : `http://localhost:8000${url}`
}

// 筛选联动：
// - 校区变化 -> 重载教师的选项（该校区教师）+ 班级选项 -> 刷新结果
// - 教师变化 -> 重载班级选项（该校区的该教师班级）-> 刷新结果
// - 班级/日期变化 -> 仅刷新结果
watch(campus, async () => {
  await Promise.all([loadTeacherOptions(), loadClassOptions()])
  await loadAll()
})

watch([teacherId], async () => {
  await loadClassOptions()
  await loadAll()
})

watch([classId, dateStart, dateEnd], loadAll)

onMounted(async () => {
  await loadCampuses()
  await Promise.all([loadTeacherOptions(), loadClassOptions()])
  await loadAll()
})

onBeforeUnmount(() => {
  stopAiTimer()
})
</script>

<template>
  <div>
    <PageHead title="课后反馈" eyebrow="FEEDBACKS" sub="只显示已上完的课；请假学员无需反馈。选择排课填写反馈并发送给家长">
      <template #actions>
      <div class="head-actions">
        <button class="btn ghost" @click="openTplModal">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 3h6M10 3v5.5L5.5 18a2 2 0 0 0 1.8 3h9.4a2 2 0 0 0 1.8-3L14 8.5V3M7.5 15h9" /></svg>
          提示词模板
        </button>
        <button class="btn ghost" @click="showBatch = true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 6h16M4 12h16M4 18h10" /></svg>
          批量填入课程信息
        </button>
      </div>
      </template>
    </PageHead>

    <!-- 筛选栏 -->
    <div class="filter-bar">
      <div class="filter-group">
        <label>校区</label>
        <select v-model="campus" class="filter-select">
          <option value="">全部校区</option>
          <option v-for="c in campuses" :key="c" :value="c">{{ c }}</option>
        </select>
      </div>
      <div class="filter-group">
        <label>教师</label>
        <SearchableSelect v-model="teacherId" :options="teacherOptions" placeholder="全部教师" />
      </div>
      <div class="filter-group">
        <label>班级</label>
        <SearchableSelect v-model="classId" :options="classOptions" placeholder="全部班级" />
      </div>
      <div class="filter-group">
        <label>日期区间</label>
        <div class="date-range">
          <input v-model="dateStart" type="date" />
          <span>至</span>
          <input v-model="dateEnd" type="date" />
        </div>
      </div>
      <div class="filter-group">
        <label>&nbsp;</label>
        <button class="btn ghost" @click="loadAll()">查询</button>
      </div>
    </div>

    <!-- 统计卡 -->
    <div class="stats-row">
      <div class="stat-card">
        <span class="stat-num" style="color: #6366f1">{{ stats.pending }}</span>
        <span class="stat-label">待反馈学员</span>
      </div>
      <div class="stat-card">
        <span class="stat-num" style="color: #059669">{{ stats.feedback_done }}</span>
        <span class="stat-label">已反馈学员</span>
      </div>
      <div class="stat-card">
        <span class="stat-num">{{ stats.expected }}</span>
        <span class="stat-label">应到学员</span>
      </div>
      <div class="stat-card">
        <span class="stat-num" style="color: #0891b2">{{ stats.attended }}</span>
        <span class="stat-label">签到学员</span>
      </div>
      <div class="stat-card">
        <span class="stat-num" style="color: #f59e0b">{{ stats.leave }}</span>
        <span class="stat-label">请假学员</span>
      </div>
      <div class="stat-card neutral">
        <span class="stat-num">{{ stats.schedule_count }}</span>
        <span class="stat-label">已完成排课</span>
      </div>
    </div>

    <p v-if="error" class="error-banner">{{ error }}</p>
    <p v-if="notice" class="notice-banner">{{ notice }}</p>

    <!-- AI 后台任务条：弹窗关闭后仍在生成，此处持续展示进度 -->
    <div v-if="aiGenerating" class="ai-job-bar">
      <div class="ai-job-main">
        <span class="ai-job-dot" />
        <span>AI 正在后台生成「{{ aiTaskName }}」的课堂评价，已用时 {{ aiElapsed }} 秒（通常 20-60 秒），可继续编辑其他内容…</span>
      </div>
      <div class="ai-job-actions">
        <button class="btn ghost small" @click="showAiModal = true">后台运行中，可忽略</button>
      </div>
    </div>

    <!-- 排课选择（仅已完成） -->
    <div class="schedule-picker">
      <div class="schedule-picker-head">
        <span class="sp-title">选择已上完的排课</span>
        <span v-if="filtersLoading" class="sp-loading">加载中…</span>
        <span v-else class="sp-count">{{ completedSchedules.length }} 节</span>
      </div>
      <div v-if="completedSchedules.length === 0 && !filtersLoading" class="sp-empty">
        当前筛选条件下暂无已上完的排课
      </div>
      <div v-else class="sp-grid">
        <button
          v-for="s in completedSchedules"
          :key="s.id"
          type="button"
          class="schedule-card"
          :class="{ picked: selectedScheduleId === s.id }"
          @click="selectSchedule(s.id)"
        >
          <div class="schedule-top">
            <span class="subject-badge">{{ (s.subject || '课').slice(0, 2) }}</span>
            <div class="schedule-body">
              <div class="schedule-name">
                {{ s.class_name }}
                <span class="status-pill" :class="s.all_done ? 'done' : 'todo'">
                  {{ s.all_done ? '已全部反馈' : `待反馈 ${Math.max(s.attended - s.feedback_done, 0)} 人` }}
                </span>
              </div>
              <div class="schedule-meta">
                {{ fmtDateTimeFromIso(s.start_time) }} ~ {{ fmtDateTimeFromIso(s.end_time) }} ·
                {{ s.teacher_name }}
                <template v-if="s.campus"> · {{ s.campus }}</template>
              </div>
              <div class="schedule-progress">
                <span class="bar" :style="{ width: s.attended ? Math.min((s.feedback_done / s.attended) * 100, 100) + '%' : '0%' }"></span>
                <span class="progress-text">
                  {{ s.feedback_done }}/{{ s.attended }} 已发送
                  <template v-if="s.saved_draft > 0"> · {{ s.saved_draft }} 草稿</template>
                </span>
              </div>
            </div>
          </div>
        </button>
      </div>
    </div>

    <div v-if="loading" class="loading">加载学员中…</div>

    <!-- 请假学员提示条 -->
    <div v-if="absentRows.length" class="absent-banner">
      {{ absentRows.length }} 名学员已请假，无需反馈：{{ absentRows.map((r) => r.student_name).join('、') }}
    </div>

    <!-- 学员反馈卡片 -->
    <div v-if="rows.length && !loading" class="card-grid">
      <div
        v-for="r in rows"
        :key="r.student_id"
        class="fb-card"
        :class="{ absent: r.attendance_status !== 'attended', published: r.status === 'published' }"
      >
        <div class="fb-head">
          <div class="fb-student">
            <span class="avatar">{{ r.student_name.slice(0, 1) }}</span>
            <div>
              <div class="fb-name">
                {{ r.student_name }}
                <span v-if="r.attendance_status === 'leave'" class="status-pill leave">已请假</span>
                <span v-else-if="r.attendance_status !== 'attended'" class="status-pill unmarked">未标记</span>
                <span v-else-if="r.status === 'published'" class="status-pill done">已发送</span>
                <span v-else class="status-pill draft">草稿</span>
              </div>
              <div class="fb-meta">{{ r.attendance_status === 'attended' ? '需反馈' : '无需反馈' }}</div>
            </div>
          </div>
          <div v-if="r.attendance_status === 'attended'" class="fb-ops">
            <template v-if="r.status !== 'published'">
              <button class="op-btn ai" @click="openAiModal(r)" :disabled="r.aiLoading || r.saving">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2l1.9 5.1L19 9l-5.1 1.9L12 16l-1.9-5.1L5 9l5.1-1.9L12 2zM19 16l.9 2.1L22 19l-2.1.9L19 22l-.9-2.1L16 19l2.1-.9L19 16z" /></svg>
                AI 课堂评价
              </button>
              <button class="op-btn" @click="saveRow(r)" :disabled="r.saving">
                {{ r.saving ? '保存中…' : '保存' }}
              </button>
              <button class="op-btn send" @click="publishRow(r)" :disabled="r.saving || r.status === 'published'">
                {{ r.status === 'published' ? '已发送' : '发送' }}
              </button>
            </template>
            <template v-else>
              <span class="sent-label">已发送</span>
              <button class="op-btn" @click="unpublishRow(r)" :disabled="r.saving">
                {{ r.saving ? '撤回中…' : '重新编辑' }}
              </button>
            </template>
          </div>
        </div>

        <template v-if="r.attendance_status === 'attended'">
          <div class="fb-fields">
            <label>
              课题
              <input v-model="r.topic" type="text" placeholder="如：Python 变量与类型" />
            </label>
            <label>
              课题内容
              <textarea v-autogrow v-model="r.content" rows="2" placeholder="本节课讲的知识点 / 内容概要…"></textarea>
            </label>
            <label>
              课堂表现
              <textarea v-autogrow v-model="r.performance" rows="2" placeholder="如：专注度、提问、完成练习情况…"></textarea>
            </label>
            <label class="eval-field">
              <span class="field-title">
                课堂评价
                <span class="eval-tip">AI 生成内容将写入此处，可继续编辑或再次润色</span>
              </span>
              <textarea v-autogrow v-model="r.evaluation" rows="4" placeholder="对学员本堂课的总体评价（AI 可辅助生成）…"></textarea>
            </label>
            <label>
              今日作业
              <textarea v-autogrow v-model="r.homework" rows="2" placeholder="今天的课后作业/练习…"></textarea>
            </label>
          </div>

          <div class="media-box">
            <button class="media-add" @click="triggerUpload(r)" :disabled="r.uploading">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14M5 12h14" /></svg>
              {{ r.uploading ? '上传中…' : '上传照片/视频' }}
            </button>
            <div v-if="r.media_urls.length" class="media-list">
              <div v-for="u in r.media_urls" :key="u" class="media-item">
                <img v-if="u.match(/\.(png|jpe?g|gif|webp|bmp)(\?|$)/i)" :src="mediaUrl(u)" alt="素材" />
                <span v-else class="video-tag">🎬 视频</span>
                <button class="media-del" title="移除" @click="removeMedia(r, u)">×</button>
              </div>
            </div>
          </div>
        </template>

        <div v-else class="absent-note">
          {{ r.attendance_status === 'leave' ? '已请假，本课无需反馈' : '考勤未标记，不生成反馈' }}
        </div>
      </div>
    </div>
    <div v-if="selectedSchedule && rows.length === 0 && !loading" class="empty-card">
      该排课暂无学员
    </div>

    <!-- 底部批量操作 -->
    <div v-if="selectedSchedule && editableRows.length" class="bottom-actions">
      <button class="btn primary" @click="saveAll" :disabled="savingAll">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2zM17 21v-8H7v8M7 3v5h8" /></svg>
        全部保存（{{ editableRows.length }}）
      </button>
      <button class="btn primary" @click="publishAll">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 2 11 13M22 2l-7 20-4-9-9-4 20-7z" /></svg>
        全部发送给家长
      </button>
    </div>

    <!-- 批量填入弹窗 -->
    <div v-if="showBatch" class="overlay" @click.self="showBatch = false">
      <div class="modal batch-modal">
        <h2>批量填入课程信息</h2>
        <p class="batch-hint">以下内容将应用到本课【签到学员】的反馈输入框中（请假学员自动跳过）</p>
        <label>
          标题（可选）
          <input v-model="batch.title" type="text" placeholder="如：第 3 次课 · Python 入门" />
        </label>
        <label>
          课题
          <input v-model="batch.topic" type="text" placeholder="如：Python 变量与类型" />
        </label>
        <label>
          课题内容
          <textarea v-autogrow v-model="batch.content" rows="2" placeholder="本节课讲的知识点 / 内容概要…"></textarea>
        </label>
        <label>
          课堂表现（可选）
          <textarea v-autogrow v-model="batch.performance" rows="2" placeholder="如：大部分学员专注度高，能独立完成练习…"></textarea>
        </label>
        <label>
          课堂评价（可选）
          <textarea v-autogrow v-model="batch.evaluation" rows="3" placeholder="对学员本堂课的总体评价…"></textarea>
        </label>
        <label>
          今日作业（可选）
          <textarea v-autogrow v-model="batch.homework" rows="2" placeholder="今天的课后作业/练习…"></textarea>
        </label>
        <div class="modal-actions">
          <button class="btn ghost" @click="showBatch = false">取消</button>
          <button class="btn primary" @click="applyBatch">应用到全部签到学员</button>
        </div>
      </div>
    </div>

    <!-- AI 课堂评价生成弹窗 -->
    <div v-if="showAiModal && aiRow" class="overlay" @click.self="showAiModal = false">
      <div class="modal ai-modal">
        <h2>AI 课堂评价</h2>
        <p class="batch-hint">
          为「{{ aiRow.student_name }}」选择提示词模板，AI 将结合科目/课题/课题内容/课堂表现/作业生成课堂评价，写入「课堂评价」输入框，可编辑后再润色。
          提交后即进后台生成，可直接关闭弹窗继续操作，顶部进度条会持续展示直到完成。
        </p>
        <label>
          提示词模板
          <select v-model="aiTemplateId" class="filter-select ai-tpl-select">
            <option v-for="t in aiTemplates" :key="t.id" :value="t.id">
              {{ t.name }}（{{ tplScopeLabel(t.scope) }}）
            </option>
          </select>
        </label>
        <div v-if="aiSelectedTemplate" class="ai-tpl-preview">{{ aiSelectedTemplate.content }}</div>
        <div v-if="!aiTemplates.length" class="ai-tpl-empty">
          暂无可用模板，请先到「提示词模板」新建。
        </div>
        <p v-if="aiTplError" class="error-banner">{{ aiTplError }}</p>
        <div class="modal-actions">
          <button class="btn ghost" @click="showAiModal = false">取消</button>
          <button class="btn primary" @click="aiEnhance" :disabled="aiGenerating || !aiTemplateId">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2l1.9 5.1L19 9l-5.1 1.9L12 16l-1.9-5.1L5 9l5.1-1.9L12 2zM19 16l.9 2.1L22 19l-2.1.9L19 22l-.9-2.1L16 19l2.1-.9L19 16z" /></svg>
            {{ aiGenerating ? `后台生成中 ${aiElapsed}s…` : aiRow.evaluation ? '提交后台润色' : '提交后台生成' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 提示词模板管理弹窗 -->
    <div v-if="showTplModal" class="overlay" @click.self="showTplModal = false">
      <div class="modal tpl-modal">
        <h2>提示词模板</h2>
        <p class="batch-hint">
          模板用于 AI 生成课堂评价。系统模板开箱即用（可编辑、不可删除）；「我的」模板仅自己可见；
          <template v-if="isAdmin">管理员可将模板「发布」给全校教师使用。</template>
          <template v-else>发布需管理员操作。</template>
        </p>

        <div class="tpl-layout">
          <div class="tpl-list">
            <div v-if="tplLoading" class="loading">加载中…</div>
            <template v-for="(group, key) in tplGroups" :key="key">
              <div v-if="group.length" class="tpl-group">
                <div class="tpl-group-title">
                  {{ key === 'system' ? '系统模板' : key === 'published' ? '已发布（全校）' : '我的模板' }}
                </div>
                <div v-for="t in group" :key="t.id" class="tpl-item">
                  <div class="tpl-item-main">
                    <div class="tpl-item-name">
                      {{ t.name }}
                      <span class="tpl-owner" v-if="t.owner_name && key !== 'system'">{{ t.owner_name }}</span>
                    </div>
                    <div class="tpl-item-content">{{ t.content }}</div>
                  </div>
                  <div class="tpl-item-ops">
                    <button v-if="tplCanEdit(t)" class="tpl-btn" @click="editTpl(t)">编辑</button>
                    <button v-if="isAdmin && key === 'personal'" class="tpl-btn" @click="publishTpl(t)">发布</button>
                    <button v-if="isAdmin && key === 'published'" class="tpl-btn" @click="unpublishTpl(t)">撤回</button>
                    <button v-if="tplCanEdit(t) && key !== 'system'" class="tpl-btn danger" @click="removeTpl(t)" title="系统模板不可删除，仅可编辑">删除</button>
                    <span v-if="key === 'system'" class="tpl-sys-tip" title="系统模板可编辑、不可删除">系统模板·可改不可删</span>
                  </div>
                </div>
              </div>
            </template>
            <div v-if="!tplLoading && !tplTemplates.length" class="ai-tpl-empty">暂无模板，点击下方「新建模板」创建</div>
          </div>

          <div class="tpl-form">
            <div class="tpl-form-title">{{ tplEditing ? '编辑模板' : '新建模板' }}</div>
            <label>
              模板名称
              <input v-model="tplForm.name" type="text" placeholder="如：通用鼓励型" maxlength="100" />
            </label>
            <label>
              模板内容
              <textarea v-autogrow v-model="tplForm.content" rows="7" placeholder="撰写提示词，可用占位符：{student_name} {class_name} {subject} {topic} {content} {performance} {homework} {evaluation}"></textarea>
            </label>
            <p v-if="tplNotice" class="error-banner">{{ tplNotice }}</p>
            <div class="modal-actions">
              <button v-if="tplEditing" class="btn ghost" @click="tplEditing = null; tplForm = { name: '', content: '' }">取消编辑</button>
              <button class="btn primary" @click="saveTpl" :disabled="tplLoading">
                {{ tplEditing ? '保存修改' : '新建模板' }}
              </button>
            </div>
          </div>
        </div>

        <div class="modal-actions">
          <button class="btn ghost" @click="showTplModal = false">关闭</button>
        </div>
      </div>
    </div>

    <!-- 隐藏的媒体选择器 -->
    <input ref="mediaInput" type="file" accept="image/*,video/*" multiple class="media-hidden" @change="onMediaSelected" />
  </div>
</template>

<style scoped>
.page-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 18px;
}
h1 {
  font-size: 22px;
}
.page-sub {
  color: var(--ink-3);
  font-size: 13px;
  margin-top: 4px;
}
.head-actions {
  display: flex;
  gap: 8px;
}

.btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 9px 16px;
  border-radius: 10px;
  border: none;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}
.btn svg {
  width: 16px;
  height: 16px;
}
.btn.primary {
  background: linear-gradient(135deg, #6366f1, #06b6d4);
  color: #fff;
  box-shadow: 0 6px 16px rgba(99, 102, 241, 0.3);
}
.btn.primary:hover {
  transform: translateY(-1px);
}
.btn.primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  transform: none;
}
.btn.ghost {
  background: var(--surface);
  color: var(--ink-2);
  border: 1px solid var(--line);
}
.btn.danger-outline {
  background: var(--surface);
  color: var(--danger);
  border: 1px solid var(--danger);
}

/* 筛选栏 */
.filter-bar {
  display: flex;
  align-items: flex-end;
  gap: 14px;
  flex-wrap: wrap;
  padding: 14px 16px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 14px;
  margin-bottom: 14px;
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
.filter-select {
  padding: 8px 11px;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: var(--surface);
  font-size: 13.5px;
  color: var(--ink-2);
}
.filter-select:focus {
  outline: none;
  border-color: var(--brand);
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
.date-range input:focus {
  outline: none;
  border-color: var(--brand);
}
.date-range span {
  color: var(--ink-3);
  font-size: 13px;
}

/* 统计卡 */
.stats-row {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 12px;
  margin-bottom: 16px;
}
.stat-card {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 13px;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.stat-card.neutral {
  border-style: dashed;
}
.stat-num {
  font-size: 26px;
  font-weight: 800;
  color: var(--ink);
  line-height: 1.1;
}
.stat-label {
  font-size: 12px;
  color: var(--ink-3);
}

.error-banner {
  background: var(--danger-soft);
  color: var(--danger);
  padding: 10px 14px;
  border-radius: 10px;
  margin-bottom: 14px;
  font-size: 13px;
}
.notice-banner {
  background: var(--success-soft);
  color: var(--success);
  padding: 10px 14px;
  border-radius: 10px;
  margin-bottom: 14px;
  font-size: 13px;
}

/* AI 后台任务条（与报告/总结页同款）：弹窗关闭后仍展示进度 */
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
@keyframes ai-pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.4; transform: scale(0.8); }
}
.ai-job-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

/* 排课选择器（仅已完成） */
.schedule-picker {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 16px;
  margin-bottom: 16px;
}
.schedule-picker-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.sp-title {
  font-weight: 700;
  font-size: 14px;
}
.sp-loading {
  color: var(--ink-3);
  font-size: 12.5px;
}
.sp-count {
  color: var(--ink-3);
  font-size: 12.5px;
}
.sp-empty {
  text-align: center;
  color: var(--ink-3);
  padding: 20px 0;
  font-size: 13px;
}
.sp-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 10px;
  max-height: 300px;
  overflow: auto;
}
.schedule-card {
  text-align: left;
  border: 1px solid var(--line);
  border-radius: 11px;
  background: var(--surface);
  padding: 12px 14px;
  cursor: pointer;
  transition: all 0.15s;
}
.schedule-card:hover {
  border-color: #c7d2fe;
}
.schedule-card.picked {
  border-color: var(--brand);
  box-shadow: 0 0 0 3px var(--brand-soft);
}
.schedule-top {
  display: flex;
  gap: 11px;
  align-items: flex-start;
}
.subject-badge {
  width: 38px;
  height: 38px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 10px;
  font-weight: 800;
  color: #fff;
  background: linear-gradient(135deg, #6366f1, #06b6d4);
}
.schedule-body {
  min-width: 0;
  flex: 1;
}
.schedule-name {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 700;
  font-size: 14px;
  flex-wrap: wrap;
}
.status-pill {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 999px;
  white-space: nowrap;
}
.status-pill.done {
  background: var(--success-soft);
  color: var(--success);
}
.status-pill.todo {
  background: var(--danger-soft);
  color: var(--danger);
}
.status-pill.leave {
  background: #fef3c7;
  color: #b45309;
}
.status-pill.unmarked {
  background: var(--ink-2-soft, #f1f5f9);
  color: var(--ink-2);
}
.status-pill.draft {
  background: var(--ink-2-soft, #f1f5f9);
  color: var(--ink-2);
}
.schedule-meta {
  color: var(--ink-3);
  font-size: 12px;
  margin-top: 3px;
}
.schedule-progress {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
}
.schedule-progress .bar {
  height: 5px;
  flex: 1;
  border-radius: 999px;
  background: var(--brand-soft);
  overflow: hidden;
  position: relative;
  display: block;
}
.schedule-progress .bar::after {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(90deg, #6366f1, #06b6d4);
}
.progress-text {
  font-size: 11.5px;
  color: var(--ink-3);
  white-space: nowrap;
}

/* 请假提示 */
.absent-banner {
  background: #fffbeb;
  border: 1px solid #fde68a;
  color: #92400e;
  padding: 10px 14px;
  border-radius: 10px;
  margin-bottom: 14px;
  font-size: 13px;
}

/* 学员卡片 */
.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
  gap: 16px;
}
.fb-card {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 16px;
  padding: 16px 18px;
  transition: all 0.18s;
}
.fb-card:hover {
  box-shadow: var(--shadow-md);
}
.fb-card.published {
  border-color: #a7f3d0;
}
.fb-card.absent {
  border-style: dashed;
  background: #fafafa;
}
.fb-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 10px;
  margin-bottom: 12px;
}
.fb-student {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.avatar {
  width: 36px;
  height: 36px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  font-weight: 700;
  color: #fff;
  background: linear-gradient(135deg, #6366f1, #06b6d4);
}
.fb-name {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 700;
  font-size: 14.5px;
  flex-wrap: wrap;
}
.fb-meta {
  color: var(--ink-3);
  font-size: 12px;
  margin-top: 1px;
}
.fb-ops {
  display: flex;
  gap: 6px;
  flex-shrink: 0;
}
.op-btn {
  border: 1px solid var(--brand);
  background: var(--brand-soft);
  color: var(--brand-strong);
  font-size: 12px;
  font-weight: 600;
  padding: 6px 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.15s;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  line-height: 1;
}
.op-btn svg {
  width: 13px;
  height: 13px;
  flex-shrink: 0;
}
.op-btn:hover {
  background: var(--brand);
  color: #fff;
}
.op-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.op-btn.ai {
  border-color: #c4b5fd;
  background: #f5f3ff;
  color: #7c3aed;
}
.op-btn.ai:hover {
  background: #ede9fe;
  color: #6d28d9;
}
.op-btn.send {
  border-color: #a7f3d0;
  background: var(--success-soft);
  color: var(--success);
}
.op-btn.send:hover {
  background: var(--success);
  color: #fff;
}
.op-btn.send:disabled {
  opacity: 0.6;
}

.sent-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--ink-3);
  align-self: center;
}

.fb-fields label {
  display: block;
  margin-bottom: 10px;
  font-size: 12.5px;
  color: var(--ink-2);
  font-weight: 500;
}
.fb-fields input,
.fb-fields textarea {
  display: block;
  width: 100%;
  box-sizing: border-box;
  margin-top: 5px;
  padding: 8px 10px;
  border: 1px solid var(--line);
  border-radius: 9px;
  font-size: 13.5px;
  font-family: inherit;
  background: var(--surface);
}
.fb-fields input:focus,
.fb-fields textarea:focus {
  outline: none;
  border-color: var(--brand);
  box-shadow: 0 0 0 3px var(--brand-soft);
}
.fb-fields textarea {
  resize: vertical;
}
.eval-field {
  border: 1px dashed #c7d2fe;
  border-radius: 10px;
  padding: 10px 12px;
  background: #fafaff;
}
.field-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
}
.eval-tip {
  font-size: 11px;
  font-weight: 500;
  color: #7c3aed;
  background: #f5f3ff;
  padding: 2px 8px;
  border-radius: 999px;
}
.absent-note {
  color: var(--ink-3);
  font-size: 12.5px;
  padding: 8px 0;
}

.media-box {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  border-top: 1px dashed var(--line);
  padding-top: 12px;
}
.media-add {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  border: 1px dashed var(--brand);
  background: var(--brand-soft);
  color: var(--brand-strong);
  font-size: 12px;
  font-weight: 600;
  padding: 7px 12px;
  border-radius: 9px;
  cursor: pointer;
}
.media-add svg {
  width: 13px;
  height: 13px;
}
.media-add:disabled {
  opacity: 0.6;
  cursor: wait;
}
.media-list {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.media-item {
  position: relative;
  width: 56px;
  height: 56px;
  border-radius: 9px;
  overflow: hidden;
  border: 1px solid var(--line);
}
.media-item img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.video-tag {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
  font-size: 11px;
  background: #f1f5f9;
  color: var(--ink-2);
}
.media-del {
  position: absolute;
  top: 2px;
  right: 2px;
  width: 18px;
  height: 18px;
  border: none;
  border-radius: 50%;
  background: rgba(15, 23, 42, 0.65);
  color: #fff;
  font-size: 12px;
  line-height: 1;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}

.bottom-actions {
  display: flex;
  gap: 10px;
  justify-content: flex-end;
  margin-top: 18px;
}

.empty-card {
  border: 2px dashed var(--line);
  border-radius: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--ink-3);
  padding: 50px 0;
}
.loading {
  text-align: center;
  color: var(--ink-3);
  padding: 40px 0;
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
}
.batch-modal {
  width: 480px;
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
.modal input,
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
  transition: all 0.15s;
}
.modal input:focus,
.modal textarea:focus {
  outline: none;
  border-color: var(--brand);
  box-shadow: 0 0 0 3px var(--brand-soft);
}
.modal textarea {
  resize: vertical;
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 20px;
}

.ai-modal {
  width: 460px;
}
.ai-tpl-select {
  width: 100%;
  box-sizing: border-box;
  margin-top: 6px;
}
.ai-tpl-preview {
  background: #f8fafc;
  border: 1px solid var(--line);
  border-radius: 9px;
  padding: 10px 12px;
  font-size: 12.5px;
  color: var(--ink-2);
  max-height: 130px;
  overflow: auto;
  white-space: pre-wrap;
  margin-top: 4px;
}
.ai-tpl-empty {
  color: var(--ink-3);
  font-size: 12.5px;
  padding: 12px 0;
}

.tpl-modal {
  width: 720px;
  max-width: calc(100vw - 40px);
}
.tpl-layout {
  display: grid;
  grid-template-columns: 1.2fr 1fr;
  gap: 16px;
  margin-top: 4px;
}
.tpl-list {
  max-height: 420px;
  overflow: auto;
  padding-right: 6px;
}
.tpl-group {
  margin-bottom: 14px;
}
.tpl-group-title {
  font-size: 12px;
  font-weight: 700;
  color: var(--ink-3);
  margin-bottom: 6px;
  letter-spacing: 0.5px;
}
.tpl-item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 10px 12px;
  margin-bottom: 8px;
  background: var(--surface);
}
.tpl-item-main {
  flex: 1;
  min-width: 0;
}
.tpl-item-name {
  font-weight: 700;
  font-size: 13.5px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.tpl-owner {
  font-size: 11px;
  font-weight: 500;
  color: var(--ink-3);
  background: #f1f5f9;
  padding: 1px 6px;
  border-radius: 999px;
}
.tpl-item-content {
  font-size: 12px;
  color: var(--ink-2);
  margin-top: 3px;
  white-space: pre-wrap;
  word-break: break-all;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.tpl-item-ops {
  display: flex;
  gap: 5px;
  flex-shrink: 0;
}
.tpl-btn {
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--ink-2);
  font-size: 11.5px;
  padding: 4px 9px;
  border-radius: 7px;
  cursor: pointer;
}
.tpl-btn:hover {
  border-color: var(--brand);
  color: var(--brand-strong);
}
.tpl-btn.danger {
  color: var(--danger);
  border-color: #fecaca;
}
.tpl-btn.danger:hover {
  background: var(--danger-soft);
}
.tpl-sys-tip {
  font-size: 11px;
  color: var(--ink-3);
}
.tpl-form {
  border-left: 1px solid var(--line);
  padding-left: 16px;
}
.tpl-form-title {
  font-weight: 700;
  font-size: 13.5px;
  margin-bottom: 10px;
}
.tpl-form textarea {
  font-family: inherit;
  white-space: pre-wrap;
}

.media-hidden {
  display: none;
}
</style>