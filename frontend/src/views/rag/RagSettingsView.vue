<script setup lang="ts">
import { onMounted, ref } from 'vue'

import PageHead from '@/components/PageHead.vue'
import RagTabs from '@/components/RagTabs.vue'
import { getEmbeddingConfig, type RetrievalConfigOut } from '@/api/retrievalConfig'
import {
  getRagConfig,
  listRagAudit,
  listRagConfigVersions,
  rollbackRagConfig,
  updateRagConfig,
  type RagConfigVersion,
} from '@/api/ragAdmin'

interface Cfg {
  chunk_size: number
  chunk_overlap: number
  parent_chunk_size: number
  top_k: number
  rerank_oversample: number
  min_similarity: number
  per_doc_cap: number
  rerank_timeout_s: number
  rerank_circuit_threshold: number
  rerank_circuit_cooldown_s: number
  keyword_fallback_enabled: boolean
  hybrid_enabled: boolean
  hybrid_candidates: number
  query_rewrite_enabled: boolean
  trace_success_sample_rate: number
  trace_retention_days: number
  trace_error_retention_days: number
}

const form = ref<Cfg | null>(null)
const defaults = ref<Cfg | null>(null)
const versions = ref<RagConfigVersion[]>([])
const audit = ref<any[]>([])
const note = ref('')
const loading = ref(false)
const saving = ref(false)
const msg = ref('')
const error = ref('')
const embedding = ref<RetrievalConfigOut | null>(null)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const data = await getRagConfig()
    form.value = data.config as unknown as Cfg
    defaults.value = data.defaults as unknown as Cfg
    versions.value = await listRagConfigVersions()
    audit.value = await listRagAudit(30)
    embedding.value = await getEmbeddingConfig()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}

async function save() {
  if (!form.value) return
  saving.value = true
  msg.value = ''
  error.value = ''
  try {
    await updateRagConfig(form.value as unknown as Record<string, unknown>, note.value)
    msg.value = '配置已保存并立即生效'
    note.value = ''
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '保存失败'
  } finally {
    saving.value = false
  }
}

async function rollback(v: number) {
  if (!confirm(`回滚到配置版本 v${v}？`)) return
  try {
    await rollbackRagConfig(v)
    msg.value = `已回滚到 v${v}`
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '回滚失败'
  }
}

onMounted(load)
</script>

<template>
  <div>
    <PageHead title="RAG 参数配置" eyebrow="RAG SETTINGS" sub="版本化参数、Embedding 状态与操作审计">
      <template #actions>
        <button class="btn ghost" :disabled="loading" @click="load">{{ loading ? '刷新中…' : '刷新' }}</button>
        <button class="btn" :disabled="saving || !form" @click="save">{{ saving ? '保存中…' : '保存配置' }}</button>
      </template>
    </PageHead>

    <RagTabs />

    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="msg" class="ok">{{ msg }}</p>

    <section class="two-col">
      <div class="panel">
        <div class="panel-head"><h3>索引参数</h3><span class="muted">修改后对新入库文档生效</span></div>
        <div v-if="form" class="form-grid">
          <label>chunk_size <input v-model.number="form.chunk_size" type="number" min="128" max="2048" /></label>
          <label>chunk_overlap <input v-model.number="form.chunk_overlap" type="number" min="0" max="1024" /></label>
          <label>parent_chunk_size <input v-model.number="form.parent_chunk_size" type="number" min="0" max="8192" /></label>
        </div>
      </div>

      <div class="panel">
        <div class="panel-head"><h3>检索参数</h3><span class="muted">保存后下一次检索立即生效</span></div>
        <div v-if="form" class="form-grid">
          <label>top_k <input v-model.number="form.top_k" type="number" min="1" max="50" /></label>
          <label>rerank_oversample <input v-model.number="form.rerank_oversample" type="number" min="1" max="20" /></label>
          <label>min_similarity <input v-model.number="form.min_similarity" type="number" min="0" max="1" step="0.01" /></label>
          <label>per_doc_cap <input v-model.number="form.per_doc_cap" type="number" min="1" max="20" /></label>
          <label>rerank_timeout_s <input v-model.number="form.rerank_timeout_s" type="number" min="0.2" max="10" step="0.1" /></label>
          <label>rerank_circuit_threshold <input v-model.number="form.rerank_circuit_threshold" type="number" min="1" max="20" /></label>
          <label>rerank_circuit_cooldown_s <input v-model.number="form.rerank_circuit_cooldown_s" type="number" min="10" max="3600" /></label>
          <label>hybrid_candidates <input v-model.number="form.hybrid_candidates" type="number" min="5" max="200" /></label>
        </div>
      </div>
    </section>

    <section v-if="form" class="panel">
      <div class="panel-head"><h3>能力开关</h3></div>
      <div class="checks">
        <label><input v-model="form.keyword_fallback_enabled" type="checkbox" /> 关键词兜底</label>
        <label><input v-model="form.hybrid_enabled" type="checkbox" /> 混合检索（向量 + 关键词 RRF）</label>
        <label><input v-model="form.query_rewrite_enabled" type="checkbox" /> 轻量 Query 改写</label>
      </div>
    </section>

    <section v-if="form" class="two-col">
      <div class="panel">
        <div class="panel-head"><h3>观测与保留</h3></div>
        <div class="form-grid">
          <label>成功 trace 采样率 <input v-model.number="form.trace_success_sample_rate" type="number" min="0" max="1" step="0.05" /></label>
          <p v-if="form && form.trace_success_sample_rate < 1" class="warn">采样率小于 1 时，命中率/零结果率仅作趋势参考。</p>
          <label>成功 trace 保留天数 <input v-model.number="form.trace_retention_days" type="number" min="1" max="365" /></label>
          <label>错误/零结果保留天数 <input v-model.number="form.trace_error_retention_days" type="number" min="1" max="365" /></label>
        </div>
      </div>
      <div class="panel">
        <div class="panel-head"><h3>Embedding 状态</h3><RouterLink class="link" to="/settings">去设置</RouterLink></div>
        <div v-if="embedding" class="embed">
          <div><span>provider</span><b>{{ embedding.provider }}</b></div>
          <div><span>model</span><b>{{ embedding.model || '-' }}</b></div>
          <div><span>base_url</span><b class="mono">{{ embedding.base_url || '-' }}</b></div>
          <div><span>key</span><b>{{ embedding.api_key_masked || '-' }}</b></div>
        </div>
        <div v-else class="muted">未配置系统级 Embedding，检索将回退到全局 env 或不可用。</div>
      </div>
    </section>

    <section class="panel">
      <div class="panel-head"><h3>保存配置</h3><span class="muted">可以填写本次变更说明</span></div>
      <div class="save-row">
        <input v-model="note" placeholder="变更说明（可选，如：评测后收紧门控）" />
        <button class="btn" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存' }}</button>
      </div>
    </section>

    <section class="two-col">
      <div class="panel">
        <div class="panel-head"><h3>配置版本</h3></div>
        <table class="table">
          <thead><tr><th>版本</th><th>说明</th><th>时间</th><th></th></tr></thead>
          <tbody>
            <tr v-for="v in versions" :key="v.version">
              <td class="mono">v{{ v.version }}</td>
              <td>{{ v.note || '-' }}</td>
              <td class="mono">{{ v.created_at?.slice(0, 16).replace('T', ' ') }}</td>
              <td><button class="mini" @click="rollback(v.version)">回滚</button></td>
            </tr>
            <tr v-if="!versions.length"><td colspan="4" class="muted">暂无版本记录</td></tr>
          </tbody>
        </table>
      </div>
      <div class="panel">
        <div class="panel-head"><h3>操作审计</h3></div>
        <table class="table">
          <thead><tr><th>动作</th><th>目标</th><th>时间</th></tr></thead>
          <tbody>
            <tr v-for="a in audit" :key="a.id">
              <td>{{ a.action }}</td>
              <td class="mono ellipsis">{{ a.target }}</td>
              <td class="mono">{{ a.created_at?.slice(0, 16).replace('T', ' ') }}</td>
            </tr>
            <tr v-if="!audit.length"><td colspan="3" class="muted">暂无审计</td></tr>
          </tbody>
        </table>
      </div>
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
.muted { color: var(--ink-3); font-size: 12px; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.form-grid label { display: flex; flex-direction: column; gap: 4px; font-size: 11.5px; color: var(--ink-3); }
.form-grid input { padding: 7px 9px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface); color: var(--ink); font-size: 12.5px; }
.checks { display: flex; gap: 18px; flex-wrap: wrap; font-size: 12.5px; }
.checks label { display: flex; gap: 6px; align-items: center; }
.embed { display: flex; flex-direction: column; gap: 8px; }
.embed div { display: flex; justify-content: space-between; gap: 12px; font-size: 12.5px; }
.embed span { color: var(--ink-3); }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11.5px; word-break: break-all; }
.save-row { display: flex; gap: 10px; }
.save-row input { flex: 1; padding: 9px 10px; border: 1px solid var(--line); border-radius: 9px; background: var(--surface); color: var(--ink); }
.table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.table th, .table td { text-align: left; padding: 8px 6px; border-bottom: 1px solid var(--line); }
.table th { color: var(--ink-3); font-weight: 600; }
.mini { padding: 4px 9px; border: 1px solid var(--line); background: var(--surface); border-radius: 7px; cursor: pointer; font-size: 11.5px; }
.ellipsis { max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; display: inline-block; }
.link { color: var(--brand-strong); font-size: 12px; text-decoration: none; }
.error { color: #b91c1c; background: #fef2f2; padding: 10px 12px; border-radius: 10px; margin-bottom: 12px; }
.ok { color: #047857; background: var(--success-soft); padding: 10px 12px; border-radius: 10px; margin-bottom: 12px; }
@media (max-width: 1100px) { .two-col { grid-template-columns: 1fr; } .form-grid { grid-template-columns: 1fr; } }
</style>
