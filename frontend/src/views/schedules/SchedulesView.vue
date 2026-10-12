<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import SearchableSelect from '@/components/SearchableSelect.vue'
import PageHead from '@/components/PageHead.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'

import {
  cancelSchedule,
  createRecurringSchedules,
  createSchedule,
  listSchedules,
  type ConflictOut,
  type RecurringSlotIn,
  type ScheduleOut,
} from '@/api/schedule'
import { listClasses, type ClassOut } from '@/api/enrollment'
import { listCampusesApi, listTeachersApi, type UserOut } from '@/api/auth'
import { myPermissions } from '@/api/permissions'
import { useAuthStore } from '@/stores/auth'
import {
  addDays,
  dayKey,
  dayKeyFromIso,
  fmtHMFromIso,
  mondayOf,
  parseServerTime,
  toLocalNaiveIso,
  today,
  weekdayName,
} from '@/utils/date'

const router = useRouter()
const auth = useAuthStore()

// 新建排课权限：管理员/教务全开；教师按权限管理配置（后端兜底 403）
const myPerms = ref<Record<string, boolean>>({})
const canCreate = computed(() => {
  if (auth.user?.role !== 'teacher') return true
  return myPerms.value.schedule_create === true
})
// 取消排课权限：默认关闭，按需开通（后端同样校验 + 有考勤记录时禁止取消）
const canCancel = computed(() => {
  if (auth.user?.role !== 'teacher') return true
  return myPerms.value.schedule_cancel === true
})
const showNoPerm = ref(false)
const noPermText = ref('暂无新建排课权限，请联系管理员开通。')

const schedules = ref<ScheduleOut[]>([])
const teachers = ref<UserOut[]>([])
const campuses = ref<string[]>([])
const loading = ref(false)
const error = ref('')

// ---------- 校区 / 教师 / 科目筛选 ----------
const campusFilter = ref('')
const teacherFilter = ref('')
const subjectFilter = ref('')

const subjectOptions = computed(() => {
  const set = new Set<string>()
  for (const s of schedules.value) if (s.subject) set.add(s.subject)
  return [...set].sort()
})

async function loadTeachers() {
  const pageData = await listTeachersApi({
    campus: campusFilter.value || undefined,
    limit: 500,
  })
  teachers.value = pageData.items
}

// 切换校区：联动刷新教师下拉 + 课表
watch(campusFilter, async () => {
  teacherFilter.value = ''
  await loadTeachers()
  load()
})

// 切换教师：刷新课表
watch(teacherFilter, () => {
  load()
})

// ---------- 周视图导航（相对当前周，可无限前后翻） ----------
const weekStart = ref<Date>(mondayOf(today()))
const weekEnd = computed(() => addDays(weekStart.value, 6))

function prevWeek() {
  weekStart.value = addDays(weekStart.value, -7)
}
function nextWeek() {
  weekStart.value = addDays(weekStart.value, 7)
}
function goToday() {
  weekStart.value = mondayOf(today())
}

// 切换周时自动重新拉取该周课表，无需手动点刷新
watch(weekStart, () => {
  load()
})

const scheduleByDay = computed(() => {
  const map: Record<string, ScheduleOut[]> = {}
  for (const s of schedules.value) {
    if (subjectFilter.value && s.subject !== subjectFilter.value) continue
    const key = dayKeyFromIso(s.start_time)
    if (!map[key]) map[key] = []
    map[key].push(s)
  }
  return map
})

// ---------- 时间刻度课表（8:00 - 22:00，按实际时间垂直对齐；同时段多节=课组收起/展开） ----------
const HOUR_START = 8
const HOUR_END = 22
const HOUR_H = 48
const PX_PER_MIN = HOUR_H / 60
const TIMELINE_H = (HOUR_END - HOUR_START) * HOUR_H
const MIN_H = 30
const GAP = 3
const HEADER_H = 44 // 课组头部高度（收起态最小高度=头部高度，收起态实际高度≥时间跨度，保证刻度对齐）

function startMin(s: ScheduleOut): number {
  const d = parseServerTime(s.start_time)
  return d.getHours() * 60 + d.getMinutes()
}
function endMin(s: ScheduleOut): number {
  const d = parseServerTime(s.end_time)
  return d.getHours() * 60 + d.getMinutes()
}

// 展开中的「课组」id 集合（同一天同时段多节合并为一个课组）
const expandedGroups = ref<Set<string>>(new Set())

function toggleGroup(gid: string) {
  const next = new Set(expandedGroups.value)
  if (next.has(gid)) next.delete(gid)
  else next.add(gid)
  expandedGroups.value = next
}

interface ChildCell {
  s: ScheduleOut
  height: number
}
interface GroupCell {
  kind: 'group'
  gid: string
  collapsed: boolean
  top: number
  height: number
  left: number
  width: number
  count: number
  children: ChildCell[]
}
interface SingleCell {
  kind: 'single'
  s: ScheduleOut
  top: number
  height: number
  left: number
  width: number
}
type TimelineCell = SingleCell | GroupCell

function groupIdOf(list: ScheduleOut[]): string {
  return [...list]
    .map((x) => x.id)
    .sort()
    .join(',')
}

/** 同日同时段重叠的排课合并为「课组」；展开时垂直向下堆叠并让下方刻度下移 */
function layoutTimeline(list: ScheduleOut[]): TimelineCell[] {
  const sorted = [...list].sort(
    (a, b) => startMin(a) - startMin(b) || endMin(a) - endMin(b),
  )
  // 重叠连通分量分组
  const clusters: ScheduleOut[][] = []
  for (const s of sorted) {
    const st = startMin(s)
    const en = endMin(s)
    let placed = false
    for (const cl of clusters) {
      if (cl.some((it) => st < endMin(it) && startMin(it) < en)) {
        cl.push(s)
        placed = true
        break
      }
    }
    if (!placed) clusters.push([s])
  }

  const cells: TimelineCell[] = []
  let cursorY = 0 // 已占用最低点：展开的课组会把它往下推，保证不压到后面刻度
  for (const cl of clusters) {
    const sortedCl = [...cl].sort((a, b) => startMin(a) - startMin(b) || endMin(a) - endMin(b))
    const minSt = startMin(sortedCl[0])
    const nominalTop = Math.max(0, (minSt - HOUR_START * 60) * PX_PER_MIN)
    const top = Math.max(nominalTop, cursorY)

    if (cl.length === 1) {
      const s = sortedCl[0]
      const height = Math.max((endMin(s) - startMin(s)) * PX_PER_MIN, MIN_H)
      cells.push({ kind: 'single', s, top, height, left: 0, width: 100 })
      cursorY = top + height + GAP
      continue
    }

    // 课组
    const gid = groupIdOf(sortedCl)
    const collapsed = !expandedGroups.value.has(gid)
    const children: ChildCell[] = []
    for (const s of sortedCl) {
      const h = Math.max((endMin(s) - startMin(s)) * PX_PER_MIN, MIN_H)
      children.push({ s, height: h })
    }
    // 课组覆盖的真实时间跨度（最早开始 → 最晚结束），收起态高度按此对齐刻度
    const spanEnd = Math.max(...sortedCl.map((s) => endMin(s)))
    let height: number
    if (collapsed) {
      // 收起态：高度 = 真实时间跨度，与单节排课同口径（顶部对齐最早开始、底部对齐最晚结束）
      height = Math.max((spanEnd - minSt) * PX_PER_MIN, HEADER_H)
    } else {
      // 展开态：头部 + 各排课纵向堆叠（含堆叠区上边距 3px）
      height =
        HEADER_H +
        3 +
        children.reduce((acc, c) => acc + c.height, 0) +
        GAP * (children.length - 1)
    }
    cells.push({
      kind: 'group',
      gid,
      collapsed,
      top,
      height,
      left: 0,
      width: 100,
      count: sortedCl.length,
      children,
    })
    cursorY = top + height + GAP
  }
  return cells
}

const timelineByDay = computed(() => {
  const map: Record<string, TimelineCell[]> = {}
  for (const key of Object.keys(scheduleByDay.value)) {
    map[key] = layoutTimeline(scheduleByDay.value[key])
  }
  return map
})

// 课组展开后当天刻度向下延长（各列统一取最高底部，保持跨列水平对齐）
const maxDayBottom = computed(() => {
  let m = TIMELINE_H
  for (const key of Object.keys(timelineByDay.value)) {
    for (const c of timelineByDay.value[key]) {
      m = Math.max(m, c.top + c.height)
    }
  }
  return m + 12
})

const hourMarks = computed(() => {
  const n = Math.ceil(maxDayBottom.value / HOUR_H)
  const res: number[] = []
  for (let h = HOUR_START; h < HOUR_START + n; h++) res.push(h)
  return res
})

const weekDays = computed(() => {
  const names = ['一', '二', '三', '四', '五', '六', '日']
  const days: { key: string; label: string; dow: string; isToday: boolean }[] = []
  for (let i = 0; i < 7; i++) {
    const d = addDays(weekStart.value, i)
    days.push({
      key: dayKey(d),
      label: `${d.getMonth() + 1}/${d.getDate()}`,
      dow: `周${names[i]}`,
      isToday: dayKey(d) === dayKey(today()),
    })
  }
  return days
})

function fmtRange(s: ScheduleOut): string {
  return `${fmtHMFromIso(s.start_time)}–${fmtHMFromIso(s.end_time)}`
}

function fmtMin(min: number): string {
  const h = Math.floor(min / 60)
  const m = min % 60
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`
}

/** 课组副标题：展示课组覆盖的完整时间区间（最早开始–最晚结束），与收起态卡片高度一致 */
function groupTitleText(children: { s: ScheduleOut }[]): string {
  if (!children.length) return ''
  const min = Math.min(...children.map((c) => startMin(c.s)))
  const max = Math.max(...children.map((c) => endMin(c.s)))
  return `${fmtMin(min)}–${fmtMin(max)}`
}

// ---------- 新建排课弹窗 ----------
const showForm = ref(false)
const prevStartDate = ref('')
const mode = ref<'single' | 'recurring'>('single')

// 单次排课
const single = ref({ class_id: '', teacher_id: '', date: dayKey(today()), time: '09:00', duration_min: 90 })
// 循环排课
const recurring = ref({
  class_id: '',
  teacher_id: '',
  start_date: dayKey(today()),
  total_lessons: 10,
  slots: [] as { weekday: number; start_time: string; duration_min: number }[],
})
const formError = ref('')
const submitting = ref(false)

// 新建排课表单：校区筛选（联动教师/班级）
const formCampus = ref('')
const formTeachers = ref<UserOut[]>([])
const formClasses = ref<ClassOut[]>([])
const formLoading = ref(false)

const formTeacherOptions = computed(() =>
  formTeachers.value.map((t) => ({
    id: t.id,
    label: t.name + (t.campus ? `（${t.campus}）` : ''),
  })),
)

// 班级候选：优先 = 所选教师带教的班级；未选教师但有校区 = 该校区的教师带教的班级
const formClassOptions = computed(() => {
  let list = formClasses.value
  const tid =
    mode.value === 'single' ? single.value.teacher_id : recurring.value.teacher_id
  if (tid) {
    list = list.filter((c) => c.teacher_id === tid)
  } else if (formCampus.value) {
    const campusTids = new Set(
      formTeachers.value.filter((t) => t.campus === formCampus.value).map((t) => t.id),
    )
    list = list.filter((c) => c.teacher_id && campusTids.has(c.teacher_id))
  }
  return list.map((c) => ({ id: c.id, label: `${c.name}（${c.subject}）` }))
})

async function loadFormData() {
  formLoading.value = true
  try {
    const [teachersPage, classesPage] = await Promise.all([
      listTeachersApi({ campus: formCampus.value || undefined, limit: 500 }),
      listClasses({ campus: formCampus.value || undefined, limit: 500 }),
    ])
    formTeachers.value = teachersPage.items
    formClasses.value = classesPage.items
  } finally {
    formLoading.value = false
  }
}

// 切换校区：清空已选教师/班级并重新加载联动数据
watch(formCampus, async () => {
  if (mode.value === 'single') {
    single.value.teacher_id = ''
    single.value.class_id = ''
  } else {
    recurring.value.teacher_id = ''
    recurring.value.class_id = ''
  }
  await loadFormData()
})

// 切换教师：清空已选班级（班级候选联动到该教师带教的班级）
function onFormTeacherChange(tid: string) {
  if (mode.value === 'single') {
    single.value.teacher_id = tid
    single.value.class_id = ''
  } else {
    recurring.value.teacher_id = tid
    recurring.value.class_id = ''
  }
}

function onFormClassChange(cid: string) {
  if (mode.value === 'single') single.value.class_id = cid
  else recurring.value.class_id = cid
}

// 冲突确认弹窗
const showConflict = ref(false)
const conflictTitle = ref('')
const conflicts = ref<ConflictOut[]>([])

async function load() {
  loading.value = true
  error.value = ''
  try {
    schedules.value = await listSchedules({
      start: toLocalNaiveIso(weekStart.value),
      end: toLocalNaiveIso(addDays(weekEnd.value, 1)),
      campus: campusFilter.value || undefined,
      teacher_id: teacherFilter.value || undefined,
    })
  } catch {
    error.value = '加载排课失败'
  } finally {
    loading.value = false
  }
}

function openCreate() {
  mode.value = 'single'
  formCampus.value = ''
  single.value = { class_id: '', teacher_id: '', date: dayKey(today()), time: '09:00', duration_min: 90 }
  recurring.value = {
    class_id: '',
    teacher_id: '',
    start_date: dayKey(today()),
    total_lessons: 10,
    slots: [{ weekday: today().getDay() === 0 ? 7 : today().getDay(), start_time: '09:00', duration_min: 90 }],
  }
  prevStartDate.value = recurring.value.start_date
  formError.value = ''
  showForm.value = true
  loadFormData()
}

function isoWeekday(dateStr: string): number {
  const d = new Date(`${dateStr}T00:00:00`).getDay()
  return d === 0 ? 7 : d
}

// 起始日期联动星期：只跟随“还没被手动改过”的时段（即星期等于旧起始日期星期的时段）
function onStartDateChange() {
  const r = recurring.value
  if (!r.start_date) return
  const oldW = prevStartDate.value ? isoWeekday(prevStartDate.value) : -1
  const newW = isoWeekday(r.start_date)
  for (const s of r.slots) {
    if (s.weekday === oldW) s.weekday = newW
  }
  prevStartDate.value = r.start_date
}

function addSlot() {
  if (recurring.value.slots.length >= 7) return
  recurring.value.slots.push({ weekday: 1, start_time: '09:00', duration_min: 90 })
}
function removeSlot(i: number) {
  recurring.value.slots.splice(i, 1)
}

async function submit() {
  formError.value = ''
  if (mode.value === 'single') {
    await submitSingle()
  } else {
    await submitRecurring()
  }
}

async function submitSingle() {
  if (!single.value.teacher_id) {
    formError.value = '请选择教师（班级可空，不选即教师空余时段体验课）'
    return
  }
  const start = new Date(`${single.value.date}T${single.value.time}:00`)
  const end = addMinutesSafe(start, single.value.duration_min)
  submitting.value = true
  try {
    const result = await createSchedule({
      class_id: single.value.class_id || null,
      teacher_id: single.value.teacher_id,
      start_time: toLocalNaiveIso(start),
      end_time: toLocalNaiveIso(end),
    })
    if (!result.created && result.conflicts.length > 0) {
      conflicts.value = result.conflicts
      conflictTitle.value = `时间冲突（${teachers.value.find((t) => t.id === single.value.teacher_id)?.name || ''}，同教师或同班同时段）`
      showConflict.value = true
      return
    }
    showForm.value = false
    await load()
  } catch (e: any) {
    formError.value = e?.response?.data?.detail || '创建排课失败'
  } finally {
    submitting.value = false
  }
}

async function submitRecurring() {
  const r = recurring.value
  if (!r.class_id || !r.teacher_id) {
    formError.value = '请选择班级和教师'
    return
  }
  if (r.slots.length === 0) {
    formError.value = '请至少添加一个时间段'
    return
  }
  if (!r.total_lessons || r.total_lessons <= 0) {
    formError.value = '请填写总节数'
    return
  }
  submitting.value = true
  try {
    const slots: RecurringSlotIn[] = r.slots.map((s) => ({
      weekday: s.weekday,
      start_time: s.start_time,
      duration_min: s.duration_min,
    }))
    const result = await createRecurringSchedules({
      class_id: r.class_id,
      teacher_id: r.teacher_id,
      start_date: r.start_date,
      slots,
      total_lessons: r.total_lessons,
    })
    if (!result.created && result.conflicts.length > 0) {
      conflicts.value = result.conflicts
      conflictTitle.value = `循环排课存在时间冲突（教师 ${teachers.value.find((t) => t.id === r.teacher_id)?.name || ''}）`
      showConflict.value = true
      return
    }
    showForm.value = false
    await load()
  } catch (e: any) {
    formError.value = e?.response?.data?.detail || '创建循环排课失败'
  } finally {
    submitting.value = false
  }
}

function addMinutesSafe(d: Date, minutes: number): Date {
  return new Date(d.getTime() + minutes * 60000)
}

function closeConflict() {
  showConflict.value = false
  showForm.value = true
}

async function removeSchedule(s: ScheduleOut) {
  if (!canCancel.value) {
    noPermText.value = '暂无取消排课权限，请联系管理员开通。'
    showNoPerm.value = true
    return
  }
  cancelTarget.value = s
  showCancel.value = true
}
const cancelTarget = ref<ScheduleOut | null>(null)
const showCancel = ref(false)
async function confirmCancel() {
  if (!cancelTarget.value) return
  showCancel.value = false
  try {
    await cancelSchedule(cancelTarget.value.id)
    await load()
  } catch (e: any) {
    error.value = e?.response?.data?.detail || '取消排课失败'
  }
}

function goDetail(id: string) {
  router.push({ name: 'schedule-detail', params: { id } })
}

function statusLabel(status: string): string {
  const map: Record<string, string> = {
    scheduled: '待上课',
    completed: '已完成',
    cancelled: '已取消',
  }
  return map[status] || status
}

function previewWeeks(): string {
  const r = recurring.value
  const perWeek = r.slots.length
  if (!perWeek || !r.start_date) return '—'
  // 与后端 _generate_recurring 同口径：从起始周起按星期推进，跳过起始日之前的日期
  const startDate = new Date(`${r.start_date}T00:00:00`)
  const monday = new Date(startDate)
  monday.setDate(monday.getDate() - (isoWeekday(r.start_date) - 1))
  const slotsSorted = [...r.slots].sort((a, b) => a.weekday - b.weekday)
  let count = 0
  let weekNo = 0
  let last: Date | null = null
  while (count < r.total_lessons && weekNo < 520) {
    for (const s of slotsSorted) {
      if (count >= r.total_lessons) break
      const day = new Date(monday)
      day.setDate(day.getDate() + weekNo * 7 + (s.weekday - 1))
      if (day < startDate) continue
      last = day
      count++
    }
    weekNo++
  }
  const weeks = Math.ceil(r.total_lessons / perWeek)
  const lastText = last ? `${last.getMonth() + 1}月${last.getDate()}日` : '—'
  return `每周 ${perWeek} 节 × ${weeks} 周，约至 ${lastText}`
}

onMounted(async () => {
  const campusList = await listCampusesApi()
  campuses.value = campusList
  if (auth.user?.role === 'teacher') {
    try {
      myPerms.value = await myPermissions()
    } catch {
      myPerms.value = {}
    }
  }
  await loadTeachers()
  await load()
})
</script>

<template>
  <div>
    <PageHead title="排课与考勤" eyebrow="SCHEDULES" sub="周课表 · 同一教师时间冲突自动检测 · 支持每周多节循环排课">
      <template #actions>
      <div class="head-actions">
        <button class="btn primary" @click="canCreate ? openCreate() : (noPermText = '暂无新建排课权限，请联系管理员开通。', showNoPerm = true)">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 5v14M5 12h14" /></svg>
          新建排课
        </button>
      </div>
      </template>
    </PageHead>

    <div class="toolbar">
      <div class="week-nav">
        <button class="icon-btn" @click="prevWeek">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 12H5M12 19l-7-7 7-7" /></svg>
        </button>
        <span class="week-label">
          {{ dayKey(weekStart) }} 至 {{ dayKey(weekEnd) }}
        </span>
        <button class="icon-btn" @click="nextWeek">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M12 5l7 7-7 7" /></svg>
        </button>
        <button class="today-btn" @click="goToday">今天</button>
      </div>

      <div class="filter-group">
        <select v-model="campusFilter" class="filter-select" title="按校区筛选课表">
          <option value="">全部校区</option>
          <option v-for="c in campuses" :key="c" :value="c">{{ c }}</option>
        </select>
        <select v-model="teacherFilter" class="filter-select" title="按教师筛选课表">
          <option value="">全部教师</option>
          <option v-for="t in teachers" :key="t.id" :value="t.id">
            {{ t.name }}{{ t.campus ? `（${t.campus}）` : '' }}
          </option>
        </select>
        <select v-model="subjectFilter" class="filter-select" title="按科目筛选课表">
          <option value="">全部科目</option>
          <option v-for="s in subjectOptions" :key="s" :value="s">{{ s }}</option>
        </select>
      </div>

      <button class="btn ghost" @click="load">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-2.64-6.36M21 3v6h-6" /></svg>
        刷新
      </button>
    </div>

    <p v-if="error" class="error-banner">{{ error }}</p>

    <div class="week-timetable">
      <div class="tt-axis-head"></div>
      <div v-for="d in weekDays" :key="'h' + d.key" class="day-head" :class="{ today: d.isToday }">
        <span class="dow" :class="{ 'today-dot': d.isToday }">{{ d.dow }}</span>
        <span class="date">{{ d.label }}</span>
      </div>

      <div class="tt-axis" :style="{ height: maxDayBottom + 'px' }">
        <div
          v-for="h in hourMarks"
          :key="h"
          class="axis-mark"
          :style="{ top: (h - HOUR_START) * HOUR_H - 8 + 'px' }"
        >
          {{ h }}:00
        </div>
      </div>

      <div
        v-for="d in weekDays"
        :key="d.key"
        class="day-body"
        :class="{ today: d.isToday }"
        :style="{ height: maxDayBottom + 'px' }"
      >
        <div
          v-for="h in hourMarks"
          :key="'gl' + h"
          class="hour-line"
          :style="{ top: (h - HOUR_START) * HOUR_H + 'px' }"
        ></div>
        <template v-if="timelineByDay[d.key]?.length">
          <div
            v-for="card in timelineByDay[d.key]"
            :key="card.kind === 'single' ? 's' + card.s.id : 'g' + card.gid"
            class="sched-card"
            :class="card.kind === 'single' ? card.s.status : 'group-cell'"
            :style="{
              top: card.top + 'px',
              height: card.height + 'px',
              left: `calc(${card.left}% + 3px)`,
              width: `calc(${card.width}% - 6px)`,
            }"
            @click="card.kind === 'single' ? goDetail(card.s.id) : toggleGroup(card.gid)"
          >
            <template v-if="card.kind === 'single'">
              <div class="sched-time">{{ fmtRange(card.s) }}</div>
              <div class="sched-class">{{ card.s.class_name || '体验课（无班级）' }}</div>
              <div class="sched-meta">
                <span v-if="card.s.subject" class="pill">{{ card.s.subject }}</span>
                <span v-if="card.s.is_trial" class="trial-chip">体验课</span>
                <span class="sched-teacher">{{ card.s.teacher_name || '未分配' }}</span>
              </div>
              <div class="sched-status" :class="card.s.status">{{ statusLabel(card.s.status) }}</div>
              <button
                v-if="card.s.status === 'scheduled'"
                class="sched-cancel"
                title="取消排课"
                @click.stop="removeSchedule(card.s)"
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M18 6 6 18M6 6l12 12" /></svg>
              </button>
            </template>

            <template v-else>
              <!-- 课组：头部始终可见（点击切换收起/展开），下方展开后纵向堆叠 -->
              <div class="group-header">
                <div class="group-count">{{ card.count }}</div>
                <div class="group-info">
                  <div class="group-label">
                    {{ card.collapsed ? `同时段 ${card.count} 节课 · 点击展开` : `同时段 ${card.count} 节课 · 点击收起` }}
                  </div>
                  <div class="group-cls">
                    {{ groupTitleText(card.children) }}
                  </div>
                </div>
                <svg
                  class="group-chev"
                  :class="{ open: !card.collapsed }"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="2"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                ><path d="M6 9l6 6 6-6" /></svg>
              </div>
              <!-- 课组收起态：下方留白展示真实时间跨度（与刻度对齐），斜纹提示可展开 -->
              <div v-if="card.collapsed" class="group-body">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6" /></svg>
              </div>
              <!-- 课组展开态：垂直堆叠 -->
              <div v-else class="group-expanded">
                <div
                  v-for="child in card.children"
                  :key="'c' + child.s.id"
                  class="group-child"
                  :class="child.s.status"
                  :style="{ height: child.height + 'px' }"
                  @click.stop="goDetail(child.s.id)"
                >
                  <div class="sched-time">{{ fmtRange(child.s) }}</div>
                  <div class="sched-class">{{ child.s.class_name || '体验课（无班级）' }}</div>
                  <div class="sched-meta">
                    <span v-if="child.s.subject" class="pill">{{ child.s.subject }}</span>
                    <span v-if="child.s.is_trial" class="trial-chip">体验课</span>
                    <span class="sched-teacher">{{ child.s.teacher_name || '未分配' }}</span>
                  </div>
                  <div class="sched-status" :class="child.s.status">{{ statusLabel(child.s.status) }}</div>
                  <button
                    v-if="child.s.status === 'scheduled'"
                    class="sched-cancel"
                    title="取消排课"
                    @click.stop="removeSchedule(child.s)"
                  >
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M18 6 6 18M6 6l12 12" /></svg>
                  </button>
                </div>
              </div>
            </template>
          </div>
        </template>
        <div v-else class="day-empty">—</div>
      </div>
    </div>

    <!-- 新建排课弹窗 -->
    <div v-if="showForm" class="overlay" @click.self="showForm = false">
      <div class="modal wide">
        <div class="mode-tabs">
          <button :class="['mode-tab', { active: mode === 'single' }]" @click="mode = 'single'">单次排课</button>
          <button :class="['mode-tab', { active: mode === 'recurring' }]" @click="mode = 'recurring'">
            每周循环排课
          </button>
        </div>

        <template v-if="mode === 'single'">
          <h2>新建单次排课</h2>
          <label>
            校区筛选（可空）
            <select v-model="formCampus">
              <option value="">全部校区</option>
              <option v-for="c in campuses" :key="c" :value="c">{{ c }}</option>
            </select>
          </label>
          <label>
            选择教师
            <SearchableSelect
              :model-value="single.teacher_id"
              :options="formTeacherOptions"
              placeholder="搜索选择教师…"
              @update:model-value="onFormTeacherChange"
            />
          </label>
          <label>
            选择班级
            <SearchableSelect
              :model-value="single.class_id"
              :options="formClassOptions"
              placeholder="仅显示所选教师的班级"
              @update:model-value="onFormClassChange"
            />
          </label>
          <div class="row">
            <label>
              日期
              <input v-model="single.date" type="date" />
            </label>
            <label>
              开始时间
              <input v-model="single.time" type="time" />
            </label>
            <label>
              时长（分钟）
              <input v-model.number="single.duration_min" type="number" min="30" step="30" />
            </label>
          </div>
        </template>

        <template v-else>
          <h2>每周循环排课</h2>
          <p class="muted">设置每周固定的上课时间段，系统将从起始周开始按周循环，直到排满总节数。</p>
          <label>
            校区筛选（可空）
            <select v-model="formCampus">
              <option value="">全部校区</option>
              <option v-for="c in campuses" :key="c" :value="c">{{ c }}</option>
            </select>
          </label>
          <label>
            选择教师
            <SearchableSelect
              :model-value="recurring.teacher_id"
              :options="formTeacherOptions"
              placeholder="搜索选择教师…"
              @update:model-value="onFormTeacherChange"
            />
          </label>
          <label>
            选择班级
            <SearchableSelect
              :model-value="recurring.class_id"
              :options="formClassOptions"
              placeholder="仅显示所选教师的班级"
              @update:model-value="onFormClassChange"
            />
          </label>
          <div class="row">
            <label>
              起始日期（从该周起）
              <input v-model="recurring.start_date" type="date" @change="onStartDateChange" />
            </label>
            <label>
              总节数
              <input v-model.number="recurring.total_lessons" type="number" min="1" />
            </label>
          </div>

          <div class="slot-head">
            <span>每周时间段（每周 {{ recurring.slots.length }} 节）</span>
            <button class="btn mini" :disabled="recurring.slots.length >= 7" @click="addSlot">+ 添加时间段</button>
          </div>
          <div v-for="(s, i) in recurring.slots" :key="i" class="slot-row">
            <select v-model="s.weekday">
              <option v-for="w in [1, 2, 3, 4, 5, 6, 7]" :key="w" :value="w">{{ weekdayName(w) }}</option>
            </select>
            <input v-model="s.start_time" type="time" />
            <input v-model.number="s.duration_min" type="number" min="30" step="30" title="时长(分钟)" />
            <button class="icon-btn danger" title="删除该时间段" @click="removeSlot(i)">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M18 6 6 18M6 6l12 12" /></svg>
            </button>
          </div>
          <p class="preview" v-if="recurring.slots.length">{{ previewWeeks() }}</p>
        </template>

        <p v-if="formError" class="error">{{ formError }}</p>
        <div class="modal-actions">
          <button class="btn ghost" @click="showForm = false">取消</button>
          <button class="btn primary" :disabled="submitting" @click="submit">
            {{ submitting ? '检测中…' : '检测并创建' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 冲突确认弹窗 -->
    <div v-if="showConflict" class="overlay">
      <div class="modal conflict-modal">
        <div class="warn-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 9v4M12 17h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" /></svg>
        </div>
        <h2>{{ conflictTitle }}</h2>
        <p class="muted">同一教师在以下时段已有排课，冲突时段不允许创建，请返回调整时间或更换教师。</p>
        <div class="conflict-list">
          <div v-for="c in conflicts" :key="c.id" class="conflict-item">
            <div class="conflict-main">
              <strong>{{ c.class_name || '未知班级' }}</strong>
              <span>{{ c.teacher_name || '未知教师' }}</span>
            </div>
            <span class="conflict-time">{{ fmtHMFromIso(c.start_time) }}–{{ fmtHMFromIso(c.end_time) }}</span>
          </div>
        </div>
        <div class="modal-actions">
          <button class="btn primary" @click="closeConflict">返回调整</button>
        </div>
      </div>
    </div>

    <!-- 无权限提示 -->
    <ConfirmDialog
      :visible="showNoPerm"
      title="暂无操作权限"
      :message="noPermText"
      confirm-text="知道了"
      @confirm="showNoPerm = false"
      @cancel="showNoPerm = false"
    />
    <!-- 取消排课确认 -->
    <ConfirmDialog
      :visible="showCancel"
      title="取消排课"
      :message="`确认取消「${cancelTarget?.class_name} · ${cancelTarget?.teacher_name}」这节课？取消后不可恢复。`"
      confirm-text="确认取消"
      danger
      @confirm="confirmCancel"
      @cancel="showCancel = false"
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
.btn.danger-solid {
  background: linear-gradient(135deg, #f97316, #ef4444);
  color: #fff;
}
.btn.mini {
  padding: 4px 10px;
  font-size: 12px;
  border: 1px solid var(--brand);
  color: var(--brand);
  background: var(--brand-soft);
  border-radius: 8px;
}
.btn.mini:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.btn:disabled {
  opacity: 0.6;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 18px;
  flex-wrap: wrap;
}
.filter-group {
  display: flex;
  align-items: center;
  gap: 8px;
}
.filter-select {
  padding: 7px 10px;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: var(--surface);
  font-size: 13px;
  color: var(--ink-2);
  cursor: pointer;
  transition: all 0.15s;
}
.filter-select:focus {
  outline: none;
  border-color: var(--brand);
  box-shadow: 0 0 0 3px var(--brand-soft);
}
.week-nav {
  display: flex;
  align-items: center;
  gap: 6px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 5px 8px;
  box-shadow: var(--shadow-sm);
}
.icon-btn {
  width: 30px;
  height: 30px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  background: transparent;
  color: var(--ink-3);
  border-radius: 8px;
  cursor: pointer;
}
.icon-btn:hover {
  background: var(--brand-soft);
  color: var(--brand);
}
.icon-btn svg {
  width: 16px;
  height: 16px;
}
.icon-btn.danger:hover {
  background: var(--danger-soft);
  color: var(--danger);
}
.week-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--ink-2);
  min-width: 160px;
  text-align: center;
}
.today-btn {
  border: none;
  background: var(--brand-soft);
  color: var(--brand-strong);
  font-size: 12px;
  font-weight: 600;
  padding: 4px 10px;
  border-radius: 8px;
  cursor: pointer;
}
.today-btn:hover {
  background: var(--brand);
  color: #fff;
}

.error-banner {
  background: var(--danger-soft);
  color: var(--danger);
  padding: 10px 14px;
  border-radius: 10px;
  margin-bottom: 16px;
  font-size: 13px;
}

.week-timetable {
  display: grid;
  grid-template-columns: 52px repeat(7, 1fr);
  grid-template-rows: auto auto;
  column-gap: 8px;
  row-gap: 0;
  overflow-x: auto;
  padding: 2px 4px 10px;
}
.tt-axis-head,
.day-head {
  background: var(--surface);
}
.tt-axis-head {
  border: 1px solid var(--line);
  border-radius: 14px 14px 0 0;
  border-bottom: none;
  background: var(--surface);
}
.day-head {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 10px 6px 8px;
  border: 1px solid var(--line);
  border-radius: 14px 14px 0 0;
  border-bottom: 2px solid var(--line);
}
.day-head.today {
  border-color: var(--brand);
}
.dow {
  font-size: 12px;
  color: var(--ink-3);
  position: relative;
}
.today-dot::after {
  content: '';
  position: absolute;
  width: 5px;
  height: 5px;
  background: var(--brand);
  border-radius: 50%;
  top: -2px;
  right: -10px;
}
.date {
  font-size: 17px;
  font-weight: 700;
  margin-top: 2px;
}
.day-head.today .date {
  color: var(--brand);
}

.tt-axis {
  position: relative;
  background: var(--surface);
  border: 1px solid var(--line);
  border-top: none;
  border-radius: 0 0 14px 14px;
}
.axis-mark {
  position: absolute;
  right: 6px;
  font-size: 11px;
  font-weight: 600;
  color: var(--ink-2);
  background: var(--surface);
  padding: 2px 5px;
  border-radius: 6px;
  line-height: 1.4;
  transform: translateY(-50%);
  white-space: nowrap;
}

.day-body {
  position: relative;
  border: 1px solid var(--line);
  border-top: none;
  border-radius: 0 0 14px 14px;
  background: var(--surface);
  overflow: hidden;
}
.day-body.today {
  border-color: var(--brand);
}
.day-body.today::after {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 2px;
  background: var(--brand);
}

/* 时间刻度网格 */
.hour-line {
  position: absolute;
  left: 0;
  right: 0;
  height: 1px;
  background: #eef2f7;
  pointer-events: none;
}

.day-empty {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--line);
  font-size: 18px;
  pointer-events: none;
}

.sched-card {
  position: absolute;
  border-radius: 8px;
  padding: 6px 8px;
  cursor: pointer;
  box-sizing: border-box;
  overflow: hidden;
  transition: all 0.15s;
  background: linear-gradient(135deg, #eef2ff, #f5f3ff);
  border: 1px solid #e0e7ff;
}
.sched-card:hover {
  z-index: 2;
  box-shadow: var(--shadow-md);
}
.sched-card.completed {
  background: #ecfdf5;
  border-color: #a7f3d0;
  opacity: 0.85;
}
.sched-card.cancelled {
  background: #f1f5f9;
  border-color: var(--line);
  opacity: 0.6;
}
.sched-time {
  font-size: 11px;
  font-weight: 700;
  color: var(--brand-strong);
  white-space: nowrap;
}
.sched-card.completed .sched-time {
  color: var(--success);
}
.sched-class {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--ink);
  margin-top: 2px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.sched-meta {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-top: 3px;
  font-size: 10px;
  white-space: nowrap;
  overflow: hidden;
}
.pill {
  background: var(--brand-soft);
  color: var(--brand-strong);
  padding: 1px 6px;
  border-radius: 999px;
  font-weight: 600;
  flex-shrink: 0;
}
.sched-teacher {
  color: var(--ink-3);
  overflow: hidden;
  text-overflow: ellipsis;
}
.trial-chip {
  font-size: 10px;
  font-weight: 700;
  padding: 1px 7px;
  border-radius: 999px;
  background: linear-gradient(135deg, #fef3c7, #fde68a);
  color: #92400e;
  flex-shrink: 0;
}
.sched-status {
  position: absolute;
  top: 5px;
  right: 6px;
  font-size: 9px;
  font-weight: 700;
  color: var(--brand-strong);
}
.sched-cancel {
  position: absolute;
  bottom: 4px;
  right: 4px;
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  background: var(--danger-soft);
  color: var(--danger);
  border-radius: 6px;
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.15s;
}
.sched-card:hover .sched-cancel {
  opacity: 1;
}
.sched-card:hover .sched-status {
  display: none;
}
.sched-cancel svg {
  width: 11px;
  height: 11px;
}

/* 课组：收起 / 展开 */
.sched-card.group-cell {
  background: linear-gradient(135deg, #fef3c7, #fde68a);
  border-color: #fcd34d;
  padding: 6px;
}
.group-cell.completed {
  opacity: 0.9;
}
.group-header {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 32px;
  cursor: pointer;
  border-radius: 8px;
  padding: 0 4px;
  user-select: none;
}
.group-count {
  display: flex;
  align-items: center;
  justify-content: center;
  min-width: 30px;
  height: 26px;
  padding: 0 6px;
  flex-shrink: 0;
  border-radius: 8px;
  background: linear-gradient(135deg, #f59e0b, #d97706);
  color: #fff;
  font-size: 15px;
  font-weight: 800;
}
.group-info {
  flex: 1;
  min-width: 0;
  line-height: 1.25;
}
.group-label {
  font-size: 11px;
  color: #b45309;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.group-cls {
  font-size: 11px;
  font-weight: 700;
  color: #92400e;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.group-chev {
  width: 15px;
  height: 15px;
  color: #b45309;
  flex-shrink: 0;
  transition: transform 0.15s;
}
.group-chev.open {
  transform: rotate(180deg);
}
/* 收起态下方留白：高度 = 真实时间跨度（对齐刻度），斜纹提示可展开 */
.group-body {
  position: absolute;
  left: 6px;
  right: 6px;
  top: 44px;
  bottom: 6px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: rgba(180, 83, 9, 0.55);
  background: repeating-linear-gradient(
    -45deg,
    rgba(255, 255, 255, 0.5) 0 7px,
    rgba(255, 255, 255, 0) 7px 14px
  );
  pointer-events: none;
}
.group-body svg {
  width: 16px;
  height: 16px;
  opacity: 0;
  transition: opacity 0.15s;
}
.sched-card.group-cell:hover .group-body svg {
  opacity: 1;
}
.group-cell:hover .group-header {
  background: rgba(245, 158, 11, 0.12);
}
.group-expanded {
  margin-top: 3px;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.group-child {
  display: flex;
  flex-direction: column;
  border-radius: 8px;
  padding: 5px 8px;
  box-sizing: border-box;
  background: #fff;
  border: 1px solid #e0e7ff;
  transition: all 0.15s;
  cursor: pointer;
  overflow: hidden;
}
.group-child:hover {
  box-shadow: var(--shadow-md);
}
.group-child.completed {
  background: #ecfdf5;
  border-color: #a7f3d0;
}
.group-child .sched-status {
  top: 4px;
  right: 6px;
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
.modal.wide {
  width: 560px;
}
.mode-tabs {
  display: flex;
  gap: 8px;
  background: #f1f5f9;
  border-radius: 10px;
  padding: 4px;
  margin-bottom: 18px;
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
.modal h2 {
  font-size: 17px;
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
.row {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 10px;
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

.slot-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin: 6px 0 10px;
  font-size: 13px;
  font-weight: 600;
  color: var(--ink-2);
}
.slot-row {
  display: grid;
  grid-template-columns: 90px 1fr 1fr 34px;
  gap: 8px;
  align-items: center;
  margin-bottom: 8px;
}
.slot-row select,
.slot-row input {
  margin-top: 0;
}
.preview {
  background: var(--brand-soft);
  color: var(--brand-strong);
  font-size: 12.5px;
  padding: 8px 12px;
  border-radius: 8px;
  margin-top: 4px;
}

.modal :deep(.ssel-trigger) {
  width: 100%;
  max-width: none;
}
.modal :deep(.ssel-drop) {
  z-index: 60;
  width: min(320px, calc(100% - 40px));
}
.form-loading-hint {
  font-size: 12px;
  color: var(--ink-3);
  margin: -6px 0 10px;
}

.conflict-modal {
  width: 460px;
}
.warn-icon {
  width: 48px;
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--warning-soft);
  color: var(--warning);
  border-radius: 12px;
  margin-bottom: 14px;
}
.warn-icon svg {
  width: 26px;
  height: 26px;
}
.conflict-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 200px;
  overflow: auto;
}
.conflict-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 12px;
  background: #fff7ed;
  border: 1px solid #fed7aa;
  border-radius: 10px;
  font-size: 13px;
}
.conflict-main {
  display: flex;
  flex-direction: column;
}
.conflict-main strong {
  color: var(--ink);
}
.conflict-main span {
  color: var(--ink-3);
  font-size: 12px;
}
.conflict-time {
  font-weight: 600;
  color: var(--warning);
}
</style>