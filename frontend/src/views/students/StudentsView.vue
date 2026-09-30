<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'

import PageHead from '@/components/PageHead.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import PaginationBar from '@/components/PaginationBar.vue'
import StudentFilter, { type StudentFilterValue } from '@/components/StudentFilter.vue'
import { pinyinInitials } from '@/utils/pinyin'
import { listCampusesApi, listTeachersApi, registerApi, resetUserPasswordApi } from '@/api/auth'
import {
  adjustLessonBalance,
  createStudent,
  deleteStudent,
  listClasses,
  listLessonRecords,
  listStudents,
  refundStudent,
  refundStudentPreview,
  renewStudent,
  listPackages,
  updateStudent,
  updateStudentClasses,
  updateStudentFollowUp,
  updateStudentStatus,
  type ClassOut,
  type LessonPackageOut,
  type LessonRecordOut,
  type StudentCreate,
  type StudentOut,
} from '@/api/enrollment'
import { listUsersApi } from '@/api/client'
import { myPermissions } from '@/api/permissions'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const isAdmin = computed(() => auth.user?.role === 'admin')
// 当前用户操作权限：管理员/教务全开；教师按权限管理配置（后端兜底 403）
const myPerms = ref<Record<string, boolean>>({})
const can = (key: string): boolean => {
  if (auth.user?.role !== 'teacher') return true
  return myPerms.value[key] !== false
}
async function loadMyPerms() {
  if (auth.user?.role !== 'teacher') return
  try {
    myPerms.value = await myPermissions()
  } catch {
    myPerms.value = {}
  }
}
// 无权限点击 → 统一提示框（按钮保持可见，点击弹提示）
const showNoPerm = ref(false)
const noPermText = ref('')
function guard(key: string, action: () => void) {
  if (can(key)) action()
  else {
    noPermText.value = '暂无该操作权限，请联系管理员开通。'
    showNoPerm.value = true
  }
}

const students = ref<StudentOut[]>([])
const classes = ref<ClassOut[]>([])
const keyword = ref('')
const campusFilter = ref('')
const accountFilter = ref<'' | 'unbound_student' | 'unbound_parent'>('')
const statusFilter = ref('')
const lessonMin = ref<string>('')
const lessonMax = ref<string>('')
const classKeyword = ref('')
const classTeacherId = ref('')
const classId = ref('')
const loading = ref(false)
const error = ref('')

/** 学员管理主筛选（跨端复用组件的绑定值，由内部联动维护） */
const mainFilter = ref<StudentFilterValue>({
  campus: '',
  teacherId: '',
  classId: '',
  keyword: '',
  account: '',
})

// 分页
const page = ref(1)
const pageSize = 10
const total = ref(0)

const showForm = ref(false)
const editing = ref<StudentOut | null>(null)
const form = ref<StudentCreate>({ name: '', phone: '', campus: '', lesson_balance: 0, class_ids: [] })
const formError = ref('')

const showRecords = ref(false)
const records = ref<LessonRecordOut[]>([])
const recordsStudent = ref<StudentOut | null>(null)

const showAdjust = ref(false)
const adjustDelta = ref(0)
const adjustRemark = ref('')
const adjustStudent = ref<StudentOut | null>(null)

// 统一确认弹窗（替代 window.confirm）
interface ConfirmAsk {
  visible: boolean
  title: string
  message: string
  confirmText: string
  danger: boolean
  onConfirm: () => void | Promise<void>
}
const confirmState = reactive<ConfirmAsk>({
  visible: false,
  title: '',
  message: '',
  confirmText: '确认',
  danger: false,
  onConfirm: () => {},
})
function askConfirm(opts: {
  title: string
  message: string
  confirmText?: string
  danger?: boolean
  onConfirm: () => void | Promise<void>
}) {
  confirmState.title = opts.title
  confirmState.message = opts.message
  confirmState.confirmText = opts.confirmText || '确认'
  confirmState.danger = !!opts.danger
  confirmState.onConfirm = opts.onConfirm
  confirmState.visible = true
}
async function runConfirm() {
  confirmState.visible = false
  await confirmState.onConfirm()
}

const isTeacher = computed(() => auth.user?.role === 'teacher')
/** 教师可管理的班级：仅本人所带班级；管理员/教务为全部班级 */
const manageableClasses = computed(() =>
  isTeacher.value ? classes.value.filter((c) => c.teacher_id === auth.user?.id) : classes.value,
)

const campusOptions = ref<string[]>([])
const teacherOptions = ref<{ id: string; name: string; campus: string | null }[]>([])

// 退费弹窗（FIFO 自动计算明细）
interface RefundItem {
  order_id: string
  package_name: string
  purchased_lessons: number
  remaining_lessons: number
  unit_price: string
  refund_amount: string
}
const showRefund = ref(false)
const refundStudentRef = ref<StudentOut | null>(null)
const refundPreview = ref<RefundItem[]>([])
const refundTotal = ref('0.00')
const refundLessons = ref(0)
const refundLoading = ref(false)
const refundNote = ref('')
const refundSubmitting = ref(false)
const refundError = ref('')

async function openRefund(s: StudentOut) {
  refundStudentRef.value = s
  refundNote.value = ''
  refundError.value = ''
  refundSubmitting.value = false
  refundPreview.value = []
  refundTotal.value = '0.00'
  refundLessons.value = 0
  showRefund.value = true
  refundLoading.value = true
  try {
    const data = await refundStudentPreview(s.id)
    refundPreview.value = data.items
    refundTotal.value = data.total_amount
    refundLessons.value = data.total_lessons
  } catch (e: any) {
    refundError.value = e?.response?.data?.detail || '无法计算退费明细'
  } finally {
    refundLoading.value = false
  }
}

async function submitRefund() {
  if (!refundStudentRef.value || !refundNote.value.trim()) {
    refundError.value = '请填写退费备注'
    return
  }
  refundSubmitting.value = true
  refundError.value = ''
  try {
    const res = await refundStudent(refundStudentRef.value.id, refundNote.value.trim())
    window.alert(`退费完成，合计 ¥${Number(res.total_amount).toFixed(2)}（${res.total_lessons} 课时）`)
    showRefund.value = false
    await load()
  } catch (e: any) {
    refundError.value = e?.response?.data?.detail || '退费失败'
  } finally {
    refundSubmitting.value = false
  }
}

// 停课弹窗（需填备注）
const showStop = ref(false)
const stopStudent = ref<StudentOut | null>(null)
const stopNote = ref('')
const stopSubmitting = ref(false)

const stats = ref({ total: 0, low: 0 })

// ========== 缴费名单（催缴）子页面：从学员管理切换进入 ==========
const viewMode = ref<'students' | 'collection'>('students')
const collectionStudents = ref<StudentOut[]>([])
const collectionPackages = ref<LessonPackageOut[]>([])
const collectionFollowUpTab = ref<'all' | 'pending' | 'renewed' | 'stopped'>('all')
const collectionPage = ref(1)
const collectionPageSize = 10
const collectionTotal = ref(0)
const collectionSummary = ref({ total: 0, urgent: 0, renewed: 0 })
const collectionLoading = ref(false)
const collectionError = ref('')

const collectionFilter = ref<StudentFilterValue>({
  campus: '',
  teacherId: '',
  classId: '',
  keyword: '',
  account: '',
})

async function loadCollection() {
  collectionLoading.value = true
  collectionError.value = ''
  try {
    const pageData = await listStudents({
      low_balance_only: true,
      keyword: collectionFilter.value.keyword || undefined,
      campus:
        collectionFilter.value.campus && collectionFilter.value.campus !== '__unassigned__'
          ? collectionFilter.value.campus
          : undefined,
      campus_unassigned: collectionFilter.value.campus === '__unassigned__' || undefined,
      teacher_id:
        collectionFilter.value.teacherId && collectionFilter.value.teacherId !== '__unassigned__'
          ? collectionFilter.value.teacherId
          : undefined,
      teacher_unassigned: collectionFilter.value.teacherId === '__unassigned__' || undefined,
      class_id:
        collectionFilter.value.classId && collectionFilter.value.classId !== '__unassigned__'
          ? collectionFilter.value.classId
          : undefined,
      class_unassigned: collectionFilter.value.classId === '__unassigned__' || undefined,
      account: collectionFilter.value.account || undefined,
      follow_up:
        collectionFollowUpTab.value === 'all' ? undefined : collectionFollowUpTab.value,
      limit: collectionPageSize,
      offset: (collectionPage.value - 1) * collectionPageSize,
    })
    const list = pageData.items
    // 待跟进优先，其次按课时余额升序
    collectionStudents.value = [...list].sort((a, b) => {
      const pa = a.follow_up_status === 'pending' ? 0 : 1
      const pb = b.follow_up_status === 'pending' ? 0 : 1
      if (pa !== pb) return pa - pb
      return a.lesson_balance - b.lesson_balance
    })
    collectionTotal.value = pageData.total
    collectionSummary.value = {
      total: pageData.total,
      urgent: list.filter((s) => s.lesson_balance <= 5 && s.follow_up_status === 'pending').length,
      renewed: list.filter((s) => s.follow_up_status === 'renewed').length,
    }
  } catch {
    collectionError.value = '加载缴费名单失败'
  } finally {
    collectionLoading.value = false
  }
}

function switchToCollection() {
  viewMode.value = 'collection'
  collectionPage.value = 1
  if (collectionPackages.value.length === 0) {
    listPackages(true)
      .then((p) => (collectionPackages.value = p.items))
      .catch(() => (collectionPackages.value = []))
  }
  void loadCollection()
}

function backToStudents() {
  viewMode.value = 'students'
  void load()
}

const followUpLabel: Record<string, string> = {
  pending: '待跟进',
  renewed: '已续费',
  stopped: '已停课',
}

// —— 已续费弹窗：选课包 / 自定义 ——
const showRenew = ref(false)
const renewTarget = ref<StudentOut | null>(null)
const renewMode = ref<'package' | 'custom'>('package')
const renewPackageId = ref('')
const renewCustomLessons = ref<number | null>(null)
const renewCustomAmount = ref<number | null>(null)
const renewNote = ref('')
const renewError = ref('')
const renewSubmitting = ref(false)

function openRenew(s: StudentOut) {
  renewTarget.value = s
  renewMode.value = 'package'
  renewPackageId.value = ''
  renewCustomLessons.value = null
  renewCustomAmount.value = null
  renewNote.value = ''
  renewError.value = ''
  showRenew.value = true
}

async function submitRenew() {
  if (!renewTarget.value) return
  renewError.value = ''
  if (renewMode.value === 'package' && !renewPackageId.value) {
    renewError.value = '请选择课时包'
    return
  }
  if (renewMode.value === 'custom' && !(renewCustomLessons.value ?? 0)) {
    renewError.value = '请填写补充课时'
    return
  }
  renewSubmitting.value = true
  try {
    await renewStudent(renewTarget.value.id, {
      package_id: renewMode.value === 'package' ? renewPackageId.value : undefined,
      custom_lessons: renewMode.value === 'custom' ? renewCustomLessons.value ?? 0 : undefined,
      custom_amount: renewMode.value === 'custom' ? renewCustomAmount.value ?? 0 : undefined,
      note: renewNote.value || null,
    })
    showRenew.value = false
    await loadCollection()
  } catch (e: any) {
    renewError.value = e?.response?.data?.detail || '续费失败'
  } finally {
    renewSubmitting.value = false
  }
}

async function markFollowUp(s: StudentOut, status: string) {
  try {
    await updateStudentFollowUp(s.id, { follow_up_status: status })
    await loadCollection()
  } catch (e: any) {
    collectionError.value = e?.response?.data?.detail || '更新跟进状态失败'
  }
}

const classOptions = computed(() => {
  // 级联：选择教师后，班级下拉只显示该教师所带班级；
  // 选择“未分配教师”后，班级下拉只显示未分配教师的班级
  let pool = classes.value
  if (classTeacherId.value === '__unassigned__') {
    pool = pool.filter((c) => !c.teacher_id)
  } else if (classTeacherId.value) {
    pool = pool.filter((c) => c.teacher_id === classTeacherId.value)
  }
  const kw = classKeyword.value.trim().toLowerCase()
  return pool.filter((c) => {
    const matchesKeyword =
      !kw || c.name.toLowerCase().includes(kw) || c.subject.toLowerCase().includes(kw)
    return matchesKeyword
  })
})

/** 班级教师下拉：选择校区后，只显示对应校区的教师（另设“未分配”选项） */
const filteredTeacherOptions = computed(() => {
  const list = campusFilter.value
    ? teacherOptions.value.filter((t) => t.campus === campusFilter.value)
    : teacherOptions.value
  return list
})

// 家长/学员账号搜索（M5 客户端绑定）
const parentUserSearch = ref('')
const parentUsers = ref<{ id: string; name: string; username: string; role: string; phone: string | null }[]>([])
const parentUserKeyword = ref('')
const parentUserLoading = ref(false)
const studentUserSearch = ref('')
const studentUsers = ref<{ id: string; name: string; username: string; role: string; phone: string | null }[]>([])
const studentUserKeyword = ref('')
const studentUserLoading = ref(false)

// —— 编辑弹窗：班级选择器（校区 / 带教教师 联动筛选候选班级）——
const classPickerCampus = ref('')
const classPickerTeacherId = ref('')

/** 编辑弹窗候选班级：所选校区教师所带班级（教师按校区收敛）+ 关键字过滤；已勾选的始终保留 */
const pickerTeacherOptions = computed(() => {
  if (!classPickerCampus.value || classPickerCampus.value === '__unassigned__') {
    return teacherOptions.value
  }
  return teacherOptions.value.filter((t) => t.campus === classPickerCampus.value)
})

const pickerClasses = computed(() => {
  let pool = classes.value
  if (classPickerCampus.value === '__unassigned__') {
    // 学员校区“未分配”只是学员自己的属性，这里不强制过滤班级（班级看教师归口）
  } else if (classPickerCampus.value) {
    const ids = new Set(
      teacherOptions.value.filter((t) => t.campus === classPickerCampus.value).map((t) => t.id),
    )
    pool = pool.filter((c) => (c.teacher_id && ids.has(c.teacher_id)) || form.value.class_ids.includes(c.id))
  }
  if (classPickerTeacherId.value === '__unassigned__') {
    pool = pool.filter((c) => !c.teacher_id || form.value.class_ids.includes(c.id))
  } else if (classPickerTeacherId.value) {
    pool = pool.filter((c) => c.teacher_id === classPickerTeacherId.value || form.value.class_ids.includes(c.id))
  }
  return pool
})

// 班级搜索（编辑弹窗内筛选）
const classSearch = ref('')
const filteredClasses = computed(() => {
  let pool = pickerClasses.value
  const q = classSearch.value.trim().toLowerCase()
  if (!q) return pool
  return pool.filter(
    (c) => c.name.toLowerCase().includes(q) || c.subject.toLowerCase().includes(q),
  )
})

function resetClassPicker() {
  classPickerCampus.value = ''
  classPickerTeacherId.value = ''
  classSearch.value = ''
}

watch(classPickerCampus, () => {
  // 校区切换：教师失效则清空（班级由 computed 自动收敛，已勾选的保留）
  if (
    classPickerTeacherId.value &&
    classPickerTeacherId.value !== '__unassigned__' &&
    !pickerTeacherOptions.value.some((t) => t.id === classPickerTeacherId.value)
  ) {
    classPickerTeacherId.value = ''
  }
})

async function loadParentUsers() {
  parentUserLoading.value = true
  try {
    const data = await listUsersApi({
      role: 'parent',
      keyword: parentUserKeyword.value || undefined,
      limit: 50,
    })
    parentUsers.value = data.items
  } catch {
    parentUsers.value = []
  } finally {
    parentUserLoading.value = false
  }
}

async function loadStudentUsers() {
  studentUserLoading.value = true
  try {
    const data = await listUsersApi({
      role: 'student',
      keyword: studentUserKeyword.value || undefined,
      limit: 50,
    })
    studentUsers.value = data.items
  } catch {
    studentUsers.value = []
  } finally {
    studentUserLoading.value = false
  }
}

const parentUserLabel = computed(() => {
  const s = editing.value
  if (!s?.parent_user_id) return ''
  const u = parentUsers.value.find((x) => x.id === s.parent_user_id)
  return u ? `${u.name}（${u.username}）` : s.parent_user_id.slice(0, 8)
})

const studentUserLabel = computed(() => {
  const s = editing.value
  if (!s?.student_user_id) return ''
  const u = studentUsers.value.find((x) => x.id === s.student_user_id)
  return u ? `${u.name}（${u.username}）` : s.student_user_id.slice(0, 8)
})

// —— 新客户账号创建（默认密码 123456）——
const showCreateParent = ref(false)
const createParentUsername = ref('')
const creatingParent = ref(false)
const createParentError = ref('')
const showCreateStudent = ref(false)
const createStudentUsername = ref('')
const creatingStudentUser = ref(false)
const createStudentError = ref('')

// —— 管理员重置已绑定账号密码（默认 123456）——
const resetTarget = ref<{ kind: 'parent' | 'student'; id: string; label: string } | null>(null)
const resetNewPw = ref('123456')
const resetMsg = ref('')
const resetSubmitting = ref(false)

function openCreateParentForm() {
  showCreateParent.value = !showCreateParent.value
  // 家长账号：登录名默认=学员电话号码，密码默认 123456
  createParentUsername.value = showCreateParent.value ? (form.value.phone || '').trim() : ''
  createParentError.value = ''
}

function openCreateStudentForm() {
  showCreateStudent.value = !showCreateStudent.value
  // 学员账号：登录名默认=姓名缩写+家长电话（如：露露+138… → ll138…）；用户名必须 ≥3 位
  const phone = (form.value.phone || '').trim()
  const abbr = pinyinInitials(form.value.name || '')
  createStudentUsername.value = showCreateStudent.value && abbr && phone ? `${abbr}${phone}` : ''
  createStudentError.value = ''
}

/** 输入变化时自动补默认登录名（用户手动改过则不再覆盖） */
const parentUsernameTouched = ref(false)
const studentUsernameTouched = ref(false)

function onParentUsernameInput() {
  parentUsernameTouched.value = true
}
function onStudentUsernameInput() {
  studentUsernameTouched.value = true
}

watch(
  () => [form.value.phone, form.value.name],
  () => {
    if (showCreateParent.value && !parentUsernameTouched.value) {
      createParentUsername.value = (form.value.phone || '').trim()
    }
    if (showCreateStudent.value && !studentUsernameTouched.value) {
      const phone = (form.value.phone || '').trim()
      const abbr = pinyinInitials(form.value.name || '')
      createStudentUsername.value = abbr && phone ? `${abbr}${phone}` : ''
    }
  },
)

async function createParentAccount() {
  createParentError.value = ''
  const username = createParentUsername.value.trim()
  const name = parentUserSearch.value.trim()
  if (!username || username.length < 3) {
    createParentError.value = '请填写登录名（至少 3 位字母/数字）'
    return
  }
  if (!name) {
    createParentError.value = '请先在搜索框输入家长姓名，用于账号显示名'
    return
  }
  creatingParent.value = true
  try {
    const user = await registerApi({ role: 'parent', username, password: '123456', name })
    await loadParentUsers()
    bindParent(user.id)
    showCreateParent.value = false
    createParentError.value = ''
  } catch (e: any) {
    createParentError.value =
      e?.response?.data?.detail === 'Username already exists'
        ? '该登录名已被占用，请换一个'
        : e?.response?.data?.detail || '创建失败，请重试'
  } finally {
    creatingParent.value = false
  }
}

async function createStudentAccount() {
  createStudentError.value = ''
  const username = createStudentUsername.value.trim()
  const name = studentUserSearch.value.trim()
  if (!username || username.length < 3) {
    createStudentError.value = '请填写登录名（至少 3 位字母/数字）'
    return
  }
  if (!name) {
    createStudentError.value = '请先在搜索框输入学员姓名，用于账号显示名'
    return
  }
  creatingStudentUser.value = true
  try {
    const user = await registerApi({ role: 'student', username, password: '123456', name })
    await loadStudentUsers()
    bindStudentUser(user.id)
    showCreateStudent.value = false
    createStudentError.value = ''
  } catch (e: any) {
    createStudentError.value =
      e?.response?.data?.detail === 'Username already exists'
        ? '该登录名已被占用，请换一个'
        : e?.response?.data?.detail || '创建失败，请重试'
  } finally {
    creatingStudentUser.value = false
  }
}

function openReset(kind: 'parent' | 'student', id: string, label: string) {
  resetTarget.value = { kind, id, label }
  resetNewPw.value = '123456'
  resetMsg.value = ''
}

async function confirmReset() {
  if (!resetTarget.value) return
  const pw = resetNewPw.value.trim()
  if (pw.length < 6) {
    resetMsg.value = '密码至少 6 位'
    return
  }
  resetSubmitting.value = true
  resetMsg.value = ''
  try {
    await resetUserPasswordApi(resetTarget.value.id, pw)
    resetMsg.value = '密码已更新 ✓'
    setTimeout(() => {
      resetTarget.value = null
    }, 900)
  } catch (e: any) {
    resetMsg.value = e?.response?.data?.detail || '重置失败，请重试'
  } finally {
    resetSubmitting.value = false
  }
}


async function load() {
  loading.value = true
  error.value = ''
  try {
    const pageData = await listStudents({
      keyword: mainFilter.value.keyword || undefined,
      campus:
        mainFilter.value.campus && mainFilter.value.campus !== '__unassigned__'
          ? mainFilter.value.campus
          : undefined,
      campus_unassigned: mainFilter.value.campus === '__unassigned__' || undefined,
      status: statusFilter.value || undefined,
      lesson_balance_min: lessonMin.value ? Number(lessonMin.value) : undefined,
      lesson_balance_max: lessonMax.value ? Number(lessonMax.value) : undefined,
      teacher_id:
        mainFilter.value.teacherId && mainFilter.value.teacherId !== '__unassigned__'
          ? mainFilter.value.teacherId
          : undefined,
      teacher_unassigned: mainFilter.value.teacherId === '__unassigned__' || undefined,
      class_id:
        mainFilter.value.classId && mainFilter.value.classId !== '__unassigned__'
          ? mainFilter.value.classId
          : undefined,
      class_unassigned: mainFilter.value.classId === '__unassigned__' || undefined,
      account: mainFilter.value.account || undefined,
      limit: pageSize,
      offset: (page.value - 1) * pageSize,
    })
    students.value = pageData.items
    total.value = pageData.total
    stats.value = {
      total: pageData.total,
      low: pageData.items.filter((s) => s.low_balance).length,
    }
  } catch {
    error.value = '加载学员列表失败'
  } finally {
    loading.value = false
  }
}

function onSearch() {
  page.value = 1
  load()
}

/** 统一筛选变化（来自复用组件的联动值）：回到第一页并刷新 */
function onMainFilter() {
  page.value = 1
  load()
}

function clearFilters() {
  mainFilter.value = { campus: '', teacherId: '', classId: '', keyword: '', account: '' }
  keyword.value = ''
  campusFilter.value = ''
  accountFilter.value = ''
  statusFilter.value = ''
  lessonMin.value = ''
  lessonMax.value = ''
  classKeyword.value = ''
  classTeacherId.value = ''
  classId.value = ''
  page.value = 1
  load()
}

function onPageChange(p: number) {
  page.value = p
  load()
}

function openCreate() {
  editing.value = null
  form.value = { name: '', phone: '', campus: '', lesson_balance: 0, class_ids: [] }
  resetClassPicker()
  formError.value = ''
  parentUserSearch.value = ''
  studentUserSearch.value = ''
  parentUsernameTouched.value = false
  studentUsernameTouched.value = false
  showCreateParent.value = false
  showCreateStudent.value = false
  showForm.value = true
  loadParentUsers()
  loadStudentUsers()
}

function openEdit(s: StudentOut) {
  editing.value = s
  const manageableIds = new Set(manageableClasses.value.map((c) => c.id))
  form.value = {
    name: s.name,
    phone: s.phone,
    campus: s.campus ?? '',
    lesson_balance: s.lesson_balance,
    // 教师只能看到/调整本人所带班级的归属；其他教师的班级不在其管理范围
    class_ids: s.classes.map((c) => c.id).filter((id) => !isTeacher.value || manageableIds.has(id)),
    parent_user_id: s.parent_user_id,
    student_user_id: s.student_user_id,
  }
  resetClassPicker()
  // 沿用学员校区作为班级选择器的初始校区，便于快速定位同校区班级
  classPickerCampus.value = s.campus ?? ''
  formError.value = ''
  parentUserSearch.value = ''
  studentUserSearch.value = ''
  showForm.value = true
  loadParentUsers()
  loadStudentUsers()
}

function bindParent(userId: string) {
  form.value.parent_user_id = userId
  parentUserSearch.value = ''
}

function unbindParent() {
  form.value.parent_user_id = null
}

function bindStudentUser(userId: string) {
  form.value.student_user_id = userId
  studentUserSearch.value = ''
}

function unbindStudentUser() {
  form.value.student_user_id = null
}

async function submit() {
  formError.value = ''
  if (!form.value.name.trim()) {
    formError.value = '请填写学员姓名'
    return
  }
  try {
    if (editing.value) {
      if (isTeacher.value) {
        // 教师：只需调整学员班级归属（本人所带班级），走教师作用域接口
        await updateStudentClasses(editing.value.id, form.value.class_ids)
      } else {
        await updateStudent(editing.value.id, {
          name: form.value.name,
          phone: form.value.phone || null,
          campus: form.value.campus || null,
          parent_user_id: form.value.parent_user_id,
          student_user_id: form.value.student_user_id,
          class_ids: form.value.class_ids,
        })
      }
    } else {
      await createStudent(form.value)
    }
    showForm.value = false
    await load()
  } catch (e: any) {
    formError.value = e?.response?.data?.detail || '保存失败'
  }
}

function removeStudent(s: StudentOut) {
  askConfirm({
    title: '删除学员',
    message: `确认删除学员「${s.name}」？删除后该学员将从在读列表移除，历史课时、考勤与评估数据会归档保留，可在需要时恢复。`,
    confirmText: '删除',
    danger: true,
    onConfirm: async () => {
      await deleteStudent(s.id)
      await load()
    },
  })
}

function openStop(s: StudentOut) {
  stopStudent.value = s
  stopNote.value = ''
  stopSubmitting.value = false
  showStop.value = true
}

async function submitStop() {
  if (!stopStudent.value) return
  if (!stopNote.value.trim()) {
    formError.value = '停课需填写备注，以便后续教务与学生家长沟通恢复复课'
    return
  }
  stopSubmitting.value = true
  try {
    await updateStudentStatus(stopStudent.value.id, {
      status: 'stopped',
      stop_note: stopNote.value.trim(),
    })
    showStop.value = false
    await load()
  } catch (e: any) {
    formError.value = e?.response?.data?.detail || '停课失败'
  } finally {
    stopSubmitting.value = false
  }
}

function resumeStudent(s: StudentOut) {
  askConfirm({
    title: '恢复在读',
    message: `确认恢复「${s.name}」在读？将同步恢复为待跟进状态。`,
    confirmText: '恢复',
    onConfirm: async () => {
      await updateStudentStatus(s.id, { status: 'active' })
      await load()
    },
  })
}

async function openRecords(s: StudentOut) {
  recordsStudent.value = s
  records.value = await listLessonRecords(s.id)
  showRecords.value = true
}

function openAdjust(s: StudentOut) {
  adjustStudent.value = s
  adjustDelta.value = 0
  adjustRemark.value = ''
  showAdjust.value = true
}

async function submitAdjust() {
  if (!adjustStudent.value || !adjustDelta.value) return
  await adjustLessonBalance(adjustStudent.value.id, adjustDelta.value, adjustRemark.value || null)
  showAdjust.value = false
  await load()
}

const className = (s: StudentOut) => s.classes.map((c) => c.name).join('、') || '—'

function typeLabel(t: string): string {
  const map: Record<string, string> = {
    recharge: '充值',
    consume: '上课',
    adjust: '调整',
    refund: '退费',
  }
  return map[t] || t
}

/** 学员管理主列表的行内账号徽标：直观展示家长/学员账号绑定情况 */
function accountBadges(s: StudentOut): Array<{ label: string; bound: boolean }> {
  return [
    { label: '家长', bound: !!s.parent_user_id },
    { label: '学员', bound: !!s.student_user_id },
  ]
}

/** 缴费名单：未绑定学员账号的学员（课堂作业无法触达，需补建账号） */
const collectionUnboundOnly = ref(false)
const collectionUnbound = computed(() => collectionStudents.value.filter((s) => !s.student_user_id).length)
const filteredCollectionStudents = computed(() =>
  collectionUnboundOnly.value
    ? collectionStudents.value.filter((s) => !s.student_user_id)
    : collectionStudents.value,
)

/** 一键补建学员账号：登录名默认 st+电话，显示名取学员姓名，密码 123456，成功后就地回填绑定 */
const batchCreating = ref(false)
const batchError = ref('')
const batchDone = ref('')

function defaultStudentUsername(s: StudentOut): string {
  const phone = (s.phone || '').trim()
  return phone ? `st${phone}` : ''
}

async function ensureStudentAccount(s: StudentOut): Promise<boolean> {
  if (s.student_user_id) return true
  const username = defaultStudentUsername(s)
  if (!username || username.length < 3) {
    batchError.value = `「${s.name}」没有电话号码，无法按默认规则生成登录名，请先补电话`
    return false
  }
  try {
    const user = await registerApi({ role: 'student', username, password: '123456', name: s.name })
    await updateStudent(s.id, { student_user_id: user.id })
    s.student_user_id = user.id
    return true
  } catch (e: any) {
    batchError.value =
      e?.response?.data?.detail === 'Username already exists'
        ? `「${s.name}」默认登录名 ${username} 已被占用，请手动处理`
        : e?.response?.data?.detail || `「${s.name}」账号创建失败`
    return false
  }
}

async function createMissingAccount(s: StudentOut) {
  batchError.value = ''
  batchDone.value = ''
  const ok = await ensureStudentAccount(s)
  if (ok) batchDone.value = `已为「${s.name}」补建学员账号`
}

/** 缴费名单一键补建：仅处理当前名单中未绑定学员账号的学员 */
async function batchCreateMissingAccounts() {
  batchError.value = ''
  batchDone.value = ''
  const targets = collectionStudents.value.filter((s) => !s.student_user_id)
  if (targets.length === 0) {
    batchDone.value = '当前名单学员均已绑定学员账号'
    return
  }
  batchCreating.value = true
  let okCount = 0
  try {
    for (const s of targets) {
      const ok = await ensureStudentAccount(s)
      if (ok) okCount += 1
      else break
    }
    if (okCount > 0) {
      batchDone.value = `已补建 ${okCount} 个学员账号（登录名 st+电话，密码 123456）`
      await loadCollection()
    }
  } finally {
    batchCreating.value = false
  }
}

function statusInfo(s: StudentOut): { label: string; cls: string } {
  if (s.status === 'stopped') return { label: '已停课', cls: 'stopped' }
  if (s.status === 'archived') return { label: '已归档', cls: 'archived' }
  return { label: '在读', cls: 'active' }
}

function teacherNameById(id: string | null | undefined): string {
  if (!id) return ''
  return teacherOptions.value.find((t) => t.id === id)?.name || ''
}

watch([keyword, campusFilter, statusFilter, lessonMin, lessonMax, classTeacherId, classId], () => {
  page.value = 1
  load()
})

// 级联收敛：切换校区 → 教师/班级失效则清空；切换教师 → 班级失效则清空
watch(campusFilter, () => {
  if (
    classTeacherId.value &&
    classTeacherId.value !== '__unassigned__' &&
    !filteredTeacherOptions.value.some((t) => t.id === classTeacherId.value)
  ) {
    classTeacherId.value = ''
  }
  if (
    classId.value &&
    classId.value !== '__unassigned__' &&
    !classOptions.value.some((c) => c.id === classId.value)
  ) {
    classId.value = ''
  }
})

watch(classTeacherId, () => {
  if (
    classId.value &&
    classId.value !== '__unassigned__' &&
    !classOptions.value.some((c) => c.id === classId.value)
  ) {
    classId.value = ''
  }
})

onMounted(async () => {
  const [clsPage, campuses, teachers] = await Promise.all([
    listClasses({ limit: 500 }),
    listCampusesApi().catch(() => []),
    listTeachersApi({ limit: 500, include_inactive: true }).catch(() => ({ items: [] })),
    loadMyPerms(),
  ])
  classes.value = clsPage.items
  campusOptions.value = campuses
  teacherOptions.value = teachers.items.map((t) => ({ id: t.id, name: t.name, campus: t.campus }))
  await load()
})
</script>

<template>
  <div>
    <PageHead
      :title="viewMode === 'collection' ? '缴费名单' : '学员管理'"
      eyebrow="STUDENTS"
    >
      <template #sub>
        {{
          viewMode === 'collection'
            ? `课时 ≤10 的学员需要缴费 · 共 ${collectionTotal} 名待处理`
            : `${total} 名学员 · 支持校区、课时、状态与班级联动筛选`
        }}
      </template>
      <template #actions>
      <div class="actions">
        <template v-if="viewMode === 'students'">
          <button class="btn ghost" @click="clearFilters">重置筛选</button>
          <button class="btn warn" @click="switchToCollection">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 8v4l3 3M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z" /></svg>
            缴费名单
          </button>
          <button class="btn primary" @click="guard('student_create', openCreate)">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 5v14M5 12h14" /></svg>
            新增学员
          </button>
        </template>
        <template v-else>
          <button class="btn primary" :disabled="batchCreating" title="为当前名单中未绑定学员账号的学员一键补建（登录名 st+电话，密码 123456）" @click="batchCreateMissingAccounts">
            {{ batchCreating ? '补建中…' : '一键补建学员账号' }}
          </button>
          <button class="btn ghost" @click="backToStudents">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 12H5M12 19l-7-7 7-7" /></svg>
            返回学员管理
          </button>
        </template>
      </div>
      </template>
    </PageHead>

    <!-- ========== 缴费名单子页面 ========== -->
    <template v-if="viewMode === 'collection'">
      <section class="stat-row">
        <div class="stat-card">
          <strong>{{ collectionSummary.total }}</strong>
          <span>待缴费名单</span>
        </div>
        <div class="stat-card alert">
          <strong>{{ collectionSummary.urgent }}</strong>
          <span>紧急（≤5 课时且待跟进）</span>
        </div>
        <div class="stat-card ok">
          <strong>{{ collectionSummary.renewed }}</strong>
          <span>本页已续费</span>
        </div>
        <div class="stat-card" :class="{ alert: collectionUnbound > 0 }">
          <strong>{{ collectionUnbound }}</strong>
          <span>未绑定学员账号（课堂作业无法触达）</span>
        </div>
      </section>

      <StudentFilter
        v-model="collectionFilter"
        show-account-filter
        campus-placeholder="全部校区"
        teacher-placeholder="全部教师"
        class-placeholder="全部班级"
        search-placeholder="搜索需要缴费的学员姓名…"
        @update:model-value="(v) => { collectionFilter = v; collectionPage = 1; loadCollection() }"
      >
        <label class="unbound-check">
          <input v-model="collectionUnboundOnly" type="checkbox" @change="collectionPage = 1" />
          <span>只看未绑定学员账号</span>
        </label>
      </StudentFilter>

      <p v-if="batchError" class="error-banner">{{ batchError }}</p>
      <p v-if="batchDone" class="ok-banner">{{ batchDone }}</p>

      <div class="tabs">
        <button
          v-for="t in [
            { v: 'all', l: '全部' },
            { v: 'pending', l: '待跟进' },
            { v: 'renewed', l: '已续费' },
            { v: 'stopped', l: '已停课' },
          ] as const"
          :key="t.v"
          class="tab"
          :class="{ active: collectionFollowUpTab === t.v }"
          @click="collectionFollowUpTab = t.v; collectionPage = 1; loadCollection()"
        >
          {{ t.l }}
        </button>
      </div>

      <p v-if="collectionError" class="error-banner">{{ collectionError }}</p>

      <div class="card-table">
        <table>
          <thead>
            <tr>
              <th>学员</th>
              <th>班级</th>
              <th>剩余课时</th>
              <th>跟进状态</th>
              <th class="ops">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="s in filteredCollectionStudents" :key="s.id" :class="{ urgent: s.lesson_balance <= 5 && s.follow_up_status === 'pending' }">
              <td>
                <div class="cell-user">
                  <div class="cell-avatar low">{{ s.name.slice(0, 1) }}</div>
                  <div>
                    <div class="cell-name">
                      {{ s.name }}
                      <span v-if="!s.student_user_id" class="no-account" title="未绑定学员账号：课堂作业无法触达">无学员账号</span>
                    </div>
                    <div class="cell-sub">{{ s.campus || '未填校区' }} · {{ s.phone || '未留电话' }}</div>
                  </div>
                </div>
              </td>
              <td><span class="tags">{{ className(s) }}</span></td>
              <td><span :class="['balance', { low: s.lesson_balance <= 10 }]">{{ s.lesson_balance }}</span></td>
              <td>
                <span class="follow-pill" :class="s.follow_up_status">{{ followUpLabel[s.follow_up_status] || s.follow_up_status }}</span>
                <div v-if="s.follow_up_note" class="stop-note" :title="s.follow_up_note">备注：{{ s.follow_up_note }}</div>
              </td>
              <td class="ops">
                <button class="op-btn primary" @click="guard('student_refund', () => openRenew(s))">续费</button>
                <button v-if="!s.student_user_id" class="op-btn ok" title="按默认规则补建：登录名 st+电话，密码 123456" @click="createMissingAccount(s)">补建账号</button>
                <button v-if="s.follow_up_status === 'pending'" class="op-btn ok" @click="guard('student_stop', () => markFollowUp(s, 'renewed'))">标已续费</button>
                <button v-if="s.follow_up_status === 'pending'" class="op-btn warn" @click="guard('student_stop', () => markFollowUp(s, 'stopped'))">标已停课</button>
                <button v-if="s.follow_up_status !== 'pending'" class="op-btn" @click="guard('student_stop', () => markFollowUp(s, 'pending'))">恢复待跟进</button>
              </td>
            </tr>
            <tr v-if="!collectionLoading && filteredCollectionStudents.length === 0">
              <td colspan="5" class="empty">暂无需要缴费的学员</td>
            </tr>
          </tbody>
        </table>
      </div>

      <PaginationBar :total="collectionTotal" :page="collectionPage" :page-size="collectionPageSize" @update:page="(p) => { collectionPage = p; loadCollection() }" />

      <!-- 续费弹窗 -->
      <div v-if="showRenew" class="overlay" @click.self="showRenew = false">
        <div class="modal">
          <h2>{{ renewTarget?.name }} · 续费入账</h2>
          <p class="muted">当前余额：{{ renewTarget?.lesson_balance }} 课时</p>
          <div class="mode-tabs">
            <button class="mode-tab" :class="{ active: renewMode === 'package' }" @click="renewMode = 'package'">选课包</button>
            <button class="mode-tab" :class="{ active: renewMode === 'custom' }" @click="renewMode = 'custom'">自定义</button>
          </div>
          <label v-if="renewMode === 'package'">
            课时包
            <select v-model="renewPackageId">
              <option value="">请选择课时包</option>
              <option v-for="p in collectionPackages" :key="p.id" :value="p.id">
                {{ p.name }} · {{ p.total_lessons }} 课时 · ¥{{ Number(p.price).toFixed(2) }}
              </option>
            </select>
          </label>
          <template v-else>
            <div class="row">
              <label>补充课时 *<input v-model.number="renewCustomLessons" type="number" min="1" /></label>
              <label>实收金额（元）<input v-model.number="renewCustomAmount" type="number" min="0" step="0.01" /></label>
            </div>
          </template>
          <label>备注<input v-model="renewNote" type="text" placeholder="如：家长微信转账续费" /></label>
          <p v-if="renewError" class="error">{{ renewError }}</p>
          <div class="modal-actions">
            <button class="btn ghost" @click="showRenew = false">取消</button>
            <button class="btn primary" :disabled="renewSubmitting" @click="submitRenew">
              {{ renewSubmitting ? '入账中…' : '确认续费' }}
            </button>
          </div>
        </div>
      </div>
    </template>

    <!-- ========== 学员管理主页面 ========== -->
    <template v-else>
    <StudentFilter
      v-model="mainFilter"
      show-account-filter
      campus-placeholder="全部校区"
      teacher-placeholder="班级教师"
      class-placeholder="选择班级"
      search-placeholder="班级名称/科目/学员姓名搜索…"
      @update:model-value="(v) => { mainFilter = v; onMainFilter() }"
    >
      <select v-model="statusFilter" class="filter-input" @change="onMainFilter">
        <option value="">全部状态</option>
        <option value="active">在读</option>
        <option value="stopped">已停课</option>
        <option value="archived">已归档</option>
      </select>
      <input v-model="lessonMin" class="filter-input small" type="number" min="0" placeholder="最少课时" @change="onMainFilter" />
      <input v-model="lessonMax" class="filter-input small" type="number" min="0" placeholder="最多课时" @change="onMainFilter" />
    </StudentFilter>

    <p v-if="error" class="error-banner">{{ error }}</p>

    <div class="card-table">
      <table>
        <thead>
          <tr>
            <th>学员</th>
            <th>班级</th>
            <th>课时余额</th>
            <th>状态</th>
            <th class="ops">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="s in students" :key="s.id">
            <td>
              <div class="cell-user">
                <div class="cell-avatar" :class="{ low: s.low_balance, stopped: s.status === 'stopped' }">{{ s.name.slice(0, 1) }}</div>
                <div>
                  <div class="cell-name">
                    {{ s.name }}
                    <span v-if="!s.student_user_id" class="no-account" title="未绑定学员账号：课堂作业无法触达">无学员账号</span>
                  </div>
                  <div class="cell-sub">{{ s.phone || '未留电话' }}</div>
                  <div class="account-badges">
                    <span
                      v-for="b in accountBadges(s)"
                      :key="b.label"
                      class="account-badge"
                      :class="{ bound: b.bound, unbound: !b.bound }"
                      :title="b.bound ? `已绑定${b.label}账号` : `未绑定${b.label}账号`"
                    >
                      {{ b.label }}{{ b.bound ? '✓' : '✕' }}
                    </span>
                  </div>
                </div>
              </div>
            </td>
            <td><span class="tags">{{ className(s) }}</span></td>
            <td>
              <span :class="['balance', { low: s.low_balance }]">{{ s.lesson_balance }}</span>
              <span v-if="s.low_balance && s.status === 'active'" class="low-tag">待续费</span>
            </td>
            <td>
              <span class="status-pill" :class="statusInfo(s).cls">
                {{ statusInfo(s).label }}
              </span>
              <div v-if="s.status === 'stopped' && s.stop_note" class="stop-note" :title="s.stop_note">
                备注：{{ s.stop_note }}
              </div>
            </td>
            <td class="ops">
              <button class="op-btn" @click="guard('student_edit', () => openEdit(s))">编辑</button>
              <button class="op-btn" @click="guard('student_records', () => openRecords(s))">流水</button>
              <button class="op-btn" @click="guard('student_adjust', () => openAdjust(s))">调课时</button>
              <button class="op-btn" @click="guard('student_refund', () => openRefund(s))">退费</button>
              <button v-if="s.status === 'active'" class="op-btn warn" @click="guard('student_stop', () => openStop(s))">停课</button>
              <button v-else-if="s.status === 'stopped'" class="op-btn ok" @click="guard('student_stop', () => resumeStudent(s))">恢复在读</button>
              <button class="op-btn danger" @click="guard('student_delete', () => removeStudent(s))">删除</button>
            </td>
          </tr>
          <tr v-if="!loading && students.length === 0">
            <td colspan="5" class="empty">暂无学员，点击右上角新增</td>
          </tr>
        </tbody>
      </table>
    </div>

    <PaginationBar :total="total" :page="page" :page-size="pageSize" @update:page="onPageChange" />

    <!-- 新建/编辑弹窗 -->
    <div v-if="showForm" class="overlay" @click.self="showForm = false">
      <div class="modal">
        <h2>{{ editing ? '编辑学员' : '新增学员' }}</h2>
        <label>
          姓名 *
          <input v-model="form.name" type="text" />
        </label>
        <label>
          联系电话
          <input v-model="form.phone" type="text" />
        </label>
        <label>
          所属校区
          <input v-model="form.campus" type="text" list="campus-list" placeholder="如：一校 / 二校 / 三校" />
          <datalist id="campus-list">
            <option v-for="c in campusOptions" :key="c" :value="c" />
          </datalist>
        </label>
        <label v-if="!editing">
          初始课时
          <input v-model.number="form.lesson_balance" type="number" min="0" />
        </label>
        <label>
          班级（可搜索）
          <div class="class-picker">
            <div class="class-picker-filters">
              <select v-model="classPickerCampus" class="filter-input" title="按校区筛选班级（仅显示该校区教师所带班级）">
                <option value="">全部校区</option>
                <option v-for="c in campusOptions" :key="c" :value="c">{{ c }}</option>
              </select>
              <select v-model="classPickerTeacherId" class="filter-input" title="选择校区后仅显示该校区教师；选择教师后仅显示其所带班级">
                <option value="">全部带教教师</option>
                <option value="__unassigned__">未分配教师</option>
                <option v-for="t in pickerTeacherOptions" :key="t.id" :value="t.id">
                  {{ t.name }}<template v-if="t.campus">（{{ t.campus }}）</template>
                </option>
              </select>
            </div>
            <input v-model="classSearch" type="text" placeholder="输入班级名称/科目筛选…" />
            <div class="class-options">
              <label v-for="c in filteredClasses" :key="c.id" class="class-option">
                <input v-model="form.class_ids" type="checkbox" :value="c.id" />
                <span>{{ c.name }}（{{ c.subject }}）</span>
                <small v-if="c.teacher_name">{{ c.teacher_name }}</small>
              </label>
              <p v-if="filteredClasses.length === 0" class="no-match">没有匹配的班级</p>
            </div>
            <small>已选 {{ form.class_ids.length }} 个班级 · 点击勾选可多选</small>
          </div>
        </label>

        <!-- 账号绑定（M5 客户端） -->
        <label>
          家长账号（家长可查看课时/反馈/订阅/作业）
          <div class="user-picker">
            <div v-if="form.parent_user_id" class="user-tag">
              <span>{{ parentUserLabel }}</span>
              <template v-if="isAdmin">
                <button v-if="resetTarget?.kind !== 'parent'" class="tag-act" @click="openReset('parent', form.parent_user_id, '家长账号')">重置密码</button>
              </template>
              <button class="unbind" title="解绑账号" @click="unbindParent">✕</button>
            </div>
            <div v-else class="user-search">
              <input v-model="parentUserSearch" type="text" placeholder="搜索家长姓名/账号，或输入新客户姓名…" @input="parentUserKeyword = parentUserSearch; loadParentUsers()" />
              <div v-if="parentUserSearch" class="user-options">
                <button
                  v-for="u in parentUsers.filter(x => x.name.includes(parentUserSearch) || x.username.includes(parentUserSearch))"
                  :key="u.id"
                  class="user-option"
                  @click="bindParent(u.id)"
                >
                  <strong>{{ u.name }}</strong>
                  <small>{{ u.username }}</small>
                </button>
                <div v-if="parentUsers.filter(x => x.name.includes(parentUserSearch) || x.username.includes(parentUserSearch)).length === 0" class="user-empty">
                  <p>未找到已有账号</p>
                </div>
                <div class="user-create">
                  <button v-if="!showCreateParent" class="create-account-btn" type="button" @click="openCreateParentForm">
                    ＋ 没有该账号？新建家长账号（登录名默认学员电话号码，密码 123456）
                  </button>
                  <div v-else class="create-form">
                    <div class="cf-row">
                      <input v-model="createParentUsername" type="text" placeholder="登录名默认=学员电话号码（字母/数字，≥3 位）" @input="onParentUsernameInput" />
                      <span class="cf-note">显示名：{{ parentUserSearch.trim() || '（先输入姓名）' }}</span>
                    </div>
                    <p class="cf-note">密码默认 123456，创建后请及时告知家长</p>
                    <p v-if="createParentError" class="cf-error">{{ createParentError }}</p>
                    <div class="cf-actions">
                      <button class="cf-btn ghost" type="button" @click="showCreateParent = false">取消</button>
                      <button class="cf-btn primary" type="button" :disabled="creatingParent" @click="createParentAccount">
                        {{ creatingParent ? '创建中…' : '创建并绑定' }}
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </label>

        <label>
          学员账号（学员本人登录做题）
          <div class="user-picker">
            <div v-if="form.student_user_id" class="user-tag">
              <span>{{ studentUserLabel }}</span>
              <template v-if="isAdmin">
                <button v-if="resetTarget?.kind !== 'student'" class="tag-act" @click="openReset('student', form.student_user_id, '学员账号')">重置密码</button>
              </template>
              <button class="unbind" title="解绑账号" @click="unbindStudentUser">✕</button>
            </div>
            <div v-else class="user-search">
              <input v-model="studentUserSearch" type="text" placeholder="搜索学员账号，或输入新学员姓名…" @input="studentUserKeyword = studentUserSearch; loadStudentUsers()" />
              <div v-if="studentUserSearch" class="user-options">
                <button
                  v-for="u in studentUsers.filter(x => x.name.includes(studentUserSearch) || x.username.includes(studentUserSearch))"
                  :key="u.id"
                  class="user-option"
                  @click="bindStudentUser(u.id)"
                >
                  <strong>{{ u.name }}</strong>
                  <small>{{ u.username }}</small>
                </button>
                <div v-if="studentUsers.filter(x => x.name.includes(studentUserSearch) || x.username.includes(studentUserSearch)).length === 0" class="user-empty">
                  <p>未找到已有账号</p>
                </div>
                <div class="user-create">
                  <button v-if="!showCreateStudent" class="create-account-btn" type="button" @click="openCreateStudentForm">
                    ＋ 没有该账号？新建学员账号（登录名默认 st+学员电话号码，密码 123456）
                  </button>
                  <div v-else class="create-form">
                    <div class="cf-row">
                      <input v-model="createStudentUsername" type="text" placeholder="登录名默认=st+学员电话号码（字母/数字，≥3 位）" />
                      <span class="cf-note">显示名：{{ studentUserSearch.trim() || '（先输入姓名）' }}</span>
                    </div>
                    <p v-if="createStudentError" class="cf-error">{{ createStudentError }}</p>
                    <div class="cf-actions">
                      <button class="cf-btn ghost" type="button" @click="showCreateStudent = false">取消</button>
                      <button class="cf-btn primary" type="button" :disabled="creatingStudentUser" @click="createStudentAccount">
                        {{ creatingStudentUser ? '创建中…' : '创建并绑定' }}
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </label>
        <p v-if="formError" class="error">{{ formError }}</p>
        <div class="modal-actions">
          <button class="btn ghost" @click="showForm = false">取消</button>
          <button class="btn primary" @click="submit">保存</button>
        </div>
      </div>
    </div>

    <!-- 管理员重置绑定账号密码弹窗 -->
    <div v-if="resetTarget" class="reset-modal" @click.self="resetTarget = null">
      <div class="reset-card">
        <h4>重置{{ resetTarget.label }}密码</h4>
        <p class="rm-sub">重置后请及时告知对方新密码。新客户默认密码为 123456。</p>
        <label>
          新密码
          <input v-model="resetNewPw" type="text" placeholder="新密码（至少 6 位）" />
        </label>
        <p v-if="resetMsg" class="rm-msg" :class="{ ok: resetMsg.includes('✓') }">{{ resetMsg }}</p>
        <div class="rm-actions">
          <button class="btn ghost" type="button" @click="resetTarget = null">取消</button>
          <button class="btn primary" type="button" :disabled="resetSubmitting" @click="confirmReset">
            {{ resetSubmitting ? '提交中…' : '确认重置' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 退费弹窗（FIFO 自动计算） -->
    <div v-if="showRefund" class="overlay" @click.self="showRefund = false">
      <div class="modal wide">
        <h2>{{ refundStudentRef?.name }} · 退费</h2>
        <p class="muted">系统按先进先出（FIFO）自动计算退费明细。</p>
        <div v-if="refundLoading" class="loading-tip">正在计算退费明细…</div>
        <template v-else>
          <div class="refund-summary">
            <span>可退课时：<strong>{{ refundLessons }}</strong></span>
            <span>预计退款：<strong>¥{{ Number(refundTotal).toFixed(2) }}</strong></span>
          </div>
          <table class="mini-table">
            <thead>
              <tr>
                <th>课时包</th>
                <th>已购</th>
                <th>剩余</th>
                <th>单价</th>
                <th>退款</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in refundPreview" :key="item.order_id">
                <td>{{ item.package_name }}</td>
                <td>{{ item.purchased_lessons }}</td>
                <td>{{ item.remaining_lessons }}</td>
                <td>¥{{ Number(item.unit_price).toFixed(2) }}</td>
                <td class="minus">¥{{ Number(item.refund_amount).toFixed(2) }}</td>
              </tr>
              <tr v-if="refundPreview.length === 0"><td colspan="5" class="empty">暂无可退课时</td></tr>
            </tbody>
          </table>
          <label>
            退费备注 *
            <textarea v-model="refundNote" rows="3" placeholder="如：家长申请退费，转校不再上课" />
          </label>
          <p v-if="refundError" class="error">{{ refundError }}</p>
          <div class="modal-actions">
            <button class="btn ghost" @click="showRefund = false">取消</button>
            <button class="btn primary" :disabled="refundSubmitting || refundLoading" @click="submitRefund">
              {{ refundSubmitting ? '退费中…' : '确认退费' }}
            </button>
          </div>
        </template>
      </div>
    </div>

    <!-- 停课弹窗（需备注） -->
    <div v-if="showStop" class="overlay" @click.self="showStop = false">
      <div class="modal">
        <h2>停课 · {{ stopStudent?.name }}</h2>
        <p class="muted">因特殊原因停课的学员，请填写停课备注，便于后续教务与学生家长沟通恢复复课。</p>
        <label>
          停课备注 *
          <textarea
            v-model="stopNote"
            rows="3"
            placeholder="如：家长请假 1 个月，预计 9 月底复课"
          />
        </label>
        <p v-if="formError" class="error">{{ formError }}</p>
        <div class="modal-actions">
          <button class="btn ghost" @click="showStop = false">取消</button>
          <button class="btn primary" :disabled="stopSubmitting" @click="submitStop">
            {{ stopSubmitting ? '提交中…' : '确认停课' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 课时流水抽屉 -->
    <div v-if="showRecords" class="overlay" @click.self="showRecords = false">
      <div class="modal wide">
        <h2>{{ recordsStudent?.name }} · 课时流水</h2>
        <table class="mini-table">
          <thead>
            <tr>
              <th>时间</th>
              <th>类型</th>
              <th>变动</th>
              <th>余额</th>
              <th>备注</th>
              <th>操作人</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in records" :key="r.id">
              <td>{{ new Date(r.created_at).toLocaleString() }}</td>
              <td>
                <span class="type-pill" :class="r.record_type">{{ typeLabel(r.record_type) }}</span>
              </td>
              <td :class="r.delta > 0 ? 'plus' : 'minus'">{{ r.delta > 0 ? '+' : '' }}{{ r.delta }}</td>
              <td>{{ r.balance_after }}</td>
              <td>{{ r.remark || '—' }}</td>
              <td>{{ r.operator_name || '—' }}</td>
            </tr>
            <tr v-if="records.length === 0"><td colspan="6" class="empty">暂无流水</td></tr>
          </tbody>
        </table>
        <div class="modal-actions">
          <button class="btn ghost" @click="showRecords = false">关闭</button>
        </div>
      </div>
    </div>

    <!-- 课时调整弹窗 -->
    <div v-if="showAdjust" class="overlay" @click.self="showAdjust = false">
      <div class="modal">
        <h2>{{ adjustStudent?.name }} · 调整课时</h2>
        <p class="muted">当前余额：{{ adjustStudent?.lesson_balance }} 课时</p>
        <label>
          变动数量
          <input v-model.number="adjustDelta" type="number" placeholder="正数入账 / 负数扣减" />
        </label>
        <label>
          备注
          <input v-model="adjustRemark" type="text" placeholder="如：充值 40 课时" />
        </label>
        <div class="modal-actions">
          <button class="btn ghost" @click="showAdjust = false">取消</button>
          <button class="btn primary" :disabled="!adjustDelta" @click="submitAdjust">确认调整</button>
        </div>
      </div>
    </div>

    <!-- 统一确认弹窗（删除/恢复等） -->
    <ConfirmDialog
      :visible="confirmState.visible"
      :title="confirmState.title"
      :message="confirmState.message"
      :confirm-text="confirmState.confirmText"
      :danger="confirmState.danger"
      @confirm="runConfirm"
      @cancel="confirmState.visible = false"
    />
    <!-- 无权限提示 -->
    <ConfirmDialog
      :visible="showNoPerm"
      title="暂无操作权限"
      :message="noPermText"
      confirm-text="知道了"
      @confirm="showNoPerm = false"
      @cancel="showNoPerm = false"
    />
    </template>
  </div>
</template>

<style scoped>
.page-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 20px;
}
h1 {
  font-size: 22px;
}
.page-sub {
  color: var(--ink-3);
  font-size: 13px;
  margin-top: 4px;
}
.actions {
  display: flex;
  gap: 10px;
}
.search-box {
  display: flex;
  align-items: center;
  gap: 8px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 0 12px;
  min-width: 220px;
  transition: all 0.15s;
}
.search-box:focus-within {
  border-color: var(--brand);
  box-shadow: 0 0 0 3px var(--brand-soft);
}
.search-box svg {
  width: 15px;
  height: 15px;
  color: var(--ink-3);
}
.search-box input {
  border: none;
  outline: none;
  padding: 9px 0;
  font-size: 14px;
  width: 100%;
  background: transparent;
}

.filter-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  padding: 14px 16px;
  margin-bottom: 14px;
  border: 1px solid var(--line);
  border-radius: 16px;
  background: var(--surface);
}

.filter-input {
  padding: 8px 10px;
  border-radius: 10px;
  border: 1px solid var(--line);
  background: var(--surface);
  font-size: 13px;
  color: var(--ink);
  min-width: 150px;
}

.filter-input.small {
  min-width: 120px;
  width: 120px;
}

.filter-input.grow {
  flex: 1;
  min-width: 200px;
}

.filter-input:focus {
  outline: none;
  border-color: var(--brand);
  box-shadow: 0 0 0 3px var(--brand-soft);
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
  box-shadow: 0 10px 22px rgba(99, 102, 241, 0.4);
}
.btn.ghost {
  background: var(--surface);
  color: var(--ink-2);
  border: 1px solid var(--line);
}
.btn.ghost:hover {
  border-color: var(--brand);
  color: var(--brand);
}

.error-banner {
  background: var(--danger-soft);
  color: var(--danger);
  padding: 10px 14px;
  border-radius: 10px;
  margin-bottom: 16px;
  font-size: 13px;
}
.ok-banner {
  background: var(--success-soft);
  color: #047857;
  padding: 10px 14px;
  border-radius: 10px;
  margin-bottom: 16px;
  font-size: 13px;
}

/* —— 账号绑定徽标 —— */
.account-badges {
  display: flex;
  gap: 6px;
  margin-top: 4px;
}
.account-badge {
  font-size: 11px;
  font-weight: 600;
  padding: 1px 8px;
  border-radius: 999px;
  border: 1px solid var(--line);
}
.account-badge.bound {
  background: var(--success-soft);
  border-color: #a7f3d0;
  color: #047857;
}
.account-badge.unbound {
  background: var(--danger-soft);
  border-color: #fecaca;
  color: var(--danger);
}
.no-account {
  display: inline-block;
  font-size: 11px;
  font-weight: 700;
  padding: 1px 8px;
  border-radius: 999px;
  background: #fef3c7;
  color: #b45309;
  margin-left: 6px;
  vertical-align: 1px;
}
.unbound-check {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--ink-2);
  white-space: nowrap;
}
.unbound-check input {
  width: 15px;
  height: 15px;
  accent-color: #6366f1;
}

/* —— 缴费名单子页面 —— */
.btn.warn {
  background: linear-gradient(135deg, #f59e0b, #ef4444);
  color: #fff;
  box-shadow: 0 6px 16px rgba(245, 158, 11, 0.3);
}
.btn.warn:hover {
  transform: translateY(-1px);
  box-shadow: 0 10px 22px rgba(245, 158, 11, 0.4);
}
.stat-row {
  display: flex;
  gap: 12px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}
.stat-card {
  flex: 1;
  min-width: 160px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 14px 18px;
  border-radius: 14px;
  background: var(--surface);
  border: 1px solid var(--line);
  box-shadow: var(--shadow-sm);
}
.stat-card strong {
  font-size: 22px;
  font-weight: 800;
  color: var(--ink);
}
.stat-card span {
  font-size: 12px;
  color: var(--ink-3);
}
.stat-card.alert {
  border-color: #fecaca;
  background: #fef2f2;
}
.stat-card.alert strong {
  color: var(--danger);
}
.stat-card.ok {
  border-color: #a7f3d0;
  background: #ecfdf5;
}
.stat-card.ok strong {
  color: #047857;
}
.tabs {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}
.tab {
  padding: 7px 16px;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--ink-2);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}
.tab:hover {
  border-color: var(--brand);
  color: var(--brand-strong);
}
.tab.active {
  background: var(--brand-soft);
  border-color: #c7d2fe;
  color: var(--brand-strong);
}
tr.urgent td:first-child {
  box-shadow: inset 3px 0 0 var(--danger);
}
.follow-pill {
  display: inline-block;
  padding: 3px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
}
.follow-pill.pending {
  background: var(--warning-soft);
  color: #b45309;
}
.follow-pill.renewed {
  background: var(--success-soft);
  color: #047857;
}
.follow-pill.stopped {
  background: var(--line);
  color: var(--ink-3);
}
.op-btn.primary {
  border-color: transparent;
  background: linear-gradient(135deg, #6366f1, #06b6d4);
  color: #fff;
}
.op-btn.primary:hover {
  filter: brightness(1.05);
  color: #fff;
}
.op-btn.ok {
  color: #047857;
}
.op-btn.ok:hover {
  border-color: #047857;
  background: var(--success-soft);
}
.mode-tabs {
  display: flex;
  gap: 8px;
  background: #f1f5f9;
  border-radius: 10px;
  padding: 4px;
  margin-bottom: 16px;
}
.mode-tab {
  flex: 1;
  border: none;
  background: transparent;
  padding: 8px 0;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  color: var(--ink-3);
  cursor: pointer;
  transition: all 0.15s;
}
.mode-tab.active {
  background: var(--surface);
  color: var(--brand-strong);
  box-shadow: var(--shadow-sm);
}
.row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

/* 卡片式表格 */
.card-table {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 16px;
  overflow: hidden;
  box-shadow: var(--shadow-sm);
}
.card-table table {
  width: 100%;
  border-collapse: collapse;
}
.card-table th,
.card-table td {
  padding: 13px 18px;
  text-align: left;
  font-size: 14px;
  border-bottom: 1px solid var(--line);
}
.card-table th {
  background: #f9fafb;
  color: var(--ink-3);
  font-weight: 600;
  font-size: 12.5px;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}
.card-table tr:last-child td {
  border-bottom: none;
}
.card-table tbody tr {
  transition: background 0.12s;
}
.card-table tbody tr:hover {
  background: #f8fafc;
}

.cell-user {
  display: flex;
  align-items: center;
  gap: 11px;
}
.cell-avatar {
  width: 38px;
  height: 38px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 11px;
  font-weight: 700;
  color: #fff;
  background: linear-gradient(135deg, #6366f1, #06b6d4);
}
.cell-avatar.low {
  background: linear-gradient(135deg, #f97316, #ef4444);
}
.cell-avatar.stopped {
  background: linear-gradient(135deg, #94a3b8, #64748b);
}
.cell-name {
  font-weight: 600;
  color: var(--ink);
}
.cell-sub {
  color: var(--ink-3);
  font-size: 12px;
  margin-top: 1px;
}
.tags {
  color: var(--ink-2);
}

.balance {
  font-weight: 700;
  font-size: 16px;
  color: var(--ink);
}
.balance.low {
  color: var(--danger);
}
.low-tag {
  margin-left: 7px;
  background: var(--danger-soft);
  color: var(--danger);
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 999px;
}
.status-pill {
  font-size: 12px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 999px;
}
.status-pill.active {
  background: var(--success-soft);
  color: var(--success);
}
.status-pill.stopped {
  background: #f1f5f9;
  color: var(--ink-3);
}
.status-pill.archived {
  background: var(--danger-soft);
  color: var(--danger);
}
.stop-note {
  margin-top: 4px;
  font-size: 11.5px;
  color: var(--ink-3);
  max-width: 220px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.ops {
  white-space: nowrap;
}
.op-btn {
  border: none;
  background: none;
  color: var(--brand);
  cursor: pointer;
  font-size: 13px;
  font-weight: 500;
  margin-right: 10px;
  padding: 0;
}
.op-btn:hover {
  text-decoration: underline;
}
.op-btn.warn {
  color: var(--warning);
}
.op-btn.ok {
  color: var(--success);
}
.op-btn.danger {
  color: var(--danger);
}
.empty {
  text-align: center;
  color: var(--ink-3);
  padding: 36px 0;
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
  z-index: 50;
}
.modal {
  width: 440px;
  background: var(--surface);
  border-radius: 16px;
  padding: 26px;
  box-shadow: var(--shadow-lg);
  max-height: 82vh;
  overflow: auto;
}
.modal.wide {
  width: 720px;
}
.modal h2 {
  font-size: 18px;
  margin-bottom: 18px;
}
.modal label {
  display: block;
  margin-bottom: 14px;
  font-size: 13px;
  color: var(--ink-2);
  font-weight: 500;
}
.modal input,
.modal select,
.modal textarea {
  display: block;
  width: 100%;
  margin-top: 6px;
  padding: 9px 11px;
  border: 1px solid var(--line);
  border-radius: 10px;
  box-sizing: border-box;
  font-size: 14px;
  transition: all 0.15s;
}
.modal input:focus,
.modal select:focus,
.modal textarea:focus {
  outline: none;
  border-color: var(--brand);
  box-shadow: 0 0 0 3px var(--brand-soft);
}
.modal small {
  color: var(--ink-3);
}
.muted {
  color: var(--ink-3);
  font-size: 13px;
  margin-bottom: 12px;
}
.error {
  color: var(--danger);
  font-size: 13px;
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 20px;
}

/* 班级搜索多选 */
.class-picker {
  margin-top: 6px;
}
.class-picker-filters {
  display: flex;
  gap: 8px;
  margin-bottom: 8px;
}
.class-picker-filters .filter-input {
  flex: 1;
  min-width: 0;
  margin-top: 0;
  padding: 8px 10px;
  border: 1px solid var(--line);
  border-radius: 9px;
  font-size: 13px;
  background: var(--surface);
}
.class-picker > input {
  margin-top: 0;
}
.class-options {
  border: 1px solid var(--line);
  border-radius: 10px;
  max-height: 180px;
  overflow: auto;
  margin: 8px 0;
  padding: 4px;
  background: var(--surface);
}
.class-option {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 10px;
  margin: 0;
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px;
  color: var(--ink);
}
.class-option:hover {
  background: #f8fafc;
}
.class-option input[type='checkbox'] {
  width: 15px;
  height: 15px;
  margin: 0;
}
.class-option small {
  margin-left: auto;
  color: var(--ink-3);
}
.no-match {
  padding: 12px;
  text-align: center;
  color: var(--ink-3);
  font-size: 13px;
}

/* 账号绑定搜索 */
.user-picker {
  margin-top: 6px;
}
.user-picker > input {
  margin-top: 0;
}
.user-tag {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 8px 12px;
  border-radius: 10px;
  background: var(--brand-soft);
  color: var(--brand-strong);
  font-size: 13px;
  font-weight: 600;
}
.user-tag .unbind {
  border: none;
  background: rgba(255, 255, 255, 0.7);
  color: var(--ink-3);
  width: 20px;
  height: 20px;
  border-radius: 50%;
  cursor: pointer;
  font-size: 11px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.user-search {
  position: relative;
}
.user-options {
  position: absolute;
  z-index: 20;
  left: 0;
  right: 0;
  top: calc(100% + 4px);
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 10px;
  box-shadow: var(--shadow-md);
  max-height: 180px;
  overflow: auto;
  padding: 4px;
}
.user-option {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 1px;
  width: 100%;
  padding: 7px 10px;
  border: none;
  background: transparent;
  border-radius: 8px;
  cursor: pointer;
  text-align: left;
}
.user-option:hover {
  background: var(--brand-soft);
}
.user-option strong {
  font-size: 13px;
  color: var(--ink);
}
.user-option small {
  color: var(--ink-3);
}

.mini-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.mini-table th,
.mini-table td {
  padding: 9px 10px;
  text-align: left;
  border-bottom: 1px solid var(--line);
}
.mini-table th {
  color: var(--ink-3);
  font-weight: 600;
  background: #f9fafb;
}
.type-pill {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 999px;
}
.type-pill.recharge {
  background: var(--success-soft);
  color: var(--success);
}
.type-pill.consume {
  background: var(--brand-soft);
  color: var(--brand-strong);
}
.type-pill.adjust {
  background: var(--warning-soft);
  color: #b45309;
}
.refund-summary {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 12px;
  padding: 10px 12px;
  border-radius: 10px;
  background: var(--brand-soft);
  color: var(--brand-strong);
  font-size: 13px;
}
.plus {
  color: var(--success);
  font-weight: 700;
}
.minus {
  color: var(--danger);
  font-weight: 700;
}

/* —— 账号：新建/重置 —— */
.user-tag {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.user-tag > span {
  font-weight: 600;
}
.tag-act {
  border: 1px solid var(--brand);
  background: var(--brand-soft);
  color: var(--brand-strong);
  border-radius: 999px;
  padding: 2px 9px;
  font-size: 11.5px;
  cursor: pointer;
}
.tag-act:hover {
  background: var(--brand);
  color: #fff;
}
.user-empty {
  text-align: center;
  color: var(--ink-3);
  font-size: 12.5px;
  padding: 8px 0 2px;
}
.user-create {
  border-top: 1px dashed var(--line);
  margin-top: 6px;
  padding-top: 6px;
}
.create-account-btn {
  width: 100%;
  border: none;
  background: var(--brand-soft);
  color: var(--brand-strong);
  font-size: 12.5px;
  font-weight: 600;
  padding: 8px 10px;
  border-radius: 8px;
  cursor: pointer;
  text-align: center;
}
.create-account-btn:hover {
  background: var(--brand);
  color: #fff;
}
.create-form {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.cf-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.cf-row input {
  flex: 1;
  min-width: 180px;
  margin-top: 0;
}
.cf-note {
  font-size: 11.5px;
  color: var(--ink-3);
}
.cf-error {
  color: var(--danger);
  font-size: 12px;
  margin: 0;
}
.cf-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
.cf-btn {
  padding: 6px 14px;
  border-radius: 8px;
  border: none;
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
}
.cf-btn.ghost {
  background: var(--surface);
  border: 1px solid var(--line);
  color: var(--ink-2);
}
.cf-btn.primary {
  background: linear-gradient(135deg, #6366f1, #06b6d4);
  color: #fff;
}
.cf-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.reset-modal {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 90;
}
.reset-card {
  width: 360px;
  max-width: calc(100vw - 40px);
  background: var(--surface);
  border-radius: 16px;
  padding: 22px;
  box-shadow: var(--shadow-lg);
}
.reset-card h4 {
  font-size: 15.5px;
  margin-bottom: 6px;
}
.reset-card label {
  display: block;
  font-size: 13px;
  font-weight: 500;
  color: var(--ink-2);
  margin-bottom: 10px;
}
.reset-card input {
  display: block;
  width: 100%;
  box-sizing: border-box;
  margin-top: 6px;
  padding: 8px 10px;
  border: 1px solid var(--line);
  border-radius: 9px;
  font-size: 13.5px;
  background: var(--surface);
}
.reset-card input:focus {
  outline: none;
  border-color: var(--brand);
  box-shadow: 0 0 0 3px var(--brand-soft);
}
.rm-sub {
  font-size: 12.5px;
  color: var(--ink-3);
  margin-bottom: 12px;
  line-height: 1.6;
}
.rm-msg {
  font-size: 12.5px;
  color: var(--danger);
  margin: 8px 0 0;
}
.rm-msg.ok {
  color: var(--success);
}
.rm-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 14px;
}
</style>
