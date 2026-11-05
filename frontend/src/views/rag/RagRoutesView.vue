<script setup lang="ts">
import { onMounted, ref } from 'vue'

import PageHead from '@/components/PageHead.vue'
import RagTabs from '@/components/RagTabs.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import { listRagRoutes, testRagRoute, updateRagRoute, type RagTrace } from '@/api/ragAdmin'

const routes = ref<any[]>([])
const loading = ref(false)
const error = ref('')
const testForm = ref({
  query: '',
  route_key: 'admin_test',
  owner_id: '',
  collected_ids: '',
  top_k: 5,
  rerank: true,
  min_similarity: '',
})
const testResult = ref<any>(null)
const pending = ref<{ title: string; message: string; run: () => void | Promise<void> } | null>(null)

function ask(title: string, message: string, run: () => void | Promise<void>) {
  pending.value = { title, message, run }
}
async function confirmPending() {
  const p = pending.value
  pending.value = null
  if (p) await p.run()
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    routes.value = (await listRagRoutes()).items
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}

async function saveRoute(r: any) {
  ask('保存路由配置', `确认保存「${r.name}」的检索参数？保存后新请求将立即使用。`, async () => {
    try {
      await updateRagRoute(r.key, {
        top_k: Number(r.effective.top_k),
        min_similarity: Number(r.effective.min_similarity),
        per_doc_cap: Number(r.effective.per_doc_cap),
        rerank_oversample: Number(r.effective.rerank_oversample || 5),
      })
      error.value = ''
      await load()
    } catch (e) {
      error.value = e instanceof Error ? e.message : '保存失败'
    }
  })
}

async function runTest() {
  if (!testForm.value.query.trim()) return
  error.value = ''
  try {
    testResult.value = await testRagRoute({
      query: testForm.value.query,
      route_key: testForm.value.route_key,
      owner_id: testForm.value.owner_id || undefined,
      collected_ids: testForm.value.collected_ids
        ? testForm.value.collected_ids.split(/[,，\n]/).map((x) => x.trim()).filter(Boolean)
        : [],
      top_k: testForm.value.top_k,
      rerank: testForm.value.rerank,
      min_similarity: testForm.value.min_similarity === '' ? undefined : Number(testForm.value.min_similarity),
    })
  } catch (e) {
    error.value = e instanceof Error ? e.message : '测试失败'
  }
}

function stageText(t: RagTrace | any) {
  const s = t?.stage_timings || {}
  return Object.entries(s).map(([k, v]) => `${k} ${Math.round(Number(v))}ms`).join(' · ')
}

onMounted(load)
</script>

<template>
  <div>
    <PageHead title="检索路由" eyebrow="RAG ROUTING" sub="业务域路由矩阵与逐阶段检索测试">
      <template #actions>
        <button class="btn ghost" :disabled="loading" @click="load">{{ loading ? '刷新中…' : '刷新' }}</button>
        <RouterLink class="btn ghost" to="/rag/settings">参数配置</RouterLink>
      </template>
    </PageHead>

    <RagTabs />

    <p v-if="error" class="error">{{ error }}</p>

    <section class="panel">
      <div class="panel-head"><h3>路由矩阵</h3><span class="muted">当前为代码定义 + 参数覆盖，避免任意规则破坏租户隔离</span></div>
      <table class="table">
        <thead><tr><th>路由</th><th>owner 范围</th><th>文档范围</th><th>top_k</th><th>门控</th><th>单文档上限</th><th>说明</th><th></th></tr></thead>
        <tbody>
          <tr v-for="r in routes" :key="r.key">
            <td><strong>{{ r.name }}</strong><div class="muted mono">{{ r.key }}</div></td>
            <td>{{ r.owner_scope }}</td>
            <td>{{ r.doc_scope }}</td>
            <td><input v-model.number="r.effective.top_k" class="cell-input" type="number" min="1" max="50" /></td>
            <td><input v-model.number="r.effective.min_similarity" class="cell-input" type="number" min="0" max="1" step="0.01" /></td>
            <td><input v-model.number="r.effective.per_doc_cap" class="cell-input" type="number" min="1" max="20" /></td>
            <td class="muted">{{ r.description }}</td>
            <td><button class="mini" @click="saveRoute(r)">保存</button></td>
          </tr>
        </tbody>
      </table>
    </section>

    <section class="panel">
      <div class="panel-head"><h3>测试台</h3><span class="muted">只读测试，不写入生产对话</span></div>
      <div class="test-form">
        <input v-model="testForm.query" placeholder="输入测试 query" @keyup.enter="runTest" />
        <select v-model="testForm.route_key">
          <option value="admin_test">admin_test</option>
          <option value="agent_teacher">agent_teacher</option>
          <option value="parent_service">parent_service</option>
          <option value="eval">eval</option>
        </select>
        <input v-model="testForm.owner_id" placeholder="owner_id（可选，默认当前管理员）" />
        <input v-model="testForm.collected_ids" placeholder="collected doc ids，逗号分隔（可选）" />
        <input v-model.number="testForm.top_k" type="number" min="1" max="50" />
        <input v-model="testForm.min_similarity" placeholder="min_similarity（可选）" />
        <label class="check"><input v-model="testForm.rerank" type="checkbox" /> rerank</label>
        <button class="btn" :disabled="!testForm.query.trim()" @click="runTest">运行测试</button>
      </div>
    </section>

    <section v-if="testResult" class="panel">
      <div class="panel-head"><h3>测试结果</h3><span class="muted mono">{{ testResult.trace_id }}</span></div>
      <div class="meta">
        <span>{{ testResult.summary }}</span>
        <span>{{ stageText(testResult.diag) }}</span>
      </div>
      <table class="table">
        <thead><tr><th>#</th><th>标题</th><th>相似度</th><th>rerank</th><th>RRF</th><th>预览</th></tr></thead>
        <tbody>
          <tr v-for="(h, i) in testResult.hits || []" :key="i">
            <td>{{ i + 1 }}</td>
            <td>{{ h.title }}</td>
            <td>{{ h.similarity ?? '-' }}</td>
            <td>{{ h.rerank_score ?? '-' }}</td>
            <td>{{ h.rrf_score ?? '-' }}</td>
            <td class="muted preview">{{ h.text }}</td>
          </tr>
          <tr v-if="!testResult.hits?.length"><td colspan="6" class="muted">无命中</td></tr>
        </tbody>
      </table>
    </section>
  </div>
  <ConfirmDialog
    :visible="!!pending"
    :title="pending?.title || ''"
    :message="pending?.message || ''"
    confirm-text="保存"
    @confirm="confirmPending"
    @cancel="pending = null"
  />
</template>

<style scoped>
.btn { padding: 8px 14px; border-radius: 9px; border: 1px solid var(--brand); background: var(--brand); color: #fff; font-weight: 600; cursor: pointer; font-size: 13px; text-decoration: none; }
.btn.ghost { background: var(--surface); color: var(--brand-strong); border-color: var(--line); }
.panel { background: var(--surface); border: 1px solid var(--line); border-radius: 14px; padding: 16px; margin-bottom: 16px; box-shadow: var(--shadow-sm); }
.panel-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.panel-head h3 { font-size: 14px; font-weight: 800; }
.table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.table th, .table td { text-align: left; padding: 8px 6px; border-bottom: 1px solid var(--line); vertical-align: top; }
.table th { color: var(--ink-3); font-weight: 600; }
.muted { color: var(--ink-3); font-size: 12px; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11.5px; }
.test-form { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.test-form input, .test-form select { padding: 8px 10px; border: 1px solid var(--line); border-radius: 9px; background: var(--surface); color: var(--ink); font-size: 12.5px; }
.test-form input:first-child { flex: 1; min-width: 220px; }
.check { display: flex; gap: 6px; align-items: center; font-size: 12.5px; }
.meta { display: flex; gap: 14px; flex-wrap: wrap; font-size: 12.5px; color: var(--ink-2); margin-bottom: 10px; }
.preview { max-width: 480px; }
.cell-input { width: 78px; padding: 5px 7px; border: 1px solid var(--line); border-radius: 7px; background: var(--surface); color: var(--ink); font-size: 12px; }
.mini { padding: 4px 9px; border: 1px solid var(--line); background: var(--surface); border-radius: 7px; cursor: pointer; font-size: 11.5px; }
.error { color: #b91c1c; background: #fef2f2; padding: 10px 12px; border-radius: 10px; margin-bottom: 12px; }
</style>
