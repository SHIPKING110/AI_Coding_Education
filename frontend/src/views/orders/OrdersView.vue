<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import PageHead from '@/components/PageHead.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import PaginationBar from '@/components/PaginationBar.vue'
import { cancelAdminOrder, confirmOrder, listAdminOrders, type OrderOut } from '@/api/client'
import { listPackages, type LessonPackageOut } from '@/api/enrollment'
import { listCampusesApi } from '@/api/auth'

const items = ref<OrderOut[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 12
const loading = ref(false)
const error = ref('')
const msg = ref('')

const statusFilter = ref('')
const keyword = ref('')
const campus = ref('')
const packageId = ref('')
const dateFrom = ref('')
const dateTo = ref('')
const packageOptions = ref<LessonPackageOut[]>([])
const campusOptions = ref<string[]>([])

const statusMap: Record<string, { label: string; cls: string }> = {
  pending: { label: '待支付', cls: 'pending' },
  paid: { label: '待确认到账', cls: 'paid' },
  confirmed: { label: '已到账', cls: 'confirmed' },
  cancelled: { label: '已取消', cls: 'cancelled' },
  refunded: { label: '已退款', cls: 'refunded' },
}

const statusTabs = [
  { key: '', label: '全部' },
  { key: 'pending', label: '待支付' },
  { key: 'paid', label: '待确认' },
  { key: 'confirmed', label: '已到账' },
  { key: 'cancelled', label: '已取消' },
  { key: 'refunded', label: '已退款' },
]

// 确认弹窗
const confirmVisible = ref(false)
const confirmTarget = ref<OrderOut | null>(null)
const confirmTitle = ref('')
const confirmText = ref('')
const confirmDanger = ref(false)

function openConfirm(o: OrderOut, action: 'confirm' | 'cancel') {
  confirmTarget.value = o
  if (action === 'confirm') {
    confirmTitle.value = '确认到账'
    confirmText.value = `确认「${o.student_name || '学员'}」的订单（${o.package_name || '课时包'}，¥${Number(o.amount).toFixed(2)}）已到账？课时将立即入账并通知家长。`
    confirmDanger.value = false
  } else {
    confirmTitle.value = '取消订单'
    confirmText.value = `确认取消该订单（${o.package_name || '课时包'}）？取消后不可恢复。`
    confirmDanger.value = true
  }
  confirmVisible.value = true
}

async function onConfirm() {
  const o = confirmTarget.value
  if (!o) return
  confirmVisible.value = false
  try {
    if (confirmTitle.value === '确认到账') {
      await confirmOrder(o.id)
      msg.value = '已确认到账，课时已入账'
    } else {
      await cancelAdminOrder(o.id)
      msg.value = '订单已取消'
    }
    setTimeout(() => (msg.value = ''), 3000)
    await load()
  } catch (e: any) {
    alert(e?.response?.data?.detail || '操作失败')
  }
}

const hasFilters = computed(() => Boolean(keyword.value || campus.value || packageId.value || dateFrom.value || dateTo.value || statusFilter.value))

function fmt(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const data = await listAdminOrders({
      status: statusFilter.value || undefined,
      keyword: keyword.value || undefined,
      campus: campus.value || undefined,
      package_id: packageId.value || undefined,
      date_from: dateFrom.value ? new Date(dateFrom.value).toISOString() : undefined,
      date_to: dateTo.value ? new Date(dateTo.value).toISOString() : undefined,
      limit: pageSize,
      offset: (page.value - 1) * pageSize,
    })
    items.value = data.items
    total.value = data.total
  } catch (e: any) {
    if (e?.response?.status === 403) {
      error.value = '你没有权限查看订单管理'
    } else {
      error.value = e?.response?.data?.detail || '加载订单失败'
    }
  } finally {
    loading.value = false
  }
}

function onPageChange(p: number) {
  page.value = p
  load()
}

function switchStatus(key: string) {
  statusFilter.value = key
  page.value = 1
  load()
}

function clearFilters() {
  keyword.value = ''
  campus.value = ''
  packageId.value = ''
  dateFrom.value = ''
  dateTo.value = ''
  statusFilter.value = ''
  page.value = 1
  load()
}

onMounted(async () => {
  // 首屏先加载订单，选项数据并行异步填充，避免任一接口失败阻塞列表（含「全部」Tab）
  load()
  const [pkg, campuses] = await Promise.allSettled([
    listPackages(false, { limit: 500 }),
    listCampusesApi(),
  ])
  if (pkg.status === 'fulfilled') packageOptions.value = pkg.value.items
  if (campuses.status === 'fulfilled') campusOptions.value = campuses.value
})
</script>

<template>
  <div>
    <PageHead title="课时订阅订单" eyebrow="ORDERS" sub="家长客户端订阅课时包 · 模拟支付由管理员确认到账（OQ-06）">
      <template #actions>
      <div class="search-row">
        <input v-model="keyword" class="search-input" placeholder="搜索学员姓名" @keyup.enter="load" />
        <select v-model="campus" class="search-select" @change="load">
          <option value="">全部校区</option>
          <option v-for="c in campusOptions" :key="c" :value="c">{{ c }}</option>
        </select>
        <select v-model="packageId" class="search-select" @change="load">
          <option value="">全部课时包</option>
          <option v-for="p in packageOptions" :key="p.id" :value="p.id">{{ p.name }}</option>
        </select>
        <input v-model="dateFrom" type="datetime-local" class="search-input small" @change="load" />
        <input v-model="dateTo" type="datetime-local" class="search-input small" @change="load" />
        <button class="op-btn" @click="clearFilters">重置</button>
      </div>
      </template>
    </PageHead>

    <p v-if="error" class="error-banner">{{ error }}</p>
    <p v-if="msg" class="success-banner">{{ msg }}</p>

    <div class="tabs">
      <button
        v-for="t in statusTabs"
        :key="t.key"
        class="tab"
        :class="{ active: statusFilter === t.key }"
        @click="switchStatus(t.key)"
      >
        {{ t.label }}
      </button>
    </div>

    <div v-if="loading" class="loading-tip">加载中…</div>

    <div v-else-if="items.length === 0" class="empty-tip">暂无订单</div>

    <div v-else class="order-table-wrap">
      <table class="order-table">
        <thead>
          <tr>
            <th>学员</th>
            <th>校区</th>
            <th>课时包</th>
            <th>金额</th>
            <th>状态</th>
            <th>下单时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="o in items" :key="o.id">
            <td>
              <strong>{{ o.student_name || '—' }}</strong>
            </td>
            <td>
              <span v-if="o.student_campus" class="campus-tag">{{ o.student_campus }}</span>
              <span v-else class="muted">—</span>
            </td>
            <td>{{ o.package_name || '—' }}</td>
            <td class="amount">¥{{ Number(o.amount).toFixed(2) }}</td>
            <td>
              <span class="status-pill" :class="statusMap[o.status]?.cls || 'pending'">
                {{ statusMap[o.status]?.label || o.status }}
              </span>
              <div v-if="o.status === 'refunded'" class="refund-note">
                退 ¥{{ Number(o.refund_amount ?? o.amount).toFixed(2) }}
                <span v-if="o.refund_note" class="refund-note-sub" :title="o.refund_note">{{ o.refund_note.slice(0, 12) }}</span>
              </div>
            </td>
            <td class="date">{{ fmt(o.created_at) }}</td>
            <td>
              <div class="ops">
                <button
                  v-if="o.status === 'paid'"
                  class="op-btn confirm"
                  @click="openConfirm(o, 'confirm')"
                >
                  确认到账
                </button>
                <button
                  v-if="o.status === 'pending'"
                  class="op-btn cancel"
                  @click="openConfirm(o, 'cancel')"
                >
                  取消
                </button>
                <span v-else-if="o.status === 'confirmed'" class="done-text">课时已入账</span>
                <span v-else class="done-text">—</span>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <PaginationBar :total="total" :page="page" :page-size="pageSize" @update:page="onPageChange" />

    <ConfirmDialog
      :visible="confirmVisible"
      :title="confirmTitle"
      :message="confirmText"
      :confirm-text="confirmDanger ? '确认取消' : '确认到账'"
      :danger="confirmDanger"
      @cancel="confirmVisible = false"
      @confirm="onConfirm"
    />
  </div>
</template>

<style scoped>
.page-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
h1 {
  font-size: 22px;
}
.page-sub {
  color: var(--ink-3);
  font-size: 13px;
  margin-top: 4px;
}

.search-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.search-input,
.search-select {
  padding: 7px 10px;
  border-radius: 10px;
  border: 1px solid var(--line);
  background: var(--surface);
  font-size: 12.5px;
  color: var(--ink);
}
.search-input.small {
  width: 170px;
}
.search-input:focus,
.search-select:focus {
  outline: none;
  border-color: var(--brand);
}

.error-banner {
  background: var(--danger-soft);
  color: var(--danger);
  padding: 10px 14px;
  border-radius: 10px;
  margin-bottom: 14px;
  font-size: 13px;
}

.success-banner {
  background: var(--success-soft);
  color: var(--success);
  padding: 10px 14px;
  border-radius: 10px;
  margin-bottom: 14px;
  font-size: 13px;
}

.tabs {
  display: flex;
  gap: 8px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}

.tab {
  padding: 7px 16px;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--ink-3);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.15s;
}

.tab.active {
  background: linear-gradient(135deg, #6366f1, #06b6d4);
  color: #fff;
  border-color: transparent;
  font-weight: 600;
}

.loading-tip {
  text-align: center;
  color: var(--ink-3);
  font-size: 13px;
  padding: 20px 0;
}

.empty-tip {
  text-align: center;
  color: var(--ink-3);
  padding: 40px 0;
  font-size: 14px;
  background: var(--surface);
  border: 1px dashed var(--line);
  border-radius: 16px;
}

.order-table-wrap {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 16px;
  overflow: hidden;
}

.order-table {
  width: 100%;
  border-collapse: collapse;
}

.order-table th {
  text-align: left;
  font-size: 12px;
  font-weight: 600;
  color: var(--ink-3);
  padding: 12px 16px;
  background: var(--bg);
  border-bottom: 1px solid var(--line);
}

.order-table td {
  padding: 13px 16px;
  border-bottom: 1px solid #f1f5f9;
  font-size: 13.5px;
}

.order-table tr:last-child td {
  border-bottom: none;
}

.amount {
  font-weight: 700;
}

.date {
  font-size: 12.5px;
  color: var(--ink-3);
}

.campus-tag {
  font-size: 11.5px;
  padding: 2px 9px;
  border-radius: 999px;
  background: var(--brand-soft);
  color: var(--brand-strong);
  white-space: nowrap;
}

.muted {
  color: var(--ink-3);
}

.refund-note {
  font-size: 11.5px;
  color: var(--danger);
  margin-top: 3px;
  font-weight: 600;
}

.refund-note-sub {
  display: block;
  color: var(--ink-3);
  font-weight: 500;
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.status-pill {
  font-size: 11.5px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 999px;
}

.status-pill.pending {
  background: var(--warning-soft);
  color: #b45309;
}

.status-pill.paid {
  background: var(--brand-soft);
  color: var(--brand-strong);
}

.status-pill.confirmed {
  background: var(--success-soft);
  color: var(--success);
}

.status-pill.cancelled {
  background: #f1f5f9;
  color: var(--ink-3);
}

.status-pill.refunded {
  background: var(--danger-soft);
  color: var(--danger);
}

.ops {
  display: flex;
  gap: 8px;
  align-items: center;
}

.op-btn {
  padding: 6px 14px;
  border-radius: 999px;
  border: 1px solid var(--line);
  font-size: 12.5px;
  cursor: pointer;
  transition: all 0.15s;
}

.op-btn.confirm {
  background: linear-gradient(135deg, #6366f1, #06b6d4);
  color: #fff;
  border-color: transparent;
  font-weight: 600;
}

.op-btn.cancel {
  background: var(--surface);
  color: var(--danger);
  border-color: #fecaca;
}

.op-btn:hover {
  transform: translateY(-1px);
}

.done-text {
  font-size: 12px;
  color: var(--ink-3);
}
</style>
