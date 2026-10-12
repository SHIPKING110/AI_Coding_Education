<script setup lang="ts">
/**
 * 权限管理（管理员）：
 * - 按教师设置：左侧选人，右侧按模块开关（默认见各键默认值；关闭后教师端点击弹提示且后端 403）
 * - 职务预设：维护职务及其默认权限；新建教师选职务即套用，换职务自动切换，一键应用/追溯同步到教师
 * 硬性规则不受开关影响：教师只能操作本人所带班级；只有空班级才能删除。
 */
import { computed, onMounted, ref } from 'vue'

import PageHead from '@/components/PageHead.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import { listCampusesApi } from '@/api/auth'
import {
  applyTitleToTeacher,
  createJobTitle,
  deleteJobTitle,
  listJobTitles,
  listPermissionKeys,
  listTeacherPermissions,
  syncTitleToTeachers,
  updateJobTitle,
  updateTeacherPermissions,
  type JobTitle,
  type PermissionKey,
  type TeacherPermissionRow,
} from '@/api/permissions'

const tab = ref<'teachers' | 'titles'>('teachers')

const keys = ref<PermissionKey[]>([])
const rows = ref<TeacherPermissionRow[]>([])
const campuses = ref<string[]>([])
const keyword = ref('')
const campusFilter = ref('')
const titleFilter = ref('')
const loading = ref(false)
const error = ref('')
const savingId = ref('')
const selectedId = ref('')

/** 按模块分组展示权限键（标签形如“学员管理-新增学员”） */
const keyGroups = computed(() => {
  const groups: { module: string; items: PermissionKey[] }[] = []
  for (const k of keys.value) {
    const [module, ...rest] = k.label.split('-')
    const label = rest.join('-') || k.label
    let g = groups.find((x) => x.module === module)
    if (!g) {
      g = { module, items: [] }
      groups.push(g)
    }
    g.items.push({ key: k.key, label })
  }
  return groups
})

const filtered = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  return rows.value.filter((r) => {
    if (kw && !(r.teacher_name.toLowerCase().includes(kw) || r.username.toLowerCase().includes(kw)))
      return false
    if (campusFilter.value && (r.campus || '') !== campusFilter.value) return false
    if (titleFilter.value === '__none__' && r.title) return false
    if (titleFilter.value && titleFilter.value !== '__none__' && (r.title || '') !== titleFilter.value)
      return false
    return true
  })
})

/** 校区筛选选项：以业务校区表顺序为准（设置模块可调），教师历史字符串兜底追加 */
const campusOptions = computed(() => {
  const ordered = campuses.value.length ? [...campuses.value] : []
  const seen = new Set(ordered)
  for (const r of rows.value) {
    if (r.campus && !seen.has(r.campus)) {
      seen.add(r.campus)
      ordered.push(r.campus)
    }
  }
  return ordered
})
const titleOptions = computed(() => {
  const set = new Set<string>()
  for (const r of rows.value) if (r.title) set.add(r.title)
  for (const t of titles.value) set.add(t.name)
  return [...set].sort()
})

const selected = computed(
  () => rows.value.find((r) => r.teacher_id === selectedId.value) || null,
)

function isOn(row: TeacherPermissionRow | null, key: string): boolean {
  if (!row) return false
  return row.permissions[key] !== false
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    keys.value = await listPermissionKeys()
    rows.value = await listTeacherPermissions()
    titles.value = await listJobTitles()
    try {
      campuses.value = await listCampusesApi()
    } catch {
      campuses.value = []
    }
    if (!selectedId.value && rows.value.length) selectedId.value = rows.value[0].teacher_id
  } catch {
    error.value = '加载失败，请稍后重试'
  } finally {
    loading.value = false
  }
}

async function toggle(row: TeacherPermissionRow | null, key: string, value: boolean) {
  if (!row) return
  savingId.value = `${row.teacher_id}:${key}`
  try {
    const updated = await updateTeacherPermissions(row.teacher_id, { [key]: value })
    const i = rows.value.findIndex((r) => r.teacher_id === row.teacher_id)
    if (i >= 0) rows.value[i] = updated
  } catch {
    error.value = `保存「${row.teacher_name}」的权限失败`
  } finally {
    savingId.value = ''
  }
}

/** 一键套用职务到当前选中教师 */
const quickTitle = ref('')
const quickMsg = ref('')
async function quickApply() {
  if (!selected.value || !quickTitle.value) return
  try {
    const updated = await applyTitleToTeacher(selected.value.teacher_id, quickTitle.value)
    const i = rows.value.findIndex((r) => r.teacher_id === updated.teacher_id)
    if (i >= 0) rows.value[i] = updated
    quickMsg.value = `已应用「${quickTitle.value}」`
  } catch (e: any) {
    quickMsg.value = e?.response?.data?.detail || '应用失败'
  }
}

// —— 职务预设 ——
const titles = ref<JobTitle[]>([])
const editingTitle = ref<JobTitle | null>(null)
const titleName = ref('')
const titleSalary = ref('')
const titlePerms = ref<Record<string, boolean>>({})
const titleSaving = ref(false)
const titleError = ref('')
const showTitleForm = ref(false)

function openTitleCreate() {
  editingTitle.value = null
  titleName.value = ''
  titleSalary.value = ''
  titlePerms.value = Object.fromEntries(keys.value.map((k) => [k.key, true]))
  titleError.value = ''
  showTitleForm.value = true
}

function openTitleEdit(t: JobTitle) {
  editingTitle.value = t
  titleName.value = t.name
  titleSalary.value = t.base_salary || ''
  titlePerms.value = Object.fromEntries(keys.value.map((k) => [k.key, t.permissions[k.key] !== false]))
  titleError.value = ''
  showTitleForm.value = true
}

async function saveTitle() {
  if (!titleName.value.trim()) {
    titleError.value = '请填写职务名称'
    return
  }
  titleSaving.value = true
  titleError.value = ''
  try {
    if (editingTitle.value) {
      await updateJobTitle(editingTitle.value.id, { name: titleName.value.trim(), permissions: { ...titlePerms.value }, base_salary: titleSalary.value || '0' })
    } else {
      await createJobTitle({ name: titleName.value.trim(), permissions: { ...titlePerms.value }, base_salary: titleSalary.value || '0' })
    }
    showTitleForm.value = false
    // 双向互通：职务改完即刷新两边数据；若有在职教师正在用该职务，自动弹出同步确认，一键追溯
    const savedName = titleName.value.trim()
    titles.value = await listJobTitles()
    rows.value = await listTeacherPermissions()
    const affected = rows.value.filter((r) => r.title === savedName).length
    const saved = titles.value.find((t) => t.name === savedName) || null
    syncMsg.value = ''
    if (saved && affected > 0) syncTarget.value = saved
    else if (saved) syncMsg.value = `职务「${savedName}」已保存，暂无在职教师使用`
  } catch (e: any) {
    titleError.value = e?.response?.data?.detail || '保存职务失败'
  } finally {
    titleSaving.value = false
  }
}

const delTitle = ref<JobTitle | null>(null)
async function confirmDelTitle() {
  if (!delTitle.value) return
  try {
    await deleteJobTitle(delTitle.value.id)
    delTitle.value = null
    titles.value = await listJobTitles()
  } catch (e: any) {
    error.value = e?.response?.data?.detail || '删除职务失败'
  }
}

// 追溯同步：职务改权限后一键同步到所有同职务在职教师
const syncTarget = ref<JobTitle | null>(null)
const syncCount = computed(() =>
  syncTarget.value ? rows.value.filter((r) => r.title === syncTarget.value!.name).length : 0,
)
const syncMsg = ref('')
async function confirmSync() {
  if (!syncTarget.value) return
  try {
    const res = await syncTitleToTeachers(syncTarget.value.id)
    syncMsg.value = `「${res.title}」已同步到 ${res.synced} 名教师`
    syncTarget.value = null
    rows.value = await listTeacherPermissions()
  } catch (e: any) {
    error.value = e?.response?.data?.detail || '同步失败'
    syncTarget.value = null
  }
}

// 一键应用职务到教师（底部快捷区）
const applyTeacherId = ref('')
const applyTitleName = ref('')
const applyMsg = ref('')

/** 职务预设 ↔ 教师个人互通：教师当前权限与所挂职务预设不一致即视为偏离 */
function presetOf(titleName: string | null | undefined): JobTitle | null {
  if (!titleName) return null
  return titles.value.find((t) => t.name === titleName) || null
}
function isDiverged(row: TeacherPermissionRow): boolean {
  const preset = presetOf(row.title)
  if (!preset) return false
  const perms = preset.permissions || {}
  return Object.keys(perms).some((k) => (row.permissions[k] ?? true) !== !!perms[k])
}
function titleUserCount(t: JobTitle): number {
  return rows.value.filter((r) => r.title === t.name).length
}
function titleDivergedCount(t: JobTitle): number {
  return rows.value.filter((r) => r.title === t.name && isDiverged(r)).length
}
const CARD_ACCENTS = ['#2f6fed', '#0e9f6e', '#c2570b', '#7c3aed', '#0284c7', '#be123c']
function titleOnCount(t: JobTitle): number {
  return keys.value.filter((k) => t.permissions[k.key] !== false).length
}
function titleOnPct(t: JobTitle): number {
  if (!keys.value.length) return 0
  return Math.round((titleOnCount(t) / keys.value.length) * 100)
}
async function applyTitle() {
  if (!applyTeacherId.value || !applyTitleName.value) {
    applyMsg.value = '请选择教师与职务'
    return
  }
  try {
    const updated = await applyTitleToTeacher(applyTeacherId.value, applyTitleName.value)
    const i = rows.value.findIndex((r) => r.teacher_id === updated.teacher_id)
    if (i >= 0) rows.value[i] = updated
    applyMsg.value = `已将「${applyTitleName.value}」应用到「${updated.teacher_name}」`
  } catch (e: any) {
    applyMsg.value = e?.response?.data?.detail || '应用失败'
  }
}

onMounted(load)
</script>

<template>
  <div>
    <PageHead title="权限管理" eyebrow="PERMISSIONS">
      <template #sub>
        左侧选教师、右侧按模块开关 · 无权限点击弹提示 ·
        教师始终只能操作本人所带班级，且只有空班级才能删除（硬性规则）
      </template>
      <template #actions>
      <div class="tabs">
        <button :class="{ active: tab === 'teachers' }" @click="tab = 'teachers'">
          按教师设置<em>{{ rows.length }}</em>
        </button>
        <button :class="{ active: tab === 'titles' }" @click="tab = 'titles'">
          职务预设<em>{{ titles.length }}</em>
        </button>
      </div>
      </template>
    </PageHead>

    <p v-if="error" class="perm-error">{{ error }}</p>
    <p v-if="loading" class="muted">加载中…</p>

    <template v-else>
      <!-- 按教师设置：左侧选人 + 右侧模块开关 -->
      <div v-if="tab === 'teachers'" class="master-detail">
        <aside class="teacher-list">
          <div class="search-box">
            <input v-model="keyword" placeholder="搜索教师姓名 / 用户名" />
          </div>
          <div class="filter-row">
            <select v-model="campusFilter" title="按校区筛选">
              <option value="">全部校区</option>
              <option v-for="c in campusOptions" :key="c" :value="c">{{ c }}</option>
            </select>
            <select v-model="titleFilter" title="按职务筛选">
              <option value="">全部职务</option>
              <option v-for="t in titleOptions" :key="t" :value="t">{{ t }}</option>
              <option value="__none__">未设职务</option>
            </select>
          </div>
          <button
            v-for="r in filtered"
            :key="r.teacher_id"
            class="teacher-item"
            :class="{ active: r.teacher_id === selectedId }"
            @click="selectedId = r.teacher_id; quickMsg = ''; quickTitle = ''"
          >
            <span class="avatar">{{ r.teacher_name.slice(0, 1) }}</span>
            <span class="t-info">
              <strong>{{ r.teacher_name }}</strong>
              <small>{{ r.username }}<template v-if="r.campus"> · {{ r.campus }}</template></small>
            </span>
            <span v-if="r.title" class="t-title">{{ r.title }}</span>
            <span v-if="isDiverged(r)" class="t-diverged" title="该教师的个人权限与职务预设不一致（单独调整过）">偏离预设</span>
            <span class="t-count">{{ Object.values(r.permissions).filter((v) => v !== false).length }}/{{ keys.length }}</span>
          </button>
          <p v-if="filtered.length === 0" class="muted" style="padding: 8px 4px">暂无教师</p>
        </aside>

        <section v-if="selected" class="perm-panel">
          <div class="panel-head">
            <div>
              <div class="eyebrow">当前设置对象</div>
              <strong class="panel-name">{{ selected.teacher_name }}</strong>
              <span v-if="selected.title" class="t-title big">{{ selected.title }}</span>
              <span v-if="isDiverged(selected)" class="t-diverged big" title="个人权限与职务预设不一致；用职务卡片「同步」可一键对齐">偏离预设</span>
              <span class="muted">{{ selected.username }}<template v-if="selected.campus"> · {{ selected.campus }}</template></span>
            </div>
            <div class="quick-apply">
              <select v-model="quickTitle">
                <option value="">套用职务预设…</option>
                <option v-for="t in titles" :key="t.id" :value="t.name">{{ t.name }}</option>
              </select>
              <button class="btn primary sm" :disabled="!quickTitle" @click="quickApply">一键套用</button>
            </div>
          </div>
          <p v-if="quickMsg" class="muted">{{ quickMsg }}</p>
          <div v-for="g in keyGroups" :key="g.module" class="module-card">
            <div class="module-title">
              <span class="module-dot" />
              {{ g.module }}
              <small>{{ g.items.filter((k) => isOn(selected, k.key)).length }}/{{ g.items.length }} 开启</small>
            </div>
            <p v-if="g.module === '设置'" class="module-hint">
              教师端看到「设置」入口需要同时开启「设置-全部设置管理」与「导航可见-设置」；子 tab（个性化/模型/业务）再按需单独开。权限管理入口仅管理员可见，不受开关影响。
            </p>
            <p v-if="g.module === '财务管理'" class="module-hint">
              教师端看到「财务管理」入口需要同时开启「财务管理-可见」与「导航可见-财务管理」；板块内按钮再按创收/流水/薪资键控制。
            </p>
            <div class="switch-grid">
              <div v-for="k in g.items" :key="k.key" class="switch-row" :class="{ off: !isOn(selected, k.key) }">
                <span>{{ k.label }}</span>
                <button
                  class="switch"
                  :class="{ on: isOn(selected, k.key) }"
                  :disabled="savingId === `${selected.teacher_id}:${k.key}`"
                  :title="isOn(selected, k.key) ? '点击关闭' : '点击开启'"
                  @click="toggle(selected, k.key, !isOn(selected, k.key))"
                >
                  <i />
                </button>
              </div>
            </div>
          </div>
        </section>
        <section v-else class="perm-panel empty-panel">
          <p class="muted">暂无教师</p>
        </section>
      </div>

      <!-- 职务预设 -->
      <div v-else>
        <div class="title-actions">
          <p class="muted">新建教师选职务即套用预设权限；教师换职务自动切换；改完预设可用「同步」追溯到所有同职务在职教师。</p>
          <button class="btn primary" @click="openTitleCreate">新建职务</button>
        </div>
        <p v-if="syncMsg" class="done-msg">{{ syncMsg }}</p>
        <div class="title-grid">
          <div
            v-for="(t, ti) in titles"
            :key="t.id"
            class="title-card"
            :style="{ '--card-accent': CARD_ACCENTS[ti % CARD_ACCENTS.length] }"
          >
            <div class="title-top">
              <span class="title-badge">{{ t.name.slice(0, 1) }}</span>
              <div class="title-ops">
                <button class="op-btn" @click="syncTarget = t">同步</button>
                <button class="op-btn" @click="openTitleEdit(t)">编辑</button>
                <button class="op-btn danger" @click="delTitle = t">删除</button>
              </div>
            </div>
            <div class="eyebrow">职务</div>
            <strong class="title-name">{{ t.name }}</strong>
            <div class="title-salary">基本工资 ¥{{ Number(t.base_salary || 0).toLocaleString('zh-CN') }}/月</div>
            <div class="title-stat">
              <div class="title-bar"><i :style="{ width: `${titleOnPct(t)}%` }" /></div>
              <span>{{ titleOnCount(t) }}/{{ keys.length }} 开启</span>
            </div>
            <div class="title-usage">
              在用 {{ titleUserCount(t) }} 人<template v-if="titleDivergedCount(t)"> · {{ titleDivergedCount(t) }} 人偏离预设</template>
            </div>
            <div class="title-perms">
              <span v-for="k in keys" :key="k.key" class="perm-tag" :class="{ off: t.permissions[k.key] === false }">
                {{ k.label }}
              </span>
            </div>
          </div>
          <div v-if="titles.length === 0" class="empty-card">暂无职务预设，点击右上新建（如：主教 / 助教 / 班主任）</div>
        </div>

        <div class="apply-card">
          <h3>一键应用职务到教师</h3>
          <div class="apply-row">
            <select v-model="applyTeacherId">
              <option value="">选择教师</option>
              <option v-for="r in rows" :key="r.teacher_id" :value="r.teacher_id">
                {{ r.teacher_name }}（{{ r.username }}）
              </option>
            </select>
            <select v-model="applyTitleName">
              <option value="">选择职务</option>
              <option v-for="t in titles" :key="t.id" :value="t.name">{{ t.name }}</option>
            </select>
            <button class="btn primary" @click="applyTitle">应用</button>
          </div>
          <p v-if="applyMsg" class="muted">{{ applyMsg }}</p>
        </div>
      </div>
    </template>

    <!-- 职务编辑弹窗 -->
    <div v-if="showTitleForm" class="overlay" @click.self="showTitleForm = false">
      <div class="modal wide">
        <h2>{{ editingTitle ? '编辑职务' : '新建职务' }}</h2>
        <label>
          职务名称 *
          <input v-model="titleName" type="text" placeholder="如：主教 / 助教 / 班主任" />
        </label>
        <label>
          基本工资（元/月，用于薪资核算）
          <input v-model="titleSalary" type="number" min="0" step="100" placeholder="如：5000" />
        </label>
        <div v-for="g in keyGroups" :key="g.module" class="form-group">
          <div class="form-group-title">{{ g.module }}</div>
          <p v-if="g.module === '设置' || g.module === '财务管理'" class="module-hint">
            教师端入口需“功能开关 + 导航可见”同时开启（设置：全部设置管理＋导航可见-设置；财务：财务管理-可见＋导航可见-财务管理）。
          </p>
          <label v-for="k in g.items" :key="k.key" class="check-row">
            <input v-model="titlePerms[k.key]" type="checkbox" />
            <span>{{ k.label }}</span>
          </label>
        </div>
        <p v-if="titleError" class="perm-error">{{ titleError }}</p>
        <div class="modal-actions">
          <button class="btn ghost" @click="showTitleForm = false">取消</button>
          <button class="btn primary" :disabled="titleSaving" @click="saveTitle">
            {{ titleSaving ? '保存中…' : '保存' }}
          </button>
        </div>
      </div>
    </div>

    <ConfirmDialog
      :visible="!!delTitle"
      title="删除职务"
      :message="`确认删除职务「${delTitle?.name}」？仍被人员使用时不可删除，需先调整人员职务。`"
      confirm-text="删除"
      danger
      @confirm="confirmDelTitle"
      @cancel="delTitle = null"
    />
    <ConfirmDialog
      :visible="!!syncTarget"
      title="同步职务权限"
      :message="`将「${syncTarget?.name}」的当前预设权限同步到${syncCount} 名在职同职务教师？会覆盖这些教师的个人单独调整，不可撤销。`"
      confirm-text="确认同步"
      @confirm="confirmSync"
      @cancel="syncTarget = null"
    />
  </div>
</template>

<style scoped>
.page-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 20px;
  gap: 12px;
}
h1 {
  font-size: 22px;
}
.page-sub {
  color: var(--ink-3);
  font-size: 13px;
  margin-top: 4px;
  max-width: 640px;
}
.tabs {
  display: flex;
  gap: 8px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 5px;
  box-shadow: var(--shadow-sm);
}
.tabs button {
  border: none;
  background: transparent;
  padding: 9px 18px;
  border-radius: 9px;
  font-size: 13.5px;
  font-weight: 600;
  color: var(--ink-3);
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 8px;
}
.tabs button em {
  font-style: normal;
  font-size: 11.5px;
  font-weight: 700;
  background: var(--bg-soft);
  color: var(--ink-2);
  border-radius: 999px;
  padding: 1px 8px;
}
.tabs button.active {
  background: var(--ink);
  color: #fff;
}
.tabs button.active em {
  background: rgba(255, 255, 255, 0.2);
  color: #fff;
}
.perm-error {
  color: var(--danger);
  background: var(--danger-soft);
  border-radius: 8px;
  padding: 8px 12px;
  font-size: 13px;
  margin-bottom: 12px;
}
.done-msg {
  color: #047857;
  background: #e0fbe9;
  border-radius: 8px;
  padding: 8px 12px;
  font-size: 13px;
  margin-bottom: 12px;
}
.muted {
  color: var(--ink-3);
  font-size: 13px;
}
.eyebrow {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
  color: var(--ink-light);
  text-transform: uppercase;
  margin-bottom: 2px;
}

/* —— 左侧选人 + 右侧开关 —— */
.master-detail {
  display: grid;
  grid-template-columns: 300px 1fr;
  gap: 14px;
  align-items: start;
}
.teacher-list {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: calc(100vh - 220px);
  overflow: auto;
  box-shadow: var(--shadow-sm);
}
.search-box input {
  width: 100%;
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 9px 12px;
  font-size: 13px;
  background: var(--surface);
  color: var(--ink);
  margin-bottom: 4px;
}
.filter-row {
  display: flex;
  gap: 8px;
  margin-bottom: 8px;
}
.filter-row select {
  flex: 1;
  min-width: 0;
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 8px 6px;
  font-size: 12.5px;
  background: var(--surface);
  color: var(--ink-2);
  font-weight: 600;
}
.teacher-item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  text-align: left;
  border: 1px solid transparent;
  background: transparent;
  border-radius: 12px;
  padding: 9px 10px;
  cursor: pointer;
}
.teacher-item:hover {
  background: var(--bg-soft);
}
.teacher-item.active {
  background: var(--ink);
  color: #fff;
}
.teacher-item.active .t-info small {
  color: rgba(255, 255, 255, 0.65);
}
.teacher-item .avatar {
  width: 34px;
  height: 34px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 10px;
  background: var(--brand-soft);
  color: var(--brand-strong);
  font-weight: 700;
  font-size: 15px;
}
.teacher-item.active .avatar {
  background: rgba(255, 255, 255, 0.16);
  color: #fff;
}
.t-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.t-info strong {
  font-size: 13.5px;
}
.t-title {
  flex-shrink: 0;
  font-size: 10.5px;
  font-weight: 700;
  padding: 2px 7px;
  border-radius: 999px;
  background: #fef3c7;
  color: #92400e;
}
.teacher-item.active .t-title {
  background: rgba(255, 255, 255, 0.2);
  color: #fff;
}
.t-title.big {
  font-size: 11.5px;
  padding: 3px 10px;
  margin-left: 8px;
  vertical-align: 2px;
}
.t-diverged {
  flex-shrink: 0;
  font-size: 10.5px;
  font-weight: 700;
  padding: 2px 7px;
  border-radius: 999px;
  background: #fee2e2;
  color: #b91c1c;
}
.t-diverged.big {
  font-size: 11.5px;
  padding: 3px 10px;
  margin-left: 6px;
  vertical-align: 2px;
}
.title-usage {
  font-size: 12px;
  color: var(--ink-3);
  font-weight: 600;
  margin: 2px 0 8px;
}
.module-hint {
  font-size: 12px;
  color: var(--ink-3);
  background: var(--bg-soft);
  border-radius: 8px;
  padding: 7px 10px;
  margin: -2px 0 10px;
}
.t-info small {
  color: var(--ink-3);
  font-size: 11.5px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.t-count {
  font-size: 11px;
  font-weight: 700;
  color: var(--ink-3);
  background: var(--bg-soft);
  border-radius: 999px;
  padding: 2px 8px;
  flex-shrink: 0;
}
.teacher-item.active .t-count {
  background: rgba(255, 255, 255, 0.16);
  color: #fff;
}
.perm-panel {
  min-width: 0;
}
.panel-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: 12px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 14px 18px;
  margin-bottom: 12px;
  box-shadow: var(--shadow-sm);
}
.panel-name {
  font-size: 18px;
}
.quick-apply {
  display: flex;
  gap: 8px;
}
.quick-apply select {
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 8px 12px;
  font-size: 13px;
  background: var(--surface);
  color: var(--ink);
}
.btn.sm {
  padding: 8px 14px;
  font-size: 13px;
}
.module-card {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 14px 18px;
  margin-bottom: 12px;
  box-shadow: var(--shadow-sm);
}
.module-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14.5px;
  font-weight: 700;
  margin-bottom: 10px;
}
.module-dot {
  width: 9px;
  height: 9px;
  border-radius: 3px;
  background: var(--brand);
}
.module-title small {
  margin-left: auto;
  font-size: 11.5px;
  font-weight: 600;
  color: var(--ink-3);
}
.switch-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 8px;
}
.switch-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 9px 12px;
  border-radius: 10px;
  background: var(--bg-soft);
  font-size: 13px;
  font-weight: 500;
}
.switch-row.off {
  opacity: 0.75;
}
.switch {
  width: 40px;
  height: 22px;
  flex-shrink: 0;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: #cbd5e1;
  position: relative;
  cursor: pointer;
  transition: background 0.15s;
  padding: 0;
}
.switch i {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: #fff;
  transition: left 0.15s;
}
.switch.on {
  background: var(--brand-strong);
  border-color: var(--brand-strong);
}
.switch.on i {
  left: 20px;
}
.switch:disabled {
  opacity: 0.5;
  cursor: wait;
}
.empty-panel {
  background: var(--surface);
  border: 1px dashed var(--line);
  border-radius: 14px;
  padding: 40px;
  text-align: center;
}

/* —— 职务预设 —— */
.title-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 14px;
  gap: 12px;
}
.title-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}
.title-card {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 16px;
  padding: 18px;
  border-top: 4px solid var(--card-accent, var(--brand));
  box-shadow: var(--shadow-sm);
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.title-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.title-badge {
  width: 40px;
  height: 40px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  font-weight: 800;
  color: #fff;
  background: var(--card-accent, var(--brand));
}
.title-name {
  font-size: 17px;
}
.title-stat {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 8px 0 10px;
  font-size: 12px;
  color: var(--ink-3);
  font-weight: 600;
}
.title-bar {
  flex: 1;
  height: 6px;
  border-radius: 999px;
  background: var(--line-soft);
  overflow: hidden;
}
.title-bar i {
  display: block;
  height: 100%;
  border-radius: 999px;
  background: var(--card-accent, var(--brand));
}
.title-ops {
  display: flex;
  gap: 4px;
  flex-shrink: 0;
}
.op-btn {
  border: none;
  background: none;
  color: var(--brand);
  cursor: pointer;
  font-size: 13px;
  font-weight: 500;
  padding: 4px 6px;
}
.op-btn:hover {
  text-decoration: underline;
}
.op-btn.danger {
  color: var(--danger);
}
.title-perms {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.perm-tag {
  font-size: 11.5px;
  padding: 3px 10px;
  border-radius: 999px;
  background: var(--brand-soft);
  color: var(--brand-strong);
  font-weight: 600;
}
.perm-tag.off {
  background: var(--bg-soft);
  color: var(--ink-light);
  text-decoration: line-through;
}
.apply-card {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 16px 18px;
  box-shadow: var(--shadow-sm);
}
.apply-card h3 {
  font-size: 15px;
  margin-bottom: 10px;
}
.apply-row {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
.apply-row select {
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 9px 12px;
  font-size: 13.5px;
  background: var(--surface);
  color: var(--ink);
  min-width: 180px;
}
.overlay {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 50;
}
.modal {
  width: 440px;
  max-width: calc(100vw - 40px);
  max-height: calc(100vh - 80px);
  overflow: auto;
  background: var(--surface);
  border-radius: 16px;
  padding: 22px;
}
.modal.wide {
  width: 560px;
}
.modal h2 {
  font-size: 17px;
  margin-bottom: 14px;
}
.modal label {
  display: block;
  margin-bottom: 12px;
  font-size: 13px;
  color: var(--ink-2);
}
.modal input[type='text'] {
  width: 100%;
  margin-top: 4px;
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 9px 12px;
  font-size: 13.5px;
  background: var(--surface);
  color: var(--ink);
}
.form-group {
  margin: 12px 0;
  border-top: 1px solid var(--line);
  padding-top: 10px;
}
.form-group-title {
  font-size: 13px;
  font-weight: 700;
  margin-bottom: 6px;
}
.check-row {
  display: flex !important;
  flex-direction: row !important;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px !important;
  cursor: pointer;
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 14px;
}
.empty-card {
  background: var(--surface);
  border: 1px dashed var(--line);
  border-radius: 14px;
  padding: 24px;
  text-align: center;
  color: var(--ink-3);
  font-size: 13.5px;
  grid-column: 1 / -1;
}
</style>
