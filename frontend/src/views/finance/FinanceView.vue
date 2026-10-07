<script setup lang="ts">
import { computed, defineAsyncComponent, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
const SalaryPanel = defineAsyncComponent(() => import('./SalaryPanel.vue'))
import * as echarts from 'echarts'

import PageHead from '@/components/PageHead.vue'
import OrdersView from '@/views/orders/OrdersView.vue'
import { myPermissions } from '@/api/permissions'
import { useAuthStore } from '@/stores/auth'
import { listCampuses } from '@/api/business'
import {
  getFinanceBySubject,
  getFinanceByTeacher,
  getLessonStats,
  getOrderStats,
  type LessonStats,
  type OrderStatBucket,
  type OrderStatsSummary,
  type SubjectStat,
  type TeacherStat,
} from '@/api/finance'
import {
  listAllLessonRecords,
  type AllRecordsOut,
  type LessonRecordOut,
} from '@/api/enrollment'

const activeTab = ref<'orders' | 'lessons' | 'records' | 'salary'>('orders')

// 财务 tab 精细化可见：教师按 finance_* 键（finance_view 为总开关，后端同样校验）
const auth = useAuthStore()
const myPerms = ref<Record<string, boolean>>({})
const canFin = (key: string): boolean => {
  if (auth.user?.role !== 'teacher') return true
  return myPerms.value[key] === true || myPerms.value.finance_view === true
}
const visibleTabs = computed(() => ({
  orders: canFin('finance_revenue'),
  lessons: canFin('finance_revenue'),
  records: canFin('finance_records'),
  salary: canFin('finance_salary') || canFin('finance_salary_all'),
}))

// ---- 通用筛选 ----
const campuses = ref<{ id: string; name: string }[]>([])
const campus = ref('')
const dateFrom = ref('')
const dateTo = ref('')

function defaultRange(days = 13) {
  const to = new Date()
  const from = new Date()
  from.setDate(from.getDate() - days)
  const fmt = (d: Date) => d.toISOString().slice(0, 10)
  dateFrom.value = fmt(from)
  dateTo.value = fmt(to)
}

// ---- 订单管理 ----
const orderStats = ref<OrderStatBucket[]>([])
const orderSummary = ref<OrderStatsSummary | null>(null)
const statsLoading = ref(false)
const showOrders = ref(true)
const showPaid = ref(true)
const showRefunds = ref(true)
const showPaidAmount = ref(true)
const trendEl = ref<HTMLDivElement | null>(null)
let trendChart: echarts.ECharts | null = null

async function loadOrderStats() {
  statsLoading.value = true
  try {
    const data = await getOrderStats({
      date_from: dateFrom.value || undefined,
      date_to: dateTo.value || undefined,
      campus: campus.value || undefined,
    })
    orderStats.value = data.items
    orderSummary.value = data.summary
  } catch {
    orderStats.value = []
    orderSummary.value = null
  } finally {
    statsLoading.value = false
    renderTrend()
  }
}

function barGradient(c1: string, c2: string) {
  return new echarts.graphic.LinearGradient(0, 0, 0, 1, [
    { offset: 0, color: c1 },
    { offset: 1, color: c2 },
  ])
}

function lineArea(c: string) {
  return new echarts.graphic.LinearGradient(0, 0, 0, 1, [
    { offset: 0, color: c + '55' },
    { offset: 1, color: c + '05' },
  ])
}

async function renderTrend() {
  // 等待 v-if 切换后的 DOM 就绪，否则容器不存在或尺寸为 0，图表空白
  await nextTick()
  if (!trendEl.value || !orderSummary.value) return
  // 筛选 reload 会销毁重建图表容器（v-if），旧实例绑定的是已卸载节点，必须重建
  if (!trendChart || trendChart.getDom() !== trendEl.value) {
    if (trendChart) trendChart.dispose()
    trendChart = echarts.init(trendEl.value)
  }
  const labels = orderStats.value.map((b) => b.label.slice(5))
  const series: echarts.SeriesOption[] = []
  if (showOrders.value)
    series.push({
      name: '下单数',
      type: 'bar',
      data: orderStats.value.map((b) => b.orders),
      itemStyle: { borderRadius: [7, 7, 2, 2], color: barGradient('#818cf8', '#6366f1') },
      showBackground: true,
      backgroundStyle: { color: 'rgba(99,102,241,0.07)', borderRadius: [7, 7, 2, 2] },
      barGap: '25%',
      emphasis: { itemStyle: { shadowBlur: 12, shadowColor: 'rgba(99,102,241,0.5)' } },
    })
  if (showPaid.value)
    series.push({
      name: '已支付数',
      type: 'bar',
      data: orderStats.value.map((b) => b.paid),
      itemStyle: { borderRadius: [7, 7, 2, 2], color: barGradient('#34d399', '#10b981') },
      showBackground: true,
      backgroundStyle: { color: 'rgba(16,185,129,0.07)', borderRadius: [7, 7, 2, 2] },
      emphasis: { itemStyle: { shadowBlur: 12, shadowColor: 'rgba(16,185,129,0.5)' } },
    })
  if (showPaidAmount.value)
    series.push({
      name: '课时包盈收',
      type: 'line',
      yAxisIndex: 1,
      data: orderStats.value.map((b) => Number(b.paid_amount)),
      smooth: true,
      symbol: 'circle',
      symbolSize: 7,
      lineStyle: { width: 3, color: '#f59e0b', shadowBlur: 10, shadowColor: 'rgba(245,158,11,0.45)' },
      itemStyle: { color: '#f59e0b', borderColor: '#fff', borderWidth: 2 },
      areaStyle: { color: lineArea('#f59e0b') },
      markLine: {
        silent: true,
        symbol: 'none',
        lineStyle: { type: 'dashed', color: '#f59e0b', opacity: 0.6 },
        label: { formatter: '均值 {c}', fontSize: 11, color: '#b45309' },
        data: [{ type: 'average' }],
      },
    })
  if (showRefunds.value)
    series.push({
      name: '退款金额',
      type: 'line',
      yAxisIndex: 1,
      data: orderStats.value.map((b) => Number(b.refunds)),
      smooth: true,
      symbol: 'circle',
      symbolSize: 7,
      lineStyle: { width: 3, color: '#ef4444', shadowBlur: 10, shadowColor: 'rgba(239,68,68,0.4)' },
      itemStyle: { color: '#ef4444', borderColor: '#fff', borderWidth: 2 },
      areaStyle: { color: lineArea('#ef4444') },
    })
  trendChart.setOption(
    {
      grid: { left: 46, right: 52, top: 20, bottom: 28 },
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow', shadowStyle: { color: 'rgba(99,102,241,0.06)' } },
        backgroundColor: 'rgba(15,23,42,0.92)',
        borderWidth: 0,
        textStyle: { color: '#f1f5f9', fontSize: 12 },
        formatter: (params: any) => {
          const rows = (params as any[])
            .map((p) => {
              const unit = p.seriesName.includes('金额') || p.seriesName.includes('盈收') ? '元' : '单';
              const val =
                unit === '元' ? `¥${Number(p.value).toLocaleString('zh-CN')}` : `${p.value} 单`;
              return `${p.marker} ${p.seriesName}<span style="float:right;margin-left:24px;font-weight:700">${val}</span>`;
            })
            .join('<br/>');
          return `<div style="font-weight:700;margin-bottom:4px">${params[0].axisValue}</div>${rows}`;
        },
      },
      legend: {
        show: false,
      },
      xAxis: {
        type: 'category',
        data: labels,
        axisTick: { show: false },
        axisLine: { lineStyle: { color: '#e2e8f0' } },
        axisLabel: { color: '#94a3b8', fontSize: 11 },
      },
      yAxis: [
        {
          type: 'value',
          name: '单数',
          nameTextStyle: { color: '#94a3b8', fontSize: 11 },
          splitLine: { lineStyle: { type: 'dashed', color: '#eef2f7' } },
          axisLabel: { color: '#94a3b8', fontSize: 11 },
        },
        {
          type: 'value',
          name: '金额(元)',
          nameTextStyle: { color: '#94a3b8', fontSize: 11 },
          splitLine: { show: false },
          axisLabel: {
            color: '#94a3b8',
            fontSize: 11,
            formatter: (v: number) => (v >= 10000 ? `${(v / 10000).toFixed(0)}万` : v),
          },
        },
      ],
      series,
    },
    true,
  )
  trendChart.resize()
}

// ---- 课时创收 ----
const lessonStats = ref<LessonStats | null>(null)
const bySubject = ref<SubjectStat[]>([])
const byTeacher = ref<TeacherStat[]>([])
const finLoading = ref(false)
const finError = ref('')
const lessonEl = ref<HTMLDivElement | null>(null)
let lessonChart: echarts.ECharts | null = null

async function loadLessons() {
  finLoading.value = true
  finError.value = ''
  try {
    const params = {
      date_from: dateFrom.value || undefined,
      date_to: dateTo.value || undefined,
      campus: campus.value || undefined,
    }
    const [st, sub, tea] = await Promise.all([
      getLessonStats(params),
      getFinanceBySubject(params),
      getFinanceByTeacher(params),
    ])
    lessonStats.value = st
    bySubject.value = sub.items
    byTeacher.value = tea.items
  } catch {
    finError.value = '加载课时创收数据失败'
  } finally {
    finLoading.value = false
    renderLessons()
  }
}

async function renderLessons() {
  await nextTick()
  if (!lessonEl.value || !lessonStats.value) return
  if (!lessonChart || lessonChart.getDom() !== lessonEl.value) {
    if (lessonChart) lessonChart.dispose()
    lessonChart = echarts.init(lessonEl.value)
  }
  const daily = lessonStats.value.daily
  lessonChart.setOption(
    {
      grid: { left: 52, right: 20, top: 16, bottom: 44 },
      tooltip: { trigger: 'axis' },
      legend: { bottom: 0, icon: 'roundRect', itemWidth: 14, itemHeight: 6, textStyle: { fontSize: 12 } },
      xAxis: {
        type: 'category',
        data: daily.map((d) => d.label.slice(5)),
        axisTick: { show: false },
      },
      yAxis: { type: 'value', name: '课时', splitLine: { lineStyle: { type: 'dashed' } } },
      series: [
        {
          name: '每日消耗课时',
          type: 'bar',
          data: daily.map((d) => Number(d.lessons)),
          itemStyle: {
            borderRadius: [7, 7, 0, 0],
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: '#6366f1' },
              { offset: 1, color: '#06b6d4' },
            ]),
          },
          barMaxWidth: 26,
        },
      ],
    },
    true,
  )
  lessonChart.resize()
}

// ---- 总流水 ----
const allRecords = ref<LessonRecordOut[]>([])
const recordsTotal = ref(0)
const recordsSummary = ref({ amount_in: '0', amount_out: '0', amount_net: '0' })
const recordsLoading = ref(false)
const recordKeyword = ref('')
const recordType = ref('')
const recordsPage = ref(1)
const recordsPageSize = 20

const RECORD_TYPE_LABEL: Record<string, string> = {
  recharge: '充值入账',
  consume: '上课扣减',
  adjust: '人工调整',
  refund: '退款扣减',
}

async function loadRecords() {
  recordsLoading.value = true
  try {
    const data: AllRecordsOut = await listAllLessonRecords({
      keyword: recordKeyword.value.trim() || undefined,
      campus: campus.value || undefined,
      record_type: recordType.value || undefined,
      date_from: dateFrom.value || undefined,
      date_to: dateTo.value || undefined,
      limit: recordsPageSize,
      offset: (recordsPage.value - 1) * recordsPageSize,
    })
    allRecords.value = data.items
    recordsTotal.value = data.total
    recordsSummary.value = data.summary
  } catch {
    allRecords.value = []
  } finally {
    recordsLoading.value = false
  }
}

function onRecordsFilter() {
  recordsPage.value = 1
  loadRecords()
}

function recordTime(s: string): string {
  return s ? s.slice(0, 16).replace('T', ' ') : '—'
}

function reloadActive() {
  if (activeTab.value === 'orders') loadOrderStats()
  else if (activeTab.value === 'lessons') loadLessons()
  else onRecordsFilter()
}

async function switchTab(t: 'orders' | 'lessons' | 'records' | 'salary') {
  activeTab.value = t
  // tab 内容是 v-if 渲染，容器在切换后才挂载，需重绘图表以校正尺寸
  await nextTick()
  if (t === 'orders') {
    if (orderSummary.value) renderTrend()
    else loadOrderStats()
  }
  if (t === 'lessons') {
    if (lessonStats.value) renderLessons()
    else loadLessons()
  }
  if (t === 'records' && allRecords.value.length === 0) loadRecords()
}

watch([showOrders, showPaid, showRefunds, showPaidAmount], renderTrend)

function onResize() {
  trendChart?.resize()
  lessonChart?.resize()
}

function money(s: string | number | null | undefined): string {
  return Number(s || 0).toLocaleString('zh-CN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
}

function compactMoney(s: string | number): string {
  const v = Number(s || 0)
  if (v >= 10000) return `${(v / 10000).toFixed(1)}万`
  return v.toLocaleString('zh-CN', { maximumFractionDigits: 0 })
}

const DONUT_COLORS = ['#6366f1', '#10b981', '#f59e0b', '#8b5cf6', '#ef4444', '#06b6d4', '#ec4899', '#64748b']
const donutC = 2 * Math.PI * 54
const donutSegs = computed(() => {
  const total = bySubject.value.reduce((s, x) => s + Number(x.revenue), 0)
  let acc = 0
  return bySubject.value.map((x, i) => {
    const frac = total > 0 ? Number(x.revenue) / total : 0
    const seg = {
      subject: x.subject,
      revenue: x.revenue,
      pct: Math.round(frac * 100),
      color: DONUT_COLORS[i % DONUT_COLORS.length],
      len: Math.max(frac * donutC - 1.5, 0.1),
      offset: acc,
    }
    acc += frac * donutC
    return seg
  })
})
const subjectMax = computed(() => bySubject.value.reduce((m, x) => Math.max(m, Number(x.revenue)), 0))
const teacherMax = computed(() => byTeacher.value.reduce((m, x) => Math.max(m, Number(x.commission)), 0))

onMounted(async () => {
  if (auth.user?.role === 'teacher') {
    try {
      myPerms.value = await myPermissions()
    } catch {
      myPerms.value = {}
    }
    // 默认选中第一个可见 tab，避免落在无权限 tab 上一片空白
    const first = (['orders', 'lessons', 'records', 'salary'] as const).find((t) => visibleTabs.value[t])
    if (first) activeTab.value = first
  }
  defaultRange(13)
  try {
    campuses.value = await listCampuses()
  } catch {
    campuses.value = []
  }
  await loadOrderStats()
  window.addEventListener('resize', onResize)
})
onUnmounted(() => {
  window.removeEventListener('resize', onResize)
  trendChart?.dispose()
  lessonChart?.dispose()
})
</script>

<template>
  <div>
    <PageHead
      title="财务管理"
      eyebrow="FINANCE"
      sub="订单出入账 · 课时创收与教师绩效 · 时间/校区/类型多维筛选"
    />

    <div class="tabs">
      <button v-if="visibleTabs.orders" class="tab" :class="{ active: activeTab === 'orders' }" @click="switchTab('orders')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M4 6h16M4 12h16M4 18h10" /></svg>
        订单管理
      </button>
      <button v-if="visibleTabs.lessons" class="tab" :class="{ active: activeTab === 'lessons' }" @click="switchTab('lessons')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 17l6-6 4 4 8-8" /><path d="M15 7h6v6" /></svg>
        课时创收
      </button>
      <button v-if="visibleTabs.records" class="tab" :class="{ active: activeTab === 'records' }" @click="switchTab('records')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M8 2v4M16 2v4M3 10h18" /></svg>
        收支流水
      </button>
      <button v-if="visibleTabs.salary" class="tab" :class="{ active: activeTab === 'salary' }" @click="switchTab('salary')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /><path d="M3 9h18" /></svg>
        薪资核算
      </button>
    </div>

    <!-- 通用筛选条（薪资核算 tab 自带月份/职务/校区筛选，此处隐藏） -->
    <div v-if="activeTab !== 'salary'" class="filter-bar">
      <input v-model="dateFrom" type="date" class="filter-input" @change="reloadActive()" />
      <span class="filter-sep">—</span>
      <input v-model="dateTo" type="date" class="filter-input" @change="reloadActive()" />
      <select v-model="campus" class="filter-select" @change="reloadActive()">
        <option value="">全部校区</option>
        <option v-for="c in campuses" :key="c.id" :value="c.name">{{ c.name }}</option>
      </select>
      <template v-if="activeTab === 'records'">
        <select v-model="recordType" class="filter-select" @change="onRecordsFilter()">
          <option value="">全部类型</option>
          <option value="recharge">充值入账</option>
          <option value="consume">上课扣减</option>
          <option value="adjust">人工调整</option>
          <option value="refund">退款扣减</option>
        </select>
        <input v-model="recordKeyword" type="text" class="filter-input" placeholder="学员姓名/电话" @keyup.enter="onRecordsFilter()" />
        <button class="btn primary sm" @click="onRecordsFilter()">查询</button>
      </template>
      <span v-else class="formula-hint">应耗 = 排课计划课时 · 消耗 = 考勤扣减 · 创收 = Σ消耗×FIFO单价 · 盈收 = 创收 − 绩效</span>
    </div>

    <!-- 订单管理 tab -->
    <div v-if="activeTab === 'orders'">
      <section class="card">
        <div class="card-title">订单趋势</div>
        <div v-if="statsLoading" class="loading-tip">加载中…</div>
        <div v-else-if="!orderSummary" class="empty-tip">暂无数据</div>
        <template v-else>
          <div class="flow-kpis flow-4">
            <div class="flow-kpi indigo">
              <div class="flow-kpi-top">
                <span class="flow-ico in"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M4 6h16M4 12h16M4 18h10" /></svg></span>
                <span class="flow-tag">全部订单</span>
              </div>
              <div class="flow-amt">{{ orderSummary.orders }}<small> 单</small></div>
              <div class="flow-label">下单金额 ¥{{ money(orderSummary.order_amount) }}</div>
            </div>
            <div class="flow-kpi amber">
              <div class="flow-kpi-top">
                <span class="flow-ico warn"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M19 5 5 19" /><circle cx="9" cy="9" r="2.5" /><circle cx="15" cy="15" r="2.5" /></svg></span>
                <span class="flow-tag">漏斗转化</span>
              </div>
              <div class="flow-amt">{{ orderSummary.pay_rate }}<small> %</small></div>
              <div class="flow-label">已支付 {{ orderSummary.paid }} 单 · 未付款 {{ orderSummary.unpaid }} 单</div>
            </div>
            <div class="flow-kpi green">
              <div class="flow-kpi-top">
                <span class="flow-ico ok"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 17l6-6 4 4 8-8" /><path d="M15 7h6v6" /></svg></span>
                <span class="flow-tag">实际营收</span>
              </div>
              <div class="flow-amt">¥{{ money(orderSummary.paid_amount) }}</div>
              <div class="flow-label">课时包盈收 · 已确认订单实收</div>
            </div>
            <div class="flow-kpi red">
              <div class="flow-kpi-top">
                <span class="flow-ico out"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 3-6.7" /><path d="M3 4v5h5" /></svg></span>
                <span class="flow-tag">售后流失</span>
              </div>
              <div class="flow-amt">{{ orderSummary.refunded_count }}<small> 单</small></div>
              <div class="flow-label">退款 ¥{{ money(orderSummary.refunds) }}</div>
            </div>
          </div>
          <div class="chart-head">
            <div class="card-title">订单趋势 <span class="hint">柱 = 单数（左轴）· 线 = 金额（右轴）</span></div>
            <div class="series-toggles">
              <button class="toggle-pill indigo" :class="{ off: !showOrders }" @click="showOrders = !showOrders">下单数</button>
              <button class="toggle-pill green" :class="{ off: !showPaid }" @click="showPaid = !showPaid">已支付数</button>
              <button class="toggle-pill amber" :class="{ off: !showPaidAmount }" @click="showPaidAmount = !showPaidAmount">课时包盈收</button>
              <button class="toggle-pill red" :class="{ off: !showRefunds }" @click="showRefunds = !showRefunds">退款金额</button>
            </div>
          </div>
          <div ref="trendEl" class="echart"></div>
        </template>
      </section>

      <OrdersView />
    </div>

    <!-- 课时创收 tab -->
    <div v-else-if="activeTab === 'lessons'">
      <p v-if="finError" class="error-banner">{{ finError }}</p>
      <div v-if="finLoading" class="loading-tip">加载中…</div>
      <template v-else-if="lessonStats">
        <div class="kpi-grid kpi-6">
          <div class="kpi ico"><span class="kpi-ico blue"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M8 2v4M16 2v4M3 10h18" /></svg></span><div class="kpi-body"><span>应耗课时</span><strong>{{ lessonStats.planned_lessons }}</strong></div></div>
          <div class="kpi ico"><span class="kpi-ico green"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9" /><path d="M8.5 12.5l2.5 2.5 4.5-5.5" /></svg></span><div class="kpi-body"><span>消耗课时</span><strong>{{ lessonStats.consumed_lessons }}</strong></div></div>
          <div class="kpi ico"><span class="kpi-ico amber"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M19 5 5 19" /><circle cx="9" cy="9" r="2.5" /><circle cx="15" cy="15" r="2.5" /></svg></span><div class="kpi-body"><span>课耗率</span><strong>{{ lessonStats.consume_rate }}%</strong></div></div>
          <div class="kpi ico highlight"><span class="kpi-ico green"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 17l6-6 4 4 8-8" /><path d="M15 7h6v6" /></svg></span><div class="kpi-body"><span>课时创收</span><strong>¥{{ money(lessonStats.revenue) }}</strong></div></div>
          <div class="kpi ico"><span class="kpi-ico amber"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="9" r="5" /><path d="M9 13.5 7.5 21 12 19l4.5 2L15 13.5" /></svg></span><div class="kpi-body"><span>教师绩效</span><strong>¥{{ money(lessonStats.commission) }}</strong></div></div>
          <div class="kpi ico"><span class="kpi-ico blue"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /><path d="M3 9h18" /></svg></span><div class="kpi-body"><span>课时盈收</span><strong>¥{{ money(lessonStats.profit) }}</strong></div></div>
          <div class="kpi ico danger"><span class="kpi-ico red"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 9v4M12 17h.01" /><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" /></svg></span><div class="kpi-body"><span>欠费消耗（本期）</span><strong>{{ lessonStats.overdraft_lessons }}节 · ¥{{ money(lessonStats.overdraft_revenue) }}</strong></div></div>
          <div class="kpi ico danger"><span class="kpi-ico red"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 3" /></svg></span><div class="kpi-body"><span>应收欠款（当前）</span><strong>¥{{ money(lessonStats.receivable) }} · {{ lessonStats.debtors }}人</strong></div></div>
        </div>

        <section class="card">
          <div class="card-title">每日消耗课时 <span class="hint">共 {{ lessonStats.sessions }} 节排课</span></div>
          <div ref="lessonEl" class="echart"></div>
        </section>

        <div class="two-col">
          <section class="card">
            <div class="card-title">按科目创收占比</div>
            <div v-if="bySubject.length === 0" class="empty-tip">暂无数据</div>
            <div v-else class="donut-wrap">
              <svg viewBox="0 0 140 140" class="donut">
                <circle cx="70" cy="70" r="54" fill="none" stroke="var(--line)" stroke-width="18" />
                <circle
                  v-for="s in donutSegs"
                  :key="s.subject"
                  cx="70" cy="70" r="54" fill="none"
                  :stroke="s.color" stroke-width="18"
                  :stroke-dasharray="`${s.len} ${donutC - s.len}`"
                  :stroke-dashoffset="-s.offset"
                  transform="rotate(-90 70 70)"
                ><title>{{ s.subject }} ¥{{ money(s.revenue) }}（{{ s.pct }}%）</title></circle>
                <text x="70" y="66" text-anchor="middle" font-size="11" fill="var(--ink-3)">区间创收</text>
                <text x="70" y="86" text-anchor="middle" font-size="17" font-weight="800" fill="var(--ink)">¥{{ compactMoney(lessonStats.revenue) }}</text>
              </svg>
              <div class="donut-legend">
                <div v-for="s in donutSegs" :key="s.subject" class="legend-row">
                  <i class="dot" :style="{ background: s.color }" />
                  <span class="legend-name">{{ s.subject }}</span>
                  <span class="legend-val">¥{{ money(s.revenue) }}</span>
                  <span class="legend-pct">{{ s.pct }}%</span>
                </div>
              </div>
            </div>
            <div v-if="bySubject.length > 0" class="subject-bars">
              <div v-for="s in bySubject" :key="s.subject" class="subject-bar-row">
                <div class="subject-bar-head">
                  <strong>{{ s.subject }}</strong>
                  <span class="muted-sm">{{ s.lessons }} 课时 · {{ s.sessions }} 节</span>
                  <span class="subject-amt">¥{{ money(s.revenue) }}</span>
                </div>
                <div class="bar-track"><div class="bar-fill" :style="{ width: `${subjectMax > 0 ? (Number(s.revenue) / subjectMax) * 100 : 0}%` }" /></div>
              </div>
            </div>
          </section>
          <section class="card">
            <div class="card-title">教师绩效排行</div>
            <div v-if="byTeacher.length === 0" class="empty-tip">暂无数据</div>
            <div v-else class="rank-list">
              <div v-for="(t, i) in byTeacher" :key="t.teacher_id || 'none'" class="rank-row" :class="{ top: i < 3 }">
                <span class="rank-no" :class="`r${i + 1}`">{{ i + 1 }}</span>
                <span class="rank-avatar">{{ (t.teacher_name || '?').slice(0, 1) }}</span>
                <div class="rank-main">
                  <div class="rank-head"><strong>{{ t.teacher_name }}</strong><span class="muted-sm">{{ t.sessions }} 节 · 创收 ¥{{ money(t.revenue) }}</span></div>
                  <div class="bar-track slim"><div class="bar-fill green" :style="{ width: `${teacherMax > 0 ? (Number(t.commission) / teacherMax) * 100 : 0}%` }" /></div>
                </div>
                <strong class="rank-amt">¥{{ money(t.commission) }}</strong>
              </div>
            </div>
          </section>
        </div>
      </template>
    </div>

    <!-- 收支流水 tab -->
    <div v-else-if="activeTab === 'records'">
      <div class="flow-kpis">
        <div class="flow-kpi in">
          <div class="flow-kpi-top">
            <span class="flow-ico in"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 17l6-6 4 4 8-8" /><path d="M15 7h6v6" /></svg></span>
            <span class="flow-tag">累计入账</span>
          </div>
          <div class="flow-amt">¥{{ money(recordsSummary.amount_in) }}</div>
          <div class="flow-label">充值 / 补课时接收金额</div>
        </div>
        <div class="flow-kpi out">
          <div class="flow-kpi-top">
            <span class="flow-ico out"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 3-6.7" /><path d="M3 4v5h5" /></svg></span>
            <span class="flow-tag">冲销退费</span>
          </div>
          <div class="flow-amt">¥{{ money(recordsSummary.amount_out) }}</div>
          <div class="flow-label">退费 / 人工减课时冲减</div>
        </div>
        <div class="flow-kpi net">
          <div class="flow-kpi-top">
            <span class="flow-ico net"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /><path d="M3 9h18" /></svg></span>
            <span class="flow-tag">实收净额</span>
          </div>
          <div class="flow-amt">¥{{ money(recordsSummary.amount_net) }}</div>
          <div class="flow-label">入账 − 冲销后的净收入</div>
        </div>
      </div>
      <section class="card flow-card">
        <div class="flow-head">
          <div>
            <div class="card-title">全学员课时流水</div>
            <div class="hint">共 {{ recordsTotal }} 条 · 带单价的调账计入金额</div>
          </div>
          <div class="flow-legend">
            <span class="pill recharge">充值入账</span>
            <span class="pill consume">上课扣减</span>
            <span class="pill adjust">人工调整</span>
            <span class="pill refund">退款扣减</span>
          </div>
        </div>
        <div v-if="recordsLoading" class="loading-tip">加载中…</div>
        <div v-else-if="allRecords.length === 0" class="empty-tip">暂无流水</div>
        <table v-else class="flow-table">
          <thead>
            <tr><th>时间</th><th>学员</th><th>校区</th><th>类型</th><th>课时</th><th>单价</th><th>金额</th><th>备注</th><th>操作人</th></tr>
          </thead>
          <tbody>
            <tr v-for="r in allRecords" :key="r.id">
              <td><div class="ft-time">{{ r.created_at ? r.created_at.slice(0, 10) : '—' }}<small>{{ r.created_at ? r.created_at.slice(11, 16) : '' }}</small></div></td>
              <td><div class="ft-user"><span class="ft-avatar">{{ (r.student_name || '?').slice(0, 1) }}</span><strong>{{ r.student_name }}</strong></div></td>
              <td><span class="ft-campus">{{ r.campus || '—' }}</span></td>
              <td><span class="pill" :class="r.record_type">{{ RECORD_TYPE_LABEL[r.record_type] || r.record_type }}</span></td>
              <td><span class="delta-chip" :class="Number(r.delta) >= 0 ? 'up' : 'down'">{{ Number(r.delta) > 0 ? '+' : '' }}{{ r.delta }}</span></td>
              <td class="num">{{ r.unit_price !== null && r.unit_price !== undefined ? `¥${money(r.unit_price)}` : '—' }}</td>
              <td class="num strong" :class="r.amount !== null && Number(r.amount) < 0 ? 'neg' : ''">{{ r.amount !== null && r.amount !== undefined ? `¥${money(r.amount)}` : '—' }}</td>
              <td class="remark" :title="r.remark || ''">{{ r.remark || '—' }}</td>
              <td class="op">{{ r.operator_name || '—' }}</td>
            </tr>
          </tbody>
        </table>
        <div class="flow-pager">
          <button class="pager-btn" :disabled="recordsPage <= 1" @click="recordsPage--; loadRecords()">‹ 上一页</button>
          <span class="muted-sm">第 {{ recordsPage }} 页 · 共 {{ recordsTotal }} 条</span>
          <button class="pager-btn" :disabled="recordsPage * recordsPageSize >= recordsTotal" @click="recordsPage++; loadRecords()">下一页 ›</button>
        </div>
      </section>
    </div>

    <!-- 薪资核算 tab -->
    <div v-else-if="activeTab === 'salary'">
      <SalaryPanel />
    </div>
  </div>
</template>

<style scoped>
.tabs { display: flex; gap: 8px; margin-bottom: 16px; }
.tab { display: inline-flex; align-items: center; gap: 7px; padding: 8px 20px; border-radius: 999px; border: 1px solid var(--line); background: var(--surface); color: var(--ink-3); font-size: 13.5px; cursor: pointer; transition: all 0.2s ease; }
.tab svg { width: 15px; height: 15px; }
.tab:hover { border-color: #c7d2fe; color: #4f46e5; }
.tab.active { background: linear-gradient(135deg, #6366f1, #06b6d4); color: #fff; border-color: transparent; font-weight: 600; box-shadow: 0 4px 12px rgba(99, 102, 241, 0.35); }
.card { background: var(--surface); border: 1px solid var(--line); border-radius: 16px; padding: 18px 20px; margin-bottom: 16px; }
.card-title { font-size: 15px; font-weight: 700; margin-bottom: 12px; }
.card-title .hint { font-size: 12px; font-weight: 400; color: var(--ink-3); margin-left: 8px; }
.filter-bar { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; flex-wrap: wrap; }
.filter-select, .filter-input { padding: 8px 12px; border: 1px solid var(--line); border-radius: 10px; background: var(--surface); font-size: 13px; color: var(--ink-2); }
.filter-sep { color: var(--ink-3); }
.check { display: flex; align-items: center; gap: 5px; font-size: 13px; color: var(--ink-2); cursor: pointer; }
.formula-hint { font-size: 12px; color: var(--ink-3); }
.error-banner { background: var(--danger-soft); color: var(--danger); padding: 10px 14px; border-radius: 10px; margin-bottom: 14px; font-size: 13px; }
.kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; margin-bottom: 16px; }
.kpi-5 { grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); }
.kpi-6 { grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); }
.kpi { background: var(--surface); border: 1px solid var(--line); border-radius: 14px; padding: 14px 16px; display: flex; flex-direction: column; gap: 6px; }
.kpi span { font-size: 12px; color: var(--ink-3); }
.kpi strong { font-size: 20px; font-weight: 800; }
.kpi.highlight { border-color: var(--brand); background: var(--brand-soft); }
.kpi.highlight strong { color: var(--brand-strong); }
.kpi.danger strong { color: var(--danger); }
.kpi.ico { flex-direction: row; align-items: center; gap: 12px; }
.kpi-ico { width: 42px; height: 42px; flex-shrink: 0; display: flex; align-items: center; justify-content: center; border-radius: 13px; }
.kpi-ico svg { width: 21px; height: 21px; }
.kpi-ico.blue { background: #e8effe; color: #2f6fed; }
.kpi-ico.green { background: #e2f5ea; color: #0e9f6e; }
.kpi-ico.amber { background: #fdf0dd; color: #c2570b; }
.kpi-ico.red { background: #fdecec; color: #d92d20; }
.kpi-body { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.sub-kpis { margin: -8px 0 14px; }
.echart { width: 100%; height: 340px; }
.loading-tip, .empty-tip { text-align: center; color: var(--ink-3); padding: 20px 0; font-size: 13px; }
.donut-wrap { display: flex; align-items: center; gap: 18px; margin: 6px 0 14px; flex-wrap: wrap; }
.donut { width: 150px; height: 150px; flex-shrink: 0; }
.donut-legend { flex: 1; min-width: 180px; display: flex; flex-direction: column; gap: 7px; }
.legend-row { display: flex; align-items: center; gap: 8px; font-size: 12.5px; }
.legend-name { flex: 1; color: var(--ink-2); font-weight: 600; }
.legend-val { color: var(--ink); font-weight: 700; }
.legend-pct { color: var(--ink-3); min-width: 38px; text-align: right; }
.dot { display: inline-block; width: 10px; height: 10px; border-radius: 3px; margin-right: 5px; }
.subject-bars { display: flex; flex-direction: column; gap: 12px; }
.subject-bar-head { display: flex; align-items: baseline; gap: 8px; font-size: 13px; margin-bottom: 5px; }
.subject-bar-head strong { font-size: 13.5px; }
.muted-sm { font-size: 11.5px; color: var(--ink-3); }
.subject-amt { margin-left: auto; font-weight: 800; color: var(--ink); }
.bar-track { height: 9px; border-radius: 6px; background: var(--surface-alt); overflow: hidden; }
.bar-track.slim { height: 7px; margin-top: 6px; }
.bar-fill { height: 100%; border-radius: 6px; background: var(--brand); }
.bar-fill.green { background: #10b981; }
.rank-list { display: flex; flex-direction: column; }
.rank-row { display: flex; align-items: center; gap: 11px; padding: 11px 4px; border-bottom: 1px solid var(--line); }
.rank-row:last-child { border-bottom: none; }
.rank-no { width: 24px; height: 24px; flex-shrink: 0; display: flex; align-items: center; justify-content: center; border-radius: 8px; font-size: 12px; font-weight: 800; background: var(--surface-alt); color: var(--ink-3); }
.rank-no.r1 { background: #fdf0dd; color: #c2570b; }
.rank-no.r2 { background: #e8effe; color: #2f6fed; }
.rank-no.r3 { background: #e2f5ea; color: #0e9f6e; }
.rank-avatar { width: 34px; height: 34px; flex-shrink: 0; display: flex; align-items: center; justify-content: center; border-radius: 50%; background: var(--brand-soft); color: var(--brand-strong); font-weight: 800; font-size: 14px; }
.rank-main { flex: 1; min-width: 0; }
.rank-head { display: flex; align-items: baseline; gap: 8px; font-size: 13px; }
.rank-amt { font-size: 15px; color: var(--brand-strong); white-space: nowrap; }
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
@media (max-width: 900px) { .two-col { grid-template-columns: 1fr; } }
.ledger-table .pos { color: #0e9f6e; font-weight: 700; }
.ledger-table .neg { color: #d64545; font-weight: 700; }
.ledger-table .remark { max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pill { display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: 12px; background: var(--surface-alt); color: var(--ink-2); }
.pill.recharge { background: #e2f5ea; color: #0e9f6e; }
.pill.consume { background: #e8effe; color: #2f6fed; }
.pill.adjust { background: #fdf0dd; color: #c2570b; }
.pill.refund { background: #fde4e4; color: #d64545; }
.kpi-ico.red { background: #fde4e4; color: #d64545; }
.kpi-ico.blue { background: #e8effe; color: #2f6fed; }
.pager { display: flex; align-items: center; justify-content: center; gap: 12px; padding: 12px 0 4px; }
.btn.sm { padding: 6px 12px; font-size: 12px; }
/* ---- 收支流水高级感 ---- */
.flow-kpis { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin-bottom: 16px; }
@media (max-width: 900px) { .flow-kpis { grid-template-columns: 1fr; } }
.flow-kpi { position: relative; overflow: hidden; border-radius: 16px; padding: 18px 20px; background: var(--card, #fff); border: 1px solid var(--line); box-shadow: 0 1px 2px rgba(16, 24, 40, 0.05); }
.flow-kpi::after { content: ''; position: absolute; left: 0; top: 0; bottom: 0; width: 4px; border-radius: 4px; }
.flow-kpi.in::after { background: linear-gradient(180deg, #12b76a, #067647); }
.flow-kpi.out::after { background: linear-gradient(180deg, #f97066, #b42318); }
.flow-kpi.indigo::after { background: linear-gradient(180deg, #818cf8, #4f46e5); }
.flow-kpi.amber::after { background: linear-gradient(180deg, #fbbf24, #b45309); }
.flow-kpi.green::after { background: linear-gradient(180deg, #34d399, #047857); }
.flow-kpi.red::after { background: linear-gradient(180deg, #f87171, #b91c1c); }
.flow-4 { grid-template-columns: repeat(4, 1fr); }
@media (max-width: 1100px) { .flow-4 { grid-template-columns: repeat(2, 1fr); } }
.flow-ico.warn { background: #fef3c7; color: #b45309; }
.flow-ico.ok { background: #dcfae6; color: #067647; }
.chart-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; margin: 4px 0 12px; }
.chart-head .card-title { margin-bottom: 0; }
.series-toggles { display: flex; gap: 8px; flex-wrap: wrap; }
.toggle-pill { padding: 6px 14px; border-radius: 999px; font-size: 12.5px; font-weight: 600; cursor: pointer; border: 1px solid transparent; color: #fff; transition: all 0.2s ease; }
.toggle-pill.indigo { background: linear-gradient(135deg, #818cf8, #6366f1); box-shadow: 0 2px 8px rgba(99, 102, 241, 0.3); }
.toggle-pill.green { background: linear-gradient(135deg, #34d399, #10b981); box-shadow: 0 2px 8px rgba(16, 185, 129, 0.3); }
.toggle-pill.amber { background: linear-gradient(135deg, #fbbf24, #f59e0b); box-shadow: 0 2px 8px rgba(245, 158, 11, 0.3); }
.toggle-pill.red { background: linear-gradient(135deg, #f87171, #ef4444); box-shadow: 0 2px 8px rgba(239, 68, 68, 0.3); }
.toggle-pill.off { background: var(--surface-alt); color: var(--ink-3); box-shadow: none; border-color: var(--line); }
.echart.tall { height: 380px; }
.flow-kpi.net { color: #fff; border: none; background: linear-gradient(135deg, #155eef 0%, #0e9384 130%); box-shadow: 0 10px 24px rgba(21, 94, 239, 0.28); }
.flow-kpi-top { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.flow-ico { width: 38px; height: 38px; border-radius: 12px; display: flex; align-items: center; justify-content: center; }
.flow-ico svg { width: 20px; height: 20px; }
.flow-ico.in { background: #dcfae6; color: #067647; }
.flow-ico.out { background: #fee4e2; color: #b42318; }
.flow-ico.net { background: rgba(255, 255, 255, 0.18); color: #fff; }
.flow-tag { font-size: 12px; color: var(--ink-3); background: var(--surface-alt); padding: 3px 10px; border-radius: 999px; white-space: nowrap; }
.net .flow-tag { background: rgba(255, 255, 255, 0.18); color: #fff; }
.flow-amt { font-size: 28px; font-weight: 800; letter-spacing: -0.5px; font-variant-numeric: tabular-nums; }
.flow-label { font-size: 12px; color: var(--ink-3); margin-top: 4px; }
.net .flow-label { color: rgba(255, 255, 255, 0.82); }
.flow-card { overflow: hidden; }
.flow-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; flex-wrap: wrap; padding: 18px 20px 4px; }
.flow-head .hint { font-size: 12px; color: var(--ink-3); margin-top: 4px; }
.flow-legend { display: flex; gap: 8px; flex-wrap: wrap; padding-top: 4px; }
.flow-table { width: 100%; border-collapse: separate; border-spacing: 0; font-size: 13px; margin-top: 8px; }
.flow-table thead th { text-align: left; font-size: 12px; font-weight: 600; color: var(--ink-3); padding: 10px 12px; background: var(--surface-alt); white-space: nowrap; }
.flow-table thead th:first-child { padding-left: 20px; }
.flow-table thead th:last-child { padding-right: 20px; }
.flow-table tbody td { padding: 12px; border-bottom: 1px solid var(--line); vertical-align: middle; }
.flow-table tbody td:first-child { padding-left: 20px; }
.flow-table tbody td:last-child { padding-right: 20px; }
.flow-table tbody tr { transition: background 0.15s ease; }
.flow-table tbody tr:hover { background: var(--brand-soft, #f4f7ff); }
.flow-table tbody tr:last-child td { border-bottom: none; }
.ft-time { font-variant-numeric: tabular-nums; font-weight: 600; white-space: nowrap; }
.ft-time small { display: block; font-weight: 400; font-size: 11px; color: var(--ink-3); }
.ft-user { display: flex; align-items: center; gap: 10px; white-space: nowrap; }
.ft-avatar { width: 30px; height: 30px; flex-shrink: 0; display: inline-flex; align-items: center; justify-content: center; border-radius: 50%; font-size: 13px; font-weight: 800; color: #fff; background: linear-gradient(135deg, #155eef, #0e9384); }
.ft-campus { color: var(--ink-2); white-space: nowrap; }
.delta-chip { display: inline-block; min-width: 64px; text-align: center; padding: 3px 10px; border-radius: 999px; font-weight: 700; font-variant-numeric: tabular-nums; white-space: nowrap; }
.delta-chip.up { background: #dcfae6; color: #067647; }
.delta-chip.down { background: #fee4e2; color: #b42318; }
.flow-table .num { font-variant-numeric: tabular-nums; white-space: nowrap; }
.flow-table .num.strong { font-weight: 800; }
.flow-table .num.neg { color: #d92d20; }
.flow-table .remark { max-width: 240px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--ink-2); }
.flow-table .op { color: var(--ink-2); white-space: nowrap; }
.flow-pager { display: flex; align-items: center; justify-content: center; gap: 14px; padding: 14px 0 16px; }
.pager-btn { padding: 7px 16px; border-radius: 999px; border: 1px solid var(--line); background: var(--card, #fff); font-size: 13px; cursor: pointer; transition: all 0.15s ease; }
.pager-btn:hover:not(:disabled) { border-color: var(--brand, #155eef); color: var(--brand, #155eef); }
.pager-btn:disabled { opacity: 0.4; cursor: not-allowed; }
</style>
