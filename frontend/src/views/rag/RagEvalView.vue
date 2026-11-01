<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import PageHead from '@/components/PageHead.vue'
import {
  addEvalCase,
  createEvalRun,
  createEvalSet,
  deleteEvalCase,
  deleteEvalSet,
  generateEvalCases,
  getEvalRun,
  listEvalCases,
  listEvalRuns,
  listEvalSets,
  type RagEvalCase,
  type RagEvalResult,
  type RagEvalRun,
  type RagEvalSet,
} from '@/api/ragAdmin'

const sets = ref<RagEvalSet[]>([])
const activeSet = ref<RagEvalSet | null>(null)
const cases = ref<RagEvalCase[]>([])
const runs = ref<RagEvalRun[]>([])
const activeRun = ref<RagEvalRun | null>(null)
const results = ref<RagEvalResult[]>([])
const loading = ref(false)
const error = ref('')
const msg = ref('')

const newSet = ref({ name: '', description: '', domain: 'agent_teacher', owner_id: '' })
const newCase = ref({ query: '', relevant: '', gt_answer: '', notes: '', query_type: 'fact' })
const runForm = ref({ top_k: 5, rerank: true, answer_eval: false })
const genForm = ref({ doc_ids: '', count: 10, use_llm: false })

const metricsOn = computed(() => activeRun.value?.metrics?.on || null)
const metricsOff = computed(() => activeRun.value?.metrics?.off || null)

async function loadSets() {
  loading.value = true
  error.value = ''
  try {
    sets.value = await listEvalSets()
    if (!activeSet.value && sets.value.length) await selectSet(sets.value[0])
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}

async function selectSet(s: RagEvalSet) {
  activeSet.value = s
  activeRun.value = null
  results.value = []
  try {
    cases.value = await listEvalCases(s.id)
    runs.value = await listEvalRuns(s.id)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  }
}

async function createSet() {
  if (!newSet.value.name.trim()) return
  try {
    const s = await createEvalSet({
      name: newSet.value.name,
      description: newSet.value.description,
      domain: newSet.value.domain,
      owner_id: newSet.value.owner_id || undefined,
    })
    msg.value = '评测集已创建'
    newSet.value = { name: '', description: '', domain: 'agent_teacher', owner_id: '' }
    await loadSets()
    await selectSet(s)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '创建失败'
  }
}

async function removeSet(s: RagEvalSet) {
  if (!confirm(`删除评测集「${s.name}」及其用例？`)) return
  try {
    await deleteEvalSet(s.id)
    if (activeSet.value?.id === s.id) activeSet.value = null
    await loadSets()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '删除失败'
  }
}

async function addCase() {
  if (!activeSet.value || !newCase.value.query.trim()) return
  try {
    await addEvalCase(activeSet.value.id, {
      query: newCase.value.query,
      relevant: newCase.value.relevant.split(/[,，\n]/).map((x) => x.trim()).filter(Boolean),
      gt_answer: newCase.value.gt_answer,
      notes: newCase.value.notes,
      query_type: newCase.value.query_type,
    })
    msg.value = '用例已添加'
    newCase.value = { query: '', relevant: '', gt_answer: '', notes: '', query_type: 'fact' }
    cases.value = await listEvalCases(activeSet.value.id)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '添加失败'
  }
}

async function removeCase(c: RagEvalCase) {
  if (!confirm('删除该用例？')) return
  try {
    await deleteEvalCase(c.id)
    if (activeSet.value) cases.value = await listEvalCases(activeSet.value.id)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '删除失败'
  }
}

async function startRun() {
  if (!activeSet.value) return
  try {
    const run = await createEvalRun(activeSet.value.id, {
      top_k: runForm.value.top_k,
      rerank: runForm.value.rerank,
      answer_eval: runForm.value.answer_eval,
    })
    msg.value = '评测已启动，稍后刷新查看结果'
    activeRun.value = run
    runs.value = await listEvalRuns(activeSet.value.id)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '启动失败'
  }
}

async function generateCases() {
  if (!activeSet.value || !genForm.value.doc_ids.trim()) return
  try {
    const r = await generateEvalCases(activeSet.value.id, {
      doc_ids: genForm.value.doc_ids.split(/[,，\n]/).map((x) => x.trim()).filter(Boolean),
      count: genForm.value.count,
      use_llm: genForm.value.use_llm,
    })
    msg.value = `已生成 ${r.created} 条候选用例，请复核`
    genForm.value.doc_ids = ''
    cases.value = await listEvalCases(activeSet.value.id)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '生成失败'
  }
}

async function openRun(r: RagEvalRun) {
  try {
    const data = await getEvalRun(r.id)
    activeRun.value = data.run
    results.value = data.results
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  }
}

function pct(v: number | undefined | null) {
  return v == null ? '-' : `${Math.round(v * 100)}%`
}
function fixed(v: number | undefined | null) {
  return v == null ? '-' : Number(v).toFixed(3)
}

onMounted(loadSets)
</script>

<template>
  <div>
    <PageHead title="评测中心" eyebrow="RAG EVAL" sub="Q-DOC 检索指标、重排 A/B 与 Bad Case 分类">
      <template #actions>
        <button class="btn ghost" :disabled="loading" @click="loadSets">{{ loading ? '刷新中…' : '刷新' }}</button>
      </template>
    </PageHead>

    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="msg" class="ok">{{ msg }}</p>

    <section class="two-col">
      <div class="panel">
        <div class="panel-head"><h3>评测集</h3></div>
        <div class="set-list">
          <button v-for="s in sets" :key="s.id" class="set-item" :class="{ on: activeSet?.id === s.id }" @click="selectSet(s)">
            <span>{{ s.name }}</span>
            <span class="muted">{{ s.domain }}</span>
            <span class="mini danger" @click.stop="removeSet(s)">删</span>
          </button>
          <div v-if="!sets.length" class="muted">暂无评测集</div>
        </div>
        <div class="create-box">
          <input v-model="newSet.name" placeholder="评测集名称" />
          <input v-model="newSet.description" placeholder="说明（可选）" />
          <select v-model="newSet.domain">
            <option value="agent_teacher">agent_teacher</option>
            <option value="parent_service">parent_service</option>
          </select>
          <input v-model="newSet.owner_id" placeholder="owner_id（可选）" />
          <button class="btn" @click="createSet">新建评测集</button>
        </div>
      </div>

      <div class="panel">
        <div class="panel-head"><h3>运行评测</h3><span class="muted">{{ activeSet?.name || '请选择评测集' }}</span></div>
        <div class="run-form">
          <label>top_k <input v-model.number="runForm.top_k" type="number" min="1" max="50" /></label>
          <label class="check"><input v-model="runForm.rerank" type="checkbox" /> 启用 rerank（同时跑 off/on 对比）</label>
          <label class="check"><input v-model="runForm.answer_eval" type="checkbox" /> 答案质量评测（LLM 裁判）</label>
          <button class="btn" :disabled="!activeSet || !cases.length" @click="startRun">开始评测</button>
        </div>
        <div class="muted">评测会同时跑 rerank=off 与 rerank=on，输出对比与逐条 Bad Case。</div>
      </div>
    </section>

    <section v-if="activeSet" class="panel">
      <div class="panel-head"><h3>用例（{{ cases.length }}）</h3></div>
      <div class="case-form">
        <input v-model="newCase.query" placeholder="用户问题" />
        <input v-model="newCase.relevant" placeholder="应命中文档标题，逗号分隔" />
        <input v-model="newCase.gt_answer" placeholder="标准答案（可选）" />
        <input v-model="newCase.notes" placeholder="备注（可选）" />
        <button class="btn" @click="addCase">添加用例</button>
      </div>
      <div class="case-form gen-form">
        <input v-model="genForm.doc_ids" placeholder="从文档分片生成：doc_id，逗号分隔" />
        <input v-model.number="genForm.count" type="number" min="1" max="100" />
        <label class="check"><input v-model="genForm.use_llm" type="checkbox" /> LLM 生成</label>
        <button class="btn ghost" :disabled="!genForm.doc_ids.trim()" @click="generateCases">生成候选用例</button>
      </div>
      <table class="table">
        <thead><tr><th>query</th><th>relevant</th><th>类型</th><th>来源</th><th></th></tr></thead>
        <tbody>
          <tr v-for="c in cases" :key="c.id">
            <td>{{ c.query }}</td>
            <td class="muted">{{ c.relevant.join('、') || '-' }}</td>
            <td>{{ c.query_type }}</td>
            <td>{{ c.source }}</td>
            <td><button class="mini danger" @click="removeCase(c)">删除</button></td>
          </tr>
          <tr v-if="!cases.length"><td colspan="5" class="muted">暂无用例</td></tr>
        </tbody>
      </table>
    </section>

    <section v-if="activeSet" class="panel">
      <div class="panel-head"><h3>运行记录</h3></div>
      <table class="table">
        <thead><tr><th>状态</th><th>top_k</th><th>配置版本</th><th>hit@3 off → on</th><th>MRR off → on</th><th>时间</th><th></th></tr></thead>
        <tbody>
          <tr v-for="r in runs" :key="r.id">
            <td><span class="tag" :class="r.status === 'done' ? 'ok' : r.status === 'failed' ? 'bad' : 'pending'">{{ r.status }}</span></td>
            <td>{{ r.top_k }}</td>
            <td>{{ r.config_version ?? '-' }}</td>
            <td>{{ fixed(r.metrics?.off?.['hit@3']) }} → {{ fixed(r.metrics?.on?.['hit@3']) }}</td>
            <td>{{ fixed(r.metrics?.off?.mrr) }} → {{ fixed(r.metrics?.on?.mrr) }}</td>
            <td class="mono">{{ r.created_at?.slice(0, 16).replace('T', ' ') }}</td>
            <td><button class="mini" @click="openRun(r)">详情</button></td>
          </tr>
          <tr v-if="!runs.length"><td colspan="7" class="muted">暂无运行记录</td></tr>
        </tbody>
      </table>
    </section>

    <section v-if="activeRun" class="panel">
      <div class="panel-head"><h3>评测结果</h3><span class="muted">{{ activeRun.status }}</span></div>
      <p v-if="activeRun.error" class="error">{{ activeRun.error }}</p>
      <div class="metrics">
        <div class="metric"><span>hit@3 (off)</span><b>{{ fixed(metricsOff?.['hit@3']) }}</b></div>
        <div class="metric"><span>hit@3 (on)</span><b>{{ fixed(metricsOn?.['hit@3']) }}</b></div>
        <div class="metric"><span>MRR (off)</span><b>{{ fixed(metricsOff?.mrr) }}</b></div>
        <div class="metric"><span>MRR (on)</span><b>{{ fixed(metricsOn?.mrr) }}</b></div>
        <div class="metric"><span>recall@5 (on)</span><b>{{ fixed(metricsOn?.['recall@5']) }}</b></div>
        <div class="metric"><span>nDCG@5 (on)</span><b>{{ fixed(metricsOn?.['ndcg@5']) }}</b></div>
        <div class="metric"><span>答案关键词命中</span><b>{{ pct(activeRun.metrics?.answer?.keyword_hit) }}</b></div>
        <div class="metric"><span>忠实度</span><b>{{ fixed(activeRun.metrics?.answer?.faithfulness) }}</b></div>
        <div class="metric"><span>完整性</span><b>{{ fixed(activeRun.metrics?.answer?.completeness) }}</b></div>
        <div class="metric"><span>逻辑性</span><b>{{ fixed(activeRun.metrics?.answer?.logic) }}</b></div>
      </div>
      <table class="table">
        <thead><tr><th>query</th><th>ranked</th><th>relevant</th><th>Bad Case</th><th>检索链</th></tr></thead>
        <tbody>
          <tr v-for="r in results" :key="r.id">
            <td>{{ r.query }}</td>
            <td class="muted">{{ r.ranked.join('、') || '-' }}</td>
            <td class="muted">{{ r.relevant.join('、') || '-' }}</td>
            <td><span class="tag" :class="r.bad_case_type === 'ok' ? 'ok' : 'bad'">{{ r.bad_case_type || '-' }}</span></td>
            <td class="muted ellipsis">{{ r.retrieval_summary }}</td>
          </tr>
          <tr v-if="!results.length"><td colspan="5" class="muted">暂无逐条结果（运行中或未完成）</td></tr>
        </tbody>
      </table>
    </section>
  </div>
</template>

<style scoped>
.btn { padding: 8px 14px; border-radius: 9px; border: 1px solid var(--brand); background: var(--brand); color: #fff; font-weight: 600; cursor: pointer; font-size: 13px; }
.btn.ghost { background: var(--surface); color: var(--brand-strong); border-color: var(--line); }
.btn:disabled { opacity: .6; cursor: default; }
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px; }
.panel { background: var(--surface); border: 1px solid var(--line); border-radius: 14px; padding: 16px; margin-bottom: 16px; box-shadow: var(--shadow-sm); }
.panel-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.panel-head h3 { font-size: 14px; font-weight: 800; }
.set-list { display: flex; flex-direction: column; gap: 6px; margin-bottom: 12px; }
.set-item { display: flex; justify-content: space-between; align-items: center; gap: 8px; padding: 9px 10px; border: 1px solid var(--line); border-radius: 9px; background: var(--surface); cursor: pointer; text-align: left; }
.set-item.on { border-color: var(--brand); background: var(--brand-soft); }
.create-box, .case-form, .run-form { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.create-box input, .create-box select, .case-form input, .run-form input { padding: 8px 10px; border: 1px solid var(--line); border-radius: 9px; background: var(--surface); color: var(--ink); font-size: 12.5px; }
.create-box input:first-child, .case-form input:first-child { flex: 1; min-width: 180px; }
.run-form label { display: flex; gap: 6px; align-items: center; font-size: 12.5px; }
.table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.table th, .table td { text-align: left; padding: 8px 6px; border-bottom: 1px solid var(--line); }
.table th { color: var(--ink-3); font-weight: 600; }
.muted { color: var(--ink-3); font-size: 12px; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11.5px; }
.mini { padding: 4px 9px; border: 1px solid var(--line); background: var(--surface); border-radius: 7px; cursor: pointer; font-size: 11.5px; }
.mini.danger { color: #b91c1c; border-color: #fecaca; }
.tag { display: inline-block; padding: 2px 8px; border-radius: 999px; background: #f1f5f9; color: var(--ink-3); font-size: 11px; }
.tag.ok { background: var(--success-soft); color: #047857; }
.tag.bad { background: #fef2f2; color: #b91c1c; }
.tag.pending { background: #fffbeb; color: #b45309; }
.metrics { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 10px; margin-bottom: 14px; }
.metric { background: #f8fafc; border-radius: 10px; padding: 10px; display: flex; flex-direction: column; gap: 4px; }
.metric span { color: var(--ink-3); font-size: 11.5px; }
.metric b { font-size: 18px; }
.error { color: #b91c1c; background: #fef2f2; padding: 10px 12px; border-radius: 10px; margin-bottom: 12px; }
.ok { color: #047857; background: var(--success-soft); padding: 10px 12px; border-radius: 10px; margin-bottom: 12px; }
.ellipsis { max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
@media (max-width: 1100px) { .two-col { grid-template-columns: 1fr; } .metrics { grid-template-columns: 1fr 1fr 1fr; } }
</style>
