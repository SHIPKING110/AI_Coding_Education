<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'

import PaginationBar from '@/components/PaginationBar.vue'
import {
  cancelClientOrder,
  checkClientRefund,
  listClientOrders,
  payClientOrder,
  refundClientOrder,
  type OrderOut,
} from '@/api/client'
import { useClientStore } from '@/stores/client'

const store = useClientStore()
const student = computed(() => store.activeStudent)

const items = ref<OrderOut[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 8
const loading = ref(false)
const error = ref('')
const msg = ref('')

const statusMap: Record<string, { label: string; cls: string }> = {
  pending: { label: '待支付', cls: 'pending' },
  paid: { label: '待确认到账', cls: 'paid' },
  confirmed: { label: '已到账', cls: 'confirmed' },
  cancelled: { label: '已取消', cls: 'cancelled' },
  refunded: { label: '已退款', cls: 'refunded' },
}

// 待支付倒计时（每秒刷新显示；过期自动重载）
const nowTs = ref(Date.now())
let tick: number | null = null

// 支付弹窗
const showPay = ref(false)
const payingOrder = ref<OrderOut | null>(null)
const paying = ref(false)
const payError = ref('')

// 退款弹窗
const showRefund = ref(false)
const refundingOrder = ref<OrderOut | null>(null)
const reasonKey = ref('wrong_package')
const reasonText = ref('')
const refunding = ref(false)
const refundError = ref('')
const hideRefundIds = ref<Set<string>>(new Set())
const REASONS = [
  { key: 'wrong_package', label: '买错课包了' },
  { key: 'busy', label: '有其他安排不打算再续费' },
  { key: 'other', label: '其他原因' },
]

function fmt(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function remainSec(o: OrderOut): number | null {
  if (o.status !== 'pending' || !o.expires_at) return null
  return Math.max(0, Math.round((new Date(o.expires_at).getTime() - nowTs.value) / 1000))
}

function fmtRemain(sec: number): string {
  const m = Math.floor(sec / 60)
  const s = sec % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

function canRefund(o: OrderOut): boolean {
  return o.status === 'confirmed' && !hideRefundIds.value.has(o.id)
}

async function load() {
  if (!store.me) await store.loadMe(true)
  if (!student.value) return
  loading.value = true
  error.value = ''
  try {
    const data = await listClientOrders({
      student_id: student.value.id,
      limit: pageSize,
      offset: (page.value - 1) * pageSize,
    })
    items.value = data.items
    total.value = data.total
  } catch {
    error.value = '加载订单失败'
  } finally {
    loading.value = false
  }
}

function openPay(order: OrderOut) {
  payingOrder.value = order
  payError.value = ''
  showPay.value = true
}

async function confirmPay() {
  if (!payingOrder.value) return
  paying.value = true
  payError.value = ''
  try {
    await payClientOrder(payingOrder.value.id)
    showPay.value = false
    msg.value = '模拟支付成功，请等待机构确认到账'
    setTimeout(() => (msg.value = ''), 3000)
    await load()
  } catch (e: any) {
    payError.value = e?.response?.data?.detail || '支付失败'
    if (/超时|撤销/.test(payError.value)) await load()
  } finally {
    paying.value = false
  }
}

async function cancel(order: OrderOut) {
  if (!window.confirm('确认取消该订单？')) return
  try {
    await cancelClientOrder(order.id)
    await load()
    await store.loadMe(true)
  } catch (e: any) {
    alert(e?.response?.data?.detail || '取消失败')
  }
}

async function openRefund(order: OrderOut) {
  refundError.value = ''
  try {
    const check = await checkClientRefund(order.id)
    if (!check.ok) {
      if (check.code === 'empty') {
        // 已耗尽：按需求不再展示退款按钮
        hideRefundIds.value.add(order.id)
        return
      }
      refundError.value = check.message
      refundingOrder.value = order
      reasonKey.value = ''
      showRefund.value = true
      return
    }
    refundingOrder.value = order
    reasonKey.value = 'wrong_package'
    reasonText.value = ''
    showRefund.value = true
  } catch (e: any) {
    alert(e?.response?.data?.detail || '检查失败')
  }
}

async function confirmRefund() {
  if (!refundingOrder.value) return
  if (!reasonKey.value) return
  if (reasonKey.value === 'other' && !reasonText.value.trim()) {
    refundError.value = '选择“其他原因”请填写具体原因'
    return
  }
  refunding.value = true
  refundError.value = ''
  try {
    await refundClientOrder(refundingOrder.value.id, {
      reason_key: reasonKey.value,
      reason_text: reasonText.value.trim() || undefined,
    })
    showRefund.value = false
    msg.value = '退款成功，课时已扣减'
    setTimeout(() => (msg.value = ''), 3000)
    await load()
    await store.loadMe(true)
  } catch (e: any) {
    refundError.value = e?.response?.data?.detail || '退款失败'
  } finally {
    refunding.value = false
  }
}

function onPageChange(p: number) {
  page.value = p
  load()
}

onMounted(() => {
  load()
  tick = window.setInterval(() => {
    nowTs.value = Date.now()
    // 有订单刚过期则自动重载（状态变为已取消）
    if (items.value.some((o) => o.status === 'pending' && remainSec(o) === 0)) {
      load()
    }
  }, 1000)
})

onUnmounted(() => {
  if (tick !== null) window.clearInterval(tick)
})
</script>

<template>
  <div>
    <header class="page-head">
      <div>
        <h1>我的订单</h1>
        <p class="page-sub" v-if="student">{{ student.name }} · 共 {{ total }} 笔订单 · 购买记录与退款都在这里</p>
      </div>
    </header>

    <p v-if="error" class="error-banner">{{ error }}</p>
    <p v-if="msg" class="success-banner">{{ msg }}</p>

    <div v-if="loading" class="loading-tip">加载中…</div>

    <div v-else-if="items.length === 0" class="empty-tip">
      暂无订单，去<a class="link" href="#/client/packages">课时订阅</a>看看吧
    </div>

    <div v-else class="order-list">
      <div v-for="o in items" :key="o.id" class="order-card">
        <div class="order-top">
          <strong>{{ o.package_name || '课时包' }}</strong>
          <span class="status-pill" :class="statusMap[o.status]?.cls || 'pending'">
            {{ statusMap[o.status]?.label || o.status }}
          </span>
        </div>
        <div class="order-mid">
          <span class="order-student">{{ o.student_name }}</span>
          <span class="order-amount">¥{{ Number(o.amount).toFixed(2) }}</span>
        </div>
        <div class="order-bottom">
          <span class="order-date">
            {{ o.paid_at ? `支付于 ${fmt(o.paid_at)}` : `下单于 ${fmt(o.created_at)}` }}
            <template v-if="o.confirmed_at"> · 到账 {{ fmt(o.confirmed_at) }}</template>
            <template v-if="o.refunded_at"> · 退款于 {{ fmt(o.refunded_at) }}</template>
            <template v-if="remainSec(o) !== null">
              · <span class="countdown" :class="{ urgent: (remainSec(o) ?? 0) <= 60 }">
                剩余 {{ fmtRemain(remainSec(o) ?? 0) }}
              </span>
            </template>
          </span>
          <div class="order-ops">
            <button v-if="o.status === 'pending'" class="op-btn pay" @click="openPay(o)">模拟支付</button>
            <button v-if="o.status === 'pending'" class="op-btn" @click="cancel(o)">取消</button>
            <button v-if="canRefund(o)" class="op-btn" @click="openRefund(o)">退款</button>
            <span v-else-if="o.status === 'paid'" class="confirm-hint">等待机构确认…</span>
            <span v-else-if="o.status === 'refunded'" class="refund-text">
              已退 ¥{{ Number(o.refund_amount ?? o.amount).toFixed(2) }}
            </span>
          </div>
        </div>
        <div v-if="o.status === 'refunded' && o.refund_note" class="refund-note">
          退费备注：{{ o.refund_note }}
        </div>
      </div>
    </div>

    <PaginationBar :total="total" :page="page" :page-size="pageSize" @update:page="onPageChange" />

    <!-- 模拟支付弹窗 -->
    <div v-if="showPay && payingOrder" class="overlay" @click.self="showPay = false">
      <div class="modal">
        <h2>模拟支付</h2>
        <div class="sum-card">
          <div class="sum-row"><span>课时包</span><strong>{{ payingOrder.package_name || '课时包' }}</strong></div>
          <div class="sum-row"><span>学员</span><strong>{{ payingOrder.student_name }}</strong></div>
          <div class="sum-row total"><span>支付金额</span><strong class="amount">¥{{ Number(payingOrder.amount).toFixed(2) }}</strong></div>
        </div>
        <p v-if="remainSec(payingOrder) !== null" class="countdown big" :class="{ urgent: (remainSec(payingOrder) ?? 0) <= 60 }">
          剩余支付时间 {{ fmtRemain(remainSec(payingOrder) ?? 0) }}
        </p>
        <p class="modal-tip">支付后需等待机构确认到账，课时随后自动入账。</p>
        <p v-if="payError" class="error">{{ payError }}</p>
        <div class="modal-actions">
          <button class="btn ghost" @click="showPay = false">稍后支付</button>
          <button class="btn primary" :disabled="paying" @click="confirmPay">
            {{ paying ? '支付中…' : '确认支付' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 退款弹窗 -->
    <div v-if="showRefund && refundingOrder" class="overlay" @click.self="showRefund = false">
      <div class="modal">
        <h2>申请退款</h2>
        <div class="sum-card">
          <div class="sum-row"><span>课时包</span><strong>{{ refundingOrder.package_name || '课时包' }}</strong></div>
          <div class="sum-row total"><span>退款金额</span><strong class="amount">¥{{ Number(refundingOrder.amount).toFixed(2) }}</strong></div>
        </div>
        <template v-if="reasonKey">
          <p class="refund-label">请选择退款原因</p>
          <label v-for="r in REASONS" :key="r.key" class="radio-row">
            <input v-model="reasonKey" type="radio" :value="r.key" />
            <span>{{ r.label }}</span>
          </label>
          <textarea
            v-if="reasonKey === 'other'"
            v-model="reasonText"
            class="reason-input"
            rows="3"
            placeholder="请填写具体原因"
          />
          <p class="modal-tip">仅「未消耗且下单 7 天内」的课包可自助退款；退款后该单课时将从学员账户扣减。</p>
        </template>
        <template v-else>
          <p class="blocked-msg">{{ refundError }}</p>
        </template>
        <p v-if="refundError && reasonKey" class="error">{{ refundError }}</p>
        <div class="modal-actions">
          <button class="btn ghost" @click="showRefund = false">关闭</button>
          <button v-if="reasonKey" class="btn danger" :disabled="refunding" @click="confirmRefund">
            {{ refunding ? '退款中…' : '确认退款' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page-head {
  margin-bottom: 16px;
}
h1 {
  font-size: 22px;
}
.page-sub {
  color: var(--ink-3);
  font-size: 13px;
  margin-top: 4px;
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

.link {
  color: var(--brand);
  font-weight: 600;
}

.order-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.order-card {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 14px 16px;
}

.order-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 6px;
}

.order-top strong {
  font-size: 14.5px;
}

.status-pill {
  font-size: 11.5px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 999px;
  flex-shrink: 0;
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

.order-mid {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.order-student {
  font-size: 12.5px;
  color: var(--ink-3);
}

.order-amount {
  font-size: 20px;
  font-weight: 800;
  background: linear-gradient(135deg, #6366f1, #06b6d4);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}

.order-bottom {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
  border-top: 1px solid #f1f5f9;
  padding-top: 10px;
}

.order-date {
  font-size: 12px;
  color: var(--ink-3);
}

.countdown {
  font-weight: 700;
  color: #b45309;
}
.countdown.urgent {
  color: var(--danger);
}
.countdown.big {
  text-align: center;
  font-size: 15px;
  margin-bottom: 12px;
}

.order-ops {
  display: flex;
  gap: 8px;
  align-items: center;
}

.op-btn {
  padding: 6px 14px;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--ink-2);
  font-size: 12.5px;
  cursor: pointer;
  transition: all 0.15s;
}

.op-btn.pay {
  background: linear-gradient(135deg, #6366f1, #06b6d4);
  color: #fff;
  border-color: transparent;
  font-weight: 600;
}

.op-btn:hover {
  transform: translateY(-1px);
}

.confirm-hint {
  font-size: 12px;
  color: var(--ink-3);
}

.refund-text {
  font-size: 12px;
  font-weight: 700;
  color: var(--danger);
}

.refund-note {
  margin-top: 6px;
  font-size: 12px;
  color: var(--ink-3);
  border-top: 1px dashed #f1f5f9;
  padding-top: 6px;
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
  padding: 20px;
}
.modal {
  width: 420px;
  max-width: 100%;
  background: var(--surface);
  border-radius: 16px;
  padding: 24px;
  box-shadow: var(--shadow-lg);
}
.modal h2 {
  font-size: 18px;
  margin-bottom: 16px;
}
.sum-card {
  background: var(--surface-alt);
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 14px 16px;
  margin-bottom: 14px;
}
.sum-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13.5px;
  padding: 5px 0;
  color: var(--ink-2);
}
.sum-row strong {
  color: var(--ink);
}
.sum-row.total {
  border-top: 1px dashed var(--line);
  margin-top: 6px;
  padding-top: 10px;
  font-size: 14.5px;
}
.amount {
  color: var(--danger);
  font-size: 20px;
}
.modal-tip {
  font-size: 12.5px;
  color: var(--ink-3);
  margin-bottom: 16px;
}
.refund-label {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 8px;
  color: var(--ink-2);
}
.radio-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13.5px;
  padding: 7px 0;
  cursor: pointer;
  color: var(--ink-2);
}
.reason-input {
  width: 100%;
  box-sizing: border-box;
  margin-top: 8px;
  padding: 9px 11px;
  border: 1px solid var(--line);
  border-radius: 10px;
  font-size: 13.5px;
  resize: vertical;
}
.reason-input:focus {
  outline: none;
  border-color: var(--brand);
  box-shadow: 0 0 0 3px var(--brand-soft);
}
.blocked-msg {
  font-size: 14px;
  color: var(--danger);
  background: var(--danger-soft);
  border-radius: 10px;
  padding: 12px 14px;
  margin-bottom: 16px;
  line-height: 1.6;
}
.error {
  color: var(--danger);
  font-size: 13px;
  margin-bottom: 10px;
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}
.btn {
  padding: 9px 18px;
  border-radius: 10px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  border: none;
}
.btn.primary {
  background: linear-gradient(135deg, #6366f1, #06b6d4);
  color: #fff;
}
.btn.primary:disabled,
.btn.danger:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
.btn.danger {
  background: var(--danger);
  color: #fff;
}
.btn.ghost {
  background: var(--surface);
  color: var(--ink-2);
  border: 1px solid var(--line);
}
</style>
