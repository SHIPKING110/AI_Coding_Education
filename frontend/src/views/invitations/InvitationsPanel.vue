<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import PaginationBar from '@/components/PaginationBar.vue'
import { listClasses } from '@/api/enrollment'
import { listUsersApi } from '@/api/client'
import { listSubjects } from '@/api/business'
import { createSchedule, listSchedules, type ScheduleOut } from '@/api/schedule'
import { listCampusesApi, listTeachersApi } from '@/api/auth'
import {
  INVITATION_STATUS_LABEL,
  createInvitation,
  createTrialStudent,
  deleteInvitation,
  listInvitations,
  updateInvitation,
  updateTrialStatus,
  uploadChatImage,
  type InvitationOut,
} from '@/api/trials'

const items = ref<InvitationOut[]>([])
const total = ref(0)
const loading = ref(false)
const error = ref('')
const statusFilter = ref('')
const keyword = ref('')
const subjectFilter = ref('')
const staffFilter = ref('')
const trialTeacherFilter = ref('')
const campusFilter = ref('')
const dateFrom = ref('')
const dateTo = ref('')
const page = ref(1)
const pageSize = 10

const subjects = ref<{ id: string; name: string }[]>([])
const classes = ref<{ id: string; name: string; subject?: string | null; teacher_id?: string | null }[]>([])
const teachers = ref<{ id: string; name: string; campus?: string | null }[]>([])
const inviters = ref<{ id: string; name: string; role: string; campus?: string | null }[]>([])
const panelCampuses = ref<string[]>([])
const msg = ref('')

// 筛选联动：校区 → 邀约人/体验教师；科目 → 体验教师（按带班科目）
const filteredInviters = computed(() =>
  campusFilter.value ? inviters.value.filter((u) => u.campus === campusFilter.value) : inviters.value,
)
const teacherSubjectMap = computed(() => {
  const m = new Map<string, Set<string>>()
  for (const c of classes.value) {
    if (!c.teacher_id || !c.subject) continue
    if (!m.has(c.teacher_id)) m.set(c.teacher_id, new Set())
    m.get(c.teacher_id)!.add(c.subject)
  }
  return m
})
const filterSubjectName = computed(() => subjects.value.find((s) => s.id === subjectFilter.value)?.name || '')
const filteredTrialTeachers = computed(() =>
  teachers.value.filter((t) => {
    if (campusFilter.value && t.campus !== campusFilter.value) return false
    if (filterSubjectName.value && !teacherSubjectMap.value.get(t.id)?.has(filterSubjectName.value)) return false
    return true
  }),
)

function onCampusChange() {
  if (staffFilter.value && !filteredInviters.value.some((u) => u.id === staffFilter.value)) staffFilter.value = ''
  if (trialTeacherFilter.value && !filteredTrialTeachers.value.some((t) => t.id === trialTeacherFilter.value)) trialTeacherFilter.value = ''
  onFilter()
}

function onSubjectChange() {
  if (trialTeacherFilter.value && !filteredTrialTeachers.value.some((t) => t.id === trialTeacherFilter.value)) trialTeacherFilter.value = ''
  onFilter()
}

function flash(t: string) {
  msg.value = t
  setTimeout(() => (msg.value = ''), 3500)
}

// 新建/编辑
const showCreate = ref(false)
const editing = ref<InvitationOut | null>(null)
const createError = ref('')
const form = ref({
  parent_name: '',
  parent_phone: '',
  student_name: '',
  subject_id: '',
  remark: '',
})
const images = ref<string[]>([])
const uploading = ref(false)
const creating = ref(false)

// 排体验课
const showSched = ref(false)
const schedTarget = ref<InvitationOut | null>(null)
const schedMode = ref<'create' | 'link'>('create')
const schedError = ref('')
const schedCampus = ref('')
const schedCampuses = ref<string[]>([])
const allTeachers = ref<{ id: string; name: string; campus?: string | null }[]>([])
const schedForm = ref({ class_id: '', teacher_id: '', start: '', end: '', is_trial: true })
const scheduling = ref(false)
// 关联已有排课
const linkDate = ref('')
const linkTeacher = ref('')
const daySchedules = ref<ScheduleOut[]>([])
const dayLoading = ref(false)
const linkSelected = ref('')
const linking = ref(false)

// 报名
const showSign = ref(false)
const signTarget = ref<InvitationOut | null>(null)
const signForm = ref({ source: 'normal', referrer: '' })
const signing = ref(false)

const previewImg = ref('')

// 排体验课弹窗内的联动筛选：校区→教师；班级不做硬过滤（意向科目相同的排前面），
// 支持先选班级（自动带出该班教师，可再改），再选时间
const schedTeachers = computed(() =>
  schedCampus.value ? allTeachers.value.filter((t) => t.campus === schedCampus.value) : allTeachers.value,
)
const schedClasses = computed(() => {
  const want = schedTarget.value?.subject_name || ''
  return [...classes.value].sort((a, b) => {
    const am = want && a.subject === want ? 0 : 1
    const bm = want && b.subject === want ? 0 : 1
    return am - bm
  })
})

// 先选班级 → 自动带出该班教师（用户可再改）
function onSchedClass() {
  const c = classes.value.find((x) => x.id === schedForm.value.class_id)
  if (c?.teacher_id && !schedForm.value.teacher_id) {
    schedForm.value.teacher_id = c.teacher_id
  }
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const data = await listInvitations({
      status: statusFilter.value || undefined,
      keyword: keyword.value.trim() || undefined,
      subject_id: subjectFilter.value || undefined,
      staff_id: staffFilter.value || undefined,
      trial_teacher_id: trialTeacherFilter.value || undefined,
      campus: campusFilter.value || undefined,
      date_from: dateFrom.value || undefined,
      date_to: dateTo.value || undefined,
      limit: pageSize,
      offset: (page.value - 1) * pageSize,
    })
    items.value = data.items
    total.value = data.total
  } catch {
    error.value = '加载邀约记录失败'
  } finally {
    loading.value = false
  }
}

function onFilter() {
  page.value = 1
  load()
}

async function onPickFiles(e: Event) {
  const files = (e.target as HTMLInputElement).files
  if (!files || !files.length) return
  uploading.value = true
  try {
    for (const f of Array.from(files)) {
      const out = await uploadChatImage(f)
      images.value.push(out.url)
    }
  } catch {
    error.value = '图片上传失败（仅支持图片）'
  } finally {
    uploading.value = false
    ;(e.target as HTMLInputElement).value = ''
  }
}

function apiUrl(u: string): string {
  if (!u) return ''
  if (u.startsWith('http')) return u
  // 上传文件由后端 /uploads 静态服务；同域下相对路径即可（dev 由 vite 代理，生产由 nginx 反代）
  return u.startsWith('/') ? u : `/${u}`
}

async function submitCreate() {
  if (!form.value.parent_name.trim() || !form.value.student_name.trim()) {
    createError.value = '请填写家长姓名与学员姓名'
    return
  }
  creating.value = true
  createError.value = ''
  try {
    const subj = subjects.value.find((s) => s.id === form.value.subject_id)
    if (editing.value) {
      await updateInvitation(editing.value.id, {
        parent_name: form.value.parent_name.trim(),
        parent_phone: form.value.parent_phone.trim() || null,
        student_name: form.value.student_name.trim(),
        subject_id: form.value.subject_id || null,
        subject_name: subj?.name || editing.value.subject_name || null,
        chat_images: images.value,
        remark: form.value.remark.trim() || null,
      })
      flash(`已更新「${form.value.student_name.trim()}」的邀约记录`)
    } else {
      await createInvitation({
        parent_name: form.value.parent_name.trim(),
        parent_phone: form.value.parent_phone.trim() || null,
        student_name: form.value.student_name.trim(),
        subject_id: form.value.subject_id || null,
        subject_name: subj?.name || null,
        chat_images: images.value,
        remark: form.value.remark.trim() || null,
      })
      flash(`已新建「${form.value.student_name.trim()}」的邀约记录`)
    }
    closeCreate()
    onFilter()
  } catch (e: any) {
    createError.value = e?.response?.data?.detail || (editing.value ? '更新邀约失败' : '新建邀约失败')
  } finally {
    creating.value = false
  }
}

function openCreate() {
  editing.value = null
  form.value = { parent_name: '', parent_phone: '', student_name: '', subject_id: '', remark: '' }
  images.value = []
  createError.value = ''
  showCreate.value = true
}

function openEdit(inv: InvitationOut) {
  editing.value = inv
  form.value = {
    parent_name: inv.parent_name,
    parent_phone: inv.parent_phone || '',
    student_name: inv.student_name,
    subject_id: inv.subject_id || '',
    remark: inv.remark || '',
  }
  images.value = [...(inv.chat_images || [])]
  createError.value = ''
  showCreate.value = true
}

function closeCreate() {
  showCreate.value = false
  editing.value = null
}

async function removeInvite(inv: InvitationOut) {
  const tip = inv.trial_student_id
    ? `确定删除「${inv.student_name}」的邀约记录吗？其体验中学员档案将一并清档（学员管理中不再保留）。`
    : `确定删除「${inv.student_name}」的邀约记录吗？`
  if (!window.confirm(tip)) return
  try {
    const r = await deleteInvitation(inv.id)
    flash(r.cleaned_student ? '已删除邀约记录，体验学员档案已同步清档' : '已删除邀约记录')
    onFilter()
  } catch (e: any) {
    error.value = e?.response?.data?.detail || '删除失败'
  }
}

async function makeTrialStudent(inv: InvitationOut) {
  try {
    await createTrialStudent(inv.id)
    load()
  } catch (e: any) {
    error.value = e?.response?.data?.detail || '建档失败'
  }
}

function openSched(inv: InvitationOut) {
  schedTarget.value = inv
  schedMode.value = 'create'
  schedError.value = ''
  schedCampus.value = ''
  schedForm.value = { class_id: '', teacher_id: '', start: '', end: '', is_trial: true }
  linkDate.value = new Date().toISOString().slice(0, 10)
  linkTeacher.value = ''
  daySchedules.value = []
  linkSelected.value = ''
  showSched.value = true
  listCampusesApi().then((c) => (schedCampuses.value = c)).catch(() => {})
  listTeachersApi({ limit: 500 })
    .then((p) => (allTeachers.value = p.items.map((t) => ({ id: t.id, name: t.name, campus: (t as any).campus ?? null }))))
    .catch(() => {})
}

// 开始时间选定 → 结束时间自动延后 90 分钟（可再手工改）
function onSchedStart() {
  if (!schedForm.value.start) return
  const d = new Date(schedForm.value.start)
  if (Number.isNaN(d.getTime())) return
  const e = new Date(d.getTime() + 90 * 60 * 1000)
  const pad = (n: number) => String(n).padStart(2, '0')
  schedForm.value.end = `${e.getFullYear()}-${pad(e.getMonth() + 1)}-${pad(e.getDate())}T${pad(e.getHours())}:${pad(e.getMinutes())}`
}

async function submitSched() {
  schedError.value = ''
  if (!schedTarget.value || !schedForm.value.teacher_id || !schedForm.value.start || !schedForm.value.end) {
    schedError.value = '请补全必填项：教师、开始时间、结束时间（班级可空，不选即教师空余时段体验课）'
    return
  }
  if (new Date(schedForm.value.end) <= new Date(schedForm.value.start)) {
    schedError.value = '结束时间必须晚于开始时间'
    return
  }
  scheduling.value = true
  try {
    const r = await createSchedule({
      class_id: schedForm.value.class_id || null,
      teacher_id: schedForm.value.teacher_id,
      start_time: new Date(schedForm.value.start).toISOString(),
      end_time: new Date(schedForm.value.end).toISOString(),
      is_trial: schedForm.value.is_trial,
    })
    if (!r.created || !r.schedule) {
      schedError.value = r.conflicts.length
        ? `时间冲突，同时段已有：${r.conflicts.map((c) => `${c.class_name || '体验课'}@${(c.start_time || '').slice(11, 16)}`).join('；')}。请换时间，或勾选强制创建。`
        : '排课失败'
      return
    }
    await updateInvitation(schedTarget.value.id, {
      status: 'scheduled',
      trial_schedule_id: r.schedule.id,
      trial_class_id: r.schedule.class_id,
      trial_teacher_id: r.schedule.teacher_id,
    })
    showSched.value = false
    load()
  } catch (e: any) {
    schedError.value = e?.response?.data?.detail || '排课失败'
  } finally {
    scheduling.value = false
  }
}

async function loadDaySchedules() {
  daySchedules.value = []
  linkSelected.value = ''
  if (!linkDate.value || !linkTeacher.value) return
  dayLoading.value = true
  try {
    const start = new Date(`${linkDate.value}T00:00:00`).toISOString()
    const end = new Date(`${linkDate.value}T23:59:59`).toISOString()
    daySchedules.value = await listSchedules({ start, end, teacher_id: linkTeacher.value })
  } catch {
    daySchedules.value = []
  } finally {
    dayLoading.value = false
  }
}

async function submitLink() {
  schedError.value = ''
  const s = daySchedules.value.find((x) => x.id === linkSelected.value)
  if (!schedTarget.value || !s) {
    schedError.value = '请先选择要关联的排课'
    return
  }
  linking.value = true
  try {
    await updateInvitation(schedTarget.value.id, {
      status: 'scheduled',
      trial_schedule_id: s.id,
      trial_class_id: s.class_id,
      trial_teacher_id: s.teacher_id,
    })
    showSched.value = false
    load()
  } catch (e: any) {
    schedError.value = e?.response?.data?.detail || '关联失败'
  } finally {
    linking.value = false
  }
}

async function setStatus(inv: InvitationOut, st: string) {
  try {
    if (inv.trial_student_id && (st === 'arrived' || st === 'signed' || st === 'lost')) {
      const r = await updateTrialStatus(inv.trial_student_id, {
        trial_status: st === 'arrived' ? 'trial' : st === 'signed' ? 'signed' : 'lost',
      })
      if (st === 'lost' && (r as Record<string, unknown>).deleted_student) {
        flash(`「${inv.student_name}」未报名，体验学员档案已自动清档（学员管理中不再保留）`)
      }
    } else if (st === 'lost') {
      flash(`「${inv.student_name}」已标记未报名结束`)
    }
    await updateInvitation(inv.id, { status: st })
    load()
  } catch (e: any) {
    error.value = e?.response?.data?.detail || '状态更新失败'
  }
}

function openSign(inv: InvitationOut) {
  signTarget.value = inv
  signForm.value = { source: 'normal', referrer: '' }
  showSign.value = true
}

async function submitSign() {
  if (!signTarget.value?.trial_student_id) {
    error.value = '请先建立体验学员档案'
    return
  }
  signing.value = true
  try {
    await updateTrialStatus(signTarget.value.trial_student_id, {
      trial_status: 'signed',
      source: signForm.value.source,
      referrer: signForm.value.referrer.trim() || null,
    })
    await updateInvitation(signTarget.value.id, { status: 'signed' })
    showSign.value = false
    load()
  } catch (e: any) {
    error.value = e?.response?.data?.detail || '报名标记失败'
  } finally {
    signing.value = false
  }
}

onMounted(async () => {
  load()
  try {
    const [s, c, u, all, camps] = await Promise.all([
      listSubjects().catch(() => []),
      listClasses({ limit: 500 }).catch(() => ({ items: [] })),
      listUsersApi({ role: 'teacher' }).catch(() => ({ items: [] as any[] })),
      listUsersApi({ limit: 500 }).catch(() => ({ items: [] as any[] })),
      listCampusesApi().catch(() => [] as string[]),
    ])
    subjects.value = (s as any[]) || []
    classes.value = ((c as any)?.items || []) as any[]
    const ulist = ((u as any)?.items || []) as any[]
    teachers.value = ulist.map((x: any) => ({ id: x.id, name: x.name, campus: x.campus ?? null }))
    const allUsers = (((all as any)?.items || []) as any[]).filter((x: any) =>
      ['admin', 'staff', 'teacher'].includes(x.role),
    )
    inviters.value = allUsers.map((x: any) => ({ id: x.id, name: x.name, role: x.role, campus: x.campus ?? null }))
    panelCampuses.value = (camps as string[]) || []
  } catch {
    /* 基础资料加载失败不阻塞主流程 */
  }
})
</script>

<template>
  <div class="invites">
    <div class="filter-bar">
      <select v-model="statusFilter" class="filter-select" @change="onFilter()">
        <option value="">全部状态</option>
        <option value="invited">已邀约</option>
        <option value="scheduled">已排体验课</option>
        <option value="arrived">已到场</option>
        <option value="signed">已报名</option>
        <option value="lost">未报名结束</option>
      </select>
      <select v-model="subjectFilter" class="filter-select" @change="onSubjectChange()">
        <option value="">全部科目</option>
        <option v-for="s in subjects" :key="s.id" :value="s.id">{{ s.name }}</option>
      </select>
      <select v-model="campusFilter" class="filter-select" @change="onCampusChange()">
        <option value="">全部校区</option>
        <option v-for="c in panelCampuses" :key="c" :value="c">{{ c }}</option>
      </select>
      <select v-model="staffFilter" class="filter-select" @change="onFilter()">
        <option value="">全部邀约人</option>
        <option v-for="u in filteredInviters" :key="u.id" :value="u.id">{{ u.name }}{{ u.campus ? `（${u.campus}）` : '' }}</option>
      </select>
      <select v-model="trialTeacherFilter" class="filter-select" @change="onFilter()">
        <option value="">全部体验教师</option>
        <option v-for="t in filteredTrialTeachers" :key="t.id" :value="t.id">{{ t.name }}{{ t.campus ? `（${t.campus}）` : '' }}</option>
      </select>
      <input v-model="keyword" type="text" class="filter-input" placeholder="学员/家长/电话" @keyup.enter="onFilter()" />
      <input v-model="dateFrom" type="date" class="filter-input" title="记录日期起" @change="onFilter()" />
      <span class="filter-sep">—</span>
      <input v-model="dateTo" type="date" class="filter-input" title="记录日期止" @change="onFilter()" />
      <button class="btn primary sm" @click="onFilter()">查询</button>
      <button class="btn ghost sm" @click="openCreate()">＋ 新建邀约</button>
    </div>

    <p v-if="error" class="error-banner">{{ error }}</p>
    <p v-if="msg" class="success-banner">{{ msg }}</p>
    <div v-if="loading" class="loading-tip">加载中…</div>
    <div v-else-if="items.length === 0" class="empty-tip">暂无邀约记录，点击右上新建</div>
    <div v-else class="invite-list">
      <section v-for="inv in items" :key="inv.id" class="card invite-card">
        <div class="invite-head">
          <strong class="invite-name">{{ inv.student_name }}</strong>
          <span class="pill" :class="`st-${inv.status}`">{{ INVITATION_STATUS_LABEL[inv.status] || inv.status }}</span>
          <span v-if="inv.subject_name" class="subj-chip">{{ inv.subject_name }}</span>
          <span class="muted-sm">{{ inv.parent_name }}{{ inv.parent_phone ? ` · ${inv.parent_phone}` : '' }}</span>
          <span class="head-sep" />
          <button v-if="inv.status !== 'signed'" class="icon-btn" title="编辑邀约" @click="openEdit(inv)">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M17 3a2.8 2.8 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5z" /></svg>
          </button>
          <button v-if="inv.status !== 'signed'" class="icon-btn danger" title="删除邀约" @click="removeInvite(inv)">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2m2 0v14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V6" /></svg>
          </button>
        </div>
        <div class="invite-meta muted-sm">
          <span>邀约人：{{ inv.staff_name || '—' }}{{ inv.staff_campus ? `（${inv.staff_campus}）` : '' }}</span>
          <span v-if="inv.trial_teacher_name">体验教师：{{ inv.trial_teacher_name }}</span>
          <span v-if="inv.created_at">记录于 {{ inv.created_at.slice(0, 16).replace('T', ' ') }}</span>
        </div>
        <p v-if="inv.remark" class="invite-remark">{{ inv.remark }}</p>
        <div v-if="inv.chat_images.length" class="thumbs">
          <img
            v-for="(u, i) in inv.chat_images"
            :key="i"
            :src="apiUrl(u)"
            class="thumb"
            @click="previewImg = apiUrl(u)"
          />
        </div>
        <div class="invite-actions">
          <button v-if="inv.status === 'invited' && !inv.trial_student_id" class="btn primary sm" @click="makeTrialStudent(inv)">建体验学员档案</button>
          <button v-if="(inv.status === 'invited' || inv.status === 'scheduled') && inv.trial_student_id && !inv.trial_schedule_id" class="btn primary sm" @click="openSched(inv)">排体验课</button>
          <button v-if="inv.status === 'scheduled'" class="btn ghost sm" @click="setStatus(inv, 'arrived')">标记已到场</button>
          <button v-if="inv.status === 'arrived'" class="btn primary sm" @click="openSign(inv)">报名成功</button>
          <button v-if="inv.status === 'arrived'" class="btn ghost sm" @click="setStatus(inv, 'lost')">未报名结束</button>
          <span v-if="inv.status === 'signed'" class="done-tag">已转正式学员</span>
          <span v-if="inv.status === 'lost'" class="muted-sm">服务结束</span>
        </div>
      </section>
    </div>
    <PaginationBar :total="total" :page="page" :page-size="pageSize" @update:page="(p) => { page = p; load() }" />

    <!-- 新建/编辑邀约 -->
    <div v-if="showCreate" class="overlay" @click.self="closeCreate()">
      <div class="modal">
        <h2>{{ editing ? '编辑邀约记录' : '新建邀约记录' }}</h2>
        <p v-if="createError" class="error-banner">{{ createError }}</p>
        <div class="form-grid">
          <label>家长姓名*<input v-model="form.parent_name" type="text" placeholder="如：王妈妈" /></label>
          <label>家长电话<input v-model="form.parent_phone" type="text" placeholder="选填" /></label>
          <label>学员姓名*<input v-model="form.student_name" type="text" placeholder="如：小王" /></label>
          <label>意向科目
            <select v-model="form.subject_id">
              <option value="">未定</option>
              <option v-for="s in subjects" :key="s.id" :value="s.id">{{ s.name }}</option>
            </select>
          </label>
        </div>
        <label class="full">沟通备注<textarea v-model="form.remark" rows="2" placeholder="意向情况说明…" /></label>
        <div class="upload-row">
          <label class="btn ghost sm file-btn">＋ 上传聊天截图<input type="file" accept="image/*" multiple hidden @change="onPickFiles" /></label>
          <span v-if="uploading" class="muted-sm">上传中…</span>
        </div>
        <div v-if="images.length" class="thumbs">
          <img v-for="(u, i) in images" :key="i" :src="apiUrl(u)" class="thumb" @click="previewImg = apiUrl(u)" />
        </div>
        <div class="modal-actions">
          <button class="btn ghost" @click="closeCreate()">取消</button>
          <button class="btn primary" :disabled="creating" @click="submitCreate">{{ creating ? '保存中…' : editing ? '保存修改' : '保存邀约' }}</button>
        </div>
      </div>
    </div>

    <!-- 排体验课 -->
    <div v-if="showSched && schedTarget" class="overlay" @click.self="showSched = false">
      <div class="modal">
        <h2>排体验课 · {{ schedTarget.student_name }}</h2>
        <p v-if="schedError" class="error-banner">{{ schedError }}</p>
        <div class="mode-tabs">
          <button class="mode-tab" :class="{ active: schedMode === 'create' }" @click="schedMode = 'create'; schedError = ''">新建排课</button>
          <button class="mode-tab" :class="{ active: schedMode === 'link' }" @click="schedMode = 'link'; schedError = ''">关联已有排课</button>
        </div>
        <template v-if="schedMode === 'create'">
          <p class="muted-sm">选开始时间后结束时间自动延后 90 分钟（可改）；班级可空，不选即排该教师空余时段。同班同时段已有课程（含体验课）会判冲突。</p>
          <div class="form-grid">
            <label>校区筛选
              <select v-model="schedCampus">
                <option value="">全部校区</option>
                <option v-for="c in schedCampuses" :key="c" :value="c">{{ c }}</option>
              </select>
            </label>
            <label>教师*
              <select v-model="schedForm.teacher_id">
                <option value="">请选择</option>
                <option v-for="t in schedTeachers" :key="t.id" :value="t.id">{{ t.name }}{{ t.campus ? `（${t.campus}）` : '' }}</option>
              </select>
            </label>
            <label class="full-row">班级（可空，不选=教师空余时段体验课）
              <select v-model="schedForm.class_id" @change="onSchedClass">
                <option value="">不选班级</option>
                <option v-for="c in schedClasses" :key="c.id" :value="c.id">{{ c.name }}{{ c.subject ? `（${c.subject}）` : '' }}</option>
              </select>
            </label>
            <label>开始时间*<input v-model="schedForm.start" type="datetime-local" @change="onSchedStart" /></label>
            <label>结束时间*<input v-model="schedForm.end" type="datetime-local" /></label>
          </div>
          <label class="check"><input v-model="schedForm.is_trial" type="checkbox" />标记为体验课（时段显示体验标签）</label>
          <div class="modal-actions">
            <button class="btn ghost" @click="showSched = false">取消</button>
            <button class="btn primary" :disabled="scheduling" @click="submitSched">{{ scheduling ? '排课中…' : '确认排课' }}</button>
          </div>
        </template>
        <template v-else>
          <p class="muted-sm">在排课与考勤模块已建好的课（含体验课）可直接关联到本邀约，关联后体验学员出现在该节考勤名单，教师收到站内通知。</p>
          <div class="form-grid">
            <label>日期<input v-model="linkDate" type="date" @change="loadDaySchedules" /></label>
            <label>教师
              <select v-model="linkTeacher" @change="loadDaySchedules">
                <option value="">请选择</option>
                <option v-for="t in schedTeachers" :key="t.id" :value="t.id">{{ t.name }}</option>
              </select>
            </label>
          </div>
          <div v-if="dayLoading" class="muted-sm">查询中…</div>
          <div v-else-if="linkTeacher && daySchedules.length === 0" class="muted-sm">该教师当天无排课</div>
          <div v-else class="link-list">
            <label v-for="s in daySchedules" :key="s.id" class="link-item" :class="{ sel: linkSelected === s.id }">
              <input v-model="linkSelected" type="radio" :value="s.id" />
              <span>{{ (s.start_time || '').slice(11, 16) }}–{{ (s.end_time || '').slice(11, 16) }}</span>
              <strong>{{ s.class_name || '体验课（无班级）' }}</strong>
              <span v-if="s.is_trial" class="trial-chip">体验课</span>
            </label>
          </div>
          <div class="modal-actions">
            <button class="btn ghost" @click="showSched = false">取消</button>
            <button class="btn primary" :disabled="linking" @click="submitLink">{{ linking ? '关联中…' : '确认关联' }}</button>
          </div>
        </template>
      </div>
    </div>

    <!-- 报名成功 -->
    <div v-if="showSign && signTarget" class="overlay" @click.self="showSign = false">
      <div class="modal small">
        <h2>报名成功 · {{ signTarget.student_name }}</h2>
        <p class="muted-sm">转正式学员并计入体验转化提成；口碑来源请标记介绍人以计转介绍提成。</p>
        <div class="form-grid">
          <label>生源
            <select v-model="signForm.source">
              <option value="normal">自然到访</option>
              <option value="referral">口碑转介绍</option>
            </select>
          </label>
          <label>介绍人<input v-model="signForm.referrer" type="text" placeholder="口碑来源必填" /></label>
        </div>
        <div class="modal-actions">
          <button class="btn ghost" @click="showSign = false">取消</button>
          <button class="btn primary" :disabled="signing" @click="submitSign">{{ signing ? '提交中…' : '确认报名' }}</button>
        </div>
      </div>
    </div>

    <!-- 图片预览 -->
    <div v-if="previewImg" class="overlay img-overlay" @click="previewImg = ''">
      <img :src="previewImg" class="preview" />
    </div>
  </div>
</template>

<style scoped>
.invites { position: relative; }
.filter-bar { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; flex-wrap: wrap; }
.filter-select, .filter-input { padding: 8px 12px; border: 1px solid var(--line); border-radius: 10px; background: var(--surface); font-size: 13px; color: var(--ink-2); }
.btn { padding: 8px 18px; border-radius: 10px; font-size: 13px; cursor: pointer; border: 1px solid var(--line); }
.btn.primary { background: linear-gradient(135deg, #6366f1, #06b6d4); color: #fff; border-color: transparent; font-weight: 600; }
.btn.ghost { background: var(--surface); color: var(--ink-2); }
.btn.danger { background: #fef2f2; color: #b91c1c; }
.action-sep { flex: 1; }
.btn.sm { padding: 7px 14px; font-size: 12.5px; }
.error-banner { background: var(--danger-soft); color: var(--danger); padding: 10px 14px; border-radius: 10px; margin-bottom: 14px; font-size: 13px; }
.success-banner { background: #e2f5ea; color: #0e9f6e; padding: 10px 14px; border-radius: 10px; margin-bottom: 14px; font-size: 13px; }
.invite-list { display: flex; flex-direction: column; gap: 12px; }
.card { background: var(--surface); border: 1px solid var(--line); border-radius: 16px; padding: 16px 18px; }
.invite-head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.head-sep { flex: 1; }
.icon-btn { display: inline-flex; align-items: center; justify-content: center; width: 30px; height: 30px; border-radius: 9px; border: 1px solid var(--line); background: var(--surface); color: var(--ink-2); cursor: pointer; transition: all 0.15s; }
.icon-btn svg { width: 15px; height: 15px; }
.icon-btn:hover { border-color: #6366f1; color: #4f46e5; }
.icon-btn.danger:hover { border-color: #fca5a5; color: #b91c1c; background: #fef2f2; }
.invite-name { font-size: 15px; }
.pill { display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: 12px; background: var(--surface-alt); color: var(--ink-2); }
.pill.st-invited { background: #eef2ff; color: #4338ca; }
.pill.st-scheduled { background: #e0f2fe; color: #0369a1; }
.pill.st-arrived { background: #fdf0dd; color: #c2570b; }
.pill.st-signed { background: #e2f5ea; color: #0e9f6e; }
.pill.st-lost { background: var(--surface-alt); color: var(--ink-3); }
.subj-chip { font-size: 11px; font-weight: 700; padding: 1px 8px; border-radius: 999px; background: #fef3c7; color: #92400e; }
.invite-meta { display: flex; gap: 14px; margin-top: 6px; flex-wrap: wrap; }
.invite-remark { font-size: 13px; color: var(--ink-2); margin: 8px 0 0; }
.thumbs { display: flex; gap: 8px; margin-top: 10px; flex-wrap: wrap; }
.thumb { width: 64px; height: 64px; object-fit: cover; border-radius: 10px; border: 1px solid var(--line); cursor: zoom-in; }
.invite-actions { display: flex; gap: 8px; margin-top: 12px; flex-wrap: wrap; align-items: center; }
.done-tag { font-size: 12px; font-weight: 700; color: #0e9f6e; }
.muted-sm { font-size: 12px; color: var(--ink-3); }
.loading-tip, .empty-tip { text-align: center; color: var(--ink-3); padding: 20px 0; font-size: 13px; }
.overlay { position: fixed; inset: 0; background: rgba(15, 23, 42, 0.45); display: flex; align-items: center; justify-content: center; z-index: 60; padding: 16px; }
.modal { background: var(--surface); border-radius: 16px; padding: 22px 24px; width: 560px; max-width: 100%; max-height: 90vh; overflow: auto; }
.modal.small { width: 440px; }
.modal h2 { font-size: 16px; margin-bottom: 8px; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin: 14px 0; }
.form-grid label, .full { display: flex; flex-direction: column; gap: 6px; font-size: 12.5px; color: var(--ink-2); }
.full-row { grid-column: 1 / -1; }
.full { margin: 0 0 10px; }
.form-grid input, .form-grid select, .full textarea { padding: 8px 10px; border: 1px solid var(--line); border-radius: 8px; font-size: 13px; }
.upload-row { display: flex; align-items: center; gap: 10px; margin-bottom: 6px; }
.file-btn { cursor: pointer; display: inline-block; }
.modal-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 16px; }
.check { display: flex; align-items: center; gap: 6px; font-size: 13px; margin-top: 6px; }
.mode-tabs { display: flex; gap: 8px; margin: 10px 0 2px; }
.mode-tab { padding: 6px 16px; border-radius: 999px; border: 1px solid var(--line); background: var(--surface); font-size: 12.5px; cursor: pointer; color: var(--ink-3); }
.mode-tab.active { background: linear-gradient(135deg, #6366f1, #06b6d4); color: #fff; border-color: transparent; font-weight: 600; }
.trial-chip { font-size: 10px; font-weight: 700; padding: 1px 7px; border-radius: 999px; background: linear-gradient(135deg, #fef3c7, #fde68a); color: #92400e; }
.link-list { display: flex; flex-direction: column; gap: 8px; margin-top: 8px; max-height: 260px; overflow: auto; }
.link-item { display: flex; align-items: center; gap: 10px; padding: 9px 12px; border: 1px solid var(--line); border-radius: 10px; font-size: 13px; cursor: pointer; }
.link-item.sel { border-color: #6366f1; background: #eef2ff; }
.img-overlay { z-index: 80; }
.preview { max-width: 90vw; max-height: 90vh; border-radius: 12px; }
</style>
