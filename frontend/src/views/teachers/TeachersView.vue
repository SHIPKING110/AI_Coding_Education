<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import PageHead from '@/components/PageHead.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import PaginationBar from '@/components/PaginationBar.vue'
import {
  createTeacherApi,
  deleteTeacherApi,
  listCampusesApi,
  listTeachersApi,
  updateTeacherApi,
  type UserOut,
} from '@/api/auth'
import { listJobTitles, myPermissions, type JobTitle } from '@/api/permissions'
import { listTeacherLevels, type TeacherLevelOut } from '@/api/payroll'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()

/** 教师操作权限：管理员/教务全开；教师按权限管理配置（后端兜底 403） */
const myPerms = ref<Record<string, boolean>>({})
const can = (key: string): boolean => {
  if (auth.user && ['admin', 'staff'].includes(auth.user.role)) return true
  return myPerms.value[key] !== false
}
async function loadMyPerms() {
  if (!auth.user || auth.user.role !== 'teacher') return
  try {
    myPerms.value = await myPermissions()
  } catch {
    myPerms.value = {}
  }
}

const teachers = ref<UserOut[]>([])
const campuses = ref<string[]>([])
const keyword = ref('')
const campusFilter = ref('')
const levelFilter = ref('')
const filteredTeachers = computed(() =>
  levelFilter.value
    ? teachers.value.filter((t) => t.teacher_level_name === levelFilter.value)
    : teachers.value,
)
const loading = ref(false)
const error = ref('')

// 分页
const page = ref(1)
const pageSize = 12
const total = ref(0)

const showCreate = ref(false)
const createForm = ref({ name: '', username: '', phone: '', password: '', gender: '', campus: '', title: '', level: '', baseSalary: '' })
const formError = ref('')
const submitting = ref(false)

const showEdit = ref(false)
const editing = ref<UserOut | null>(null)
const editForm = ref({ name: '', phone: '', gender: '', campus: '', title: '', level: '', baseSalary: '', password: '', status: 'active' })

const showDetail = ref(false)
const detail = ref<UserOut | null>(null)

// 职务预设（权限管理中维护）+ 自定义输入
const jobTitles = ref<JobTitle[]>([])
const levels = ref<TeacherLevelOut[]>([])
const customTitleCreate = ref(false)
const customTitleEdit = ref(false)

// 无权限提示弹窗
const showNoPerm = ref(false)
const noPermText = ref('')

function deny(actionLabel: string) {
  noPermText.value = `暂无「${actionLabel}」权限，请联系管理员开通。`
  showNoPerm.value = true
}

/** 无权限点击弹提示；有权限执行 */
function guardManage(key: string, actionLabel: string, action: () => void) {
  if (can(key)) action()
  else deny(actionLabel)
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const pageData = await listTeachersApi({
      keyword: keyword.value.trim() || undefined,
      campus: campusFilter.value || undefined,
      include_inactive: true,
      limit: pageSize,
      offset: (page.value - 1) * pageSize,
    })
    teachers.value = pageData.items
    total.value = pageData.total
  } catch {
    error.value = '加载教师列表失败'
  } finally {
    loading.value = false
  }
}

function onSearch() {
  page.value = 1
  load()
}

function onPageChange(p: number) {
  page.value = p
  load()
}

async function loadCampuses() {
  try {
    campuses.value = await listCampusesApi()
  } catch {
    campuses.value = []
  }
}

function openCreate() {
  createForm.value = { name: '', username: '', phone: '', password: '', gender: '', campus: '', title: '', level: '', baseSalary: '' }
  customTitleCreate.value = false
  formError.value = ''
  showCreate.value = true
}

async function submitCreate() {
  formError.value = ''
  const f = createForm.value
  if (!f.name.trim() || !f.username.trim() || !f.password) {
    formError.value = '请填写姓名、登录名与密码'
    return
  }
  if (f.password.length < 6) {
    formError.value = '密码至少 6 位'
    return
  }
  submitting.value = true
  try {
    // 管理端统一走新增教师接口（管理员/教务放行；教师需 teacher_add 权限；职务自动套用预设权限）
    await createTeacherApi({
      name: f.name.trim(),
      username: f.username.trim(),
      phone: f.phone.trim() || null,
      password: f.password,
      gender: f.gender || null,
      campus: f.campus.trim() || null,
      title: f.title.trim() || null,
      teacher_level_id: f.level || null,
      base_salary: f.baseSalary || null,
    })
    showCreate.value = false
    await loadCampuses()
    await load()
  } catch (e: any) {
    formError.value = e?.response?.data?.detail || '创建教师失败'
  } finally {
    submitting.value = false
  }
}

function openEdit(t: UserOut) {
  editing.value = t
  editForm.value = {
    name: t.name,
    phone: t.phone || '',
    gender: t.gender || '',
    campus: t.campus || '',
    title: t.title || '',
    level: t.teacher_level_id || '',
    baseSalary: t.base_salary || '',
    password: '',
    status: t.status,
  }
  customTitleEdit.value = false
  formError.value = ''
  showEdit.value = true
}

async function submitEdit() {
  if (!editing.value) return
  formError.value = ''
  const f = editForm.value
  if (!f.name.trim()) {
    formError.value = '请填写姓名'
    return
  }
  if (f.password && f.password.length < 6) {
    formError.value = '新密码至少 6 位'
    return
  }
  submitting.value = true
  try {
    await updateTeacherApi(editing.value.id, {
      name: f.name.trim(),
      phone: f.phone.trim() || null,
      gender: f.gender || null,
      campus: f.campus.trim() || null,
      title: f.title.trim() || null,
      teacher_level_id: f.level || null,
      base_salary: f.baseSalary || null,
      password: f.password || undefined,
      status: f.status,
    })
    showEdit.value = false
    await loadCampuses()
    await load()
  } catch (e: any) {
    formError.value = e?.response?.data?.detail || '保存失败'
  } finally {
    submitting.value = false
  }
}

function openDetail(t: UserOut) {
  detail.value = t
  showDetail.value = true
}

// 删除确认（统一弹窗）
const delTarget = ref<UserOut | null>(null)
const showDel = ref(false)
function askRemove(t: UserOut) {
  delTarget.value = t
  showDel.value = true
}
async function confirmRemove() {
  if (!delTarget.value) return
  showDel.value = false
  try {
    await deleteTeacherApi(delTarget.value.id)
    await load()
  } catch (e: any) {
    error.value = e?.response?.data?.detail || '删除失败'
  }
}

const activeCount = () => teachers.value.filter((t) => t.status === 'active').length

// 职务选择：选“自定义职务…”时切换为输入框
function onCreateTitleChange() {
  if (createForm.value.title === '__custom__') {
    customTitleCreate.value = true
    createForm.value.title = ''
  }
}
function onEditTitleChange() {
  if (editForm.value.title === '__custom__') {
    customTitleEdit.value = true
    editForm.value.title = ''
  }
}

onMounted(async () => {
  await loadCampuses()
  await loadMyPerms()
  try {
    // 职务预设用于新建/编辑时选择；无权限（如普通教师）则忽略，保留自定义输入
    jobTitles.value = await listJobTitles()
  } catch {
    jobTitles.value = []
  }
  try {
    levels.value = await listTeacherLevels()
  } catch {
    levels.value = []
  }
  await load()
})
</script>

<template>
  <div>
    <PageHead title="教师管理" eyebrow="TEACHERS">
      <template #sub>
        {{ activeCount() }} 名在职 · 教师按校区（一校/二校/三校，可自定义）区分，可在班级管理与排课中分配
        <template v-if="auth.user?.role === 'teacher'"> · 职务标签可在权限管理中预设权限并一键套用</template>
      </template>
      <template #actions>
      <button class="btn primary" @click="guardManage('teacher_add', '新增教师', openCreate)">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 5v14M5 12h14" /></svg>
        新增教师
      </button>
      </template>
    </PageHead>

    <div class="toolbar">
      <div class="search-box">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21 21l-4.35-4.35M17 10.5a6.5 6.5 0 1 1-13 0 6.5 6.5 0 0 1 13 0z" />
        </svg>
        <input v-model="keyword" placeholder="搜索教师姓名/登录名" @keyup.enter="onSearch" />
      </div>
      <select v-model="campusFilter" class="campus-select" @change="onSearch">
        <option value="">全部校区</option>
        <option v-for="c in campuses" :key="c" :value="c">{{ c }}</option>
      </select>
      <select v-model="levelFilter" class="campus-select" @change="onSearch">
        <option value="">全部级别</option>
        <option v-for="l in levels" :key="l.id" :value="l.name">{{ l.name }}（{{ l.ratio_pct }}%）</option>
      </select>
      <button class="btn ghost" @click="onSearch">查询</button>
    </div>

    <p v-if="error" class="error-banner">{{ error }}</p>

    <div class="card-grid">
      <div v-for="t in filteredTeachers" :key="t.id" class="teacher-card" :class="{ disabled: t.status !== 'active' }">
        <div class="avatar" :class="{ off: t.status !== 'active' }">{{ t.name.slice(0, 1) }}</div>
        <div class="info">
          <div class="name-row">
            <span class="name">{{ t.name }}</span>
            <span class="status-pill" :class="t.status === 'active' ? 'active' : 'disabled'">
              {{ t.status === 'active' ? '在职' : '停用' }}
            </span>
          </div>
          <div class="meta">
            <span class="pill username">{{ t.username }}</span>
            <span v-if="t.title" class="pill title-pill">{{ t.title }}</span>
            <span v-if="t.teacher_level_name" class="pill level-pill">{{ t.teacher_level_name }}</span>
            <span v-if="t.campus" class="pill campus">{{ t.campus }}</span>
            <span v-else class="pill no-campus">未分校区</span>
          </div>
          <div class="phone">{{ t.phone || '未留电话' }}</div>
        </div>
        <div class="card-ops">
          <button class="op-btn" title="查看详情" @click="guardManage('teacher_view', '查看教师详情', () => openDetail(t))">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z" /></svg>
          </button>
          <button class="op-btn" title="编辑" @click="guardManage('teacher_edit', '编辑教师', () => openEdit(t))">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z" /></svg>
          </button>
          <button class="op-btn danger" title="删除（停用账号）" @click="guardManage('teacher_delete', '删除教师', () => askRemove(t))">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" /></svg>
          </button>
        </div>
      </div>

      <div v-if="!loading && teachers.length === 0" class="empty-card">
        没有符合条件的教师，点击右上角新增
      </div>
    </div>

    <PaginationBar :total="total" :page="page" :page-size="pageSize" @update:page="onPageChange" />

    <!-- 新增教师弹窗 -->
    <div v-if="showCreate" class="overlay" @click.self="showCreate = false">
      <div class="modal">
        <h2>新增教师账号</h2>
        <label>
          姓名 *
          <input v-model="createForm.name" type="text" placeholder="如：张老师" />
        </label>
        <label>
          登录名 *
          <input v-model="createForm.username" type="text" placeholder="用于登录系统" />
        </label>
        <label>
          联系电话
          <input v-model="createForm.phone" type="text" placeholder="选填" />
        </label>
        <label>
          性别
          <select v-model="createForm.gender">
            <option value="">未填写</option>
            <option value="male">男</option>
            <option value="female">女</option>
          </select>
        </label>
        <label>
          所属校区
          <input v-model="createForm.campus" type="text" list="campus-options" placeholder="如：一校 / 二校 / 三校（可自定义）" />
          <datalist id="campus-options">
            <option v-for="c in campuses" :key="c" :value="c" />
          </datalist>
        </label>
        <label>
          职务标签
          <select v-if="!customTitleCreate" v-model="createForm.title" @change="onCreateTitleChange">
            <option value="">不设职务</option>
            <option v-for="j in jobTitles" :key="j.id" :value="j.name">{{ j.name }}（套用预设权限）</option>
            <option value="__custom__">自定义职务…</option>
          </select>
          <input
            v-else
            v-model="createForm.title"
            type="text"
            placeholder="输入自定义职务，如：班主任"
          />
          <small v-if="!customTitleCreate && createForm.title && createForm.title !== '__custom__'" class="hint">新建后自动套用该职务的预设权限</small>
          <button v-if="createForm.title === '__custom__' || customTitleCreate" type="button" class="link-btn" @click="createForm.title = ''; customTitleCreate = false">返回选择</button>
        </label>
        <label>
          教师级别
          <select v-model="createForm.level">
            <option value="">不设级别</option>
            <option v-for="l in levels" :key="l.id" :value="l.id">{{ l.name }}（绩效 {{ l.ratio_pct }}%）</option>
          </select>
        </label>
        <label>
          基本工资（元/月，留空取职务工资）
          <input v-model="createForm.baseSalary" type="number" min="0" step="100" placeholder="如：5000" />
        </label>
        <label>
          初始密码 *
          <input v-model="createForm.password" type="password" placeholder="至少 6 位" />
        </label>
        <p v-if="formError" class="error">{{ formError }}</p>
        <div class="modal-actions">
          <button class="btn ghost" @click="showCreate = false">取消</button>
          <button class="btn primary" :disabled="submitting" @click="submitCreate">
            {{ submitting ? '创建中…' : '创建账号' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 编辑教师弹窗 -->
    <div v-if="showEdit && editing" class="overlay" @click.self="showEdit = false">
      <div class="modal">
        <h2>编辑教师 · {{ editing.name }}</h2>
        <label>
          姓名 *
          <input v-model="editForm.name" type="text" />
        </label>
        <label>
          联系电话
          <input v-model="editForm.phone" type="text" />
        </label>
        <label>
          性别
          <select v-model="editForm.gender">
            <option value="">未填写</option>
            <option value="male">男</option>
            <option value="female">女</option>
          </select>
        </label>
        <label>
          所属校区
          <input v-model="editForm.campus" type="text" list="campus-options" placeholder="如：一校 / 二校 / 三校（可自定义）" />
        </label>
        <label>
          职务标签
          <select v-if="!customTitleEdit" v-model="editForm.title" @change="onEditTitleChange">
            <option value="">不设职务</option>
            <option v-for="j in jobTitles" :key="j.id" :value="j.name">{{ j.name }}（换职务自动套用预设权限）</option>
            <option v-if="editForm.title && !jobTitles.some((j) => j.name === editForm.title)" :value="editForm.title">{{ editForm.title }}（当前自定义）</option>
            <option value="__custom__">自定义职务…</option>
          </select>
          <input
            v-else
            v-model="editForm.title"
            type="text"
            placeholder="输入自定义职务，如：班主任"
          />
          <small v-if="!customTitleEdit && editForm.title && editForm.title !== '__custom__'" class="hint">保存后自动套用该职务的预设权限</small>
          <button v-if="customTitleEdit" type="button" class="link-btn" @click="editForm.title = ''; customTitleEdit = false">返回选择</button>
        </label>
        <label>
          教师级别
          <select v-model="editForm.level">
            <option value="">不设级别</option>
            <option v-for="l in levels" :key="l.id" :value="l.id">{{ l.name }}（绩效 {{ l.ratio_pct }}%）</option>
            <option v-if="editForm.level && !levels.some((l) => l.id === editForm.level)" :value="editForm.level">当前级别（已停用）</option>
          </select>
        </label>
        <label>
          基本工资（元/月，留空取职务工资）
          <input v-model="editForm.baseSalary" type="number" min="0" step="100" placeholder="如：5000" />
        </label>
        <label>
          重置密码（留空则不修改）
          <input v-model="editForm.password" type="password" placeholder="至少 6 位" />
        </label>
        <label>
          账号状态
          <select v-model="editForm.status">
            <option value="active">在职</option>
            <option value="disabled">停用</option>
          </select>
        </label>
        <p v-if="formError" class="error">{{ formError }}</p>
        <div class="modal-actions">
          <button class="btn ghost" @click="showEdit = false">取消</button>
          <button class="btn primary" :disabled="submitting" @click="submitEdit">
            {{ submitting ? '保存中…' : '保存' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 教师详情弹窗 -->
    <div v-if="showDetail && detail" class="overlay" @click.self="showDetail = false">
      <div class="modal">
        <h2>教师详情</h2>
        <div class="detail-row">
          <span class="detail-label">姓名</span>
          <span class="detail-value">{{ detail.name }}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">登录名</span>
          <span class="detail-value">{{ detail.username }}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">联系电话</span>
          <span class="detail-value">{{ detail.phone || '—' }}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">性别</span>
          <span class="detail-value">{{ detail.gender === 'male' ? '男' : detail.gender === 'female' ? '女' : '—' }}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">所属校区</span>
          <span class="detail-value">
            <span v-if="detail.campus" class="pill campus">{{ detail.campus }}</span>
            <span v-else class="pill no-campus">未分校区</span>
          </span>
        </div>
        <div class="detail-row">
          <span class="detail-label">职务标签</span>
          <span class="detail-value">
            <span v-if="detail.title" class="pill title-pill">{{ detail.title }}</span>
            <span v-else>—</span>
          </span>
        </div>
        <div class="detail-row">
          <span class="detail-label">教师级别</span>
          <span class="detail-value">
            <span v-if="detail.teacher_level_name" class="pill level-pill">{{ detail.teacher_level_name }}</span>
            <span v-else>—</span>
          </span>
        </div>
        <div class="detail-row">
          <span class="detail-label">基本工资</span>
          <span class="detail-value">{{ detail.base_salary ? `¥${Number(detail.base_salary).toLocaleString('zh-CN')}/月（个人）` : '按职务工资' }}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">账号状态</span>
          <span class="detail-value">
            <span class="status-pill" :class="detail.status === 'active' ? 'active' : 'disabled'">
              {{ detail.status === 'active' ? '在职' : '停用' }}
            </span>
          </span>
        </div>
        <div class="detail-row">
          <span class="detail-label">创建时间</span>
          <span class="detail-value">{{ new Date(detail.created_at).toLocaleString() }}</span>
        </div>
        <div class="modal-actions">
          <button class="btn ghost" @click="showDetail = false">关闭</button>
          <button v-if="can('teacher_edit')" class="btn primary" @click="openEdit(detail); showDetail = false">编辑</button>
        </div>
      </div>
    </div>

    <!-- 无权限提示弹窗 -->
    <div v-if="showNoPerm" class="overlay" @click.self="showNoPerm = false">
      <div class="modal no-perm-modal">
        <div class="no-perm-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2" /><path d="M7 11V7a5 5 0 0 1 10 0v4" /></svg>
        </div>
        <h2>无操作权限</h2>
        <p class="no-perm-desc">
          {{ noPermText || '暂无该操作权限，请联系管理员开通。' }}
        </p>
        <div class="modal-actions">
          <button class="btn primary" @click="showNoPerm = false">知道了</button>
        </div>
      </div>
    </div>

    <!-- 删除确认 -->
    <ConfirmDialog
      :visible="showDel"
      title="删除教师"
      :message="`确认删除教师「${delTarget?.name}」？删除后该账号将停用，历史排课与班级数据保留。`"
      confirm-text="删除"
      danger
      @confirm="confirmRemove"
      @cancel="showDel = false"
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

.toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 18px;
}
.search-box {
  display: flex;
  align-items: center;
  gap: 8px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 0 12px;
  min-width: 240px;
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
.campus-select {
  padding: 9px 12px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--surface);
  font-size: 14px;
  color: var(--ink-2);
}
.campus-select:focus {
  outline: none;
  border-color: var(--brand);
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

.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 16px;
}
.teacher-card {
  display: flex;
  align-items: center;
  gap: 14px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 16px;
  padding: 18px;
  transition: all 0.18s;
}
.teacher-card:hover {
  transform: translateY(-3px);
  box-shadow: var(--shadow-md);
  border-color: #c7d2fe;
}
.teacher-card.disabled {
  opacity: 0.65;
}
.avatar {
  width: 48px;
  height: 48px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 14px;
  font-size: 20px;
  font-weight: 800;
  color: #fff;
  background: linear-gradient(135deg, #8b5cf6, #6366f1);
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);
}
.avatar.off {
  background: linear-gradient(135deg, #94a3b8, #64748b);
  box-shadow: none;
}
.info {
  flex: 1;
  min-width: 0;
}
.name-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.name {
  font-weight: 700;
  font-size: 15.5px;
  color: var(--ink);
}
.status-pill {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 999px;
}
.status-pill.active {
  background: var(--success-soft);
  color: var(--success);
}
.status-pill.disabled {
  background: #f1f5f9;
  color: var(--ink-3);
}
.meta {
  margin-top: 5px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.pill {
  font-size: 11.5px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 999px;
}
.pill.username {
  background: #f1f5f9;
  color: var(--ink-2);
}
.pill.campus {
  background: var(--brand-soft);
  color: var(--brand-strong);
}
.pill.title-pill {
  background: #fef3c7;
  color: #92400e;
}
.pill.level-pill {
  background: #e0e7ff;
  color: #3730a3;
}
.pill.no-campus {
  background: #f1f5f9;
  color: var(--ink-3);
}
.hint {
  color: var(--ink-3);
  font-size: 12px;
  margin-top: 4px;
  display: block;
}
.link-btn {
  background: none;
  border: none;
  color: var(--brand-strong);
  font-size: 12.5px;
  cursor: pointer;
  padding: 4px 0 0;
}
.phone {
  color: var(--ink-3);
  font-size: 12.5px;
  margin-top: 4px;
}
.card-ops {
  display: flex;
  gap: 4px;
}
.op-btn {
  width: 30px;
  height: 30px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  background: var(--brand-soft);
  color: var(--brand-strong);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.15s;
}
.op-btn:hover {
  background: var(--brand);
  color: #fff;
}
.op-btn.danger {
  background: var(--danger-soft);
  color: var(--danger);
}
.op-btn.danger:hover {
  background: var(--danger);
  color: #fff;
}
.op-btn svg {
  width: 15px;
  height: 15px;
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
  max-height: 86vh;
  overflow: auto;
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

.detail-row {
  display: flex;
  align-items: center;
  padding: 11px 0;
  border-bottom: 1px solid var(--line);
  font-size: 14px;
}
.detail-row:last-of-type {
  border-bottom: none;
}
.detail-label {
  width: 90px;
  flex-shrink: 0;
  color: var(--ink-3);
  font-size: 13px;
}
.detail-value {
  color: var(--ink);
  font-weight: 500;
}

.no-perm-modal {
  width: 380px;
  text-align: center;
}
.no-perm-icon {
  width: 52px;
  height: 52px;
  margin: 0 auto 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: var(--danger-soft);
  color: var(--danger);
}
.no-perm-icon svg {
  width: 24px;
  height: 24px;
}
.no-perm-modal h2 {
  font-size: 17px;
  margin-bottom: 8px;
}
.no-perm-desc {
  color: var(--ink-3);
  font-size: 13px;
  line-height: 1.7;
}
.no-perm-modal .modal-actions {
  justify-content: center;
}
</style>
