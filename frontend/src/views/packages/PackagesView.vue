<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import PageHead from '@/components/PageHead.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import PaginationBar from '@/components/PaginationBar.vue'
import {
  createPackage,
  deletePackage,
  listPackages,
  updatePackage,
  type LessonPackageCreate,
  type LessonPackageOut,
  type LessonPackageUpdate,
} from '@/api/enrollment'
import { listSubjects, type SubjectOut } from '@/api/business'
import { myPermissions } from '@/api/permissions'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()

// 课时包权限：管理员全开；教师按 package_create / package_off（后端兜底 403）
const myPerms = ref<Record<string, boolean>>({})
const canDo = computed(() => (key: string) => {
  if (auth.user?.role !== 'teacher') return true
  return myPerms.value[key] === true
})
const showNoPerm = ref(false)
const noPermText = ref('')
function guard(key: string, label: string, action: () => void) {
  if (canDo.value(key)) action()
  else {
    noPermText.value = `暂无「${label}」权限，请联系管理员开通。`
    showNoPerm.value = true
  }
}

const packages = ref<LessonPackageOut[]>([])
const subjects = ref<SubjectOut[]>([])
const loading = ref(false)
const error = ref('')

// 筛选：科目 / 标签 / 售价范围
const filterSubject = ref('')
const filterTag = ref('')
const filterMin = ref('')
const filterMax = ref('')

// 分页
const page = ref(1)
const pageSize = 12
const total = ref(0)

// 新建/编辑表单
const showForm = ref(false)
const editing = ref<LessonPackageOut | null>(null)
const form = ref<{
  name: string
  price: string
  total_lessons: number
  subject_id: string
  tag: string
  sale_start: string
  sale_end: string
}>({ name: '', price: '', total_lessons: 0, subject_id: '', tag: 'regular', sale_start: '', sale_end: '' })
const formError = ref('')

function fmtDate(s: string | null): string {
  if (!s) return '—'
  const d = new Date(s)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const pageData = await listPackages(true, {
      limit: pageSize,
      offset: (page.value - 1) * pageSize,
      subject_id: filterSubject.value || undefined,
      tag: filterTag.value || undefined,
      price_min: filterMin.value || undefined,
      price_max: filterMax.value || undefined,
    })
    packages.value = pageData.items
    total.value = pageData.total
  } catch {
    error.value = '加载课时包失败'
  } finally {
    loading.value = false
  }
}

function onFilter() {
  page.value = 1
  load()
}

function onPageChange(p: number) {
  page.value = p
  load()
}

function toLocalInput(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function openCreate() {
  editing.value = null
  form.value = { name: '', price: '', total_lessons: 0, subject_id: '', tag: 'regular', sale_start: '', sale_end: '' }
  formError.value = ''
  showForm.value = true
}

function openEdit(p: LessonPackageOut) {
  editing.value = p
  form.value = {
    name: p.name,
    price: String(p.price),
    total_lessons: p.total_lessons,
    subject_id: p.subject_id || '',
    tag: p.tag || 'regular',
    sale_start: toLocalInput(p.sale_start),
    sale_end: toLocalInput(p.sale_end),
  }
  formError.value = ''
  showForm.value = true
}

async function submit() {
  formError.value = ''
  const price = Number(form.value.price)
  if (!form.value.name.trim() || !price || !form.value.total_lessons) {
    formError.value = '请填写名称、价格与课时数'
    return
  }
  if (form.value.tag === 'activity' && (!form.value.sale_start || !form.value.sale_end)) {
    formError.value = '活动课包需设置售卖时间范围'
    return
  }
  if (form.value.sale_start && form.value.sale_end && form.value.sale_start >= form.value.sale_end) {
    formError.value = '售卖开始时间须早于结束时间'
    return
  }
  const payload = {
    name: form.value.name.trim(),
    price: price.toFixed(2),
    total_lessons: form.value.total_lessons,
    subject_id: form.value.subject_id || null,
    subject_id_set: true,
    tag: form.value.tag,
    sale_start: form.value.sale_start ? new Date(form.value.sale_start).toISOString() : null,
    sale_end: form.value.sale_end ? new Date(form.value.sale_end).toISOString() : null,
  }
  try {
    if (editing.value) {
      await updatePackage(editing.value.id, payload as LessonPackageUpdate)
    } else {
      await createPackage(payload as LessonPackageCreate)
    }
    showForm.value = false
    await load()
  } catch (e: any) {
    formError.value = e?.response?.data?.detail || '保存失败'
  }
}

async function deactivate(p: LessonPackageOut) {
  askConfirm({
    title: '下架课时包',
    message: `确认下架课时包「${p.name}」？下架后家长端不再可订阅，历史订单不受影响。`,
    confirmText: '下架',
    danger: true,
    onConfirm: async () => {
      await deletePackage(p.id)
      await load()
    },
  })
}

// 下架确认（统一弹窗）
interface ConfirmAsk {
  visible: boolean
  title: string
  message: string
  confirmText: string
  danger: boolean
  onConfirm: () => Promise<void> | void
}
const confirmState = ref<ConfirmAsk>({
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
  onConfirm: () => Promise<void> | void
}) {
  confirmState.value = {
    visible: true,
    title: opts.title,
    message: opts.message,
    confirmText: opts.confirmText || '确认',
    danger: !!opts.danger,
    onConfirm: opts.onConfirm,
  }
}
async function runConfirm() {
  confirmState.value.visible = false
  await confirmState.value.onConfirm()
}

onMounted(async () => {
  if (auth.user?.role === 'teacher') {
    try {
      myPerms.value = await myPermissions()
    } catch {
      myPerms.value = {}
    }
  }
  try {
    subjects.value = await listSubjects()
  } catch {
    subjects.value = []
  }
  await load()
})
</script>

<template>
  <div>
    <PageHead
      title="课时包管理"
      eyebrow="PACKAGES"
      :sub="`共 ${total} 个课时方案 · 家长可在客户端订阅 · 管理员专属配置`"
    >
      <template #actions>
      <button class="btn primary" @click="guard('package_create', '新建课时包', openCreate)">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 5v14M5 12h14" /></svg>
        新建课时包
      </button>
      </template>
    </PageHead>

    <div class="filter-bar">
      <select v-model="filterSubject" class="filter-select" @change="onFilter">
        <option value="">全部科目</option>
        <option v-for="s in subjects" :key="s.id" :value="s.id">{{ s.name }}</option>
      </select>
      <select v-model="filterTag" class="filter-select" @change="onFilter">
        <option value="">全部类型</option>
        <option value="regular">常规课</option>
        <option value="activity">活动课</option>
      </select>
      <input v-model="filterMin" type="number" min="0" class="filter-input" placeholder="最低售价" @change="onFilter" />
      <span class="filter-sep">—</span>
      <input v-model="filterMax" type="number" min="0" class="filter-input" placeholder="最高售价" @change="onFilter" />
      <button
        v-if="filterSubject || filterTag || filterMin || filterMax"
        class="link-btn"
        @click="filterSubject = ''; filterTag = ''; filterMin = ''; filterMax = ''; onFilter()"
      >
        清除筛选
      </button>
    </div>

    <p v-if="error" class="error-banner">{{ error }}</p>

    <div class="card-grid">
      <div v-for="p in packages" :key="p.id" class="package-card" :class="{ inactive: p.status === 'inactive' }">
        <div class="card-head">
          <span class="tag-pill" :class="p.tag || 'regular'">{{ (p.tag || 'regular') === 'activity' ? '活动课' : '常规课' }}</span>
          <span class="status-pill" :class="p.status">{{ p.status === 'active' ? '在售' : '已下架' }}</span>
        </div>
        <h3 class="pkg-name">{{ p.name }}</h3>
        <div class="pkg-meta">
          <span v-if="p.subject_name" class="meta-chip">{{ p.subject_name }}</span>
          <span class="meta-text">发布 {{ fmtDate(p.published_at || p.created_at) }}</span>
          <span class="meta-text">{{ p.paid_students }} 人已购</span>
        </div>
        <div v-if="(p.tag || 'regular') === 'activity' && (p.sale_start || p.sale_end)" class="sale-range">
          售卖 {{ fmtDate(p.sale_start) }} ~ {{ fmtDate(p.sale_end) }}
        </div>
        <div class="price-row">
          <span class="price">¥{{ Number(p.price).toFixed(0) }}</span>
          <span class="unit">/ {{ p.total_lessons }} 课时</span>
        </div>
        <div class="unit-price">约 ¥{{ (Number(p.price) / p.total_lessons).toFixed(2) }} / 课时</div>
        <div class="card-ops">
          <button class="op-btn edit" @click="guard('package_edit', '编辑课时包', () => openEdit(p))">编辑</button>
          <button v-if="p.status === 'active'" class="op-btn danger" @click="guard('package_off', '下架课时包', () => deactivate(p))">下架</button>
          <span v-else class="inactive-note">已停售</span>
        </div>
      </div>

      <div v-if="!loading && packages.length === 0" class="empty-card">暂无课时包，点击右上角新建</div>
    </div>

    <PaginationBar :total="total" :page="page" :page-size="pageSize" @update:page="onPageChange" />

    <div v-if="showForm" class="overlay" @click.self="showForm = false">
      <div class="modal">
        <h2>{{ editing ? '编辑课时包' : '新建课时包' }}</h2>
        <p v-if="editing" class="modal-tip">已有支付订单的课包，售价与总课时将被锁定（后端校验）。</p>
        <label>
          名称 *
          <input v-model="form.name" type="text" placeholder="如：基础包 40 课时" />
        </label>
        <div class="row2">
          <label>
            价格（元）*
            <input v-model="form.price" type="number" min="0" step="0.01" />
          </label>
          <label>
            课时数 *
            <input v-model.number="form.total_lessons" type="number" min="1" />
          </label>
        </div>
        <div class="row2">
          <label>
            学科科目
            <select v-model="form.subject_id">
              <option value="">不指定</option>
              <option v-for="s in subjects" :key="s.id" :value="s.id">
                {{ s.name }}（{{ s.per_session }} 课时/次）
              </option>
            </select>
          </label>
          <label>
            课包标签
            <select v-model="form.tag">
              <option value="regular">常规课</option>
              <option value="activity">活动课</option>
            </select>
          </label>
        </div>
        <div v-if="form.tag === 'activity'" class="row2">
          <label>
            售卖开始 *
            <input v-model="form.sale_start" type="datetime-local" />
          </label>
          <label>
            售卖结束 *
            <input v-model="form.sale_end" type="datetime-local" />
          </label>
        </div>
        <p v-if="formError" class="error">{{ formError }}</p>
        <div class="modal-actions">
          <button class="btn ghost" @click="showForm = false">取消</button>
          <button class="btn primary" @click="submit">保存</button>
        </div>
      </div>
    </div>

    <!-- 下架确认 -->
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

.filter-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.filter-select,
.filter-input {
  padding: 8px 12px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--surface);
  font-size: 13px;
  color: var(--ink-2);
}
.filter-input {
  width: 110px;
}
.filter-sep {
  color: var(--ink-3);
}
.link-btn {
  border: none;
  background: none;
  color: var(--brand-strong);
  font-size: 13px;
  cursor: pointer;
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
  grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
  gap: 16px;
}
.package-card {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 16px;
  padding: 20px;
  position: relative;
  transition: all 0.18s;
  background: linear-gradient(160deg, #ffffff 0%, #f8fafc 100%);
}
.package-card:hover {
  transform: translateY(-3px);
  box-shadow: var(--shadow-md);
  border-color: #c7d2fe;
}
.package-card.inactive {
  opacity: 0.6;
  filter: grayscale(0.6);
}
.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
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
.status-pill.inactive {
  background: #f1f5f9;
  color: var(--ink-3);
}
.tag-pill {
  font-size: 11.5px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 999px;
  background: #eef2ff;
  color: var(--brand-strong);
}
.tag-pill.activity {
  background: #fef3c7;
  color: #b45309;
}
.pkg-name {
  font-size: 16px;
  color: var(--ink);
  margin-bottom: 8px;
}
.pkg-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 6px;
}
.meta-chip {
  font-size: 11.5px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 999px;
  background: var(--brand-soft);
  color: var(--brand-strong);
}
.meta-text {
  font-size: 12px;
  color: var(--ink-3);
}
.sale-range {
  font-size: 12px;
  color: #b45309;
  margin-bottom: 4px;
}
.price-row {
  display: flex;
  align-items: baseline;
  gap: 6px;
}
.price {
  font-size: 28px;
  font-weight: 800;
  color: var(--ink);
  background: linear-gradient(135deg, #6366f1, #06b6d4);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}
.unit {
  color: var(--ink-3);
  font-size: 13px;
}
.unit-price {
  color: var(--ink-3);
  font-size: 12.5px;
  margin-top: 4px;
}
.card-ops {
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px solid var(--line);
  display: flex;
  gap: 8px;
}
.op-btn {
  border: none;
  font-size: 12.5px;
  font-weight: 600;
  padding: 6px 14px;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.15s;
}
.op-btn.danger {
  background: var(--danger-soft);
  color: var(--danger);
}
.op-btn.danger:hover {
  background: var(--danger);
  color: #fff;
}
.op-btn.edit {
  background: var(--brand-soft);
  color: var(--brand-strong);
}
.op-btn.edit:hover {
  background: var(--brand);
  color: #fff;
}
.inactive-note {
  color: var(--ink-3);
  font-size: 12.5px;
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
  width: 480px;
  max-height: 88vh;
  overflow-y: auto;
  background: var(--surface);
  border-radius: 16px;
  padding: 26px;
  box-shadow: var(--shadow-lg);
}
.modal h2 {
  font-size: 18px;
  margin-bottom: 6px;
}
.modal-tip {
  font-size: 12.5px;
  color: var(--ink-3);
  margin-bottom: 14px;
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
  background: var(--surface);
  color: var(--ink);
  transition: all 0.15s;
}
.modal input:focus,
.modal select:focus {
  outline: none;
  border-color: var(--brand);
  box-shadow: 0 0 0 3px var(--brand-soft);
}
.row2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
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
