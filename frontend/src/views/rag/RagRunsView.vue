<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import PageHead from '@/components/PageHead.vue'
import RagTabs from '@/components/RagTabs.vue'
import {
  getAgentOpsStats,
  getAgentRun,
  listAgentRuns,
  type AgentOpsStats,
  type AgentRun,
  type AgentRunSpan,
} from '@/api/agentOps'

const loading = ref(false)
const error = ref('')
const stats = ref<AgentOpsStats | null>(null)
const items = ref<AgentRun[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const detail = ref<{ run: AgentRun; spans: AgentRunSpan[] } | null>(null)
const detailLoading = ref(false)

const filters = ref({
  days: 7,
  intent: '',
  task_kind: '',
  status: '',
  rag_decision: '',
  rag_status: '',
  needs_rag: '' as '' | 'true' | 'false',
  ppt_aligned: '' as '' | 'true' | 'false',
})

const INTENT_LABEL: Record<string, string> = {
  chitchat: '闲聊',
  knowledge_qa: '知识问答',
  business_data: '业务数据',
  ppt_task: 'PPT 任务',
  document_task: '文档任务',
  mcp_task: 'MCP 任务',
  mixed: '混合',
  unknown: '未知',
}
const DECISION_LABEL: Record<string, string> = {
  pending: '待定',
  used: '已检索',
  auto: '自动检索',
  skipped_by_intent: '意图无需检索',
  skipped_no_docs: '无可用文档',
  error: '检索异常',
  not_applicable: '不适用',
}

function pct(v: number | null | undefined) {
  return v == null ? '-' : `${Math.round(v * 100)}%`
}
function ms(v: number | null | undefined) {
  return v == null ? '-' : `${Math.round(v)} ms`
}
function tokens(v: number | null | undefined) {
  return (v ?? 0).toLocaleString()
}
function money(v: number | null | undefined) {
  if (v == null) return '—'
  const n = Number(v)
  return `¥${n.toFixed(n >= 1 ? 2 : 4)}`
}
function fmt(v: string | null | undefined) {
  return v ? v.slice(0, 19).replace('T', ' ') : '-'
}
function intentLabel(v: string) {
  return INTENT_LABEL[v] || v || '-'
}
function decisionLabel(v: string) {
  return DECISION_LABEL[v] || v || '-'
}

const pptDisplay = computed(() => {
  const s = stats.value
  if (!s) return { rate: null as number | null, aligned: 0, denom: 0, delivered: 0, note: '' }
  const taskRuns = s.ppt_task_runs ?? 0
  if (taskRuns > 0) {
    return {
      rate: s.ppt_task_alignment_rate ?? null,
      aligned: s.ppt_task_aligned ?? 0,
      denom: taskRuns,
      delivered: s.ppt_task_delivered ?? 0,
      note: `PPT 任务契约 ${taskRuns} 个，交付 ${s.ppt_task_delivered ?? 0} 个`,
    }
  }
  const planned = s.ppt_planned_runs ?? 0
  const extra = Math.max(0, (s.ppt_runs ?? 0) - planned)
  return {
    rate: planned ? (s.ppt_alignment_rate ?? null) : null,
    aligned: s.ppt_aligned ?? 0,
    denom: planned,
    delivered: s.ppt_delivered ?? 0,
    note: extra
      ? `另有 ${extra} 次运行未指定目标页数，不计入分母；已交付 ${s.ppt_delivered ?? 0} 次`
      : `已交付 ${s.ppt_delivered ?? 0} 次`,
  }
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    const params: Record<string, unknown> = {
      page: page.value,
      page_size: pageSize,
      days: filters.value.days,
    }
    for (const key of ['intent', 'task_kind', 'status', 'rag_decision'] as const) {
      if (filters.value[key]) params[key] = filters.value[key]
    }
    if (filters.value.needs_rag) params.needs_rag = filters.value.needs_rag === 'true'
    if (filters.value.ppt_aligned) params.ppt_aligned = filters.value.ppt_aligned === 'true'
    const [s, r] = await Promise.all([getAgentOpsStats(filters.value.days), listAgentRuns(params)])
    stats.value = s
    items.value = r.items
    total.value = r.total
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}

async function openRun(run: AgentRun) {
  detailLoading.value = true
  try {
    detail.value = await getAgentRun(run.run_id)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载运行详情失败'
  } finally {
    detailLoading.value = false
  }
}

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))
function goPage(p: number) {
  page.value = Math.min(Math.max(1, p), totalPages.value)
  void load()
}
function applyFilters() {
  page.value = 1
  void load()
}

onMounted(load)
</script>

<template>
  <div>
    <PageHead title="任务监控" eyebrow="AGENT OPS" sub="意图、RAG 决策、模型与工具调用一屏追溯">
      <template #actions>
        <button class="btn" :disabled="loading" @click="load">{{ loading ? '刷新中…' : '刷新' }}</button>
        <RouterLink class="btn ghost" to="/rag/overview">返回总览</RouterLink>
        <RouterLink class="btn ghost" to="/rag/traces">检索追踪</RouterLink>
      </template>
    </PageHead>

    <RagTabs />

    <p v-if="error" class="error">{{ error }}</p>

    <section v-if="stats" class="grid cards">
      <div class="card">
        <div class="card-label">运行数</div>
        <div class="card-value">{{ stats.total_runs }}</div>
        <div class="card-sub">成功 {{ stats.ok_runs }} · 异常 {{ stats.error_runs }} · 成功率 {{ pct(stats.success_rate) }}</div>
      </div>
      <div class="card">
        <div class="card-label">RAG 漏检</div>
        <div class="card-value">{{ stats.rag_missed }}</div>
        <div class="card-sub">需要 RAG {{ stats.needs_rag }} · 实际检索 {{ stats.rag_used }} · 漏检率 {{ pct(stats.rag_miss_rate) }}</div>
      </div>
      <div class="card">
        <div class="card-label">PPT 页数对齐</div>
        <div class="card-value">{{ pct(pptDisplay.rate) }}</div>
        <div class="card-sub">{{ pptDisplay.aligned }} / {{ pptDisplay.denom }} 个带目标页数任务对齐 · 已交付 {{ pptDisplay.delivered }} 次</div>
        <div class="card-sub">{{ pptDisplay.note }}</div>
      </div>
      <div class="card">
        <div class="card-label">时延 / Token / 成本</div>
        <div class="card-value">{{ ms(stats.p95_latency_ms) }}</div>
        <div class="card-sub">平均 {{ ms(stats.avg_latency_ms) }} · 输入 {{ tokens(stats.input_tokens) }} · 输出 {{ tokens(stats.output_tokens) }}</div>
        <div class="card-sub">已计价成本 {{ money(stats.cost_estimate) }}</div>
      </div>
    </section>

    <section v-if="stats" class="two-col">
      <div class="panel">
        <div class="panel-head"><h3>意图分布</h3></div>
        <div class="bars">
          <div v-for="x in stats.intents" :key="x.intent" class="bar-row">
            <span>{{ intentLabel(x.intent) }}</span>
            <div class="bar"><i :style="{ width: `${stats.total_runs ? (x.runs / stats.total_runs) * 100 : 0}%` }" /></div>
            <b>{{ x.runs }}</b>
          </div>
        </div>
      </div>
      <div class="panel">
        <div class="panel-head"><h3>RAG 决策</h3></div>
        <div class="bars">
          <div v-for="x in stats.rag_decisions" :key="x.decision" class="bar-row">
            <span>{{ decisionLabel(x.decision) }}</span>
            <div class="bar"><i :style="{ width: `${stats.total_runs ? (x.runs / stats.total_runs) * 100 : 0}%` }" /></div>
            <b>{{ x.runs }}</b>
          </div>
        </div>
      </div>
    </section>

    <section v-if="stats" class="panel">
      <div class="panel-head"><h3>Component synergy</h3></div>
      <div class="bars">
        <div class="bar-row"><span>RAG only</span><div class="bar"><i :style="{ width: `${stats.total_runs ? (stats.component_synergy.pure_rag / stats.total_runs) * 100 : 0}%` }" /></div><b>{{ stats.component_synergy.pure_rag }}</b></div>
        <div class="bar-row"><span>Tool only</span><div class="bar"><i :style="{ width: `${stats.total_runs ? (stats.component_synergy.pure_tool / stats.total_runs) * 100 : 0}%` }" /></div><b>{{ stats.component_synergy.pure_tool }}</b></div>
        <div class="bar-row"><span>RAG + Tool</span><div class="bar"><i :style="{ width: `${stats.total_runs ? (stats.component_synergy.rag_plus_tool / stats.total_runs) * 100 : 0}%` }" /></div><b>{{ stats.component_synergy.rag_plus_tool }}</b></div>
        <div class="bar-row"><span>Skill runs</span><div class="bar"><i :style="{ width: `${stats.total_runs ? (stats.component_synergy.skill_runs / stats.total_runs) * 100 : 0}%` }" /></div><b>{{ stats.component_synergy.skill_runs }}</b></div>
        <div class="bar-row"><span>MCP runs</span><div class="bar"><i :style="{ width: `${stats.total_runs ? (stats.component_synergy.mcp_runs / stats.total_runs) * 100 : 0}%` }" /></div><b>{{ stats.component_synergy.mcp_runs }}</b></div>
      </div>
    </section>

    <section class="panel">
      <div class="panel-head">
        <h3>运行列表</h3>
        <span class="muted">共 {{ total }} 条</span>
      </div>
      <div class="filters">
        <select v-model.number="filters.days" @change="applyFilters">
          <option :value="1">近 1 天</option>
          <option :value="7">近 7 天</option>
          <option :value="30">近 30 天</option>
        </select>
        <select v-model="filters.intent" @change="applyFilters">
          <option value="">全部意图</option>
          <option v-for="(v, k) in INTENT_LABEL" :key="k" :value="k">{{ v }}</option>
        </select>
        <select v-model="filters.task_kind" @change="applyFilters">
          <option value="">全部任务</option>
          <option value="chat">普通对话</option>
          <option value="ppt">PPT</option>
          <option value="document">文档</option>
          <option value="rag_qa">RAG 问答</option>
          <option value="business_data">业务数据</option>
        </select>
        <select v-model="filters.status" @change="applyFilters">
          <option value="">全部状态</option>
          <option value="ok">成功</option>
          <option value="error">异常</option>
          <option value="running">运行中</option>
        </select>
        <select v-model="filters.rag_decision" @change="applyFilters">
          <option value="">全部 RAG 决策</option>
          <option v-for="(v, k) in DECISION_LABEL" :key="k" :value="k">{{ v }}</option>
        </select>
        <select v-model="filters.rag_status" @change="applyFilters">
          <option value="">all RAG statuses</option>
          <option value="used">used</option>
          <option value="skipped">skipped</option>
          <option value="error">error</option>
          <option value="needed">needed</option>
          <option value="not_needed">not_needed</option>
        </select>
        <select v-model="filters.needs_rag" @change="applyFilters">
          <option value="">RAG 需求不限</option>
          <option value="true">需要 RAG</option>
          <option value="false">无需 RAG</option>
        </select>
        <select v-model="filters.ppt_aligned" @change="applyFilters">
          <option value="">PPT 对齐不限</option>
          <option value="true">已对齐</option>
          <option value="false">未对齐</option>
        </select>
      </div>
      <table class="table">
        <thead>
          <tr>
            <th>时间</th><th>意图</th><th>任务</th><th>RAG</th><th>RAG状态</th><th>模型/工具</th><th>PPT</th><th>时延</th><th>Token/成本</th><th>状态</th><th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in items" :key="r.run_id">
            <td class="mono">{{ fmt(r.created_at) }}</td>
            <td>{{ intentLabel(r.intent) }}</td>
            <td>{{ r.task_kind }}</td>
            <td>{{ decisionLabel(r.rag_decision) }}</td>
            <td>{{ r.rag_status || '-' }}</td>
            <td>{{ r.model_calls }} / {{ r.tool_calls }}</td>
            <td>
              <span v-if="r.task_kind === 'ppt'" class="tag" :class="{ active: r.ppt_aligned }">
                {{ r.ppt_current_pages }}/{{ r.ppt_target_pages }}
              </span>
              <span v-else class="muted">-</span>
            </td>
            <td>{{ r.latency_ms }} ms</td>
            <td class="mono">
              {{ tokens((r.input_tokens || 0) + (r.output_tokens || 0)) }}
              <div class="muted">{{ r.cost_known ? money(r.cost_used) : '未记账' }}</div>
            </td>
            <td><span class="tag" :class="{ active: r.status === 'ok', danger: r.status === 'error' }">{{ r.status }}</span></td>
            <td><button class="link-btn" @click="openRun(r)">详情</button></td>
          </tr>
          <tr v-if="!items.length"><td colspan="11" class="muted">暂无运行记录</td></tr>
        </tbody>
      </table>
      <div class="pager">
        <button class="btn ghost" :disabled="page <= 1" @click="goPage(page - 1)">上一页</button>
        <span class="muted">{{ page }} / {{ totalPages }}</span>
        <button class="btn ghost" :disabled="page >= totalPages" @click="goPage(page + 1)">下一页</button>
      </div>
    </section>

    <section v-if="detail" class="panel">
      <div class="panel-head">
        <h3>运行详情 · {{ detail.run.run_id.slice(0, 12) }}</h3>
        <button class="link-btn" @click="detail = null">收起</button>
      </div>
      <p v-if="detailLoading" class="muted">加载中…</p>
      <div v-else>
        <div class="detail-grid">
          <div><span>意图</span><b>{{ intentLabel(detail.run.intent) }}（{{ detail.run.intent_source }}）</b></div>
          <div><span>RAG 决策</span><b>{{ decisionLabel(detail.run.rag_decision) }}</b></div>
          <div><span>会话</span><b class="mono">{{ detail.run.conversation_id || '-' }}</b></div>
          <div><span>任务</span><b>{{ detail.run.task_kind }}</b></div>
          <div><span>Token</span><b>输入 {{ tokens(detail.run.input_tokens) }} · 输出 {{ tokens(detail.run.output_tokens) }}</b></div>
          <div><span>成本</span><b>{{ detail.run.cost_known ? money(detail.run.cost_used) : '未记账（无用量事件）' }}</b></div>
          <div v-if="detail.run.task_kind === 'ppt'"><span>PPT 契约</span><b>{{ detail.run.ppt_current_pages }} / {{ detail.run.ppt_target_pages }} 页 · {{ detail.run.ppt_aligned ? '已对齐' : '未对齐' }}</b></div>
          <div v-if="detail.run.error_message"><span>错误</span><b class="error-text">{{ detail.run.error_message }}</b></div>
        </div>
        <div class="timeline">
          <div v-for="s in detail.spans" :key="s.span_id" class="span" :class="s.status">
            <div class="span-head">
              <span class="tag">{{ s.span_type }}</span>
              <b>{{ s.name }}</b>
              <span class="muted">{{ s.latency_ms }} ms</span>
              <span v-if="s.model" class="muted">{{ s.model }}</span>
              <span v-if="(s.input_tokens || 0) + (s.output_tokens || 0) > 0" class="muted">{{ tokens(s.input_tokens) }}/{{ tokens(s.output_tokens) }} tok</span>
              <span class="tag" :class="{ active: s.status === 'ok', danger: s.status === 'error' }">{{ s.status }}</span>
            </div>
            <div v-if="s.summary" class="span-summary">{{ s.summary }}</div>
            <div v-if="s.error" class="error-text">{{ s.error }}</div>
          </div>
          <p v-if="!detail.spans.length" class="muted">暂无 span 记录</p>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.btn { padding: 8px 14px; border-radius: 9px; border: 1px solid var(--brand); background: var(--brand); color: #fff; font-weight: 600; cursor: pointer; text-decoration: none; font-size: 13px; }
.btn.ghost { background: var(--surface); color: var(--brand-strong); border-color: var(--line); }
.btn:disabled { opacity: .6; cursor: default; }
.grid.cards { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; margin-bottom: 16px; }
.card { background: var(--surface); border: 1px solid var(--line); border-radius: 14px; padding: 16px; box-shadow: var(--shadow-sm); }
.card-label { color: var(--ink-3); font-size: 12px; font-weight: 600; }
.card-value { font-size: 24px; font-weight: 800; margin: 6px 0 4px; color: var(--ink); }
.card-sub { color: var(--ink-3); font-size: 12px; }
.panel { background: var(--surface); border: 1px solid var(--line); border-radius: 14px; padding: 16px; margin-bottom: 16px; box-shadow: var(--shadow-sm); }
.panel-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.panel-head h3 { font-size: 14px; font-weight: 800; }
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.table th, .table td { text-align: left; padding: 8px 6px; border-bottom: 1px solid var(--line); }
.table th { color: var(--ink-3); font-weight: 600; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11.5px; }
.muted { color: var(--ink-3); font-size: 12px; }
.error { color: #b91c1c; background: #fef2f2; padding: 10px 12px; border-radius: 10px; margin-bottom: 12px; }
.error-text { color: #b91c1c; }
.filters { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 10px; }
.filters select { padding: 7px 9px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface); color: var(--ink); font-size: 12px; }
.pager { display: flex; align-items: center; gap: 10px; justify-content: flex-end; margin-top: 12px; }
.link-btn { border: 0; background: none; color: var(--brand-strong); cursor: pointer; font-size: 12px; padding: 0; }
.tag { display: inline-block; padding: 2px 8px; border-radius: 999px; background: #f1f5f9; color: var(--ink-3); font-size: 11px; }
.tag.active { background: var(--success-soft); color: #047857; }
.tag.danger { background: #fef2f2; color: #b91c1c; }
.bars { display: flex; flex-direction: column; gap: 9px; }
.bar-row { display: grid; grid-template-columns: 90px 1fr 38px; gap: 8px; align-items: center; font-size: 12px; }
.bar { height: 8px; background: #eef2f7; border-radius: 999px; overflow: hidden; }
.bar i { display: block; height: 100%; background: var(--brand); border-radius: 999px; }
.detail-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px 16px; font-size: 12.5px; margin-bottom: 14px; }
.detail-grid span { color: var(--ink-3); margin-right: 6px; }
.timeline { display: flex; flex-direction: column; gap: 8px; }
.span { border: 1px solid var(--line); border-radius: 10px; padding: 9px 11px; background: #fbfdff; }
.span.error { border-color: #fecaca; background: #fef2f2; }
.span-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 12.5px; }
.span-summary { margin-top: 5px; color: var(--ink-3); font-size: 12px; word-break: break-all; }
@media (max-width: 1100px) { .grid.cards { grid-template-columns: 1fr 1fr; } .two-col { grid-template-columns: 1fr; } .detail-grid { grid-template-columns: 1fr; } }
</style>
