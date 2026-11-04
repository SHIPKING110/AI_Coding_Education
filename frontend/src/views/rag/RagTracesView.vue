<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import PageHead from '@/components/PageHead.vue'
import RagTabs from '@/components/RagTabs.vue'
import { getRagOverview, getRagTrace, listRagTraces, setRagTraceFeedback, type RagOverview, type RagTrace } from '@/api/ragAdmin'

const route = useRoute()
const loading = ref(false)
const error = ref('')
const items = ref<RagTrace[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const domain = ref('')
const q = ref('')
const ragStatus = ref('')
const selected = ref<RagTrace | null>(null)
const overview = ref<RagOverview | null>(null)

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [res, ov] = await Promise.all([
      listRagTraces({
        domain: domain.value || undefined,
        q: q.value || undefined,
        rag_status: ragStatus.value || undefined,
        page: page.value,
        page_size: pageSize,
      }),
      getRagOverview(),
    ])
    items.value = res.items
    total.value = res.total
    overview.value = ov
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}

async function open(t: RagTrace) {
  try {
    selected.value = await getRagTrace(t.trace_id)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载详情失败'
  }
}

async function openById(traceId: string) {
  try {
    selected.value = await getRagTrace(traceId)
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'trace 不存在或已过期'
  }
}

async function feedback(t: RagTrace, value: string) {
  try {
    await setRagTraceFeedback(t.trace_id, value)
    t.feedback = value
    if (selected.value?.trace_id === t.trace_id) selected.value.feedback = value
  } catch (e) {
    error.value = e instanceof Error ? e.message : '提交失败'
  }
}

function search() {
  page.value = 1
  void load()
}
function changePage(delta: number) {
  page.value = Math.max(1, Math.min(totalPages.value, page.value + delta))
  void load()
}
function pct(v: number | null | undefined) {
  return v == null ? '-' : `${Math.round(v * 100)}%`
}
function fmt(iso: string | null | undefined) {
  return iso ? iso.slice(0, 19).replace('T', ' ') : '-'
}
function stageText(t: RagTrace) {
  const s = t.stage_timings || {}
  return Object.entries(s).map(([k, v]) => `${k} ${Math.round(Number(v))}ms`).join(' · ')
}

onMounted(async () => {
  await load()
  const tid = route.query.trace_id
  if (typeof tid === 'string' && tid) await openById(tid)
})
</script>

<template>
  <div>
    <PageHead title="检索追踪" eyebrow="RAG TRACES" sub="每一次检索的路由、候选、门控、重排与耗时">
      <template #actions>
        <button class="btn" :disabled="loading" @click="load">{{ loading ? '刷新中…' : '刷新' }}</button>
      </template>
    </PageHead>

    <RagTabs />

    <p v-if="error" class="error">{{ error }}</p>

    <section v-if="overview" class="health-strip">
      <div><span>命中率（排除错误）</span><b>{{ pct(overview.retrieval_24h.hit_rate_excl_errors) }}</b></div>
      <div><span>零结果率</span><b>{{ pct(overview.retrieval_24h.zero_result_rate) }}</b></div>
      <div><span>检索错误率</span><b>{{ pct(overview.retrieval_24h.error_rate) }}</b></div>
      <div><span>P95 时延</span><b>{{ overview.retrieval_24h.p95_latency_ms == null ? '-' : `${overview.retrieval_24h.p95_latency_ms} ms` }}</b></div>
      <div><span>向量成功率</span><b>{{ pct(overview.retrieval_24h.vector_success_rate) }}</b></div>
      <div><span>重排成功率</span><b>{{ pct(overview.retrieval_24h.rerank_success_rate) }}</b></div>
    </section>

    <section class="toolbar">
      <input v-model="q" placeholder="搜索 query" @keyup.enter="search" />
      <select v-model="domain" @change="search">
        <option value="">全部业务域</option>
        <option value="agent_teacher">agent_teacher</option>
        <option value="parent_service">parent_service</option>
        <option value="admin_test">admin_test</option>
        <option value="eval">eval</option>
      </select>
      <select v-model="ragStatus" @change="search">
        <option value="">all statuses</option>
        <option value="hit">hit</option>
        <option value="no_hit">no_hit</option>
        <option value="error">error</option>
      </select>
      <button class="btn" @click="search">查询</button>
    </section>

    <section class="panel">
      <table class="table">
        <thead>
          <tr><th>时间</th><th>域 / 路由</th><th>query</th><th>候选</th><th>最终</th><th>耗时</th><th>状态</th><th>反馈</th><th></th></tr>
        </thead>
        <tbody>
          <tr v-for="t in items" :key="t.id" :class="{ danger: t.is_error, warn: t.zero_result && !t.is_error }">
            <td class="mono">{{ fmt(t.created_at) }}</td>
            <td><div>{{ t.domain }}</div><div class="muted">{{ t.route }}</div></td>
            <td class="query">{{ t.query }}</td>
            <td class="muted">v{{ t.vector_candidates }} / k{{ t.keyword_candidates }} / r{{ t.rerank_candidates }}</td>
            <td>{{ t.hits?.length || 0 }}</td>
            <td>{{ t.latency_ms }} ms</td>
            <td>
              <span v-if="t.rag_status === 'error'" class="tag bad">error</span>
              <span v-else-if="t.rag_status === 'no_hit'" class="tag pending">no_hit</span>
              <span v-else-if="t.rag_status === 'hit'" class="tag ok">hit</span>
              <span v-else class="tag">{{ t.rag_status }}</span>
            </td>
            <td>
              <button class="mini" :class="{ on: t.feedback === 'up' }" @click="feedback(t, 'up')">赞</button>
              <button class="mini" :class="{ on: t.feedback === 'down' }" @click="feedback(t, 'down')">踩</button>
            </td>
            <td><button class="mini" @click="open(t)">详情</button></td>
          </tr>
          <tr v-if="!items.length"><td colspan="9" class="muted">暂无 trace</td></tr>
        </tbody>
      </table>
      <div class="pager">
        <span class="muted">共 {{ total }} 条</span>
        <button class="mini" :disabled="page <= 1" @click="changePage(-1)">上一页</button>
        <span>{{ page }} / {{ totalPages }}</span>
        <button class="mini" :disabled="page >= totalPages" @click="changePage(1)">下一页</button>
      </div>
    </section>

    <aside v-if="selected" class="drawer">
      <div class="drawer-head">
        <div>
          <h3>{{ selected.query }}</h3>
          <p class="muted mono">{{ selected.trace_id }}</p>
        </div>
        <button class="mini" @click="selected = null">关闭</button>
      </div>
      <div class="meta-grid">
        <div><span>业务域</span><b>{{ selected.domain }}</b></div>
        <div><span>路由</span><b>{{ selected.route }}</b></div>
        <div><span>耗时</span><b>{{ selected.latency_ms }} ms</b></div>
        <div><span>门控丢弃</span><b>{{ selected.gated_out }}</b></div>
        <div><span>向量</span><b>{{ selected.vector_ok ? '成功' : '失败' }}</b></div>
        <div><span>关键词兜底</span><b>{{ selected.keyword_used ? '是' : '否' }}</b></div>
        <div><span>重排</span><b>{{ selected.rerank_ok ? selected.rerank_model || '成功' : '未生效' }}</b></div>
        <div><span>embedding</span><b class="mono">{{ selected.embedding_fingerprint || '-' }}</b></div>
      </div>
      <div class="block">
        <div class="muted">阶段耗时</div>
        <p>{{ stageText(selected) || '-' }}</p>
      </div>
      <div class="block">
        <div class="muted">改写后 query</div>
        <p>{{ selected.rewritten_query || '-' }}</p>
      </div>
      <div v-if="selected.error" class="error">{{ selected.error }}</div>
      <div class="panel-head"><h3>最终命中</h3><span class="muted">{{ selected.hits?.length || 0 }} 条</span></div>
      <div class="hit-list">
        <div v-for="(h, i) in selected.hits || []" :key="i" class="hit">
          <div class="hit-head">
            <span class="tag">#{{ i + 1 }}</span>
            <strong>{{ h.title }}</strong>
            <span class="muted">sim {{ h.similarity ?? '-' }} · rr {{ h.rerank_score ?? '-' }} · rrf {{ h.rrf_score ?? '-' }}</span>
          </div>
          <p>{{ h.preview }}</p>
        </div>
        <div v-if="!selected.hits?.length" class="muted">无命中</div>
      </div>
      <div v-if="selected.related_runs && selected.related_runs.length" class="block">
        <div class="muted">related runs</div>
        <div v-for="r in selected.related_runs" :key="r.run_id" class="hit">
          <div class="hit-head">
            <span class="tag">{{ r.task_kind }}</span>
            <strong>{{ r.intent }}</strong>
            <span class="muted">{{ r.status }} / {{ r.latency_ms }} ms</span>
          </div>
          <p class="muted mono">{{ r.run_id }}</p>
        </div>
      </div>
      <div v-if="selected.conversation_id" class="block">
        <RouterLink class="btn ghost" to="/rag/sessions">session observability</RouterLink>
      </div>
    </aside>
  </div>
</template>

<style scoped>
.btn { padding: 8px 14px; border-radius: 9px; border: 1px solid var(--brand); background: var(--brand); color: #fff; font-weight: 600; cursor: pointer; font-size: 13px; }
.health-strip { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 10px; margin-bottom: 12px; }
.health-strip > div { background: var(--surface); border: 1px solid var(--line); border-radius: 10px; padding: 9px 11px; display: flex; flex-direction: column; gap: 3px; }
.health-strip span { font-size: 11px; color: var(--ink-3); }
.health-strip b { font-size: 16px; color: var(--ink); }
@media (max-width: 1000px) { .health-strip { grid-template-columns: repeat(3, 1fr); } }
@media (max-width: 600px) { .health-strip { grid-template-columns: repeat(2, 1fr); } }
.toolbar { display: flex; gap: 10px; align-items: center; margin-bottom: 12px; flex-wrap: wrap; }
.toolbar input[type='text'], .toolbar input:not([type]), .toolbar select { padding: 8px 10px; border: 1px solid var(--line); border-radius: 9px; background: var(--surface); color: var(--ink); }
label { font-size: 12.5px; color: var(--ink-2); display: flex; gap: 5px; align-items: center; }
.panel { background: var(--surface); border: 1px solid var(--line); border-radius: 14px; padding: 16px; box-shadow: var(--shadow-sm); }
.table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.table th, .table td { text-align: left; padding: 8px 6px; border-bottom: 1px solid var(--line); vertical-align: top; }
.table th { color: var(--ink-3); font-weight: 600; }
.table tr.warn { background: #fffbeb; }
.table tr.danger { background: #fef2f2; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11.5px; }
.muted { color: var(--ink-3); font-size: 12px; }
.query { max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mini { padding: 4px 9px; border: 1px solid var(--line); background: var(--surface); border-radius: 7px; cursor: pointer; font-size: 11.5px; color: var(--ink-2); }
.mini.on { background: var(--brand-soft); color: var(--brand-strong); border-color: var(--brand); }
.tag { display: inline-block; padding: 2px 8px; border-radius: 999px; background: #f1f5f9; color: var(--ink-3); font-size: 11px; }
.tag.ok { background: var(--success-soft); color: #047857; }
.tag.bad { background: #fef2f2; color: #b91c1c; }
.tag.pending { background: #fffbeb; color: #b45309; }
.pager { display: flex; gap: 10px; align-items: center; justify-content: flex-end; margin-top: 12px; }
.error { color: #b91c1c; background: #fef2f2; padding: 10px 12px; border-radius: 10px; margin-bottom: 12px; }
.drawer { position: fixed; right: 20px; top: 20px; bottom: 20px; width: min(620px, 48vw); background: var(--surface); border: 1px solid var(--line); border-radius: 16px; box-shadow: var(--shadow-lg); padding: 18px; overflow: auto; z-index: 80; }
.drawer-head { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }
.drawer-head h3 { font-size: 16px; font-weight: 800; line-height: 1.4; }
.meta-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin: 14px 0; }
.meta-grid div { background: #f8fafc; border-radius: 10px; padding: 9px 10px; display: flex; flex-direction: column; gap: 3px; }
.meta-grid span { color: var(--ink-3); font-size: 11.5px; }
.meta-grid b { font-size: 12.5px; word-break: break-all; }
.block { margin: 12px 0; }
.block p { font-size: 12.5px; line-height: 1.6; white-space: pre-wrap; margin-top: 4px; }
.panel-head { display: flex; align-items: center; justify-content: space-between; margin: 14px 0 8px; }
.panel-head h3 { font-size: 14px; font-weight: 800; }
.hit-list { display: flex; flex-direction: column; gap: 10px; }
.hit { border: 1px solid var(--line); border-radius: 10px; padding: 10px; }
.hit-head { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 6px; font-size: 12.5px; }
.hit p { font-size: 12.5px; line-height: 1.6; color: var(--ink-2); white-space: pre-wrap; }
@media (max-width: 1100px) { .drawer { left: 20px; width: auto; } }
</style>