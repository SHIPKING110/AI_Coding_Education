<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import {
  addQuestions,
  aiGenerate,
  aiRefine,
  createAssignment,
  createAssignmentFolder,
  deleteAssignment,
  deleteAssignmentFolder,
  deleteQuestion,
  getAssignment,
  isTaskRunning,
  listAssignmentsGrouped,
  listAssignmentFolders,
  listQuestionsPool,
  moveAssignmentsToFolder,
  publishAssignment,
  removeAssignmentsFromFolder,
  reorderQuestions,
  unpublishAssignment,
  updateAssignment,
  updateAssignmentFolder,
  updateQuestion,
  type AiGenerateIn,
  type AiTaskOut,
  type AssignmentFolderOut,
  type AssignmentOut,
  type QuestionIn,
  type QuestionType,
  type QuestionsPoolItem,
  QUESTION_TYPE_LABELS,
} from '@/api/assignment'
import { toastApiError } from '@/stores/toast'
import { listCampusesApi, listTeachersApi, type UserOut } from '@/api/auth'
import { listClasses, listStudents, type ClassOut } from '@/api/enrollment'
import { useAiTasksStore, type UnifiedAiTask } from '@/stores/aiTasks'
import { useAuthStore } from '@/stores/auth'
import { myPermissions } from '@/api/permissions'
import { fmtDateTimeFromIso } from '@/utils/date'
import PageHead from '@/components/PageHead.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import PaginationBar from '@/components/PaginationBar.vue'
import SearchableSelect from '@/components/SearchableSelect.vue'
import StudentFilter, { type StudentFilterValue } from '@/components/StudentFilter.vue'

const auth = useAuthStore()
const router = useRouter()
// AI出题 / 新建作业权限：管理员/教务全开；教师按权限管理配置（后端兜底 403）
const myPerms = ref<Record<string, boolean>>({})
const can = (key: string): boolean => {
  if (auth.user?.role !== 'teacher') return true
  return myPerms.value[key] !== false
}
const showNoPerm = ref(false)
const noPermText = ref('')
function guard(key: string, label: string, action: () => void) {
  if (can(key)) action()
  else {
    noPermText.value = `暂无${label}权限，请联系管理员开通。`
    showNoPerm.value = true
  }
}
const route = useRoute()
const canEdit = computed(() => {
  const r = auth.user?.role
  return r === 'admin' || r === 'staff' || r === 'teacher'
})

// ========== 作业列表（分组折叠视图，默认收起） ==========
const assignments = ref<AssignmentOut[]>([])
const total = ref(0)
const listLoading = ref(false)
const listError = ref('')
const statusFilter = ref<'' | 'draft' | 'published'>('')
const modeFilter = ref<'' | 'classwork' | 'homework'>('')
// 自定义分组
const folders = ref<AssignmentFolderOut[]>([])
// 分组折叠态：允许多个分组同时展开；Set 存已展开的 key（未分组 key='__ungrouped__'），初始为空=默认全部收起
const openFolderKeys = ref<Set<string>>(new Set())
const groupListRef = ref<HTMLElement | null>(null)
const isCollapsed = (key: string) => !openFolderKeys.value.has(key)
const toggleFolder = (key: string, ev?: MouseEvent) => {
  const next = new Set(openFolderKeys.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  openFolderKeys.value = next
  // 展开分组时，把该组标题滚到列表可视区顶部，避免“展开了却看不到内容”的错觉
  if (next.has(key)) {
    requestAnimationFrame(() => {
      const btn = (ev?.currentTarget as HTMLElement | undefined)
        ?? groupListRef.value?.querySelector<HTMLElement>(`[data-group="${key}"]`)
      btn?.scrollIntoView({ block: 'start', behavior: 'smooth' })
    })
  }
}
// 列表多选（批量移动到分组）
const selecting = ref(false)
const pickedIds = ref<string[]>([])

async function loadList() {
  listLoading.value = true
  listError.value = ''
  try {
    const items = await listAssignmentsGrouped({
      status: statusFilter.value || undefined,
      mode: modeFilter.value || undefined,
    })
    assignments.value = items
    total.value = items.length
    pickedIds.value = pickedIds.value.filter((id) => items.some((a) => a.id === id))
  } catch (e: any) {
    listError.value = e?.response?.data?.detail || '加载作业列表失败'
  } finally {
    listLoading.value = false
  }
}

/** 分组视图： [{key, name, count, items}]，未分组排最后；空分组仍展示（方便管理/删除） */
const groupedAssignments = computed(() => {
  const byId = new Map<string, AssignmentOut[]>()
  const ungrouped: AssignmentOut[] = []
  for (const a of assignments.value) {
    if (a.folder_id) {
      const arr = byId.get(a.folder_id) ?? []
      arr.push(a)
      byId.set(a.folder_id, arr)
    } else {
      ungrouped.push(a)
    }
  }
  const groups: { key: string; name: string; count: number; items: AssignmentOut[] }[] = []
  for (const f of folders.value) {
    groups.push({ key: f.id, name: f.name, count: byId.get(f.id)?.length ?? 0, items: byId.get(f.id) ?? [] })
  }
  groups.push({ key: '__ungrouped__', name: '未分组', count: ungrouped.length, items: ungrouped })
  return groups
})

/** 分组内待批改总数（组标题角标用） */
const pendingByGroup = computed(() => {
  const m = new Map<string, number>()
  for (const g of groupedAssignments.value) {
    m.set(g.key, g.items.reduce((s, a) => s + (a.pending_review || 0), 0))
  }
  return m
})

async function loadFolders() {
  try {
    folders.value = await listAssignmentFolders()
  } catch {
    folders.value = []
  }
}

function collapseAll() {
  openFolderKeys.value = new Set()
}

function expandAll() {
  openFolderKeys.value = new Set(groupedAssignments.value.map((g) => g.key))
}

function togglePicked(id: string) {
  const i = pickedIds.value.indexOf(id)
  if (i >= 0) pickedIds.value.splice(i, 1)
  else pickedIds.value.push(id)
}

function pickAllOnPage() {
  for (const g of groupedAssignments.value) {
    if (isCollapsed(g.key)) continue
    for (const a of g.items) {
      if (!pickedIds.value.includes(a.id)) pickedIds.value.push(a.id)
    }
  }
}

const folderName = (id: string | null | undefined) =>
  folders.value.find((f) => f.id === id)?.name ?? ''

// —— 分组管理弹窗 ——
const showFolderModal = ref(false)
const newFolderName = ref('')
const folderOpError = ref('')
const renamingFolderId = ref('')
const renameValue = ref('')

async function openFolderModal() {
  newFolderName.value = ''
  folderOpError.value = ''
  renamingFolderId.value = ''
  showFolderModal.value = true
  await loadFolders()
}

async function addFolder() {
  const name = newFolderName.value.trim()
  if (!name) return
  if (folders.value.some((f) => f.name === name)) {
    folderOpError.value = '已存在同名分组'
    return
  }
  folderOpError.value = ''
  try {
    const maxSort = folders.value.reduce((m, f) => Math.max(m, f.sort_no), 0)
    await createAssignmentFolder({ name, sort_no: maxSort + 1 })
    newFolderName.value = ''
    await loadFolders()
  } catch (e: any) {
    folderOpError.value = e?.response?.data?.detail || '创建分组失败'
  }
}

function startRename(f: AssignmentFolderOut) {
  renamingFolderId.value = f.id
  renameValue.value = f.name
}

async function confirmRename() {
  const id = renamingFolderId.value
  const name = renameValue.value.trim()
  if (!id || !name) return
  try {
    await updateAssignmentFolder(id, { name })
    renamingFolderId.value = ''
    await loadFolders()
  } catch (e: any) {
    folderOpError.value = e?.response?.data?.detail || '重命名失败'
  }
}

async function removeFolder(f: AssignmentFolderOut) {
  if (!window.confirm(`确认删除分组「${f.name}」？组内 ${f.assignment_count} 份作业将回到未分组。`)) return
  folderOpError.value = ''
  try {
    await deleteAssignmentFolder(f.id)
    if (openFolderKeys.value.has(f.id)) {
      const next = new Set(openFolderKeys.value)
      next.delete(f.id)
      openFolderKeys.value = next
    }
    await loadFolders()
    loadList()
  } catch (e: any) {
    folderOpError.value = e?.response?.data?.detail || '删除分组失败'
  }
}

async function movePickedTo(folderId: string) {
  if (pickedIds.value.length === 0) return
  try {
    if (folderId === '__ungrouped__') {
      await removeAssignmentsFromFolder([...pickedIds.value])
    } else {
      await moveAssignmentsToFolder(folderId, [...pickedIds.value])
    }
    editorNotice.value = `已移动 ${pickedIds.value.length} 份作业`
    pickedIds.value = []
    selecting.value = false
    await loadFolders()
    loadList()
  } catch (e: any) {
    listError.value = e?.response?.data?.detail || '移动失败'
  }
}

// 状态/模式筛选变化：重新拉全量（分组视图内过滤）
function onListFilterChange() {
  pickedIds.value = []
  selecting.value = false
  loadList()
}

// ========== 编辑器 ==========
const editing = ref<AssignmentOut | null>(null) // null=未打开编辑器
const isNew = ref(false)
const form = ref({ title: '', description: '', mode: 'homework' as 'classwork' | 'homework' })
const questions = ref<(QuestionIn & { id?: string })[]>([])
const originalIds = ref<string[]>([]) // 打开时后端已有题目 id（用于同步删除）
const activeIdx = ref(0)
const editorError = ref('')
const editorNotice = ref('')
const saving = ref(false)

const TYPE_OPTIONS = (Object.keys(QUESTION_TYPE_LABELS) as QuestionType[]).map((t) => ({
  value: t,
  label: QUESTION_TYPE_LABELS[t],
}))

/** 当前编辑题目（每题一页） */
const q = computed<QuestionIn | null>(() => questions.value[activeIdx.value] ?? null)

function resetEditor() {
  editing.value = null
  isNew.value = true
  form.value = { title: '', description: '', mode: 'homework' }
  initScoreConfig()
  questions.value = []
  originalIds.value = []
  activeIdx.value = 0
  editorError.value = ''
  editorNotice.value = ''
}

/** 新建作业：打开空编辑器（本地草稿） */
function newAssignment() {
  resetEditor()
}

/** 打开已有作业 */
function openAssignment(a: AssignmentOut) {
  editing.value = a
  isNew.value = false
  form.value = { title: a.title, description: a.description ?? '', mode: a.mode ?? 'homework' }
  initScoreConfig()
  if (a.target_student_ids?.length) {
    editorNotice.value = `补练作业：已定向 ${a.target_student_names.length} 名学员`
  }
  questions.value = a.questions.map((item) => ({
    ...cloneQuestion(item),
    id: item.id,
  }))
  originalIds.value = a.questions.map((item) => item.id)
  activeIdx.value = 0
  editorError.value = ''
  editorNotice.value = ''
}

function cloneQuestion(src: QuestionIn): QuestionIn {
  const copy: QuestionIn = {
    type: src.type,
    stem: src.stem,
    options: src.options ? [...src.options] : null,
    answer: src.answer,
    analysis: src.analysis,
    difficulty: src.difficulty ?? 1,
    test_cases: src.test_cases ? JSON.parse(JSON.stringify(src.test_cases)) : null,
    language: src.language,
  }
  normalizeByType(copy)
  return copy
}

/** 按题型规整字段（换题型时清理不适用字段） */
function normalizeByType(copy: QuestionIn) {
  if (copy.type === 'single_choice' || copy.type === 'multiple_choice') {
    if (!copy.options || copy.options.length < 2) copy.options = ['', '', '', '']
    if (copy.type === 'single_choice' && typeof copy.answer !== 'number') copy.answer = 0
    if (copy.type === 'multiple_choice' && !Array.isArray(copy.answer)) copy.answer = [0]
  } else {
    copy.options = null
  }
  if (copy.type !== 'programming') {
    copy.test_cases = null
    copy.language = null
  }
}

function changeType(idx: number, t: QuestionType) {
  const next = cloneQuestion({ ...questions.value[idx], type: t })
  questions.value[idx] = next
}

function addQuestion() {
  const item: QuestionIn = {
    type: 'single_choice',
    stem: '',
    options: ['', '', '', ''],
    answer: 0,
    analysis: '',
    difficulty: 3,
  }
  questions.value.push(item)
  activeIdx.value = questions.value.length - 1
}

function removeQuestion(idx: number) {
  if (questions.value.length <= 1) {
    editorError.value = '作业至少需要 1 道题目'
    return
  }
  questions.value.splice(idx, 1)
  if (activeIdx.value >= questions.value.length) activeIdx.value = questions.value.length - 1
}

/** 上一题 / 下一题（切换当前编辑题目，不做数组重排） */
function prevQuestion() {
  if (activeIdx.value > 0) activeIdx.value -= 1
}
function nextQuestion() {
  if (activeIdx.value < questions.value.length - 1) activeIdx.value += 1
}

/** 单选/多选 选择答案 */
function pickAnswer(oi: number) {
  const cur = q.value
  if (!cur) return
  if (cur.type === 'single_choice') {
    cur.answer = oi
  } else if (Array.isArray(cur.answer)) {
    const arr = cur.answer as number[]
    const i = arr.indexOf(oi)
    if (i >= 0) arr.splice(i, 1)
    else arr.push(oi)
  } else {
    cur.answer = [oi]
  }
}

function isAnswerPicked(oi: number): boolean {
  const cur = q.value
  if (!cur) return false
  if (cur.type === 'single_choice') return cur.answer === oi
  return Array.isArray(cur.answer) && (cur.answer as number[]).includes(oi)
}

// —— 选项/用例辅助（模板内无法写复杂赋值表达式） ——
function setOption(oi: number, v: string) {
  const cur = q.value
  if (cur?.options) cur.options[oi] = v
}
function removeOption(oi: number) {
  const cur = q.value
  if (cur?.options && cur.options.length > 2) cur.options.splice(oi, 1)
}
function addOption() {
  const cur = q.value
  if (cur?.options && cur.options.length < 6) cur.options.push('')
}
function setTcInput(ti: number, v: string) {
  const cur = q.value
  if (cur?.test_cases && cur.test_cases[ti]) cur.test_cases[ti].input = v
}
function setTcOutput(ti: number, v: string) {
  const cur = q.value
  if (cur?.test_cases && cur.test_cases[ti]) cur.test_cases[ti].output = v
}
function removeTc(ti: number) {
  const cur = q.value
  if (cur?.test_cases) cur.test_cases.splice(ti, 1)
}
function addTc() {
  const cur = q.value
  if (!cur) return
  if (!cur.test_cases) cur.test_cases = []
  cur.test_cases.push({ input: '', output: '' })
}

/** 同步本地题目到后端：更新已存在题目、批量添加新题、删除已移除题目、重排 */
async function syncQuestions(assignmentId: string): Promise<AssignmentOut> {
  const existed = questions.value.filter((item) => item.id) as (QuestionIn & { id: string })[]
  const newOnes = questions.value.filter((item) => !item.id)
  const localIds = existed.map((item) => item.id)

  for (const item of existed) {
    const { id, ...rest } = item
    await updateQuestion(assignmentId, id, rest)
  }
  for (const oldId of originalIds.value) {
    if (!localIds.includes(oldId)) {
      await deleteQuestion(assignmentId, oldId)
    }
  }
  let latest = await getAssignment(assignmentId)
  if (newOnes.length > 0) {
    latest = await addQuestions(
      assignmentId,
      newOnes.map((item) => {
        const { id: _id, ...rest } = item
        return rest
      }),
    )
  }
  // 按后端返回顺序回填本地题目（含新题 id），保证本地顺序与后端一致
  const ordered = [...latest.questions].sort((x, y) => x.order_no - y.order_no)
  questions.value = ordered.map((item) => ({ ...item, id: item.id }))
  await reorderQuestions(
    assignmentId,
    ordered.map((item) => item.id),
  )
  return await getAssignment(assignmentId)
}

async function saveAssignment(): Promise<boolean> {
  const title = form.value.title.trim()
  if (!title) {
    editorError.value = '请填写作业标题'
    return false
  }
  if (questions.value.length === 0) {
    editorError.value = '作业至少需要 1 道题目'
    return false
  }
  for (const item of questions.value) {
    if (!item.stem.trim()) {
      editorError.value = '存在空白题干，请补全后再保存'
      return false
    }
  }
  saving.value = true
  editorError.value = ''
  editorNotice.value = ''
  try {
    let saved: AssignmentOut
    if (isNew.value || !editing.value) {
      saved = await createAssignment({
        title,
        mode: form.value.mode,
        description: form.value.description || null,
        type_scores: { ...typeScores },
        passing_score: passingScore.value,
        questions: questions.value.map((item) => {
          const { id: _id, ...rest } = item
          return rest
        }),
      })
    } else {
      await updateAssignment(editing.value.id, {
        title,
        mode: form.value.mode,
        description: form.value.description || null,
        type_scores: { ...typeScores },
        passing_score: passingScore.value,
      })
      saved = await syncQuestions(editing.value.id)
    }
    editing.value = saved
    isNew.value = false
    openAssignment(saved)
    editorNotice.value = '作业已保存'
    loadList()
    return true
  } catch (e: any) {
    editorError.value = e?.response?.data?.detail || '保存失败'
    return false
  } finally {
    saving.value = false
  }
}

// ========== 发布：校区 → 教师 → 班级 三级筛选（与课后反馈一致） ==========
const showPublishModal = ref(false)
const publishClassIds = ref<string[]>([])
const publishClassQuery = ref('')
const publishDeadline = ref('')
const publishing = ref(false)
const publishError = ref('')

// 题型分值配置 + 达标线（发布弹窗内设置，随发布生效）
const TYPE_SCORE_DEFAULT: Record<string, number> = {
  single_choice: 1,
  multiple_choice: 1,
  judgement: 1,
  code_fill: 1,
  programming: 1,
}
const typeScores = reactive<Record<string, number>>({ ...TYPE_SCORE_DEFAULT })
const passingScore = ref<number | null>(null)

const publishTypeKeys = computed(() => {
  const keys = new Set<QuestionType>()
  for (const item of questions.value) {
    keys.add(item.type)
  }
  return [...keys]
})

const publishTypeScoreEntries = computed(() =>
  (publishTypeKeys.value.length > 0 ? publishTypeKeys.value : (Object.keys(TYPE_SCORE_DEFAULT) as QuestionType[])).map(
    (key) => ({ key, label: QUESTION_TYPE_LABELS[key] }),
  ),
)

const activeTypeScores = computed<Record<string, number>>(() => {
  const keys = publishTypeKeys.value
  const sourceKeys = keys.length > 0 ? keys : (Object.keys(TYPE_SCORE_DEFAULT) as QuestionType[])
  return Object.fromEntries(
    sourceKeys.map((key) => [key, typeScores[key] ?? TYPE_SCORE_DEFAULT[key] ?? 1]),
  )
})

function initScoreConfig() {
  Object.assign(typeScores, TYPE_SCORE_DEFAULT, editing.value?.type_scores ?? {})
  passingScore.value = editing.value?.passing_score ?? null
}

function normalizeScores() {
  for (const key of Object.keys(TYPE_SCORE_DEFAULT)) {
    const v = typeScores[key]
    if (typeof v !== 'number' || !Number.isFinite(v) || v < 0) typeScores[key] = 0
  }
  if (passingScore.value !== null && passingScore.value !== undefined && passingScore.value < 0) {
    passingScore.value = 0
  }
}

/** 发布弹窗里按当前题目+分值配置实时计算总分 */
const publishTotalScore = computed(() => {
  if (!questions.value.length) return 0
  return questions.value.reduce((sum, item) => sum + (activeTypeScores.value[item.type] ?? 1), 0)
})

const campusOptions = ref<{ id: string; label: string }[]>([])
const teacherOptions = ref<{ id: string; label: string }[]>([])
const classOptions = ref<{ id: string; label: string }[]>([])
const publishCampus = ref('')
const publishTeacherId = ref('')
// —— 课堂作业：按学员发布（校区 → 教师 → 班级 → 学员四级筛选，复用 StudentFilter）——
const publishStudentIds = ref<string[]>([])
const publishStudentFilter = ref<StudentFilterValue>({
  campus: '',
  teacherId: '',
  classId: '',
  keyword: '',
  account: '',
})
const publishNotifyParents = ref(false)
const publishStudents = ref<{ id: string; name: string; campus: string | null; classes: { id: string; name: string }[] }[]>([])
const publishStudentsTotal = ref(0)
const publishStudentsLoading = ref(false)

/** 已发布班级（不可重复选择，UI 禁用） */
const publishedClassIds = computed(() => editing.value?.published_class_ids ?? [])
const publishedClassNames = computed(() => editing.value?.published_class_names ?? [])
const filteredClassOptions = computed(() => {
  const q = publishClassQuery.value.trim().toLowerCase()
  if (!q) return classOptions.value
  return classOptions.value.filter((o) => o.label.toLowerCase().includes(q))
})

function isPublishedClass(id: string) {
  return publishedClassIds.value.includes(id)
}

async function loadCampusOptions() {
  try {
    campusOptions.value = (await listCampusesApi()).map((c) => ({ id: c, label: c }))
    // 当前账号所属校区自动预选
    if (auth.user?.campus && !publishCampus.value) {
      publishCampus.value = auth.user.campus
    }
  } catch {
    campusOptions.value = []
  }
}

async function loadTeacherOptions() {
  try {
    const p = await listTeachersApi({ campus: publishCampus.value || undefined, limit: 500 })
    teacherOptions.value = p.items.map((t: UserOut) => ({
      id: t.id,
      label: t.campus ? `${t.name}（${t.campus}）` : t.name,
    }))
    // 教师不在当前校区列表时自动清空（联动收敛）
    if (publishTeacherId.value && !teacherOptions.value.some((o) => o.id === publishTeacherId.value)) {
      publishTeacherId.value = ''
    }
  } catch {
    teacherOptions.value = []
  }
}

async function loadClassOptions() {
  try {
    const p = await listClasses({
      campus: publishCampus.value || undefined,
      teacher_id: publishTeacherId.value || undefined,
      limit: 500,
    })
    classOptions.value = p.items.map((c: ClassOut) => ({
      id: c.id,
      label: c.name,
    }))
    // 已选班级不在当前筛选结果时自动清空
    publishClassIds.value = publishClassIds.value.filter((id) =>
      classOptions.value.some((o) => o.id === id),
    )
  } catch {
    classOptions.value = []
  }
}

/** 校区变化：重载教师/班级（教师逐级收敛由 loadTeacherOptions 内清空失效项） */
async function onPublishCampusChange() {
  await loadTeacherOptions()
  await loadClassOptions()
}

/** 教师变化：重载班级下拉 */
async function onPublishTeacherChange() {
  await loadClassOptions()
}

async function openPublish() {
  if (questions.value.length === 0) {
    editorError.value = '作业至少需要 1 道题目才能发布'
    return
  }
  // 本地新草稿尚未落盘：先保存，确保标题/题目已进入后端，再打开发布弹窗
  if (!editing.value) {
    editorError.value = ''
    editorNotice.value = ''
    const ok = await saveAssignment()
    if (!ok) return
    if (!editing.value) return
  }
  publishClassIds.value = []
  publishClassQuery.value = ''
  publishDeadline.value = editing.value.deadline ? editing.value.deadline.slice(0, 16) : ''
  publishError.value = ''
  // 校区/教师默认当前账号（教师=自己，管理员/教务=全部）
  publishCampus.value = auth.user?.campus ?? ''
  if (auth.user?.role === 'teacher') {
    publishTeacherId.value = auth.user.id ?? ''
  } else {
    publishTeacherId.value = ''
  }
  // 课堂作业：初始化按学员发布状态（定向学员回填 + 学员筛选默认同当前账号校区）
  publishStudentIds.value = [...(editing.value.target_student_ids ?? [])]
  publishStudentFilter.value = {
    campus: auth.user?.campus ?? '',
    teacherId: auth.user?.role === 'teacher' ? auth.user.id ?? '' : '',
    classId: '',
    keyword: '',
    account: '',
  }
  publishNotifyParents.value = false
  showPublishModal.value = true
  // 预加载校区、教师与班级下拉（初始全量）
  void Promise.all([loadCampusOptions(), loadTeacherOptions(), loadClassOptions()])
  // 课堂作业：加载学员列表（筛选器元数据由复用组件内部加载）
  void loadPublishStudents()
}

/** 课堂作业：按筛选加载学员候选（沿用学员管理接口，服务端联动过滤，含未绑定账号筛选） */
async function loadPublishStudents() {
  publishStudentsLoading.value = true
  try {
    const f = publishStudentFilter.value
    const page = await listStudents({
      keyword: f.keyword.trim() || undefined,
      campus: f.campus && f.campus !== '__unassigned__' ? f.campus : undefined,
      campus_unassigned: f.campus === '__unassigned__' || undefined,
      teacher_id: f.teacherId && f.teacherId !== '__unassigned__' ? f.teacherId : undefined,
      teacher_unassigned: f.teacherId === '__unassigned__' || undefined,
      class_id: f.classId && f.classId !== '__unassigned__' ? f.classId : undefined,
      class_unassigned: f.classId === '__unassigned__' || undefined,
      account: f.account || undefined,
      limit: 100,
    })
    publishStudents.value = page.items.map((s) => ({
      id: s.id,
      name: s.name,
      campus: s.campus,
      classes: s.classes.map((c) => ({ id: c.id, name: c.name })),
    }))
    publishStudentsTotal.value = page.total
  } catch {
    publishStudents.value = []
    publishStudentsTotal.value = 0
  } finally {
    publishStudentsLoading.value = false
  }
}

/** 学员筛选变化（复用组件内部已做联动收敛）：刷新学员候选 */
async function onPublishStudentFilter() {
  await loadPublishStudents()
}

function togglePublishStudent(id: string) {
  const i = publishStudentIds.value.indexOf(id)
  if (i >= 0) publishStudentIds.value.splice(i, 1)
  else publishStudentIds.value.push(id)
}

function pickAllPublishStudents() {
  for (const s of publishStudents.value) {
    if (!publishStudentIds.value.includes(s.id)) publishStudentIds.value.push(s.id)
  }
}

function clearPublishStudents() {
  publishStudentIds.value = []
}

async function confirmPublish() {
  publishError.value = ''
  const isClasswork = form.value.mode === 'classwork'
  if (isClasswork) {
    // 课堂作业：按学员发布，必须选定向学员（仅发学员账号，答案收起）
    if (publishStudentIds.value.length === 0) {
      publishError.value = '课堂作业请至少选择 1 名发布学员'
      return
    }
  } else if (publishClassIds.value.length === 0) {
    publishError.value = '请至少选择一个发布班级'
    return
  }
  if (!editing.value) return
  publishing.value = true
  try {
    const saved = await saveForPublish()
    const r = await publishAssignment(saved.id, {
      // 课堂作业按学员发布：班级列表可为空（可见性完全由定向学员决定），后端已放开 class_ids 最少 1 个的校验
      class_ids: isClasswork ? [] : publishClassIds.value,
      deadline: publishDeadline.value ? new Date(publishDeadline.value).toISOString() : null,
      type_scores: { ...typeScores },
      passing_score: passingScore.value,
      target_student_ids: isClasswork
        ? publishStudentIds.value
        : editing.value?.target_student_ids?.length
          ? editing.value.target_student_ids
          : null,
      notify_parents: isClasswork ? publishNotifyParents.value : true,
    })
    showPublishModal.value = false
    openAssignment(r)
    editorNotice.value = isClasswork ? '课堂作业已发布到学员账号' : '作业已发布'
    loadList()
  } catch (e: any) {
    publishError.value = e?.response?.data?.detail || '发布失败'
  } finally {
    publishing.value = false
  }
}

/** 发布前先落盘当前内容（新作业先创建，已有作业先同步题目），返回已保存的作业 */
async function saveForPublish(): Promise<AssignmentOut> {
  const title = form.value.title.trim()
  if (!title) throw Object.assign(new Error('请填写作业标题'), { isClient: true })
  if (questions.value.length === 0) throw Object.assign(new Error('作业至少需要 1 道题目'), { isClient: true })

  if (isNew.value || !editing.value) {
    return await createAssignment({
      title,
      mode: form.value.mode,
      description: form.value.description || null,
      type_scores: { ...typeScores },
      passing_score: passingScore.value,
      questions: questions.value.map((item) => {
        const { id: _id, ...rest } = item
        return rest
      }),
    })
  }
  await updateAssignment(editing.value.id, { title, mode: form.value.mode, description: form.value.description || null })
  return await syncQuestions(editing.value.id)
}

// —— 确认弹窗（替代 window.confirm） ——
const confirmDel = ref(false)
const confirmUnpub = ref(false)

async function unpublish() {
  if (!editing.value) return
  try {
    const r = await unpublishAssignment(editing.value.id)
    openAssignment(r)
    editorNotice.value = '作业已撤回为草稿'
    loadList()
  } catch (e: any) {
    editorError.value = e?.response?.data?.detail || '撤回失败'
  }
}

async function remove() {
  if (!editing.value) return
  try {
    await deleteAssignment(editing.value.id)
    resetEditor()
    editorNotice.value = '作业已删除'
    loadList()
  } catch (e: any) {
    editorError.value = e?.response?.data?.detail || '删除失败'
  }
}

// ========== AI 出题弹窗 ==========
const showAiModal = ref(false)
const aiMode = ref<'similar' | 'homework'>('similar')
const aiTitle = ref('')
const aiCount = ref(3)
const aiDifficulty = ref(3)
const aiSourceQuestion = ref('')
const aiSourceAnswer = ref('')
const aiHint = ref('')
const aiTypes = ref<QuestionType[]>(['single_choice', 'multiple_choice', 'judgement'])
const aiLoading = ref(false)
const aiError = ref('')

const ALL_TYPES = (Object.keys(QUESTION_TYPE_LABELS) as QuestionType[]).map((t) => ({
  value: t,
  label: QUESTION_TYPE_LABELS[t],
}))

// 进行中任务该模式下最近 20 个（含已完成），驱动任务卡与结果加入
const aiTasks = useAiTasksStore()
const activeAiTask = computed(() =>
  aiTasks.tasks.find((t) => {
    if (t.taskKind !== 'assignment') return false
    return t.status === 'pending' || t.status === 'running' || t.status === 'done' || t.status === 'failed' || t.status === 'cancelled'
  }) ?? null,
)
const pickedCount = computed(() =>
  activeAiTask.value ? taskQuestions(activeAiTask.value).filter((_, i) => aiPicked.value[i]).length : 0,
)
const aiPicked = ref<boolean[]>([])

// 任务完成时自动初始化全选状态（题目数量可能变化）
watch(
  () => activeAiTask.value?.status,
  (st) => {
    if (st === 'done' && activeAiTask.value) {
      aiPicked.value = taskQuestions(activeAiTask.value).map(() => true)
    }
  },
)

/** 从任务 result 中取题目列表（generate）或单题（refine） */
function taskQuestions(t: UnifiedAiTask): QuestionIn[] {
  if (t.kind === 'refine') return []
  if (Array.isArray(t.result)) return t.result.filter(isQuestionLike)
  return isQuestionLike(t.result) ? [t.result] : []
}

function openAi() {
  // 若当前没有打开任何作业编辑器，新建一个草稿，确保 AI 题有落点可保存
  if (!editing.value && !isNew.value) {
    resetEditor()
  }
  // 标题入口：弹窗内可直接设置作业标题（默认沿用当前标题/占位名）
  aiTitle.value = form.value.title.trim() || 'AI 生成作业草稿'
  aiError.value = ''
  // 恢复历史任务（刷新后仍在生成中的任务）
  aiTasks.bootstrap()
  showAiModal.value = true
}

function toggleAiType(t: QuestionType) {
  const i = aiTypes.value.indexOf(t)
  if (i >= 0) aiTypes.value.splice(i, 1)
  else aiTypes.value.push(t)
}

/** 提交生成任务：立即返回 task 并登记到全局任务中心（可切页面，后台继续） */
async function runAi() {
  aiError.value = ''
  if (aiMode.value === 'similar' && !aiSourceQuestion.value.trim()) {
    aiError.value = '请填写原题题干'
    return
  }
  if (aiMode.value === 'homework' && !aiHint.value.trim()) {
    aiError.value = '请填写知识点提示语'
    return
  }
  aiLoading.value = true
  const payload: AiGenerateIn = {
    mode: aiMode.value,
    count: aiCount.value,
    difficulty: aiDifficulty.value,
    source_question: aiMode.value === 'similar' ? aiSourceQuestion.value : null,
    source_answer: aiMode.value === 'similar' ? aiSourceAnswer.value || null : null,
    hint: aiMode.value === 'homework' ? aiHint.value : null,
    types: aiMode.value === 'homework' && aiTypes.value.length ? aiTypes.value : null,
  }
  try {
    const task = await aiGenerate(payload)
    aiTasks.register(task, 'assignment')
  } catch (e: any) {
    aiError.value = e?.response?.data?.detail || '提交任务失败'
    toastApiError(e)
  } finally {
    aiLoading.value = false
  }
}

/** 把某任务勾选的题目加入作业，并自动保存为草稿，避免刷新后丢失 */
async function applyTaskResult(t: UnifiedAiTask, picked: boolean[]) {
  const items = taskQuestions(t).filter((_, i) => picked[i])
  if (items.length === 0) return
  // 弹窗里填的标题立即生效；未填时给默认名，保证自动保存必然成功（可随时改名）
  const title = aiTitle.value.trim()
  if (title) {
    form.value.title = title
  } else if (isNew.value && !form.value.title.trim()) {
    form.value.title = 'AI 生成作业草稿'
  }
  for (const item of items) {
    questions.value.push(cloneQuestion(item))
  }
  activeIdx.value = questions.value.length - 1
  showAiModal.value = false
  editorNotice.value = `已加入 ${items.length} 道 AI 生成的题目，正在自动保存为草稿…`

  try {
    // 关键修复：AI 题加入后立即落盘，刷新后仍可继续编辑/发布
    const ok = await saveAssignment()
    if (!ok) return // 校验失败，错误信息已展示在编辑器顶部
    editorNotice.value = `已加入 ${items.length} 道 AI 生成的题目，并已自动保存为草稿`
  } catch (e: any) {
    editorError.value = e?.response?.data?.detail || 'AI 题已加入，但自动保存失败，请手动点击“保存草稿”'
  }
}

// ========== 历史题目选择弹窗（复用已发布作业的题目） ==========
const showPoolModal = ref(false)
/** poolPickMode=add：勾选多题加入作业；source：选一道题作为「举一反三」原题导入 */
const poolPickMode = ref<'add' | 'source'>('add')
const poolKeyword = ref('')
const poolTypes = ref<QuestionType[]>([])
const poolDifficultyMin = ref(0)
const poolDifficultyMax = ref(0)
const poolItems = ref<QuestionsPoolItem[]>([])
const poolTotal = ref(0)
const poolPage = ref(1)
const poolLimit = 10
const poolLoading = ref(false)
const poolError = ref('')
// 勾选集合：id → 题目（跨页/跨筛选保留，加入时用 map 值而非当前页）
const poolPicked = ref<Record<string, QuestionsPoolItem>>({})
const poolApplying = ref(false)
let keywordTimer: ReturnType<typeof setTimeout> | null = null

const pickedPoolCount = computed(() => Object.keys(poolPicked.value).length)

/** 打开历史题目弹窗：新建草稿兜底 + 首次加载题目池 */
function openPool(mode: 'add' | 'source' = 'add') {
  if (!editing.value && !isNew.value) {
    resetEditor()
  }
  poolPickMode.value = mode
  poolKeyword.value = ''
  poolTypes.value = []
  poolDifficultyMin.value = 0
  poolDifficultyMax.value = 0
  poolPicked.value = {}
  poolPage.value = 1
  poolError.value = ''
  if (keywordTimer) { clearTimeout(keywordTimer); keywordTimer = null }
  showPoolModal.value = true
  void loadPool()
}

/** 搜索输入防抖：300ms 无新输入后才触发搜索，避免逐字闪烁 */
function onKeywordInput() {
  poolPage.value = 1
  if (keywordTimer) clearTimeout(keywordTimer)
  keywordTimer = setTimeout(() => { keywordTimer = null; void loadPool() }, 300)
}

async function loadPool() {
  poolLoading.value = true
  poolError.value = ''
  try {
    const r = await listQuestionsPool({
      keyword: poolKeyword.value.trim() || undefined,
      types: poolTypes.value.length > 0 ? poolTypes.value.join(',') : undefined,
      difficulty_min: poolDifficultyMin.value > 0 ? poolDifficultyMin.value : undefined,
      difficulty_max: poolDifficultyMax.value > 0 ? poolDifficultyMax.value : undefined,
      limit: poolLimit,
      offset: (poolPage.value - 1) * poolLimit,
    })
    poolItems.value = r.items
    poolTotal.value = r.total
  } catch (e: any) {
    poolError.value = e?.response?.data?.detail || '加载历史题目失败'
  } finally {
    poolLoading.value = false
  }
}

function togglePoolType(t: QuestionType) {
  const i = poolTypes.value.indexOf(t)
  if (i >= 0) poolTypes.value.splice(i, 1)
  else poolTypes.value.push(t)
}

function onPoolPageChange(p: number) {
  poolPage.value = p
  void loadPool()
}

function togglePoolPick(item: QuestionsPoolItem) {
  if (poolPicked.value[item.id]) delete poolPicked.value[item.id]
  else poolPicked.value[item.id] = item
}

/** 举一反三模式：从历史题目中选一道题作为原题导入（填充题干+答案/解析，回 AI 弹窗继续生成） */
function importSourceQuestion(item: QuestionsPoolItem) {
  aiSourceQuestion.value = item.stem
  let answerText = ''
  if (Array.isArray(item.answer)) {
    answerText = `正确答案选项：${(item.answer as number[]).map((i) => 'ABCDEFGH'[i] ?? String(i + 1)).join('、')}`
  } else if (typeof item.answer === 'boolean') {
    answerText = item.answer ? '正确' : '错误'
  } else if (item.answer !== undefined && item.answer !== null && String(item.answer).trim()) {
    answerText = String(item.answer)
  }
  const analysis = (item.analysis || '').trim()
  aiSourceAnswer.value = [answerText ? `答案：${answerText}` : '', analysis ? `解析：${analysis}` : '']
    .filter(Boolean)
    .join('\n')
  aiMode.value = 'similar'
  showPoolModal.value = false
  aiError.value = ''
  if (!showAiModal.value) {
    if (!editing.value && !isNew.value) {
      resetEditor()
    }
    aiTitle.value = form.value.title.trim() || 'AI 生成作业草稿'
    aiTasks.bootstrap()
    showAiModal.value = true
  }
}

function onPoolItemClick(item: QuestionsPoolItem) {
  if (poolPickMode.value === 'source') {
    importSourceQuestion(item)
  } else {
    togglePoolPick(item)
  }
}

/** 把勾选的历史题目加入当前作业并自动保存为草稿 */
async function applyPoolQuestions() {
  const selected = Object.values(poolPicked.value)
  if (selected.length === 0) return
  poolApplying.value = true
  poolError.value = ''
  try {
    // 弹窗中未设标题时用默认名，保证自动保存必然成功
    if (isNew.value && !form.value.title.trim()) {
      form.value.title = 'AI 生成作业草稿'
    }
    for (const it of selected) {
      questions.value.push(cloneQuestion(it))
    }
    activeIdx.value = questions.value.length - 1
    showPoolModal.value = false
    editorNotice.value = `已加入 ${selected.length} 道历史题目，正在自动保存为草稿…`
    const ok = await saveAssignment()
    if (!ok) return
    editorNotice.value = `已加入 ${selected.length} 道历史题目，并已自动保存为草稿`
  } catch (e: any) {
    editorError.value = e?.response?.data?.detail || '历史题目已加入，但自动保存失败，请手动点击“保存草稿”'
  } finally {
    poolApplying.value = false
  }
}

// ========== 对话优化弹窗（异步任务） ==========
const showRefineModal = ref(false)
const refineInstruction = ref('')
const refineLoading = ref(false)
const refineError = ref('')
// 仅记录任务 id，展示时始终从 store 读取最新状态（轮询更新）
const refineTaskId = ref('')
const refineTask = computed(
  () => aiTasks.tasks.find((t) => t.taskKind === 'assignment' && t.id === refineTaskId.value) ?? null,
)

function openRefine() {
  if (!q.value) return
  refineInstruction.value = ''
  refineError.value = ''
  refineTaskId.value = ''
  showRefineModal.value = true
}

async function runRefine() {
  if (!q.value) return
  if (!refineInstruction.value.trim()) {
    refineError.value = '请输入修改要求'
    return
  }
  refineLoading.value = true
  refineError.value = ''
  try {
    const task = await aiRefine({ question: q.value, instruction: refineInstruction.value })
    aiTasks.register(task as any, 'assignment')
    refineTaskId.value = task.id
    showRefineModal.value = false
    editorNotice.value = '优化任务已提交，稍后可在 AI 出题弹窗中查看并应用'
  } catch (e: any) {
    refineError.value = e?.response?.data?.detail || '提交优化失败'
    toastApiError(e)
  } finally {
    refineLoading.value = false
  }
}

/** 应用某个 refine 任务的结果到当前题目 */
function applyRefineTask(t: UnifiedAiTask) {
  if (t.taskKind !== 'assignment' || !q.value || !t.result || Array.isArray(t.result) || !isQuestionLike(t.result)) return
  questions.value[activeIdx.value] = cloneQuestion(t.result)
  editorNotice.value = '已用 AI 优化结果替换当前题目'
}

// ========== 文档下载（FR-AI-13，P1） ==========
/** 参考代码展示：把被转义成 \n 字面量的换行还原为真实换行，避免挤成一行 */
function formatCode(text: unknown): string {
  if (text === undefined || text === null) return '（未填写）'
  let s = String(text)
  s = s.replace(/\\n/g, '\n')
  s = s.replace(/\\t/g, '\t')
  return s
}

function formatAnswer(item: QuestionIn): string {
  const a = item.answer
  if (item.type === 'single_choice' && typeof a === 'number' && item.options) {
    return `${'ABCDEFGH'[a] ?? ''}（${item.options[a] ?? ''}）`
  }
  if (item.type === 'multiple_choice' && Array.isArray(a) && item.options) {
    const opts = item.options
    return (a as number[]).map((i) => `${'ABCDEFGH'[i] ?? ''}（${opts[i] ?? ''}）`).join('、')
  }
  if (item.type === 'judgement') return a ? '正确（√）' : '错误（×）'
  return formatCode(a)
}

function isQuestionLike(v: unknown): v is QuestionIn {
  return !!v && typeof v === 'object' && 'type' in (v as any) && 'stem' in (v as any)
}

function downloadDoc() {
  const title = form.value.title.trim() || '作业'
  const lines: string[] = [`# ${title}`, '']
  if (form.value.description.trim()) {
    lines.push(form.value.description.trim(), '')
  }
  questions.value.forEach((item, i) => {
    lines.push(`${i + 1}. （${QUESTION_TYPE_LABELS[item.type]}）${item.stem.trim()}`)
    if (item.options && item.options.length > 0) {
      item.options.forEach((o, oi) => {
        lines.push(`   ${'ABCDEFGH'[oi] ?? oi + 1}. ${o}`)
      })
    }
    lines.push('', `   【答案】${formatAnswer(item)}`)
    if (item.analysis && item.analysis.trim()) {
      lines.push('', `   【解析】${item.analysis.trim()}`)
    }
    if (item.type === 'programming' && item.test_cases && item.test_cases.length > 0) {
      lines.push('', '   【用例】')
      item.test_cases.forEach((tc) => {
        lines.push(`   输入: ${tc.input} → 期望输出: ${tc.output}`)
      })
    }
    lines.push('')
  })
  const blob = new Blob([lines.join('\n')], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${title}.txt`
  a.click()
  URL.revokeObjectURL(url)
}

function goGrade(assignmentId: string) {
  router.push(`/assignments/${assignmentId}/submissions`)
}

// ========== 工具 ==========
const currentStatus = computed(() => editing.value?.status ?? (isNew.value ? 'draft' : ''))
const answerOpen = ref(false)
const canApplyRefine = computed(() => !!refineTask.value && refineTask.value.status === 'done')

function statusLabel(s: string) {
  return s === 'published' ? '已发布' : '草稿'
}

watch(activeIdx, () => {
  answerOpen.value = false
})

// 发布筛选联动：校区 → 教师 → 班级
watch(publishCampus, onPublishCampusChange)
watch(publishTeacherId, onPublishTeacherChange)
watch(publishClassIds, () => {
  if (publishClassIds.value.length > 0 && publishError.value === '请至少选择一个发布班级') {
    publishError.value = ''
  }
})

onMounted(async () => {
  if (auth.user?.role === 'teacher') {
    try {
      myPerms.value = await myPermissions()
    } catch {
      myPerms.value = {}
    }
  }
  await Promise.all([loadList(), loadFolders()])
  // 从批改页「一键生成补练」跳转而来：自动打开补练草稿
  const draftId = route.query.draft
  if (typeof draftId === 'string' && draftId) {
    try {
      const a = await getAssignment(draftId)
      openAssignment(a)
      editorNotice.value = '补练草稿已就绪，可用 AI 出题或手动加题，再发布给未达标学员'
    } catch {
      // 草稿不存在时忽略，留在列表页
    }
  }
})
</script>

<template>
  <div class="assign-view">
    <PageHead title="AI 习题" eyebrow="ASSIGNMENTS" sub="举一反三 / 作业模式生成题目 —— 人工审核编辑后发布到班级或学员">
      <template #actions>
      <div class="head-actions">
        <button class="btn ai" @click="guard('assignment_ai', 'AI 出题', openAi)">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1" /></svg>
          AI 出题
        </button>
        <button class="btn primary" @click="guard('assignment_create', '新建作业', newAssignment)">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14M5 12h14" /></svg>
          新建作业
        </button>
      </div>
      </template>
    </PageHead>

    <div class="workspace">
      <!-- 左侧：作业列表（分组折叠视图，默认收起） -->
      <aside class="list-pane">
        <div class="list-filter">
          <button class="chip" :class="{ active: statusFilter === '' }" @click="statusFilter = ''; onListFilterChange()">全部</button>
          <button class="chip" :class="{ active: statusFilter === 'draft' }" @click="statusFilter = 'draft'; onListFilterChange()">草稿</button>
          <button class="chip" :class="{ active: statusFilter === 'published' }" @click="statusFilter = 'published'; onListFilterChange()">已发布</button>
        </div>
        <div class="list-filter">
          <button class="chip" :class="{ active: modeFilter === '' }" @click="modeFilter = ''; onListFilterChange()">全部模式</button>
          <button class="chip" :class="{ active: modeFilter === 'classwork' }" @click="modeFilter = 'classwork'; onListFilterChange()">课堂作业</button>
          <button class="chip" :class="{ active: modeFilter === 'homework' }" @click="modeFilter = 'homework'; onListFilterChange()">课后作业</button>
        </div>

        <div class="folder-toolbar">
          <span class="folder-toolbar-title">作业分组</span>
          <span class="folder-toolbar-actions">
            <button class="link-btn" @click="expandAll">全部展开</button>
            <button class="link-btn" @click="collapseAll">全部收起</button>
            <button class="link-btn" @click="openFolderModal">分组管理</button>
            <button class="link-btn" :class="{ active: selecting }" @click="selecting = !selecting; pickedIds = []">
              {{ selecting ? '取消选择' : '移至分组' }}
            </button>
          </span>
        </div>
        <div v-if="selecting" class="select-bar">
          <button class="chip" @click="pickAllOnPage">全选当前分组</button>
          <span class="picked-count">已选 {{ pickedIds.length }} 份</span>
          <select
            class="move-select"
            :disabled="pickedIds.length === 0"
            @change="movePickedTo(($event.target as HTMLSelectElement).value); ($event.target as HTMLSelectElement).value = ''"
          >
            <option value="">移动到…</option>
            <option v-for="f in folders" :key="f.id" :value="f.id">{{ f.name }}</option>
            <option value="__ungrouped__">未分组</option>
          </select>
        </div>

        <div v-if="listLoading" class="list-loading">加载中…</div>
        <div v-else-if="listError" class="list-empty">{{ listError }}</div>
        <div v-else-if="assignments.length === 0" class="list-empty">
          暂无作业，点击「新建作业」或「AI 出题」开始
        </div>
        <div v-else ref="groupListRef" class="group-list">
          <section v-for="g in groupedAssignments" :key="g.key" class="group-section">
            <button class="group-head" :class="{ open: !isCollapsed(g.key) }" :data-group="g.key" @click="toggleFolder(g.key, $event)">
              <svg class="group-caret" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="m9 18 6-6-6-6" /></svg>
              <svg class="group-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" /></svg>
              <span class="group-name">{{ g.name }}</span>
              <span class="group-count">{{ g.count }}</span>
              <span v-if="(pendingByGroup.get(g.key) ?? 0) > 0" class="group-pending">{{ pendingByGroup.get(g.key) }} 待批改</span>
            </button>
            <div v-if="!isCollapsed(g.key)" class="group-items">
              <div v-if="g.items.length === 0" class="group-empty">该分组暂无作业</div>
              <div v-for="a in g.items" :key="a.id" class="list-item-wrap">
            <label v-if="selecting" class="pick-check">
              <input type="checkbox" :checked="pickedIds.includes(a.id)" @change="togglePicked(a.id)" />
            </label>
            <button
              class="list-item"
              :class="{ active: editing?.id === a.id }"
              :title="a.title"
              @click="selecting ? togglePicked(a.id) : openAssignment(a)"
            >
              <div class="li-name" :title="a.title">{{ a.title }}</div>
              <div class="li-pills">
                <span class="pill" :class="a.mode === 'classwork' ? 'classwork' : 'homework'">{{ a.mode === 'classwork' ? '课堂' : '课后' }}</span>
                <span v-if="a.target_student_ids?.length" class="pill makeup" :title="`${a.target_student_ids.length} 名定向学员`">定向{{ a.target_student_ids.length }}人</span>
                <span class="pill" :class="a.status === 'published' ? 'pub' : 'draft'">{{ statusLabel(a.status) }}</span>
              </div>
              <div class="li-meta">
                {{ a.question_count }} 题
                <template v-if="a.class_name"> · {{ a.class_name }}</template>
                <template v-if="a.deadline"> · 截止 {{ fmtDateTimeFromIso(a.deadline) }}</template>
              </div>
              <span v-if="a.pending_review > 0" class="pending-badge" title="有待批改的提交">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9M13.7 21a2 2 0 0 1-3.4 0" /></svg>
                {{ a.pending_review }} 待批改
              </span>
            </button>
            <button
              v-if="a.status === 'published'"
              class="grade-link"
              @click.stop="goGrade(a.id)"
              title="批改作业"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" /><path d="M18.5 2.5a2.1 2.1 0 0 1 3 3L12 15l-4 1 1-4Z" /></svg>
              批改
            </button>
          </div>
            </div>
          </section>
        </div>
      </aside>

      <!-- 右侧：编辑器 -->
      <section class="editor-pane">
        <template v-if="editing || isNew">
          <div class="editor-head">
            <div class="editor-title">
              <input
                v-model="form.title"
                class="title-input"
                placeholder="作业标题（必填）"
                :disabled="!canEdit"
              />
              <span class="pill" :class="currentStatus === 'published' ? 'pub' : 'draft'">
                {{ isNew ? '新草稿' : statusLabel(currentStatus) }}
              </span>
            </div>
            <div class="mode-row">
              <span class="mode-label">作业模式</span>
              <button
                class="chip"
                :class="{ active: form.mode === 'classwork' }"
                :disabled="!canEdit"
                title="课堂作业：生成习题答案默认收起，发布时只发到学员账号，可按学员选择发布"
                @click="form.mode = 'classwork'"
              >
                课堂作业
              </button>
              <button
                class="chip"
                :class="{ active: form.mode === 'homework' }"
                :disabled="!canEdit"
                title="课后作业：常规模式，发布到班级，家长与学员均可见"
                @click="form.mode = 'homework'"
              >
                课后作业
              </button>
              <span class="mode-hint">{{ form.mode === 'classwork' ? '答案默认收起 · 仅发学员账号' : '常规发布 · 家长/学员可见' }}</span>
            </div>
            <textarea
              v-model="form.description"
              class="desc-input"
              placeholder="作业说明 / 知识点（可选）"
              rows="2"
              :disabled="!canEdit"
            />
            <div v-if="editorError" class="err-banner">{{ editorError }}</div>
            <div v-else-if="editorNotice" class="ok-banner">{{ editorNotice }}</div>
            <div class="editor-toolbar">
              <button class="btn ai small" :disabled="!canEdit" @click="guard('assignment_ai', 'AI 出题', openAi)"><svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1" /></svg>AI 出题</button>
              <button class="btn pool small" :disabled="!canEdit" @click="openPool('add')"><svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" /></svg>历史题目</button>
              <button class="btn small" :disabled="!canEdit" @click="saveAssignment">
                {{ saving ? '保存中…' : '保存草稿' }}
              </button>
              <button v-if="currentStatus === 'published'" class="btn small" :disabled="!canEdit" @click="confirmUnpub = true">撤回</button>
              <button v-else class="btn primary small" :disabled="!canEdit" @click="openPublish">发布</button>
              <span class="toolbar-spacer" />
              <button class="btn small" @click="downloadDoc">下载文档</button>
              <button class="btn danger small" :disabled="!canEdit" @click="confirmDel = true">删除</button>
            </div>
          </div>

          <!-- 题号导航 + 当前题编辑（每题一页） -->
          <div class="question-layout">
            <div class="qnav">
              <button
                v-for="(item, i) in questions"
                :key="i"
                class="qnum"
                :class="{ active: i === activeIdx, done: item.stem.trim() }"
                :title="`第 ${i + 1} 题：${QUESTION_TYPE_LABELS[item.type]}`"
                @click="activeIdx = i"
              >
                {{ i + 1 }}
              </button>
              <button class="qnum add" :disabled="!canEdit" title="添加题目" @click="addQuestion">+</button>
            </div>

            <div v-if="q" class="q-edit">
              <div class="q-top">
                <div class="q-no">第 {{ activeIdx + 1 }} 题</div>
                <select
                  :value="q.type"
                  class="type-select"
                  :disabled="!canEdit"
                  @change="changeType(activeIdx, ($event.target as HTMLSelectElement).value as QuestionType)"
                >
                  <option v-for="t in TYPE_OPTIONS" :key="t.value" :value="t.value">{{ t.label }}</option>
                </select>
                <div class="q-ops">
                  <button class="op-btn" :disabled="!canEdit || activeIdx === 0" title="上一题" @click="prevQuestion">◀</button>
                  <button class="op-btn" :disabled="!canEdit || activeIdx >= questions.length - 1" title="下一题" @click="nextQuestion">▶</button>
                  <button class="op-btn danger" :disabled="!canEdit" title="删除本题" @click="removeQuestion(activeIdx)">×</button>
                </div>
              </div>

              <div class="field">
                <span class="field-label">题干</span>
                <textarea
                  :value="q.stem"
                  class="stem-input"
                  rows="3"
                  placeholder="请输入题目内容（代码填空题/编程题请附代码与要求）"
                  :disabled="!canEdit"
                  @input="q.stem = ($event.target as HTMLTextAreaElement).value"
                />
              </div>

              <!-- 选择题选项 -->
              <template v-if="q.type === 'single_choice' || q.type === 'multiple_choice'">
                <div class="field">
                  <span class="field-label">选项</span>
                  <div v-for="(opt, oi) in q.options || []" :key="oi" class="option-row">
                    <span class="opt-letter">{{ 'ABCDEFGH'[oi] ?? oi + 1 }}</span>
                    <input
                      :value="opt"
                      class="opt-input"
                      placeholder="选项内容"
                      :disabled="!canEdit"
                      @input="setOption(oi, ($event.target as HTMLInputElement).value)"
                    />
                    <button
                      v-if="(q.options || []).length > 2"
                      class="op-btn danger"
                      :disabled="!canEdit"
                      title="删除选项"
                      @click="removeOption(oi)"
                    >
                      ×
                    </button>
                  </div>
                  <button
                    v-if="(q.options || []).length < 6"
                    class="btn small"
                    :disabled="!canEdit"
                    @click="addOption"
                  >
                    + 添加选项
                  </button>
                </div>
                <div class="field">
                  <span class="field-label">{{ q.type === 'single_choice' ? '正确答案' : '正确答案（可多选）' }}</span>
                  <div class="answer-btns">
                    <button
                      v-for="(opt, oi) in q.options || []"
                      :key="oi"
                      class="ans-btn"
                      :class="{ picked: isAnswerPicked(oi) }"
                      :disabled="!canEdit"
                      @click="pickAnswer(oi)"
                    >
                      {{ 'ABCDEFGH'[oi] ?? oi + 1 }}
                    </button>
                  </div>
                </div>
              </template>

              <!-- 判断题 -->
              <div v-else-if="q.type === 'judgement'" class="field">
                <span class="field-label">正确答案</span>
                <div class="answer-btns">
                  <button class="ans-btn" :class="{ picked: q.answer === true }" :disabled="!canEdit" @click="q.answer = true">正确 √</button>
                  <button class="ans-btn" :class="{ picked: q.answer === false }" :disabled="!canEdit" @click="q.answer = false">错误 ×</button>
                </div>
              </div>

              <!-- 代码填空 / 编程题：参考答案 -->
              <div v-if="q.type === 'code_fill' || q.type === 'programming'" class="field">
                <span class="field-label">{{ q.type === 'code_fill' ? '参考答案（代码填空）' : '参考代码' }}</span>
                <textarea
                  :value="String(q.answer ?? '')"
                  class="code-input"
                  rows="5"
                  placeholder="填写参考答案 / 参考代码"
                  :disabled="!canEdit"
                  @input="q.answer = ($event.target as HTMLTextAreaElement).value"
                />
              </div>

              <!-- 编程题：语言 + 用例（M4 仅录入，判题引擎 M5） -->
              <template v-if="q.type === 'programming'">
                <div class="field">
                  <span class="field-label">语言</span>
                  <select v-model="q.language" class="type-select" :disabled="!canEdit">
                    <option value="python">Python</option>
                    <option value="cpp">C++</option>
                  </select>
                </div>
                <div class="field">
                  <span class="field-label">判题用例（输入 → 期望输出，判题引擎 M5 启用）</span>
                  <div v-for="(tc, ti) in q.test_cases || []" :key="ti" class="tc-row">
                    <input
                      :value="tc.input"
                      class="opt-input"
                      placeholder="输入"
                      :disabled="!canEdit"
                      @input="setTcInput(ti, ($event.target as HTMLInputElement).value)"
                    />
                    <span class="tc-arrow">→</span>
                    <input
                      :value="tc.output"
                      class="opt-input"
                      placeholder="期望输出"
                      :disabled="!canEdit"
                      @input="setTcOutput(ti, ($event.target as HTMLInputElement).value)"
                    />
                    <button class="op-btn danger" :disabled="!canEdit" @click="removeTc(ti)">×</button>
                  </div>
                  <button class="btn small" :disabled="!canEdit" @click="addTc">+ 添加用例</button>
                </div>
              </template>

              <!-- 难度（1-10，对应少儿编程考级等级） -->
              <div class="field">
                <div class="difficulty-head">
                  <span class="field-label">难度：{{ q.difficulty ?? 3 }}/10</span>
                  <select class="small-select" :disabled="!canEdit" :value="q.difficulty ?? 3" @change="q.difficulty = Number(($event.target as HTMLSelectElement).value)">
                    <option v-for="s in 10" :key="s" :value="s">{{ s }} 级</option>
                  </select>
                </div>
                <div class="stars">
                  <button v-for="s in 10" :key="s" class="star" :class="{ on: s <= (q.difficulty ?? 3) }" :disabled="!canEdit" @click="q.difficulty = s">★</button>
                </div>
                <div class="difficulty-hint">1 = 一级最简单 … 10 = 十级最难（少儿编程考级等级）</div>
              </div>

              <!-- 答案与解析折叠（FR-AI-03/07） -->
              <div class="answer-fold">
                <button class="fold-btn" @click="answerOpen = !answerOpen">
                  {{ answerOpen ? '收起' : '展开' }} 答案与解析
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path :d="answerOpen ? 'M18 15l-6-6-6 6' : 'M6 9l6 6 6-6'" /></svg>
                </button>
                <div v-if="answerOpen" class="fold-body">
                  <div class="field">
                    <span class="field-label">参考答案</span>
                    <pre
                      v-if="q.type === 'code_fill' || q.type === 'programming'"
                      class="answer-preview code"
                    >{{ formatAnswer(q) }}</pre>
                    <div v-else class="answer-preview">{{ formatAnswer(q) }}</div>
                  </div>
                  <div class="field">
                    <span class="field-label">解析</span>
                    <textarea
                      :value="String(q.analysis ?? '')"
                      class="analysis-input"
                      rows="3"
                      placeholder="答案解析（默认折叠，学生作答后可见；代码填空建议先写「填空对照：① = …；② = …」）"
                      :disabled="!canEdit"
                      @input="q.analysis = ($event.target as HTMLTextAreaElement).value"
                    />
                  </div>
                </div>
              </div>

              <div class="q-footer">
                <button class="btn ai small" :disabled="!canEdit" @click="openRefine"><svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" /><path d="M8 9h8M8 13h5" /></svg>对话优化本题</button>
                <span class="q-count">共 {{ questions.length }} 题</span>
              </div>
            </div>
          </div>
        </template>

        <div v-else class="editor-empty">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M9 11l3 3L22 4M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11M15 3h6v6" /></svg>
          <p>从左侧选择作业，或新建作业 / AI 出题开始</p>
        </div>
      </section>
    </div>

    <!-- AI 出题弹窗 -->
    <div v-if="showAiModal" class="overlay" @click.self="showAiModal = false">
      <div class="modal ai-modal">
        <h2>AI 出题</h2>
        <p class="batch-hint">生成任务会在后台继续执行，你可以切换到其他页面，完成后回来加入作业</p>

        <div class="ai-tabs">
          <button class="tab" :class="{ active: aiMode === 'similar' }" @click="aiMode = 'similar'">举一反三</button>
          <button class="tab" :class="{ active: aiMode === 'homework' }" @click="aiMode = 'homework'">作业模式</button>
        </div>

        <label>
          作业标题 *
          <input v-model="aiTitle" class="ai-title-input" placeholder="如：for 循环与 if 判断练习（发布后学员看到的名字）" />
        </label>

        <div v-if="aiMode === 'similar'" class="ai-form">
          <label>
            原题题干 *
            <div class="source-row">
              <textarea v-autogrow v-model="aiSourceQuestion" rows="3" placeholder="输入一道原题，或点击右侧按钮从历史题目导入，AI 将改编出相似练习题" />
              <button type="button" class="btn pool small source-import" title="从历史题目中选一道原题（可按题型/难度筛选、搜索作业标题）" @click="openPool('source')">
                <svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" /></svg>从历史题目导入
              </button>
            </div>
          </label>
          <label>
            原题答案 / 解析（可选）
            <textarea v-autogrow v-model="aiSourceAnswer" rows="2" placeholder="帮助 AI 把握考点；从历史题目导入时自动带出答案与解析" />
          </label>
        </div>
        <div v-else class="ai-form">
          <label>
            知识点提示语 *
            <textarea v-autogrow v-model="aiHint" rows="3" placeholder="如：for 循环与列表遍历、函数的定义与调用…" />
          </label>
          <label>
            题型
            <div class="type-chips">
              <button v-for="t in ALL_TYPES" :key="t.value" class="chip" :class="{ active: aiTypes.includes(t.value) }" @click="toggleAiType(t.value)">
                {{ t.label }}
              </button>
            </div>
          </label>
        </div>

        <div class="ai-row">
          <label class="inline">
            每种题型各生成
            <select v-model.number="aiCount" class="small-select">
              <option v-for="n in 10" :key="n" :value="n">{{ n }}</option>
            </select>
            题
          </label>
          <label class="inline">
            难度
            <select v-model.number="aiDifficulty" class="small-select">
              <option v-for="n in 10" :key="n" :value="n">{{ n }} 级</option>
            </select>
            <span class="inline-hint">少儿编程考级等级</span>
          </label>
        </div>
        <p class="ai-count-tip">选了 N 种题型时，每种题型各生成「题数」道（例如：单选+多选、每类 1 题 = 共 2 题）</p>

        <div v-if="aiError" class="err-banner">{{ aiError }}</div>

        <div class="ai-status">
          <template v-if="activeAiTask">
            <div class="ai-progress-line">
              <span class="ai-status-dot" :class="activeAiTask.status" />
              <div>
                <div class="ai-stage">{{ activeAiTask.stage || '等待中' }}</div>
                <div class="ai-substage">{{ activeAiTask.summary }}</div>
              </div>
            </div>
            <div class="ai-progress-bar">
              <div class="ai-progress-fill" :class="activeAiTask.status" :style="{ width: activeAiTask.status === 'done' ? '100%' : activeAiTask.status === 'failed' ? '100%' : '65%' }" />
            </div>
            <div class="ai-status-tip">
              <span v-if="activeAiTask.status === 'pending'">任务已提交，正在排队，你可以关闭弹窗并切换到别的页面</span>
              <span v-else-if="activeAiTask.status === 'running'">AI 正在生成中，切换到其他页面也不会中断</span>
              <span v-else-if="activeAiTask.status === 'done'">生成完成，勾选题目后可加入当前作业</span>
              <span v-else-if="activeAiTask.status === 'cancelled'">任务已取消，可重新提交生成</span>
              <span v-else>生成失败：{{ activeAiTask.error || '未知错误' }}，可重试或取消后重提</span>
            </div>
          </template>
          <template v-else-if="aiLoading">
            <div class="ai-status-tip">任务已提交，正在准备生成…</div>
          </template>
        </div>

        <div v-if="activeAiTask && activeAiTask.status === 'done'" class="ai-result">
          <div v-for="(item, i) in taskQuestions(activeAiTask as UnifiedAiTask)" :key="i" class="ai-q">
            <label class="pick-line">
              <input v-model="aiPicked[i]" type="checkbox" />
              <span class="ai-q-type">{{ QUESTION_TYPE_LABELS[item.type] }}</span>
              <span class="ai-q-stem">{{ item.stem }}</span>
            </label>
          </div>
          <div class="ai-result-actions">
            <button class="btn small" @click="aiPicked = taskQuestions(activeAiTask as UnifiedAiTask).map(() => true)">全选</button>
            <button class="btn small" @click="aiPicked = taskQuestions(activeAiTask as UnifiedAiTask).map(() => false)">全不选</button>
          </div>
        </div>

        <div v-else-if="canApplyRefine && refineTask" class="ai-refine-result">
          <div class="ai-status-tip">最近一条优化任务已完成，你可以直接应用到当前题目。</div>
          <div class="ai-result">
            <div class="ai-q">
              <span class="ai-q-type">{{ QUESTION_TYPE_LABELS[taskQuestions(refineTask)[0].type] }}</span>
              <span class="ai-q-stem">{{ taskQuestions(refineTask)[0].stem }}</span>
            </div>
          </div>
          <div class="ai-result-actions">
            <button class="btn small" @click="applyRefineTask(refineTask)">应用当前优化结果</button>
          </div>
        </div>

        <div class="modal-actions">
          <button class="btn" @click="showAiModal = false">关闭</button>
          <button
            class="btn primary"
            :disabled="aiLoading"
            @click="runAi"
          >
            {{ aiLoading ? '提交中…' : '生成题目' }}
          </button>
          <button
            v-if="activeAiTask && (activeAiTask.status === 'pending' || activeAiTask.status === 'running')"
            class="btn"
            @click="aiTasks.cancel((activeAiTask as UnifiedAiTask).id)"
          >
            取消任务
          </button>
          <button
            v-if="activeAiTask && activeAiTask.status === 'done'"
            class="btn ai"
            :disabled="pickedCount === 0"
            @click="applyTaskResult(activeAiTask as UnifiedAiTask, aiPicked)"
          >
            加入作业（{{ pickedCount }} 题）
          </button>
        </div>
      </div>
    </div>

    <!-- 历史题目选择弹窗 -->
    <div v-if="showPoolModal" class="overlay" @click.self="showPoolModal = false">
      <div class="modal pool-modal">
        <h2>{{ poolPickMode === 'source' ? '从历史题目导入原题' : '历史题目' }}</h2>
        <p class="batch-hint">
          {{
            poolPickMode === 'source'
              ? '点击任意一道题即可作为「举一反三」的原题导入（题干 + 答案/解析自动带入），可按题型、难度筛选或搜索作业标题'
              : '从已发布作业中复用题目，可搜索作业标题、按题型/难度筛选'
          }}
        </p>

        <input
          v-model="poolKeyword"
          class="pool-keyword"
          placeholder="搜索作业标题…"
          @input="onKeywordInput"
        />

        <label class="pool-filter-label">
          题型
          <span class="type-chips">
            <button
              v-for="t in ALL_TYPES"
              :key="t.value"
              class="chip"
              :class="{ active: poolTypes.includes(t.value) }"
              @click="togglePoolType(t.value); onPoolPageChange(1)"
            >
              {{ t.label }}
            </button>
          </span>
        </label>

        <label class="pool-filter-label">
          难度
          <span class="pool-diff-range">
            <select v-model.number="poolDifficultyMin" class="small-select" @change="onPoolPageChange(1)">
              <option :value="0">不限</option>
              <option v-for="n in 10" :key="n" :value="n">{{ n }} 级</option>
            </select>
            <span class="pool-range-sep">~</span>
            <select v-model.number="poolDifficultyMax" class="small-select" @change="onPoolPageChange(1)">
              <option :value="0">不限</option>
              <option v-for="n in 10" :key="n" :value="n">{{ n }} 级</option>
            </select>
          </span>
        </label>

        <div class="pool-results">
          <div v-if="poolLoading && poolItems.length === 0" class="pool-empty">加载中…</div>
          <div v-else-if="poolError" class="err-banner">{{ poolError }}</div>
          <div v-else-if="poolItems.length === 0" class="pool-empty">无匹配的历史题目</div>
          <div v-else class="pool-list">
            <div
              v-for="item in poolItems"
              :key="item.id"
              class="pool-item"
              :class="{ picked: poolPickMode === 'add' && !!poolPicked[item.id] }"
              @click="onPoolItemClick(item)"
            >
              <input
                v-if="poolPickMode === 'add'"
                type="checkbox"
                class="pool-check"
                :checked="!!poolPicked[item.id]"
                @click.stop="togglePoolPick(item)"
              />
              <svg v-else class="pool-source-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1" /></svg>
              <div class="pool-item-body">
                <div class="pool-item-head">
                  <span class="ai-q-type">{{ QUESTION_TYPE_LABELS[item.type] }}</span>
                  <span class="pool-diff-badge">Lv.{{ item.difficulty }}</span>
                  <span class="pool-source">「{{ item.assignment_title }}」</span>
                </div>
                <div class="pool-item-stem">{{ item.stem }}</div>
              </div>
            </div>
          </div>
          <PaginationBar
            v-if="poolTotal > poolLimit"
            :total="poolTotal"
            :page-size="poolLimit"
            :page="poolPage"
            @update:page="onPoolPageChange"
          />
        </div>

        <div class="modal-actions">
          <button class="btn" @click="showPoolModal = false">取消</button>
          <button
            v-if="poolPickMode === 'add'"
            class="btn primary"
            :disabled="pickedPoolCount === 0 || poolApplying"
            @click="applyPoolQuestions"
          >
            {{ poolApplying ? '加入中…' : `加入作业（${pickedPoolCount} 题）` }}
          </button>
        </div>
      </div>
    </div>

    <!-- 对话优化弹窗 -->
    <div v-if="showRefineModal" class="overlay" @click.self="showRefineModal = false">
      <div class="modal refine-modal">
        <h2>对话优化本题</h2>
        <p class="batch-hint">优化任务在后台执行，完成后可在 AI 出题弹窗中查看并应用到当前题目</p>
        <label>
          修改要求 *
          <textarea v-autogrow v-model="refineInstruction" rows="3" placeholder="如：难度调低一点；把例子换成生活中的场景；改成判断题…" />
        </label>
        <div v-if="refineError" class="err-banner">{{ refineError }}</div>
        <div class="modal-actions">
          <button class="btn" @click="showRefineModal = false">取消</button>
          <button class="btn primary" :disabled="refineLoading" @click="runRefine">
            {{ refineLoading ? '提交中…' : '提交优化' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 发布弹窗（多班级发布，M4.1；课堂作业按学员发布） -->
    <div v-if="showPublishModal" class="overlay" @click.self="showPublishModal = false">
      <div class="modal publish-modal">
        <h2>{{ form.mode === 'classwork' ? '发布课堂作业' : '发布作业' }}</h2>
        <p class="batch-hint">
          {{
            form.mode === 'classwork'
              ? '课堂作业只发布到学员账号（答案默认收起）；请选择要发布的学员，可按校区/教师/班级筛选'
              : '可同时发布到多个班级；发布过的班级不可重复选择'
          }}
        </p>

        <!-- 课堂作业：按学员发布 -->
        <template v-if="form.mode === 'classwork'">
          <StudentFilter
            v-model="publishStudentFilter"
            show-account-filter
            campus-placeholder="全部校区"
            teacher-placeholder="全部教师"
            class-placeholder="全部班级"
            search-placeholder="搜索学员姓名…"
            compact
            @update:model-value="(v) => { publishStudentFilter = v; onPublishStudentFilter() }"
          />
          <div class="publish-classes">
            <span class="publish-classes-title">目标学员（可多选，共 {{ publishStudentsTotal }} 名）*</span>
            <div class="student-list">
              <div v-if="publishStudentsLoading && publishStudents.length === 0" class="class-empty">加载中…</div>
              <template v-else>
                <label
                  v-for="s in publishStudents"
                  :key="s.id"
                  class="class-item"
                >
                  <input
                    type="checkbox"
                    :checked="publishStudentIds.includes(s.id)"
                    @change="togglePublishStudent(s.id)"
                  />
                  <span class="class-name">{{ s.name }}</span>
                  <span class="student-tags">{{ s.campus || '未填校区' }} · {{ s.classes.map((c) => c.name).join('、') || '未分班' }}</span>
                  <span v-if="publishStudentIds.includes(s.id)" class="tag picked">本次发布</span>
                </label>
                <div v-if="publishStudents.length === 0" class="class-empty">无匹配学员</div>
              </template>
            </div>
            <div class="publish-student-ops">
              <button class="btn small" @click="pickAllPublishStudents">全选当前页</button>
              <button class="btn small" @click="clearPublishStudents">清空已选</button>
              <span class="picked-count">已选 {{ publishStudentIds.length }} 名学员</span>
            </div>
          </div>
          <label class="notify-row">
            <input v-model="publishNotifyParents" type="checkbox" />
            <span>同时通知家长账号（默认关闭，仅通知学员本人）</span>
          </label>
        </template>

        <!-- 课后作业：按班级发布 -->
        <template v-else>
          <div class="publish-filters">
            <label>
              校区
              <SearchableSelect v-model="publishCampus" :options="campusOptions" placeholder="全部校区" group="publish" />
            </label>
            <label>
              教师
              <SearchableSelect v-model="publishTeacherId" :options="teacherOptions" placeholder="全部教师" group="publish" />
            </label>
          </div>

          <div class="publish-classes">
            <span class="publish-classes-title">目标班级（可多选）*</span>
            <input v-model="publishClassQuery" class="class-search" placeholder="搜索班级名称…" />
            <div class="class-list">
              <label
                v-for="c in filteredClassOptions"
                :key="c.id"
                class="class-item"
                :class="{ disabled: isPublishedClass(c.id) }"
              >
                <input
                  type="checkbox"
                  :value="c.id"
                  v-model="publishClassIds"
                  :disabled="isPublishedClass(c.id)"
                />
                <span class="class-name">{{ c.label }}</span>
                <span v-if="isPublishedClass(c.id)" class="tag published">已发布</span>
                <span v-else-if="publishClassIds.includes(c.id)" class="tag picked">本次发布</span>
              </label>
              <div v-if="filteredClassOptions.length === 0" class="class-empty">无匹配班级</div>
            </div>
            <div v-if="publishedClassNames.length > 0" class="published-tip">
              已发布班级：{{ publishedClassNames.join('、') }}（发布过的班级不可重复选择）
            </div>
          </div>
        </template>

        <div class="score-config">
          <div class="score-config-head">
            <span>题型分值（每题）</span>
            <span class="score-total">总分：{{ publishTotalScore }} 分</span>
          </div>
          <div class="score-grid">
            <label v-for="item in publishTypeScoreEntries" :key="item.key" class="score-item">
              <span class="score-label">{{ item.label }}</span>
              <input
                v-model.number="typeScores[item.key]"
                type="number"
                min="0"
                max="100"
                @change="normalizeScores()"
              />
              <span class="score-unit">分/题</span>
            </label>
          </div>
          <label class="pass-line">
            <span class="pass-label">达标分数（留空 = 不设达标线）</span>
            <input v-model.number="passingScore" type="number" min="0" :max="publishTotalScore" placeholder="如：60" />
            <span class="score-unit">分</span>
          </label>
          <p v-if="editing?.target_student_ids?.length" class="target-tip">
            补练作业：仅 {{ editing.target_student_ids.length }} 名未达标学员可见
          </p>
        </div>

        <label>
          完成时间（可选，截止后标记未提交）
          <input v-model="publishDeadline" type="datetime-local" />
        </label>
        <div v-if="publishError" class="err-banner">{{ publishError }}</div>
        <div class="modal-actions">
          <button class="btn" @click="showPublishModal = false">取消</button>
          <button
            class="btn primary"
            :disabled="publishing"
            @click="confirmPublish"
          >
            {{
              publishing
                ? '发布中…'
                : form.mode === 'classwork'
                  ? `确认发布（${publishStudentIds.length} 名学员）`
                  : `确认发布（${publishClassIds.length} 个班级）`
            }}
          </button>
        </div>
      </div>
    </div>

    <!-- 分组管理弹窗 -->
    <div v-if="showFolderModal" class="overlay" @click.self="showFolderModal = false">
      <div class="modal folder-modal">
        <h2>作业分组管理</h2>
        <p class="batch-hint">按教学阶段/班级/主题自定义分组，方便管理已生成的作业。删除分组不会删除作业，组内作业回到「未分组」。</p>

        <div class="folder-add-row">
          <input
            v-model="newFolderName"
            class="folder-add-input"
            placeholder="新分组名称，如：期中复习 / Python 一班 / 每日练习"
            maxlength="64"
            @keyup.enter="addFolder"
          />
          <button class="btn primary small" :disabled="!newFolderName.trim()" @click="addFolder">+ 新建</button>
        </div>

        <div v-if="folderOpError" class="err-banner">{{ folderOpError }}</div>

        <div class="folder-list">
          <div v-if="folders.length === 0" class="pool-empty">还没有分组，先创建一个吧</div>
          <div v-for="f in folders" :key="f.id" class="folder-row">
            <template v-if="renamingFolderId === f.id">
              <input v-model="renameValue" class="folder-add-input" maxlength="64" @keyup.enter="confirmRename" />
              <button class="btn small primary" :disabled="!renameValue.trim()" @click="confirmRename">保存</button>
              <button class="btn small" @click="renamingFolderId = ''">取消</button>
            </template>
            <template v-else>
              <span class="folder-row-name">{{ f.name }}</span>
              <span class="folder-row-count">{{ f.assignment_count }} 份作业</span>
              <button class="op-btn" title="重命名" @click="startRename(f)"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M17 3a2.8 2.8 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z" /></svg></button>
              <button class="op-btn danger" title="删除分组" @click="removeFolder(f)"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m3 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" /></svg></button>
            </template>
          </div>
        </div>

        <div class="modal-actions">
          <button class="btn" @click="showFolderModal = false">完成</button>
        </div>
      </div>
    </div>

    <!-- 删除 / 撤回 确认弹窗 -->
    <ConfirmDialog
      :visible="showNoPerm"
      title="暂无操作权限"
      :message="noPermText"
      confirm-text="知道了"
      @confirm="showNoPerm = false"
      @cancel="showNoPerm = false"
    />
    <ConfirmDialog
      :visible="confirmDel"
      title="删除作业"
      message="确认删除该作业？删除后不可恢复。"
      confirm-text="删除"
      danger
      @confirm="confirmDel = false; remove()"
      @cancel="confirmDel = false"
    />
    <ConfirmDialog
      :visible="confirmUnpub"
      title="撤回作业"
      message="确认撤回该作业为草稿？撤回后可重新编辑并再次发布。"
      confirm-text="撤回"
      @confirm="confirmUnpub = false; unpublish()"
      @cancel="confirmUnpub = false"
    />
  </div>
</template>

<style scoped>
.assign-view {
  max-width: 1200px;
  margin: 0 auto;
}
.page-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
}
.page-head h1 {
  font-size: 24px;
}
.sub {
  color: var(--ink-3);
  font-size: 13px;
  margin-top: 4px;
}
.head-actions {
  display: flex;
  gap: 10px;
}
.workspace {
  display: grid;
  grid-template-columns: 280px 1fr;
  gap: 16px;
  align-items: start;
}

/* ===== 左侧列表：独立滚动列，内部自带滚轮，不与右侧题版/页面共用 ===== */
.workspace {
  /* grid 项允许在视口内收缩，否则内容高度会把左侧滚动列撑开 */
  min-height: 0;
}

.list-pane {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 14px;
  box-shadow: var(--shadow-sm);
  position: sticky;
  top: 12px;
  display: flex;
  flex-direction: column;
  min-height: 0;
  /* 固定在视口可用高度内，列表内容由唯一的 .group-list 滚轮承载 */
  box-sizing: border-box;
  height: calc(100vh - 150px);
  min-height: 0;
  max-height: calc(100vh - 150px);
  overflow: hidden;
}
.list-filter {
  display: flex;
  gap: 6px;
  margin-bottom: 12px;
}
.chip {
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--ink-2);
  font-size: 12.5px;
  padding: 6px 12px;
  border-radius: 999px;
  cursor: pointer;
  transition: all 0.15s;
  font-weight: 500;
  font-family: inherit;
}
.chip:hover {
  border-color: var(--brand);
}
.chip.active {
  background: var(--brand-soft);
  border-color: var(--brand);
  color: var(--brand-strong);
  font-weight: 600;
}
.list-items {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 560px;
  overflow: auto;
}
.list-item-wrap {
  position: relative;
  display: flex;
  align-items: stretch;
  gap: 6px;
}
.list-item-wrap .list-item {
  flex: 1;
  min-width: 0;
}
.grade-link {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 0 10px;
  border-radius: 8px;
  border: 1px solid #c7d2fe;
  background: var(--brand-soft);
  color: var(--brand-strong);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
  font-family: inherit;
}
.grade-link svg {
  width: 13px;
  height: 13px;
}
.grade-link:hover {
  background: var(--brand);
  color: #fff;
  border-color: var(--brand);
}
.list-item {
  text-align: left;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--surface);
  padding: 10px 12px;
  cursor: pointer;
  transition: all 0.15s;
  font-family: inherit;
}
.list-item:hover {
  border-color: var(--brand);
}
.list-item.active {
  border-color: var(--brand);
  background: var(--brand-soft);
}
.li-title {
  display: flex;
  align-items: center;
  gap: 8px;
}
/* 作业卡片标题：允许换行完整展示（最多 3 行），不挤压状态胶囊 */
.li-name {
  font-weight: 600;
  font-size: 13.5px;
  line-height: 1.55;
  color: var(--ink);
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
  word-break: break-word;
}
/* 状态胶囊独立一行，自动换行不与标题抢宽度 */
.li-pills {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 7px;
}
.li-meta {
  font-size: 12px;
  color: var(--ink-3);
  margin-top: 5px;
  line-height: 1.6;
  word-break: break-word;
}
.list-empty,
.list-loading {
  text-align: center;
  color: var(--ink-3);
  font-size: 13px;
  padding: 30px 0;
}

/* ===== 分组折叠视图 ===== */
.folder-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin: 10px 0 8px;
}
.folder-toolbar-title {
  font-size: 12.5px;
  font-weight: 700;
  color: var(--ink-2);
}
.folder-toolbar-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
}
.link-btn {
  border: none;
  background: none;
  color: var(--brand-strong);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  padding: 4px 6px;
  border-radius: 6px;
  font-family: inherit;
}
.link-btn:hover {
  background: var(--brand-soft);
}
.link-btn.active {
  background: var(--brand-soft);
}
.group-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  flex: 1;
  min-height: 0;
  /* 固定内容高度 + 内部滚轮：组再多也不会把外层撑爆，外层 .list-pane 高度被锁死 */
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-gutter: stable;
  scroll-padding-top: 4px;
  /* 底部安全区：最后一张卡片不会贴住边框/被滚动容器裁掉 */
  padding-bottom: 28px;
  padding-right: 6px;
}
.group-section {
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--surface);
  overflow: hidden;
  flex-shrink: 0;
}
.group-head {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  border: none;
  background: var(--bg);
  padding: 10px 12px;
  cursor: pointer;
  font-family: inherit;
  text-align: left;
  transition: background 0.15s;
}
.group-head:hover {
  background: var(--brand-soft);
}
.group-caret {
  width: 14px;
  height: 14px;
  flex-shrink: 0;
  color: var(--ink-3);
  transition: transform 0.15s;
}
.group-head.open .group-caret {
  transform: rotate(90deg);
}
.group-icon {
  width: 16px;
  height: 16px;
  flex-shrink: 0;
  color: #7c8cf8;
}
.group-name {
  flex: 1;
  min-width: 0;
  font-size: 13.5px;
  font-weight: 700;
  color: var(--ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.group-count {
  flex-shrink: 0;
  min-width: 22px;
  text-align: center;
  font-size: 11.5px;
  font-weight: 700;
  color: var(--ink-3);
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 2px 8px;
}
.group-pending {
  flex-shrink: 0;
  font-size: 11px;
  font-weight: 700;
  color: #b45309;
  background: var(--warning-soft);
  border-radius: 999px;
  padding: 2px 8px;
  white-space: nowrap;
}
.group-items {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 8px;
  border-top: 1px solid var(--line);
  /* 组内作业不再嵌套滚动：所有分组统一由外层 .group-list 滚动 */
  max-height: none;
  overflow: visible;
  overscroll-behavior: auto;
}
.group-empty {
  text-align: center;
  color: var(--ink-3);
  font-size: 12.5px;
  padding: 14px 0;
}
.select-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  background: var(--brand-soft);
  border: 1px solid var(--brand);
  border-radius: 10px;
  padding: 8px 10px;
  margin-bottom: 10px;
}
.select-bar .picked-count {
  font-size: 12px;
  font-weight: 700;
  color: var(--brand-strong);
  margin-left: auto;
}
.move-select {
  padding: 6px 8px;
  border: 1px solid var(--line);
  border-radius: 8px;
  font-size: 12.5px;
  font-family: inherit;
  background: var(--surface);
  color: var(--ink-2);
}
.pick-check {
  display: flex;
  align-items: center;
  flex-shrink: 0;
  padding: 0 2px;
}
.pick-check input {
  width: 15px;
  height: 15px;
  accent-color: #6366f1;
}
.pending-badge {
  position: absolute;
  top: -8px;
  right: -4px;
  display: inline-flex;
  align-items: center;
  gap: 3px;
  background: linear-gradient(135deg, #f59e0b, #ef4444);
  color: #fff;
  font-size: 10.5px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 999px;
  box-shadow: 0 2px 8px rgba(239, 68, 68, 0.35);
  z-index: 1;
}
.pending-badge svg {
  width: 10px;
  height: 10px;
}
.folder-modal {
  width: 480px;
  max-width: calc(100vw - 40px);
}
.folder-add-row {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}
.folder-add-input {
  flex: 1;
  padding: 9px 11px;
  border: 1px solid var(--line);
  border-radius: 10px;
  font-size: 13.5px;
  font-family: inherit;
}
.folder-add-input:focus {
  outline: none;
  border-color: var(--brand);
  box-shadow: 0 0 0 3px var(--brand-soft);
}
.folder-list {
  border: 1px solid var(--line);
  border-radius: 10px;
  max-height: 280px;
  overflow: auto;
  padding: 6px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.folder-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 10px;
  border-radius: 8px;
}
.folder-row:hover {
  background: var(--brand-soft);
}
.folder-row-name {
  flex: 1;
  font-size: 13.5px;
  font-weight: 600;
  color: var(--ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.folder-row-count {
  font-size: 12px;
  color: var(--ink-3);
  white-space: nowrap;
}

/* ===== 状态胶囊 ===== */
.pill {
  font-size: 11px;
  padding: 3px 9px;
  border-radius: 999px;
  font-weight: 600;
  white-space: nowrap;
}
.pill.draft {
  background: var(--warning-soft);
  color: #b45309;
}
.pill.pub {
  background: var(--success-soft);
  color: #047857;
}
.pill.makeup {
  background: #f3e8ff;
  color: #7c3aed;
}
.pill.classwork {
  background: #fef3c7;
  color: #b45309;
}
.pill.homework {
  background: #e0e7ff;
  color: #4338ca;
}

/* ===== 作业模式切换 ===== */
.mode-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 10px;
  flex-wrap: wrap;
}
.mode-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--ink-2);
}
.mode-hint {
  font-size: 12px;
  color: var(--ink-3);
}

/* ===== 课堂作业：学员选择 ===== */
.student-list {
  border: 1px solid var(--line);
  border-radius: 10px;
  max-height: 260px;
  overflow: auto;
  padding: 6px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin: 8px 0 10px;
}
.student-tags {
  font-size: 12px;
  color: var(--ink-3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  min-width: 0;
}
.publish-student-ops {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.picked-count {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--brand-strong);
  margin-left: auto;
}
.notify-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--ink-2);
  margin: 10px 0 4px;
}
.notify-row input {
  width: 15px;
  height: 15px;
  accent-color: #6366f1;
}

/* ===== 编辑器 ===== */
.editor-pane {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 18px;
  box-shadow: var(--shadow-sm);
  min-height: 560px;
}
.editor-title {
  display: flex;
  align-items: center;
  gap: 10px;
}
.title-input {
  flex: 1;
  font-size: 18px;
  font-weight: 700;
  border: none;
  outline: none;
  padding: 6px 0;
  font-family: inherit;
  color: var(--ink);
  border-bottom: 2px solid transparent;
  transition: border-color 0.15s;
  min-width: 0;
}
.title-input:focus {
  border-bottom-color: var(--brand);
}
.desc-input {
  width: 100%;
  box-sizing: border-box;
  margin-top: 10px;
  padding: 9px 11px;
  border: 1px solid var(--line);
  border-radius: 10px;
  font-size: 13.5px;
  font-family: inherit;
  resize: vertical;
  color: var(--ink-2);
}
.desc-input:focus {
  outline: none;
  border-color: var(--brand);
  box-shadow: 0 0 0 3px var(--brand-soft);
}
.err-banner {
  background: var(--danger-soft);
  color: var(--danger);
  font-size: 13px;
  border-radius: 9px;
  padding: 9px 12px;
  margin-top: 10px;
}
.ok-banner {
  background: var(--success-soft);
  color: #047857;
  font-size: 13px;
  border-radius: 9px;
  padding: 9px 12px;
  margin-top: 10px;
}
.editor-toolbar {
  display: flex;
  gap: 8px;
  margin-top: 12px;
  flex-wrap: wrap;
  align-items: center;
}
.toolbar-spacer {
  flex: 1;
}

/* ===== 按钮 ===== */
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
  font-family: inherit;
}
.btn svg {
  width: 14px;
  height: 14px;
  flex-shrink: 0;
}
.btn .btn-icon {
  width: 14px;
  height: 14px;
  flex-shrink: 0;
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
.btn.pool {
  background: #ecfdf5;
  border-color: #6ee7b7;
  color: #059669;
}
.btn.pool:hover {
  background: #d1fae5;
}
.btn.small {
  padding: 7px 12px;
  font-size: 12.5px;
}
.btn.danger {
  color: var(--danger);
}
.btn.danger:hover {
  border-color: var(--danger);
  color: var(--danger);
  background: var(--danger-soft);
}
.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* ===== 题号导航 + 每题一页 ===== */
.question-layout {
  display: grid;
  grid-template-columns: 64px 1fr;
  gap: 16px;
  margin-top: 16px;
}
.qnav {
  display: flex;
  flex-direction: column;
  gap: 6px;
  align-items: center;
}
.qnum {
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
  font-family: inherit;
}
.qnum:hover {
  border-color: var(--brand);
}
.qnum.active {
  background: linear-gradient(135deg, #6366f1, #06b6d4);
  color: #fff;
  border-color: transparent;
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.35);
}
.qnum.done:not(.active) {
  background: var(--success-soft);
  color: #047857;
  border-color: #a7f3d0;
}
.qnum.add {
  border-style: dashed;
  color: var(--brand);
  font-size: 18px;
}
.q-edit {
  min-width: 0;
}
.q-top {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
}
.q-no {
  font-size: 15px;
  font-weight: 700;
  color: var(--ink);
}
.type-select {
  padding: 7px 10px;
  border: 1px solid var(--line);
  border-radius: 9px;
  font-size: 13px;
  font-family: inherit;
  color: var(--ink-2);
  background: var(--surface);
}
.type-select:focus {
  outline: none;
  border-color: var(--brand);
}
.q-ops {
  margin-left: auto;
  display: flex;
  gap: 5px;
}
.op-btn {
  width: 28px;
  height: 28px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--line);
  background: var(--surface);
  border-radius: 8px;
  color: var(--ink-3);
  font-size: 14px;
  cursor: pointer;
  line-height: 1;
  font-family: inherit;
}
.op-btn svg {
  width: 14px;
  height: 14px;
}
.op-btn:hover {
  border-color: var(--brand);
  color: var(--brand);
}
.op-btn.danger:hover {
  border-color: var(--danger);
  color: var(--danger);
}
.op-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.field {
  margin-bottom: 14px;
}
.field-label {
  display: block;
  font-size: 13px;
  font-weight: 600;
  color: var(--ink-2);
  margin-bottom: 6px;
}
.stem-input,
.code-input,
.analysis-input {
  width: 100%;
  box-sizing: border-box;
  padding: 9px 11px;
  border: 1px solid var(--line);
  border-radius: 10px;
  font-size: 13.5px;
  font-family: inherit;
  resize: vertical;
  color: var(--ink);
}
.stem-input:focus,
.code-input:focus,
.analysis-input:focus {
  outline: none;
  border-color: var(--brand);
  box-shadow: 0 0 0 3px var(--brand-soft);
}
.code-input {
  font-family: 'JetBrains Mono', Consolas, monospace;
  background: #0f172a;
  color: #e2e8f0;
}
.option-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 7px;
}
.opt-letter {
  width: 20px;
  font-weight: 700;
  color: var(--ink-3);
  font-size: 13px;
  flex-shrink: 0;
}
.opt-input {
  flex: 1;
  padding: 8px 10px;
  border: 1px solid var(--line);
  border-radius: 9px;
  font-size: 13.5px;
  font-family: inherit;
}
.opt-input:focus {
  outline: none;
  border-color: var(--brand);
}
.answer-btns {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.ans-btn {
  width: 44px;
  height: 36px;
  border: 1px solid var(--line);
  background: var(--surface);
  border-radius: 9px;
  font-size: 13px;
  font-weight: 600;
  color: var(--ink-2);
  cursor: pointer;
  transition: all 0.15s;
  font-family: inherit;
}
.ans-btn:hover {
  border-color: var(--brand);
}
.ans-btn.picked {
  background: var(--success-soft);
  border-color: var(--success);
  color: #047857;
}
.stars {
  display: flex;
  gap: 2px;
  flex-wrap: wrap;
  margin-top: 6px;
}
.star {
  border: none;
  background: none;
  font-size: 16px;
  color: var(--line);
  cursor: pointer;
  padding: 0;
}
.star.on {
  color: #f59e0b;
}
.difficulty-head {
  display: flex;
  align-items: center;
  gap: 10px;
}
.difficulty-head .small-select {
  margin: 0;
}
.difficulty-hint {
  font-size: 11.5px;
  color: var(--ink-3);
  margin-top: 5px;
}
.tc-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 7px;
}
.tc-arrow {
  color: var(--ink-3);
  font-size: 13px;
}

/* ===== 答案折叠 ===== */
.answer-fold {
  border: 1px dashed var(--line);
  border-radius: 10px;
  padding: 10px 12px;
  margin-top: 4px;
}
.fold-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  border: none;
  background: none;
  color: var(--ink-3);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  padding: 0;
  font-family: inherit;
}
.fold-btn svg {
  width: 13px;
  height: 13px;
}
.fold-btn:hover {
  color: var(--brand);
}
.fold-body {
  margin-top: 12px;
}
.answer-preview {
  background: #f8fafc;
  border: 1px solid var(--line);
  border-radius: 9px;
  padding: 10px 12px;
  font-size: 13px;
  color: var(--ink-2);
}
.answer-preview.code {
  display: block;
  white-space: pre-wrap;
  word-break: break-word;
  margin: 0;
  background: rgba(15, 23, 42, 0.92);
  color: #e2e8f0;
  font-family: 'Cascadia Code', 'JetBrains Mono', Consolas, monospace;
  font-size: 12.5px;
  line-height: 1.7;
}
.q-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 16px;
}
.q-count {
  color: var(--ink-3);
  font-size: 12.5px;
}

/* ===== 编辑器空态 ===== */
.editor-empty {
  height: 480px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: var(--ink-3);
  gap: 12px;
}
.editor-empty svg {
  width: 52px;
  height: 52px;
  opacity: 0.4;
}
.editor-empty p {
  font-size: 13.5px;
}

/* ===== 弹窗 ===== */
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
  max-height: 86vh;
  overflow: auto;
}
.ai-modal {
  width: 560px;
  max-width: calc(100vw - 40px);
}
.refine-modal {
  width: 500px;
  max-width: calc(100vw - 40px);
}
.publish-modal {
  width: 420px;
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
.modal textarea,
.modal input[type='datetime-local'] {
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
.modal textarea:focus,
.modal input[type='datetime-local']:focus {
  outline: none;
  border-color: var(--brand);
  box-shadow: 0 0 0 3px var(--brand-soft);
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 20px;
}
.ai-tabs {
  display: flex;
  gap: 6px;
  margin-bottom: 14px;
}
.ai-title-input {
  display: block;
  width: 100%;
  box-sizing: border-box;
  margin-top: 6px;
  padding: 9px 11px;
  border: 1px solid var(--line);
  border-radius: 10px;
  font-size: 14px;
  font-family: inherit;
}
.ai-title-input:focus {
  outline: none;
  border-color: var(--brand);
  box-shadow: 0 0 0 3px var(--brand-soft);
}
.tab {
  flex: 1;
  padding: 9px 0;
  border: 1px solid var(--line);
  background: var(--surface);
  border-radius: 10px;
  font-size: 13.5px;
  font-weight: 600;
  color: var(--ink-3);
  cursor: pointer;
  transition: all 0.15s;
  font-family: inherit;
}
.tab.active {
  background: var(--brand-soft);
  border-color: var(--brand);
  color: var(--brand-strong);
}
.ai-form label {
  margin-bottom: 12px;
}
.ai-row {
  display: flex;
  gap: 12px;
}
.ai-row .inline {
  flex: 1;
}
.inline-hint {
  font-size: 11.5px;
  color: var(--ink-3);
  margin-top: 4px;
  display: block;
}
.ai-count-tip {
  font-size: 12px;
  color: var(--ink-3);
  margin: 8px 0 0;
  line-height: 1.6;
}
.small-select {
  display: block;
  width: 100%;
  margin-top: 6px;
  padding: 8px 10px;
  border: 1px solid var(--line);
  border-radius: 9px;
  font-size: 13.5px;
  background: var(--surface);
  font-family: inherit;
}
.type-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 6px;
}
.ai-status {
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 12px;
  background: #f8fafc;
  margin-bottom: 12px;
}
.ai-progress-line {
  display: flex;
  align-items: center;
  gap: 10px;
}
.ai-status-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
  background: #94a3b8;
}
.ai-status-dot.pending {
  background: #f59e0b;
  animation: pulse 1.2s infinite;
}
.ai-status-dot.running {
  background: var(--brand);
  animation: pulse 1.2s infinite;
}
.ai-status-dot.done {
  background: var(--success);
}
.ai-status-dot.failed {
  background: var(--danger);
}
@keyframes pulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.4;
  }
}
.ai-stage {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--ink);
}
.ai-substage {
  font-size: 12px;
  color: var(--ink-3);
  margin-top: 2px;
}
.ai-progress-bar {
  height: 6px;
  background: var(--line);
  border-radius: 999px;
  margin: 10px 0;
  overflow: hidden;
}
.ai-progress-fill {
  height: 100%;
  border-radius: 999px;
  transition: width 0.4s ease;
  background: linear-gradient(90deg, #6366f1, #06b6d4);
  animation: shimmer 1.6s infinite;
}
.ai-progress-fill.done {
  background: var(--success);
  animation: none;
}
.ai-progress-fill.failed {
  background: var(--danger);
  animation: none;
}
@keyframes shimmer {
  0% {
    background-position: 0% 0;
  }
  100% {
    background-position: 200% 0;
  }
}
.ai-status-tip {
  font-size: 12.5px;
  color: var(--ink-3);
}
.ai-refine-result {
  margin-bottom: 12px;
}
.ai-refine-result .ai-status-tip {
  margin-bottom: 8px;
}
.ai-result-actions {
  display: flex;
  justify-content: flex-end;
  gap: 6px;
  padding: 8px 6px 4px;
}
.ai-result {
  border: 1px solid var(--line);
  border-radius: 10px;
  max-height: 220px;
  overflow: auto;
  padding: 6px;
}
.ai-q {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  padding: 8px 10px;
  border-bottom: 1px solid var(--line);
  font-size: 13px;
  color: var(--ink-2);
}
.ai-q:last-child {
  border-bottom: none;
}
.ai-result .pick-line {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin: 0;
  padding: 0;
  width: 100%;
}
.pick-line input {
  margin-top: 3px;
}
.ai-q-type {
  flex-shrink: 0;
  font-size: 11px;
  font-weight: 700;
  color: #7c3aed;
  background: #f5f3ff;
  border-radius: 6px;
  padding: 2px 7px;
}
.ai-q-stem {
  line-height: 1.5;
}
.publish-filters {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 6px;
}
.publish-filters label {
  margin-bottom: 4px;
}
.publish-filters .ssel {
  margin-top: 6px;
}
.publish-class {
  margin-top: 6px;
}

/* ===== 多班级复选（发布弹窗，M4.1） ===== */
.publish-classes {
  display: block;
  margin: 8px 0 14px;
}
.publish-classes-title {
  display: block;
  font-size: 13px;
  color: var(--ink-2);
  font-weight: 500;
}
.class-search {
  display: block;
  width: 100%;
  box-sizing: border-box;
  margin-top: 6px;
  padding: 8px 11px;
  border: 1px solid var(--line);
  border-radius: 9px;
  font-size: 13.5px;
  font-family: inherit;
}
.class-search:focus {
  outline: none;
  border-color: var(--brand);
  box-shadow: 0 0 0 3px var(--brand-soft);
}
.class-list {
  margin-top: 8px;
  max-height: 220px;
  overflow: auto;
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 6px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.publish-classes .class-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.12s;
  margin-bottom: 0;
  line-height: 1.2;
  min-height: 38px;
  box-sizing: border-box;
}
.publish-classes .class-item:hover {
  background: var(--brand-soft);
}
.publish-classes .class-item.disabled {
  cursor: not-allowed;
  opacity: 0.55;
}
.publish-classes .class-item.disabled:hover {
  background: transparent;
}
.publish-classes .class-item input[type='checkbox'] {
  width: 15px;
  height: 15px;
  accent-color: #6366f1;
  flex-shrink: 0;
  margin: 0;
  vertical-align: middle;
}
.class-name {
  flex: 1;
  font-size: 13.5px;
  color: var(--ink);
}
.tag {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 999px;
  white-space: nowrap;
}
.tag.published {
  background: var(--line);
  color: var(--ink-3);
}
.tag.picked {
  background: var(--brand-soft);
  color: var(--brand-strong);
}
.class-empty {
  text-align: center;
  color: var(--ink-3);
  font-size: 13px;
  padding: 18px 0;
}
.published-tip {
  margin-top: 8px;
  font-size: 12px;
  color: var(--ink-3);
  line-height: 1.6;
}

/* ===== 发布弹窗：题型分值 + 达标线 ===== */
.score-config {
  background: #f8fafc;
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 12px 14px;
}
.score-config-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
  font-weight: 700;
  color: var(--ink);
  margin-bottom: 8px;
}
.score-total {
  color: var(--brand-strong);
  font-weight: 800;
}
.score-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 8px;
}
.score-item {
  display: flex;
  align-items: center;
  gap: 6px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 6px 10px;
}
.score-label {
  flex: 1;
  font-size: 12.5px;
  color: var(--ink-2);
  font-weight: 600;
}
.score-item input,
.pass-line input {
  width: 58px;
  padding: 4px 6px;
  border: 1px solid var(--line);
  border-radius: 6px;
  font-size: 13px;
  text-align: center;
  outline: none;
}
.score-item input:focus,
.pass-line input:focus {
  border-color: var(--brand);
}
.score-unit {
  font-size: 11px;
  color: var(--ink-3);
  flex-shrink: 0;
}
.pass-line {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 10px;
  font-size: 13px;
  font-weight: 600;
  color: var(--ink);
}
.pass-label {
  flex: 1;
}
.target-tip {
  margin-top: 8px;
  font-size: 12px;
  color: var(--brand-strong);
  background: var(--brand-soft);
  padding: 6px 10px;
  border-radius: 8px;
}

/* ===== 历史题目选择弹窗（复用已发布作业题目） ===== */
.pool-modal {
  width: 560px;
  max-width: calc(100vw - 40px);
}
.pool-keyword {
  display: block;
  width: 100%;
  box-sizing: border-box;
  margin-bottom: 14px;
  padding: 9px 11px;
  border: 1px solid var(--line);
  border-radius: 10px;
  font-size: 14px;
  font-family: inherit;
}
.pool-keyword:focus {
  outline: none;
  border-color: var(--brand);
  box-shadow: 0 0 0 3px var(--brand-soft);
}
.pool-filter-label {
  display: block;
  margin-bottom: 12px;
  font-size: 13px;
  color: var(--ink-2);
  font-weight: 500;
}
.pool-filter-label .type-chips {
  margin-top: 6px;
}
.pool-diff-range {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 6px;
}
.pool-diff-range .small-select {
  margin-top: 0;
  width: 96px;
}
.pool-range-sep {
  color: var(--ink-3);
}
.pool-results {
  border: 1px solid var(--line);
  border-radius: 10px;
  overflow: hidden;
  margin-bottom: 6px;
}
.pool-list {
  max-height: 300px;
  overflow: auto;
  padding: 6px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.pool-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.12s;
}
.pool-item:hover {
  border-color: var(--brand);
  background: var(--brand-soft);
}
.pool-item.picked {
  border-color: var(--brand);
  background: var(--brand-soft);
}
.pool-check {
  width: 15px;
  height: 15px;
  accent-color: #6366f1;
  flex-shrink: 0;
  margin-top: 2px;
  cursor: pointer;
}
.pool-item-body {
  min-width: 0;
  flex: 1;
}
.pool-item-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 4px;
}
.pool-diff-badge {
  flex-shrink: 0;
  font-size: 11px;
  font-weight: 700;
  color: #b45309;
  background: var(--warning-soft);
  border-radius: 6px;
  padding: 2px 7px;
}
.pool-source {
  flex-shrink: 0;
  font-size: 11.5px;
  color: var(--ink-3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 240px;
}
.pool-item-stem {
  font-size: 13px;
  color: var(--ink-2);
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.pool-empty {
  text-align: center;
  color: var(--ink-3);
  font-size: 13px;
  padding: 26px 0;
}

/* —— 举一反三：原题导入按钮行 —— */
.source-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}
.source-row textarea {
  flex: 1;
  min-width: 0;
}
.source-import {
  flex-shrink: 0;
  white-space: nowrap;
}
.pool-source-icon {
  width: 16px;
  height: 16px;
  flex-shrink: 0;
  margin-top: 2px;
  color: #7c3aed;
}

@media (max-width: 900px) {
  .workspace {
    grid-template-columns: 1fr;
  }
  .list-pane {
    position: static;
  }
  .question-layout {
    grid-template-columns: 48px 1fr;
  }
}
</style>
