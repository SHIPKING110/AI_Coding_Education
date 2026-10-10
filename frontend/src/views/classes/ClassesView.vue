<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import PageHead from '@/components/PageHead.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import PaginationBar from '@/components/PaginationBar.vue'
import SearchableSelect from '@/components/SearchableSelect.vue'
import { myPermissions } from '@/api/permissions'
import {
  createClass,
  deleteClass,
  getClass,
  listClasses,
  updateClass,
  updateStudentClasses,
  type ClassCreate,
  type ClassDetailOut,
  type ClassOut,
} from '@/api/enrollment'
import { listCampusesApi, listTeachersApi, type UserOut } from '@/api/auth'
import { listSubjects } from '@/api/business'
import { useAuthStore } from '@/stores/auth'
import { fmtCnDateKey } from '@/utils/date'

const auth = useAuthStore()
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
function guard(key: string, action: () => void) {
  if (can(key)) action()
  else showNoPerm.value = true
}

const classes = ref<ClassOut[]>([])
const keyword = ref('')
const campusFilter = ref('')
const subjectFilter = ref('')
const subjectOptions = ref<string[]>([])
const startFrom = ref('')
const startTo = ref('')
const loading = ref(false)
const error = ref('')

// 查看班级详情
const showDetail = ref(false)
const detailLoading = ref(false)
const detail = ref<ClassDetailOut | null>(null)

const showForm = ref(false)
const editing = ref<ClassOut | null>(null)
const form = ref<ClassCreate>({ name: '', subject: '', teacher_id: null, start_date: null })
const formError = ref('')
// 详情内操作（退班）的失败提示：直接展示在详情弹窗内，避免静默无反应
const actionError = ref('')

// —— 列表页按带教教师筛选：可搜索下拉（教师多时快速定位） ——
const teacherOptions = ref<UserOut[]>([]) // 全部在职教师
const teacherIdFilter = ref('')
const teacherFilterOptions = computed(() => {
  // 联动：选择校区后仅展示该校区教师；「未分配教师」入口始终保留
  const opts = teacherOptions.value
    .filter((t) => {
      if (!campusFilter.value || campusFilter.value === '__unassigned__') return true
      return t.campus === campusFilter.value
    })
    .map((t) => ({ id: t.id, label: `${t.name}${t.campus ? `（${t.campus}）` : ''}` }))
  return [{ id: '__unassigned__', label: '未分配教师' }, ...opts]
})

// —— 带教教师选择（弹窗内）：校区筛选 + 关键字搜索 ——
const campuses = ref<string[]>([])
const allTeachers = ref<UserOut[]>([]) // 全量在职教师（含当前已选，即便被筛选过滤也保留显示）
const teacherKeyword = ref('')
const teacherCampus = ref('')

/** 根据 校区筛选 + 关键字 过滤教师，并始终保留当前已选教师（防重名/已选被过滤掉）。 */
const filteredTeachers = () => {
  const kw = teacherKeyword.value.trim().toLowerCase()
  return allTeachers.value.filter((t) => {
    if (t.id === form.value.teacher_id) return true // 已选教师始终保留
    if (teacherCampus.value && t.campus !== teacherCampus.value) return false
    if (!kw) return true
    return (
      t.name.toLowerCase().includes(kw) ||
      t.username.toLowerCase().includes(kw) ||
      (t.campus || '').toLowerCase().includes(kw)
    )
  })
}

/** 按当前筛选条件从后端加载教师（后端 keyword/campus 过滤，避免全量拉取）。 */
async function loadTeachers() {
  allTeachers.value = (
    await listTeachersApi({
      keyword: teacherKeyword.value.trim() || undefined,
      campus: teacherCampus.value || undefined,
      limit: 500,
    })
  ).items
  // 若当前已选教师不在结果中（例如筛选后隐藏），主动补回，保证显示正确
  if (form.value.teacher_id) {
    const selected = allTeachers.value.find((t) => t.id === form.value.teacher_id)
    if (!selected) {
      try {
        const sel = (await listTeachersApi({ limit: 500 })).items.find(
          (t) => t.id === form.value.teacher_id,
        )
        if (sel) allTeachers.value.push(sel)
      } catch {
        /* 忽略：仅影响下拉回显 */
      }
    }
  }
}

// 分页
const page = ref(1)
const pageSize = 12
const total = ref(0)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const pageData = await listClasses({
      keyword: keyword.value.trim() || undefined,
      teacher_id:
        teacherIdFilter.value && teacherIdFilter.value !== '__unassigned__'
          ? teacherIdFilter.value
          : undefined,
      teacher_unassigned: teacherIdFilter.value === '__unassigned__' || undefined,
      campus:
        campusFilter.value && campusFilter.value !== '__unassigned__'
          ? campusFilter.value
          : undefined,
      campus_unassigned: campusFilter.value === '__unassigned__' || undefined,
      subject: subjectFilter.value || undefined,
      start_date_from: startFrom.value || undefined,
      start_date_to: startTo.value || undefined,
      limit: pageSize,
      offset: (page.value - 1) * pageSize,
    })
    classes.value = pageData.items
    total.value = pageData.total
  } catch {
    error.value = '加载班级列表失败'
  } finally {
    loading.value = false
  }
}

function onSearch() {
  page.value = 1
  load()
}

function onFilterChange() {
  page.value = 1
  load()
}

let filterTimer: ReturnType<typeof setTimeout> | null = null

/** 关键词搜索防抖：输入 300ms 无新输入后才触发筛选，避免逐字闪烁 */
function onFilterInput() {
  if (filterTimer) clearTimeout(filterTimer)
  filterTimer = setTimeout(() => {
    filterTimer = null
    onFilterChange()
  }, 300)
}

function clearFilters() {
  keyword.value = ''
  campusFilter.value = ''
  teacherIdFilter.value = ''
  subjectFilter.value = ''
  startFrom.value = ''
  startTo.value = ''
  page.value = 1
  load()
}

function onPageChange(p: number) {
  page.value = p
  load()
}

async function openDetail(c: ClassOut) {
  detail.value = null
  showDetail.value = true
  detailLoading.value = true
  try {
    detail.value = await getClass(c.id)
  } catch {
    error.value = '加载班级详情失败'
  } finally {
    detailLoading.value = false
  }
}

function fmtDate(iso: string | null): string {
  return fmtCnDateKey(iso)
}

function statusLabel(s: string): string {
  if (s === 'stopped') return '已停课'
  if (s === 'archived') return '已归档'
  return '在读'
}

function openCreate() {
  editing.value = null
  form.value = { name: '', subject: '', teacher_id: null, start_date: null }
  formError.value = ''
  // 教师新建班级：带教教师固定为自己（后端同样强制）
  if (auth.user?.role === 'teacher') form.value.teacher_id = auth.user.id
  // 重置教师筛选条件，重新加载全部在职教师
  teacherKeyword.value = ''
  teacherCampus.value = ''
  loadTeachers()
  showForm.value = true
}

function openEdit(c: ClassOut) {
  editing.value = c
  form.value = {
    name: c.name,
    subject: c.subject,
    teacher_id: c.teacher_id,
    start_date: c.start_date,
  }
  formError.value = ''
  teacherKeyword.value = ''
  teacherCampus.value = ''
  loadTeachers()
  showForm.value = true
}

async function submit() {
  formError.value = ''
  if (!form.value.name.trim() || !form.value.subject.trim()) {
    formError.value = '请填写班级名称与科目'
    return
  }
  try {
    if (editing.value) {
      await updateClass(editing.value.id, form.value)
    } else {
      await createClass(form.value)
    }
    showForm.value = false
    await load()
  } catch (e: any) {
    formError.value = e?.response?.data?.detail || '保存失败'
  }
}

async function remove(c: ClassOut) {
  askConfirm({
    title: '删除班级',
    message: `确认删除班级「${c.name}」？删除后该班级将从列表移除，名下学员的归属、历史排课与考勤记录会归档保留。`,
    confirmText: '删除',
    danger: true,
    onConfirm: async () => {
      await deleteClass(c.id)
      await load()
    },
  })
}

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

/** 学员退班：将学员从当前班级移出（保留其在其他班级的归属；退到无班级则为「未分班」） */
function unenroll(studentId: string, studentName: string) {
  const target = detail.value
  if (!target) return
  // 详情已自带每位学员的全部班级归属，直接计算剩余班级，无需再查一次学员详情
  const row = target.students.find((s) => s.id === studentId)
  const remaining = (row?.classes ?? []).map((c) => c.id).filter((id) => id !== target.id)
  askConfirm({
    title: '学员退班',
    message: `确认让「${studentName}」退出「${target.name}」？退班仅移除该班级归属，学员的课时余额与历史记录不受影响；可稍后在「学员管理 → 编辑」中转入其他班级。`,
    confirmText: '确认退班',
    danger: true,
    onConfirm: async () => {
      actionError.value = ''
      try {
        await updateStudentClasses(studentId, remaining)
        detail.value = await getClass(target.id)
        await load()
      } catch (e: unknown) {
        const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        actionError.value = typeof msg === 'string' && msg ? `退班失败：${msg}` : '退班失败，请稍后重试'
      }
    },
  })
}

/** 学员调班：从当前班级直接转入另一班级（保留其他班级归属） */
const showTransfer = ref(false)
const transferTarget = ref<{ id: string; name: string } | null>(null)
const transferClassId = ref('')
const transferSubmitting = ref(false)
const transferOptions = computed(() => (classes.value || []).filter((c) => c.id !== detail.value?.id))

function openTransfer(studentId: string, studentName: string) {
  transferTarget.value = { id: studentId, name: studentName }
  transferClassId.value = ''
  showTransfer.value = true
}

async function confirmTransfer() {
  const target = detail.value
  if (!target || !transferTarget.value || !transferClassId.value) return
  transferSubmitting.value = true
  actionError.value = ''
  try {
    const row = target.students.find((s) => s.id === transferTarget.value!.id)
    const remaining = (row?.classes ?? []).map((c) => c.id).filter((id) => id !== target.id)
    if (!remaining.includes(transferClassId.value)) remaining.push(transferClassId.value)
    await updateStudentClasses(transferTarget.value.id, remaining)
    showTransfer.value = false
    detail.value = await getClass(target.id)
    await load()
  } catch (e: unknown) {
    const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    actionError.value = typeof msg === 'string' && msg ? `调班失败：${msg}` : '调班失败，请稍后重试'
  } finally {
    transferSubmitting.value = false
  }
}

onMounted(async () => {
  try {
    campuses.value = await listCampusesApi()
  } catch {
    campuses.value = []
  }
  try {
    subjectOptions.value = (await listSubjects()).map((s: any) => s.name)
  } catch {
    subjectOptions.value = []
  }
  try {
    teacherOptions.value = (await listTeachersApi({ limit: 500 })).items
  } catch {
    teacherOptions.value = []
  }
  await loadMyPerms()
  await load()
})
</script>

<template>
  <div>
    <PageHead
      title="班级管理"
      eyebrow="CLASSES"
      :sub="`${total} 个班级 · 每个班级绑定科目与带教教师`"
    >
      <template #actions>
      <button class="btn primary" @click="guard('class_create', openCreate)">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 5v14M5 12h14" /></svg>
        新建班级
      </button>
      </template>
    </PageHead>

    <div class="toolbar">
      <div class="search-box">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21 21l-4.35-4.35M17 10.5a6.5 6.5 0 1 1-13 0 6.5 6.5 0 0 1 13 0z" />
        </svg>
        <input v-model="keyword" placeholder="搜索班级名称 / 科目 / 教师" @keyup.enter="onSearch" @input="onFilterInput" />
      </div>
      <select v-model="campusFilter" class="filter-select" title="按校区筛选（班级按带教教师所属校区归口）" @change="onFilterChange">
        <option value="">全部校区</option>
        <option value="__unassigned__">未分配（无教师或教师未填校区）</option>
        <option v-for="c in campuses" :key="c" :value="c">{{ c }}</option>
      </select>
      <SearchableSelect
        v-model="teacherIdFilter"
        class="teacher-select"
        :options="teacherFilterOptions"
        placeholder="全部教师（可搜索）"
        group="class-teacher-filter"
        @update:model-value="onFilterChange"
      />
      <select v-model="subjectFilter" class="filter-select" title="按科目筛选班级" @change="onFilterChange">
        <option value="">全部科目</option>
        <option v-for="s in subjectOptions" :key="s" :value="s">{{ s }}</option>
      </select>
      <label class="date-range">
        <span>开班</span>
        <input v-model="startFrom" type="date" @change="onFilterChange" />
        <i>至</i>
        <input v-model="startTo" type="date" @change="onFilterChange" />
      </label>
      <button
        v-if="keyword || campusFilter || teacherIdFilter || subjectFilter || startFrom || startTo"
        class="btn ghost"
        @click="clearFilters"
      >
        重置筛选
      </button>
    </div>

    <p v-if="error" class="error-banner">{{ error }}</p>

    <div class="card-grid">
      <div v-for="c in classes" :key="c.id" class="class-card">
        <div class="card-top">
          <div class="subject-badge">{{ c.subject.slice(0, 2) }}</div>
          <span class="status-pill active">进行中</span>
        </div>
        <h3 class="card-name">{{ c.name }}</h3>
        <p class="card-meta">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75" /></svg>
          {{ c.teacher_name || '未分配教师' }}
        </p>
        <div class="card-foot">
          <span class="count"><strong>{{ c.student_count }}</strong> 名学员</span>
          <span class="date">{{ c.start_date ? fmtDate(c.start_date) + ' 开班' : '未设开班' }}</span>
        </div>
        <div class="card-ops">
          <button class="op-btn" @click="guard('class_view', () => openDetail(c))">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z" /></svg>
            查看
          </button>
          <button class="op-btn" @click="guard('class_edit', () => openEdit(c))">编辑</button>
          <button class="op-btn danger" @click="guard('class_delete', () => remove(c))">删除</button>
        </div>
      </div>
      <div v-if="!loading && classes.length === 0" class="empty-card">没有符合条件的班级，试试调整筛选条件</div>
    </div>

    <PaginationBar :total="total" :page="page" :page-size="pageSize" @update:page="onPageChange" />

    <div v-if="showForm" class="overlay" @click.self="showForm = false">
      <div class="modal">
        <h2>{{ editing ? '编辑班级' : '新建班级' }}</h2>
        <label>
          班级名称 *
          <input v-model="form.name" type="text" />
        </label>
        <label>
          科目 *
          <input v-model="form.subject" type="text" placeholder="如：Python / C++ / Scratch" />
        </label>
        <div v-if="auth.user?.role !== 'teacher'" class="teacher-picker">
          <div class="picker-head">
            <span>带教教师</span>
            <button v-if="form.teacher_id" type="button" class="clear-teacher" @click="form.teacher_id = null">
              清除选择
            </button>
          </div>
          <div class="picker-search">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 21l-4.35-4.35M17 10.5a6.5 6.5 0 1 1-13 0 6.5 6.5 0 0 1 13 0z" /></svg>
            <input v-model="teacherKeyword" placeholder="搜索教师姓名 / 登录名 / 校区" @input="loadTeachers" />
          </div>
          <div class="picker-campus-row">
            <select v-model="teacherCampus" class="mini-campus" @change="loadTeachers">
              <option value="">全部校区</option>
              <option v-for="c in campuses" :key="c" :value="c">{{ c }}</option>
            </select>
            <button
              v-if="teacherKeyword || teacherCampus"
              type="button"
              class="clear-filter"
              title="清空筛选"
              @click="teacherKeyword = ''; teacherCampus = ''; loadTeachers()"
            >×</button>
          </div>
          <div class="teacher-list">
            <label
              v-for="t in filteredTeachers()"
              :key="t.id"
              class="teacher-option"
              :class="{ checked: form.teacher_id === t.id }"
            >
              <input
                type="radio"
                :value="t.id"
                v-model="form.teacher_id"
                :checked="form.teacher_id === t.id"
                class="teacher-radio"
              />
              <div class="teacher-body">
                <span class="teacher-name">{{ t.name }}</span>
                <span class="teacher-meta">
                  <span v-if="t.campus" class="campus-tag">{{ t.campus }}</span>
                  <span class="username-tag">{{ t.username }}</span>
                </span>
              </div>
              <span class="check-mark" aria-hidden="true">✓</span>
            </label>
            <div v-if="filteredTeachers().length === 0" class="teacher-empty">无匹配教师，可调整关键词或校区</div>
          </div>
          <p class="picker-tip">教师同名时以校区与登录名区分，可输入关键词精确定位</p>
        </div>
        <label>
          开班日期
          <input v-model="form.start_date" type="date" />
        </label>
        <p v-if="formError" class="error">{{ formError }}</p>
        <div class="modal-actions">
          <button class="btn ghost" @click="showForm = false">取消</button>
          <button class="btn primary" @click="submit">保存</button>
        </div>
      </div>
    </div>

    <!-- 班级详情：学员名单等 -->
    <div v-if="showDetail" class="overlay" @click.self="showDetail = false">
      <div class="modal detail-modal">
        <div class="detail-head">
          <div class="detail-title">
            <span class="subject-badge">{{ detail?.subject?.slice(0, 2) }}</span>
            <div>
              <h2>{{ detail?.name || '班级详情' }}</h2>
              <p class="detail-sub">
                {{ detail?.subject }} · 带教 {{ detail?.teacher_name || '未分配' }}
                <template v-if="detail?.start_date"> · {{ fmtDate(detail.start_date) }} 开班</template>
              </p>
            </div>
          </div>
          <button class="close-x" title="关闭" @click="showDetail = false">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18M6 6l12 12" /></svg>
          </button>
        </div>

        <div v-if="detailLoading" class="detail-loading">加载中…</div>

        <template v-else>
          <div class="detail-stats">
            <div class="d-stat">
              <strong>{{ detail?.students?.length ?? 0 }}</strong>
              <span>在册学员</span>
            </div>
            <div class="d-stat">
              <strong>{{ (detail?.students ?? []).filter((s) => s.status === 'active').length }}</strong>
              <span>在读</span>
            </div>
            <div class="d-stat">
              <strong>{{ (detail?.students ?? []).filter((s) => s.lesson_balance <= 10 && s.status === 'active').length }}</strong>
              <span>课时不足</span>
            </div>
          </div>

          <div v-if="detail?.students?.length" class="student-table">
            <div class="st-row st-head">
              <span>学员</span>
              <span>校区</span>
              <span>课时</span>
              <span>状态</span>
              <span>操作</span>
            </div>
            <div v-for="s in detail!.students" :key="s.id" class="st-row" :class="{ low: s.status === 'active' && s.lesson_balance <= 10 }">
              <span class="st-name">
                {{ s.name }}
                <span v-if="s.phone" class="st-phone">{{ s.phone }}</span>
              </span>
              <span>{{ s.campus || '—' }}</span>
              <span class="st-lessons">{{ s.lesson_balance }} 节</span>
              <span>
                <span class="status-pill" :class="s.status === 'active' ? 'active' : 'stopped'">
                  {{ statusLabel(s.status) }}
                </span>
              </span>
              <span>
                <template v-if="s.status !== 'archived'">
                  <button class="op-btn" @click="guard('class_edit', () => openTransfer(s.id, s.name))">调班</button>
                  <button class="op-btn warn" @click="guard('class_unenroll', () => unenroll(s.id, s.name))">退班</button>
                </template>
                <span v-else class="archived-note">已归档</span>
              </span>
            </div>
          </div>
          <div v-else class="empty-card">该班级暂无学员，可在「学员管理」编辑学员时加入班级</div>
          <p v-if="actionError" class="action-error">{{ actionError }}</p>
        </template>
      </div>
    </div>
    <!-- 学员调班弹窗 -->
    <div v-if="showTransfer" class="overlay" @click.self="showTransfer = false">
      <div class="modal">
        <h2>调班 · {{ transferTarget?.name }}</h2>
        <p class="muted">从「{{ detail?.name }}」转入目标班级（保留其在其他班级的归属）。</p>
        <label>
          目标班级 *
          <select v-model="transferClassId">
            <option value="">请选择班级</option>
            <option v-for="c in transferOptions" :key="c.id" :value="c.id">
              {{ c.name }}（{{ c.subject }} · {{ c.student_count ?? 0 }}人）
            </option>
          </select>
        </label>
        <div class="modal-actions">
          <button class="btn ghost" @click="showTransfer = false">取消</button>
          <button class="btn primary" :disabled="!transferClassId || transferSubmitting" @click="confirmTransfer">
            {{ transferSubmitting ? '提交中…' : '确认调班' }}
          </button>
        </div>
      </div>
    </div>
    <!-- 统一确认弹窗（删除班级 / 学员退班） -->
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
      message="暂无该操作权限，请联系管理员开通。"
      confirm-text="知道了"
      @confirm="showNoPerm = false"
      @cancel="showNoPerm = false"
    />
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
.btn.ghost {
  background: var(--surface);
  color: var(--ink-2);
  border: 1px solid var(--line);
}

.error-banner {
  background: var(--danger-soft);
  color: var(--danger);
  padding: 10px 14px;
  border-radius: 10px;
  margin-bottom: 16px;
  font-size: 13px;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 18px;
  flex-wrap: wrap;
}
.teacher-filter {
  padding: 9px 12px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--surface);
  font-size: 14px;
  color: var(--ink-2);
  cursor: pointer;
  transition: all 0.15s;
}
.filter-select {
  padding: 9px 12px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--surface);
  font-size: 13.5px;
  color: var(--ink-2);
  cursor: pointer;
  transition: all 0.15s;
}
.filter-select:focus {
  outline: none;
  border-color: var(--brand);
  box-shadow: 0 0 0 3px var(--brand-soft);
}
.teacher-select :deep(.ssel-trigger) {
  min-width: 158px;
  font-size: 13.5px;
  padding: 8px 11px;
}
.date-range {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--ink-3);
  font-size: 13px;
}
.date-range input {
  padding: 8px 10px;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: var(--surface);
  font-size: 13px;
  color: var(--ink);
}
.date-range input:focus {
  outline: none;
  border-color: var(--brand);
  box-shadow: 0 0 0 3px var(--brand-soft);
}
.date-range i {
  font-style: normal;
  color: var(--ink-3);
}
.search-box {
  display: flex;
  align-items: center;
  gap: 8px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 0 12px;
  min-width: 280px;
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

/* 卡片网格 */
.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(270px, 1fr));
  gap: 16px;
}
.class-card {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 16px;
  padding: 18px 20px;
  transition: all 0.18s;
  position: relative;
}
.class-card:hover {
  transform: translateY(-3px);
  box-shadow: var(--shadow-md);
  border-color: #c7d2fe;
}
.card-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.subject-badge {
  width: 42px;
  height: 42px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 12px;
  font-weight: 800;
  color: #fff;
  background: linear-gradient(135deg, #6366f1, #06b6d4);
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);
}
.status-pill {
  font-size: 11.5px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 999px;
}
.status-pill.active {
  background: var(--success-soft);
  color: var(--success);
}
.card-name {
  font-size: 16.5px;
  color: var(--ink);
  margin-bottom: 6px;
}
.card-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--ink-3);
  font-size: 13px;
}
.card-meta svg {
  width: 14px;
  height: 14px;
}
.card-foot {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid var(--line);
  font-size: 12.5px;
  color: var(--ink-3);
}
.count strong {
  font-size: 15px;
  color: var(--ink);
}
.card-ops {
  display: flex;
  gap: 8px;
  margin-top: 12px;
}
.op-btn {
  flex: 1;
  border: 1px solid var(--brand);
  background: var(--brand-soft);
  color: var(--brand-strong);
  font-size: 12.5px;
  font-weight: 600;
  padding: 7px 0;
  border-radius: 9px;
  cursor: pointer;
  transition: all 0.15s;
}
.op-btn:hover {
  background: var(--brand);
  color: #fff;
}
.op-btn svg {
  width: 13px;
  height: 13px;
  vertical-align: -2px;
  margin-right: 2px;
}
.op-btn.danger {
  border-color: #fecaca;
  background: var(--danger-soft);
  color: var(--danger);
}
.op-btn.warn {
  border-color: #fde68a;
  background: #fef9c3;
  color: #b45309;
}
.op-btn.warn:hover {
  background: #f59e0b;
  border-color: transparent;
  color: #fff;
}
.op-btn.danger:hover {
  background: var(--danger);
  color: #fff;
}
.empty-card {
  border: 2px dashed var(--line);
  border-radius: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--ink-3);
  padding: 60px 0;
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
  width: 440px;
  background: var(--surface);
  border-radius: 16px;
  padding: 26px;
  box-shadow: var(--shadow-lg);
}
.modal h2 {
  font-size: 18px;
  margin-bottom: 18px;
}
/* —— 班级详情弹窗 —— */
.detail-modal {
  width: 640px;
  max-width: calc(100vw - 40px);
  max-height: min(82vh, 720px);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.detail-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}
.detail-title {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}
.detail-title .subject-badge {
  flex-shrink: 0;
}
.detail-title h2 {
  font-size: 18px;
  margin: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.detail-sub {
  font-size: 12.5px;
  color: var(--ink-3);
  margin-top: 4px;
}
.close-x {
  border: none;
  background: transparent;
  color: var(--ink-3);
  width: 30px;
  height: 30px;
  border-radius: 50%;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.close-x:hover {
  background: var(--brand-soft);
  color: var(--brand-strong);
}
.close-x svg {
  width: 15px;
  height: 15px;
}
.detail-loading {
  text-align: center;
  color: var(--ink-3);
  padding: 40px 0;
  font-size: 13.5px;
}
.detail-stats {
  display: flex;
  gap: 10px;
  margin-bottom: 14px;
}
.d-stat {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  padding: 10px 6px;
  border-radius: 12px;
  background: var(--brand-soft);
}
.d-stat strong {
  font-size: 18px;
  color: var(--brand-strong);
}
.d-stat span {
  font-size: 11.5px;
  color: var(--ink-3);
}
.student-table {
  overflow: auto;
  border: 1px solid var(--line);
  border-radius: 12px;
}
.st-row {
  display: grid;
  grid-template-columns: 2fr 1fr 0.9fr 0.8fr 0.9fr;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  font-size: 13px;
  color: var(--ink-2);
  border-bottom: 1px solid var(--line);
}
.st-row:last-child {
  border-bottom: none;
}
.st-row.st-head {
  background: #f8fafc;
  color: var(--ink-3);
  font-weight: 600;
  font-size: 12px;
  position: sticky;
  top: 0;
}
.st-row.low {
  background: var(--warning-soft);
}
.st-name {
  font-weight: 600;
  color: var(--ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.st-phone {
  font-weight: 400;
  color: var(--ink-3);
  font-size: 11.5px;
  margin-left: 6px;
}
.st-lessons {
  font-variant-numeric: tabular-nums;
}
.status-pill {
  display: inline-block;
  font-size: 11px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 999px;
}
.detail-modal .empty-card {
  padding: 26px 0;
  margin: 0;
  font-size: 13px;
}
.status-pill.active {
  background: var(--success-soft);
  color: #047857;
}
.status-pill.stopped {
  background: var(--danger-soft);
  color: var(--danger);
}
.action-error {
  margin-top: 10px;
  font-size: 13px;
  color: var(--danger);
  background: var(--danger-soft);
  border-radius: 8px;
  padding: 8px 12px;
}
.archived-note {
  font-size: 12px;
  color: var(--ink-3);
}
.modal label {
  display: block;
  margin-bottom: 14px;
  font-size: 13px;
  color: var(--ink-2);
  font-weight: 500;
}
.modal input,
.modal select {
  display: block;
  width: 100%;
  margin-top: 6px;
  padding: 9px 11px;
  border: 1px solid var(--line);
  border-radius: 10px;
  box-sizing: border-box;
  font-size: 14px;
  transition: all 0.15s;
  background: var(--surface);
}
.modal input:focus,
.modal select:focus {
  outline: none;
  border-color: var(--brand);
  box-shadow: 0 0 0 3px var(--brand-soft);
}
/* —— 带教教师选择：搜索 + 校区筛选 —— */
.teacher-picker {
  margin-bottom: 14px;
}
.picker-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 13px;
  color: var(--ink-2);
  font-weight: 500;
  margin-bottom: 8px;
}
.clear-teacher {
  border: none;
  background: none;
  color: var(--ink-3);
  font-size: 12px;
  cursor: pointer;
  padding: 0;
}
.clear-teacher:hover {
  color: var(--danger);
  text-decoration: underline;
}
.picker-search {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  box-sizing: border-box;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 9px;
  padding: 0 10px;
  margin-bottom: 8px;
  transition: all 0.15s;
}
.picker-search:focus-within {
  border-color: var(--brand);
  box-shadow: 0 0 0 3px var(--brand-soft);
}
.picker-search svg {
  width: 14px;
  height: 14px;
  color: var(--ink-3);
  flex-shrink: 0;
}
.picker-search input {
  flex: 1;
  min-width: 0;
  border: none;
  outline: none;
  padding: 8px 0;
  font-size: 13px;
  background: transparent;
  /* 覆盖弹窗全局 .modal input 的 width/margin 规则 */
  width: 100% !important;
  margin-top: 0 !important;
}
.picker-campus-row {
  display: flex;
  gap: 8px;
  margin-bottom: 10px;
}
.picker-campus-row .mini-campus {
  flex: 1;
  width: 100% !important;
  margin-top: 0 !important;
  padding: 8px 10px;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: var(--surface);
  font-size: 13px;
  color: var(--ink-2);
}
.mini-campus:focus {
  outline: none;
  border-color: var(--brand);
}
.clear-filter {
  flex-shrink: 0;
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface);
  color: var(--ink-3);
  font-size: 16px;
  cursor: pointer;
  line-height: 1;
}
.clear-filter:hover {
  border-color: var(--danger);
  color: var(--danger);
}
.teacher-list {
  max-height: 220px;
  overflow: auto;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--surface);
}
.teacher-option {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
  cursor: pointer;
  transition: background 0.12s;
  border-bottom: 1px solid var(--line);
}
.teacher-option:last-child {
  border-bottom: none;
}
.teacher-option:hover {
  background: var(--brand-soft);
}
.teacher-option.checked {
  background: var(--brand-soft);
}
.teacher-radio {
  margin: 0;
  accent-color: var(--brand);
  flex-shrink: 0;
}
.teacher-body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.teacher-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--ink);
}
.teacher-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 2px;
}
.campus-tag {
  font-size: 10.5px;
  font-weight: 600;
  padding: 1px 7px;
  border-radius: 999px;
  background: var(--brand-soft);
  color: var(--brand-strong);
}
.username-tag {
  font-size: 11px;
  color: var(--ink-3);
}
.check-mark {
  flex-shrink: 0;
  color: var(--brand);
  font-weight: 700;
  opacity: 0;
}
.teacher-option.checked .check-mark {
  opacity: 1;
}
.teacher-empty {
  padding: 22px 0;
  text-align: center;
  color: var(--ink-3);
  font-size: 13px;
}
.picker-tip {
  margin-top: 8px;
  font-size: 11.5px;
  color: var(--ink-3);
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
</style>