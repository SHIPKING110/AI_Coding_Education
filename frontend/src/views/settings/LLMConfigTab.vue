<script setup lang="ts">
import { onMounted, ref } from 'vue'

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
import { toastApiError, useToastStore } from '@/stores/toast'

const toast = useToastStore()
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
  embed_model: '',
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
  form.value = { name: '', base_url: '', api_key: '', model: '', embed_model: '', make_default: items.value.length === 0 }
  showForm.value = true
}

function openEdit(c: LLMConfigOut) {
  editing.value = c
  form.value = { name: c.name, base_url: c.base_url, api_key: '', model: c.model, embed_model: c.embed_model || '', make_default: c.is_default }
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
        embed_model: form.value.embed_model || null,
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

onMounted(load)
</script>

<template>
  <div class="llm-tab">
    <section class="card">
      <div class="card-head">
        <div>
          <h2>我的模型配置</h2>
          <p class="muted">每人可配多个（接口地址 + API Key + 模型名）。Key 落库加密、只显示掩码；下方按模块选用。</p>
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
            <div class="cfg-meta">{{ c.base_url }} · 模型 {{ c.model }}<span v-if="c.embed_model"> · embedding {{ c.embed_model }}</span></div>
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
      <p class="muted">不选 = 用上面的默认配置。Agent 工作台还可在对话时临时切换。</p>
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

    <div v-if="showForm" class="overlay" @click.self="showForm = false">
      <div class="modal">
        <h2>{{ editing ? '编辑模型配置' : '添加模型配置' }}</h2>
        <div class="form-grid">
          <label>配置名称<input v-model="form.name" placeholder="如：deepseek-主" /></label>
          <label>接口地址（OpenAI 兼容）<input v-model="form.base_url" placeholder="https://api.deepseek.com" /></label>
          <label>API Key<input v-model="form.api_key" :type="form.showKey ? 'text' : 'password'" :placeholder="editing ? '留空则不修改' : 'sk-…'" /></label>
          <label>模型名称<input v-model="form.model" placeholder="如：deepseek-chat" /></label>
          <label class="span2">Embedding 模型（可选，用于知识库检索；DeepSeek 无 embedding 接口，需另配如硅基流动/Zhipu）
            <input v-model="form.embed_model" placeholder="留空则知识库检索不可用" />
          </label>
          <label class="check"><input v-model="form.make_default" type="checkbox" /> 设为默认配置</label>
          <label class="check"><input v-model="form.showKey" type="checkbox" /> 显示 Key 明文</label>
        </div>
        <div class="modal-actions">
          <button class="btn ghost" @click="showForm = false">取消</button>
          <button class="btn primary" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存' }}</button>
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
