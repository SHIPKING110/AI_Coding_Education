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
import {
  getParentLLMConfig,
  setParentLLMConfig,
  getParentRerankConfig,
  saveParentRerankConfig,
  deleteParentRerankConfig,
  testParentRerankConfig,
  getParentEmbeddingConfig,
  saveParentEmbeddingConfig,
  deleteParentEmbeddingConfig,
  testParentEmbeddingConfig,
  getParentIndexStatus,
  rebuildParentIndex,
  type ParentLLMConfigOut,
  type ParentEmbeddingConfigOut,
  type ParentIndexStatus,
} from '@/api/parentService'
import {
  deleteSearchConfig,
  getSearchConfig,
  saveSearchConfig,
  testSearchConfig,
  type SearchConfigIn,
  type SearchConfigOut,
} from '@/api/searchConfig'
import { toastApiError, useToastStore } from '@/stores/toast'
import { useAuthStore } from '@/stores/auth'
import { myPermissions } from '@/api/permissions'

const toast = useToastStore()
const auth = useAuthStore()
// 配置项权限：管理员全开；教师按「设置-模型配置」(settings_tab_model) /
// 「全部设置管理」(settings_manage) 权限决定——与管理员看到的配置项保持同步。
const myPerms = ref<Record<string, boolean>>({})
const canManageModel = computed(() => {
  if (auth.user?.role !== 'teacher') return true
  return myPerms.value.settings_tab_model === true || myPerms.value.settings_manage === true
})
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

/* —— 家长客服共享模型（管理员） —— */
const isAdmin = computed(() => auth.user?.role === 'admin')
const parentLlm = ref<ParentLLMConfigOut | null>(null)
const parentLlmSelected = ref<string | null>(null)
const savingParentLlm = ref(false)
const parentRrk = ref<RetrievalConfigOut | null>(null)
const parentRrkForm = ref<RetrievalConfigIn>({ provider: 'remote', base_url: '', api_key: '', model: '', model_path: '', enabled: true })
const showParentRrkForm = ref(false)
const savingParentRrk = ref(false)
const testingParentRrk = ref(false)
const parentRrkTestMsg = ref('')

/* —— 家长客服专属 Embedding（管理员）：独立父索引 —— */
const parentEmb = ref<ParentEmbeddingConfigOut | null>(null)
const parentEmbForm = ref<RetrievalConfigIn>({ provider: 'remote', base_url: '', api_key: '', model: '', model_path: '', enabled: true })
const showParentEmbForm = ref(false)
const savingParentEmb = ref(false)
const testingParentEmb = ref(false)
const parentEmbTestMsg = ref('')
const parentIndex = ref<ParentIndexStatus | null>(null)
const rebuildingParentIndex = ref(false)

async function loadParentConfigs() {
  if (!isAdmin.value) return
  try {
    parentLlm.value = await getParentLLMConfig()
    parentLlmSelected.value = parentLlm.value.config_id
  } catch { /* ignore */ }
  try {
    const cfg = await getParentRerankConfig()
    parentRrk.value = cfg
    parentRrkForm.value = cfg
      ? { provider: cfg.provider, base_url: cfg.base_url, api_key: '', model: cfg.model, model_path: cfg.model_path || '', enabled: cfg.enabled }
      : { provider: 'remote', base_url: '', api_key: '', model: '', model_path: '', enabled: true }
  } catch { /* ignore */ }
  try {
    const cfg = await getParentEmbeddingConfig()
    parentEmb.value = cfg
    parentEmbForm.value = cfg.configured
      ? { provider: cfg.provider, base_url: cfg.base_url, api_key: '', model: cfg.model, model_path: cfg.model_path || '', enabled: cfg.enabled }
      : { provider: 'remote', base_url: '', api_key: '', model: '', model_path: '', enabled: true }
  } catch { /* ignore */ }
  try {
    parentIndex.value = await getParentIndexStatus()
  } catch { /* ignore */ }
}

async function saveParentEmb() {
  if (parentEmbForm.value.provider === 'remote' && (!parentEmbForm.value.base_url.trim() || !parentEmbForm.value.model.trim())) {
    toast.error('接口地址与模型名不能为空')
    return
  }
  if (parentEmbForm.value.provider === 'remote' && !parentEmb.value?.configured && !parentEmbForm.value.api_key.trim()) {
    toast.error('API Key 不能为空')
    return
  }
  savingParentEmb.value = true
  try {
    const r = await saveParentEmbeddingConfig(parentEmbForm.value)
    parentEmb.value = r.item
    toast.success(r.indexing_started ? '已保存，正在后台重建家长索引' : '已保存家长客服专属 Embedding')
    showParentEmbForm.value = false
    await loadParentConfigs()
  } catch (e) {
    toastApiError(e, '保存失败')
  } finally {
    savingParentEmb.value = false
  }
}

async function removeParentEmb() {
  if (!confirm('删除家长客服专属 Embedding？删除后家长端将回退系统级 Embedding 与系统索引。')) return
  try {
    await deleteParentEmbeddingConfig()
    parentEmb.value = null
    toast.success('已删除，已回退系统级 Embedding')
    await loadParentConfigs()
  } catch (e) {
    toastApiError(e, '删除失败')
  }
}

async function testParentEmb() {
  testingParentEmb.value = true
  parentEmbTestMsg.value = ''
  try {
    const r = await testParentEmbeddingConfig()
    parentEmbTestMsg.value = r.ok
      ? `连通正常 · 维度 ${r.dim ?? '-'} · ${r.latency_ms ?? '-'} ms`
      : `连接失败：${r.error || '未知错误'}`
  } catch (e) {
    parentEmbTestMsg.value = `连接失败：${e instanceof Error ? e.message : '未知错误'}`
  } finally {
    testingParentEmb.value = false
  }
}

async function testParentRrk() {
  testingParentRrk.value = true
  parentRrkTestMsg.value = ''
  try {
    const r = await testParentRerankConfig()
    parentRrkTestMsg.value = r.ok
      ? `${r.note || '连通正常'} · ${r.latency_ms ?? '-'} ms`
      : `连接失败：${r.error || '未知错误'}`
  } catch (e) {
    parentRrkTestMsg.value = `连接失败：${e instanceof Error ? e.message : '未知错误'}`
  } finally {
    testingParentRrk.value = false
  }
}

async function rebuildParentIndexNow() {
  rebuildingParentIndex.value = true
  try {
    const r = await rebuildParentIndex()
    parentIndex.value = r
    toast.success(r.started ? '已开始重建家长索引' : '当前无需重建（未启用专属 Embedding）')
    setTimeout(loadParentConfigs, 1200)
  } catch (e) {
    toastApiError(e, '重建失败')
  } finally {
    rebuildingParentIndex.value = false
  }
}

async function saveParentLlm() {
  savingParentLlm.value = true
  try {
    await setParentLLMConfig(parentLlmSelected.value)
    toast.success('已保存家长客服共享对话模型')
    await loadParentConfigs()
  } catch (e) {
    toastApiError(e, '保存失败')
  } finally {
    savingParentLlm.value = false
  }
}

async function saveParentRrk() {
  if (parentRrkForm.value.provider === 'remote' && (!parentRrkForm.value.base_url.trim() || !parentRrkForm.value.model.trim())) {
    toast.error('接口地址与模型名不能为空')
    return
  }
  if (parentRrkForm.value.provider === 'remote' && !parentRrk.value && !parentRrkForm.value.api_key.trim()) {
    toast.error('API Key 不能为空')
    return
  }
  savingParentRrk.value = true
  try {
    parentRrk.value = await saveParentRerankConfig(parentRrkForm.value)
    toast.success('已保存家长客服共享 Rerank')
    showParentRrkForm.value = false
    await loadParentConfigs()
  } catch (e) {
    toastApiError(e, '保存失败')
  } finally {
    savingParentRrk.value = false
  }
}

async function removeParentRrk() {
  if (!confirm('删除家长客服共享 Rerank？删除后家长客服检索退化为单层向量召回。')) return
  try {
    await deleteParentRerankConfig()
    parentRrk.value = null
    toast.success('已删除')
    await loadParentConfigs()
  } catch (e) {
    toastApiError(e, '删除失败')
  }
}

async function loadRetrieval() {
  try {
    if (canManageModel.value) {
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

/* —— 联网搜索：Tavily（系统级，管理员） —— */
const search = ref<SearchConfigOut | null>(null)
const searchForm = ref<SearchConfigIn>({
  base_url: 'https://api.tavily.com',
  api_key: '',
  enabled: true,
  search_depth: 'basic',
  max_results: 5,
  language: 'zh',
})
const showSearchForm = ref(false)
const savingSearch = ref(false)
const testingSearch = ref(false)
const searchTestMsg = ref('')

async function loadSearch() {
  try {
    search.value = await getSearchConfig()
    searchForm.value = search.value
      ? {
          base_url: search.value.base_url,
          api_key: '',
          enabled: search.value.enabled,
          search_depth: search.value.search_depth,
          max_results: search.value.max_results,
          language: search.value.language,
        }
      : { base_url: 'https://api.tavily.com', api_key: '', enabled: true, search_depth: 'basic', max_results: 5, language: 'zh' }
  } catch {
    // 联网搜索为可选增强，读取失败不阻塞模型配置页
  }
}

async function saveSearch() {
  if (!search.value && !searchForm.value.api_key.trim()) {
    toast.error('首次配置需填写 Tavily API Key')
    return
  }
  savingSearch.value = true
  try {
    search.value = await saveSearchConfig(searchForm.value)
    toast.success('已保存联网搜索配置')
    showSearchForm.value = false
    await loadSearch()
  } catch (e) {
    toastApiError(e, '保存失败')
  } finally {
    savingSearch.value = false
  }
}

async function removeSearch() {
  if (!confirm('删除联网搜索配置？删除后 Agent 将无法联网检索（内部数据与知识库问答不受影响）。')) return
  try {
    await deleteSearchConfig()
    search.value = null
    toast.success('已删除')
    await loadSearch()
  } catch (e) {
    toastApiError(e, '删除失败')
  }
}

async function checkSearch() {
  testingSearch.value = true
  searchTestMsg.value = ''
  try {
    const r = await testSearchConfig()
    searchTestMsg.value = r.ok ? `连通正常（${r.latency_ms}ms · 命中 ${r.count} 条）` : `✗ ${r.error || '连通失败'}`
  } catch (e) {
    searchTestMsg.value = '✗ 请求失败，请稍后重试'
    toastApiError(e, '检查失败')
  } finally {
    testingSearch.value = false
  }
}

onMounted(async () => {
  if (auth.user?.role === 'teacher') {
    try {
      myPerms.value = await myPermissions()
    } catch {
      myPerms.value = {}
    }
  }
  load()
  void loadRetrieval()
  void loadSearch()
  if (auth.user?.role === 'admin') void loadParentConfigs()
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
      <p class="muted">不选 = 用上面的默认配置。Agent 工作台还可在对话时临时切换。家长客服已从本模块映射中移出，统一在下方「家长客服 · 共享模型」由管理员配置（全校共用，不随教师变化）；家长只能看到后台勾选为「家长可见」的文档。</p>
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

    <!-- 检索 · Embedding（系统级：管理员 / 有模型配置权限的教师） -->
    <section v-if="canManageModel" class="card">
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

    <!-- 家长客服共享模型（管理员） -->
    <section v-if="isAdmin" class="card">
      <div class="card-head">
        <div>
          <h2>家长客服 · 共享模型（管理员）</h2>
          <p class="muted">
            家长端客服 Agent 的对话模型、Embedding、Rerank 独立配置，全校共用，不与教师端混用。
            <strong>Embedding 建议单独配置</strong>：家长域使用独立集合 parent_knowledge__指纹，只索引「家长可见」文档，互不干扰；
            未配置时自动回退系统级 Embedding 与系统索引（仍可正常问答）。
          </p>
        </div>
      </div>
      <div class="cfg-row" style="margin-bottom:10px">
        <div class="cfg-main">
          <div class="cfg-head">
            <strong>Embedding（家长域向量）</strong>
            <span v-if="parentEmb?.configured" class="def-tag">专属</span>
          </div>
          <div class="cfg-meta" v-if="parentEmb?.configured">
            {{ parentEmb.model }} ·
            {{ parentEmb.provider === 'local' ? `本地模型 · ${parentEmb.model_path || '未设路径'}` : parentEmb.base_url }} ·
            {{ parentEmb.enabled ? '启用' : '停用' }}
          </div>
          <div class="cfg-meta" v-else>未配置：回退系统级 Embedding 与系统索引（家长端仍可用）</div>
          <div v-if="parentEmbTestMsg" class="test-line">{{ parentEmbTestMsg }}</div>
          <div class="cfg-meta" v-if="parentIndex">
            家长可见文档 {{ parentIndex.documents }} 篇 · 已索引 {{ parentIndex.indexed }} 篇
            <span v-if="parentIndex.dedicated">（独立集合 {{ parentIndex.collection }}）</span>
            <span v-else>（复用系统索引）</span>
            <span v-if="parentIndex.pending > 0"> · 待同步 {{ parentIndex.pending }} 篇</span>
            <span v-if="parentIndex.running"> · 后台重建中…</span>
          </div>
        </div>
        <div class="cfg-actions">
          <button v-if="parentEmb?.configured" class="link-btn" :disabled="testingParentEmb" @click="testParentEmb">{{ testingParentEmb ? '检查中…' : '检查' }}</button>
          <button v-if="parentEmb?.configured" class="link-btn" @click="showParentEmbForm = true">编辑</button>
          <button v-else class="btn primary sm" @click="showParentEmbForm = true">配置 Embedding</button>
          <button v-if="parentEmb?.configured" class="link-btn" :disabled="rebuildingParentIndex || !parentIndex?.dedicated" @click="rebuildParentIndexNow">{{ rebuildingParentIndex ? '重建中…' : '重建索引' }}</button>
          <button v-if="parentEmb?.configured" class="link-btn danger" @click="removeParentEmb">删除</button>
        </div>
      </div>
      <div class="cfg-row" style="margin-bottom:10px">
        <div class="cfg-main">
          <div class="cfg-head"><strong>对话模型</strong></div>
          <div class="cfg-meta">当前：{{ parentLlm?.resolved_name || '未配置（回退系统默认）' }} · {{ parentLlm?.resolved_model || '' }}</div>
        </div>
        <div class="cfg-actions">
          <select v-model="parentLlmSelected" class="filter-select">
            <option :value="null">系统默认</option>
            <option v-for="c in items" :key="c.id" :value="c.id">{{ c.name }}（{{ c.model }}）</option>
          </select>
          <button class="btn primary sm" :disabled="savingParentLlm" @click="saveParentLlm">{{ savingParentLlm ? '保存中…' : '保存' }}</button>
        </div>
      </div>
      <div class="cfg-row">
        <div class="cfg-main">
          <div class="cfg-head"><strong>Rerank（可选）</strong></div>
          <div class="cfg-meta" v-if="parentRrk">{{ parentRrk.model }} · {{ parentRrk.base_url }} · {{ parentRrk.enabled ? '启用' : '停用' }}</div>
          <div class="cfg-meta" v-else>未配置：家长客服检索退化为单层向量召回</div>
          <div v-if="parentRrkTestMsg" class="test-line">{{ parentRrkTestMsg }}</div>
        </div>
        <div class="cfg-actions">
          <button v-if="parentRrk" class="link-btn" :disabled="testingParentRrk" @click="testParentRrk">{{ testingParentRrk ? '检查中…' : '检查' }}</button>
          <button v-if="parentRrk" class="link-btn" @click="showParentRrkForm = true">编辑</button>
          <button v-else class="btn primary sm" @click="showParentRrkForm = true">配置 Rerank</button>
          <button v-if="parentRrk" class="link-btn danger" @click="removeParentRrk">删除</button>
        </div>
      </div>
    </section>

    <!-- 联网搜索 · Tavily（系统级：管理员 / 有模型配置权限的教师） -->
    <section v-if="canManageModel" class="card">
      <div class="card-head">
        <div>
          <h2>联网搜索 · Tavily（系统级）</h2>
          <p class="muted">
            让 Agent 在需要<strong>外部公开信息</strong>时联网检索（行业动态、竞品做法、公开资料、最新政策等）。
            全校共用一套 Key。<strong>边界</strong>：联网结果只作外部事实补充，
            本校的学员/课时/排课/收费/退费/请假政策一律以内部数据与知识库为准；
            未配置即不联网（内部数据与知识库问答完全不受影响）。
          </p>
        </div>
        <div class="cfg-actions">
          <button v-if="search" class="link-btn" :disabled="testingSearch" @click="checkSearch">{{ testingSearch ? '检查中…' : '检查' }}</button>
          <button v-if="search" class="link-btn" @click="showSearchForm = true">编辑</button>
          <button v-else class="btn primary sm" @click="showSearchForm = true">配置联网搜索</button>
          <button v-if="search" class="link-btn danger" @click="removeSearch">删除</button>
        </div>
      </div>
      <div v-if="search" class="cfg-row def">
        <div class="cfg-main">
          <div class="cfg-head"><strong>Tavily Search</strong></div>
          <div class="cfg-meta">
            {{ search.base_url }} · {{ search.search_depth === 'advanced' ? '深度（2 credits/次）' : '基础（1 credit/次）' }}
            · 每次最多 {{ search.max_results }} 条 · 语言 {{ search.language || '不限' }}
            · {{ search.enabled ? '启用' : '停用' }}
          </div>
          <div v-if="searchTestMsg" class="test-line">{{ searchTestMsg }}</div>
        </div>
      </div>
      <div v-else class="empty-tip">未配置联网搜索：Agent 不会联网检索（内部数据与知识库问答不受影响）。</div>
    </section>

    <div v-if="showSearchForm" class="overlay" @click.self="showSearchForm = false">
      <div class="modal">
        <h2>{{ search ? '编辑联网搜索配置' : '配置联网搜索（Tavily）' }}</h2>
        <p class="muted" style="margin-bottom: 12px">
          在 <a href="https://app.tavily.com" target="_blank" rel="noopener">app.tavily.com</a> 申请 API Key（形如 <code>tvly-…</code>），粘贴到下方即可启用。
        </p>
        <div class="form-grid">
          <label>接口地址<input v-model="searchForm.base_url" placeholder="https://api.tavily.com" /></label>
          <label>API Key<input v-model="searchForm.api_key" type="password" :placeholder="search ? '留空则不修改' : 'tvly-…'" /></label>
          <label>搜索深度
            <select v-model="searchForm.search_depth">
              <option value="basic">基础（快，1 credit/次）</option>
              <option value="advanced">深度（准，2 credit/次）</option>
              <option value="fast">快速（1 credit/次）</option>
            </select>
          </label>
          <label>每次最多返回条数<input v-model.number="searchForm.max_results" type="number" min="1" max="20" step="1" /></label>
          <label>语言偏好（ISO 639-1，可留空）<input v-model="searchForm.language" placeholder="zh / en" /></label>
          <label class="check"><input v-model="searchForm.enabled" type="checkbox" /> 启用联网搜索</label>
        </div>
        <div class="modal-actions">
          <button class="btn ghost" @click="showSearchForm = false">取消</button>
          <button class="btn primary" :disabled="savingSearch" @click="saveSearch">{{ savingSearch ? '保存中…' : '保存' }}</button>
        </div>
      </div>
    </div>

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
    <!-- 家长客服共享 Rerank 编辑 -->
    <div v-if="showParentRrkForm" class="overlay" @click.self="showParentRrkForm = false">
      <div class="modal">
        <h2>{{ parentRrk ? '编辑家长客服共享 Rerank' : '配置家长客服共享 Rerank' }}</h2>
        <div class="form-grid">
          <label class="check"><input v-model="parentRrkForm.provider" type="radio" value="remote" /> 云端 API</label>
          <label class="check"><input v-model="parentRrkForm.provider" type="radio" value="local" /> 本地模型（预留）</label>
          <template v-if="parentRrkForm.provider === 'remote'">
            <label class="span2">接口地址<input v-model="parentRrkForm.base_url" placeholder="https://api.siliconflow.cn" /></label>
            <label class="span2">API Key<input v-model="parentRrkForm.api_key" :type="parentRrkForm.api_key ? 'text' : 'password'" :placeholder="parentRrk ? '留空则不修改' : 'sk-…'" /></label>
            <label class="span2">Rerank 模型名<input v-model="parentRrkForm.model" placeholder="如 BAAI/bge-reranker-v2-m3" /></label>
          </template>
          <template v-else>
            <label class="span2">本地模型路径<input v-model="parentRrkForm.model_path" placeholder="如 /srv/app/models/bge-reranker-v2-m3" /></label>
            <label class="span2">模型名（标识）<input v-model="parentRrkForm.model" placeholder="如 bge-reranker-local" /></label>
          </template>
          <label class="check"><input v-model="parentRrkForm.enabled" type="checkbox" /> 启用</label>
        </div>
        <div class="modal-actions">
          <button class="btn ghost" @click="showParentRrkForm = false">取消</button>
          <button class="btn primary" :disabled="savingParentRrk" @click="saveParentRrk">{{ savingParentRrk ? '保存中…' : '保存' }}</button>
        </div>
      </div>
    </div>

    <!-- 家长客服专属 Embedding 编辑 -->
    <div v-if="showParentEmbForm" class="overlay" @click.self="showParentEmbForm = false">
      <div class="modal">
        <h2>{{ parentEmb?.configured ? '编辑家长客服专属 Embedding' : '配置家长客服专属 Embedding' }}</h2>
        <p class="muted">
          保存后家长域改用独立集合，只索引「家长可见」文档；后台会自动重建家长索引。
          未配置则回退系统级 Embedding 与系统索引。
        </p>
        <div class="form-grid">
          <label class="check"><input v-model="parentEmbForm.provider" type="radio" value="remote" /> 云端 API</label>
          <label class="check"><input v-model="parentEmbForm.provider" type="radio" value="local" /> 本地模型（预留）</label>
          <template v-if="parentEmbForm.provider === 'remote'">
            <label class="span2">接口地址<input v-model="parentEmbForm.base_url" placeholder="https://api.siliconflow.cn" /></label>
            <label class="span2">API Key<input v-model="parentEmbForm.api_key" :type="parentEmbForm.api_key ? 'text' : 'password'" :placeholder="parentEmb?.configured ? '留空则不修改' : 'sk-…'" /></label>
            <label class="span2">Embedding 模型名<input v-model="parentEmbForm.model" placeholder="如 BAAI/bge-m3" /></label>
          </template>
          <template v-else>
            <label class="span2">本地模型路径<input v-model="parentEmbForm.model_path" placeholder="如 /srv/app/models/bge-m3" /></label>
            <label class="span2">模型名（标识）<input v-model="parentEmbForm.model" placeholder="如 bge-m3-local" /></label>
          </template>
          <label class="check"><input v-model="parentEmbForm.enabled" type="checkbox" /> 启用</label>
        </div>
        <div class="modal-actions">
          <button class="btn ghost" @click="showParentEmbForm = false">取消</button>
          <button class="btn primary" :disabled="savingParentEmb" @click="saveParentEmb">{{ savingParentEmb ? '保存中…' : '保存' }}</button>
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
