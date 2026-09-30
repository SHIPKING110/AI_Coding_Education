<script setup lang="ts">
/**
 * 学员选择器（跨端复用）：校区 / 教师 / 班级 / 学员 四级联动 + 可选「未绑定账号」筛选。
 *
 * 学员管理列表筛选、学员评估学员下拉、课堂作业发布学员选择三处共用同一份筛选逻辑，
 * 保证「选校区后教师只显示该校区教师、选教师后学员只显示其学员、未分配选项语义一致」。
 */
import { computed, reactive, ref, watch } from 'vue'

import { listCampusesApi, listTeachersApi, type UserOut } from '@/api/auth'
import { listClasses, listStudents, type ClassOut, type StudentOut } from '@/api/enrollment'

export interface StudentFilterValue {
  campus: string
  teacherId: string
  classId: string
  keyword: string
  /** ''=全部学员 / 'unbound_student'=未绑定学员账号 / 'unbound_parent'=未绑定家长账号 */
  account: '' | 'unbound_student' | 'unbound_parent'
}

const props = withDefaults(
  defineProps<{
    modelValue: StudentFilterValue
    /** 是否展示「未绑定账号」筛选（学员管理/缴费名单需要；评估/发布按需开启） */
    showAccountFilter?: boolean
    /** 校区下拉占位 */
    campusPlaceholder?: string
    /** 教师下拉占位 */
    teacherPlaceholder?: string
    /** 班级下拉占位 */
    classPlaceholder?: string
    /** 搜索框占位 */
    searchPlaceholder?: string
    /** 紧凑模式（发布弹窗内嵌使用） */
    compact?: boolean
  }>(),
  {
    showAccountFilter: false,
    campusPlaceholder: '全部校区',
    teacherPlaceholder: '全部教师',
    classPlaceholder: '全部班级',
    searchPlaceholder: '搜索学员姓名…',
    compact: false,
  },
)

const emit = defineEmits<{ 'update:modelValue': [value: StudentFilterValue] }>()

const campuses = ref<string[]>([])
const teachers = ref<UserOut[]>([])
const classes = ref<ClassOut[]>([])
const students = ref<StudentOut[]>([])
const studentLoading = ref(false)
const loaded = ref(false)

// —— 本地 v-model 代理：任何一级变化都向上传递完整值 ——
const value = reactive<StudentFilterValue>({
  campus: props.modelValue.campus ?? '',
  teacherId: props.modelValue.teacherId ?? '',
  classId: props.modelValue.classId ?? '',
  keyword: props.modelValue.keyword ?? '',
  account: props.modelValue.account ?? '',
})

watch(
  () => props.modelValue,
  (v) => {
    value.campus = v.campus ?? ''
    value.teacherId = v.teacherId ?? ''
    value.classId = v.classId ?? ''
    value.keyword = v.keyword ?? ''
    value.account = v.account ?? ''
  },
  { deep: true },
)

function push() {
  emit('update:modelValue', { ...value })
}

async function loadStudents() {
  studentLoading.value = true
  try {
    const r = await listStudents({
      keyword: value.keyword.trim() || undefined,
      campus: value.campus && value.campus !== '__unassigned__' ? value.campus : undefined,
      campus_unassigned: value.campus === '__unassigned__' || undefined,
      teacher_id: value.teacherId && value.teacherId !== '__unassigned__' ? value.teacherId : undefined,
      teacher_unassigned: value.teacherId === '__unassigned__' || undefined,
      class_id: value.classId && value.classId !== '__unassigned__' ? value.classId : undefined,
      class_unassigned: value.classId === '__unassigned__' || undefined,
      account: value.account || undefined,
      limit: 500,
    })
    students.value = r.items
  } catch {
    students.value = []
  } finally {
    studentLoading.value = false
  }
}

/** 教师下拉：选校区后只显示该校区教师（含未分配选项由模板提供） */
const teacherOptions = computed(() => {
  if (!value.campus || value.campus === '__unassigned__') return teachers.value
  return teachers.value.filter((t) => t.campus === value.campus)
})

/** 班级下拉：选教师后只显示其所带班级；选校区后只显示该校区教师的班级 */
const classOptions = computed(() => {
  let pool = classes.value
  if (value.teacherId && value.teacherId !== '__unassigned__') {
    pool = pool.filter((c) => c.teacher_id === value.teacherId)
  } else if (value.teacherId === '__unassigned__') {
    pool = pool.filter((c) => !c.teacher_id)
  } else if (value.campus && value.campus !== '__unassigned__') {
    const ids = new Set(teachers.value.filter((t) => t.campus === value.campus).map((t) => t.id))
    pool = pool.filter((c) => (c.teacher_id && ids.has(c.teacher_id)) || selectedClassKept.value.has(c.id))
  }
  return pool
})

/** 已选班级（不在当前联动结果中也保留，避免切换筛选时丢失选择） */
const selectedClassKept = ref<Set<string>>(new Set())

function onCampusChange() {
  if (value.teacherId && value.teacherId !== '__unassigned__' && !teacherOptions.value.some((t) => t.id === value.teacherId)) {
    value.teacherId = ''
  }
  if (value.classId && !classOptions.value.some((c) => c.id === value.classId)) {
    selectedClassKept.value.add(value.classId)
  }
  push()
  void loadStudents()
}

function onTeacherChange() {
  if (value.classId && !classOptions.value.some((c) => c.id === value.classId)) {
    selectedClassKept.value.add(value.classId)
  }
  push()
  void loadStudents()
}

function onClassChange() {
  if (value.classId) selectedClassKept.value.delete(value.classId)
  push()
  void loadStudents()
}

let timer: ReturnType<typeof setTimeout> | null = null
function onKeywordInput() {
  if (timer) clearTimeout(timer)
  timer = setTimeout(() => {
    timer = null
    push()
    void loadStudents()
  }, 300)
}

function reset() {
  value.campus = ''
  value.teacherId = ''
  value.classId = ''
  value.keyword = ''
  value.account = ''
  selectedClassKept.value.clear()
  push()
}

async function bootstrap() {
  if (loaded.value) return
  loaded.value = true
  try {
    campuses.value = await listCampusesApi().catch(() => [] as string[])
    const t = await listTeachersApi({ limit: 500, include_inactive: true }).catch(() => ({ items: [] as UserOut[] }))
    teachers.value = t.items ?? []
    const c = await listClasses({ limit: 500 }).catch(() => ({ items: [] as ClassOut[] }))
    classes.value = c.items ?? []
  } catch {
    campuses.value = []
    teachers.value = []
    classes.value = []
  }
}

defineExpose({ reset, bootstrap, classOptions, teacherOptions, students, loadStudents })

bootstrap()
void loadStudents()
</script>

<template>
  <div class="stu-filter" :class="{ compact }">
    <select v-model="value.campus" class="filter-input" @change="onCampusChange">
      <option value="">{{ campusPlaceholder }}</option>
      <option value="__unassigned__">未分配</option>
      <option v-for="c in campuses" :key="c" :value="c">{{ c }}</option>
    </select>
    <select v-model="value.teacherId" class="filter-input" :title="`选择校区后仅显示该校区教师`" @change="onTeacherChange">
      <option value="">{{ teacherPlaceholder }}</option>
      <option value="__unassigned__">未分配教师</option>
      <option v-for="t in teacherOptions" :key="t.id" :value="t.id">
        {{ t.name }}<template v-if="t.campus">（{{ t.campus }}）</template>
      </option>
    </select>
    <select v-model="value.classId" class="filter-input grow" :title="`选择教师后仅显示其所带班级`" @change="onClassChange">
      <option value="">{{ classPlaceholder }}</option>
      <option value="__unassigned__">未分配班级</option>
      <option v-for="c in classOptions" :key="c.id" :value="c.id">
        {{ c.name }}（{{ c.subject }}）{{ c.teacher_name ? ` · ${c.teacher_name}` : '' }}
      </option>
    </select>
    <input v-model="value.keyword" class="filter-input grow" type="text" :placeholder="searchPlaceholder" @input="onKeywordInput" />
    <select v-if="showAccountFilter" v-model="value.account" class="filter-input" title="按账号绑定情况筛选学员" @change="push(); loadStudents()">
      <option value="">全部学员</option>
      <option value="unbound_student">未绑定学员账号</option>
      <option value="unbound_parent">未绑定家长账号</option>
    </select>
    <select v-if="students.length || studentLoading" class="student-result" :disabled="studentLoading" title="当前筛选结果中的学员">
      <option>{{ studentLoading ? '学员加载中…' : `当前匹配 ${students.length} 名学员` }}</option>
    </select>
  </div>
</template>

<style scoped>
.stu-filter {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  align-items: center;
  margin-bottom: 12px;
}
.stu-filter.compact {
  margin-bottom: 8px;
}
.filter-input {
  padding: 8px 10px;
  border: 1px solid var(--line);
  border-radius: 9px;
  font-size: 13px;
  background: var(--surface);
  color: var(--ink-2);
}
.filter-input.grow {
  flex: 1;
  min-width: 140px;
}
.filter-input:focus {
  outline: none;
  border-color: var(--brand);
  box-shadow: 0 0 0 3px var(--brand-soft);
}
.student-result {
  padding: 8px 10px;
  border: 1px solid var(--line);
  border-radius: 9px;
  font-size: 13px;
  background: var(--bg);
  color: var(--ink-3);
}
</style>
