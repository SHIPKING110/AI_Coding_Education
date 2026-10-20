<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import {
  createLLMConfig,
  deleteLLMConfig,
  getModuleMapping,
  listLLMConfigs,
  setModuleMapping,
  testLLMConfig,
  updateLLMConfig,
  LLM_MODULES,
  type LLMConfigIn,
  type LLMConfigOut,
} from '@/api/llm'
import {
  deleteEmbeddingConfig,
  deleteRerankConfig,
  getEmbeddingConfig,
  getRerankConfig,
  saveEmbeddingConfig,
  saveRerankConfig,
  testEmbeddingConfig,
  testRerankConfig,
  type RetrievalConfigIn,
  type RetrievalConfigOut,
} from '@/api/retrievalConfig'
import { toastApiError, useToastStore } from '@/stores/toast'
import { useAuthStore } from '@/stores/auth'

const toast = useToastStore()
const auth = useAuthStore()
const isAdmin = computed(() => auth.user?.role === 'admin')
const items = ref<LLMConfigOut[]>([])
const loading = ref(false)

// 新增/编辑表单
const showForm = ref(false)
const editing = ref<LLMConfigOut | null>(null)
const form = ref<LLMConfigIn & { showKey?: boolean }>({
  name: '',
  base_url: '',
  api_key: '',
  model: '',
  make_default: false,
})
const saving = ref(false)

// 检查连通性
const testingId = ref('')
const testResult = ref<{ id: string; ok: boolean; text: string } | null>(null)

// 模块映射
const mapping = ref<Record<string, string | null>>({})
const savingMap = ref(false)

async function load() {
  loading.value = true
  try {
    const [cfgs, mp] = await Promise.all([listLLMConfigs(), getModuleMapping().catch(() => ({ mapping: {} }))])
    items.value = cfgs.items
    mapping.value = { ...(mp.mapping || {}) }
  } catch (e) {
    toastApiError(e, '加载模型配置失败')
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editing.value = null
  form.value = { name: '', base_url: '', api_key: '', model: '', make_default: items.value.length === 0 }
  showForm.value = true
}

function openEdit(c: LLMConfigOut) {
  editing.value = c
  form.value = { name: c.name, base_url: c.base_url, api_key: '', model: c.model, make_default: c.is_default }
  showForm.value = true
}

async function save() {
  if (!form.value.name.trim() || !form.value.base_url.trim() || !form.value.model.trim()) {
    toast.error('名称、接口地址、模型名不能为空')
    return
  }
  if (!editing.value && !form.value.api_key.trim()) {
    toast.error('API Key 不能为空')
    return
  }
  saving.value = true
  try {
    if (editing.value) {
      const payload: Record<string, unknown> = {
        name: form.value.name,
        base_url: form.value.base_url,
        model: form.value.model,
        make_default: form.value.make_default,
      }
      if (form.value.api_key.trim()) payload.api_key = form.value.api_key
      await updateLLMConfig(editing.value.id, payload)
      toast.success('已更新模型配置')
    } else {
      await createLLMConfig({ ...form.value })
      toast.success('已添加模型配置')
    }
    showForm.value = false
    await load()
  } catch (e) {
    toastApiError(e, '保存失败')
  } finally {
    saving.value = false
  }
}

async function remove(c: LLMConfigOut) {
  if (!confirm(`删除模型配置「${c.name}」？引用它的模块将回退到默认配置。`)) return
  try {
    await deleteLLMConfig(c.id)
    toast.success('已删除')
    await load()
  } catch (e) {
    toastApiError(e, '删除失败')
  }
}

async function setDefault(c: LLMConfigOut) {
  try {
    await updateLLMConfig(c.id, { make_default: true })
    toast.success(`已将「${c.name}」设为默认`)
    await load()
  } catch (e) {
    toastApiError(e, '设置默认失败')
  }
}

async function check(c: LLMConfigOut) {
  testingId.value = c.id
  testResult.value = null
  try {
    const r = await testLLMConfig(c.id)
    testResult.value = r.ok
      ? { id: c.id, ok: true, text: `连通正常（${r.latency_ms}ms）${r.reply ? ` · 模型回复：${r.reply}` : ''}` }
      : { id: c.id, ok: false, text: r.error || '连通失败' }
    if (r.ok) toast.success(`「${c.name}」连通正常`)
    else toast.error(`「${c.name}」${r.error || '连通失败'}`)
  } catch (e) {
    testResult.value = { id: c.id, ok: false, text: '请求失败，请稍后重试' }
    toastApiError(e, '检查失败')
  } finally {
    testingId.value = ''
  }
}

async function saveMapping() {
  savingMap.value = true
  try {
    const r = await setModuleMapping({ ...mapping.value })
    mapping.value = { ...(r.mapping || {}) }
    toast.success('模块模型映射已保存')
  } catch (e) {
    toastApiError(e, '保存映射失败')
  } finally {
    savingMap.value = false
  }
}

function configName(id: string | null): string {
  if (!id) return '默认配置'
  return items.value.find((c) => c.id === id)?.name || '（已删除，回退默认）'
}

/* —— 检索模型：Embedding（系统级，管理员） + Rerank（教师级，可选） —— */
const emb = ref<RetrievalConfigOut | null>(null)
const rrk = ref<RetrievalConfigOut | null>(null)
const embForm = ref<RetrievalConfigIn>({ provider: 'remote', base_url: '', api_key: '', model: '', model_path: '', enabled: true })
const rrkForm = ref<RetrievalConfigIn>({ provider: 'remote', base_url: '', api_key: '', model: '', model_path: '', enabled: true })
const showEmbForm = ref(false)
const showRrkForm = ref(false)
const savingEmb = ref(false)
const savingRrk = ref(false)
const testingEmb = ref(false)
const testingRrk = ref(false)
const embTestMsg = ref('')
const rrkTestMsg = ref('')

async function loadRetrieval() {
  try {
    if (isAdmin.value) {
      emb.value = await getEmbeddingConfig()
      embForm.value = emb.value
        ? {
            provider: emb.value.provider,
            base_url: emb.value.base_url,
            api_key: '',
            model: emb.value.model,
            model_path: emb.value.model_path || '',
            enabled: emb.value.enabled,
          }
        : { provider: 'remote', base_url: '', api_key: '', model: '', model_path: '', enabled: true }
    }
    rrk.value = await getRerankConfig()
    rrkForm.value = rrk.value
      ? {
          provider: rrk.value.provider,
          base_url: rrk.value.base_url,
          api_key: '',
          model: rrk.value.model,
          model_path: rrk.value.model_path || '',
          enabled: rrk.value.enabled,
        }
      : { provider: 'remote', base_url: '', api_key: '', model: '', model_path: '', enabled: true }
  } catch {
    // 检索配置为可选增强，读取失败不阻塞模型配置页
  }
}

async function saveEmb() {
  if (embForm.value.provider === 'remote' && (!embForm.value.base_url.trim() || !embForm.value.model.trim())) {
    toast.error('接口地址与模型名不能为空')
    return
  }
  if (embForm.value.provider === 'remote' && !emb.value && !embForm.value.api_key.trim()) {
    toast.error('API Key 不能为空')
    return
  }
  savingEmb.value = true
  try {
    emb.value = await saveEmbeddingConfig(embForm.value)
    toast.success('已保存系统级 Embedding 配置')
    showEmbForm.value = false
    await loadRetrieval()
  } catch (e) {
    toastApiError(e, '保存失败')
  } finally {
    savingEmb.value = false
  }
}

async function saveRrk() {
  if (rrkForm.value.provider === 'remote' && (!rrkForm.value.base_url.trim() || !rrkForm.value.model.trim())) {
    toast.error('接口地址与模型名不能为空')
    return
  }
  if (rrkForm.value.provider === 'remote' && !rrk.value && !rrkForm.value.api_key.trim()) {
    toast.error('API Key 不能为空')
    return
  }
  savingRrk.value = true
  try {
    rrk.value = await saveRerankConfig(rrkForm.value)
    toast.success('已保存 Rerank 配置')
    showRrkForm.value = false
    await loadRetrieval()
  } catch (e) {
    toastApiError(e, '保存失败')
  } finally {
    savingRrk.value = false
  }
}

async function removeEmb() {
  if (!confirm('删除系统级 Embedding 配置？删除后知识库检索将回退到全局 env 或不可用。')) return
  try {
    await deleteEmbeddingConfig()
    emb.value = null
    toast.success('已删除')
    await loadRetrieval()
  } catch (e) {
    toastApiError(e, '删除失败')
  }
}

async function removeRrk() {
  if (!confirm('删除 Rerank 配置？删除后检索将退化为单层向量召回。')) return
  try {
    await deleteRerankConfig()
    rrk.value = null
    toast.success('已删除')
    await loadRetrieval()
  } catch (e) {
    toastApiError(e, '删除失败')
  }
}

async function checkEmb() {
  testingEmb.value = true
  embTestMsg.value = ''
  try {
    const r = await testEmbeddingConfig()
    embTestMsg.value = r.ok ? `连通正常（${r.latency_ms}ms · ${r.dim} 维）` : `✗ ${r.error || '连通失败'}`
  } catch (e) {
    embTestMsg.value = '✗ 请求失败，请稍后重试'
    toastApiError(e, '检查失败')
  } finally {
    testingEmb.value = false
  }
}

async function checkRrk() {
  testingRrk.value = true
  rrkTestMsg.value = ''
  try {
    const r = await testRerankConfig()
    rrkTestMsg.value = r.ok ? `连通正常（${r.latency_ms}ms）` : `✗ ${r.error || '连通失败'}`
  } catch (e) {
    rrkTestMsg.value = '✗ 请求失败，请稍后重试'
    toastApiError(e, '检查失败')
  } finally {
    testingRrk.value = false
  }
}

onMounted(() => {
  load()
  void loadRetrieval()
})
</script>

<template>
  <div class="llm-tab">
    <section class="card">
      <div class="card-head">
        <div>
          <h2>我的模型配置</h2>
          <p class="muted">每人可配多个（接口地址 + API Key + 对话模型名）。Key 落库加密、只显示掩码；下方按模块选用。知识库向量化（Embedding）统一由下面「检索 · Embedding」板块配置，此处不再重复填写。</p>
        </div>
        <button class="btn primary sm" @click="openCreate">＋ 添加配置</button>
      </div>
      <div v-if="loading" class="muted-sm">加载中…</div>
      <div v-else-if="items.length === 0" class="empty-tip">还没有模型配置，先添加一个（如 DeepSeek：地址 https://api.deepseek.com，模型 deepseek-chat）</div>
      <div v-else class="cfg-list">
        <div v-for="c in items" :key="c.id" class="cfg-row" :class="{ def: c.is_default }">
          <div class="cfg-main">
            <div class="cfg-head">
              <strong>{{ c.name }}</strong>
              <span v-if="c.is_default" class="def-tag">默认</span>
            </div>
            <div class="cfg-meta">{{ c.base_url }} · 模型 {{ c.model }}</div>
            <div v-if="testResult && testResult.id === c.id" class="test-line" :class="{ ok: testResult.ok, bad: !testResult.ok }">
              {{ testResult.ok ? '✓' : '✗' }} {{ testResult.text }}
            </div>
          </div>
          <div class="cfg-actions">
            <button class="link-btn" :disabled="testingId === c.id" @click="check(c)">{{ testingId === c.id ? '检查中…' : '检查' }}</button>
            <button v-if="!c.is_default" class="link-btn" @click="setDefault(c)">设为默认</button>
            <button class="link-btn" @click="openEdit(c)">编辑</button>
            <button class="link-btn danger" @click="remove(c)">删除</button>
          </div>
        </div>
      </div>
    </section>

    <section class="card">
      <h2>各模块选用模型</h2>
      <p class="muted">不选 = 用上面的默认配置。Agent 工作台还可在对话时临时切换。「教学服务 · 家长客服」控制家长端问答用的对话模型，其 RAG 检索共用系统级 Embedding（下方配置）与归属教师的 Rerank；家长只能看到后台勾选为「家长可见」的文档。</p>
      <div class="map-grid">
        <label v-for="m in LLM_MODULES" :key="m.key" class="map-row">
          <span>{{ m.label }}</span>
          <select v-model="mapping[m.key]" class="filter-select">
            <option :value="null">默认配置</option>
            <option v-for="c in items" :key="c.id" :value="c.id">{{ c.name }}（{{ c.model }}）</option>
          </select>
          <span class="muted-sm">当前：{{ configName(mapping[m.key] ?? null) }}</span>
        </label>
      </div>
      <button class="btn primary sm" :disabled="savingMap" @click="saveMapping">{{ savingMap ? '保存中…' : '保存映射' }}</button>
    </section>

    <!-- 检索 · Embedding（系统级，管理员） -->
    <section v-if="isAdmin" class="card">
      <div class="card-head">
        <div>
          <h2>检索 · Embedding（系统级）</h2>
          <p class="muted">
            知识库向量化的模型，<strong>全校共用一套</strong>：单一向量集合不能混存不同 embedding 的向量（会跨教师串味/维度冲突）。
            更换模型会落到新的向量集合（旧数据不丢，可离线清理/重建）。
          </p>
        </div>
        <div class="cfg-actions">
          <button v-if="emb" class="link-btn" :disabled="testingEmb" @click="checkEmb">{{ testingEmb ? '检查中…' : '检查' }}</button>
          <button v-if="emb" class="link-btn" @click="showEmbForm = true">编辑</button>
          <button v-else class="btn primary sm" @click="showEmbForm = true">配置 Embedding</button>
          <button v-if="emb" class="link-btn danger" @click="removeEmb">删除</button>
        </div>
      </div>
      <div v-if="emb" class="cfg-row def">
        <div class="cfg-main">
          <div class="cfg-head"><strong>{{ emb.model || '（未填模型）' }}</strong></div>
          <div class="cfg-meta">{{ emb.provider === 'local' ? `本地模型 · ${emb.model_path || '未设路径'}` : emb.base_url }} · {{ emb.enabled ? '启用' : '停用' }}</div>
          <div v-if="embTestMsg" class="test-line">{{ embTestMsg }}</div>
        </div>
      </div>
      <div v-else class="empty-tip">未配置系统级 Embedding，知识库检索将回退到全局 env 或本地模型（仅开发机可用）。</div>
    </section>

    <!-- 检索 · Rerank（教师级，可选） -->
    <section class="card">
      <div class="card-head">
        <div>
          <h2>检索 · Rerank（可选）</h2>
          <p class="muted">
            两阶段检索的第二阶段：对向量召回的候选重排以提升精准率。<strong>未配置即退化为单层向量召回</strong>，
            调用失败/超时也会静默降级，不影响正常对话。
          </p>
        </div>
        <div class="cfg-actions">
          <button v-if="rrk" class="link-btn" :disabled="testingRrk" @click="checkRrk">{{ testingRrk ? '检查中…' : '检查' }}</button>
          <button v-if="rrk" class="link-btn" @click="showRrkForm = true">编辑</button>
          <button v-else class="btn primary sm" @click="showRrkForm = true">配置 Rerank</button>
          <button v-if="rrk" class="link-btn danger" @click="removeRrk">删除</button>
        </div>
      </div>
      <div v-if="rrk" class="cfg-row def">
        <div class="cfg-main">
          <div class="cfg-head"><strong>{{ rrk.model || '（未填模型）' }}</strong></div>
          <div class="cfg-meta">{{ rrk.provider === 'local' ? `本地模型 · ${rrk.model_path || '未设路径'}` : rrk.base_url }} · {{ rrk.enabled ? '启用' : '停用' }}</div>
          <div v-if="rrkTestMsg" class="test-line">{{ rrkTestMsg }}</div>
        </div>
      </div>
      <div v-else class="empty-tip">未配置 Rerank（可选项）：当前为单层向量检索，完全正常工作。</div>
    </section>

    <div v-if="showForm" class="overlay" @click.self="showForm = false">
      <div class="modal">
        <h2>{{ editing ? '编辑模型配置' : '添加模型配置' }}</h2>
        <div class="form-grid">
          <label>配置名称<input v-model="form.name" placeholder="如：deepseek-主" /></label>
          <label>接口地址（OpenAI 兼容）<input v-model="form.base_url" placeholder="https://api.deepseek.com" /></label>
          <label>API Key<input v-model="form.api_key" :type="form.showKey ? 'text' : 'password'" :placeholder="editing ? '留空则不修改' : 'sk-…'" /></label>
          <label>模型名称<input v-model="form.model" placeholder="如：deepseek-chat" /></label>
          <label class="check"><input v-model="form.make_default" type="checkbox" /> 设为默认配置</label>
          <label class="check"><input v-model="form.showKey" type="checkbox" /> 显示 Key 明文</label>
        </div>
        <div class="modal-actions">
          <button class="btn ghost" @click="showForm = false">取消</button>
          <button class="btn primary" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存' }}</button>
        </div>
      </div>
    </div>

    <!-- Embedding 编辑（系统级） -->
    <div v-if="showEmbForm" class="overlay" @click.self="showEmbForm = false">
      <div class="modal">
        <h2>系统级 Embedding 配置</h2>
        <div class="form-grid">
          <label class="check"><input v-model="embForm.provider" type="radio" value="remote" /> 云端 API（OpenAI 兼容）</label>
          <label class="check"><input v-model="embForm.provider" type="radio" value="local" /> 本地模型（预留）</label>
          <template v-if="embForm.provider === 'remote'">
            <label class="span2">接口地址<input v-model="embForm.base_url" placeholder="https://api.siliconflow.cn" /></label>
            <label class="span2">API Key<input v-model="embForm.api_key" :type="embForm.api_key ? 'text' : 'password'" :placeholder="emb ? '留空则不修改' : 'sk-…'" /></label>
            <label class="span2">Embedding 模型名<input v-model="embForm.model" placeholder="如 BAAI/bge-m3" /></label>
          </template>
          <template v-else>
            <label class="span2">本地模型路径<input v-model="embForm.model_path" placeholder="如 /srv/app/models/bge-m3" /></label>
            <label class="span2">模型名（标识）<input v-model="embForm.model" placeholder="如 bge-m3-local" /></label>
          </template>
          <label class="check"><input v-model="embForm.enabled" type="checkbox" /> 启用</label>
        </div>
        <div class="modal-actions">
          <button class="btn ghost" @click="showEmbForm = false">取消</button>
          <button class="btn primary" :disabled="savingEmb" @click="saveEmb">{{ savingEmb ? '保存中…' : '保存' }}</button>
        </div>
      </div>
    </div>

    <!-- Rerank 编辑（教师级，可选） -->
    <div v-if="showRrkForm" class="overlay" @click.self="showRrkForm = false">
      <div class="modal">
        <h2>Rerank 配置（可选）</h2>
        <div class="form-grid">
          <label class="check"><input v-model="rrkForm.provider" type="radio" value="remote" /> 云端 API（/rerank 端点）</label>
          <label class="check"><input v-model="rrkForm.provider" type="radio" value="local" /> 本地模型（预留）</label>
          <template v-if="rrkForm.provider === 'remote'">
            <label class="span2">接口地址<input v-model="rrkForm.base_url" placeholder="https://api.siliconflow.cn" /></label>
            <label class="span2">API Key<input v-model="rrkForm.api_key" :type="rrkForm.api_key ? 'text' : 'password'" :placeholder="rrk ? '留空则不修改' : 'sk-…'" /></label>
            <label class="span2">Rerank 模型名<input v-model="rrkForm.model" placeholder="如 BAAI/bge-reranker-v2-m3" /></label>
          </template>
          <template v-else>
            <label class="span2">本地模型路径<input v-model="rrkForm.model_path" placeholder="如 /srv/app/models/bge-reranker-v2-m3" /></label>
            <label class="span2">模型名（标识）<input v-model="rrkForm.model" placeholder="如 bge-reranker-local" /></label>
          </template>
          <label class="check"><input v-model="rrkForm.enabled" type="checkbox" /> 启用（停用即退化为单层向量检索）</label>
        </div>
        <div class="modal-actions">
          <button class="btn ghost" @click="showRrkForm = false">取消</button>
          <button class="btn primary" :disabled="savingRrk" @click="saveRrk">{{ savingRrk ? '保存中…' : '保存' }}</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.llm-tab { display: flex; flex-direction: column; gap: 16px; }
.card { background: var(--surface); border: 1px solid var(--line); border-radius: 16px; padding: 18px 20px; }
.card-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
h2 { font-size: 15px; font-weight: 700; margin-bottom: 4px; }
.muted { font-size: 12.5px; color: var(--ink-3); margin-bottom: 12px; }
.muted-sm { font-size: 12px; color: var(--ink-3); }
.empty-tip { text-align: center; color: var(--ink-3); padding: 16px 0; font-size: 13px; }
.cfg-list { display: flex; flex-direction: column; gap: 10px; }
.cfg-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; border: 1px solid var(--line); border-radius: 12px; padding: 12px 14px; }
.cfg-row.def { border-color: var(--brand); background: var(--brand-soft); }
.cfg-head { display: flex; align-items: center; gap: 8px; font-size: 14px; }
.def-tag { font-size: 11px; font-weight: 700; padding: 1px 8px; border-radius: 999px; background: #e2f5ea; color: #0e9f6e; }
.cfg-meta { font-size: 12px; color: var(--ink-3); margin-top: 4px; word-break: break-all; }
.test-line { font-size: 12.5px; margin-top: 6px; }
.test-line.ok { color: #0e9f6e; }
.test-line.bad { color: #b91c1c; }
.cfg-actions { display: flex; gap: 10px; flex-shrink: 0; }
.link-btn { border: none; background: none; color: var(--brand-strong); font-size: 12.5px; cursor: pointer; white-space: nowrap; }
.link-btn:disabled { opacity: 0.5; }
.link-btn.danger { color: #b91c1c; }
.map-grid { display: flex; flex-direction: column; gap: 10px; margin-bottom: 14px; }
.map-row { display: grid; grid-template-columns: 110px 1fr auto; gap: 10px; align-items: center; font-size: 13.5px; }
.filter-select { padding: 8px 12px; border: 1px solid var(--line); border-radius: 10px; background: var(--surface); font-size: 13px; color: var(--ink-2); }
.btn { padding: 8px 18px; border-radius: 10px; font-size: 13px; cursor: pointer; border: 1px solid var(--line); }
.btn.primary { background: linear-gradient(135deg, #6366f1, #06b6d4); color: #fff; border-color: transparent; font-weight: 600; }
.btn.ghost { background: var(--surface); color: var(--ink-2); }
.btn.sm { padding: 7px 14px; font-size: 12.5px; }
.overlay { position: fixed; inset: 0; background: rgba(15, 23, 42, 0.45); display: flex; align-items: center; justify-content: center; z-index: 60; padding: 16px; }
.modal { background: var(--surface); border-radius: 16px; padding: 22px 24px; width: 560px; max-width: 100%; max-height: 90vh; overflow: auto; }
.modal h2 { font-size: 16px; margin-bottom: 12px; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin: 14px 0; }
.form-grid label { display: flex; flex-direction: column; gap: 6px; font-size: 12.5px; color: var(--ink-2); }
.form-grid label.span2 { grid-column: span 2; }
.form-grid label.check { flex-direction: row; align-items: center; gap: 8px; }
.form-grid input { padding: 8px 10px; border: 1px solid var(--line); border-radius: 8px; font-size: 13px; }
.modal-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 16px; }
</style>
