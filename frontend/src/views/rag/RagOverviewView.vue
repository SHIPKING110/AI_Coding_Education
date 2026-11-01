<script setup lang="ts">
import { onMounted, ref } from 'vue'

import PageHead from '@/components/PageHead.vue'
import { getAgentOpsStats, type AgentOpsStats } from '@/api/agentOps'
import { getRagOverview, type RagOverview } from '@/api/ragAdmin'

const loading = ref(false)
const error = ref('')
const data = ref<RagOverview | null>(null)
const ops = ref<AgentOpsStats | null>(null)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [overview, stats] = await Promise.all([getRagOverview(), getAgentOpsStats(7)])
    data.value = overview
    ops.value = stats
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}

function pct(v: number | null | undefined) {
  return v == null ? '-' : `${Math.round(v * 100)}%`
}
function ms(v: number | null | undefined) {
  return v == null ? '-' : `${Math.round(v)} ms`
}

onMounted(load)
</script>

<template>
  <div>
    <PageHead title="RAG 运行总览" eyebrow="RAG OPS" sub="知识资产、检索健康与风险一屏掌握">
      <template #actions>
        <button class="btn" :disabled="loading" @click="load">{{ loading ? '刷新中…' : '刷新' }}</button>
        <RouterLink class="btn ghost" to="/rag/assets">知识资产</RouterLink>
        <RouterLink class="btn ghost" to="/rag/traces">检索追踪</RouterLink>
        <RouterLink class="btn ghost" to="/rag/runs">任务监控</RouterLink>
        <RouterLink class="btn ghost" to="/rag/routes">路由测试</RouterLink>
      </template>
    </PageHead>

    <p v-if="error" class="error">{{ error }}</p>

    <template v-if="data">
      <section class="grid cards">
        <div class="card">
          <div class="card-label">文档 / 分片</div>
          <div class="card-value">{{ data.assets.documents }} / {{ data.assets.chunks }}</div>
          <div class="card-sub">ready {{ data.assets.ready }} · failed {{ data.assets.failed }} · 索引中 {{ data.assets.indexing }}</div>
        </div>
        <div class="card">
          <div class="card-label">24h 检索量</div>
          <div class="card-value">{{ data.retrieval_24h.queries }}</div>
          <div class="card-sub">命中率 {{ pct(data.retrieval_24h.hit_rate) }} · 零结果 {{ pct(data.retrieval_24h.zero_result_rate) }}</div>
        </div>
        <div class="card">
          <div class="card-label">24h 平均时延</div>
          <div class="card-value">{{ ms(data.retrieval_24h.avg_latency_ms) }}</div>
          <div class="card-sub">向量失败 {{ data.retrieval_24h.vector_fail }} · 关键词兜底 {{ data.retrieval_24h.keyword_used }}</div>
        </div>
        <div class="card">
          <div class="card-label">启用 / 家长可见</div>
          <div class="card-value">{{ data.assets.enabled }} / {{ data.assets.parent_visible }}</div>
          <div class="card-sub">广场 {{ data.assets.plaza }} · 最近更新 {{ data.assets.last_updated?.slice(0, 10) || '-' }}</div>
        </div>
      </section>

      <section v-if="ops" class="panel">
        <div class="panel-head">
          <h3>Agent 任务与意图（7 天）</h3>
          <RouterLink class="link" to="/rag/runs">任务监控</RouterLink>
        </div>
        <div class="ops-grid">
          <div><span>运行数</span><b>{{ ops.total_runs }}</b><small>成功率 {{ pct(ops.success_rate) }}</small></div>
          <div><span>RAG 漏检</span><b>{{ ops.rag_missed }}</b><small>需要 RAG {{ ops.needs_rag }} · 漏检率 {{ pct(ops.rag_miss_rate) }}</small></div>
          <div><span>PPT 对齐率</span><b>{{ pct(ops.ppt_alignment_rate) }}</b><small>{{ ops.ppt_aligned }} / {{ ops.ppt_runs }} 次</small></div>
          <div><span>P95 时延</span><b>{{ ms(ops.p95_latency_ms) }}</b><small>Token {{ ops.input_tokens }} / {{ ops.output_tokens }}</small></div>
        </div>
      </section>

      <section class="panel">
        <div class="panel-head">
          <h3>风险提示</h3>
          <span class="muted">来自索引状态与 24h 检索指标</span>
        </div>
        <div v-if="!data.risks.length" class="ok-tip">暂无风险，链路状态正常</div>
        <ul v-else class="risk-list">
          <li v-for="(r, i) in data.risks" :key="i" :class="r.level">
            <strong>{{ r.title }}</strong>
            <span>{{ r.detail }}</span>
          </li>
        </ul>
      </section>

      <section class="two-col">
        <div class="panel">
          <div class="panel-head"><h3>业务域拆分（7 天）</h3></div>
          <table class="table">
            <thead><tr><th>域</th><th>查询</th><th>零结果率</th><th>平均时延</th></tr></thead>
            <tbody>
              <tr v-for="d in data.domains_7d" :key="d.domain">
                <td>{{ d.domain }}</td>
                <td>{{ d.queries }}</td>
                <td>{{ pct(d.zero_result_rate) }}</td>
                <td>{{ ms(d.avg_latency_ms) }}</td>
              </tr>
              <tr v-if="!data.domains_7d.length"><td colspan="4" class="muted">暂无检索记录</td></tr>
            </tbody>
          </table>
        </div>

        <div class="panel">
          <div class="panel-head"><h3>向量集合</h3></div>
          <table class="table">
            <thead><tr><th>集合</th><th>分片</th><th>状态</th></tr></thead>
            <tbody>
              <tr v-for="c in data.collections.collections" :key="c.name">
                <td class="mono">{{ c.name }}</td>
                <td>{{ c.count }}</td>
                <td><span class="tag" :class="{ active: c.active }">{{ c.active ? 'active' : '历史' }}</span></td>
              </tr>
              <tr v-if="!data.collections.collections.length"><td colspan="3" class="muted">暂无集合</td></tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="panel">
        <div class="panel-head">
          <h3>最近错误</h3>
          <RouterLink class="link" to="/rag/traces?error_only=1">查看全部</RouterLink>
        </div>
        <table class="table">
          <thead><tr><th>时间</th><th>域</th><th>query</th><th>错误</th><th>耗时</th></tr></thead>
          <tbody>
            <tr v-for="t in data.recent_errors" :key="t.id">
              <td class="mono">{{ t.created_at?.slice(0, 19).replace('T', ' ') }}</td>
              <td>{{ t.domain }}</td>
              <td class="ellipsis">{{ t.query }}</td>
              <td class="error-text ellipsis">{{ t.error }}</td>
              <td>{{ t.latency_ms }} ms</td>
            </tr>
            <tr v-if="!data.recent_errors.length"><td colspan="5" class="muted">暂无错误</td></tr>
          </tbody>
        </table>
      </section>
    </template>
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
.muted { color: var(--ink-3); font-size: 12px; }
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.table th, .table td { text-align: left; padding: 8px 6px; border-bottom: 1px solid var(--line); }
.table th { color: var(--ink-3); font-weight: 600; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11.5px; }
.ellipsis { max-width: 360px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.error { color: #b91c1c; background: #fef2f2; padding: 10px 12px; border-radius: 10px; margin-bottom: 12px; }
.error-text { color: #b91c1c; }
.ok-tip { color: #047857; background: var(--success-soft); padding: 10px 12px; border-radius: 10px; font-size: 12.5px; }
.risk-list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 8px; }
.risk-list li { display: flex; gap: 10px; align-items: baseline; padding: 10px 12px; border-radius: 10px; background: #fffbeb; border: 1px solid #fde68a; font-size: 12.5px; }
.risk-list li.error { background: #fef2f2; border-color: #fecaca; }
.tag { display: inline-block; padding: 2px 8px; border-radius: 999px; background: #f1f5f9; color: var(--ink-3); font-size: 11px; }
.tag.active { background: var(--success-soft); color: #047857; }
.link { color: var(--brand-strong); font-size: 12px; text-decoration: none; }
.ops-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.ops-grid > div { display: flex; flex-direction: column; gap: 3px; padding: 10px 12px; border: 1px solid var(--line); border-radius: 10px; background: #fbfdff; }
.ops-grid span { color: var(--ink-3); font-size: 12px; }
.ops-grid b { font-size: 18px; }
.ops-grid small { color: var(--ink-3); font-size: 11px; }
@media (max-width: 1100px) { .ops-grid { grid-template-columns: 1fr 1fr; } }
@media (max-width: 1100px) { .grid.cards { grid-template-columns: 1fr 1fr; } .two-col { grid-template-columns: 1fr; } }
</style>
