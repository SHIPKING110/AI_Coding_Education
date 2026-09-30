<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import {
  createClientOrder,
  listClientPackages,
  payClientOrder,
  type ClientPackageOut,
  type OrderOut,
} from '@/api/client'
import { listSubjects, type SubjectOut } from '@/api/business'
import { useClientStore } from '@/stores/client'

const store = useClientStore()
const router = useRouter()

const student = computed(() => store.activeStudent)
const packages = ref<ClientPackageOut[]>([])
const subjects = ref<SubjectOut[]>([])
const loading = ref(false)
const error = ref('')

// 筛选：科目 / 标签 / 售价范围
const filterSubject = ref('')
const filterTag = ref('')
const filterMin = ref('')
const filterMax = ref('')

// 订阅确认弹窗
const showSubscribe = ref(false)
const subscribingPkg = ref<ClientPackageOut | null>(null)
const ordering = ref(false)
const orderError = ref('')

// 支付弹窗（含 5 分钟倒计时）
const showPay = ref(false)
const payingOrder = ref<OrderOut | null>(null)
const paying = ref(false)
const payError = ref('')
const remainSec = ref(300)
let timer: number | null = null

function fmtDate(s: string | null): string {
  if (!s) return ''
  const d = new Date(s)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function fmtRemain(sec: number): string {
  const m = Math.floor(sec / 60)
  const s = sec % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

function stopTimer() {
  if (timer !== null) {
    window.clearInterval(timer)
    timer = null
  }
}

function startTimer(expiresAt: string | null) {
  stopTimer()
  const calc = () => {
    if (!expiresAt) {
      remainSec.value = 300
      return
    }
    remainSec.value = Math.max(0, Math.round((new Date(expiresAt).getTime() - Date.now()) / 1000))
    if (remainSec.value <= 0) stopTimer()
  }
  calc()
  timer = window.setInterval(calc, 1000)
}

async function load() {
  if (!store.me) await store.loadMe(true)
  loading.value = true
  error.value = ''
  try {
    packages.value = await listClientPackages({
      subject_id: filterSubject.value || undefined,
      tag: filterTag.value || undefined,
      price_min: filterMin.value || undefined,
      price_max: filterMax.value || undefined,
    })
  } catch {
    error.value = '加载课时包失败'
  } finally {
    loading.value = false
  }
}

function onFilter() {
  load()
}

function openSubscribe(pkg: ClientPackageOut) {
  if (!student.value) {
    orderError.value = '请先在首页选择学员'
    return
  }
  subscribingPkg.value = pkg
  orderError.value = ''
  showSubscribe.value = true
}

async function confirmSubscribe() {
  if (!student.value || !subscribingPkg.value) return
  ordering.value = true
  orderError.value = ''
  try {
    const order = await createClientOrder({
      student_id: student.value.id,
      package_id: subscribingPkg.value.id,
    })
    showSubscribe.value = false
    payingOrder.value = order
    payError.value = ''
    showPay.value = true
    startTimer(order.expires_at)
  } catch (e: any) {
    orderError.value = e?.response?.data?.detail || '下单失败，请重试'
  } finally {
    ordering.value = false
  }
}

async function confirmPay() {
  if (!payingOrder.value) return
  paying.value = true
  payError.value = ''
  try {
    await payClientOrder(payingOrder.value.id)
    showPay.value = false
    stopTimer()
    router.push({ name: 'client-orders' })
  } catch (e: any) {
    payError.value = e?.response?.data?.detail || '支付失败'
  } finally {
    paying.value = false
  }
}

function payLater() {
  showPay.value = false
  stopTimer()
  router.push({ name: 'client-orders' })
}

onMounted(async () => {
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
    <header class="page-head">
      <div>
        <h1>课时订阅</h1>
        <p class="page-sub" v-if="student">{{ student.name }} 剩余 {{ student.lesson_balance }} 课时 · 选择课时包续费</p>
      </div>
      <button class="head-btn" @click="router.push({ name: 'client-orders' })">我的订单</button>
    </header>

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
    </div>

    <p v-if="error" class="error-banner">{{ error }}</p>
    <p v-if="orderError" class="error-banner">{{ orderError }}</p>

    <div v-if="loading" class="loading-tip">加载中…</div>

    <div v-else-if="packages.length === 0" class="empty-tip">
      暂无可订阅的课时包，请联系机构
    </div>

    <div v-else class="package-grid">
      <div v-for="pkg in packages" :key="pkg.id" class="package-card">
        <div class="pkg-badge" :class="pkg.tag">{{ pkg.tag === 'activity' ? '活动课' : '官方课时包' }}</div>
        <h3 class="pkg-name">{{ pkg.name }}</h3>
        <div class="pkg-tags">
          <span v-if="pkg.subject_name" class="tag-chip">{{ pkg.subject_name }}</span>
          <span v-if="pkg.tag === 'activity' && pkg.sale_end" class="sale-chip">
            售卖至 {{ fmtDate(pkg.sale_end) }}
          </span>
        </div>
        <div class="price-row">
          <span class="currency">¥</span>
          <span class="price">{{ Number(pkg.price).toFixed(0) }}</span>
        </div>
        <div class="pkg-meta">
          <span>{{ pkg.total_lessons }} 课时</span>
          <span>约 ¥{{ (Number(pkg.price) / pkg.total_lessons).toFixed(2) }} / 课时</span>
        </div>
        <div class="pkg-foot">{{ pkg.paid_students }} 人已购 · 发布 {{ fmtDate(pkg.published_at || pkg.created_at) }}</div>
        <button class="buy-btn" :disabled="ordering" @click="openSubscribe(pkg)">
          {{ ordering ? '下单中…' : '立即订阅' }}
        </button>
      </div>
    </div>

    <div class="pay-note">
      <p>订阅流程：下单 → 模拟支付 → 机构确认到账 → 课时自动入账</p>
      <p>下单后请在 5 分钟内完成支付，超时订单将自动撤销。</p>
    </div>

    <!-- 订阅确认弹窗 -->
    <div v-if="showSubscribe && subscribingPkg" class="overlay" @click.self="showSubscribe = false">
      <div class="modal">
        <h2>确认订阅</h2>
        <div class="sum-card">
          <div class="sum-row"><span>课时包</span><strong>{{ subscribingPkg.name }}</strong></div>
          <div v-if="subscribingPkg.subject_name" class="sum-row"><span>科目</span><strong>{{ subscribingPkg.subject_name }}</strong></div>
          <div class="sum-row"><span>课时</span><strong>{{ subscribingPkg.total_lessons }} 课时</strong></div>
          <div class="sum-row"><span>学员</span><strong>{{ student?.name }}</strong></div>
          <div class="sum-row total"><span>应付</span><strong class="amount">¥{{ Number(subscribingPkg.price).toFixed(2) }}</strong></div>
        </div>
        <p class="modal-tip">下单后进入待支付，5 分钟内未支付将自动撤销。</p>
        <div class="modal-actions">
          <button class="btn ghost" @click="showSubscribe = false">再想想</button>
          <button class="btn primary" :disabled="ordering" @click="confirmSubscribe">
            {{ ordering ? '下单中…' : '确认下单' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 模拟支付弹窗 -->
    <div v-if="showPay && payingOrder" class="overlay" @click.self="payLater">
      <div class="modal">
        <h2>模拟支付</h2>
        <div class="sum-card">
          <div class="sum-row"><span>课时包</span><strong>{{ payingOrder.package_name || '课时包' }}</strong></div>
          <div class="sum-row"><span>学员</span><strong>{{ payingOrder.student_name }}</strong></div>
          <div class="sum-row total"><span>支付金额</span><strong class="amount">¥{{ Number(payingOrder.amount).toFixed(2) }}</strong></div>
        </div>
        <p class="countdown" :class="{ urgent: remainSec <= 60 }">
          剩余支付时间 {{ fmtRemain(remainSec) }}
        </p>
        <p v-if="payError" class="error">{{ payError }}</p>
        <div class="modal-actions">
          <button class="btn ghost" @click="payLater">稍后支付</button>
          <button class="btn primary" :disabled="paying || remainSec <= 0" @click="confirmPay">
            {{ paying ? '支付中…' : remainSec <= 0 ? '订单已超时' : '确认支付' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page-head {
  margin-bottom: 16px;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
h1 {
  font-size: 22px;
}
.page-sub {
  color: var(--ink-3);
  font-size: 13px;
  margin-top: 4px;
}
.head-btn {
  flex-shrink: 0;
  padding: 8px 16px;
  border-radius: 10px;
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--ink-2);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}
.head-btn:hover {
  border-color: var(--brand);
  color: var(--brand-strong);
}

.filter-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}
.filter-select,
.filter-input {
  padding: 7px 10px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--surface);
  font-size: 12.5px;
  color: var(--ink-2);
}
.filter-input {
  width: 96px;
}
.filter-sep {
  color: var(--ink-3);
}

.error-banner {
  background: var(--danger-soft);
  color: var(--danger);
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

.package-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 16px;
}

.package-card {
  position: relative;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 16px;
  padding: 20px;
  transition: all 0.18s;
  display: flex;
  flex-direction: column;
}

.package-card:hover {
  transform: translateY(-3px);
  box-shadow: var(--shadow-md);
  border-color: #c7d2fe;
}

.pkg-badge {
  position: absolute;
  top: 14px;
  right: 14px;
  font-size: 11px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 999px;
  background: var(--brand-soft);
  color: var(--brand-strong);
}
.pkg-badge.activity {
  background: #fef3c7;
  color: #b45309;
}

.pkg-name {
  font-size: 15px;
  margin-bottom: 8px;
  padding-right: 80px;
}

.pkg-tags {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}
.tag-chip {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 999px;
  background: var(--brand-soft);
  color: var(--brand-strong);
}
.sale-chip {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 999px;
  background: #fef3c7;
  color: #b45309;
}

.price-row {
  display: flex;
  align-items: baseline;
  gap: 4px;
  margin-bottom: 8px;
}

.currency {
  font-size: 18px;
  font-weight: 700;
  color: var(--ink-2);
}

.price {
  font-size: 34px;
  font-weight: 800;
  background: linear-gradient(135deg, #6366f1, #06b6d4);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}

.pkg-meta {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  color: var(--ink-3);
  margin-bottom: 6px;
}

.pkg-foot {
  font-size: 11.5px;
  color: var(--ink-3);
  margin-bottom: 14px;
}

.buy-btn {
  margin-top: auto;
  padding: 11px 0;
  border-radius: 12px;
  border: none;
  background: linear-gradient(135deg, #6366f1, #06b6d4);
  color: #fff;
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.15s;
}

.buy-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 6px 16px rgba(99, 102, 241, 0.3);
}

.pay-note {
  margin-top: 18px;
  padding: 14px 16px;
  border-radius: 12px;
  background: var(--warning-soft);
  color: #b45309;
  font-size: 12.5px;
  line-height: 1.7;
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
  color: var(--brand-strong);
  font-size: 20px;
}
.modal-tip {
  font-size: 12.5px;
  color: var(--ink-3);
  margin-bottom: 16px;
}
.countdown {
  text-align: center;
  font-size: 15px;
  font-weight: 700;
  color: var(--brand-strong);
  margin-bottom: 14px;
}
.countdown.urgent {
  color: var(--danger);
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
.btn.primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
.btn.ghost {
  background: var(--surface);
  color: var(--ink-2);
  border: 1px solid var(--line);
}
</style>
