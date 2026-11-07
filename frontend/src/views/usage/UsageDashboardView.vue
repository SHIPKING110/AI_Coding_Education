<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart, LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

import PageHead from '@/components/PageHead.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import {
  createPrice,
  deletePrice,
  deleteReconciliation,
  exportUsageCsv,
  getUsageSettings,
  getUsageStats,
  listPrices,
  listReconciliations,
  listUsageEvents,
  repriceUnpricedUsage,
  updatePrice,
  updateUsageSettings,
  upsertReconciliation,
  type LedgerProvider,
  type ModelPrice,
  type ReconciliationRow,
  type UsageBudget,
  type UsageEvent,
  type UsageStats,
} from '@/api/usage'

echarts.use([LineChart, BarChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])

const days = ref(30)
const loading = ref(false)
const error = ref('')
const stats = ref<UsageStats | null>(null)

const events = ref<UsageEvent[]>([])
const eventTotal = ref(0)
const page = ref(1)
const pageSize = 15
const filterModule = ref('')
const filterPriced = ref('')
const eventsLoading = ref(false)

const prices = ref<ModelPrice[]>([])
const repricing = ref(false)
const priceDialog = ref(false)
const priceSaving = ref(false)
const priceForm = ref({
  id: '',
  provider_host: '',
  model_pattern: '',
  currency: 'CNY',
  input_per_1m: 0,
  output_per_1m: 0,
  cache_read_per_1m: 0,
  cache_write_per_1m: 0,
  effective_from: '',
  source_note: '',
})

const budget = ref<UsageBudget>({ monthly_budget: 0, alert_ratio: 0.8 })
const budgetSaving = ref(false)
const budgetTip = ref('')

const reconMonth = ref(new Date().toISOString().slice(0, 7))
const recons = ref<ReconciliationRow[]>([])
const ledger = ref<LedgerProvider[]>([])
const reconSaving = ref(false)
const reconForm = ref({ provider: '', billed_amount: 0, note: '' })
const pending = ref<{ title: string; message: string; run: () => void | Promise<void> } | null>(null)

function ask(title: string, message: string, run: () => void | Promise<void>) {
  pending.value = { title, message, run }
}
async function confirmPending() {
  const p = pending.value
  pending.value = null
  if (p) await p.run()
}

const lineEl = ref<HTMLDivElement | null>(null)
const barEl = ref<HTMLDivElement | null>(null)
let lineChart: echarts.ECharts | null = null
let barChart: echarts.ECharts | null = null

const totalTokens = computed(() =>
  stats.value ? stats.value.input_tokens + stats.value.output_tokens : 0,
)
const today = computed(() => {
  const series = stats.value?.series || []
  return series.length ? series[series.length - 1] : null
})
// 口径自检：分模块/分归属/分类型合计必须等于总额，页面直接公示
const consistencyOk = computed(() => {
  const s = stats.value
  if (!s) return true
  const near = (v: number) => Math.abs(v - s.cost_estimate) < 0.01
  return (
    near(s.by_kind.reduce((a, b) => a + b.cost, 0)) &&
    near(s.by_module.reduce((a, b) => a + b.cost, 0)) &&
    near(s.by_owner.reduce((a, b) => a + b.cost, 0))
  )
})

function money(v: number | null | undefined) {
  if (v == null) return '-'
  return `¥${Number(v).toFixed(2)}`
}
function tokens(v: number | null | undefined) {
  return (v ?? 0).toLocaleString()
}
function pct(v: number | null | undefined) {
  return v == null ? '-' : `${Math.round(v * 100)}%`
}
function sourceLabel(s: string) {
  return s === 'provider' ? '厂商' : s === 'estimated' ? '估算' : s
}
const MODULE_LABELS: Record<string, string> = {
  agent: 'Agent 工作台',
  report: '报告总结',
  evaluation: '学员评估',
  rag_eval: 'RAG 评测',
  assignment: 'AI 习题',
  feedback: '客户反馈',
  parent_service: '家长客服',
  embedding: 'Embedding',
  rerank: 'Rerank',
  config_test: '连通性检查',
}
function moduleLabel(m: string | null | undefined) {
  if (!m) return '未知'
  return MODULE_LABELS[m] || m
}

async function loadStats() {
  loading.value = true
  error.value = ''
  try {
    stats.value = await getUsageStats(days.value)
    await nextTick()
    renderCharts()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}

function renderCharts() {
  if (!stats.value) return
  const series = stats.value.series
  const daysX = series.map((p) => p.day.slice(5))
  if (lineEl.value) {
    if (!lineChart) lineChart = echarts.init(lineEl.value)
    lineChart.setOption(
      {
        tooltip: { trigger: 'axis' },
        legend: { data: ['平台成本', '教师成本'], top: 0 },
        grid: { left: 48, right: 16, top: 36, bottom: 28 },
        xAxis: { type: 'category', data: daysX },
        yAxis: { type: 'value', name: '元' },
        series: [
          {
            name: '平台成本',
            type: 'line',
            stack: 'cost',
            areaStyle: { opacity: 0.15 },
            data: series.map((p) => Number(p.cost_platform.toFixed(4))),
          },
          {
            name: '教师成本',
            type: 'line',
            stack: 'cost',
            areaStyle: { opacity: 0.15 },
            data: series.map((p) => Number(p.cost_teacher.toFixed(4))),
          },
        ],
      },
      true,
    )
  }
  const modules = stats.value.by_module.slice(0, 8).reverse()
  if (barEl.value) {
    if (!barChart) barChart = echarts.init(barEl.value)
    barChart.setOption(
      {
        tooltip: { trigger: 'axis' },
        grid: { left: 96, right: 24, top: 16, bottom: 24 },
        xAxis: { type: 'value', name: '元' },
        yAxis: { type: 'category', data: modules.map((m) => moduleLabel(m.module)) },
        series: [
          {
            type: 'bar',
            data: modules.map((m) => Number(m.cost.toFixed(4))),
            itemStyle: { borderRadius: [0, 6, 6, 0] },
          },
        ],
      },
      true,
    )
  }
}

async function loadEvents() {
  eventsLoading.value = true
  try {
    const res = await listUsageEvents({
      days: days.value,
      page: page.value,
      page_size: pageSize,
      module: filterModule.value || undefined,
      priced_status: filterPriced.value || undefined,
    })
    events.value = res.items
    eventTotal.value = res.total
  } catch (e) {
    error.value = e instanceof Error ? e.message : '明细加载失败'
  } finally {
    eventsLoading.value = false
  }
}

async function loadPrices() {
  try {
    prices.value = await listPrices()
  } catch {
    /* 兼容旧部署：价格表不可用时不影响其它面板 */
  }
}

async function loadBudget() {
  try {
    budget.value = await getUsageSettings()
  } catch {
    /* ignore */
  }
}

async function loadRecons() {
  try {
    const res = await listReconciliations(reconMonth.value)
    recons.value = res.items
    ledger.value = res.ledger.providers || []
  } catch {
    /* ignore */
  }
}

async function loadAll() {
  page.value = 1
  await Promise.all([loadStats(), loadEvents(), loadPrices(), loadBudget(), loadRecons()])
}

function applyRange(d: number) {
  days.value = d
  page.value = 1
  void loadStats()
  void loadEvents()
}

async function downloadCsv() {
  try {
    await exportUsageCsv({ days: days.value, module: filterModule.value || undefined })
  } catch (e) {
    error.value = e instanceof Error ? e.message : '导出失败'
  }
}

function openPriceDialog(row?: ModelPrice) {
  priceForm.value = row
    ? {
        id: row.id,
        provider_host: row.provider_host,
        model_pattern: row.model_pattern,
        currency: row.currency,
        input_per_1m: row.input_per_1m,
        output_per_1m: row.output_per_1m,
        cache_read_per_1m: row.cache_read_per_1m,
        cache_write_per_1m: row.cache_write_per_1m,
        effective_from: (row.effective_from || '').slice(0, 19),
        source_note: row.source_note,
      }
    : {
        id: '',
        provider_host: '',
        model_pattern: '',
        currency: 'CNY',
        input_per_1m: 0,
        output_per_1m: 0,
        cache_read_per_1m: 0,
        cache_write_per_1m: 0,
        effective_from: '',
        source_note: '',
      }
  priceDialog.value = true
}

async function savePrice() {
  priceSaving.value = true
  try {
    const f = priceForm.value
    const payload: Record<string, unknown> = {
      provider_host: f.provider_host.trim(),
      model_pattern: f.model_pattern.trim(),
      currency: f.currency || 'CNY',
      input_per_1m: Number(f.input_per_1m) || 0,
      output_per_1m: Number(f.output_per_1m) || 0,
      cache_read_per_1m: Number(f.cache_read_per_1m) || 0,
      cache_write_per_1m: Number(f.cache_write_per_1m) || 0,
      source_note: f.source_note || '',
    }
    if (f.effective_from) payload.effective_from = f.effective_from
    if (f.id) await updatePrice(f.id, payload)
    else await createPrice(payload)
    priceDialog.value = false
    await loadPrices()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '保存价格失败'
  } finally {
    priceSaving.value = false
  }
}

async function removePrice(row: ModelPrice) {
  ask('删除价格行', `删除价格行 ${row.model_pattern || '*'}（${row.provider_host || '任意网关'}）？仅影响后续新发生的调用计价。`, async () => {
    try {
      await deletePrice(row.id)
      await loadPrices()
    } catch (e) {
      error.value = e instanceof Error ? e.message : '删除失败'
    }
  })
}

function repriceUnpriced() {
  ask(
    '重算未定价记录',
    `按当前价格表重算最近 ${days.value} 天的未定价明细？仅更新保留期内的明细，已归档月度汇总不受影响。`,
    async () => {
      repricing.value = true
      error.value = ''
      try {
        const r = await repriceUnpricedUsage(days.value)
        if (r.skipped) {
          error.value = `已重算 ${r.repriced} 笔，仍有 ${r.skipped} 笔未匹配到价格`
        }
        await Promise.all([loadStats(), loadEvents()])
      } catch (e) {
        error.value = e instanceof Error ? e.message : '重算失败'
      } finally {
        repricing.value = false
      }
    },
  )
}

async function saveBudget() {
  budgetSaving.value = true
  budgetTip.value = ''
  try {
    budget.value = await updateUsageSettings({
      monthly_budget: Number(budget.value.monthly_budget) || 0,
      alert_ratio: Number(budget.value.alert_ratio) || 0,
    })
    budgetTip.value = '已保存'
  } catch (e) {
    error.value = e instanceof Error ? e.message : '保存预算失败'
  } finally {
    budgetSaving.value = false
  }
}

async function saveRecon() {
  reconSaving.value = true
  try {
    await upsertReconciliation({
      month: reconMonth.value,
      provider: reconForm.value.provider.trim(),
      billed_amount: Number(reconForm.value.billed_amount) || 0,
      note: reconForm.value.note || '',
    })
    reconForm.value = { provider: '', billed_amount: 0, note: '' }
    await loadRecons()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '保存账单失败'
  } finally {
    reconSaving.value = false
  }
}

async function removeRecon(row: ReconciliationRow) {
  ask('删除对账记录', `删除 ${row.month} ${row.provider || '全部'} 的对账记录？此操作不可恢复。`, async () => {
    try {
      await deleteReconciliation(row.id)
      await loadRecons()
    } catch (e) {
      error.value = e instanceof Error ? e.message : '删除失败'
    }
  })
}

function reconTone(row: ReconciliationRow) {
  if (row.diff_ratio == null) return 'neutral'
  const abs = Math.abs(row.diff_ratio)
  return abs <= 0.02 ? 'good' : abs <= 0.05 ? 'warn' : 'bad'
}

watch(reconMonth, () => void loadRecons())
watch([filterModule, filterPriced], () => {
  page.value = 1
  void loadEvents()
})

function onResize() {
  lineChart?.resize()
  barChart?.resize()
}
onMounted(() => {
  void loadAll()
  window.addEventListener('resize', onResize)
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  lineChart?.dispose()
  barChart?.dispose()
})
</script>

<template>
  <div>
    <PageHead title="用量与成本" eyebrow="AI USAGE" sub="全链路 Token 记账、分归属成本与月度对账">
      <template #actions>
        <button class="btn ghost" :class="{ active: days === 7 }" @click="applyRange(7)">7 天</button>
        <button class="btn ghost" :class="{ active: days === 30 }" @click="applyRange(30)">30 天</button>
        <button class="btn ghost" :class="{ active: days === 90 }" @click="applyRange(90)">90 天</button>
        <button class="btn" :disabled="loading" @click="loadAll">{{ loading ? '刷新中…' : '刷新' }}</button>
        <button class="btn ghost" @click="downloadCsv">导出 CSV</button>
      </template>
    </PageHead>

    <p v-if="error" class="error">{{ error }}</p>

    <template v-if="stats">
      <section class="grid cards">
        <div class="card">
          <div class="card-label">总费用（{{ days }} 天）</div>
          <div class="card-value">{{ money(stats.cost_estimate) }}</div>
          <div class="card-sub">平台 {{ money(stats.cost_platform) }} · 教师 {{ money(stats.cost_teacher) }}</div>
          <div class="card-sub">今日 {{ money(today?.cost) }} · 事件 {{ stats.events.toLocaleString() }} 笔</div>
        </div>
        <div class="card">
          <div class="card-label">Token 总量</div>
          <div class="card-value">{{ tokens(totalTokens) }}</div>
          <div class="card-sub">输入 {{ tokens(stats.input_tokens) }} · 输出 {{ tokens(stats.output_tokens) }}</div>
          <div class="card-sub">今日 {{ tokens((today?.input_tokens || 0) + (today?.output_tokens || 0)) }}</div>
        </div>
        <div class="card" :class="`tone-${stats.provider_ratio == null ? 'neutral' : stats.provider_ratio >= 0.85 ? 'good' : stats.provider_ratio >= 0.6 ? 'warn' : 'bad'}`">
          <div class="card-label">厂商口径占比</div>
          <div class="card-value">{{ pct(stats.provider_ratio) }}</div>
          <div class="card-sub">厂商返回 {{ stats.provider_events.toLocaleString() }} 笔 · 估算 {{ stats.estimated_events.toLocaleString() }} 笔</div>
          <div class="card-sub">估算行单列展示，不承诺绝对精准</div>
        </div>
        <div class="card" :class="stats.unpriced_events ? 'tone-bad' : 'tone-good'">
          <div class="card-label">未定价事件</div>
          <div class="card-value">{{ stats.unpriced_events.toLocaleString() }}</div>
          <div class="card-sub">无价格行的模型不臆造费用</div>
          <div v-if="stats.unpriced_events" class="card-alert">请在下方价格表补充 {{ stats.unpriced.length }} 个模型的价格</div>
        </div>
      </section>

      <section v-if="stats.unpriced.length" class="panel warn-panel">
        <div class="panel-head">
          <h3>未定价模型（费用按 0 计）</h3>
          <span class="muted">新调用按当前价格表计价；已产生的保留期明细可重算</span>
          <button class="link-btn" :disabled="repricing" @click="repriceUnpriced">{{ repricing ? '重算中…' : '重算未定价' }}</button>
        </div>
        <div class="chips">
          <span v-for="u in stats.unpriced" :key="`${u.provider_host}-${u.model}`" class="chip">
            {{ u.model || '未知模型' }} · {{ u.provider_host || '未知网关' }} · {{ u.events }} 笔
          </span>
        </div>
      </section>

      <section class="two-col">
        <div class="panel">
          <div class="panel-head"><h3>成本趋势（按天）</h3><span class="muted">按记账时单价快照累计</span></div>
          <div ref="lineEl" class="chart" />
        </div>
        <div class="panel">
          <div class="panel-head"><h3>模块成本 Top</h3><span class="muted">Agent/报告/评估/习题/客服…</span></div>
          <div ref="barEl" class="chart" />
        </div>
      </section>

      <section class="two-col">
        <div class="panel">
          <div class="panel-head">
            <h3>按模型</h3>
            <span class="muted">{{ consistencyOk ? '口径自检 ✓ 分组合计=总额' : '口径自检异常：分组合计与总额不一致' }}</span>
          </div>
          <table class="table">
            <thead><tr><th>模型</th><th>事件</th><th>输入</th><th>输出</th><th>费用</th></tr></thead>
            <tbody>
              <tr v-for="m in stats.by_model" :key="m.model">
                <td class="mono">{{ m.model || '-' }}</td>
                <td>{{ m.events }}</td>
                <td>{{ tokens(m.input_tokens) }}</td>
                <td>{{ tokens(m.output_tokens) }}</td>
                <td>{{ money(m.cost) }}</td>
              </tr>
              <tr v-if="!stats.by_model.length"><td colspan="5" class="muted">暂无调用</td></tr>
            </tbody>
          </table>
        </div>
        <div class="panel">
          <div class="panel-head"><h3>按归属（教师 BYOK / 平台共享）</h3></div>
          <table class="table">
            <thead><tr><th>归属</th><th>事件</th><th>输入</th><th>输出</th><th>费用</th></tr></thead>
            <tbody>
              <tr v-for="o in stats.by_owner" :key="o.owner_id || 'platform'">
                <td>{{ o.owner_name }}</td>
                <td>{{ o.events }}</td>
                <td>{{ tokens(o.input_tokens) }}</td>
                <td>{{ tokens(o.output_tokens) }}</td>
                <td>{{ money(o.cost) }}</td>
              </tr>
              <tr v-if="!stats.by_owner.length"><td colspan="5" class="muted">暂无调用</td></tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="panel">
        <div class="panel-head">
          <h3>调用明细</h3>
          <div class="filters">
            <select v-model="filterModule">
              <option value="">全部模块</option>
              <option v-for="m in stats.by_module" :key="m.module" :value="m.module">{{ moduleLabel(m.module) }}</option>
            </select>
            <select v-model="filterPriced">
              <option value="">全部定价状态</option>
              <option value="priced">已定价</option>
              <option value="unpriced">未定价</option>
            </select>
          </div>
        </div>
        <table class="table">
          <thead>
            <tr><th>时间</th><th>类型</th><th>模块</th><th>归属</th><th>模型</th><th>Token</th><th>口径</th><th>费用</th><th>耗时</th><th>状态</th></tr>
          </thead>
          <tbody>
            <tr v-for="ev in events" :key="ev.id">
              <td class="mono">{{ ev.created_at?.slice(0, 19).replace('T', ' ') }}</td>
              <td>{{ ev.kind }}</td>
              <td>{{ moduleLabel(ev.module) }}</td>
              <td>{{ ev.is_platform ? '平台' : ev.owner_name || '教师' }}</td>
              <td class="mono ellipsis">{{ ev.model || '-' }}</td>
              <td>{{ tokens(ev.input_tokens) }} / {{ tokens(ev.output_tokens) }}</td>
              <td><span class="tag" :class="ev.source">{{ sourceLabel(ev.source) }}</span></td>
              <td>{{ ev.priced_status === 'priced' ? money(ev.cost) : '未定价' }}</td>
              <td>{{ ev.latency_ms }} ms</td>
              <td><span class="tag" :class="ev.status === 'ok' ? 'ok' : 'bad'">{{ ev.status === 'ok' ? '成功' : '失败' }}</span></td>
            </tr>
            <tr v-if="!events.length"><td colspan="10" class="muted">暂无记录</td></tr>
          </tbody>
        </table>
        <div class="pager">
          <span class="muted">共 {{ eventTotal }} 条 · 第 {{ page }} 页</span>
          <div>
            <button class="btn ghost" :disabled="page <= 1 || eventsLoading" @click="page--; loadEvents()">上一页</button>
            <button class="btn ghost" :disabled="page * pageSize >= eventTotal || eventsLoading" @click="page++; loadEvents()">下一页</button>
          </div>
        </div>
      </section>

      <section class="panel">
        <div class="panel-head">
          <h3>模型价格表（版本化）</h3>
          <button class="btn" @click="openPriceDialog()">新增价格</button>
        </div>
        <p class="metric-note">调价请新增一行（生效时间填今日），历史账本不会回写；单价单位：元 / 1M tokens。网关域名留空=任意网关，模型匹配留空=任意模型。</p>
        <table class="table">
          <thead><tr><th>网关</th><th>模型匹配</th><th>输入/1M</th><th>输出/1M</th><th>缓存读/1M</th><th>生效时间</th><th>来源备注</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="p in prices" :key="p.id">
              <td class="mono">{{ p.provider_host || '*' }}</td>
              <td class="mono">{{ p.model_pattern || '*' }}</td>
              <td>{{ p.input_per_1m }}</td>
              <td>{{ p.output_per_1m }}</td>
              <td>{{ p.cache_read_per_1m }}</td>
              <td class="mono">{{ p.effective_from?.slice(0, 10) }}</td>
              <td class="ellipsis">{{ p.source_note || '-' }}</td>
              <td>
                <button class="link-btn" @click="openPriceDialog(p)">编辑</button>
                <button class="link-btn danger" @click="removePrice(p)">删除</button>
              </td>
            </tr>
            <tr v-if="!prices.length"><td colspan="8" class="muted">尚无价格行：所有调用会显示「未定价」</td></tr>
          </tbody>
        </table>
      </section>

      <section class="two-col">
        <div class="panel">
          <div class="panel-head"><h3>预算告警</h3><span v-if="budgetTip" class="ok-inline">{{ budgetTip }}</span></div>
          <div class="form-row">
            <label>月度预算（元）</label>
            <input v-model.number="budget.monthly_budget" type="number" min="0" step="10" />
          </div>
          <div class="form-row">
            <label>提醒阈值（0-1）</label>
            <input v-model.number="budget.alert_ratio" type="number" min="0" max="1" step="0.05" />
          </div>
          <p class="metric-note">达到预算 × 阈值时，给所有管理员发一次站内通知（同月幂等）。0 表示不告警。</p>
          <button class="btn" :disabled="budgetSaving" @click="saveBudget">{{ budgetSaving ? '保存中…' : '保存预算' }}</button>
        </div>

        <div class="panel">
          <div class="panel-head"><h3>月度对账</h3><input v-model="reconMonth" type="month" class="month-input" /></div>
          <div class="form-row">
            <label>供应商</label>
            <input v-model="reconForm.provider" placeholder="如 deepseek / dashscope（留空=全部）" />
          </div>
          <div class="form-row">
            <label>账单金额（元）</label>
            <input v-model.number="reconForm.billed_amount" type="number" min="0" step="0.01" />
          </div>
          <div class="form-row">
            <label>备注</label>
            <input v-model="reconForm.note" placeholder="发票号 / 核对日期" />
          </div>
          <button class="btn" :disabled="reconSaving" @click="saveRecon">{{ reconSaving ? '保存中…' : '录入账单' }}</button>

          <table class="table mt">
            <thead><tr><th>供应商</th><th>账单</th><th>账本</th><th>差异</th><th>备注</th><th></th></tr></thead>
            <tbody>
              <tr v-for="r in recons" :key="r.id">
                <td>{{ r.provider || '全部' }}</td>
                <td>{{ money(r.billed_amount) }}</td>
                <td>{{ money(r.ledger_cost) }}</td>
                <td :class="`diff-${reconTone(r)}`">
                  {{ money(r.diff) }} <small v-if="r.diff_ratio != null">({{ (r.diff_ratio * 100).toFixed(1) }}%)</small>
                </td>
                <td class="ellipsis">{{ r.note || '-' }}</td>
                <td><button class="link-btn danger" @click="removeRecon(r)">删除</button></td>
              </tr>
              <tr v-if="!recons.length"><td colspan="6" class="muted">尚未录入当月账单</td></tr>
            </tbody>
          </table>
          <p class="metric-note">差异 = 账单金额 − 账本金额；偏差超过 2% 标黄、5% 标红。账本按网关域名归集。</p>
        </div>
      </section>

      <section class="panel">
        <div class="panel-head"><h3>当月账本按网关</h3><span class="muted">{{ reconMonth }}</span></div>
        <table class="table">
          <thead><tr><th>网关</th><th>币种</th><th>事件</th><th>输入</th><th>输出</th><th>费用</th></tr></thead>
          <tbody>
            <tr v-for="p in ledger" :key="`${p.provider_host}-${p.currency}`">
              <td class="mono">{{ p.provider_host || '未知' }}</td>
              <td>{{ p.currency }}</td>
              <td>{{ p.events }}</td>
              <td>{{ tokens(p.input_tokens) }}</td>
              <td>{{ tokens(p.output_tokens) }}</td>
              <td>{{ money(p.cost) }}</td>
            </tr>
            <tr v-if="!ledger.length"><td colspan="6" class="muted">当月暂无调用</td></tr>
          </tbody>
        </table>
      </section>
    </template>

    <div v-if="priceDialog" class="modal-mask" @click.self="priceDialog = false">
      <div class="modal">
        <div class="panel-head"><h3>{{ priceForm.id ? '编辑价格' : '新增价格' }}</h3><button class="link-btn" @click="priceDialog = false">关闭</button></div>
        <div class="form-row"><label>网关域名</label><input v-model="priceForm.provider_host" placeholder="如 api.deepseek.com（留空=任意）" /></div>
        <div class="form-row"><label>模型匹配</label><input v-model="priceForm.model_pattern" placeholder="如 deepseek-chat（支持前缀）" /></div>
        <div class="form-row"><label>输入/1M</label><input v-model.number="priceForm.input_per_1m" type="number" min="0" step="0.01" /></div>
        <div class="form-row"><label>输出/1M</label><input v-model.number="priceForm.output_per_1m" type="number" min="0" step="0.01" /></div>
        <div class="form-row"><label>缓存读/1M</label><input v-model.number="priceForm.cache_read_per_1m" type="number" min="0" step="0.01" /></div>
        <div class="form-row"><label>生效时间</label><input v-model="priceForm.effective_from" type="datetime-local" /></div>
        <div class="form-row"><label>来源备注</label><input v-model="priceForm.source_note" placeholder="官网价目 / 商务报价 核对日期" /></div>
        <div class="modal-actions">
          <button class="btn ghost" @click="priceDialog = false">取消</button>
          <button class="btn" :disabled="priceSaving" @click="savePrice">{{ priceSaving ? '保存中…' : '保存' }}</button>
        </div>
      </div>
    </div>
    <ConfirmDialog
      :visible="!!pending"
      :title="pending?.title || ''"
      :message="pending?.message || ''"
      confirm-text="删除"
      danger
      @confirm="confirmPending"
      @cancel="pending = null"
    />
  </div>
</template>

<style scoped>
.btn { padding: 8px 14px; border-radius: 9px; border: 1px solid var(--brand); background: var(--brand); color: #fff; font-weight: 600; cursor: pointer; font-size: 13px; }
.btn.ghost { background: var(--surface); color: var(--brand-strong); border-color: var(--line); }
.btn.ghost.active { border-color: var(--brand); color: var(--brand); }
.btn:disabled { opacity: .6; cursor: default; }
.grid.cards { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; margin-bottom: 16px; }
.card { background: var(--surface); border: 1px solid var(--line); border-radius: 14px; padding: 16px; box-shadow: var(--shadow-sm); }
.card.tone-good { border-top: 3px solid #10b981; }
.card.tone-warn { border-top: 3px solid #f59e0b; background: #fffdf7; }
.card.tone-bad { border-top: 3px solid #ef4444; background: #fffafa; }
.card-label { color: var(--ink-3); font-size: 12px; font-weight: 600; }
.card-value { font-size: 24px; font-weight: 800; margin: 6px 0 4px; color: var(--ink); }
.card-sub { color: var(--ink-3); font-size: 12px; line-height: 1.6; }
.card-alert { margin-top: 6px; padding: 5px 8px; border-radius: 8px; background: #fef2f2; color: #b91c1c; font-size: 11.5px; font-weight: 600; }
.panel { background: var(--surface); border: 1px solid var(--line); border-radius: 14px; padding: 16px; margin-bottom: 16px; box-shadow: var(--shadow-sm); }
.panel.warn-panel { border-color: #fecaca; background: #fffafa; }
.panel-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 10px; }
.panel-head h3 { font-size: 14px; font-weight: 800; }
.muted { color: var(--ink-3); font-size: 12px; }
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.chart { width: 100%; height: 260px; }
.table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.table th, .table td { text-align: left; padding: 8px 6px; border-bottom: 1px solid var(--line); }
.table th { color: var(--ink-3); font-weight: 600; }
.table.mt { margin-top: 12px; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11.5px; }
.ellipsis { max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.error { color: #b91c1c; background: #fef2f2; padding: 10px 12px; border-radius: 10px; margin-bottom: 12px; }
.chips { display: flex; flex-wrap: wrap; gap: 8px; }
.chip { padding: 4px 10px; border-radius: 999px; background: #fef2f2; color: #b91c1c; font-size: 11.5px; }
.tag { display: inline-block; padding: 2px 8px; border-radius: 999px; background: #f1f5f9; color: var(--ink-3); font-size: 11px; }
.tag.provider, .tag.ok { background: var(--success-soft); color: #047857; }
.tag.estimated { background: #fffbeb; color: #b45309; }
.tag.bad { background: #fef2f2; color: #b91c1c; }
.filters { display: flex; gap: 8px; }
.filters select, .form-row input, .month-input { padding: 7px 10px; border: 1px solid var(--line); border-radius: 8px; font-size: 12.5px; background: var(--surface); }
.pager { display: flex; align-items: center; justify-content: space-between; margin-top: 10px; }
.pager > div { display: flex; gap: 8px; }
.link-btn { background: none; border: none; color: var(--brand-strong); font-size: 12px; cursor: pointer; padding: 2px 6px; }
.link-btn.danger { color: #b91c1c; }
.form-row { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.form-row label { width: 108px; color: var(--ink-3); font-size: 12.5px; flex-shrink: 0; }
.form-row input { flex: 1; min-width: 0; }
.metric-note { margin: 10px 0; color: var(--ink-3); font-size: 11.5px; line-height: 1.7; background: #f8fafc; border-radius: 8px; padding: 8px 10px; }
.ok-inline { color: #047857; font-size: 12px; }
.diff-good { color: #047857; }
.diff-warn { color: #b45309; }
.diff-bad { color: #b91c1c; font-weight: 700; }
.diff-neutral { color: var(--ink-3); }
.modal-mask { position: fixed; inset: 0; background: rgba(15, 23, 42, .45); display: flex; align-items: center; justify-content: center; z-index: 60; }
.modal { background: var(--surface); border-radius: 14px; padding: 18px; width: min(560px, 92vw); max-height: 86vh; overflow: auto; box-shadow: 0 20px 50px rgba(15, 23, 42, .3); }
.modal-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 14px; }
@media (max-width: 1100px) { .grid.cards, .two-col { grid-template-columns: 1fr 1fr; } }
@media (max-width: 760px) { .grid.cards, .two-col { grid-template-columns: 1fr; } }
</style>
