<script setup lang="ts">
import { onMounted, ref } from 'vue'

import PageHead from '@/components/PageHead.vue'
import RagTabs from '@/components/RagTabs.vue'
import { getAgentOpsStats, type AgentOpsStats } from '@/api/agentOps'
import { getRagOverview, type RagOverview } from '@/api/ragAdmin'
import { getUsageStats, type UsageStats } from '@/api/usage'

const loading = ref(false)
const error = ref('')
const data = ref<RagOverview | null>(null)
const ops = ref<AgentOpsStats | null>(null)
const usage = ref<UsageStats | null>(null)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [overview, stats, usageStats] = await Promise.all([
      getRagOverview(),
      getAgentOpsStats(7),
      getUsageStats(7),
    ])
    data.value = overview
    ops.value = stats
    usage.value = usageStats
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
function rateTone(v: number | null | undefined, good = 0.8, warn = 0.6) {
  if (v == null) return 'neutral'
  return v >= good ? 'good' : v >= warn ? 'warn' : 'bad'
}
function latencyTone(v: number | null | undefined, good = 800, warn = 2000) {
  if (v == null) return 'neutral'
  return v <= good ? 'good' : v <= warn ? 'warn' : 'bad'
}
function evalMetric(path: [string, string] | [string], fallback = '-') {
  const m = data.value?.latest_eval?.metrics
  if (!m) return fallback
  let cur: any = m
  for (const key of path) {
    if (cur == null || typeof cur !== 'object') return fallback
    cur = cur[key]
  }
  return cur == null ? fallback : cur
}
function score(v: any) {
  if (v == null || Number.isNaN(Number(v))) return '-'
  return Number(v).toFixed(3)
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

    <RagTabs />

    <p v-if="error" class="error">{{ error }}</p>

    <template v-if="data">
      <section class="grid cards">
        <div class="card" :class="data.assets.failed ? 'tone-bad' : 'tone-good'">
          <div class="card-label">知识资产健康</div>
          <div class="card-value">{{ data.assets.ready }} / {{ data.assets.documents }}</div>
          <div class="bar"><span :style="{ width: `${data.assets.documents ? Math.round(data.assets.ready / data.assets.documents * 100) : 0}%` }" /></div>
          <div class="card-sub">ready 率 {{ pct(data.assets.documents ? data.assets.ready / data.assets.documents : null) }} · 分片 {{ data.assets.chunks }} · 索引中 {{ data.assets.indexing }}</div>
          <div v-if="data.assets.failed" class="card-alert">失败 {{ data.assets.failed }} 篇，需重试/修复</div>
        </div>
        <div class="card" :class="`tone-${rateTone(data.retrieval_24h.hit_rate_excl_errors)}`">
          <div class="card-label">24h 检索命中率</div>
          <div class="card-value">{{ pct(data.retrieval_24h.hit_rate_excl_errors) }}</div>
          <div class="card-sub">排除错误口径 · 零结果 {{ pct(data.retrieval_24h.zero_result_rate) }} · 错误 {{ pct(data.retrieval_24h.error_rate) }}</div>
          <div class="card-sub">查询 {{ data.retrieval_24h.queries }} 次 · 命中 {{ data.retrieval_24h.hits ?? 0 }} · 零结果 {{ data.retrieval_24h.zero_results }}</div>
        </div>
        <div class="card" :class="`tone-${latencyTone(data.retrieval_24h.p95_latency_ms)}`">
          <div class="card-label">24h 检索 P95</div>
          <div class="card-value">{{ ms(data.retrieval_24h.p95_latency_ms) }}</div>
          <div class="card-sub">平均 {{ ms(data.retrieval_24h.avg_latency_ms) }} · 平均候选 {{ data.retrieval_24h.avg_candidates ?? '-' }} 条</div>
          <div class="card-sub">向量成功 {{ pct(data.retrieval_24h.vector_success_rate) }} · 重排成功 {{ pct(data.retrieval_24h.rerank_success_rate) }} · 关键词兜底 {{ pct(data.retrieval_24h.keyword_rate) }}</div>
        </div>
        <div class="card" :class="data.assets.parent_visible === 0 ? 'tone-bad' : 'tone-good'">
          <div class="card-label">家长客服知识覆盖</div>
          <div class="card-value">{{ data.assets.parent_visible }} 篇</div>
          <div class="card-sub">家长可见文档 / 启用 {{ data.assets.enabled }} · 广场 {{ data.assets.plaza }}</div>
          <div v-if="data.assets.parent_visible === 0" class="card-alert">家长端 RAG 白名单为空，客服只会兜底转人工</div>
          <div v-else class="card-sub">最近更新 {{ data.assets.last_updated?.slice(0, 10) || '-' }}</div>
        </div>
      </section>

      <section v-if="ops" class="panel">
        <div class="panel-head">
          <h3>Agent 任务健康度（7 天）</h3>
          <RouterLink class="link" to="/rag/runs">任务监控</RouterLink>
        </div>
        <div class="ops-grid health-grid">
          <div :class="`tone-${rateTone(ops.success_rate, 0.98, 0.9)}`">
            <span>任务成功率</span><b>{{ pct(ops.success_rate) }}</b>
            <small>{{ ops.ok_runs }} 成功 / {{ ops.error_runs }} 失败 · 共 {{ ops.total_runs }} 次</small>
          </div>
          <div :class="`tone-${ops.rag_miss_rate == null ? 'neutral' : ops.rag_miss_rate <= 0.05 ? 'good' : ops.rag_miss_rate <= 0.2 ? 'warn' : 'bad'}`">
            <span>RAG 漏检率</span><b>{{ pct(ops.rag_miss_rate) }}</b>
            <small>需要 RAG {{ ops.needs_rag }} · 实际使用 {{ ops.rag_used }} · 漏检 {{ ops.rag_missed }}</small>
          </div>
          <div :class="`tone-${rateTone(((ops.ppt_task_runs ?? 0) > 0 ? ops.ppt_task_alignment_rate : ops.ppt_alignment_rate), 0.95, 0.8)}`">
            <span>PPT 页数达成率</span><b>{{ pct((ops.ppt_task_runs ?? 0) > 0 ? ops.ppt_task_alignment_rate : ops.ppt_alignment_rate) }}</b>
            <small>{{ (ops.ppt_task_runs ?? 0) > 0 ? ops.ppt_task_aligned : ops.ppt_aligned }} / {{ (ops.ppt_task_runs ?? 0) > 0 ? (ops.ppt_task_runs ?? 0) : (ops.ppt_planned_runs ?? 0) }} 个任务 · 交付率 {{ pct((ops.ppt_task_runs ?? 0) > 0 ? ops.ppt_task_delivery_rate : ops.ppt_delivery_rate) }}</small>
          </div>
          <div :class="`tone-${latencyTone(ops.interactive_latency?.p95_ms)}`">
            <span>交互应答 P95</span><b>{{ ms(ops.interactive_latency?.p95_ms) }}</b>
            <small>P50 {{ ms(ops.interactive_latency?.p50_ms) }} · 首字 P95 {{ ms(ops.interactive_latency?.first_token_p95_ms) }}</small>
          </div>
          <div :class="`tone-${latencyTone(ops.long_task_latency?.p95_ms, 300000, 900000)}`">
            <span>长任务 P95</span><b>{{ ms(ops.long_task_latency?.p95_ms) }}</b>
            <small>PPT / Skill / 工具类任务 · P50 {{ ms(ops.long_task_latency?.p50_ms) }}</small>
          </div>
          <div>
            <span>Token / 成本（用量账本 7 天）</span>
            <b>{{ usage ? (usage.input_tokens + usage.output_tokens).toLocaleString() : '-' }}</b>
            <small v-if="usage">平台 ¥{{ usage.cost_platform.toFixed(2) }} · 教师 ¥{{ usage.cost_teacher.toFixed(2) }} · 估算占比 {{ pct(usage.estimated_ratio) }}</small>
            <small v-else>用量账本暂无数据</small>
          </div>
        </div>
        <p class="metric-note">
          口径：PPT 页数达成率优先按「PPT 任务契约」统计（已交付且目标页数明确）；无契约但已出片时按实际成品页数补记，避免明明产出 PPT 却显示 0。未指定页数的运行不计入分母。交互应答与长任务分开统计 P95，避免 PPT/长任务把客服对话时延指标整体拖高。
        </p>
      </section>

      <section class="panel">
        <div class="panel-head">
          <h3>RAG 权威评测指标（最近一次已完成评测）</h3>
          <RouterLink class="link" to="/rag/eval">去评测</RouterLink>
        </div>
        <template v-if="data.latest_eval">
          <div class="ops-grid eval-grid">
            <div><span>Hit@1</span><b>{{ score(evalMetric(['on', 'hit@1'])) }}</b><small>Top1 命中率</small></div>
            <div><span>Hit@3</span><b>{{ score(evalMetric(['on', 'hit@3'])) }}</b><small>Top3 命中率</small></div>
            <div><span>Recall@5</span><b>{{ score(evalMetric(['on', 'recall@5'])) }}</b><small>前 5 条召回</small></div>
            <div><span>nDCG@5</span><b>{{ score(evalMetric(['on', 'ndcg@5'])) }}</b><small>排序质量</small></div>
            <div><span>MRR</span><b>{{ score(evalMetric(['on', 'mrr'])) }}</b><small>首个相关文档排名</small></div>
            <div><span>忠实度</span><b>{{ score(evalMetric(['answer', 'faithfulness'])) }}</b><small>答案忠于检索片段（0-5）</small></div>
            <div><span>相关性</span><b>{{ score(evalMetric(['answer', 'relevance'])) }}</b><small>答案切题程度（0-5）</small></div>
            <div><span>完整性</span><b>{{ score(evalMetric(['answer', 'completeness'])) }}</b><small>关键信息覆盖（0-5）</small></div>
          </div>
          <p class="metric-note">
            评测集用例 {{ evalMetric(['on', 'cases']) }} 条 · 完成时间 {{ data.latest_eval.finished_at?.slice(0, 19).replace('T', ' ') || '-' }}。
            检索指标来自标注集（文档级），答案指标由裁判模型按 0-5 打分；这是比线上零结果率更强的质量依据。
          </p>
        </template>
        <div v-else class="ok-tip">还没有已完成的评测。建议先建评测集，再比较“关闭/开启 Rerank”的 Hit@3 与 MRR。</div>
      </section>

      <section class="panel">
        <div class="panel-head">
          <h3>指标口径说明</h3>
          <span class="muted">看不懂的指标从这里查</span>
        </div>
        <div class="def-grid">
          <div><b>检索命中率</b><span>24h 内返回至少 1 条可用片段的查询占比；分母排除报错查询，避免配置错误把质量指标拉低。</span></div>
          <div><b>零结果率</b><span>检索返回 0 条片段的比例。偏高通常表示知识库没有覆盖、相似度门槛过高或文档未启用。</span></div>
          <div><b>RAG 漏检率</b><span>意图判定“需要知识库”但实际没有检索的次数 / 需要检索总次数。检索开关打开却没有引用时，看这个指标。</span></div>
          <div><b>PPT 页数达成率</b><span>实际页数与目标页数一致的任务 / 用户明确指定页数的 PPT 任务。未指定页数的生成不计入分母。</span></div>
          <div><b>Hit@K / MRR</b><span>评测集里前 K 条是否命中人工标注的相关文档；MRR 衡量首个相关文档排得有多靠前。</span></div>
          <div><b>忠实度 / 相关性</b><span>裁判模型对答案是否忠于检索片段、是否回答问题的 0-5 分评分。</span></div>
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
.card.tone-good { border-top: 3px solid #10b981; }
.card.tone-warn { border-top: 3px solid #f59e0b; background: #fffdf7; }
.card.tone-bad { border-top: 3px solid #ef4444; background: #fffafa; }
.card-label { color: var(--ink-3); font-size: 12px; font-weight: 600; }
.card-value { font-size: 24px; font-weight: 800; margin: 6px 0 4px; color: var(--ink); }
.card-sub { color: var(--ink-3); font-size: 12px; line-height: 1.6; }
.card-alert { margin-top: 6px; padding: 5px 8px; border-radius: 8px; background: #fef2f2; color: #b91c1c; font-size: 11.5px; font-weight: 600; }
.bar { height: 6px; border-radius: 999px; background: #eef2f7; overflow: hidden; margin-bottom: 7px; }
.bar span { display: block; height: 100%; border-radius: inherit; background: linear-gradient(90deg, #10b981, #06b6d4); }
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
.ops-grid.eval-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); }
.ops-grid > div { display: flex; flex-direction: column; gap: 3px; padding: 10px 12px; border: 1px solid var(--line); border-radius: 10px; background: #fbfdff; }
.ops-grid > div.tone-good { background: #f0fdf8; border-color: #a7f3d0; }
.ops-grid > div.tone-warn { background: #fffbeb; border-color: #fde68a; }
.ops-grid > div.tone-bad { background: #fef2f2; border-color: #fecaca; }
.ops-grid span { color: var(--ink-3); font-size: 12px; }
.ops-grid b { font-size: 18px; }
.ops-grid small { color: var(--ink-3); font-size: 11px; }
.metric-note { margin: 10px 0 0; color: var(--ink-3); font-size: 11.5px; line-height: 1.7; background: #f8fafc; border-radius: 8px; padding: 8px 10px; }
.def-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
.def-grid > div { padding: 10px 12px; border: 1px solid var(--line); border-radius: 10px; background: #fbfdff; display: flex; flex-direction: column; gap: 4px; }
.def-grid b { font-size: 12.5px; }
.def-grid span { color: var(--ink-3); font-size: 11.5px; line-height: 1.65; }
@media (max-width: 1100px) { .ops-grid, .ops-grid.eval-grid { grid-template-columns: 1fr 1fr; } .def-grid { grid-template-columns: 1fr; } }
@media (max-width: 1100px) { .grid.cards { grid-template-columns: 1fr 1fr; } .two-col { grid-template-columns: 1fr; } }
</style>
