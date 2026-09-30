<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import * as echarts from 'echarts'

import PageHead from '@/components/PageHead.vue'
import OrdersView from '@/views/orders/OrdersView.vue'
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

const activeTab = ref<'orders' | 'lessons'>('orders')

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

function renderTrend() {
  if (!trendEl.value) return
  if (!trendChart) trendChart = echarts.init(trendEl.value)
  const labels = orderStats.value.map((b) => b.label.slice(5))
  const series: echarts.SeriesOption[] = []
  if (showOrders.value)
    series.push({
      name: '下单数',
      type: 'bar',
      data: orderStats.value.map((b) => b.orders),
      itemStyle: { borderRadius: [6, 6, 0, 0], color: '#6366f1' },
      barGap: '20%',
    })
  if (showPaid.value)
    series.push({
      name: '已支付数',
      type: 'bar',
      data: orderStats.value.map((b) => b.paid),
      itemStyle: { borderRadius: [6, 6, 0, 0], color: '#10b981' },
    })
  if (showRefunds.value)
    series.push({
      name: '退款金额',
      type: 'line',
      yAxisIndex: 1,
      data: orderStats.value.map((b) => Number(b.refunds)),
      smooth: true,
      lineStyle: { width: 2.5, color: '#ef4444' },
      itemStyle: { color: '#ef4444' },
      symbolSize: 6,
    })
  if (showPaidAmount.value)
    series.push({
      name: '课时包盈收',
      type: 'line',
      yAxisIndex: 1,
      data: orderStats.value.map((b) => Number(b.paid_amount)),
      smooth: true,
      lineStyle: { width: 2.5, color: '#f59e0b' },
      itemStyle: { color: '#f59e0b' },
      symbolSize: 6,
    })
  trendChart.setOption(
    {
      grid: { left: 48, right: 56, top: 44, bottom: 30 },
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      legend: { top: 8, textStyle: { fontSize: 12 } },
      xAxis: { type: 'category', data: labels, axisTick: { show: false } },
      yAxis: [
        { type: 'value', name: '单数', splitLine: { lineStyle: { type: 'dashed' } } },
        {
          type: 'value',
          name: '金额(元)',
          splitLine: { show: false },
          axisLabel: { formatter: (v: number) => (v >= 10000 ? `${(v / 10000).toFixed(0)}万` : v) },
        },
      ],
      series,
    },
    true,
  )
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

function renderLessons() {
  if (!lessonEl.value || !lessonStats.value) return
  if (!lessonChart) lessonChart = echarts.init(lessonEl.value)
  const daily = lessonStats.value.daily
  lessonChart.setOption(
    {
      grid: { left: 52, right: 20, top: 40, bottom: 30 },
      tooltip: { trigger: 'axis' },
      legend: { top: 8, textStyle: { fontSize: 12 } },
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
}

function switchTab(t: 'orders' | 'lessons') {
  activeTab.value = t
  if (t === 'lessons' && !lessonStats.value) loadLessons()
}

watch([showOrders, showPaid, showRefunds, showPaidAmount], renderTrend)

function onResize() {
  trendChart?.resize()
  lessonChart?.resize()
}

function money(s: string | number): string {
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
      <button class="tab" :class="{ active: activeTab === 'orders' }" @click="switchTab('orders')">
        订单管理
      </button>
      <button class="tab" :class="{ active: activeTab === 'lessons' }" @click="switchTab('lessons')">
        课时创收
      </button>
    </div>

    <!-- 通用筛选条 -->
    <div class="filter-bar">
      <input v-model="dateFrom" type="date" class="filter-input" @change="activeTab === 'orders' ? loadOrderStats() : loadLessons()" />
      <span class="filter-sep">—</span>
      <input v-model="dateTo" type="date" class="filter-input" @change="activeTab === 'orders' ? loadOrderStats() : loadLessons()" />
      <select v-model="campus" class="filter-select" @change="activeTab === 'orders' ? loadOrderStats() : loadLessons()">
        <option value="">全部校区</option>
        <option v-for="c in campuses" :key="c.id" :value="c.name">{{ c.name }}</option>
      </select>
      <template v-if="activeTab === 'orders'">
        <label class="check"><input v-model="showOrders" type="checkbox" />下单数</label>
        <label class="check"><input v-model="showPaid" type="checkbox" />已支付数</label>
        <label class="check"><input v-model="showPaidAmount" type="checkbox" />课时包盈收</label>
        <label class="check"><input v-model="showRefunds" type="checkbox" />退款金额</label>
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
          <div class="kpi-grid kpi-5">
            <div class="kpi ico">
              <span class="kpi-ico blue"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M4 6h16M4 12h16M4 18h10" /></svg></span>
              <div class="kpi-body"><span>下单总数</span><strong>{{ orderSummary.orders }} 单</strong></div>
            </div>
            <div class="kpi ico">
              <span class="kpi-ico red"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 3-6.7" /><path d="M3 4v5h5" /></svg></span>
              <div class="kpi-body"><span>退课数</span><strong>{{ orderSummary.refunded_count }} 单</strong></div>
            </div>
            <div class="kpi ico">
              <span class="kpi-ico amber"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M19 5 5 19" /><circle cx="9" cy="9" r="2.5" /><circle cx="15" cy="15" r="2.5" /></svg></span>
              <div class="kpi-body"><span>支付转化率</span><strong>{{ orderSummary.pay_rate }}%</strong></div>
            </div>
            <div class="kpi ico highlight">
              <span class="kpi-ico green"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /><path d="M3 9h18" /></svg></span>
              <div class="kpi-body"><span>课时包盈收</span><strong>¥{{ money(orderSummary.paid_amount) }}</strong></div>
            </div>
            <div class="kpi ico danger">
              <span class="kpi-ico red"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 3-6.7" /><path d="M3 4v5h5" /></svg></span>
              <div class="kpi-body"><span>退款金额</span><strong>¥{{ money(orderSummary.refunds) }}</strong></div>
            </div>
          </div>
          <div class="sub-kpis muted-sm">
            已支付 {{ orderSummary.paid }} 单 · 未付款 {{ orderSummary.unpaid }} 单 · 下单金额 ¥{{ money(orderSummary.order_amount) }}
          </div>
          <div ref="trendEl" class="echart"></div>
        </template>
      </section>

      <OrdersView />
    </div>

    <!-- 课时创收 tab -->
    <div v-else>
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
  </div>
</template>

<style scoped>
.tabs { display: flex; gap: 8px; margin-bottom: 16px; }
.tab { padding: 8px 20px; border-radius: 999px; border: 1px solid var(--line); background: var(--surface); color: var(--ink-3); font-size: 13.5px; cursor: pointer; }
.tab.active { background: linear-gradient(135deg, #6366f1, #06b6d4); color: #fff; border-color: transparent; font-weight: 600; }
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
</style>
